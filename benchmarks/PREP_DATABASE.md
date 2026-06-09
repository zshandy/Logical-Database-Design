# prep_database

LLM-assisted schema preparation for a merged SQLite database. Produces a
single consolidated JSON (the "prep JSON") that every downstream NL2SQL
baseline in this repo loads to know:

- which tables are active (the originals, or LLM-renamed views on top of them)
- how original column names map to renamed column names
- which table-sets cluster together in the workload
- which cluster-views exist and how the history SQLs are rewritten against them

Run [`prep_database.py`](prep_database.py) once per (database, history)
combination; the four baselines ([`basesql/`](basesql/), [`din-sql/`](din-sql/),
[`csc_sql/`](csc_sql/), [`MAC-SQL/`](MAC-SQL/)) then read the resulting JSON
through [`_common/rename_mapping.py`](_common/rename_mapping.py).

---

## What it does (phase by phase)

Each phase is independently gated by a flag. A typical run combines them.

| Phase | Flag | What it does |
|-------|------|--------------|
| 1. Backup | always | Copies the input sqlite to `<db>.bak.<timestamp>` before any modification. |
| 2. Rename LLM call | `--rename` | One prompt that asks the LLM for one `CREATE VIEW` per base table — same rows, same columns in the same order, with `AS` renames. Both the prompt and the raw response are cached to disk. |
| 3. Apply views | `--rename` | Executes each `CREATE VIEW` against the DB and verifies the view's column count matches the base table's. Re-prompts the LLM up to `--max_retries` times for failures, then falls back to identity (keeps the original table name) for anything still failing. |
| 4. Rename mapping | `--rename` | Writes the `rename` section of the prep JSON (`table_to_view`, `column_mapping`) and switches the top-level `tables` list from originals to renamed views. |
| 5. History rewrite (rename) | `--rename` + history | For each row in the history CSV, asks the LLM to rewrite the SQL against the renamed views, verifies by executing both rewritten and original against the DB and comparing result sets. Failed rows get retried, then fall back to the original SQL with `result=0`. Adds `<renamed_sql_col>`, `<renamed_sql_col>_result`, `gt_<stem>_tables` columns to the history CSV in place (with a backup). |
| 6. Cluster mining | `--cluster` (or implied by `--view`) | Pure-computation phase, no LLM. Mines frequent table-set clusters from history (see [`_common/clusters.py`](_common/clusters.py)). Saved into the prep JSON only when `--cluster` is set; built in-memory only when `--view` is set without `--cluster`. |
| 7. Cluster view creation | `--view` | For each cluster with ≥2 tables, asks the LLM for one `CREATE VIEW` that joins the cluster's tables on their FKs. Retries `--view_max_create_retries` times, then falls back to a code-based FK-walker that emits joins from the introspected schema + JOIN edges observed in the history. Skips clusters where no non-cartesian join is reachable. |
| 8. History rewrite (view) | `--view` + history | Same shape as phase 5, but the LLM is allowed to use cluster views in addition to the renamed base tables. Adds `<view_sql_col>` and `<view_sql_col>_result` to the history CSV. |

The cached prompts + raw + parsed responses for each LLM call land in
`<LDD>/outputs/prep_database/<timestamp>/`, keyed by phase and attempt — so
every decision is auditable after the fact.

---

## Inputs

### 1. Merged SQLite (required)

A single `.sqlite` file containing **all the base tables** from every source
database you want covered, merged into one DB. Tables from different source DBs
just sit side by side; the LLM uses naming + workload signals to figure out
which tables came from which source.

- Default location: `<LDD>/databases/merged_<dataset>.sqlite`
  (e.g. `databases/merged_bird.sqlite`).
- Pass `--db_path` to point elsewhere.
- The script reads via PRAGMA / sqlite3; any sqlite3-compatible file works.
- The input is backed up before any modification (phase 1) — you can always
  recover the pre-prep state by restoring the `.bak.<timestamp>` sibling.

### 2. Benchmark CSV (required for any phase that needs questions/SQLs)

Currently consumed only by the history phases (5, 8) and the cluster miner
(phase 6). If you're running plain `--rename` with no history, you don't need
this file. Required columns:

| Column | Default name | Override | Notes |
|--------|--------------|----------|-------|
| Question | `question` | `--question_col` | Plain English NL question. |
| Gold SQL | `SQL` | `--sql_col` | Executable SQLite. Used for execution-verification of every rewrite. |

Extra columns (e.g. `db_id`, `evidence`, baseline-specific output columns) are
preserved verbatim — the script only reads the two columns above and appends
the phase-5/8 rewrite columns at the end.

### 3. History CSV (optional, same shape as the benchmark CSV)

When provided, history feeds both the cluster miner (phase 6) and the rename
LLM call (phase 2 — appears to the LLM as "tables that co-occur in the same
SQL are from the same source DB"). Same required columns as the benchmark CSV
(`question`, `SQL`).

| Flag | Effect |
|------|--------|
| (neither flag) | History disabled. Phases 5, 6, 7, 8 are unavailable. |
| `--history` | Uses `<LDD>/csvs/sample_<dataset>.csv`. |
| `--history_path FILE` | Uses `FILE`, **and** implicitly enables history. |

The history CSV is **rewritten in place** by phases 5 and 8 (with a
timestamped backup). The new columns are additive — `renamed_SQL`,
`renamed_SQL_result`, `gt_renamed_tables`, `renamed_view_SQL`,
`renamed_view_SQL_result` — and don't disturb columns produced by other
tooling.

---

## Setup

### Python deps

Everything is in [`benchmarks/requirements.txt`](requirements.txt). The core
deps for prep_database specifically are:

```
openai            # phase 2, 3, 5, 7, 8 LLM calls
google-genai      # only when --model starts with 'gemini'
sqlglot           # CREATE VIEW parsing + table extraction + JOIN edge mining
pandas            # history CSV I/O
func_timeout      # SQL execution timeouts in phase 5/8 verification
```

### Environment variables

| Variable | Required by | Purpose |
|----------|-------------|---------|
| `OPENAI_API_KEY` | Default `--model gpt-4.1-mini` and any other OpenAI model | OpenAI chat completions |
| `GEMINI_API_KEY` | `--model gemini-...` | Google GenAI |

No keys are embedded in the code — both are read via `os.environ.get` inside
[`_common/llm.py`](_common/llm.py).

---

## Important flags

The full list is `python prep_database.py --help`. The highlights:

### Phase selection

| Flag | Default | What it gates |
|------|---------|---------------|
| `--rename` | off | Phases 2–5. Without this, the script jumps straight to phase 6 / 7 / 8 if those are on. |
| `--cluster` | off | Phase 6, with cluster artifacts saved into the prep JSON. Requires history. |
| `--view` | off | Phases 6 (in-memory if `--cluster` is off), 7, 8. Requires history. |

You can run any subset. Common combinations:

- `--rename` — rename + history rewrite only. No clusters, no cluster views.
- `--rename --cluster` — rename + mine clusters, no cluster views.
- `--rename --view` — rename + cluster views (clusters mined in-memory, not saved).
- `--rename --cluster --view` — full pipeline. The recommended combination if
  you intend to use any of the downstream baselines' cluster/view modes.
- `--view` alone — cluster views over the ORIGINAL (un-renamed) tables.

### Inputs / outputs

| Flag | Default | Notes |
|------|---------|-------|
| `--db_path` | required | Path to the merged sqlite. |
| `--history_path` | none | Path to the history CSV. Implies `--history`. |
| `--history` | off | Use the default `<LDD>/csvs/sample_<dataset>.csv`. |
| `--question_col` | `question` | Override if your CSV uses a different header. |
| `--sql_col` | `SQL` | Same. |
| `--output_mapping_path` | `<LDD>/mapping_files/prep_<stem>[_renamed].json` | Bare filename → resolved under the standard `mapping_files/` dir. Absolute path → used verbatim. |
| `--cache_dir` | `<LDD>/outputs/prep_database/<timestamp>/` | Where prompts + raw/parsed LLM responses are written. |

### Model + retries

| Flag | Default | Notes |
|------|---------|-------|
| `--model` | `gpt-4.1-mini` | Names starting with `gemini` route through Google GenAI; everything else uses OpenAI. |
| `--num_rows` | 3 | Sample rows per table in the schema prompt. |
| `--max_tokens` | 32000 | Output token cap for the LLM call. |
| `--max_retries` | 3 | Phase 3 re-prompts for tables whose CREATE VIEW failed verification. |
| `--rewrite_max_retries` | 5 | Phase 5 retries for SQL rewrites that don't match ground truth. |
| `--view_max_create_retries` | 3 | Phase 7 retries before the code-based fallback. |
| `--view_max_rewrite_retries` | 5 | Phase 8 retries. |

### Clustering knobs

| Flag | Default | Notes |
|------|---------|-------|
| `--min_frequency` | 5 | A table-set has to be shared by this many history questions before it becomes a cluster. |
| `--min_tables` | 2 | A cluster must span at least this many tables. |
| `--cluster_col` | inferred from `--rename` | History-CSV column holding per-row table lists. Default: `gt_renamed_tables` if `--rename` else `gt_tables`. Missing → extracted from the SQL column via sqlglot. |
| `--cluster_sql_col` | inferred from `--cluster_col` | History-CSV column with the SQL used for join paths. |

### Iteration (rename only)

| Flag | Effect |
|------|--------|
| `--dry_run` | Build the prompt, cache it, exit before calling the LLM. Useful for previewing prompt size. |
| `--cache_only` | Stop after the initial LLM response is cached. Useful for inspecting before committing. |
| `--from_cache PATH` | Skip the LLM call; load a previously-cached response and run only phases 3–5. |

---

## Example commands

All examples assume you're in `benchmarks/`. Adjust paths if you run from
elsewhere.

### Just rename (no history, no clusters, no views)

```bash
python prep_database.py \
    --db_path ../databases/merged_bird.sqlite \
    --rename
```

Writes `mapping_files/prep_bird_renamed.json` with the `rename` section only.

### Rename + history rewrite

```bash
python prep_database.py \
    --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv \
    --rename
```

Adds `renamed_SQL`, `renamed_SQL_result`, `gt_renamed_tables` columns to
`sample_bird.csv` in place (with a `.bak.<timestamp>` backup).

### Full pipeline (rename + cluster + view)

```bash
python prep_database.py \
    --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv \
    --rename --cluster --view \
    --model gpt-4.1-mini
```

Writes all four sections (`rename`, `cluster`, `view`, plus top-level `tables`
and `columns`) to `mapping_files/prep_bird_renamed.json`. Adds
`renamed_SQL`, `renamed_view_SQL`, and their `_result` columns to the history
CSV.

### Cluster views over the original schema (no rename)

```bash
python prep_database.py \
    --db_path ../databases/merged_spider.sqlite \
    --history_path ../csvs/sample_spider.csv \
    --cluster --view
```

The clusters/views are built directly over the original table names. Useful
when you want to study the effect of cluster views in isolation.

### Just mine clusters (no LLM at all)

```bash
python prep_database.py \
    --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv \
    --cluster
```

No model call — pure computation. The output JSON contains only the `cluster`
section (plus `tables` and `columns`).

### Inspect the rename prompt before paying for the LLM call

```bash
python prep_database.py \
    --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv \
    --rename --dry_run
```

Prompt is cached to `outputs/prep_database/<ts>/<stem>_<ts>.prompt.txt`; no
LLM call is made. Inspect it, then drop `--dry_run` for the real run.

### Resume from a cached LLM response

```bash
python prep_database.py \
    --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv \
    --rename \
    --from_cache outputs/prep_database/20260605-104012/merged_bird_20260605-104015.response.json
```

Skips phase 2; runs phases 3–5 against the cached response. Useful when phase
3 fails for an external reason (e.g. disk full) and you don't want to repay
for the rename LLM call.

### Use Gemini instead of OpenAI

```bash
export GEMINI_API_KEY=...
python prep_database.py \
    --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv \
    --rename --cluster --view \
    --model gemini-2.5-flash
```

---

## Output: the consolidated prep JSON

Written to `--output_mapping_path` (default
`<LDD>/mapping_files/prep_<stem>[_renamed].json`). All sections below are
optional — present only if the corresponding phase ran.

```jsonc
{
  "metadata": {
    "db_path":      "...",          // absolute path to the input sqlite
    "dataset_stem": "bird",          // derived from the db filename
    "rename":       true,
    "cluster":      true,
    "view":         true,
    "built_at":     "2026-06-08T17:14:46"
  },

  // The active table list for downstream baselines:
  //  - with --rename: the renamed view names
  //  - without --rename: the original base table names
  "tables": ["chem_atom_dim", "club_member_roster", ...],

  // The history-CSV column names this prep run used — downstream baselines
  // read this so users don't have to retype --question_col / --sql_col etc.
  "columns": {
    "question":   "question",
    "sql":        "renamed_SQL",
    "gt_tables":  "gt_renamed_tables",
    "view_sql":   "renamed_view_SQL"
  },

  "rename": {
    "table_to_view": {"atom": "chem_atom_dim", ...},
    "column_mapping": {
      "chem_atom_dim": {"atom_id": "atom_pk", "element": "element_symbol", ...},
      ...
    }
  },

  "cluster": {
    "history_path":          "...",
    "cluster_col":           "gt_renamed_tables",
    "cluster_sql_col":       "renamed_SQL",
    "min_frequency":         5,
    "min_tables":            2,
    "n_questions":           1534,
    "n_clusters":            47,
    "exact_clusters":        [{"cluster_id": 0, "tables": [...], "paths": [...]}, ...],
    "question_cluster_map":  {"0": [3, 7], ...}
  },

  "view": {
    "n_clusters":       47,
    "n_views_created":  39,
    "n_views_skipped":  8,
    "cluster_views":    ["chem_atom_dim_join_chem_bond_xref", ...],
    "skipped_clusters": [{"cluster_id": 12, "reason": "..."}, ...]
  }
}
```

Downstream baselines load this JSON through
[`_common/rename_mapping.py`](_common/rename_mapping.py)'s `load_active_views`,
which auto-detects which sections are present.

---

## Caching, retries, and audit trail

Every LLM call (initial + retries) caches three files into the cache dir:

```
<cache>/<stem>_<ts>.<label>.prompt.txt   # exact prompt sent
<cache>/<stem>_<ts>.<label>.raw.txt      # raw response from the API
<cache>/<stem>_<ts>.<label>.response.json # parsed JSON (post-extract_json_block)
```

Labels encode the phase and attempt:
- `prompt`/`raw`/`response` (no label) — phase 2 initial rename call
- `retry1`/`retry2`/... — phase 3 view-fix re-prompts
- `rewrite_initial`/`rewrite_retry_N`/`rewrite_initial_bN_ofN` — phase 5
- `view_create_cN_attemptM` — phase 7 per-cluster view creation
- `view_create_cN_codefallback.sql.txt` — phase 7 code-based fallback output
- `view_rewrite_initial`/`view_rewrite_retry_N` — phase 8

Persistent failures (after all retries) are surfaced in the final summary
block on stdout — and, for the rename phase, are mirrored into the prep JSON
as identity entries so downstream code doesn't have to special-case them.
