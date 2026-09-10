"""LDD history as DeepEye-SQL's few-shot pool.

Replaces the BIRD-train / Spider-train corpus with ``sample_<ds>.csv``, the same
history pool every other LDD pipeline retrieves from. Nothing else about
DeepEye's few-shot machinery changes: the masker still masks, the retriever
still scores masked-question 0.6 / preliminary-SQL 0.4, only ``num_examples``
drops from 7 to 3.

One index per dataset, not per arm
----------------------------------
The masked index is built once from the question and the BASE SQL column. Which
SQL an arm *shows* is decided at render time from ``metadata["sql_variants"]``.
So every arm retrieves the same three history questions and differs only in the
namespace of the SQL printed in the prompt -- which is what makes base vs +APR a
clean comparison rather than two different retrievals.

Two render points, because +A does not exist yet at linking time
----------------------------------------------------------------
step 4  -> non-view column  (SQL | workload_updated_SQL)
           The reversed linker drafts SQL from these examples and the schema is
           parsed out of it. Cluster views are not in scope until 5.5, so
           view-flavoured examples there would produce draft SQL over objects
           that filter_used_database_schema then drops, silently zeroing out the
           strongest linker on every +A arm.
step 5.5 -> view column     (view_SQL | workload_updated_view_SQL) when +A,
           pool restricted to matched-cluster questions when +P.
"""

from __future__ import annotations

import ast
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from .config import HISTORY_COLS, SAMPLE_CSV, Arm


def _parse_tables(raw: Any) -> List[str]:
    """gt_tables is stored as a stringified list in the history CSV."""
    if isinstance(raw, (list, tuple)):
        return [str(t) for t in raw]
    text = str(raw or "").strip()
    if not text or text.lower() == "nan":
        return []
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, (list, tuple)):
            return [str(t) for t in parsed]
        return [str(parsed)]
    except (ValueError, SyntaxError):
        return [t.strip().strip("'\"") for t in text.strip("[]").split(",") if t.strip()]


@lru_cache(maxsize=4)
def load_history(dataset: str) -> pd.DataFrame:
    return pd.read_csv(SAMPLE_CSV[dataset])


def sql_variants(dataset: str, row: pd.Series) -> Dict[str, str]:
    """Every namespace this history row is available in, keyed by arm shape."""
    out: Dict[str, str] = {}
    for rename in (False, True):
        cols = HISTORY_COLS[(dataset, rename)]
        tag = "renamed" if rename else "org"
        for kind in ("sql", "view_sql"):
            col = cols[kind]
            if col and col in row.index:
                value = row[col]
                if pd.notna(value) and str(value).strip():
                    out[f"{tag}_{kind}"] = str(value).strip()
    return out


def variant_key(arm: Arm, use_view: bool) -> str:
    return f"{'renamed' if arm.rename else 'org'}_{'view_sql' if use_view else 'sql'}"


def render_sql(example: Dict[str, Any], arm: Arm, use_view: bool) -> str:
    """The SQL this arm should print for a retrieved example.

    Falls back to the non-view variant when a row has no view SQL, which happens
    for roughly half the history rows.
    """
    variants = (example.get("sql_variants") or {})
    return (variants.get(variant_key(arm, use_view))
            or variants.get(variant_key(arm, False))
            or str(example.get("sql", "")))


def render_sql_pair(example: Dict[str, Any], arm: Arm) -> str:
    """Both formulations of one history question, base first then the view.

    LDD's other ports emit a flat 6-line ``History SQLs:`` block (3 base + 3
    view). DeepEye's ICL prompt is structured question->SQL pairs, so emitting 6
    entries would show the same question mapped to two different answers -- a
    poor in-context signal. Instead each of the 3 retrieved questions carries
    both SQLs, labelled as equivalents.

    That labelling is the point: previously +A showed only the view query, so
    the model saw the shortcut without ever seeing the join it replaces, and
    nothing indicated the two were the same query. View uptake in the generators
    was 14%.

    Rows with no view SQL (roughly half of sample_bird.csv) degrade to base-only,
    which is why this is strictly additive over the previous view-only rendering.
    """
    base = render_sql(example, arm, use_view=False)
    if not arm.view:
        return base
    variants = example.get("sql_variants") or {}
    view = variants.get(variant_key(arm, True), "")
    if not view or view == base:
        return base
    return ("-- base tables\n" + base
            + "\n-- equivalent, using the pre-joined cluster view\n" + view)


def load_history_examples(dataset: str, rename: bool = False) -> List[Dict[str, Any]]:
    """History rows as index-builder records (base SQL, all variants attached).

    DEEPEYE_LDD_POOL_LIMIT truncates the pool. Dry runs only: building the
    masked few-shot index costs one LLM call per pool row, so a 767-row pool is
    767 calls before the first question is even linked. Never set for a real run.
    """
    frame = load_history(dataset)
    limit = os.environ.get("DEEPEYE_LDD_POOL_LIMIT")
    if limit:
        frame = frame.iloc[: int(limit)]
    # The pool's own SQL -- and therefore the masked SQL the retriever embeds --
    # must live in the arm's namespace. For +R that is workload_updated_SQL,
    # verified 767/767 execution-identical to the org SQL column with zero org
    # table references. Using org SQL for a renamed arm would be defensible only
    # by arguing masking erases the difference, which is weaker than just being
    # consistent.
    base_col = HISTORY_COLS[(dataset, rename)]["sql"]
    gt_col = HISTORY_COLS[(dataset, rename)]["gt_tables"]

    records: List[Dict[str, Any]] = []
    for row_index, row in frame.iterrows():
        question = str(row.get("question", "")).strip()
        base_sql = str(row.get(base_col, "")).strip()
        if not question or not base_sql or base_sql.lower() == "nan":
            continue
        records.append({
            "example_id": f"ldd:{dataset}:{row_index}",
            "dataset": dataset,
            "db_id": f"merged_{dataset}",
            "question": question,
            "sql": base_sql,
            # evidence is deliberately empty: the LDD runs use no hints anywhere
            "evidence": "",
            "metadata": {
                "row_index": int(row_index),
                "gt_tables": _parse_tables(row.get(gt_col)),
                "gt_tables_renamed": _parse_tables(
                    row.get(HISTORY_COLS[(dataset, True)]["gt_tables"])),
                "sql_variants": sql_variants(dataset, row),
            },
        })
    return records


def restrict_to_indices(examples: Sequence[Dict[str, Any]],
                        allowed_row_indices: Optional[Sequence[int]],
                        top_k: int) -> List[Dict[str, Any]]:
    """Keep cluster-matched examples first, then backfill globally to ``top_k``.

    Mirrors basesql._topk_history_sqls: rank inside the matched clusters, and if
    fewer than top_k survive, fill the remainder from the global ranking rather
    than returning a short block.
    """
    if not allowed_row_indices:
        return list(examples)[:top_k]
    allowed = {int(i) for i in allowed_row_indices}

    def row_of(example: Dict[str, Any]) -> Optional[int]:
        meta = example.get("metadata") or {}
        value = meta.get("row_index", example.get("row_index"))
        return int(value) if value is not None else None

    inside = [e for e in examples if row_of(e) in allowed]
    if len(inside) >= top_k:
        return inside[:top_k]
    outside = [e for e in examples if row_of(e) not in allowed]
    return (inside + outside)[:top_k]
