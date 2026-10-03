"""Score completed AutoLink arms with AutoLink's shipped comparator, and only that.

Metric = compare_pandas_table(pred, gold, ignore_order=True), imported from the
vendored sql_selection.py (Spider 2.0's official comparator, which is what
AutoLink's own selection step uses). Every gold column vector must appear in
the prediction; extra predicted columns are tolerated.

    python score_shipped.py
    python score_shipped.py --dataset bird
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ldd_config as C                                  # noqa: E402
from sql_selection import compare_pandas_table          # noqa: E402

LDD = os.environ.get("LDD_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 os.pardir, os.pardir, os.pardir))
TIMEOUT_S = 30

ARMS = [
    ("base",   dict()),
    ("+A",     dict(view=True, mode="opt1")),
    ("+P",     dict(cluster=True, mode="opt2")),
    ("+R",     dict(rename=True)),
    ("+A+P",   dict(view=True, cluster=True, mode="opt2")),
    ("+A+R",   dict(rename=True, view=True, mode="opt1")),
    ("+P+R",   dict(rename=True, cluster=True, mode="opt2")),
    ("+A+P+R", dict(rename=True, view=True, cluster=True, mode="opt2")),
]


def exec_df(db, sql):
    """DataFrame, or None if the query fails. Mirrors AutoLink's executor."""
    conn = None
    try:
        conn = sqlite3.connect(db, timeout=TIMEOUT_S)
        dl = time.monotonic() + TIMEOUT_S
        conn.set_progress_handler(lambda dl=dl: 1 if time.monotonic() > dl else 0, 1000)
        cur = conn.execute(str(sql))
        cols = [d[0] for d in cur.description] if cur.description else []
        return pd.DataFrame(cur.fetchall(), columns=cols)
    except sqlite3.Error:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def shipped(db, gold, pred) -> bool:
    g, p = exec_df(db, gold), exec_df(db, pred)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=None, choices=("bird", "spider"))
    a = ap.parse_args()

    for ds in ([a.dataset] if a.dataset else ["bird", "spider"]):
        n_expect = 767 if ds == "bird" else 502
        df = pd.read_csv(os.path.join(LDD, "csvs", f"nl2sql_{ds}.csv"),
                         low_memory=False)
        gold_all = df["SQL"].astype(str).tolist()
        n = len(df)
        print(f"\n{'=' * 60}")
        print(f"{ds.upper()}-Union  n={n}   metric: AutoLink compare_pandas_table")
        print("=" * 60)
        base = None
        for label, kw in ARMS:
            arm = C.Arm(dataset=ds, **kw)
            sel = os.path.join(arm.log_path, "sql_selection", "final")
            if not os.path.isdir(sel) or len(os.listdir(sel)) < n_expect:
                print(f"  {label:8}  (incomplete -- skipped)")
                continue
            db = os.path.join(HERE, "resource", "databases", "spider2-localdb",
                              f"{arm.db_name}.sqlite")
            if not os.path.exists(db):
                db = C.MERGED_DB[ds]

            # Read predictions from the arm's own sql_selection/final rather than
            # from the CSV: an arm can be finished on disk long before anything
            # exports it, and scoring must not silently skip those.
            # instance_id local%06d maps to CSV row order.
            preds = []
            for i in range(n):
                f = os.path.join(sel, f"local{i:06d}", "selected.sql")
                preds.append(open(f, encoding="utf-8", errors="replace").read()
                             if os.path.exists(f) else "")
            missing = sum(1 for p in preds if not p.strip())
            ok = 0
            for gold, pred in zip(gold_all, preds):
                if pred.strip() and shipped(db, gold, pred):
                    ok += 1
            if missing:
                print(f"  {label:8}  ({missing} predictions missing on disk)")
            ex = 100 * ok / n
            if base is None:
                base = ex
                print(f"  {label:8} {ok:4d}/{n}  {ex:6.2f}%")
            else:
                print(f"  {label:8} {ok:4d}/{n}  {ex:6.2f}%   {ex-base:+.2f}")


if __name__ == "__main__":
    main()
