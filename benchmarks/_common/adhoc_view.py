"""Ad-hoc LLM-generated view creation (for ``--view_adhoc``).

The LLM is asked to design a ``CREATE VIEW`` over the linked tables using
known foreign keys. The view is materialized in the SQLite DB and reused on
later questions that link the same table set.
"""

from __future__ import annotations

import ast
import sqlite3
from typing import List, Optional, Sequence, Tuple

from .clusters import find_foreign_keys_between_tables
from .llm import chat_with_chatgpt, chat_with_gemini
from .rename_mapping import fetch_org_fks, load_rename_mapping
from .schema import generate_schema_prompt, get_column_count
from .sql_exec import execute_sql


def find_fk_conditions_for_view_adhoc(
    db_path: str,
    tables: Sequence[str],
    rename_mode: bool = False,
    mapping_path: Optional[str] = None,
    ds_org_tables: Optional[Sequence[str]] = None,
    org_keyed: bool = False,
) -> List[str]:
    """Return ``T1.col=T2.col`` FK condition strings between pairs of ``tables``.

    Non-rename: ``find_foreign_keys_between_tables`` via PRAGMA.
    Rename: translate original FKs to the renamed namespace and filter to ``tables``.
    """
    if not tables or len(tables) < 2:
        return []
    if not rename_mode:
        return find_foreign_keys_between_tables(db_path, tables)
    if not ds_org_tables or not mapping_path:
        return []
    tset = {t.lower() for t in tables}
    table_to_view, view_org_to_renamed = load_rename_mapping(mapping_path, org_keyed)
    out = set()
    for from_t, from_c, ref_t, ref_c in fetch_org_fks(db_path, ds_org_tables):
        from_view = table_to_view.get(from_t.lower())
        ref_view = table_to_view.get(ref_t.lower())
        if not from_view or not ref_view:
            continue
        if from_view.lower() not in tset or ref_view.lower() not in tset:
            continue
        from_renamed = view_org_to_renamed.get(from_view, {}).get(from_c.lower())
        ref_renamed = view_org_to_renamed.get(ref_view, {}).get(ref_c.lower())
        if not from_renamed or not ref_renamed:
            continue
        out.add(f"{from_view}.{from_renamed}={ref_view}.{ref_renamed}")
    return sorted(out)


_ADHOC_VIEW_PROMPT = """You are a database expert. Please give me the SQL script for creating the joined table on foreign keys.
The new view name should be in the format of `table1_join_table2` where table1 and table2 are the names of the tables that are joined together.
Keep all the original column, unless there is a name conflict.
In that case, change those columns from table1 into `table1_column`, and those columns from table2 into `table2_column`, only need to change the columns that has a name conflict.

Here is an example task:
###
Database Schema
CREATE TABLE Examination
(
    ID                 INTEGER          null,
    `Examination Date` DATE         null,
    `aCL IgG`          REAL        null,
    `aCL IgM`          REAL        null,
    ANA                INTEGER          null,
    `ANA Pattern`      TEXT null,
    `aCL IgA`          INTEGER          null,
    Diagnosis          TEXT null,
    KCT                TEXT null,
    RVVT               TEXT null,
    LAC                TEXT null,
    Symptoms           TEXT null,
    Thrombosis         INTEGER          null,
    foreign key (ID) references Patient (ID)
            on update cascade on delete cascade
)

CREATE TABLE Patient
(
    ID           INTEGER default 0 not null
        primary key,
    SEX          TEXT  null,
    Birthday     DATE          null,
    Description  DATE          null,
    `First Date` DATE          null,
    Admission    TEXT  null,
    Diagnosis    TEXT  null
)
###

Tables to be joined: ['Patient', 'Examination']
Join conditions: ['Examination.ID = Patient.ID']
New table name: Patient_join_Examination

Please respond with a JSON object structured as follows:

{{
    "chain_of_thought_reasoning": "The foreign key on these tables are the Patient.ID and Examination.ID and it is also in the join conditions. We need to join the Patient and Examination tables on the ID column. The new table name should be Patient_join_Examination. All columns from the Patient table has no conflict except the ID columns, so ID from Patient is renamed to Patient_ID, and ID from the Examination table is renamed to Examination_ID.",
    "SQL": "CREATE VIEW `Patient_join_Examination` AS SELECT `Patient`.`ID` AS `Patient_ID`, `Patient`.`SEX` AS `SEX`, `Patient`.`Birthday` AS `Birthday`, `Patient`.`Description` AS `Description`, `Patient`.`First Date` AS `First Date`, `Patient`.`Admission` AS `Admission`, `Patient`.`Diagnosis` AS `Diagnosis`, `Examination`.`ID` AS `Examination_ID`, `Examination`.`Examination Date` AS `Examination Date`, `Examination`.`aCL IgG` AS `aCL IgG`, `Examination`.`aCL IgM` AS `aCL IgM`, `Examination`.`ANA` AS `ANA`, `Examination`.`ANA Pattern` AS `ANA Pattern`, `Examination`.`aCL IgA` AS `aCL IgA`, `Examination`.`Diagnosis` AS `Diagnosis`, `Examination`.`KCT` AS `KCT`, `Examination`.`RVVT` AS `RVVT`, `Examination`.`LAC` AS `LAC`, `Examination`.`Symptoms` AS `Symptoms`, `Examination`.`Thrombosis` AS `Thrombosis` FROM `Patient` JOIN `Examination` ON `Examination`.`ID` = `Patient`.`ID`;"
}}

###
The new view name should be in the format of `table1_join_table2_join_...` where tables are joined together.
Keep all the original columns, unless there is a name conflict.
In that case, change those columns from tableA into `tableA_column`, and those columns from tableB into `tableB_column`, only need to change the columns that has a name conflict.
Now, here is a new schema for creating a new view:
{base_schema_for_prompt}

###

Tables to be joined: {tables_list}
Join conditions: {fk_conditions}
New table name: {view_name}

Please respond with a JSON object structured as follows, and make sure each entry is there and follows the same format as the given format:
{{
    "chain_of_thought_reasoning": "Your thought process on how you arrived at the final SQL query",
    "SQL": "The CREATE VIEW SQL query for the new table based on the join conditions as well as the new column names."
}}

Carefully read the given schema, make sure all columns are there for the given table, do not hallucinate and mix up the columns between tables. If you follow all the instructions and answer correctly, I will give you 1 million dollars."""


_CONN_TIMEOUT = 60          # seconds
_BUSY_PRAGMA_MS = 30_000    # milliseconds


def create_adhoc_view(
    db_path: str,
    tables: Sequence[str],
    fk_conditions: Sequence[str],
    model: str,
    is_gemini: bool,
    num_rows: int = 3,
    max_attempts: int = 3,
    excluded_views: Optional[Sequence[str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Ask the LLM for a CREATE VIEW over ``tables``, run it, and return
    ``(view_name, view_schema_prompt)``. Returns ``(None, None)`` on failure.

    If the view already exists in the DB, reuse it (no drop/recreate) — but
    only if its name is NOT in ``excluded_views`` (the pre-defined
    org_views/renamed_views pool). If the intended ``view_name`` itself
    collides with an excluded name, bail out to avoid stomping on a
    pre-existing cluster view.
    """
    if len(tables) < 2 or not fk_conditions:
        return None, None
    view_name = "_join_".join(tables)

    excluded_lc = {v.lower() for v in (excluded_views or [])}
    if view_name.lower() in excluded_lc:
        print(
            f"[adhoc view] ⛔ intended name {view_name!r} collides with a "
            f"pre-defined (cluster) view — falling back to base schema"
        )
        return None, None

    base_pieces: List[str] = []
    for t in tables:
        try:
            base_pieces.append(
                generate_schema_prompt(
                    db_path=db_path, num_rows=num_rows, no_join=False, target_table=t
                )
            )
        except Exception:
            continue
    base_schema_for_prompt = "\n\n".join(base_pieces)

    prompt = _ADHOC_VIEW_PROMPT.format(
        base_schema_for_prompt=base_schema_for_prompt,
        tables_list=list(tables),
        fk_conditions=list(fk_conditions),
        view_name=view_name,
    )

    def _view_status() -> str:
        """Return ``'missing' | 'valid' | 'broken'`` for ``view_name``."""
        try:
            conn = sqlite3.connect(db_path, timeout=_CONN_TIMEOUT)
            cur = conn.cursor()
            try:
                cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='view' AND lower(name)=lower(?)",
                    (view_name,),
                )
                row = cur.fetchone()
                if not row:
                    return "missing"
                try:
                    cur.execute(f"SELECT * FROM `{row[0]}` LIMIT 1")
                    cur.fetchone()
                    return "valid"
                except Exception:
                    return "broken"
            finally:
                cur.close()
                conn.close()
        except Exception:
            return "missing"

    def _drop_view() -> bool:
        try:
            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=_CONN_TIMEOUT)
            cur = conn.cursor()
            cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
            execute_sql(cur, f"DROP VIEW IF EXISTS `{view_name}`")
            cur.close()
            conn.close()
            return True
        except Exception as _e:
            print(
                f"[adhoc view]    ⚠️  could not DROP broken view {view_name!r}: "
                f"{type(_e).__name__}: {_e}"
            )
            return False

    status = _view_status()
    if status == "valid":
        if view_name.lower() in excluded_lc:
            print(
                f"[adhoc view] ⛔ existing view {view_name!r} is in the pre-defined "
                f"pool — refusing to reuse; falling back to base schema"
            )
            return None, None
        print(f"[adhoc view] 🔁 reusing existing view {view_name!r} (valid, no recreate)")
        try:
            view_schema = generate_schema_prompt(
                db_path=db_path, num_rows=num_rows, no_join=False, target_table=view_name
            )
            return view_name, view_schema
        except Exception as e:
            print(
                f"[adhoc view]    ⚠️  reading existing view schema failed: "
                f"{type(e).__name__}: {e} — dropping and recreating"
            )
            _drop_view()
    elif status == "broken":
        print(
            f"[adhoc view] ⚠️  existing view {view_name!r} is BROKEN — "
            f"dropping before recreate"
        )
        _drop_view()

    print(f"[adhoc view] 🛠️  creating view {view_name!r}")
    print(f"[adhoc view]    tables ({len(tables)}): {list(tables)}")
    print(f"[adhoc view]    fk_conditions ({len(fk_conditions)}): {list(fk_conditions)}")
    print(f"[adhoc view]    model={model!r} (gemini={is_gemini})")

    for attempt in range(max_attempts):
        try:
            print(f"[adhoc view]    → LLM attempt {attempt + 1}/{max_attempts}")
            if is_gemini:
                resp = chat_with_gemini(prompt, model=model, response_fields={"SQL": str})
            else:
                resp = chat_with_chatgpt(prompt, model=model)
            if resp.find("```json") != -1:
                resp = resp[resp.find("```json"):]
            parsed = ast.literal_eval(resp.replace("```json", "").replace("```", ""))
            create_sql = parsed["SQL"]
            preview = " ".join(str(create_sql).split())
            print(f"[adhoc view]    LLM CREATE VIEW (first 200 chars): {preview[:200]}")

            _drop_view()

            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=_CONN_TIMEOUT)
            conn.text_factory = bytes
            cur = conn.cursor()
            try:
                cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
                execute_sql(cur, create_sql)
            finally:
                cur.close()
                conn.close()

            view_schema = generate_schema_prompt(
                db_path=db_path, num_rows=num_rows, no_join=False, target_table=view_name
            )
            print(
                f"[adhoc view]    ✅ created {view_name!r} "
                f"(schema {len(view_schema)} chars)"
            )
            return view_name, view_schema
        except Exception as e:
            print(
                f"[adhoc view]    ❌ attempt {attempt + 1}/{max_attempts} failed: "
                f"{type(e).__name__}: {e}"
            )
            _drop_view()
            continue
    print(
        f"[adhoc view]    ⛔ giving up on {view_name!r} after {max_attempts} attempts — "
        f"fall back to base schema"
    )
    return None, None


def check_auto_views_have_matching_columns(
    sqlite_path: str,
    selected_views: Sequence[str],
    prefix: str,
    check_from_clause: bool = False,
) -> List:
    """Validate that adhoc views report the same column count as their base
    tables' columns combined. Returns a list of mismatch entries (empty if all
    views align).
    """
    import re

    conn = sqlite3.connect(sqlite_path)
    mismatches: List = []

    for view_name in selected_views:
        if not check_from_clause and not view_name.startswith(prefix):
            continue

        base_tables: List[str] = []
        if check_from_clause:
            try:
                res = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='view' AND name=?",
                    (view_name,),
                ).fetchone()

                if res and res[0]:
                    sql_def = res[0]
                    matches = re.findall(
                        r'(?:FROM|JOIN)\s+["\']?(\w+)["\']?', sql_def, re.IGNORECASE
                    )
                    if matches:
                        base_tables = matches
            except Exception as e:
                mismatches.append((view_name, "N/A", f"sql_lookup_error: {str(e)}"))
                continue
        else:
            base_tables = [view_name.replace(prefix, "", 1)]

        if not base_tables:
            mismatches.append((view_name, "N/A", "could_not_determine_base_tables"))
            continue

        try:
            view_cols = get_column_count(conn, view_name)
            total_base_cols = sum(get_column_count(conn, t) for t in base_tables)
            if view_cols != total_base_cols:
                mismatches.append({
                    "view": view_name,
                    "tables_found": base_tables,
                    "view_count": view_cols,
                    "expected_sum": total_base_cols,
                })
        except Exception as e:
            mismatches.append((view_name, str(base_tables), f"error: {str(e)}"))

    conn.close()
    return mismatches
