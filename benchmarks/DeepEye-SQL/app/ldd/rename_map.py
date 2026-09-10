"""org <-> renamed name translation for the +R arms.

Only needed for DIAGNOSTICS. The pipeline itself never translates: a +R arm
sees renamed objects end to end, and EX is scored by executing against the same
merged database, where the renamed tables are views over the same rows.

What does need translation is DeepEye's own schema-linking recall
(``_eval_schema_linking_recall``), which parses ``gold_sql`` -- written in the
ORIGINAL namespace -- and compares the extracted names against what the linkers
returned. On a +R arm those never match, so recall would read 0.0 for every
question and the stage's built-in diagnostic would be meaningless.

Source of truth is ``mapping_files/name_mapping_<ds>.json``, validated against
merged_bird.sqlite: 75/75 tables and 798/798 renamed columns exist in the actual
views, 0 missing. The alternative -- parsing ``CREATE VIEW ... AS SELECT x AS y``
out of sqlite_master -- agrees but is redundant.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

# Vendored under <LDD>/benchmarks/, so the repo root is derived from this
# file's location rather than hardcoded -- the original absolute path only
# worked on the machine the experiments were run on.
LDD = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, os.pardir))
MAPPING_FILES = os.path.join(LDD, "mapping_files")


@lru_cache(maxsize=4)
def load_mapping(dataset: str) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """``({org_table_lower: renamed_table}, {renamed_table: {org_col_lower: renamed_col}})``."""
    path = os.path.join(MAPPING_FILES, f"name_mapping_{dataset}.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    section = raw.get("rename") or raw
    table_to_view = {str(k).lower(): str(v) for k, v in (section.get("table_to_view") or {}).items()}
    column_mapping = {
        str(view): {str(o).lower(): str(n) for o, n in (cols or {}).items()}
        for view, cols in (section.get("column_mapping") or {}).items()
    }
    if not table_to_view:
        raise ValueError(f"{path} carries no table_to_view mapping")
    return table_to_view, column_mapping


def translate_table(dataset: str, org_table: str) -> Optional[str]:
    table_to_view, _ = load_mapping(dataset)
    return table_to_view.get(str(org_table).lower())


def translate_column(dataset: str, org_table: str, org_column: str) -> Optional[str]:
    table_to_view, column_mapping = load_mapping(dataset)
    renamed_table = table_to_view.get(str(org_table).lower())
    if renamed_table is None:
        return None
    # Columns absent from the mapping kept their original name (e.g. account_id).
    return column_mapping.get(renamed_table, {}).get(str(org_column).lower(), org_column)


def translate_linked(dataset: str,
                     tables_and_columns: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Translate a ``{table: [columns]}`` dict from the org into the renamed namespace.

    Tables with no mapping entry are dropped rather than passed through: a name
    that survives untranslated would be scored as if it matched, inflating recall.
    """
    out: Dict[str, List[str]] = {}
    for org_table, columns in (tables_and_columns or {}).items():
        renamed_table = translate_table(dataset, org_table)
        if renamed_table is None:
            continue
        out[renamed_table] = [
            translate_column(dataset, org_table, c) or c for c in (columns or [])
        ]
    return out
