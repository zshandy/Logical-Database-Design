"""Integrity gate for the 16 AutoLink arms. Exit 0 only if every arm is sound.

Checks per arm:
    complete   sql_selection/final has one dir per question, and selected.jsonl
               has one row per question
    non-empty  every selected.sql has content
    runnable   executable rate from selected.jsonl status
    distinct   duplicate-SQL rate (a collapsed arm repeats one query)

Exit code is what the overnight driver gates on: 0 = every arm complete and
sound, 1 = something needs a human.

    python integrity_check.py
"""

from __future__ import annotations

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ldd_config as C  # noqa: E402

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


def main() -> int:
    bad = []
    print(f"{'dataset':8}{'arm':9}{'final':>7}{'jsonl':>7}{'empty':>7}"
          f"{'exec%':>8}{'dup%':>7}   status")
    print("-" * 66)
    for ds, tot in (("bird", 767), ("spider", 502)):
        for label, kw in ARMS:
            arm = C.Arm(dataset=ds, **kw)
            fin = os.path.join(arm.log_path, "sql_selection", "final")
            n = len(os.listdir(fin)) if os.path.isdir(fin) else 0
            if n < tot:
                print(f"{ds:8}{label:9}{n:>7}{'-':>7}{'-':>7}{'-':>8}{'-':>7}   "
                      f"INCOMPLETE")
                bad.append(f"{ds}/{label}: {n}/{tot} selections")
                continue
            jl = os.path.join(arm.log_path, "sql_selection", "selected.jsonl")
            rows = ([json.loads(x) for x in open(jl, encoding="utf-8") if x.strip()]
                    if os.path.exists(jl) else [])
            st = collections.Counter(r.get("status") for r in rows)
            empty, sqls = 0, []
            for i in os.listdir(fin):
                p = os.path.join(fin, i, "selected.sql")
                s = (open(p, encoding="utf-8", errors="replace").read().strip()
                     if os.path.exists(p) else "")
                if not s:
                    empty += 1
                sqls.append(s)
            dup = 100 * (1 - len(set(sqls)) / max(len(sqls), 1))
            ok = 100 * st.get("success", 0) / max(len(rows), 1)
            problems = []
            if len(rows) != tot:
                problems.append(f"jsonl {len(rows)}/{tot}")
            if empty:
                problems.append(f"{empty} empty SQL")
            if ok < 90:
                problems.append(f"exec {ok:.1f}%")
            if dup > 10:
                problems.append(f"dup {dup:.1f}%")
            status = "OK" if not problems else "** " + ", ".join(problems)
            if problems:
                bad.append(f"{ds}/{label}: " + ", ".join(problems))
            print(f"{ds:8}{label:9}{n:>7}{len(rows):>7}{empty:>7}{ok:>7.1f}%"
                  f"{dup:>6.1f}%   {status}")

    print()
    if bad:
        print(f"FAILED: {len(bad)} problem(s)")
        for b in bad:
            print(f"   {b}")
        return 1
    print("ALL 16 ARMS COMPLETE AND SOUND")
    return 0


if __name__ == "__main__":
    sys.exit(main())
