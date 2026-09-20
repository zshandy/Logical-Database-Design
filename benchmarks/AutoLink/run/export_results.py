"""Score an arm's final SQL and write three columns into nl2sql_<ds>.csv.

Columns follow basesql's naming with an ``autolink_`` prefix:

    autolink_schema<suffix>          the final linked schema handed to generation
    autolink_sql<suffix>             the selected SQL
    autolink_sql<suffix>_result      1 if it execution-matches the gold SQL

EX uses the same comparison as the TEMPLAR driver: ordered row comparison when
the gold SQL has an ORDER BY, multiset comparison otherwise.
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from typing import Any, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ldd_config as C  # noqa: E402
from sql_selection import compare_pandas_table  # noqa: E402  (AutoLink's own)

EXEC_TIMEOUT_S = 30


def _exec(db: str, sql: str) -> Tuple[bool, Any]:
    conn = None
    try:
        conn = sqlite3.connect(db, timeout=EXEC_TIMEOUT_S)
        conn.text_factory = bytes
        dl = time.monotonic() + EXEC_TIMEOUT_S
        conn.set_progress_handler(
            lambda dl=dl: 1 if time.monotonic() > dl else 0, 1000)
        return True, conn.execute(str(sql)).fetchall()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _norm(row: tuple) -> tuple:
    out = []
    for v in row:
        if v is None:
            out.append(None)
        elif isinstance(v, bytes):
            out.append(v.decode("utf-8", errors="replace"))
        else:
            out.append(str(v))
    return tuple(out)


def ex_match(db: str, gold: str, pred: str) -> bool:
    if not str(pred).strip():
        return False
    ok_g, g = _exec(db, gold)
    if not ok_g:
        return False
    ok_p, p = _exec(db, pred)
    if not ok_p:
        return False
    # LDD's compare_sql is SET equality -- `set(predicted) == set(gold)` -- and
    # every other pipeline in the paper is scored that way, so this must match it
    # exactly or AutoLink is not comparable to them. It previously used
    # Counter(...)== (multiset) plus an ORDER BY-triggered ordered compare, which
    # is strictly harsher: a prediction that adds DISTINCT returns the same set
    # but a different multiset, and scored 0 here while scoring 1 everywhere
    # else. That cost ~2.8 points of strict EX on BIRD, and because the reported
    # lenient metric is `strict OR compare_pandas_table`, it dragged lenient down
    # ~2.3 with it.
    gn = [_norm(r) for r in g]
    pn = [_norm(r) for r in p]
    return set(gn) == set(pn)


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


def lenient_match(db: str, gold: str, pred: str) -> bool:
    """AutoLink's OWN comparator, imported -- not reimplemented.

    compare_pandas_table (sql_selection.py, Spider 2.0's official comparator) is
    the rule AutoLink's generation prompt is written against: the result "can be
    more than what is required by the question, but it must not be less"
    (config.py:392), so extra predicted columns are tolerated. An earlier version
    of this function reimplemented that rule by hand and scored ~2.3 points low
    on BIRD, which is why it now calls the shipped code instead. Identical to
    analysis/pipelines/rescore_lenient.py, which produced the published numbers.
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

    lenient_col = f"{arm.result_col}_lenient"
    for col in (arm.schema_col, arm.sql_col, arm.result_col, lenient_col):
        if col not in nl.columns:
            nl[col] = None

    # The linked SCHEMA never goes in the CSV: it is CREATE-TABLE text with
    # sample rows (up to 156 KB per cell, 363 k newlines per column) and such
    # columns had grown nl2sql_bird.csv to 193 MB, unopenable in any spreadsheet.
    # It goes to a parquet sidecar keyed by row_index instead.
    schemas: dict = {}
    n = ok = ok_len = missing = 0
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
        # NO union. This column is AutoLink's shipped compare_pandas_table and
        # nothing else. It used to be `res or lenient_match(...)`, which quietly
        # credited rows the shipped comparator rejects (a prediction that adds
        # DISTINCT has gold's set but not gold's column-vector length), so the
        # published "lenient" number was really max(strict, shipped).
        lres = int(lenient_match(db, gold, sql)) if sql else 0
        ok += res
        ok_len += lres
        schemas[i] = schema
        nl.at[i, arm.sql_col] = sql
        nl.at[i, arm.result_col] = res
        nl.at[i, lenient_col] = lres

    print(f"=== {arm.dataset} {arm.suffix} ===")
    print(f"  gold column      : {gold_col}")
    print(f"  scored           : {n}")
    print(f"  no SQL produced  : {missing}")
    print(f"  EX strict  (LDD) : {ok}/{n} = {100*ok/max(1,n):.2f}%")
    print(f"  EX lenient (AL)  : {ok_len}/{n} = {100*ok_len/max(1,n):.2f}%")
    print(f"  columns          : {arm.sql_col}")
    print(f"                     {arm.result_col}")
    print(f"                     {lenient_col}")

    if a.no_write:
        print("\n  --no_write: CSV untouched")
        return
    nl.to_csv(C.NL2SQL_CSV[a.dataset], index=False)
    if schemas:
        import pandas as _pd
        sp = os.path.join(os.path.dirname(C.NL2SQL_CSV[a.dataset]),
                          f"nl2sql_{a.dataset}_schemas.parquet")
        new = _pd.DataFrame({"row_index": sorted(schemas),
                             arm.schema_col: [schemas[r] for r in sorted(schemas)]})
        if os.path.exists(sp):
            old = _pd.read_parquet(sp)
            if arm.schema_col in old.columns:
                old = old.drop(columns=[arm.schema_col])
            new = old.merge(new, on="row_index", how="outer")
        new.to_parquet(sp, index=False, compression="zstd")
        print(f"  schemas          -> {sp} ({arm.schema_col})")
    print(f"\n  wrote {os.path.basename(C.NL2SQL_CSV[a.dataset])}")


if __name__ == "__main__":
    main()
