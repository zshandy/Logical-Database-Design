"""Generate AutoLink's inputs for one LDD arm.

Writes the two things AutoLink's own scripts consume:

  resource/databases/sqlite/<db_name>/<object>.json   one per exposed table/view
  spider2_data.json                                   {instance_id: {db_name, question, ...}}

Instance ids are ``local######`` because AutoLink's prefix routing keys off
"local" to select the SQLite dialect, the localdb documents file, the localdb
embeddings directory, and the pass-through branch in add_id.py.

Deliberately omitted, per the experiment design:
  * column descriptions  -- LDD's basesql never sees them, so neither does this
  * external knowledge / BIRD evidence -- same reason (written as null)

Usage
-----
    python prep_ldd_inputs.py --dataset bird                       # base arm
    python prep_ldd_inputs.py --dataset bird --view --cluster --mode opt1
    python prep_ldd_inputs.py --dataset bird --rename --view --cluster --mode opt2
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from typing import Dict, List

import pandas as pd

import ldd_config as C

SAMPLE_ROWS = 5


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    return conn


def dump_objects(db_path: str, objects: List[str], out_dir: str) -> Dict[str, int]:
    """One JSON per exposed object, in the shape generate_docs.py expects."""
    os.makedirs(out_dir, exist_ok=True)
    conn = _connect(db_path)
    cur = conn.cursor()

    present = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    missing = [o for o in objects if o not in present]
    if missing:
        raise SystemExit(f"{len(missing)} exposed object(s) absent from "
                         f"{os.path.basename(db_path)}: {missing[:5]}")

    stats = {"objects": 0, "columns": 0}
    for obj in objects:
        info = cur.execute(f'PRAGMA table_info("{obj}")').fetchall()
        cols = [str(r[1]) for r in info]
        types = [str(r[2] or "TEXT") for r in info]

        try:
            cur.execute(f'SELECT * FROM "{obj}" LIMIT {SAMPLE_ROWS}')
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, r)) for r in cur.fetchall()]
        except Exception:
            rows = []

        payload = {
            "table_fullname": obj,
            "column_names": cols,
            "column_types": types,
            # empty by design -- no descriptions anywhere in this pipeline
            "description": ["" for _ in cols],
            "sample_rows": rows,
        }
        with open(os.path.join(out_dir, f"{obj}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
        stats["objects"] += 1
        stats["columns"] += len(cols)

    conn.close()
    return stats


def build_question_file(dataset: str, db_name: str, out_path: str,
                        limit: int | None = None,
                        stratify: bool = False) -> int:
    """spider2_data.json from the nl2sql CSV, preserving row order in the id."""
    nl = pd.read_csv(C.NL2SQL_CSV[dataset])
    samp = pd.read_csv(C.SAMPLE_CSV[dataset])
    qcol = "question" if "question" in nl.columns else nl.columns[0]

    idxs = list(range(len(nl)))
    if limit and limit < len(idxs):
        if stratify:
            idxs = _stratified(samp, limit)
        else:
            idxs = idxs[:limit]

    data = {}
    for i in idxs:
        data[f"local{i:06d}"] = {
            "db_name": db_name,
            "question": str(nl.at[i, qcol]),
            # no evidence / hint / external knowledge by design
            "external_knowledge": None,
            "row_index": int(i),
        }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return len(data)


def _stratified(samp: pd.DataFrame, limit: int) -> List[int]:
    """Sample proportionally across gold table counts (1/2/3/4-table strata)."""
    import ast
    import collections
    import random

    def ntab(v):
        try:
            return len({str(t).strip().lower() for t in ast.literal_eval(str(v))})
        except Exception:
            return 0

    col = "gt_tables" if "gt_tables" in samp.columns else None
    if col is None:
        return list(range(limit))
    buckets = collections.defaultdict(list)
    for i in range(len(samp)):
        buckets[ntab(samp.at[i, col])].append(i)

    rng = random.Random(42)
    total = sum(len(v) for v in buckets.values())
    out: List[int] = []
    for k in sorted(buckets):
        share = max(1, round(limit * len(buckets[k]) / total))
        out.extend(rng.sample(buckets[k], min(share, len(buckets[k]))))
    return sorted(out[:limit])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=["bird", "spider"], default="bird")
    p.add_argument("--rename", action="store_true", help="+R")
    p.add_argument("--view", action="store_true", help="+A")
    p.add_argument("--cluster", action="store_true", help="+P")
    p.add_argument("--mode", choices=["opt1", "opt2"], default="opt1")
    p.add_argument("--top_n", type=int, default=30)
    p.add_argument("--limit", type=int, default=None,
                   help="run on the first N questions (pilot)")
    p.add_argument("--stratify", action="store_true",
                   help="with --limit, sample proportionally across gold table counts")
    a = p.parse_args()

    arm = C.Arm(dataset=a.dataset, rename=a.rename, view=a.view,
                cluster=a.cluster, mode=a.mode, top_n=a.top_n)
    arm.validate()
    lists = C.load_object_lists()

    tables, views = arm.tables(lists), arm.views(lists)
    exposed = tables + views

    print(f"=== arm {arm.suffix} ===")
    print(f"  rename={arm.rename}  view={arm.view}  cluster={arm.cluster}  mode={arm.mode}")
    print(f"  exposed: {len(tables)} tables + {len(views)} views = {len(exposed)} objects")
    print(f"  history: sql={arm.hist['sql']}  view_sql={arm.hist['view_sql']}")
    print(f"           gt_tables={arm.hist['gt_tables']}  view_prefix={arm.hist['view_prefix']}")

    out_dir = os.path.join(C.HERE, "resource", "databases", "sqlite", arm.db_name)
    stats = dump_objects(C.MERGED_DB[a.dataset], exposed, out_dir)
    print(f"  wrote {stats['objects']} dumps ({stats['columns']} columns) -> {out_dir}")

    # AutoLink opens the DB at this fixed path; one shared copy is enough since
    # arm isolation is enforced by the exposed-object list, not by the file.
    link_dir = os.path.join(C.HERE, "resource", "databases", "spider2-localdb")
    os.makedirs(link_dir, exist_ok=True)
    dst = os.path.join(link_dir, f"{arm.db_name}.sqlite")
    if not os.path.exists(dst):
        import shutil
        shutil.copy2(C.MERGED_DB[a.dataset], dst)
        print(f"  copied db -> {dst}")

    # The allowed-object list the executor uses to mask sqlite_master / PRAGMA.
    # Must NOT live in out_dir -- generate_docs.py globs every *.json there and
    # expects each to be a table dump with a "table_fullname" key.
    exp_dir = os.path.join(C.HERE, "exposed")
    os.makedirs(exp_dir, exist_ok=True)
    with open(os.path.join(exp_dir, f"{arm.db_name}.json"), "w", encoding="utf-8") as f:
        json.dump({"tables": tables, "views": views}, f, indent=1)

    qpath = os.path.join(C.HERE, f"questions_{arm.dataset}{arm.suffix}.json")
    n = build_question_file(a.dataset, arm.db_name, qpath,
                            limit=a.limit, stratify=a.stratify)
    print(f"  wrote {n} questions -> {os.path.basename(qpath)}")


if __name__ == "__main__":
    main()
