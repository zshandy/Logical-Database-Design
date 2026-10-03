"""Final AutoLink export + significance grid.

One pass per dataset:

  1. read each arm's predictions from its OWN sql_selection/final/<id>/selected.sql
     -- never via the glob fallback, which used to pick up result.txt ("No data
     found for the specified query.") for failed rows and export the error
     string as the prediction (108 rows across the 16 arms).
  2. execute every gold query ONCE and cache it; 8 arms share it.
  3. score each arm two ways:
        _result          set(pred) == set(gold)          (compare_sql semantics)
        _result_lenient  compare_pandas_table(pred,gold) (AutoLink's shipped
                         comparator, imported, NO union with strict)
  4. write SQL + both result columns into csvs/nl2sql_<ds>.csv and, when it
     exists, into csvs/nl2sql_<ds>_min.csv (artifact naming:
     autolink_sql[_CFG]_ds), the full-results copy kept alongside the working
     CSV. It is not shipped -- recreate_database/nl2sql_<ds>.csv carries
     inputs only -- so on a fresh clone only the working CSV is written.
  5. report EX, delta vs baseline, McNemar vs baseline, and the full pairwise
     McNemar p-value grid, on the shipped comparator.

    python final_export_and_stats.py
    python final_export_and_stats.py --dataset bird --no_write
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import binomtest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ldd_config as C                                  # noqa: E402
from sql_selection import compare_pandas_table          # noqa: E402

LDD = os.environ.get("LDD_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 os.pardir, os.pardir, os.pardir))
TIMEOUT_S = 30

# label -> (Arm kwargs, artifact column infix)
ARMS = [
    ("base",   dict(),                                                   ""),
    ("+A",     dict(view=True, mode="opt1"),                             "A"),
    ("+P",     dict(cluster=True, mode="opt2"),                          "P"),
    ("+R",     dict(rename=True),                                        "R"),
    ("+A+P",   dict(view=True, cluster=True, mode="opt2"),               "AP"),
    ("+A+R",   dict(rename=True, view=True, mode="opt1"),                "AR"),
    ("+P+R",   dict(rename=True, cluster=True, mode="opt2"),             "PR"),
    ("+A+P+R", dict(rename=True, view=True, cluster=True, mode="opt2"),  "APR"),
]


def run_sql(db, sql):
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


def rowset(df):
    """Normalised row set for compare_sql-style equality."""
    out = set()
    for r in df.itertuples(index=False, name=None):
        v = []
        for x in r:
            if isinstance(x, bytes):
                x = x.decode("utf-8", "replace")
            # NaN/inf are floats but not integral; int() raises on them.
            if isinstance(x, float) and np.isfinite(x) and x == int(x):
                x = int(x)
            v.append(x)
        out.add(tuple(v))
    return out


def mcnemar(a, b):
    """Exact McNemar on paired 0/1 vectors. Returns (b01, b10, p)."""
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    n01 = int((~a & b).sum())     # a wrong, b right
    n10 = int((a & ~b).sum())     # a right, b wrong
    if n01 + n10 == 0:
        return n01, n10, 1.0
    return n01, n10, float(binomtest(n10, n01 + n10, 0.5).pvalue)


def stars(p):
    return "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=None, choices=("bird", "spider"))
    ap.add_argument("--no_write", action="store_true")
    a = ap.parse_args()

    summary = {}
    for ds in ([a.dataset] if a.dataset else ["bird", "spider"]):
        n_expect = 767 if ds == "bird" else 502
        work = os.path.join(LDD, "csvs", f"nl2sql_{ds}.csv")
        mini = os.path.join(LDD, "csvs", f"nl2sql_{ds}_min.csv")
        df = pd.read_csv(work, low_memory=False)
        # The full-results artifact is not shipped; without it only the
        # working CSV is written.
        mn = pd.read_csv(mini, low_memory=False) if os.path.exists(mini) else None
        n = len(df)
        assert n == n_expect, (n, n_expect)
        if mn is not None:
            assert len(mn) == n, (len(mn), n)
            # artifact rows must line up with working rows
            same_q = (df["question"].astype(str).map(lambda s: " ".join(s.split()))
                      .eq(mn["question"].astype(str).map(lambda s: " ".join(s.split())))).sum()
            print(f"\n{'='*74}\n{ds.upper()}-Union  n={n}   "
                  f"(artifact rows aligned: {same_q}/{n})\n{'='*74}")
            assert same_q == n, "artifact CSV row order does not match working CSV"
        else:
            print(f"\n{'='*74}\n{ds.upper()}-Union  n={n}   "
                  f"(no {os.path.basename(mini)}; writing the working CSV only)\n{'='*74}")

        gold_sql = df["SQL"].astype(str).tolist()
        gold_cache, gold_set = {}, {}

        strict_v, lenient_v, labels = {}, {}, []
        for label, kw, infix in ARMS:
            arm = C.Arm(dataset=ds, **kw)
            sel = os.path.join(arm.log_path, "sql_selection", "final")
            nsel = len(os.listdir(sel)) if os.path.isdir(sel) else 0
            if nsel < n:
                print(f"  {label:8} INCOMPLETE ({nsel}/{n}) -- skipped")
                continue
            db = os.path.join(HERE, "resource", "databases", "spider2-localdb",
                              f"{arm.db_name}.sqlite")
            if not os.path.exists(db):
                db = C.MERGED_DB[ds]

            preds, s_vec, l_vec = [], [], []
            for i in range(n):
                f = os.path.join(sel, f"local{i:06d}", "selected.sql")
                pred = (open(f, encoding="utf-8", errors="replace").read().strip()
                        if os.path.exists(f) else "")
                preds.append(pred)
                if i not in gold_cache:
                    g = run_sql(db, gold_sql[i])
                    gold_cache[i] = g
                    gold_set[i] = rowset(g) if g is not None else None
                g = gold_cache[i]
                if not pred or g is None:
                    s_vec.append(0); l_vec.append(0); continue
                p = run_sql(db, pred)
                if p is None:
                    s_vec.append(0); l_vec.append(0); continue
                s_vec.append(int(rowset(p) == gold_set[i]))
                if g.empty:
                    l_vec.append(int(p.empty))
                elif p.empty:
                    l_vec.append(0)
                else:
                    try:
                        l_vec.append(int(bool(compare_pandas_table(p, g, ignore_order=True))))
                    except Exception:
                        l_vec.append(0)

            strict_v[label], lenient_v[label] = s_vec, l_vec
            labels.append(label)
            print(f"  {label:8} strict {100*np.mean(s_vec):6.2f}%   "
                  f"shipped {100*np.mean(l_vec):6.2f}%")

            if not a.no_write:
                df[arm.sql_col] = preds
                df[arm.result_col] = s_vec
                df[arm.result_col + "_lenient"] = l_vec
                if mn is not None:
                    stem = f"autolink_sql_{infix + '_' if infix else ''}ds"
                    mn[stem] = preds
                    mn[stem + "_result"] = s_vec
                    mn[stem + "_result_lenient"] = l_vec

        if not a.no_write:
            df.to_csv(work, index=False)
            if mn is not None:
                mn.to_csv(mini, index=False)
                print(f"\n  wrote {os.path.basename(work)} and {os.path.basename(mini)}")
            else:
                print(f"\n  wrote {os.path.basename(work)}")

        # ---------------------------------------------------- significance
        base = labels[0]
        print(f"\n  EX / delta / McNemar vs {base}   (AutoLink shipped comparator)")
        print(f"    {'arm':8}{'EX':>9}{'delta':>9}{'b01':>6}{'b10':>6}{'p':>11}")
        rows = {}
        for lbl in labels:
            ex = 100 * np.mean(lenient_v[lbl])
            d = ex - 100 * np.mean(lenient_v[base])
            if lbl == base:
                print(f"    {lbl:8}{ex:8.2f}%{'--':>9}{'':>6}{'':>6}{'':>11}")
                rows[lbl] = dict(ex=ex)
                continue
            n01, n10, p = mcnemar(lenient_v[base], lenient_v[lbl])
            print(f"    {lbl:8}{ex:8.2f}%{d:+8.2f} {n01:>6}{n10:>6}{p:>10.4f}{stars(p)}")
            rows[lbl] = dict(ex=ex, delta=d, gained=n01, lost=n10, p=p)

        print(f"\n  pairwise McNemar p (row vs column), shipped comparator")
        print("    " + " " * 9 + "".join(f"{l:>9}" for l in labels))
        for r in labels:
            cells = []
            for c in labels:
                if r == c:
                    cells.append(f"{'--':>9}")
                else:
                    _, _, p = mcnemar(lenient_v[r], lenient_v[c])
                    cells.append(f"{p:>9.3f}")
            print(f"    {r:9}" + "".join(cells))
        summary[ds] = rows

    out = os.path.join(HERE, "runlogs", "final_stats.json")
    json.dump(summary, open(out, "w"), indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
