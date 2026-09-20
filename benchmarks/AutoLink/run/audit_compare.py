"""Diff each arm's stored top-30 against a pristine re-retrieval.

audit_retrieval.sh produces, for every arm, a fresh retrieval in a scratch dir
whose cache/ started empty -- i.e. the TRUE top-30. This compares that against
the first `retrieved_count` entries the arm actually ran on.

    identical        the arm used the true top-30           -> clean
    partial overlap  some columns shifted                   -> suspect
    zero overlap     the arm was handed the NEXT 30 columns -> contaminated

    python audit_compare.py
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ldd_config as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.join(HERE, "audit_scratch")

KW = {
    "base":  dict(),
    "+A":    dict(view=True, mode="opt1"),
    "+P":    dict(cluster=True, mode="opt2"),
    "+R":    dict(rename=True),
    "+A+P":  dict(view=True, cluster=True, mode="opt2"),
    "+A+R":  dict(rename=True, view=True, mode="opt1"),
    "+P+R":  dict(rename=True, cluster=True, mode="opt2"),
    "+A+P+R": dict(rename=True, view=True, cluster=True, mode="opt2"),
}


def pairs(entry, n=None):
    n = entry["retrieved_count"] if n is None else n
    return [(str(t).lower(), str(c).lower())
            for t, c in zip(entry["table_candidates"][:n],
                            entry["column_candidates"][:n])]


def main():
    print(f"{'dataset':8}{'arm':8}{'n':>6}{'identical':>11}{'overlap':>9}"
          f"{'zero-ov':>9}   verdict")
    print("-" * 74)
    rows = {}
    for ds in ("bird", "spider"):
        for label, kw in KW.items():
            arm = C.Arm(dataset=ds, **kw)
            try:
                arm.validate()
            except Exception:
                continue
            live = os.path.join(arm.log_path, "initial_candidates.json")
            fresh = os.path.join(SCRATCH, f"{ds}{arm.suffix}",
                                 "initial_candidates.json")
            if not (os.path.exists(live) and os.path.exists(fresh)):
                continue
            L = json.load(open(live, encoding="utf-8"))
            F = json.load(open(fresh, encoding="utf-8"))
            same = 0
            ovs = []
            zero = 0
            n = 0
            for iid, e in L.items():
                if iid not in F:
                    continue
                n += 1
                a, b = pairs(e), pairs(F[iid])
                if a == b:
                    same += 1
                sa, sb = set(a), set(b)
                ov = len(sa & sb) / max(len(sb), 1)
                ovs.append(ov)
                if ov == 0:
                    zero += 1
            if not n:
                continue
            mo = 100 * st.mean(ovs)
            if same == n:
                verdict = "CLEAN"
            elif zero == n:
                verdict = "CONTAMINATED (next-30)"
            elif mo < 95:
                verdict = "SHIFTED"
            else:
                verdict = "reordered only"
            print(f"{ds:8}{label:8}{n:>6}{same:>11}{mo:>8.1f}%{zero:>9}   {verdict}")
            rows[f"{ds}:{label}"] = dict(n=n, identical=same, mean_overlap=mo,
                                         zero_overlap=zero, verdict=verdict)
    out = os.path.join(HERE, "audit_scratch", "verdicts.json")
    json.dump(rows, open(out, "w"), indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
