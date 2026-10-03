"""prep_database.py — LLM-assisted schema preparation for a merged SQLite DB.

Takes a merged SQLite database (the union of one or more source DBs) plus an
optional workload history CSV of question/SQL pairs, and produces a single
consolidated prep JSON that downstream NL2SQL baselines consume. Each phase is
optional and gated by its own flag, so a typical run mixes-and-matches:

  --rename    rename every base table to a view (LLM CREATE VIEW per table) and
              rewrite the history SQLs to use the renamed views.
  --cluster   mine frequent table-set clusters from the history CSV (pure
              computation — no LLM calls).
  --view      build one cluster-view per cluster (LLM with code-based FK
              fallback) and view-aware-rewrite the history SQLs to use them.

The phases compose: ``--rename --cluster --view`` runs the full pipeline.

Pipeline phases:

  1. Backup the input sqlite to ``<db>.bak.<timestamp>``.
  2. (--rename) LLM call: one CREATE VIEW per base table. Cached to disk.
  3. (--rename) Apply CREATE VIEWs with column-count verification. Failed
     tables are re-prompted up to ``--max_retries`` times; persistent failures
     fall back to identity (no view, original name preserved in the mapping).
  4. (--rename) Write the rename mapping into the consolidated prep JSON.
  5. (--rename + history) Rewrite each history SQL against the renamed views,
     verified by execution against the gold SQL. Failed rows fall back to the
     original SQL with ``result=0``.
  6. (--cluster or --view) Mine frequent table-set clusters from history.
     Saved into the prep JSON only when ``--cluster`` is set.
  7. (--view) Build one CREATE VIEW per cluster that joins its tables on FKs.
     LLM first, then a code-based FK-walker fallback.
  8. (--view + history) Rewrite each history SQL to use a cluster view where
     the question's tables match a cluster, falling back to renamed tables
     otherwise. Same execution-verification + retry loop as step 5.

Output:
  One JSON file at ``--output_mapping_path`` (default:
  ``<LDD>/mapping_files/prep_<dataset>[_renamed].json``) with these top-level
  sections, present only if the corresponding phase ran:

    - ``metadata``  - dataset stem, flags set, build timestamp
    - ``tables``    - active table list (renamed views when --rename, else originals)
    - ``columns``   - history-CSV column names used during the prep run
    - ``rename``    - {table_to_view, column_mapping}
    - ``cluster``   - {exact_clusters, question_cluster_map, params}
    - ``view``      - {cluster_views, skipped_clusters, counts}

  All cached prompts + raw LLM responses also land under
  ``<LDD>/outputs/prep_database/<timestamp>/`` for auditability.

Iteration flags (rename only):

  --dry_run      build the prompt and cache it; skip the LLM call.
  --cache_only   stop after caching the initial LLM response.
  --from_cache F load a previously-cached response from F and run only the
                 apply + mapping + history-rewrite phases.

See ``--help`` for the full flag set and ``benchmarks/PREP_DATABASE.md`` for
example invocations.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from collections import Counter
from typing import List, Optional, Sequence

import pandas as pd

# Allow importing from sibling _common/
_BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
if _BENCH_DIR not in sys.path:
    sys.path.insert(0, _BENCH_DIR)

from func_timeout import FunctionTimedOut, func_set_timeout  # noqa: E402

from _common.llm import (  # noqa: E402
    chat_with_chatgpt,
    chat_with_gemini,
    ensure_gemini,
    ensure_openai,
)
from _common.parsers import extract_json_block  # noqa: E402
from _common.paths import LDD_ROOT  # noqa: E402
from _common.schema import generate_schema_prompt  # noqa: E402


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """You are a database expert. Your task is to rename the tables and columns of a SQLite database by writing one `CREATE VIEW` per base table, in order to improve a downstream NL2SQL pipeline's execution accuracy on a known workload.

The database is a UNION of multiple source databases merged into one sqlite file. You will see ALL base tables together.

# Your goals
1. For EACH of the {n_tables} base tables listed below, produce exactly ONE `CREATE VIEW` statement that is 1:1 with the base table:
   - same rows (no filters, no DISTINCT, no aggregation)
   - every column present in the base table appears in the view, in the same order
   - the table name is rewritten, and every column name is rewritten via `AS`
2. Choose new names that:
   a. More descriptively reflect what the table/column actually represents (so the NL2SQL LLM can match natural-language phrasing).
   b. Use the workload history to drive name *proximity*: tables that frequently co-occur in the same SQL statement should get semantically tight names (shared vocabulary, related theme) so the downstream LLM treats them as a unit. Tables that NEVER co-occur should get visibly distant names so the downstream LLM is less likely to wrongly pull one in when the other is needed. Short generic names like `account`, `card`, `users`, `order`, `posts` are bad because they're easy to confuse across source DBs — prefer something more specific that signals which workload neighborhood the table lives in.
   c. Tables you believe come from different source databases should NOT share naming vocabulary.
3. {history_signal}

# Hard constraints (violations make the output unusable)
- The output MUST contain exactly {n_tables} `base_table` entries total — one per base table, no more, no less. Before responding, count your entries: if the count is not {n_tables}, fix the output (you most likely listed some base tables twice — remove the duplicates).
- Each base table name from the list below must appear as a `base_table` value EXACTLY ONCE. Do not emit two `CREATE VIEW` statements for the same base table even if you change your mind about the name.
- Every column in the base table must appear in the view with a `AS` rename — no drops, no additions, no reordering.
- Each `CREATE VIEW` must be valid SQLite and executable as-is against the schema below.
- View names and column names must be unique across the entire database.
- Wrap every identifier (view name, column names, base table name) in backticks.
- Do NOT include `IF NOT EXISTS`, comments, semicolon-terminated multi-statement blocks, or any text outside the `CREATE VIEW ... AS SELECT ... FROM ...` body.

# Base tables you must rename ({n_tables} total)
{base_table_checklist}

# Current schema (CREATE TABLE statements + {num_rows} sample rows per table)
###
{schema}
###
{history_block}
# Output

Respond with a single JSON object. The `clusters` array groups tables you believe come from the same source database — group them by their original source DB, not alphabetically. Each `tables` entry has exactly TWO fields: `base_table` (the exact original name) and `create_view_sql` (the full executable CREATE VIEW string).

{{
  "chain_of_thought_reasoning": "1-3 sentences on how you identified source databases (from history + schema cues) and your naming conventions.",
  "clusters": [
    {{
      "rationale": "One short sentence describing the source database this cluster represents.",
      "tables": [
        {{
          "base_table": "<exact original base table name>",
          "create_view_sql": "CREATE VIEW `<new_view_name>` AS SELECT `<orig_col_1>` AS `<new_col_1>`, `<orig_col_2>` AS `<new_col_2>`, ... FROM `<original_base_table>`"
        }}
      ]
    }}
  ]
}}
"""

_HISTORY_INSTRUCTION_ON = (
    "A workload history of question -> SQL pairs is provided below. Tables that appear together in the SAME "
    "SQL statement are DEFINITELY from the same source database — use this as a hard clustering signal."
)
_HISTORY_INSTRUCTION_OFF = (
    "No workload history is provided. Infer source-database clusters from table names, column names, "
    "and the sample rows alone."
)

_HISTORY_BLOCK_TEMPLATE = (
    "\n# Workload history (one entry per row: `<index> <question>` then the SQL, separated by `---------------`)\n"
    "###\n{history}\n###\n"
)


REWRITE_PROMPT_TEMPLATE = """You are a database expert. You have just renamed every base table in a SQLite database to a view, using the mapping below. Now rewrite each (question, original SQL) pair so the new SQL uses the renamed views and renamed columns instead of the original base tables.

# Rename mapping (bird-style: column dict is {{original_col: renamed_col}} per view)
###
{mapping_json}
###

# Hard constraints
- Use ONLY the renamed views listed in `table_to_view` above. NEVER reference the original base tables.
- Use the renamed column names (look them up via `column_mapping`).
- The rewritten SQL must return the SAME result set as the original SQL.
- Do not add LIMIT, ORDER BY, or DISTINCT that wasn't in the original.
- If the original used a table alias (e.g. `T1`), feel free to keep aliases — but the FROM/JOIN must point at a renamed view, not an original table.

# Workload to rewrite ({n_rows} row(s); each is labelled `index : <n>`)
###
{workload}
###

# Output

Respond with a single JSON object. The `rewrites` array must contain exactly {n_rows} entries, one per row above, in order, each carrying that row's own `index` as listed.

{{
  "rewrites": [
    {{"index": <the row's index>, "renamed_sql": "<rewritten SQL using renamed views + renamed columns>"}},
    {{"index": <the next row's index>, "renamed_sql": "..."}}
  ]
}}
"""


REWRITE_RETRY_PROMPT_TEMPLATE = """You are a database expert. Your previous attempt to rewrite {n_failed} SQL(s) failed for the reasons listed below. Rewrite ONLY these rows again, fixing the issues.

# Rename mapping (same as before)
###
{mapping_json}
###

# Why each row failed
{failure_summary}

# Hard constraints (same as before — re-read carefully)
- Use ONLY the renamed views listed in `table_to_view`. NEVER reference the original base tables.
- Use the renamed column names (look them up via `column_mapping`).
- The rewritten SQL must return the SAME result set as the original.

# Rows to rewrite ({n_failed} row(s))
###
{workload}
###

# Output

Respond with the same JSON shape — but only include entries for the {n_failed} indices above:

{{
  "rewrites": [
    {{"index": <one of the indices above>, "renamed_sql": "..."}}
  ]
}}
"""


RETRY_PROMPT_TEMPLATE = """You are a database expert. Your previous attempt to rename {n_failed} table(s) failed for the reasons listed below. Generate NEW `CREATE VIEW` statements for these tables ONLY, fixing the issues.

# Why each table failed
{failure_summary}

# Hard constraints (same as before — pay extra attention to these now)
- Each `CREATE VIEW` must be 1:1 with its base table:
  * same rows (no filters, no DISTINCT, no aggregation, no GROUP BY)
  * every column in the base table appears in the view, in the same order, with an `AS` rename
  * no columns dropped, no columns added
- Each `CREATE VIEW` must be valid SQLite and executable as-is against the schema below.
- View names and column names must be unique within the database.
- Wrap every identifier in backticks.
- Do NOT use `SELECT *` — list every column explicitly with `AS`.
- Do NOT include `IF NOT EXISTS`, comments, or any text outside the `CREATE VIEW ... AS SELECT ... FROM ...` body.

# Tables to re-rename ({n_failed} total)
{checklist}

# Schema for these tables (CREATE TABLE statements + {num_rows} sample rows)
###
{schema}
###
{history_block}
# Output

Respond with the same JSON shape as before:

{{
  "chain_of_thought_reasoning": "Brief note on what you changed to address the failures.",
  "clusters": [
    {{
      "rationale": "One short sentence — group by source database.",
      "tables": [
        {{
          "base_table": "<exact original base table name>",
          "create_view_sql": "CREATE VIEW `<new_view_name>` AS SELECT `<orig_col>` AS `<new_col>`, ... FROM `<original_base_table>`"
        }}
      ]
    }}
  ]
}}

Only include the {n_failed} table(s) listed above. Do not retry any other tables.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def list_base_tables(db_path: str) -> List[str]:
    """Return the names of all user-defined TABLES (excluding views and sqlite_*)."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name;"
    )
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def existing_views(db_path: str) -> List[str]:
    """Return the names of any existing views in the DB (from a prior run, perhaps)."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name;")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def format_history(
    history_path: str,
    question_col: str = "question",
    sql_col: str = "SQL",
) -> str:
    """Format the history CSV as ``"{index} {question}\\n{SQL}\\n---------------"`` per row."""
    df = pd.read_csv(history_path)
    for col in (question_col, sql_col):
        if col not in df.columns:
            raise SystemExit(
                f"history CSV {history_path} is missing required column {col!r}. "
                f"Available columns: {list(df.columns)}"
            )
    parts = []
    for i, row in df.iterrows():
        parts.append(f"{i} {row[question_col]}\n{row[sql_col]}\n---------------")
    return "\n".join(parts)


def backup_database(db_path: str) -> str:
    """Copy ``db_path`` to ``<db_path>.bak.<timestamp>``; return the backup path."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{db_path}.bak.{ts}"
    shutil.copy2(db_path, bak)
    print(f"[prep_database] backup written to {bak}")
    return bak


def _stem_short(db_path: str) -> str:
    """Return the dataset-like stem of ``db_path``: ``merged_spider.sqlite`` -> ``spider``."""
    stem = os.path.splitext(os.path.basename(db_path))[0]
    return stem[len("merged_"):] if stem.startswith("merged_") else stem


# ---------------------------------------------------------------------------
# View materialization + verification
# ---------------------------------------------------------------------------

def _column_count(db_path: str, name: str) -> int:
    """Return the number of columns in ``name`` (table or view) via PRAGMA."""
    conn = sqlite3.connect(db_path)
    try:
        return len(conn.execute(f'PRAGMA table_info("{name}")').fetchall())
    finally:
        conn.close()


def _column_names(db_path: str, name: str) -> List[str]:
    """Return the column names of ``name`` (table or view) via PRAGMA, in order."""
    conn = sqlite3.connect(db_path)
    try:
        return [row[1] for row in conn.execute(f'PRAGMA table_info("{name}")').fetchall()]
    finally:
        conn.close()


def _drop_view_if_exists(db_path: str, view_name: str) -> None:
    """Drop ``view_name`` (if it exists). Does NOT drop tables."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f'DROP VIEW IF EXISTS "{view_name}"')
        conn.commit()
    finally:
        conn.close()


def _execute_view_sql(db_path: str, sql: str) -> None:
    """Execute a single ``CREATE VIEW`` statement against the DB."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _drop_all_views(db_path: str) -> List[str]:
    """Drop every view in the DB. Returns the list of dropped view names."""
    names = []
    conn = sqlite3.connect(db_path)
    try:
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall():
            view_name = row[0]
            conn.execute(f'DROP VIEW IF EXISTS "{view_name}"')
            names.append(view_name)
        conn.commit()
    finally:
        conn.close()
    return names


# ---------------------------------------------------------------------------
# CREATE VIEW parsing (sqlglot)
# ---------------------------------------------------------------------------

def _extract_view_name(create_view_sql: str) -> str:
    """Extract just the view's identifier from a CREATE VIEW SQL string."""
    import sqlglot
    from sqlglot import expressions as exp

    parsed = sqlglot.parse_one(create_view_sql, read="sqlite")
    if not isinstance(parsed, exp.Create):
        raise ValueError(f"not a CREATE statement: {create_view_sql[:200]!r}")
    if (parsed.args.get("kind") or "").upper() != "VIEW":
        raise ValueError(f"not a CREATE VIEW: {create_view_sql[:200]!r}")
    target = parsed.this
    # ``parsed.this`` is the Table being created; ``.name`` is its identifier
    if hasattr(target, "name") and target.name:
        return target.name
    if hasattr(target, "this") and hasattr(target.this, "name"):
        return target.this.name
    raise ValueError(f"could not extract view name from: {create_view_sql[:200]!r}")


def _extract_view_name_and_columns(
    create_view_sql: str,
) -> tuple[str, List[tuple[str, str]]]:
    """Return ``(view_name, [(original_col, renamed_col), ...])`` in source order."""
    import sqlglot
    from sqlglot import expressions as exp

    parsed = sqlglot.parse_one(create_view_sql, read="sqlite")
    if not isinstance(parsed, exp.Create):
        raise ValueError(f"not a CREATE statement")
    if (parsed.args.get("kind") or "").upper() != "VIEW":
        raise ValueError(f"not a CREATE VIEW")

    target = parsed.this
    view_name = (
        target.name if hasattr(target, "name") and target.name
        else target.this.name
    )

    select = parsed.expression
    if not isinstance(select, exp.Select):
        raise ValueError(f"CREATE VIEW body is not a SELECT")

    pairs: List[tuple[str, str]] = []
    for projection in select.expressions:
        if isinstance(projection, exp.Alias):
            inner = projection.this
            if isinstance(inner, exp.Column):
                orig = inner.name
            else:
                orig = inner.sql(dialect="sqlite")
            new = projection.alias
            pairs.append((orig, new))
        elif isinstance(projection, exp.Column):
            pairs.append((projection.name, projection.name))
        elif isinstance(projection, exp.Star):
            raise ValueError("uses SELECT * — cannot extract column mapping")
        else:
            # An expression without alias (e.g. CAST(x AS INTEGER)) — unusual for rename
            raise ValueError(
                f"unsupported projection type {type(projection).__name__}: "
                f"{projection.sql(dialect='sqlite')[:120]}"
            )
    return view_name, pairs


# ---------------------------------------------------------------------------
# Apply phase
# ---------------------------------------------------------------------------

def _flatten_clusters(
    parsed: dict,
    allowed_base_tables: List[str],
) -> dict[str, tuple[str, str]]:
    """Flatten ``parsed['clusters']`` into ``{base_table: (view_name, create_view_sql)}``.

    Filters out:
      - entries whose ``base_table`` is not in ``allowed_base_tables`` (LLM hallucinations)
      - entries whose CREATE VIEW SQL cannot be parsed for a view name
    Case-insensitively matches ``base_table`` to canonical names.
    """
    canonical = {t.lower(): t for t in allowed_base_tables}
    out: dict[str, tuple[str, str]] = {}
    for cluster in parsed.get("clusters", []):
        for entry in cluster.get("tables", []):
            base = entry.get("base_table")
            sql = entry.get("create_view_sql")
            if not base or not sql:
                continue
            canon = canonical.get(str(base).lower())
            if canon is None:
                continue  # hallucinated table name
            try:
                view_name = _extract_view_name(sql)
            except Exception as e:
                print(f"   ⚠️  could not extract view name for base {base!r}: {e}")
                continue
            out[canon] = (view_name, sql)
    return out


def _apply_views_once(
    db_path: str,
    candidates: dict[str, tuple[str, str]],
    base_col_counts: dict[str, int],
    reserved_view_names: set,
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Try to apply each candidate view exactly once.

    Returns ``(success, failures)`` where:
      - ``success[base] = (view_name, sql)`` for views that materialized AND have
        a matching column count
      - ``failures[base] = "<reason>"`` for everything else
    """
    success: dict[str, tuple[str, str]] = {}
    failures: dict[str, str] = {}
    used_in_round: set = set()
    base_table_names_lower = {t.lower() for t in base_col_counts}

    for base in sorted(candidates):
        view_name, sql = candidates[base]

        # Name-collision guards
        if view_name.lower() in {n.lower() for n in reserved_view_names}:
            failures[base] = (
                f"view name {view_name!r} already in use by another successful rename"
            )
            continue
        if view_name in used_in_round:
            failures[base] = f"view name {view_name!r} duplicated within this batch"
            continue
        if view_name.lower() in base_table_names_lower:
            failures[base] = (
                f"view name {view_name!r} collides with an existing base table"
            )
            continue

        # Drop any pre-existing view with this name (e.g. left from a prior attempt)
        try:
            _drop_view_if_exists(db_path, view_name)
        except Exception as e:
            failures[base] = f"DROP VIEW {view_name!r} failed: {type(e).__name__}: {e}"
            continue

        # Execute the CREATE VIEW
        try:
            _execute_view_sql(db_path, sql)
        except Exception as e:
            failures[base] = f"CREATE VIEW failed: {type(e).__name__}: {e}"
            continue

        # Verify column count
        try:
            view_col_count = _column_count(db_path, view_name)
        except Exception as e:
            _drop_view_if_exists(db_path, view_name)
            failures[base] = f"PRAGMA on new view failed: {type(e).__name__}: {e}"
            continue

        expected = base_col_counts[base]
        if view_col_count != expected:
            _drop_view_if_exists(db_path, view_name)
            failures[base] = (
                f"column count mismatch: base={expected}, view={view_col_count}"
            )
            continue

        success[base] = (view_name, sql)
        used_in_round.add(view_name)

    return success, failures


def _call_llm_subset(
    args: argparse.Namespace,
    failed_tables: List[str],
    failure_reasons: dict[str, str],
    history_block: str,
    cache_dir: str,
    stem: str,
    attempt: int,
) -> dict:
    """Re-prompt the LLM for ``failed_tables`` only. Caches prompt + raw response."""
    schema_pieces = [
        generate_schema_prompt(
            db_path=args.db_path, num_rows=args.num_rows,
            no_join=False, target_table=t,
        )
        for t in failed_tables
    ]
    schema = "\n\n".join(schema_pieces)

    failure_summary = "\n".join(
        f"  - `{base}`: {reason}" for base, reason in failure_reasons.items()
    )
    checklist = "\n".join(f"  - {t}" for t in failed_tables)

    prompt = RETRY_PROMPT_TEMPLATE.format(
        n_failed=len(failed_tables),
        num_rows=args.num_rows,
        failure_summary=failure_summary,
        checklist=checklist,
        schema=schema,
        history_block=history_block,
    )

    ts = time.strftime("%Y%m%d-%H%M%S")
    prompt_path = os.path.join(cache_dir, f"{stem}_{ts}.retry{attempt}.prompt.txt")
    raw_path = os.path.join(cache_dir, f"{stem}_{ts}.retry{attempt}.raw.txt")
    response_path = os.path.join(cache_dir, f"{stem}_{ts}.retry{attempt}.response.json")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    is_gemini = args.model.startswith("gemini")
    if is_gemini:
        response = chat_with_gemini(prompt, model=args.model, max_tokens=args.max_tokens)
    else:
        response = chat_with_chatgpt(prompt, model=args.model, max_tokens=args.max_tokens)
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(response)

    parsed = json.loads(extract_json_block(response))
    with open(response_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)
    print(f"   retry response cached to {response_path}")
    return parsed


def apply_views_with_retry(
    args: argparse.Namespace,
    db_path: str,
    parsed: dict,
    base_tables: List[str],
    history_block: str,
    cache_dir: str,
    stem: str,
    max_retries: int = 3,
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Apply CREATE VIEWs with column-count verification and retry.

    Returns ``(success, persistent_failures)``:
      - ``success[base] = (view_name, sql)`` for verified materialized views
      - ``persistent_failures[base] = "<last reason>"`` for tables that still
        failed after ``max_retries`` retries
    """
    # Pre-compute base table column counts (once)
    base_col_counts = {t: _column_count(db_path, t) for t in base_tables}

    # Build initial candidates from the full LLM response
    candidates = _flatten_clusters(parsed, base_tables)
    print(f"[prep_database] {len(candidates)} candidate view(s) from initial LLM response "
          f"(out of {len(base_tables)} base tables)")
    missing_initial = [t for t in base_tables if t not in candidates]
    if missing_initial:
        # Treat these as "failures" from the start so they go into the retry loop
        for t in missing_initial:
            print(f"   ⚠️  LLM did not return a view for base table {t!r}")

    success: dict[str, tuple[str, str]] = {}
    last_failures: dict[str, str] = {
        t: "missing from initial LLM response" for t in missing_initial
    }

    for attempt in range(max_retries + 1):
        label = "initial" if attempt == 0 else f"retry {attempt}/{max_retries}"
        reserved = {view for view, _sql in success.values()}
        if candidates:
            print(f"[prep_database] applying views ({label}): "
                  f"{len(candidates)} candidate(s)")
            run_success, run_failures = _apply_views_once(
                db_path, candidates, base_col_counts, reserved
            )
            success.update(run_success)
            last_failures = {**last_failures, **run_failures}
            # Remove any base table that just succeeded
            for b in run_success:
                last_failures.pop(b, None)
        else:
            print(f"[prep_database] ({label}): no candidates to apply this round")

        if not last_failures:
            print(f"[prep_database] ✅ all {len(base_tables)} views applied successfully")
            return success, {}

        if attempt >= max_retries:
            break

        # Re-prompt for the failing tables
        print(f"[prep_database] {len(last_failures)} table(s) still failing; "
              f"re-prompting LLM (retry {attempt + 1}/{max_retries})")
        for base, reason in sorted(last_failures.items()):
            print(f"   - {base}: {reason}")

        try:
            retry_parsed = _call_llm_subset(
                args, sorted(last_failures.keys()), last_failures,
                history_block, cache_dir, stem, attempt + 1,
            )
        except Exception as e:
            print(f"   ❌ retry LLM call failed: {type(e).__name__}: {e}")
            break

        retry_candidates = _flatten_clusters(retry_parsed, sorted(last_failures.keys()))
        candidates = {
            base: retry_candidates[base]
            for base in last_failures
            if base in retry_candidates
        }
        not_returned = sorted(set(last_failures) - set(candidates))
        if not_returned:
            print(f"   ⚠️  LLM did not return retries for: {not_returned}")
        # last_failures will be re-populated by the next _apply_views_once iteration

    print(f"[prep_database] persistent failures after {max_retries + 1} attempt(s): "
          f"{sorted(last_failures)}")
    return success, last_failures


# ---------------------------------------------------------------------------
# Mapping JSON (bird-style)
# ---------------------------------------------------------------------------

def build_mapping_json(
    success: dict[str, tuple[str, str]],
    persistent_failures: dict[str, str],
    base_tables: List[str],
    db_path: str,
) -> dict:
    """Build the final mapping JSON in **bird-style** format.

    Shape::

      {
        "table_to_view": {"<base_table>": "<renamed_view_or_base>", ...},
        "column_mapping": {
          "<renamed_view_or_base>": {"<original_col>": "<renamed_col_or_original>", ...},
          ...
        }
      }

    Persistent failures (and any base table missing from ``success``) get an
    identity entry: ``table_to_view[base] = base`` and
    ``column_mapping[base] = {col: col, ...}``.
    """
    table_to_view: dict[str, str] = {}
    column_mapping: dict[str, dict[str, str]] = {}

    # Successful renames
    for base, (view_name, create_sql) in success.items():
        table_to_view[base] = view_name
        try:
            _vn, pairs = _extract_view_name_and_columns(create_sql)
            # Bird-style: {original_col: renamed_col}
            column_mapping[view_name] = {orig: new for orig, new in pairs}
        except Exception as e:
            print(f"   ⚠️  could not extract column mapping for {base!r} "
                  f"({view_name!r}): {e} — falling back to identity")
            cols = _column_names(db_path, base)
            column_mapping[view_name] = {c: c for c in cols}

    # Identity fallbacks (persistent failures + anything missing entirely)
    handled = set(table_to_view.keys())
    for base in base_tables:
        if base in handled:
            continue
        table_to_view[base] = base
        cols = _column_names(db_path, base)
        column_mapping[base] = {c: c for c in cols}

    return {
        "table_to_view": table_to_view,
        "column_mapping": column_mapping,
    }


# ---------------------------------------------------------------------------
# History rewrite — robust table extraction + per-row verification + retry
# ---------------------------------------------------------------------------

def _extract_tables(sql: str) -> List[str]:
    """Extract real base-schema table references from ``sql``.

    Uses sqlglot's scope analysis so that:
      - CTE definitions and CTE references are excluded
      - Subquery aliases and derived-table aliases are excluded
      - Table aliases are normalized to the underlying table name
      - Schema-qualified names (e.g. ``main.drivers``) return just the table name

    Returns a sorted, deduplicated list of table names. Returns ``[]`` on parse
    failure (silent — caller decides what to do).
    """
    import sqlglot
    from sqlglot import expressions as exp
    from sqlglot.optimizer.scope import traverse_scope

    if not sql or not str(sql).strip():
        return []
    try:
        parsed = sqlglot.parse_one(str(sql), read="sqlite")
    except Exception:
        return []
    if parsed is None:
        return []

    tables = set()

    # Scope-based: source is exp.Table for real tables, Scope for CTEs/subqueries
    scope_worked = False
    try:
        for scope in traverse_scope(parsed):
            for _alias_or_name, source in scope.sources.items():
                if isinstance(source, exp.Table):
                    tables.add(source.name)
        scope_worked = True
    except Exception:
        pass

    if not scope_worked:
        # Fallback: manual CTE filter
        cte_names = {c.alias_or_name.lower() for c in parsed.find_all(exp.CTE)}
        for t in parsed.find_all(exp.Table):
            if t.name and t.name.lower() not in cte_names:
                tables.add(t.name)

    return sorted(tables)


def _partition_tables(sql: str, renamed_views: set) -> tuple:
    """Return ``(matched, other)`` — tables that ARE / are NOT in ``renamed_views``.

    A non-empty ``other`` means the rewrite referenced something outside the
    renamed-view set (a base table, a typo, or a hallucination) and should
    trigger a retry.
    """
    all_t = _extract_tables(sql)
    rl = {v.lower() for v in renamed_views}
    matched = [t for t in all_t if t.lower() in rl]
    other = [t for t in all_t if t.lower() not in rl]
    return matched, other


def _translate_original_to_renamed(
    sql: str, table_to_view: dict
) -> List[str]:
    """For fallback rows (rewrite gave up, ``renamed_SQL`` = original SQL):
    extract the original base tables and translate them to their renamed view
    names via ``table_to_view``. Keeps ``gt_renamed_tables`` semantically
    consistent (always renamed view names).
    """
    t2v_lower = {k.lower(): v for k, v in table_to_view.items()}
    seen = []
    for t in _extract_tables(sql):
        v = t2v_lower.get(t.lower())
        target = v if v else t
        if target not in seen:
            seen.append(target)
    return sorted(seen)


# ---------------------------------------------------------------------------
# Compare SQL (silent — failures reported only as indices + reason summary)
# ---------------------------------------------------------------------------

@func_set_timeout(15)
def _exec_sql(cursor, sql: str):
    cursor.execute(sql)
    return cursor.fetchall()


def _compare_sql(
    predicted_sql: str,
    ground_truth: str,
    db_path: str,
) -> tuple:
    """Run both SQLs against the DB and compare result sets.

    Returns ``(result_code, reason)``:
      - ``result_code``: 1 if result sets match, 0 otherwise
      - ``reason``: short string describing the failure (empty on success).
        Ground-truth failures are silent — they get ``"ground truth N/A"``
        which means we can't compare and the rewrite is conservatively counted
        as a failure (the rewrite gets retried, and on persistent failure the
        row falls back to the original SQL).
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
        conn.text_factory = bytes
        cursor = conn.cursor()
        try:
            ground_truth_res = _exec_sql(cursor, ground_truth)
        except (Exception, FunctionTimedOut):
            return 0, "ground truth N/A"
        try:
            predicted_res = _exec_sql(cursor, predicted_sql)
        except FunctionTimedOut:
            return 0, "predicted SQL timeout"
        except Exception as e:
            return 0, f"predicted execution error: {type(e).__name__}: {e}"
        if set(predicted_res) == set(ground_truth_res):
            return 1, ""
        return 0, "result set mismatch"
    finally:
        if conn is not None:
            try:
                conn.interrupt()
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# History rewrite orchestration
# ---------------------------------------------------------------------------

def _derive_tables_col(renamed_sql_col: str) -> str:
    """gt_<col with trailing _SQL or _sql stripped>_tables.

    Examples:
      renamed_SQL -> gt_renamed_tables
      foo_sql     -> gt_foo_tables
      foo         -> gt_foo_tables
    """
    stem = renamed_sql_col
    if stem.endswith("_SQL"):
        stem = stem[: -len("_SQL")]
    elif stem.endswith("_sql"):
        stem = stem[: -len("_sql")]
    return f"gt_{stem}_tables"


def _format_workload(df: pd.DataFrame, indices: list, question_col: str, sql_col: str) -> str:
    """Format a subset of rows as the workload text block."""
    parts = []
    for i in indices:
        row = df.iloc[i]
        parts.append(
            f"index : {i} question : {row[question_col]}\n"
            f"\nSQL: {row[sql_col]}\n"
            f"\n----------"
        )
    return "\n\n".join(parts)


# Output budget tuning. Per-row output estimate covers JSON wrapping
# (``{"index": N, "renamed_sql": "..."}``) plus a generous SQL allowance.
# ``_CHARS_PER_TOKEN`` is a conservative proxy (~3 chars/token vs the typical
# ~3.5-4) so we round down to the safer side of the budget.
_OUTPUT_CHARS_PER_ROW = 280
_OUTPUT_BUDGET_HEADROOM = 1200  # reserve for outer JSON wrap + EOS etc.
_CHARS_PER_TOKEN = 3


def _align_batch_indices(index_to_sql: dict, chunk: list) -> dict:
    """Key a batch's rewrites by global row index.

    The prompt lists each row as ``index : <global n>`` and asks for those
    indices back. A reply that instead numbers the batch 0..len-1 (none of its
    keys a row of this batch) is mapped back by position. Every rewrite is still
    execution-verified against its own row's gold SQL afterwards.
    """
    keys = set(index_to_sql)
    if keys and not keys & set(chunk) and keys <= set(range(len(chunk))):
        return {chunk[k]: v for k, v in index_to_sql.items()}
    return index_to_sql


def _chunk_pending(args: argparse.Namespace, pending_idx: list) -> list:
    """Split ``pending_idx`` into chunks of at most ``--rewrite_batch_size`` rows
    that also fit within the output budget.

    Returns a list of index lists. A single chunk = single LLM call.

    The budget estimate is purposely conservative: we'd rather over-split than
    have the LLM truncate its output mid-row. The row cap matters more: given a
    long list, the model answers the first rows and closes its JSON early,
    well inside the budget, so rows deep in a large call never get attempted
    and come back as "no response" on every retry.
    """
    if not pending_idx:
        return []
    output_budget_chars = max(0, args.max_tokens * _CHARS_PER_TOKEN - _OUTPUT_BUDGET_HEADROOM)
    max_per_chunk = max(1, output_budget_chars // _OUTPUT_CHARS_PER_ROW)
    max_per_chunk = min(max_per_chunk, max(1, getattr(args, "rewrite_batch_size", 50)))
    if len(pending_idx) <= max_per_chunk:
        return [pending_idx]
    return [
        pending_idx[i : i + max_per_chunk]
        for i in range(0, len(pending_idx), max_per_chunk)
    ]


def _call_llm_rewrite(
    args: argparse.Namespace,
    prompt: str,
    cache_dir: str,
    stem: str,
    label: str,
) -> dict:
    """Call the LLM for a rewrite (initial or retry). Cache prompt + raw + parsed."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    prompt_path = os.path.join(cache_dir, f"{stem}_{ts}.rewrite_{label}.prompt.txt")
    raw_path = os.path.join(cache_dir, f"{stem}_{ts}.rewrite_{label}.raw.txt")
    response_path = os.path.join(cache_dir, f"{stem}_{ts}.rewrite_{label}.response.json")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    is_gemini = args.model.startswith("gemini")
    if is_gemini:
        response = chat_with_gemini(prompt, model=args.model, max_tokens=args.max_tokens)
    else:
        response = chat_with_chatgpt(prompt, model=args.model, max_tokens=args.max_tokens)
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(response)

    parsed = json.loads(extract_json_block(response))
    with open(response_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)
    print(f"   {label} response cached to {response_path}")
    return parsed


def _parse_rewrite_response(parsed: dict) -> dict:
    """Return ``{index: renamed_sql}`` from the LLM response dict."""
    out: dict = {}
    for entry in parsed.get("rewrites", []) or []:
        idx = entry.get("index")
        sql = entry.get("renamed_sql")
        if idx is None or sql is None:
            continue
        try:
            out[int(idx)] = str(sql)
        except (TypeError, ValueError):
            continue
    return out


def _verify_rewrite(
    candidate_sql: str,
    ground_truth: str,
    db_path: str,
    renamed_views: set,
) -> tuple:
    """Verify a single rewrite. Returns ``(ok, reason, matched_tables)``.

    ``ok`` is True only if compare_sql=1 AND no non-renamed tables are referenced.
    """
    if not candidate_sql or not str(candidate_sql).strip():
        return False, "empty rewrite", []
    matched, other = _partition_tables(candidate_sql, renamed_views)
    res_code, res_reason = _compare_sql(candidate_sql, ground_truth, db_path)
    if other:
        # Even if execution matches, refusing because it used non-renamed tables
        reason = f"used non-renamed table(s): {other}"
        if res_code == 0 and res_reason:
            reason = f"{res_reason}; also {reason}"
        return False, reason, matched
    if res_code == 0:
        return False, res_reason, matched
    return True, "", matched


def rewrite_history_sqls(
    args: argparse.Namespace,
    mapping: dict,
    db_path: str,
    cache_dir: str,
    stem: str,
) -> None:
    """Rewrite each row of the history CSV to use renamed views.

    Adds three columns:
      - ``<renamed_sql_col>``         the rewritten SQL (or the original on fallback)
      - ``<renamed_sql_col>_result``  1 if the rewrite matched ground truth, 0 otherwise
      - ``gt_<stripped>_tables``      the renamed views referenced (or translated
                                       from the original SQL for fallback rows)

    Writes back to ``args.history_path`` in place with a ``.bak.<ts>`` backup.
    """
    sql_out_col = args.renamed_sql_col
    result_col = f"{sql_out_col}_result"
    tables_col = _derive_tables_col(sql_out_col)

    print()
    print("=" * 60)
    print(f"[prep_database] HISTORY REWRITE PHASE")
    print(f"  history CSV:     {args.history_path}")
    print(f"  output columns:  {sql_out_col}, {result_col}, {tables_col}")
    print(f"  max retries:     {args.rewrite_max_retries}")
    print("=" * 60)

    df = pd.read_csv(args.history_path)
    for col in (args.question_col, args.sql_col):
        if col not in df.columns:
            raise SystemExit(
                f"history CSV missing required column {col!r}. "
                f"Available: {list(df.columns)}"
            )

    n = len(df)
    renamed_views = set(mapping["table_to_view"].values())
    table_to_view = mapping["table_to_view"]
    mapping_json = json.dumps(mapping, indent=2)

    # Per-row state across attempts
    pending_idx = list(range(n))
    final_sql: List[Optional[str]] = [None] * n
    final_result: List[int] = [0] * n
    final_tables: List[List[str]] = [[] for _ in range(n)]
    last_reason: List[str] = [""] * n

    for attempt in range(args.rewrite_max_retries + 1):
        label = "initial" if attempt == 0 else f"retry_{attempt}"
        if not pending_idx:
            break

        # Preemptively split into chunks that each fit within the output budget.
        # Most runs will single-pass; only big histories or long-tail retries split.
        chunks = _chunk_pending(args, pending_idx)
        if len(chunks) > 1:
            print(f"[history rewrite] {label}: {len(pending_idx)} row(s); "
                  f"splitting into {len(chunks)} batch(es) of <= {len(chunks[0])}")

        attempt_successes = 0
        new_pending: list = []
        # Aggregated failure categories for the per-attempt summary
        ground_truth_na: list = []
        exec_errors: list = []
        set_mismatches: list = []
        non_renamed: list = []
        no_response: list = []
        llm_failure: list = []

        for batch_idx, chunk in enumerate(chunks):
            batch_label = (
                f"{label}_b{batch_idx + 1}of{len(chunks)}" if len(chunks) > 1 else label
            )

            if attempt == 0:
                workload = _format_workload(df, chunk, args.question_col, args.sql_col)
                prompt = REWRITE_PROMPT_TEMPLATE.format(
                    mapping_json=mapping_json,
                    n_rows=len(chunk),
                    n_rows_minus_1=len(chunk) - 1,
                    workload=workload,
                )
            else:
                workload = _format_workload(df, chunk, args.question_col, args.sql_col)
                failure_summary = "\n".join(
                    f"  - index {i}: {last_reason[i]}" for i in chunk
                )
                prompt = REWRITE_RETRY_PROMPT_TEMPLATE.format(
                    mapping_json=mapping_json,
                    n_failed=len(chunk),
                    failure_summary=failure_summary,
                    workload=workload,
                )

            print(f"[history rewrite] {batch_label}: calling LLM for {len(chunk)} row(s)")
            try:
                parsed = _call_llm_rewrite(args, prompt, cache_dir, stem, batch_label)
            except Exception as e:
                # Treat the entire chunk as failed; they retry next attempt
                print(f"   ❌ LLM call failed: {type(e).__name__}: {e}")
                for i in chunk:
                    last_reason[i] = f"LLM call failed: {type(e).__name__}: {e}"
                    llm_failure.append(i)
                    new_pending.append(i)
                continue
            index_to_sql = _align_batch_indices(_parse_rewrite_response(parsed), chunk)

            for i in chunk:
                cand = index_to_sql.get(i)
                if cand is None:
                    last_reason[i] = "LLM did not return a rewrite for this index"
                    no_response.append(i)
                    new_pending.append(i)
                    continue
                ground_truth = str(df.iloc[i][args.sql_col])
                ok, reason, matched_tables = _verify_rewrite(
                    cand, ground_truth, db_path, renamed_views
                )
                if ok:
                    final_sql[i] = cand
                    final_result[i] = 1
                    final_tables[i] = matched_tables
                    attempt_successes += 1
                else:
                    last_reason[i] = reason
                    if "ground truth N/A" in reason:
                        ground_truth_na.append(i)
                    elif "non-renamed" in reason:
                        non_renamed.append(i)
                    elif "mismatch" in reason:
                        set_mismatches.append(i)
                    else:
                        exec_errors.append(i)
                    new_pending.append(i)

        # Per-attempt summary (across all chunks for this attempt)
        print(f"[history rewrite] {label} summary: ok {attempt_successes}/{len(pending_idx)}, "
              f"failed {len(new_pending)}")
        if new_pending:
            print(f"   failed indices: {new_pending[:20]}{'...' if len(new_pending) > 20 else ''}")
            if exec_errors:
                print(f"     - execution error ({len(exec_errors)}): {exec_errors[:10]}")
            if set_mismatches:
                print(f"     - set mismatch ({len(set_mismatches)}): {set_mismatches[:10]}")
            if non_renamed:
                print(f"     - used non-renamed table ({len(non_renamed)}): {non_renamed[:10]}")
            if ground_truth_na:
                print(f"     - ground truth not executable ({len(ground_truth_na)}): {ground_truth_na[:10]}")
            if no_response:
                print(f"     - LLM no response ({len(no_response)}): {no_response[:10]}")
            if llm_failure:
                print(f"     - LLM call failed ({len(llm_failure)}): {llm_failure[:10]}")

        pending_idx = new_pending

    # Fallback: still-failing rows -> use original SQL, translate tables via mapping
    if pending_idx:
        print(f"[history rewrite] {len(pending_idx)} row(s) still failing after "
              f"{args.rewrite_max_retries + 1} attempt(s); falling back to original SQL")
    for i in pending_idx:
        original_sql = str(df.iloc[i][args.sql_col])
        final_sql[i] = original_sql
        final_result[i] = 0
        final_tables[i] = _translate_original_to_renamed(original_sql, table_to_view)

    # Write columns back. Tables column is stored as a repr-style list string
    # (matches the existing history CSV convention of `ast.literal_eval`-able lists).
    df[sql_out_col] = final_sql
    df[result_col] = final_result
    df[tables_col] = [str(t) for t in final_tables]

    # Backup + write
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{args.history_path}.bak.{ts}"
    shutil.copy2(args.history_path, bak)
    df.to_csv(args.history_path, index=False)

    n_ok = sum(final_result)
    print()
    print(f"[prep_database] history rewrite complete")
    print(f"  backup:       {bak}")
    print(f"  rewritten:    {args.history_path}")
    print(f"  EX (renamed): {n_ok}/{n} ({n_ok/n*100:.1f}%)")
    if pending_idx:
        print(f"  fallback rows ({len(pending_idx)}): {pending_idx[:20]}"
              f"{'...' if len(pending_idx) > 20 else ''}")


# ---------------------------------------------------------------------------
# Cluster build phase (no LLM calls — pure computation from history CSV)
# ---------------------------------------------------------------------------

def _infer_cluster_col(args: argparse.Namespace) -> str:
    """Auto-pick tables column. Override via --cluster_col."""
    if args.cluster_col:
        return args.cluster_col
    return "gt_renamed_tables" if args.rename else "gt_tables"


def _infer_sql_col_from_tables_col(tables_col: str) -> str:
    """Derive the matching SQL column name from a tables column name.

    Convention: ``gt_<stem>_tables`` -> ``<stem>_SQL``; bare ``gt_tables`` -> ``SQL``.
    """
    if not tables_col.startswith("gt_") or not tables_col.endswith("_tables"):
        raise ValueError(
            f"unexpected tables column name {tables_col!r}; expected gt_<stem>_tables"
        )
    stem = tables_col[len("gt_"): -len("_tables")]
    return f"{stem}_SQL" if stem else "SQL"


def _resolve_cluster_columns(
    args: argparse.Namespace,
    df: pd.DataFrame,
) -> tuple:
    """Return ``(tables_col, sql_col, derive_tables_from_sql)``.

    - ``tables_col`` is always set, but may not exist in ``df``.
    - ``sql_col`` is always set, and MUST exist in ``df`` (errors otherwise).
    - ``derive_tables_from_sql`` is True when the tables column is missing and we
      should extract on the fly from ``sql_col``.
    """
    tables_col = _infer_cluster_col(args)

    if args.cluster_sql_col:
        sql_col = args.cluster_sql_col
    else:
        try:
            sql_col = _infer_sql_col_from_tables_col(tables_col)
        except ValueError as e:
            raise SystemExit(
                f"Could not infer --cluster_sql_col from --cluster_col={tables_col!r}: {e}. "
                f"Pass --cluster_sql_col explicitly."
            )

    if sql_col not in df.columns:
        raise SystemExit(
            f"History CSV {args.history_path} is missing the SQL column {sql_col!r} "
            f"that --cluster needs for join paths (and possibly fallback table extraction). "
            f"Pass --cluster_sql_col with a column that exists in the CSV. "
            f"Available columns: {list(df.columns)}"
        )

    derive = tables_col not in df.columns
    if derive:
        print(f"[cluster build] tables column {tables_col!r} not in CSV — "
              f"will extract tables from {sql_col!r} using sqlglot")
    return tables_col, sql_col, derive


def _build_t_list_for_clusters(
    df: pd.DataFrame,
    tables_col: str,
    sql_col: str,
    derive_from_sql: bool,
    renamed_views: Optional[set],
) -> list:
    """Build ``t_list`` (list of table-name lists, one per row) for cluster computation.

    If ``derive_from_sql``, extract via sqlglot — filtered against ``renamed_views``
    when rename mode is on, otherwise raw extracted names.
    """
    if not derive_from_sql:
        import ast
        out = []
        for raw in df[tables_col].tolist():
            try:
                parsed = ast.literal_eval(str(raw))
                out.append(list(parsed))
            except Exception:
                out.append([])
        return out

    # Fallback: extract via sqlglot
    out = []
    for sql in df[sql_col].tolist():
        if renamed_views is not None:
            matched, _other = _partition_tables(str(sql), renamed_views)
            out.append(matched)
        else:
            out.append(_extract_tables(str(sql)))
    return out


def build_clusters_in_memory(
    args: argparse.Namespace,
    mapping: Optional[dict],
) -> tuple:
    """Build clusters from the history CSV — return in-memory artifacts only.

    Returns ``(exact_clusters, question_cluster_map, tables_col, sql_col, n_rows)``.
    No file written — use :func:`save_clusters_to_file` to persist.
    """
    from _common.clusters import (
        assign_queries_to_clusters,
        compute_subsets_inplace,
        find_exact_query_patterns,
        simplify_sql,
    )

    df = pd.read_csv(args.history_path)
    if args.question_col not in df.columns:
        raise SystemExit(
            f"History CSV missing required column {args.question_col!r}. "
            f"Available: {list(df.columns)}"
        )

    tables_col, sql_col, derive_from_sql = _resolve_cluster_columns(args, df)
    print(f"  cluster_col:        {tables_col}  (derived: {derive_from_sql})")
    print(f"  cluster_sql_col:    {sql_col}")

    renamed_views: Optional[set] = None
    if args.rename and mapping is not None:
        renamed_views = set(mapping["table_to_view"].values())

    t_list = _build_t_list_for_clusters(
        df, tables_col, sql_col, derive_from_sql, renamed_views,
    )
    n_with_tables = sum(1 for ts in t_list if ts)
    print(f"  rows with tables:   {n_with_tables}/{len(df)}")

    path_list: list = []
    for s in df[sql_col].tolist():
        try:
            path_list.append(simplify_sql(str(s)))
        except Exception:
            path_list.append("")

    question_list = df[args.question_col].astype(str).tolist()

    exact_clusters = find_exact_query_patterns(
        t_list, path_list,
        min_frequency=args.min_frequency,
        min_tables=args.min_tables,
    )
    question_cluster_map = assign_queries_to_clusters(
        t_list, exact_clusters, question_list, path_list,
        min_tables=args.min_tables,
    )
    compute_subsets_inplace(exact_clusters, t_list, path_list)

    print(f"  clusters built:     {len(exact_clusters)}")
    return exact_clusters, question_cluster_map, tables_col, sql_col, len(df)


def _write_consolidated(args: argparse.Namespace, payload: dict) -> None:
    """Write the consolidated config to ``args.output_mapping_path``.

    Touches ``payload['metadata']['built_at']`` so the timestamp tracks the
    most recent phase write.
    """
    payload.setdefault("metadata", {})
    meta = payload["metadata"]
    meta["db_path"] = args.db_path
    meta["dataset_stem"] = _stem_short(args.db_path)
    meta["rename"] = bool(args.rename)
    meta["cluster"] = "cluster" in payload
    meta["view"] = "view" in payload
    meta["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs(os.path.dirname(args.output_mapping_path), exist_ok=True)
    with open(args.output_mapping_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=_json_safe)


def build_and_save_clusters(
    args: argparse.Namespace,
    mapping: Optional[dict],
    consolidated: dict,
) -> tuple:
    """Build clusters AND merge them into the consolidated file.

    Returns ``(exact_clusters, question_cluster_map)``. Side-effect: updates
    ``consolidated["cluster"]`` and writes the file.
    """
    print()
    print("=" * 60)
    print(f"[prep_database] CLUSTER BUILD PHASE")
    print(f"  history CSV:        {args.history_path}")
    print(f"  min_frequency:      {args.min_frequency}")
    print(f"  min_tables:         {args.min_tables}")
    print(f"  consolidated file:  {args.output_mapping_path}")
    print("=" * 60)

    exact_clusters, question_cluster_map, tables_col, sql_col, n_questions = (
        build_clusters_in_memory(args, mapping)
    )

    consolidated["cluster"] = {
        "history_path": args.history_path,
        "cluster_col": tables_col,
        "cluster_sql_col": sql_col,
        "min_frequency": args.min_frequency,
        "min_tables": args.min_tables,
        "n_questions": n_questions,
        "n_clusters": len(exact_clusters),
        "exact_clusters": exact_clusters,
        "question_cluster_map": question_cluster_map,
    }
    _write_consolidated(args, consolidated)
    print(f"  ✅ cluster section written to {args.output_mapping_path}")
    return exact_clusters, question_cluster_map


def _json_safe(obj):
    """Fallback encoder for tuples/sets that sneak through cluster dicts."""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# Cluster view creation (Phase 7)
# ---------------------------------------------------------------------------

def _is_cartesian_create_view(sql: str) -> bool:
    """Return True if any JOIN in the CREATE VIEW has no real key condition.

    Treated as cartesian:
      - CROSS JOIN (explicit or comma-separated FROM clause)
      - JOIN with ``on=None``
      - JOIN whose ON resolves to a constant (sqlglot rewrites bare ``JOIN B``
        as ``ON TRUE``, which is the LLM forgetting the key)
    """
    import sqlglot
    from sqlglot import expressions as exp

    try:
        parsed = sqlglot.parse_one(str(sql), read="sqlite")
    except Exception:
        return False
    if parsed is None:
        return False
    select = parsed.expression
    if not isinstance(select, exp.Select):
        return False
    for join in select.find_all(exp.Join):
        kind = (join.args.get("kind") or "").upper()
        if kind == "CROSS":
            return True
        on = join.args.get("on")
        if on is None:
            return True
        # ``JOIN B`` (no ON) parses with on=Boolean(True). Also catch any
        # constant literal as ON, which can't be a real key condition.
        if isinstance(on, (exp.Boolean, exp.Literal, exp.Null)):
            return True
    return False


def _try_apply_and_verify_view(
    db_path: str,
    view_name: str,
    create_sql: str,
    expected_col_count: int,
) -> tuple:
    """Drop any existing view, apply ``create_sql``, verify column count + cartesian.

    Returns ``(ok, reason)`` where ``reason`` is empty on success or a short
    failure description.
    """
    if _is_cartesian_create_view(create_sql):
        return False, "cartesian join (missing ON / CROSS JOIN)"
    try:
        _drop_view_if_exists(db_path, view_name)
    except Exception as e:
        return False, f"DROP failed: {type(e).__name__}: {e}"
    try:
        _execute_view_sql(db_path, create_sql)
    except Exception as e:
        return False, f"CREATE VIEW failed: {type(e).__name__}: {e}"
    try:
        actual = _column_count(db_path, view_name)
    except Exception as e:
        _drop_view_if_exists(db_path, view_name)
        return False, f"PRAGMA failed: {type(e).__name__}: {e}"
    if actual != expected_col_count:
        _drop_view_if_exists(db_path, view_name)
        return False, f"column count mismatch: expected={expected_col_count}, got={actual}"
    return True, ""


# ----- Code-based fallback (adapted from the user's reference snippet) -----

def _pragma_table_info(db_path: str, table: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"PRAGMA table_info('{table}');").fetchall()
    finally:
        conn.close()


def _pragma_foreign_key_list(db_path: str, table: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT * FROM pragma_foreign_key_list('{table}');").fetchall()
    finally:
        conn.close()


def _build_fk_dict_pragma(db_path: str, tables: list) -> dict:
    """Return ``{table: [pragma_foreign_key_list rows]}`` for non-rename mode."""
    return {t: _pragma_foreign_key_list(db_path, t) for t in tables}


def _build_fk_dict_from_mapping(
    db_path: str,
    cluster_tables: list,
    mapping: dict,
    ds_org_tables: list,
) -> dict:
    """Derive synthetic FK rows for renamed views from the original-table FKs.

    For ``--rename`` mode: cluster_tables are renamed views (no PRAGMA FKs).
    We look up each renamed view's original base table, fetch original FKs via
    ``fetch_org_fks``, translate column names through ``column_mapping``, and
    emit rows in PRAGMA's tuple shape:
    ``(id, seq, ref_table, from_col, to_col, on_update, on_delete, match)``.
    """
    from _common.rename_mapping import fetch_org_fks

    table_to_view = {k.lower(): v for k, v in mapping["table_to_view"].items()}
    view_to_table_lower = {v.lower(): k for k, v in mapping["table_to_view"].items()}
    column_mapping = mapping["column_mapping"]
    column_mapping_lower = {
        view: {k.lower(): v for k, v in cols.items()}
        for view, cols in column_mapping.items()
    }

    cluster_lower = {t.lower() for t in cluster_tables}
    org_fks = fetch_org_fks(db_path, ds_org_tables)
    out: dict = {t: [] for t in cluster_tables}

    for from_t, from_c, ref_t, ref_c in org_fks:
        from_view = table_to_view.get(from_t.lower())
        ref_view = table_to_view.get(ref_t.lower())
        if not from_view or not ref_view:
            continue
        if from_view.lower() not in cluster_lower or ref_view.lower() not in cluster_lower:
            continue
        from_renamed = column_mapping_lower.get(from_view, {}).get(from_c.lower())
        ref_renamed = column_mapping_lower.get(ref_view, {}).get(ref_c.lower())
        if not from_renamed or not ref_renamed:
            continue
        row = (0, 0, ref_view, from_renamed, ref_renamed,
               "NO ACTION", "NO ACTION", "NONE")
        for key in out:
            if key.lower() == from_view.lower():
                out[key].append(row)
                break
    return out


def _extract_edges_from_paths(
    paths: Sequence[str],
    cluster_tables: Sequence[str],
) -> list:
    """Parse cluster ``paths`` (FROM..JOIN fragments from gold/validated SQLs)
    and return PRAGMA-shaped FK rows for every JOIN ON column-equality between
    tables in ``cluster_tables``.

    Each row is ``(from_t, [(0, 0, ref_t, from_c, to_c, "NO ACTION", "NO ACTION", "NONE")])``
    grouped by ``from_t``; the returned value is a dict ``{table: [rows]}`` so
    the caller can merge it into the FK dict produced by the PRAGMA / rename
    paths.

    Hallucination-free by construction: ``paths`` is a regex-sliced substring
    of an execution-validated SQL (see ``simplify_sql`` and the Phase 5 result-set
    check). Edges referencing tables outside ``cluster_tables`` are dropped.
    """
    import sqlglot
    from sqlglot import expressions as exp

    norm_to_orig = {t.lower(): t for t in cluster_tables}
    cluster_lower = set(norm_to_orig.keys())
    seen = set()
    out: dict = {t: [] for t in cluster_tables}

    for raw in paths or []:
        if not raw:
            continue
        p = raw.strip()
        if p.startswith("("):
            p = p[1:].strip()
        candidates = ["SELECT 1 " + p] if p.upper().startswith("FROM") else [p, "SELECT 1 " + p]
        stmt = None
        for cand in candidates:
            try:
                stmt = sqlglot.parse_one(cand, read="sqlite")
                break
            except Exception:
                continue
        if stmt is None:
            continue

        alias_map: dict = {}
        for tbl in stmt.find_all(exp.Table):
            alias_map[tbl.alias_or_name.lower()] = tbl.name
            alias_map[tbl.name.lower()] = tbl.name

        for join in stmt.find_all(exp.Join):
            on = join.args.get("on")
            if on is None:
                continue
            for eq in on.find_all(exp.EQ):
                l, r = eq.this, eq.expression
                if not (isinstance(l, exp.Column) and isinstance(r, exp.Column)):
                    continue
                lt_n = alias_map.get(l.table.lower(), l.table).lower()
                rt_n = alias_map.get(r.table.lower(), r.table).lower()
                if lt_n not in cluster_lower or rt_n not in cluster_lower:
                    continue
                if lt_n == rt_n:
                    continue
                from_t, from_c, ref_t, ref_c = (
                    norm_to_orig[lt_n], l.name, norm_to_orig[rt_n], r.name,
                )
                key = (from_t.lower(), from_c.lower(), ref_t.lower(), ref_c.lower())
                if key in seen:
                    continue
                seen.add(key)
                row = (0, 0, ref_t, from_c, ref_c, "NO ACTION", "NO ACTION", "NONE")
                out.setdefault(from_t, []).append(row)
    return out


def _code_generate_join_view_sql(
    table_infos: dict,
    foreign_keys: dict,
    table_names: list,
    view_name: str,
) -> tuple:
    """Adapted from the user's ``generate_join_view_sql`` (potent_fk.json /
    des_path / meaning_path / linking dropped, view_name passed in directly).

    Column-aliasing matches the LLM output convention: keep original column
    names UNLESS the name collides across tables in this cluster — only then
    rewrite as ``<table>_<column>``.

    Returns ``(sql, cart_join)`` where ``cart_join`` is True when one or more
    tables had to be JOINed without an ON clause (insufficient FK coverage).
    """
    # Identify column-name collisions across the tables in this cluster.
    all_column_names = [row[1] for tinfo in table_infos.values() for row in tinfo]
    name_counts = Counter(all_column_names)
    dup_cols = {name for name, count in name_counts.items() if count > 1}

    # Header
    sql = f"CREATE VIEW `{view_name}` AS\nSELECT\n"

    # Only alias collisions; non-colliding columns keep their original name.
    for table_name, table_info in table_infos.items():
        for row in table_info:
            column_name = row[1]
            if column_name in dup_cols:
                sql += f"  `{table_name}`.`{column_name}` AS `{table_name}_{column_name}`,\n"
            else:
                sql += f"  `{table_name}`.`{column_name}`,\n"
    sql = sql[:-2] + "\n"  # trim trailing comma

    # Update FKs with missing `to` columns by inferring from the PK of the ref table.
    for table_name, fk_list in foreign_keys.items():
        updated: list = []
        for fk in fk_list:
            if len(fk) >= 5 and fk[4] is None:
                ref_t = fk[2]
                if ref_t in table_infos:
                    for info in table_infos[ref_t]:
                        if info[5] == 1:
                            fk = fk[:4] + (info[1],) + fk[5:]
                            break
                elif ref_t.lower() in {k.lower() for k in table_infos}:
                    for k in table_infos:
                        if k.lower() == ref_t.lower():
                            for info in table_infos[k]:
                                if info[5] == 1:
                                    fk = fk[:4] + (info[1],) + fk[5:]
                                    break
                            break
            updated.append(fk)
        foreign_keys[table_name] = updated

    sql += f"FROM `{table_names[0]}`\n"
    joined_tables = {table_names[0]}
    cart_join = False

    table_names_lower = {t.lower() for t in table_names}
    joined_lower = lambda: {t.lower() for t in joined_tables}  # noqa: E731

    # First pass — emit JOINs from FKs of the anchor table.
    for fk in foreign_keys.get(table_names[0], []):
        ref = fk[2]
        if (ref.lower() in table_names_lower
                and ref.lower() != table_names[0].lower()
                and ref.lower() not in joined_lower()):
            sql += f"JOIN `{ref}` ON `{table_names[0]}`.`{fk[3]}` = `{ref}`.`{fk[4]}`\n"
            joined_tables.add(ref)

    # Second pass — walk remaining tables and try to FK-join them onto something already joined.
    for table_name, fk_list in foreign_keys.items():
        if table_name.lower() == table_names[0].lower():
            continue
        if table_name.lower() in joined_lower():
            continue
        # Look for any FK from `table_name` to an already-joined table
        emitted = False
        for fk in fk_list:
            ref = fk[2]
            if ref.lower() in joined_lower() and ref.lower() != table_name.lower():
                sql += f"JOIN `{table_name}` ON `{table_name}`.`{fk[3]}` = `{ref}`.`{fk[4]}`\n"
                joined_tables.add(table_name)
                emitted = True
                break
            # Or an FK from an already-joined table to this one
        if not emitted:
            # Search FK lists of joined tables that reference this one
            for joined_t in list(joined_tables):
                for fk in foreign_keys.get(joined_t, []):
                    if (fk[2].lower() == table_name.lower()
                            and table_name.lower() not in joined_lower()):
                        sql += f"JOIN `{table_name}` ON `{joined_t}`.`{fk[3]}` = `{table_name}`.`{fk[4]}`\n"
                        joined_tables.add(table_name)
                        emitted = True
                        break
                if emitted:
                    break
        if not emitted:
            # No FK coverage — emit a cartesian JOIN and flag.
            sql += f"JOIN `{table_name}`\n"
            joined_tables.add(table_name)
            cart_join = True

    if len(joined_tables) < len(table_names):
        for t in table_names:
            if t.lower() not in joined_lower():
                sql += f"JOIN `{t}`\n"
                joined_tables.add(t)
                cart_join = True

    return sql, cart_join


def _code_based_view_fallback(
    db_path: str,
    cluster_tables: list,
    view_name: str,
    mapping: Optional[dict],
    ds_org_tables: Optional[list],
    paths: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """Try to build a CREATE VIEW SQL via the adapted code path.

    Returns the SQL on success, or ``None`` if the result would be cartesian
    (insufficient FK coverage between the cluster's tables).

    ``paths`` are the cluster's historical FROM/JOIN fragments (regex-sliced
    out of execution-validated SQLs). Their JOIN ON edges are merged into the
    FK dict as synthetic FKs — this rescues BIRD-style clusters where the
    source DB declares no FK between cluster members (e.g. cards/sets, or
    Examination/Laboratory which only declare FKs to a shared parent).
    """
    table_infos = {t: _pragma_table_info(db_path, t) for t in cluster_tables}
    if mapping is not None and ds_org_tables is not None:
        foreign_keys = _build_fk_dict_from_mapping(
            db_path, cluster_tables, mapping, ds_org_tables,
        )
    else:
        foreign_keys = _build_fk_dict_pragma(db_path, cluster_tables)

    if paths:
        path_edges = _extract_edges_from_paths(paths, cluster_tables)
        seen = {
            (t.lower(), r[3].lower() if r[3] else "", r[2].lower() if r[2] else "",
             r[4].lower() if r[4] else "")
            for t, rows in foreign_keys.items() for r in rows
        }
        for t, rows in path_edges.items():
            bucket = foreign_keys.setdefault(t, [])
            for r in rows:
                key = (t.lower(), r[3].lower(), r[2].lower(), r[4].lower())
                if key in seen:
                    continue
                seen.add(key)
                bucket.append(r)

    # Re-anchor: put the table with the most outgoing FK rows first. The join
    # builder walks edges from the anchor outward and is single-pass, so a
    # star-schema cluster (e.g. fact + 2 dims) only converges when the fact
    # table is the anchor. Stable sort keeps ties in input order.
    ordered = sorted(
        cluster_tables,
        key=lambda t: len(foreign_keys.get(t, [])),
        reverse=True,
    )

    sql, cart = _code_generate_join_view_sql(
        table_infos, foreign_keys, ordered, view_name,
    )
    if cart:
        return None
    return sql


# ----- LLM-based attempt (one shot, returns the candidate SQL or None) -----

def _llm_create_cluster_view(
    args: argparse.Namespace,
    db_path: str,
    cluster_tables: list,
    fk_conditions: list,
    is_gemini: bool,
    num_rows: int,
    cache_dir: str,
    stem: str,
    cluster_id,
    attempt: int,
) -> Optional[str]:
    """Single LLM call for a CREATE VIEW over ``cluster_tables`` using the
    existing ``_ADHOC_VIEW_PROMPT`` in ``_common/adhoc_view.py``.

    Caches the prompt + raw response + parsed SQL to ``cache_dir`` keyed by
    ``cluster_id`` and ``attempt`` so each per-cluster attempt is auditable.

    Returns the parsed ``create_view_sql`` string, or ``None`` on parse failure.
    """
    import ast as _ast

    from _common.adhoc_view import _ADHOC_VIEW_PROMPT
    from _common.schema import generate_schema_prompt

    if len(cluster_tables) < 2:
        return None

    view_name = "_join_".join(cluster_tables)
    base_pieces = []
    for t in cluster_tables:
        try:
            base_pieces.append(
                generate_schema_prompt(
                    db_path=db_path, num_rows=num_rows, no_join=False, target_table=t
                )
            )
        except Exception:
            continue
    base_schema = "\n\n".join(base_pieces)

    prompt = _ADHOC_VIEW_PROMPT.format(
        base_schema_for_prompt=base_schema,
        tables_list=list(cluster_tables),
        fk_conditions=list(fk_conditions),
        view_name=view_name,
    )

    ts = time.strftime("%Y%m%d-%H%M%S")
    label = f"view_create_c{cluster_id}_attempt{attempt}"
    prompt_path = os.path.join(cache_dir, f"{stem}_{ts}.{label}.prompt.txt")
    raw_path = os.path.join(cache_dir, f"{stem}_{ts}.{label}.raw.txt")
    sql_path = os.path.join(cache_dir, f"{stem}_{ts}.{label}.sql.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    if is_gemini:
        resp = chat_with_gemini(prompt, model=args.model, response_fields={"SQL": str})
    else:
        resp = chat_with_chatgpt(prompt, model=args.model)
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(resp)

    if "```json" in resp:
        resp = resp[resp.find("```json"):]
    parsed_sql: Optional[str] = None
    try:
        parsed = _ast.literal_eval(resp.replace("```json", "").replace("```", ""))
        parsed_sql = str(parsed["SQL"])
    except Exception:
        try:
            parsed = json.loads(extract_json_block(resp))
            parsed_sql = str(parsed["SQL"])
        except Exception:
            parsed_sql = None
    if parsed_sql is not None:
        with open(sql_path, "w", encoding="utf-8") as f:
            f.write(parsed_sql)
    return parsed_sql


def create_cluster_views(
    args: argparse.Namespace,
    mapping: dict,
    exact_clusters: list,
    ds_org_tables: list,
    cache_dir: str,
    stem: str,
) -> tuple:
    """For each cluster, create a 1-view that joins all its tables.

    A single-table cluster gets a plain ``cluster<id>_<table>`` view over its
    table, built directly without an LLM call. For multi-table clusters the
    strategy is: LLM up to ``--view_max_create_retries`` times (each attempt's
    prompt + raw response + parsed SQL is cached to ``cache_dir``), then the
    adapted code-based fallback. A cluster whose view never works correctly
    is skipped.

    Returns ``(successful_views, skipped_cluster_ids)`` where ``successful_views``
    is a list of ``(view_name, cluster_id, base_tables, create_view_sql)``.
    """
    from _common.adhoc_view import find_fk_conditions_for_view_adhoc

    print()
    print("=" * 60)
    print(f"[prep_database] CLUSTER VIEW CREATION PHASE")
    print(f"  clusters:              {len(exact_clusters)}")
    print(f"  LLM retries per view:  {args.view_max_create_retries}")
    print(f"  code-based fallback:   on (after LLM exhausted)")
    print("=" * 60)

    is_gemini = args.model.startswith("gemini")
    if is_gemini:
        ensure_gemini()
    else:
        ensure_openai()

    successful_views: list = []
    skipped: list = []
    single_table_views: list = []

    for cluster in exact_clusters:
        cluster_id = cluster.get("cluster_id")
        cluster_tables = list(cluster.get("tables", []))
        if not cluster_tables:
            skipped.append((cluster_id, "cluster has no tables"))
            continue
        if len(cluster_tables) == 1:
            # Single-table clusters keep a view, as in the published catalogue
            # (e.g. cluster49_votes): one view per cluster, joins or not. There is
            # no join to synthesise, so no LLM call -- the view selects every
            # column of its table. The cluster<N>_ prefix keeps the name from
            # colliding with the table itself; parse_view_base_tables strips it.
            t = cluster_tables[0]
            view_name = f"cluster{cluster_id}_{t}"
            cols = _column_names(args.db_path, t)
            create_sql = (
                f'CREATE VIEW "{view_name}" AS SELECT '
                + ", ".join('"' + c.replace('"', '""') + '"' for c in cols)
                + f' FROM "{t}"'
            )
            ok, reason = _try_apply_and_verify_view(args.db_path, view_name, create_sql, len(cols))
            if ok:
                print(f"   [cluster {cluster_id}] ✅ single-table view → {view_name}")
                single_table_views.append(cluster_id)
                successful_views.append((view_name, cluster_id, cluster_tables, create_sql))
            else:
                print(f"   [cluster {cluster_id}] ❌ single-table view failed: {reason} — skipped")
                skipped.append((cluster_id, f"single-table view: {reason}"))
            continue

        view_name = "_join_".join(cluster_tables)
        try:
            expected_cols = sum(_column_count(args.db_path, t) for t in cluster_tables)
        except Exception as e:
            print(f"   [cluster {cluster_id}] ❌ could not count base columns: {e}")
            skipped.append((cluster_id, f"base column count failed: {e}"))
            continue

        fk_conditions = find_fk_conditions_for_view_adhoc(
            args.db_path, cluster_tables,
            rename_mode=args.rename,
            mapping_path=args.output_mapping_path,
            ds_org_tables=ds_org_tables,
        )

        # LLM attempts
        ok = False
        last_reason = ""
        for attempt in range(1, args.view_max_create_retries + 1):
            create_sql = _llm_create_cluster_view(
                args, args.db_path, cluster_tables, fk_conditions,
                is_gemini, num_rows=args.num_rows,
                cache_dir=cache_dir, stem=stem,
                cluster_id=cluster_id, attempt=attempt,
            )
            if create_sql is None:
                last_reason = "LLM response unparseable"
                continue
            ok, reason = _try_apply_and_verify_view(
                args.db_path, view_name, create_sql, expected_cols,
            )
            if ok:
                print(f"   [cluster {cluster_id}] ✅ LLM attempt {attempt} succeeded → {view_name}")
                successful_views.append((view_name, cluster_id, cluster_tables, create_sql))
                break
            last_reason = reason
            print(f"   [cluster {cluster_id}] LLM attempt {attempt}/{args.view_max_create_retries} failed: {reason}")

        if ok:
            continue

        # Code-based fallback
        print(f"   [cluster {cluster_id}] LLM exhausted; trying code-based fallback")
        fb_sql = _code_based_view_fallback(
            args.db_path, cluster_tables, view_name,
            mapping if args.rename else None,
            ds_org_tables if args.rename else None,
            paths=cluster.get("paths", []),
        )
        if fb_sql is not None:
            ts = time.strftime("%Y%m%d-%H%M%S")
            fb_path = os.path.join(
                cache_dir, f"{stem}_{ts}.view_create_c{cluster_id}_codefallback.sql.txt"
            )
            with open(fb_path, "w", encoding="utf-8") as f:
                f.write(fb_sql)
        if fb_sql is None:
            print(f"   [cluster {cluster_id}] ❌ code-based fallback gave cartesian join — skipped")
            skipped.append((cluster_id, "cartesian (insufficient FK coverage)"))
            continue
        fb_ok, fb_reason = _try_apply_and_verify_view(
            args.db_path, view_name, fb_sql, expected_cols,
        )
        if fb_ok:
            print(f"   [cluster {cluster_id}] ✅ code-based fallback succeeded → {view_name}")
            successful_views.append((view_name, cluster_id, cluster_tables, fb_sql))
        else:
            print(f"   [cluster {cluster_id}] ❌ code-based fallback failed: {fb_reason} — skipped")
            skipped.append((cluster_id, f"code fallback: {fb_reason}"))

    print()
    print(f"[prep_database] views created: {len(successful_views)}/{len(exact_clusters)} "
          f"(of which {len(single_table_views)} single-table), skipped: {len(skipped)}")
    if single_table_views:
        single_ids = sorted(single_table_views)
        print(f"   single-table views: cluster ids {single_ids[:20]}"
              f"{'...' if len(single_ids) > 20 else ''}")
    return successful_views, skipped


# ---------------------------------------------------------------------------
# View-aware history rewrite (Phase 8) — mirror of the rename rewrite
# ---------------------------------------------------------------------------

VIEW_REWRITE_PROMPT_TEMPLATE = """You are a database expert. The base tables have been renamed to views (per the mapping below). On top of those, cluster views have been created — each cluster view joins several renamed tables on their foreign keys and exposes the union of their columns (with `<table>_<column>` aliases on collision). Rewrite each (question, original SQL) pair below so the new SQL uses a cluster view when its tables match a cluster, and uses the renamed base tables otherwise.

# Rename mapping (use this to translate the original SQL's table + column names into the renamed namespace; column dict is {{original_col: renamed_col}} per view)
###
{mapping_json}
###

# Available cluster views (each view joins ALL of the tables in its `base_tables` list and exposes the columns listed in `columns`)
###
{cluster_views_json}
###

# Available base tables (use these when no cluster view fits the question's tables — these are the renamed views from `table_to_view`)
###
{base_tables_json}
###

# Hard constraints
- Use ONLY the cluster views above OR the renamed base tables above. NEVER reference the original base table names from the input SQL.
- Workflow per row:
  1. Look at the original SQL's tables. Map each to its renamed view via `table_to_view`.
  2. If those renamed views are exactly the `base_tables` of some cluster view (or a subset of one), prefer that cluster view — replace the FROM/JOIN block with `FROM <cluster_view>`. Then use the column names from that cluster view's `columns` list.
  3. Otherwise, use the renamed base tables directly. Look up renamed column names via `column_mapping`.
- The rewritten SQL must return the SAME result set as the original.
- Column-naming convention inside cluster views: a column from the renamed base table is exposed under its renamed name UNLESS the same renamed name appeared in another of the cluster's base tables — only those colliding columns become `<base_table>_<column>` (with the base table prefix from the cluster view's `base_tables`). The authoritative list is the `columns` field of each cluster view above.

# Workload to rewrite ({n_rows} row(s); each is labelled `index : <n>`)
###
{workload}
###

# Output

Respond with a single JSON object. The `rewrites` array MUST contain exactly {n_rows} entries, one per row above, in order, each carrying that row's own `index` as listed.

{{
  "rewrites": [
    {{"index": <the row's index>, "view_sql": "<rewritten SQL using a cluster view if applicable, else renamed base tables>"}},
    {{"index": <the next row's index>, "view_sql": "..."}}
  ]
}}
"""


VIEW_REWRITE_RETRY_PROMPT_TEMPLATE = """You are a database expert. Your previous attempt to view-rewrite {n_failed} SQL(s) failed for the reasons listed below. Rewrite ONLY these rows again, fixing the issues.

# Rename mapping (same as before — use to translate original SQL identifiers to the renamed namespace)
###
{mapping_json}
###

# Available cluster views (same as before)
###
{cluster_views_json}
###

# Available base tables (renamed views from `table_to_view`)
###
{base_tables_json}
###

# Why each row failed
{failure_summary}

# Hard constraints (same as before — re-read carefully)
- NEVER reference original base table names from the input SQL. Translate via `table_to_view` first.
- When a cluster view's `base_tables` covers the question's renamed tables, prefer it; use its `columns` list to pick the right (possibly collision-aliased) column names.
- Otherwise use the renamed base tables, with column names from `column_mapping`.
- The rewritten SQL must return the SAME result set as the original.

# Rows to rewrite ({n_failed} row(s))
###
{workload}
###

# Output

Respond with the same JSON shape. Only include entries for the {n_failed} indices above:

{{
  "rewrites": [
    {{"index": <one of the indices above>, "view_sql": "..."}}
  ]
}}
"""


def _parse_view_rewrite_response(parsed: dict) -> dict:
    """Return ``{index: view_sql}`` from the LLM response dict."""
    out: dict = {}
    for entry in parsed.get("rewrites", []) or []:
        idx = entry.get("index")
        sql = entry.get("view_sql")
        if idx is None or sql is None:
            continue
        try:
            out[int(idx)] = str(sql)
        except (TypeError, ValueError):
            continue
    return out


def _verify_view_rewrite(
    candidate_sql: str,
    ground_truth: str,
    db_path: str,
    allowed_identifiers_lower: set,
) -> tuple:
    """Verify a single view rewrite. Returns ``(ok, reason)``.

    ``ok`` requires compare_sql=1 AND every table reference is in
    ``allowed_identifiers_lower`` (the union of cluster_views + base_tables).
    """
    if not candidate_sql or not str(candidate_sql).strip():
        return False, "empty rewrite"
    used = _extract_tables(candidate_sql)
    bad = [t for t in used if t.lower() not in allowed_identifiers_lower]
    res_code, res_reason = _compare_sql(candidate_sql, ground_truth, db_path)
    if bad:
        reason = f"used non-allowed table(s): {bad}"
        if res_code == 0 and res_reason:
            reason = f"{res_reason}; also {reason}"
        return False, reason
    if res_code == 0:
        return False, res_reason
    return True, ""


def _call_llm_view_rewrite(
    args: argparse.Namespace,
    prompt: str,
    cache_dir: str,
    stem: str,
    label: str,
) -> dict:
    ts = time.strftime("%Y%m%d-%H%M%S")
    prompt_path = os.path.join(cache_dir, f"{stem}_{ts}.view_rewrite_{label}.prompt.txt")
    raw_path = os.path.join(cache_dir, f"{stem}_{ts}.view_rewrite_{label}.raw.txt")
    response_path = os.path.join(cache_dir, f"{stem}_{ts}.view_rewrite_{label}.response.json")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)
    is_gemini = args.model.startswith("gemini")
    if is_gemini:
        response = chat_with_gemini(prompt, model=args.model, max_tokens=args.max_tokens)
    else:
        response = chat_with_chatgpt(prompt, model=args.model, max_tokens=args.max_tokens)
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(response)
    parsed = json.loads(extract_json_block(response))
    with open(response_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)
    print(f"   {label} response cached to {response_path}")
    return parsed


def _derive_view_sql_col(args: argparse.Namespace) -> str:
    """Default: 'view_SQL' (no rename) or 'renamed_view_SQL' (--rename).
    Overridable via --view_sql_col.
    """
    if args.view_sql_col:
        return args.view_sql_col
    return "renamed_view_SQL" if args.rename else "view_SQL"


def rewrite_history_with_views(
    args: argparse.Namespace,
    mapping: dict,
    base_tables: list,
    successful_views: list,
    db_path: str,
    cache_dir: str,
    stem: str,
) -> None:
    """View-aware rewrite. Adds two columns to the history CSV:

      - ``<view_sql_col>``         rewritten SQL using cluster views where possible
      - ``<view_sql_col>_result``  1 if it executes and matches ground truth, else 0

    Fallback: rows that fail after all retries copy the renamed_SQL (if --rename
    set) or the original SQL into ``<view_sql_col>``, result=0.
    """
    sql_out_col = _derive_view_sql_col(args)
    result_col = f"{sql_out_col}_result"

    print()
    print("=" * 60)
    print(f"[prep_database] VIEW-AWARE HISTORY REWRITE PHASE")
    print(f"  history CSV:        {args.history_path}")
    print(f"  output columns:     {sql_out_col}, {result_col}")
    print(f"  cluster views:      {len(successful_views)}")
    print(f"  max retries:        {args.view_max_rewrite_retries}")
    print("=" * 60)

    df = pd.read_csv(args.history_path)
    for col in (args.question_col, args.sql_col):
        if col not in df.columns:
            raise SystemExit(
                f"history CSV missing required column {col!r}. "
                f"Available: {list(df.columns)}"
            )

    n = len(df)

    # Build the LLM-visible "available views" + "available base tables" info.
    # Each cluster view also exposes its actual materialized column list (PRAGMA-
    # introspected) so the LLM doesn't have to guess collision-aliased names.
    cluster_views_for_prompt = []
    for (view_name, _cid, cluster_tables, _sql) in successful_views:
        try:
            cols = _column_names(db_path, view_name)
        except Exception:
            cols = []
        cluster_views_for_prompt.append({
            "view_name": view_name,
            "base_tables": cluster_tables,
            "columns": cols,
        })
    cluster_views_json = json.dumps(cluster_views_for_prompt, indent=2)
    base_tables_json = json.dumps(base_tables, indent=2)
    mapping_json = json.dumps(mapping, indent=2)

    # Identifier whitelist (cluster view names + base table names)
    allowed_identifiers_lower = {
        v["view_name"].lower() for v in cluster_views_for_prompt
    } | {t.lower() for t in base_tables}

    # Per-row state
    pending_idx = list(range(n))
    final_sql: List[Optional[str]] = [None] * n
    final_result: List[int] = [0] * n
    last_reason: List[str] = [""] * n

    for attempt in range(args.view_max_rewrite_retries + 1):
        label = "initial" if attempt == 0 else f"retry_{attempt}"
        if not pending_idx:
            break

        chunks = _chunk_pending(args, pending_idx)
        if len(chunks) > 1:
            print(f"[view rewrite] {label}: {len(pending_idx)} row(s); "
                  f"splitting into {len(chunks)} batch(es) of <= {len(chunks[0])}")

        attempt_successes = 0
        new_pending: list = []
        non_allowed: list = []
        exec_errors: list = []
        set_mismatches: list = []
        ground_truth_na: list = []
        no_response: list = []
        llm_failure: list = []

        for batch_idx, chunk in enumerate(chunks):
            batch_label = (
                f"{label}_b{batch_idx + 1}of{len(chunks)}" if len(chunks) > 1 else label
            )

            if attempt == 0:
                workload = _format_workload(df, chunk, args.question_col, args.sql_col)
                prompt = VIEW_REWRITE_PROMPT_TEMPLATE.format(
                    mapping_json=mapping_json,
                    cluster_views_json=cluster_views_json,
                    base_tables_json=base_tables_json,
                    n_rows=len(chunk),
                    n_rows_minus_1=len(chunk) - 1,
                    workload=workload,
                )
            else:
                workload = _format_workload(df, chunk, args.question_col, args.sql_col)
                failure_summary = "\n".join(
                    f"  - index {i}: {last_reason[i]}" for i in chunk
                )
                prompt = VIEW_REWRITE_RETRY_PROMPT_TEMPLATE.format(
                    mapping_json=mapping_json,
                    cluster_views_json=cluster_views_json,
                    base_tables_json=base_tables_json,
                    n_failed=len(chunk),
                    failure_summary=failure_summary,
                    workload=workload,
                )

            print(f"[view rewrite] {batch_label}: calling LLM for {len(chunk)} row(s)")
            try:
                parsed = _call_llm_view_rewrite(args, prompt, cache_dir, stem, batch_label)
            except Exception as e:
                print(f"   ❌ LLM call failed: {type(e).__name__}: {e}")
                for i in chunk:
                    last_reason[i] = f"LLM call failed: {type(e).__name__}: {e}"
                    llm_failure.append(i)
                    new_pending.append(i)
                continue
            index_to_sql = _align_batch_indices(_parse_view_rewrite_response(parsed), chunk)

            for i in chunk:
                cand = index_to_sql.get(i)
                if cand is None:
                    last_reason[i] = "LLM did not return a rewrite for this index"
                    no_response.append(i)
                    new_pending.append(i)
                    continue
                ground_truth = str(df.iloc[i][args.sql_col])
                ok, reason = _verify_view_rewrite(
                    cand, ground_truth, db_path, allowed_identifiers_lower,
                )
                if ok:
                    final_sql[i] = cand
                    final_result[i] = 1
                    attempt_successes += 1
                else:
                    last_reason[i] = reason
                    if "ground truth N/A" in reason:
                        ground_truth_na.append(i)
                    elif "non-allowed" in reason:
                        non_allowed.append(i)
                    elif "mismatch" in reason:
                        set_mismatches.append(i)
                    else:
                        exec_errors.append(i)
                    new_pending.append(i)

        print(f"[view rewrite] {label} summary: ok {attempt_successes}/{len(pending_idx)}, "
              f"failed {len(new_pending)}")
        if new_pending:
            print(f"   failed indices: {new_pending[:20]}{'...' if len(new_pending) > 20 else ''}")
            if exec_errors:
                print(f"     - execution error ({len(exec_errors)}): {exec_errors[:10]}")
            if set_mismatches:
                print(f"     - set mismatch ({len(set_mismatches)}): {set_mismatches[:10]}")
            if non_allowed:
                print(f"     - used non-allowed identifier ({len(non_allowed)}): {non_allowed[:10]}")
            if ground_truth_na:
                print(f"     - ground truth not executable ({len(ground_truth_na)}): {ground_truth_na[:10]}")
            if no_response:
                print(f"     - LLM no response ({len(no_response)}): {no_response[:10]}")
            if llm_failure:
                print(f"     - LLM call failed ({len(llm_failure)}): {llm_failure[:10]}")

        pending_idx = new_pending

    # Fallback for still-failing rows: copy renamed_SQL (or original SQL)
    # Look for the rename rewrite column (default 'renamed_SQL') if present.
    rename_col = args.renamed_sql_col if args.rename and args.renamed_sql_col in df.columns else None
    for i in pending_idx:
        if rename_col is not None and pd.notna(df.iloc[i][rename_col]):
            final_sql[i] = str(df.iloc[i][rename_col])
        else:
            final_sql[i] = str(df.iloc[i][args.sql_col])
        final_result[i] = 0

    df[sql_out_col] = final_sql
    df[result_col] = final_result

    # Backup + write
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{args.history_path}.bak.{ts}"
    shutil.copy2(args.history_path, bak)
    df.to_csv(args.history_path, index=False)

    n_ok = sum(final_result)
    print()
    print(f"[prep_database] view rewrite complete")
    print(f"  backup:       {bak}")
    print(f"  rewritten:    {args.history_path}")
    print(f"  EX (view):    {n_ok}/{n} ({n_ok / n * 100:.1f}%)")
    if pending_idx:
        print(f"  fallback rows ({len(pending_idx)}): {pending_idx[:20]}"
              f"{'...' if len(pending_idx) > 20 else ''}")


# ---------------------------------------------------------------------------
# Views config writer (Phase 7 + 8 artifact)
# ---------------------------------------------------------------------------

def write_views_section(
    args: argparse.Namespace,
    successful_views: list,
    skipped: list,
    n_clusters: int,
    consolidated: dict,
) -> None:
    """Merge the view phase output into the consolidated config and write it.

    The top-level ``tables`` list is seeded in ``main()`` with the DB's base
    tables and updated to renamed-view names in Phase 4 when ``--rename`` is
    set, so downstream pipelines (basesql / din-sql / csc_sql / MAC-SQL) can
    load the active table list directly without DB introspection.
    """
    section: dict = {
        "n_clusters": n_clusters,
        "n_views_created": len(successful_views),
        "n_views_skipped": len(skipped),
    }
    if args.view:
        section["cluster_views"] = [v[0] for v in successful_views]
        if skipped:
            section["skipped_clusters"] = [
                {"cluster_id": cid, "reason": reason} for cid, reason in skipped
            ]
    consolidated["view"] = section

    _write_consolidated(args, consolidated)
    print(f"  ✅ view section written to {args.output_mapping_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="prep_database",
        description="LLM-rename base tables in a merged SQLite DB. "
                    "Backs up the DB, builds a prompt, calls the LLM, caches the raw JSON response. "
                    "View materialization and final mapping JSON happen in a follow-up step.",
        allow_abbrev=False,
    )
    p.add_argument("--db_path", required=True,
                   help="Path to the input SQLite database (will be backed up before any modification).")
    p.add_argument("--history", action="store_true",
                   help="Enable history mode. When set with no --history_path, defaults to "
                        "../csvs/sample_<short_stem>.csv where <short_stem> strips a leading 'merged_' "
                        "from the db filename (e.g. merged_spider.sqlite -> sample_spider.csv).")
    p.add_argument("--history_path", default=None,
                   help="Path to history CSV. Implies --history when provided.")
    p.add_argument("--model", default="gpt-4.1-mini",
                   help="LLM model. Names starting with 'gemini' route through Google GenAI; "
                        "everything else uses OpenAI. Default: gpt-4.1-mini.")
    p.add_argument("--num_rows", type=int, default=3,
                   help="Sample rows per table in the schema prompt. Default: 3.")
    p.add_argument("--question_col", default="question",
                   help="Column name in the history CSV holding the question. Default: 'question'.")
    p.add_argument("--sql_col", default="SQL",
                   help="Column name in the history CSV holding the SQL. Default: 'SQL'.")
    p.add_argument("--max_tokens", type=int, default=32000,
                   help="Max output tokens for the LLM call. Default: 32000.")
    p.add_argument("--cache_dir", default=None,
                   help="Directory for cached prompts + LLM responses. "
                        "Default: <LDD>/outputs/prep_database/<timestamp>/")
    p.add_argument("--dry_run", action="store_true",
                   help="Build the prompt and cache it; skip the LLM call.")
    p.add_argument("--cache_only", action="store_true",
                   help="Stop after caching the initial LLM response (skip apply + mapping). "
                        "Useful for inspecting the LLM output before committing.")
    p.add_argument("--from_cache", default=None, metavar="PATH",
                   help="Skip the initial LLM call; load a previously-cached response JSON "
                        "from PATH and run only the apply + mapping phases. The DB is still "
                        "backed up before any modification.")
    p.add_argument("--max_retries", type=int, default=3,
                   help="Max LLM re-asks when the rename response is not valid JSON, and max re-prompts for failed views. Default: 3.")
    p.add_argument("--output_mapping_path", default=None,
                   help="Full path (or just filename) for the consolidated prep JSON. "
                        "Default: <LDD>/mapping_files/prep_<short_stem>[_renamed].json "
                        "where <short_stem> strips a leading 'merged_' from the db filename. "
                        "Pass a custom name to keep multiple snapshots side-by-side, e.g. "
                        "--output_mapping_path prep_bird_clean_v2.json (relative paths land "
                        "in the same mapping_files/ directory).")
    p.add_argument("--rename", action="store_true",
                   help="Run the rename phases: backup → LLM CREATE VIEW (per base table) → "
                        "apply with verification → write mapping JSON → history-rewrite SQLs to "
                        "use the renamed views. Without --rename, the rename phases are skipped "
                        "and the script jumps straight to --cluster / --view if those are set.")
    p.add_argument("--renamed_sql_col", default="renamed_SQL",
                   help="Column name to write the rewritten SQL into (history rewrite phase). "
                        "Default: 'renamed_SQL'. Derived columns: '<col>_result', "
                        "'gt_<col-with-_SQL-stripped>_tables'.")
    p.add_argument("--rewrite_max_retries", type=int, default=5,
                   help="Max LLM retries when a rewritten SQL fails verification "
                        "(execution error, result mismatch, or used a non-renamed table). "
                        "After this many retries, the row falls back to the original SQL "
                        "with result=0. Default: 5.")
    p.add_argument("--rewrite_batch_size", type=int, default=50,
                   help="Max history rows per LLM call in the rename and view-aware "
                        "rewrite phases (initial pass and every retry). Default: 50.")
    p.add_argument("--skip_history_rewrite", action="store_true",
                   help="Skip the history-rewrite phase even when --history is enabled. "
                        "Useful when you only want the views + mapping JSON.")
    # --- Cluster build phase ---
    p.add_argument("--cluster", action="store_true",
                   help="Build the table-cluster file from the history CSV. Requires --history. "
                        "No LLM calls — pure computation. Output is a JSON the baselines can "
                        "load directly to skip their own cluster-build step.")
    p.add_argument("--cluster_col", default=None, metavar="COLUMN",
                   help="History-CSV column holding the per-row tables list. "
                        "Default: 'gt_renamed_tables' if --rename else 'gt_tables'. "
                        "If the column is missing, falls back to extracting tables from the "
                        "SQL column via sqlglot (see --cluster_sql_col).")
    p.add_argument("--cluster_sql_col", default=None, metavar="COLUMN",
                   help="History-CSV column holding the per-row SQL (used for cluster join paths "
                        "AND for the fallback table extraction). Default: inferred from "
                        "--cluster_col (e.g. 'gt_renamed_tables' -> 'renamed_SQL'). "
                        "Override if your CSV uses a non-standard naming.")
    p.add_argument("--min_frequency", type=int, default=5,
                   help="Minimum number of history questions that must share the same table set "
                        "before that set becomes a cluster. Default: 5.")
    p.add_argument("--min_tables", type=int, default=2,
                   help="Minimum number of tables a cluster must span. Default: 2.")
    # --- View creation phase (Phases 7 + 8) ---
    p.add_argument("--view", action="store_true",
                   help="Create one CREATE VIEW per cluster (joins all the cluster's tables on FKs) "
                        "AND view-aware-rewrite the history SQLs. Requires --history. Internally "
                        "builds clusters (no save unless --cluster is also on). Sequence: "
                        "rename -> cluster -> view.")
    p.add_argument("--view_sql_col", default=None, metavar="COL",
                   help="Column to write the view-rewritten SQL into. "
                        "Default: 'renamed_view_SQL' if --rename else 'view_SQL'. "
                        "Result column auto-derived as '<col>_result'.")
    p.add_argument("--view_max_create_retries", type=int, default=3,
                   help="Max LLM retries per cluster view-creation attempt. After this, the "
                        "code-based FK fallback is tried. Default: 3.")
    p.add_argument("--view_max_rewrite_retries", type=int, default=5,
                   help="Max LLM retries for the view-aware SQL rewrite phase. After this, the "
                        "row falls back to renamed_SQL (or original SQL) with result=0. Default: 5.")
    return p.parse_args(argv)


def resolve_history_path(args: argparse.Namespace) -> None:
    """Apply the 3-state history convention (matches basesql / din-sql)."""
    if args.history_path:
        args.history = True
        return
    if not args.history:
        return
    short = _stem_short(args.db_path)
    default = os.path.join(LDD_ROOT, "csvs", f"sample_{short}.csv")
    if not os.path.exists(default):
        raise SystemExit(
            f"--history requested but default sample file not found at {default}. "
            f"Pass --history_path explicitly or drop --history."
        )
    args.history_path = default
    print(f"[prep_database] --history_path auto-resolved to {args.history_path}")


def resolve_output_mapping_path(args: argparse.Namespace) -> None:
    """Default ``--output_mapping_path`` to ``<LDD>/mapping_files/prep_<short>[_renamed].json``.

    User-provided values:
      - absolute path → used verbatim
      - bare filename (no separators) → placed under ``<LDD>/mapping_files/``
      - relative path with separators → resolved relative to CWD

    This is the SINGLE consolidated output. The file holds the rename mapping
    (under ``rename``), the cluster artifacts (under ``cluster``), and the
    views config (under ``view``) — each present only if the corresponding
    phase ran.
    """
    if args.output_mapping_path:
        user_val = args.output_mapping_path
        if not os.path.isabs(user_val) and (os.sep not in user_val and "/" not in user_val):
            # Bare filename → land it in the standard mapping_files dir.
            args.output_mapping_path = os.path.join(LDD_ROOT, "mapping_files", user_val)
            print(f"[prep_database] --output_mapping_path resolved bare filename to {args.output_mapping_path}")
        return
    short = _stem_short(args.db_path)
    suffix = "_renamed" if args.rename else ""
    args.output_mapping_path = os.path.join(
        LDD_ROOT, "mapping_files", f"prep_{short}{suffix}.json"
    )
    print(f"[prep_database] --output_mapping_path auto-resolved to {args.output_mapping_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _initial_llm_phase(
    args: argparse.Namespace,
    base_tables: List[str],
    history_block: str,
    history_signal: str,
    cache_dir: str,
    stem: str,
    backup_path: str,
) -> Optional[dict]:
    """Build the initial prompt, call the LLM (unless ``--dry_run``), cache, parse.

    Returns the parsed response dict, or ``None`` for ``--dry_run``.
    """
    # Build schema (per-table, joined)
    schema = "\n\n".join(
        generate_schema_prompt(
            db_path=args.db_path, num_rows=args.num_rows,
            no_join=False, target_table=t,
        )
        for t in base_tables
    )

    checklist = "\n".join(f"  - {t}" for t in base_tables)
    prompt = PROMPT_TEMPLATE.format(
        n_tables=len(base_tables),
        num_rows=args.num_rows,
        history_signal=history_signal,
        base_table_checklist=checklist,
        schema=schema,
        history_block=history_block,
    )

    ts = time.strftime("%Y%m%d-%H%M%S")
    prompt_path = os.path.join(cache_dir, f"{stem}_{ts}.prompt.txt")
    raw_path = os.path.join(cache_dir, f"{stem}_{ts}.raw.txt")
    response_path = os.path.join(cache_dir, f"{stem}_{ts}.response.json")

    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)
    print(f"[prep_database] prompt cached to {prompt_path}  ({len(prompt)} chars)")

    if args.dry_run:
        print(f"[prep_database] --dry_run: skipping LLM call. backup={backup_path}")
        return None

    is_gemini = args.model.startswith("gemini")
    if is_gemini:
        ensure_gemini()
    else:
        ensure_openai()
    # One long JSON reply carries every table's CREATE VIEW, so a single stray
    # token (e.g. Python-style \"\"\" quotes) makes it unparseable. Re-ask up to
    # --max_retries times instead of failing the whole run.
    parsed = None
    for attempt in range(1, args.max_retries + 2):
        print(f"[prep_database] calling {args.model} (max_tokens={args.max_tokens})"
              f"{'' if attempt == 1 else f' -- attempt {attempt}'}...")
        if is_gemini:
            response = chat_with_gemini(prompt, model=args.model, max_tokens=args.max_tokens)
        else:
            response = chat_with_chatgpt(prompt, model=args.model, max_tokens=args.max_tokens)

        path = raw_path if attempt == 1 else raw_path.replace(".raw.txt", f".attempt{attempt}.raw.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(response)
        print(f"[prep_database] raw response cached to {path}  ({len(response)} chars)")

        try:
            parsed = json.loads(extract_json_block(response))
            break
        except Exception as e:
            print(f"[prep_database] LLM response could not be parsed as JSON: "
                  f"{type(e).__name__}: {e}")
    if parsed is None:
        raise SystemExit(
            f"LLM response could not be parsed as JSON after {args.max_retries + 1} "
            f"attempts. Raw responses are next to {raw_path}."
        )
    with open(response_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)
    print(f"[prep_database] parsed response cached to {response_path}")

    _print_initial_coverage_summary(parsed, base_tables)
    return parsed


def _print_initial_coverage_summary(parsed: dict, base_tables: List[str]) -> None:
    """Sanity check: did the LLM return one entry per base table?"""
    n_clusters = len(parsed.get("clusters", []))
    returned = [
        t.get("base_table") for c in parsed.get("clusters", []) for t in c.get("tables", [])
    ]
    print(f"[prep_database] LLM returned {n_clusters} cluster(s), {len(returned)} table(s) "
          f"(DB has {len(base_tables)})")

    base_set = {t.lower() for t in base_tables}
    returned_set = {str(t).lower() for t in returned}
    missing = sorted(t for t in base_tables if t.lower() not in returned_set)
    extra = sorted(t for t in returned if str(t).lower() not in base_set)
    duplicates = sorted({t for t in returned if returned.count(t) > 1})
    if missing:
        print(f"   ⚠️  missing from LLM output ({len(missing)}): {missing}")
    if extra:
        print(f"   ⚠️  unrecognized in LLM output ({len(extra)}): {extra}")
    if duplicates:
        print(f"   ⚠️  duplicates in LLM output ({len(duplicates)}): {duplicates}")
    if not (missing or extra or duplicates):
        print("   ✅ LLM output covers every base table exactly once.")


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not os.path.exists(args.db_path):
        raise SystemExit(f"--db_path not found: {args.db_path}")
    if args.from_cache and not os.path.exists(args.from_cache):
        raise SystemExit(f"--from_cache not found: {args.from_cache}")
    resolve_history_path(args)
    resolve_output_mapping_path(args)

    if args.cluster and not args.history_path:
        raise SystemExit(
            "--cluster requires --history (or --history_path). "
            "Clusters are built from the history CSV."
        )
    if args.view and not args.history_path:
        raise SystemExit(
            "--view requires --history (or --history_path). "
            "Cluster views are derived from history clusters."
        )

    # Phase 1 — Backup (unconditional)
    backup_path = backup_database(args.db_path)

    # List base tables (warn if views already exist)
    base_tables = list_base_tables(args.db_path)
    if not base_tables:
        raise SystemExit(f"No base tables found in {args.db_path}.")
    print(f"[prep_database] found {len(base_tables)} base tables in {args.db_path}")
    pre_views = existing_views(args.db_path)
    if pre_views:
        print(f"[prep_database] {len(pre_views)} view(s) already exist in the DB; "
              f"only views with names this run is about to create will be "
              f"replaced. Existing custom views are left untouched.")
        print(f"   sample: {pre_views[:5]}{'...' if len(pre_views) > 5 else ''}")

    # Build the history block once (reused by retries)
    if args.history_path:
        history_str = format_history(args.history_path, args.question_col, args.sql_col)
        history_block = _HISTORY_BLOCK_TEMPLATE.format(history=history_str)
        history_signal = _HISTORY_INSTRUCTION_ON
    else:
        history_block = ""
        history_signal = _HISTORY_INSTRUCTION_OFF

    if args.cache_dir:
        cache_dir = args.cache_dir
    else:
        from _common.paths import default_output_dir
        run_ts = time.strftime("%Y%m%d-%H%M%S")
        cache_dir = default_output_dir("prep_database", run_ts)
    os.makedirs(cache_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.db_path))[0]
    print(f"[prep_database] cache dir: {cache_dir}")

    # One JSON per prep run — start fresh each invocation. Each phase still
    # writes incrementally so partial runs (e.g. crash after Phase 4) leave a
    # usable file, but we never mix sections produced by different prep runs.
    # Top-level "tables" is seeded with the DB's base tables and overwritten in
    # Phase 4 with renamed-view names when --rename is set.
    # Top-level "columns" records the history-CSV column names this prep run
    # used — resolved from --question_col / --sql_col / --renamed_sql_col /
    # --cluster_col / --view_sql_col so any user override flows through into
    # the JSON. Downstream pipelines read from this section so the user does
    # not have to retype --*_col flags when invoking the baselines.
    _cols_recorded: dict = {
        "question": args.question_col,
        "sql": args.renamed_sql_col if args.rename else args.sql_col,
        "gt_tables": _derive_tables_col(args.renamed_sql_col) if args.rename else "gt_tables",
    }
    if args.view:
        _cols_recorded["view_sql"] = _derive_view_sql_col(args)
    consolidated: dict = {
        "metadata": {},
        "tables": list(base_tables),
        "columns": _cols_recorded,
    }

    # Phases 2-5 (rename) only run when --rename is set. Without --rename, the
    # script falls straight through to Phase 6 (cluster) / Phase 7-8 (view).
    mapping: Optional[dict] = None
    success: dict = {}
    persistent_failures: dict = {}
    if args.rename:
        # Phase 2 — Initial LLM call (or load from cache)
        if args.from_cache:
            print(f"[prep_database] loading cached response from {args.from_cache}")
            with open(args.from_cache, encoding="utf-8") as f:
                parsed = json.load(f)
            _print_initial_coverage_summary(parsed, base_tables)
        else:
            parsed = _initial_llm_phase(
                args, base_tables, history_block, history_signal,
                cache_dir, stem, backup_path,
            )
            if parsed is None:
                # --dry_run: stop here
                return

        if args.cache_only:
            print(f"[prep_database] --cache_only: skipping apply + mapping. backup={backup_path}")
            return

        # Phase 3 — Apply views (with column-count verification + retry).
        # Note: NO bulk drop here — only the specific view names we're about to
        # create get dropped (per-name, inside _apply_views_once). Any other
        # views in the DB (user-custom views, views from a prior run with
        # different names, etc.) are left untouched.
        success, persistent_failures = apply_views_with_retry(
            args, args.db_path, parsed, base_tables, history_block,
            cache_dir, stem, max_retries=args.max_retries,
        )

        # Phase 4 — Build the bird-style rename mapping; write the rename
        # section of the consolidated config.
        mapping = build_mapping_json(success, persistent_failures, base_tables, args.db_path)
        consolidated["rename"] = mapping
        # Switch the top-level "tables" from the original base names to the
        # renamed-view names — that's the active table list for downstream use.
        consolidated["tables"] = sorted({str(v) for v in mapping["table_to_view"].values()})
        _write_consolidated(args, consolidated)
        print(f"[prep_database] rename section written to {args.output_mapping_path}")

        # Phase 5 — Rewrite history SQLs (if --history is on and not skipped)
        if args.history_path and not args.skip_history_rewrite:
            rewrite_history_sqls(args, mapping, args.db_path, cache_dir, stem)
        elif args.history_path and args.skip_history_rewrite:
            print(f"[prep_database] --skip_history_rewrite: skipping history rewrite phase")
    else:
        # No rename — short-circuit out of from_cache / cache_only when they wouldn't make sense
        if args.from_cache:
            raise SystemExit(
                "--from_cache only makes sense with --rename (it loads a rename-LLM response). "
                "Drop --from_cache or add --rename."
            )
        if args.cache_only:
            raise SystemExit(
                "--cache_only only makes sense with --rename (it stops after the rename LLM call). "
                "Drop --cache_only or add --rename."
            )
        print(f"[prep_database] --rename not set: skipping Phases 2-5 (rename + history rewrite)")

    # Phase 6 — Build clusters (always when --cluster or --view; save only when --cluster)
    cluster_artifacts: Optional[tuple] = None
    if args.cluster or args.view:
        if args.cluster:
            ec, qcm = build_and_save_clusters(args, mapping, consolidated)
            cluster_artifacts = (ec, qcm)
        else:
            # --view only: build in-memory, don't merge a 'cluster' section into the file
            print()
            print("=" * 60)
            print(f"[prep_database] CLUSTER BUILD (in-memory, --view only)")
            print(f"  min_frequency:      {args.min_frequency}")
            print(f"  min_tables:         {args.min_tables}")
            print("=" * 60)
            ec, qcm, _tc, _sc, _nq = build_clusters_in_memory(args, mapping)
            cluster_artifacts = (ec, qcm)

    # Phase 7 — Cluster view creation (if --view)
    successful_views: list = []
    skipped_clusters: list = []
    if args.view and cluster_artifacts is not None:
        exact_clusters, _ = cluster_artifacts
        # ds_org_tables is always the ORIGINAL base table list (used for FK lookups
        # via the mapping in rename mode).
        successful_views, skipped_clusters = create_cluster_views(
            args, mapping, exact_clusters, base_tables, cache_dir, stem,
        )

    # Phase 8 — View-aware history rewrite (if --view)
    if args.view and successful_views:
        # active_base_tables: what the LLM should see as "available base tables".
        # In rename mode these are the renamed view names (1:1 over base tables).
        if args.rename and mapping is not None:
            active_base_tables = sorted(mapping["table_to_view"].values())
        else:
            active_base_tables = list(base_tables)
        rewrite_history_with_views(
            args, mapping, active_base_tables, successful_views,
            args.db_path, cache_dir, stem,
        )
    elif args.view and not successful_views:
        print(f"[prep_database] --view: no cluster views created → skipping view rewrite phase")

    # Merge the renamed_tables + cluster_views lists into the consolidated config.
    if args.rename or args.view:
        n_clusters = len(cluster_artifacts[0]) if cluster_artifacts is not None else 0
        write_views_section(args, successful_views, skipped_clusters, n_clusters, consolidated)

    # Final summary
    print()
    print("=" * 60)
    print(f"[prep_database] FINAL SUMMARY")
    print(f"  backup:                {backup_path}")
    print(f"  base tables:           {len(base_tables)}")
    if args.rename:
        print(f"  views materialized:    {len(success)}")
        print(f"  identity fallbacks:    {len(persistent_failures) + (len(base_tables) - len(success) - len(persistent_failures))}")
        if persistent_failures:
            print(f"  persistent failures ({len(persistent_failures)}):")
            for base, reason in sorted(persistent_failures.items()):
                print(f"    - {base}: {reason}")
        if args.history_path and not args.skip_history_rewrite:
            print(f"  history rewritten:     {args.history_path}")
    if args.cluster:
        print(f"  clusters built:        {len(cluster_artifacts[0]) if cluster_artifacts else 0}")
    if args.view:
        print(f"  cluster views created: {len(successful_views)}")
    print(f"  consolidated config:   {args.output_mapping_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
