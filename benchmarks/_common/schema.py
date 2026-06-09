"""Database schema readers and prompt builders."""

from __future__ import annotations

import sqlite3
from typing import List, Optional, Union

from func_timeout import func_set_timeout
from langchain.sql_database import SQLDatabase


def get_database_schema(
    DB_URI: str,
    table_name: Union[str, List[str], None] = None,
    sample_rows: int = 3,
    include_views: bool = False,
) -> str:
    """Get the database schema via LangChain's ``SQLDatabase`` wrapper.

    If ``table_name`` is a string or list, only those tables are returned —
    and reflection is restricted to that same allowlist. This matters when
    the DB contains leftover views from prior ``prep_database`` runs that may
    reference columns the current rename no longer exposes: without an
    ``include_tables`` filter, ``MetaData.reflect()`` PRAGMAs every view and
    crashes on the stale ones. We treat the caller-provided list (or, in
    pipelines, the prep-JSON's active-view list) as the source of truth.
    """
    if isinstance(table_name, str):
        wanted = [table_name]
    elif isinstance(table_name, list):
        wanted = list(table_name)
    else:
        wanted = None

    db = SQLDatabase.from_uri(
        "sqlite:///" + DB_URI,
        sample_rows_in_table_info=sample_rows,
        view_support=include_views,
        include_tables=wanted,
    )

    if wanted is None:
        return db.get_table_info_no_throw()
    return db.get_table_info_no_throw(table_names=wanted)


def get_database_schema_manual(
    db_path: str,
    table_names,
    sample_rows: int = 3,
) -> str:
    """Drop-in replacement for ``get_database_schema`` that mimics its output
    format but reads rows via a raw sqlite cursor (no SQLAlchemy type coercion).

    Produces ``CREATE TABLE <name> (...)`` — even for views — plus a
    ``/* N rows from <name> table: ... */`` sample block. Used as a fallback
    when ``get_database_schema``'s fromisoformat coercion trips on
    DATE-as-int columns.
    """
    if isinstance(table_names, str):
        table_names = [table_names]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    pieces: List[str] = []

    for name in table_names:
        cols = cur.execute(f'PRAGMA table_info("{name}")').fetchall()
        if not cols:
            continue

        col_lines: List[str] = []
        pks: List = []
        for cid, col_name, col_type, notnull, dflt, pk in cols:
            parts = [col_name]
            if col_type:
                parts.append(col_type)
            if notnull:
                parts.append("NOT NULL")
            if dflt is not None:
                parts.append(f"DEFAULT {dflt}")
            col_lines.append("\t" + " ".join(parts))
            if pk and pk > 0:
                pks.append((pk, col_name))

        if pks:
            pk_names = ", ".join(n for _, n in sorted(pks))
            col_lines.append(f"\tPRIMARY KEY ({pk_names})")

        try:
            fks = cur.execute(f'PRAGMA foreign_key_list("{name}")').fetchall()
        except sqlite3.DatabaseError:
            fks = []
        for fk in fks:
            col_lines.append(f"\tFOREIGN KEY({fk[3]}) REFERENCES {fk[2]} ({fk[4]})")

        create_stmt = f"CREATE TABLE {name} (\n" + ", \n".join(col_lines) + "\n)"

        sample_block = ""
        if sample_rows and sample_rows > 0:
            try:
                rows = cur.execute(
                    f'SELECT * FROM "{name}" LIMIT {int(sample_rows)}'
                ).fetchall()
            except Exception:
                rows = []
            col_names = [c[1] for c in cols]
            header = "\t".join(col_names)
            body_lines = [
                "\t".join("" if v is None else str(v) for v in row) for row in rows
            ]
            body = "\n".join(body_lines)
            sample_block = (
                f"\n\n/*\n{len(rows)} rows from {name} table:\n{header}\n{body}\n*/"
            )

        pieces.append(create_stmt + sample_block)

    conn.close()
    return "\n\n".join(pieces)


@func_set_timeout(90)
def generate_schema_prompt(
    db_path: str,
    num_rows: Optional[int] = None,
    no_join: bool = False,
    target_table: str = "all",
    extracted_values: Optional[dict] = None,
    alias_map: Optional[dict] = None,
    alias_namespace: str = "workload",
) -> str:
    """Build a ``CREATE TABLE/VIEW ...`` + sample-rows schema prompt.

    Optional ``alias_map`` (``{table: {col: {namespace: comment}}}``) injects
    inline ``-- <namespace> alias: ...`` comments for matching column lines.
    """
    full_schema_prompt_list: List[str] = []
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if no_join:
        cursor.execute(
            """SELECT name FROM sqlite_master
                          WHERE type='table' AND name != 'sqlite_sequence'
                          AND name != 'sqlite_stat1' AND name not like '%_join_%';"""
        )
    else:
        if target_table != "all":
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type in ('table', 'view') "
                "AND lower(name) = lower('{}');".format(target_table)
            )
        else:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type in ('table', 'view') "
                "AND name != 'sqlite_sequence' AND name != 'sqlite_stat1';"
            )

    tables = cursor.fetchall()
    schemas = {}

    if extracted_values is None:
        extracted_values = {}

    for table in tables:
        tname = table[0]
        if tname == "sqlite_sequence":
            continue

        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type in ('table','view') AND name=?",
            (tname,),
        )
        raw_sql = cursor.fetchone()[0]

        final_sql = raw_sql

        if alias_map and tname in alias_map:
            lines = raw_sql.split("\n")
            new_lines = []

            for line in lines:
                stripped = line.strip()
                tokens = stripped.split()

                if tokens:
                    raw_col_token = tokens[0].strip("`\"")

                    if (
                        raw_col_token in alias_map[tname]
                        and alias_namespace in alias_map[tname][raw_col_token]
                        and "--" not in stripped
                    ):
                        alias_comment = alias_map[tname][raw_col_token][alias_namespace]
                        line = f"{line}    -- {alias_namespace} alias: {alias_comment}"

                new_lines.append(line)

            final_sql = "\n".join(new_lines)

        schemas[tname] = final_sql

        if num_rows:
            cur_table = tname
            cursor.execute("SELECT * FROM `{}` LIMIT {}".format(cur_table, num_rows))
            column_names = [description[0] for description in cursor.description]
            db_rows = cursor.fetchall()

            extracted_rows = []
            table_extracted = {
                col.split(".", 1)[1]: vals
                for col, vals in extracted_values.items()
                if col.split(".", 1)[0].lower() == cur_table.lower()
            }

            if table_extracted:
                max_len = max(len(vs) for vs in table_extracted.values())
                for i in range(max_len):
                    row_dict = {c: "" for c in column_names}
                    for col, vals in table_extracted.items():
                        if col in row_dict and i < len(vals):
                            row_dict[col] = vals[i]
                    extracted_rows.append(tuple(row_dict[c] for c in column_names))

            final_rows = list(db_rows) + extracted_rows

            rows_prompt = nice_look_table(column_names=column_names, values=final_rows)

            verbose_prompt = "/* \n {} rows from {}: \n {} \n */".format(
                len(final_rows), cur_table, rows_prompt
            )

            schemas[tname] = schemas[tname] + "\n\n" + verbose_prompt

    for _, v in schemas.items():
        full_schema_prompt_list.append(v)

    schema_prompt = "\n\n".join(full_schema_prompt_list)

    return schema_prompt


def nice_look_table(column_names: list, values: list) -> str:
    """Format column names + rows as a right-justified text table."""
    rows: List[str] = []
    widths = [
        max(len(str(value[i])) for value in values + [column_names])
        for i in range(len(column_names))
    ]
    header = "".join(
        f"{column.rjust(width)} " for column, width in zip(column_names, widths)
    )
    for value in values:
        row = "".join(f"{str(v).rjust(width)} " for v, width in zip(value, widths))
        rows.append(row)
    return header + "\n" + "\n".join(rows)


def list_tables_and_views(sqlite_path: str) -> List[str]:
    """Sorted list of user-defined tables and views in a SQLite database."""
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type IN ('table', 'view')
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
        """
    )
    results = [row[0] for row in cursor.fetchall()]
    conn.close()
    return results


def get_column_count(conn: sqlite3.Connection, table_or_view_name: str) -> int:
    """Return the number of columns in a SQLite table or view."""
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info("{table_or_view_name}");')
    return len(cur.fetchall())
