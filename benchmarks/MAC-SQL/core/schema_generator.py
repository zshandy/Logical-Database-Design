# -*- coding: utf-8 -*-
"""
Simplified schema generator that reads directly from SQLite database.
Generates schema prompts without column descriptions.
"""

import sqlite3
from typing import List, Dict, Optional, Tuple


def get_table_columns(cursor: sqlite3.Cursor, table_name: str) -> List[str]:
    """Get column names for a table using PRAGMA."""
    cursor.execute(f"PRAGMA table_info(`{table_name}`)")
    columns = cursor.fetchall()
    return [col[1] for col in columns]  # col[1] is the column name


def get_column_values(cursor: sqlite3.Cursor, table_name: str, column_name: str, limit: int = 6) -> List:
    """
    Get sample values for a column, ordered by frequency (most common first).
    Returns up to `limit` values.
    """
    try:
        sql = f"SELECT `{column_name}` FROM `{table_name}` GROUP BY `{column_name}` ORDER BY COUNT(*) DESC LIMIT {limit}"
        cursor.execute(sql)
        values = cursor.fetchall()
        return [v[0] for v in values]
    except Exception as e:
        print(f"Error getting values for {table_name}.{column_name}: {e}")
        return []


def should_skip_column_values(column_name: str) -> bool:
    """Check if column should skip value examples (id, email, url columns)."""
    lower_name = column_name.lower()
    return (lower_name.endswith('id') or
            lower_name.endswith('email') or
            lower_name.endswith('url'))


def format_values(values: List) -> str:
    """Format values list as string for prompt."""
    if not values:
        return ''

    # Filter out None and empty strings, but track if None exists
    has_null = None in values
    filtered = [v for v in values if v is not None and str(v).strip() != '']

    if not filtered:
        return ''

    # Check for URLs or emails in text values
    for v in filtered:
        if isinstance(v, str):
            if 'http://' in v or 'https://' in v:
                return ''
            if '@' in v and '.' in v:  # Simple email check
                return ''
            if len(v) > 50:  # Skip long text values
                return ''

    # Take up to 6 values
    result = filtered[:6]

    # Add None back at the beginning if it existed
    if has_null:
        result.insert(0, None)

    return str(result)


def get_foreign_keys(cursor: sqlite3.Cursor, table_name: str) -> List[Tuple[str, str, str]]:
    """Get foreign keys for a table. Returns list of (from_col, to_table, to_col)."""
    cursor.execute(f"PRAGMA foreign_key_list(`{table_name}`)")
    fks = cursor.fetchall()
    # fk format: (id, seq, table, from, to, on_update, on_delete, match)
    return [(fk[3], fk[2], fk[4]) for fk in fks]


def generate_schema_prompt(
    db_path: str,
    tables: List[str],
    include_foreign_keys: bool = True
) -> Tuple[str, str]:
    """
    Generate schema prompt string from SQLite database.

    Args:
        db_path: Path to SQLite database file
        tables: List of table/view names to include
        include_foreign_keys: Whether to include foreign key information

    Returns:
        Tuple of (schema_string, foreign_keys_string)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    schema_parts = []
    all_fk_strings = []

    for table_name in tables:
        # Get columns for this table
        columns = get_table_columns(cursor, table_name)

        if not columns:
            print(f"Warning: Table '{table_name}' not found or has no columns")
            continue

        # Build column entries
        column_entries = []
        for col_name in columns:
            # Get value examples (skip for id/email/url columns)
            if should_skip_column_values(col_name):
                values_str = ''
            else:
                values = get_column_values(cursor, table_name, col_name, limit=6)
                values_str = format_values(values)

            # Format: (column_name. Value examples: [...].),
            if values_str:
                col_line = f"  ({col_name}. Value examples: {values_str}.),"
            else:
                col_line = f"  ({col_name}.),"

            column_entries.append(col_line)

        # Build table schema string (strip trailing comma like original)
        columns_str = "\n".join(column_entries).rstrip(',')
        table_schema = f"# Table: {table_name}\n[\n{columns_str}\n]"
        schema_parts.append(table_schema)

        # Get foreign keys for this table
        if include_foreign_keys:
            fks = get_foreign_keys(cursor, table_name)
            for from_col, to_table, to_col in fks:
                # Only include FK if the referenced table is in our list
                if to_table in tables:
                    fk_str = f"{table_name}.`{from_col}` = {to_table}.`{to_col}`"
                    if fk_str not in all_fk_strings:
                        all_fk_strings.append(fk_str)

    conn.close()

    schema_string = "\n".join(schema_parts)
    fk_string = "\n".join(all_fk_strings)

    return schema_string, fk_string


def get_all_tables(db_path: str) -> List[str]:
    """Get all table names from SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    return tables


def get_all_views(db_path: str) -> List[str]:
    """Get all view names from SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
    views = [row[0] for row in cursor.fetchall()]
    conn.close()
    return views


def generate_view_fk_string(db_path: str, views: List[str], mapping_path: str) -> str:
    """
    Generate FK string for views by mapping base table FKs to view names/columns.

    Args:
        db_path: Path to SQLite database
        views: List of view names to include
        mapping_path: Path to name_mapping.json

    Returns:
        FK string with view names and mapped column names
    """
    import json

    # Load the mapping
    with open(mapping_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    table_to_view = mapping.get('table_to_view', {})
    column_mapping = mapping.get('column_mapping', {})

    # Create reverse mapping: view -> base table (case-insensitive)
    view_to_table = {}
    for base_table, view_name in table_to_view.items():
        view_to_table[view_name.lower()] = base_table.lower()

    # Get the set of views we're interested in (lowercase for matching)
    views_lower = {v.lower(): v for v in views}

    # Get FKs from base tables
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    all_fk_strings = []

    # For each view, find its base table and get FKs
    for view_name in views:
        view_lower = view_name.lower()
        base_table = view_to_table.get(view_lower)
        if not base_table:
            continue

        # Get FKs for this base table
        cursor.execute(f"PRAGMA foreign_key_list(`{base_table}`)")
        fks = cursor.fetchall()

        for fk in fks:
            # fk format: (id, seq, to_table, from_col, to_col, on_update, on_delete, match)
            from_col = fk[3]
            to_table = fk[2].lower() if fk[2] else None
            to_col = fk[4]

            # Skip if any required field is None
            if not from_col or not to_table or not to_col:
                continue

            # Check if the referenced table has a corresponding view in our list
            to_view = None
            for vl, v_original in views_lower.items():
                if view_to_table.get(vl) == to_table:
                    to_view = v_original
                    break

            if not to_view:
                continue

            # Map column names to view column names
            view_col_map = column_mapping.get(view_name, {})
            to_view_col_map = column_mapping.get(to_view, {})

            # Map from_col (case-insensitive lookup)
            mapped_from_col = from_col
            for orig_col, new_col in view_col_map.items():
                if orig_col.lower() == from_col.lower():
                    mapped_from_col = new_col
                    break

            # Map to_col (case-insensitive lookup)
            mapped_to_col = to_col
            for orig_col, new_col in to_view_col_map.items():
                if orig_col.lower() == to_col.lower():
                    mapped_to_col = new_col
                    break

            fk_str = f"{view_name}.`{mapped_from_col}` = {to_view}.`{mapped_to_col}`"
            if fk_str not in all_fk_strings:
                all_fk_strings.append(fk_str)

    conn.close()
    return "\n".join(all_fk_strings)


def generate_renamed_fk_string(db_path: str, renamed_tables: List[str], mapping_path: str) -> str:
    """
    Generate FK string for spider renamed tables.

    Spider mapping format (inverted vs bird):
        table_to_view:   {original_table: renamed_table}
        column_mapping:  {renamed_table: {renamed_col: original_col}}

    Strategy: for each renamed table, find its base table, PRAGMA its FKs,
    then map the FK columns (which are in original naming) back to renamed
    column names via reverse-lookup in column_mapping.
    """
    import json

    with open(mapping_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    table_to_renamed = mapping.get('table_to_view', {})  # {orig_table: renamed_table}
    column_mapping = mapping.get('column_mapping', {})   # {renamed_table: {renamed_col: orig_col}}

    # Reverse: renamed_table -> orig_table (case-insensitive)
    renamed_to_table = {v.lower(): k for k, v in table_to_renamed.items()}
    # Set of renamed tables we're asked about
    renamed_set_lower = {t.lower(): t for t in renamed_tables}

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    all_fk_strings = []
    for renamed_name in renamed_tables:
        base_table = renamed_to_table.get(renamed_name.lower())
        if not base_table:
            continue

        cursor.execute(f"PRAGMA foreign_key_list(`{base_table}`)")
        fks = cursor.fetchall()

        for fk in fks:
            from_col = fk[3]
            to_table = fk[2]
            to_col = fk[4]
            if not from_col or not to_table or not to_col:
                continue

            # Find the renamed name of the referenced base table
            to_renamed = table_to_renamed.get(to_table)
            if not to_renamed:
                # case-insensitive fallback
                for k, v in table_to_renamed.items():
                    if k.lower() == to_table.lower():
                        to_renamed = v
                        break
            if not to_renamed or to_renamed.lower() not in renamed_set_lower:
                continue

            # Reverse-lookup renamed column names (inner dict is {renamed_col: orig_col})
            from_col_map = column_mapping.get(renamed_name, {})
            to_col_map = column_mapping.get(to_renamed, {})

            mapped_from_col = from_col
            for renamed_col, orig_col in from_col_map.items():
                if str(orig_col).lower() == from_col.lower():
                    mapped_from_col = renamed_col
                    break

            mapped_to_col = to_col
            for renamed_col, orig_col in to_col_map.items():
                if str(orig_col).lower() == to_col.lower():
                    mapped_to_col = renamed_col
                    break

            fk_str = f"{renamed_name}.`{mapped_from_col}` = {to_renamed}.`{mapped_to_col}`"
            if fk_str not in all_fk_strings:
                all_fk_strings.append(fk_str)

    conn.close()
    return "\n".join(all_fk_strings)


if __name__ == "__main__":
    # Example usage
    db_path = "D:\WORK\PhD\column retrieval\exp\merged_schema_fk.sqlite"
    tables = get_all_tables(db_path)
    print(f"Tables found: {tables}")

    schema_str, fk_str = generate_schema_prompt(db_path, tables)
    print("\n=== Schema ===")
    print(schema_str)
    print("\n=== Foreign Keys ===")
    print(fk_str)
