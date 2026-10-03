"""Score an arm's final SQL and write it into nl2sql_<ds>.csv.

Columns follow basesql's naming with an ``autolink_`` prefix:

    autolink_sql<suffix>             the selected SQL
    autolink_sql<suffix>_result      1 if it matches the gold SQL under
                                     AutoLink's own comparator

The linked schema handed to generation goes to nl2sql_<ds>_schemas.parquet,
keyed by row_index, as ``autolink_schema<suffix>``.
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import sqlite3
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ldd_config as C  # noqa: E402
from sql_selection import compare_pandas_table  # noqa: E402  (AutoLink's own)

EXEC_TIMEOUT_S = 30


def _exec_df(db: str, sql: str):
    """DataFrame, or None if the query fails. Mirrors AutoLink's executor."""
    conn = None
    try:
        conn = sqlite3.connect(db, timeout=EXEC_TIMEOUT_S)
        deadline = time.monotonic() + EXEC_TIMEOUT_S
        conn.set_progress_handler(
            lambda dl=deadline: 1 if time.monotonic() > dl else 0, 1000)
        cur = conn.execute(str(sql))
        cols = [d[0] for d in cur.description] if cur.description else []
        return pd.DataFrame(cur.fetchall(), columns=cols)
    except sqlite3.Error:
        return None          # unrunnable only; a bug here must surface
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def ex_match(db: str, gold: str, pred: str) -> bool:
    """AutoLink's own comparator, imported from sql_selection.py.

    compare_pandas_table is Spider 2.0's official comparator and the rule
    AutoLink's generation prompt is written against: the result "can be more
    than what is required by the question, but it must not be less"
    (config.py:392), so extra predicted columns are tolerated.
    """
    if not str(pred).strip():
        return False
    g, p = _exec_df(db, gold), _exec_df(db, pred)
    if g is None or p is None:
        return False
    if g.empty:
        return bool(p.empty)
    if p.empty:
        return False
    try:
        return bool(compare_pandas_table(p, g, ignore_order=True))
    except Exception:
        return False


def read_final_sql(log_path: str, task: str, instance_id: str) -> str:
    """The selected SQL from sql_selection's final/ directory."""
    base = os.path.join(log_path, "sql_selection", "final", instance_id)
    if not os.path.isdir(base):
        return ""
    # selected.sql FIRST. dump_final_selection writes it for every instance, and
    # for instances whose query failed it also writes result.txt holding an error
    # string ("No data found for the specified query."). The old glob fallback
    # sorted *.sql and *.txt together, so "result.txt" < "selected.sql" and the
    # error message was exported AS the prediction -- scoring those rows 0.
    for name in ("selected.sql", "sql.txt", "final.sql", "final.txt"):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return open(p, encoding="utf-8", errors="replace").read().strip()
    cands = sorted(glob.glob(os.path.join(base, "*.sql")))   # .sql only
    return (open(cands[0], encoding="utf-8", errors="replace").read().strip()
            if cands else "")


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=["bird", "spider"], default="bird")
    p.add_argument("--rename", action="store_true")
    p.add_argument("--view", action="store_true")
    p.add_argument("--cluster", action="store_true")
    p.add_argument("--mode", choices=["opt1", "opt2"], default="opt1")
    p.add_argument("--task", default="ldd")
    p.add_argument("--no_write", action="store_true")
    a = p.parse_args()

    arm = C.Arm(dataset=a.dataset, rename=a.rename, view=a.view,
                cluster=a.cluster, mode=a.mode)
    arm.validate()

    qpath = os.path.join(C.HERE, f"questions_{arm.dataset}{arm.suffix}.json")
    with open(qpath, encoding="utf-8") as f:
        questions = json.load(f)

    # EX is scored against the arm's own database copy, which is a byte copy of
    # merged_<ds>.sqlite -- gold SQL from the CSV runs against the same objects.
    db = os.path.join(C.HERE, "resource", "databases", "spider2-localdb",
                      f"{arm.db_name}.sqlite")
    if not os.path.exists(db):
        db = C.MERGED_DB[a.dataset]

    nl = pd.read_csv(C.NL2SQL_CSV[a.dataset])
    # Gold comes from the EVAL csv, not the history csv. nl2sql_<ds>.csv and
    # sample_<ds>.csv are disjoint question sets (0/767 row-aligned, different
    # sets entirely) -- sample_<ds>.csv is the history pool only. Reading gold
    # from it scored every prediction against an unrelated question.
    #
    # The gold SQL is in the original namespace, which is correct for every arm:
    # renamed tables and cluster views are views over the same base data, so the
    # reference RESULT SET is identical regardless of the arm's namespace.
    gold_col = "SQL"

    for col in (arm.sql_col, arm.result_col):
        if col not in nl.columns:
            nl[col] = None

    # The linked SCHEMA never goes in the CSV: it is CREATE-TABLE text with
    # sample rows (up to 156 KB per cell, 363 k newlines per column) and such
    # columns had grown nl2sql_bird.csv to 193 MB, unopenable in any spreadsheet.
    # It goes to a parquet sidecar keyed by row_index instead.
    schemas: dict = {}
    n = ok = missing = 0
    for iid, info in questions.items():
        i = int(info["row_index"])
        n += 1
        schema_path = os.path.join(arm.log_path, "final_schema_prompts", f"{iid}.txt")
        schema = open(schema_path, encoding="utf-8").read() \
            if os.path.exists(schema_path) else ""
        sql = read_final_sql(arm.log_path, a.task, iid)
        if not sql:
            missing += 1
        gold = str(nl.at[i, gold_col])
        res = int(ex_match(db, gold, sql)) if sql else 0
        ok += res
        schemas[i] = schema
        nl.at[i, arm.sql_col] = sql
        nl.at[i, arm.result_col] = res

    print(f"=== {arm.dataset} {arm.suffix} ===")
    print(f"  gold column      : {gold_col}")
    print(f"  scored           : {n}")
    print(f"  no SQL produced  : {missing}")
    print(f"  EX               : {ok}/{n} = {100*ok/max(1,n):.2f}%")
    print(f"  columns          : {arm.sql_col}")
    print(f"                     {arm.result_col}")

    if a.no_write:
        print("\n  --no_write: CSV untouched")
        return
    nl.to_csv(C.NL2SQL_CSV[a.dataset], index=False)
    if schemas:
        sp = os.path.join(os.path.dirname(C.NL2SQL_CSV[a.dataset]),
                          f"nl2sql_{a.dataset}_schemas.parquet")
        new = pd.DataFrame({"row_index": sorted(schemas),
                            arm.schema_col: [schemas[r] for r in sorted(schemas)]})
        if os.path.exists(sp):
            old = pd.read_parquet(sp)
            if arm.schema_col in old.columns:
                old = old.drop(columns=[arm.schema_col])
            new = old.merge(new, on="row_index", how="outer")
        new.to_parquet(sp, index=False, compression="zstd")
        print(f"  schemas          -> {sp} ({arm.schema_col})")
    print(f"\n  wrote {os.path.basename(C.NL2SQL_CSV[a.dataset])}")


if __name__ == "__main__":
    main()
