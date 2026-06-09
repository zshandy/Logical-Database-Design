"""Name-mapping (rename) helpers: load JSON mapping, fetch and translate FKs."""

from __future__ import annotations

import json
import sqlite3
from typing import Dict, List, Sequence, Tuple


def load_rename_mapping(
    mapping_path: str,
) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """Load a name-mapping JSON in **bird-style** (org-keyed) format.

    Returns ``(table_to_view, view_org_to_renamed)`` where:
      - ``table_to_view``: ``{org_table_lower: renamed_view}`` (case-insensitive keys)
      - ``view_org_to_renamed``: ``{renamed_view: {org_col_lower: renamed_col}}``

    Supports two on-disk shapes:

    1. **Consolidated** (current ``prep_database`` output):
       ``{"rename": {"table_to_view": ..., "column_mapping": ...}, ...}``
    2. **Legacy** flat format:
       ``{"table_to_view": ..., "column_mapping": ...}``

    The inner column dict is always bird-style:
    ``column_mapping[view] = {original_col: renamed_col}``.
    Legacy spider files in the *opposite* direction were migrated via
    ``benchmarks/flip_spider_mapping.py``.
    """
    with open(mapping_path, encoding="utf-8") as f:
        data = json.load(f)
    # Shape sniffer
    if isinstance(data.get("rename"), dict) and "table_to_view" in data["rename"]:
        m = data["rename"]
    elif "table_to_view" in data:
        m = data
    else:
        raise KeyError(
            f"mapping file {mapping_path} has neither "
            f"'rename.table_to_view' (consolidated) nor 'table_to_view' (legacy)."
        )
    table_to_view = {k.lower(): v for k, v in m["table_to_view"].items()}
    column_mapping = m["column_mapping"]
    view_org_to_renamed: Dict[str, Dict[str, str]] = {}
    for view, cols in column_mapping.items():
        view_org_to_renamed[view] = {k.lower(): v for k, v in cols.items()}
    return table_to_view, view_org_to_renamed


def load_active_views(mapping_path: str) -> Tuple[List[str], List[str]]:
    """Return ``(active_tables, cluster_views)`` lists from a prep-config JSON.

    ``active_tables`` is the list of table/view names the downstream pipeline
    should expose to the LLM. Sources, in priority order:
      1. top-level ``tables`` (current prep_database output; renamed views in
         ``--rename`` mode, base tables otherwise).
      2. ``rename.table_to_view.values()`` (consolidated rename section).
      3. ``table_to_view.values()`` (legacy flat ``name_mapping_*.json``).

    ``cluster_views`` comes from ``view.cluster_views`` (current) or is empty
    when the file pre-dates the view phase. Pipelines use these as the source
    of truth so stale leftover views in the DB are ignored.
    """
    with open(mapping_path, encoding="utf-8") as f:
        data = json.load(f)
    active_tables: List[str] = []
    if isinstance(data.get("tables"), list) and data["tables"]:
        active_tables = sorted({str(t) for t in data["tables"]})
    elif isinstance(data.get("rename"), dict) and "table_to_view" in data["rename"]:
        active_tables = sorted({str(v) for v in data["rename"]["table_to_view"].values()})
    elif "table_to_view" in data:
        active_tables = sorted({str(v) for v in data["table_to_view"].values()})
    cluster_views: List[str] = []
    if isinstance(data.get("view"), dict) and "cluster_views" in data["view"]:
        seen = set()
        for v in data["view"]["cluster_views"]:
            sv = str(v)
            if sv not in seen:
                seen.add(sv)
                cluster_views.append(sv)
    return active_tables, cluster_views


def load_active_columns(mapping_path: str) -> dict:
    """Return the history-CSV column-name defaults recorded by the prep run.

    Returns a dict with any subset of: ``question``, ``sql``, ``gt_tables``,
    ``view_sql``. Pipelines should treat these as the default columns to read
    when the user did not pass an explicit ``--*_col`` flag.

    Returns an empty dict if the JSON has no ``columns`` section (legacy
    files), so callers can do ``cols.get("sql", "SQL")`` etc.
    """
    with open(mapping_path, encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("columns")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


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
) -> str:
    """Translate each FK declared between ``org_tables`` into the renamed namespace
    and return a ``Foreign Keys:`` block string.

    Returns ``""`` if no FKs translate cleanly.
    """
    table_to_view, view_org_to_renamed = load_rename_mapping(mapping_path)
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
