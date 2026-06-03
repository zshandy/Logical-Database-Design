"""Name-mapping (rename) helpers: load JSON mapping, fetch and translate FKs."""

from __future__ import annotations

import json
import sqlite3
from typing import Dict, List, Sequence, Tuple


def load_rename_mapping(
    mapping_path: str,
    org_keyed_columns: bool = False,
) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """Load a name-mapping JSON.

    Returns ``(table_to_view, view_org_to_renamed)`` where:
      - ``table_to_view``: ``{org_table_lower: renamed_view}`` (case-insensitive keys)
      - ``view_org_to_renamed``: ``{renamed_view: {org_col_lower: renamed_col}}``

    ``org_keyed_columns`` controls how the inner column dict is interpreted:
      - ``False`` (spider): inner dict is ``{renamed_col: org_col}``
      - ``True``  (bird):   inner dict is ``{org_col: renamed_col}``
    """
    with open(mapping_path, encoding="utf-8") as f:
        m = json.load(f)
    table_to_view = {k.lower(): v for k, v in m["table_to_view"].items()}
    column_mapping = m["column_mapping"]
    view_org_to_renamed: Dict[str, Dict[str, str]] = {}
    for view, cols in column_mapping.items():
        if org_keyed_columns:
            view_org_to_renamed[view] = {k.lower(): v for k, v in cols.items()}
        else:
            view_org_to_renamed[view] = {v.lower(): k for k, v in cols.items()}
    return table_to_view, view_org_to_renamed


def fetch_org_fks(
    db_path: str,
    org_tables: Sequence[str],
) -> List[Tuple[str, str, str, str]]:
    """Return ``(from_table, from_col, ref_table, ref_col)`` tuples for FKs
    declared between tables in ``org_tables``. Reads PRAGMA foreign_key_list.
    """
    org_lower = {t.lower(): t for t in org_tables}
    out: List[Tuple[str, str, str, str]] = []
    seen = set()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        for t in org_tables:
            try:
                rows = cur.execute(f"PRAGMA foreign_key_list('{t}')").fetchall()
            except sqlite3.DatabaseError:
                continue
            for row in rows:
                # (id, seq, ref_table, from_col, to_col, on_update, on_delete, match)
                ref_table = row[2]
                from_col = row[3]
                to_col = row[4]
                if not ref_table or not from_col or not to_col:
                    continue
                if ref_table.lower() not in org_lower:
                    continue
                key = (t.lower(), from_col.lower(), ref_table.lower(), to_col.lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append((t, from_col, ref_table, to_col))
    finally:
        conn.close()
    return out


def build_renamed_fk_block(
    db_path: str,
    org_tables: Sequence[str],
    mapping_path: str,
    org_keyed_columns: bool = False,
) -> str:
    """Translate each FK declared between ``org_tables`` into the renamed namespace
    and return a ``Foreign Keys:`` block string.

    Returns ``""`` if no FKs translate cleanly.
    """
    table_to_view, view_org_to_renamed = load_rename_mapping(
        mapping_path, org_keyed_columns
    )
    fks = fetch_org_fks(db_path, org_tables)

    lines: List[str] = []
    skipped: List[Tuple[str, str, str, str, str]] = []
    for from_t, from_c, ref_t, ref_c in fks:
        from_view = table_to_view.get(from_t.lower())
        ref_view = table_to_view.get(ref_t.lower())
        if not from_view or not ref_view:
            skipped.append((from_t, from_c, ref_t, ref_c, "table not in mapping"))
            continue
        from_renamed = view_org_to_renamed.get(from_view, {}).get(from_c.lower())
        ref_renamed = view_org_to_renamed.get(ref_view, {}).get(ref_c.lower())
        if not from_renamed or not ref_renamed:
            skipped.append((from_t, from_c, ref_t, ref_c, "column not in mapping"))
            continue
        lines.append(f"{from_view}.{from_renamed} = {ref_view}.{ref_renamed}")

    if skipped:
        print(f"⚠️  {len(skipped)}/{len(fks)} FK lines could not be translated:")
        for s in skipped[:10]:
            print(f"     {s}")
        if len(skipped) > 10:
            print(f"     ... and {len(skipped) - 10} more")

    if not lines:
        return ""

    return "Foreign Keys:\n" + "\n".join(sorted(set(lines))) + "\n\n"
