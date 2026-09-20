"""Inject +A (cluster views) and +P (cluster tables + join paths) into AutoLink's
initial schema, between retrieval and the agent loop.

Pipeline position (runs after retrieve_topk_schema.py, before add_id.py):

    retrieve_topk_schema.py --top_n 30   ->  initial_candidates.json
    apply_apr.py            [THIS]       ->  initial_candidates.json (rewritten)
    add_id.py                            ->  id/name/code sweep
    generate_schema.py --is_initial      ->  schema_prompts/<id>.txt
    complete_schema.py                   ->  agent loop

Placement follows MAC-SQL, the only LDD pipeline with a schema-pruning agent: it
looks clusters up from a prior linking and pre-prunes the Selector's input via
``filtered_tables``, and injects views into the schema the Selector sees. Here the
BGE top-n stands in for MAC-SQL's stored ``history_linking`` column.

Two strategies
--------------
opt1  one retrieval pass. Tables of the top-n -> matching clusters -> inject ALL
      columns of every cluster table plus every matched cluster view. Mirrors
      LDD's --cluster_filter, which replaces the linked tables with the cluster
      union and rebuilds the schema from all their columns.

opt2  two retrieval passes (BGE is local, so the second is ~free). Top-n ->
      tables -> clusters -> restrict the candidate pool to those clusters'
      columns -> retrieve top-n *again* inside that pool -> tables of the second
      pass -> matching views. Keeps the initial schema bounded at n columns
      instead of absorbing whole cluster tables.

Views are injected as schema text, never added to the vector store: a join view
re-exposes its constituents' columns, so indexing them would make ~70% of the
store near-duplicates of base columns and crowd out real retrieval slots.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Dict, List, Sequence, Set, Tuple

import pandas as pd

LDD_BENCH = os.environ.get("LDD_BENCH") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 os.pardir, os.pardir))
sys.path.insert(0, LDD_BENCH)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common.clusters import find_all_clusters_for_tables  # noqa: E402
from _common.history import build_clusters_from_history  # noqa: E402

import ldd_config as C  # noqa: E402


# ---------------------------------------------------------------------------
# metadata helpers
# ---------------------------------------------------------------------------
def load_metadata(db_name: str) -> List[dict]:
    """The per-column metadata list FAISS indices point into."""
    path = os.path.join(C.HERE, "embeddings", "localdb", db_name, "metadata.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def columns_of(metadata: Sequence[dict], objects: Set[str]) -> List[int]:
    """Metadata indices belonging to any of ``objects`` (case-insensitive)."""
    low = {o.lower() for o in objects}
    return [i for i, m in enumerate(metadata) if str(m["table"]).lower() in low]


def append_entries(entry: dict, metadata: Sequence[dict], idxs: Sequence[int],
                   seen: Set[Tuple[str, str]]) -> int:
    """Append metadata rows onto an instance's five parallel candidate lists."""
    added = 0
    for i in idxs:
        m = metadata[i]
        key = (str(m["table"]).lower(), str(m["column"]).lower())
        if key in seen:
            continue
        seen.add(key)
        entry["table_candidates"].append(m["table"])
        entry["column_candidates"].append(m["column"])
        entry["column_types"].append(m["column_type"])
        entry["column_values"].append(m["column_value"])
        entry["descriptions"].append(m["description"])
        added += 1
    return added


def seen_keys(entry: dict) -> Set[Tuple[str, str]]:
    return {(str(t).lower(), str(c).lower())
            for t, c in zip(entry["table_candidates"], entry["column_candidates"])}


# ---------------------------------------------------------------------------
# cluster -> view name resolution (mirrors MAC-SQL run_union.py)
# ---------------------------------------------------------------------------
def views_for_clusters(cluster_ids: Sequence[int], all_views: Sequence[str],
                       prefix: str) -> List[str]:
    """Views whose name starts with ``<prefix><cluster_id>_``.

    Both view lists are numbered 1..64 (bird) / 1..57 (spider), so this is a
    clean id join. prefix is "cluster" for org and spider, and
    "workload_updated_cluster" for bird renamed.
    """
    wanted = tuple(f"{prefix}{cid}_" for cid in cluster_ids)
    if not wanted:
        return []
    return [v for v in all_views if v.startswith(wanted)]


# ---------------------------------------------------------------------------
# second retrieval pass (opt2)
# ---------------------------------------------------------------------------
def retrieve_within(question: str, db_name: str, allowed_idx: Set[int],
                    top_n: int, device: str = "cuda:0") -> List[int]:
    """Top-n columns restricted to ``allowed_idx``, by the same BGE + FAISS path."""
    import faiss
    import numpy as np
    from model_manager import model_manager

    embed_dir = os.path.join(C.HERE, "embeddings", "localdb", db_name)
    index = faiss.read_index(os.path.join(embed_dir, "index.faiss"))
    model_manager.load_model(device=device)
    q = model_manager.encode(question)

    # over-fetch, then keep only allowed rows -- cheaper than rebuilding an index
    k = min(index.ntotal, max(top_n * 20, top_n + len(allowed_idx)))
    _d, ids = index.search(np.array([q], dtype=np.float32), k)
    out = [int(i) for i in ids[0] if int(i) in allowed_idx]
    return out[:top_n]


# ---------------------------------------------------------------------------
def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=["bird", "spider"], default="bird")
    p.add_argument("--rename", action="store_true")
    p.add_argument("--view", action="store_true", help="+A")
    p.add_argument("--cluster", action="store_true", help="+P")
    p.add_argument("--mode", choices=["opt1", "opt2"], default="opt1")
    p.add_argument("--top_n", type=int, default=30)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--dry_run", action="store_true",
                   help="report the effect per question, write nothing")
    a = p.parse_args()

    arm = C.Arm(dataset=a.dataset, rename=a.rename, view=a.view,
                cluster=a.cluster, mode=a.mode, top_n=a.top_n)
    arm.validate()
    lists = C.load_object_lists()
    all_views = arm.views(lists)          # [] when +A is off
    hist = arm.hist

    if not (a.view or a.cluster):
        print(f"[apply_apr] arm {arm.suffix} has neither +A nor +P — nothing to do")
        return

    cand_path = os.path.join(arm.log_path, "initial_candidates.json")
    if not os.path.exists(cand_path):
        sys.exit(f"missing {cand_path}; run retrieve_topk_schema.py first")
    with open(cand_path, encoding="utf-8") as f:
        candidates = json.load(f)

    metadata = load_metadata(arm.db_name)

    # clusters are built from the history CSV, keyed on the arm's gt_tables column
    _sample, exact_clusters, _qcm = build_clusters_from_history(
        C.SAMPLE_CSV[a.dataset], sql_col=hist["sql"], gt_tables_col=hist["gt_tables"])
    print(f"[apply_apr] arm {arm.suffix}")
    print(f"  clusters built from {os.path.basename(C.SAMPLE_CSV[a.dataset])}"
          f" [{hist['gt_tables']}]: {len(exact_clusters)}")
    print(f"  view pool: {len(all_views)}  prefix={hist['view_prefix']!r}")
    print(f"  mode={a.mode}  top_n={a.top_n}")

    stats = {"n": 0, "no_cluster": 0, "cols_before": 0, "cols_after": 0,
             "views_injected": 0, "cluster_tables": 0, "paths": 0}
    paths_out: Dict[str, List[str]] = {}

    for iid, entry in candidates.items():
        stats["n"] += 1
        before = len(entry["column_candidates"])
        stats["cols_before"] += before

        seed_tables = {str(t) for t in entry["table_candidates"]}
        res = find_all_clusters_for_tables(sorted(seed_tables), exact_clusters)
        cids = res.get("cluster_ids") or []
        if not cids:
            stats["no_cluster"] += 1
            stats["cols_after"] += before
            paths_out[iid] = {"paths": [], "indices": [], "cluster_ids": []}
            continue

        cluster_tables = {str(t) for t in (res.get("tables") or [])}
        matched_views = views_for_clusters(cids, all_views, hist["view_prefix"]) \
            if a.view else []
        seen = seen_keys(entry)

        if a.mode == "opt1":
            # +P: every column of every cluster table
            if a.cluster and cluster_tables:
                idxs = columns_of(metadata, cluster_tables)
                append_entries(entry, metadata, idxs, seen)
                stats["cluster_tables"] += len(cluster_tables)
        else:
            # opt2: re-retrieve inside the cluster tables, keeping the schema bounded
            if a.cluster and cluster_tables:
                allowed = set(columns_of(metadata, cluster_tables))
                if allowed:
                    second = retrieve_within(entry["question"], arm.db_name,
                                             allowed, a.top_n, a.device)
                    append_entries(entry, metadata, second, seen)
                    # views are chosen from the SECOND pass's tables
                    second_tables = {str(metadata[i]["table"]) for i in second}
                    res2 = find_all_clusters_for_tables(sorted(second_tables),
                                                        exact_clusters)
                    if a.view:
                        matched_views = views_for_clusters(
                            res2.get("cluster_ids") or [], all_views,
                            hist["view_prefix"])
                    stats["cluster_tables"] += len(cluster_tables)

        # +A: every column of each matched cluster view
        if a.view and matched_views:
            idxs = columns_of(metadata, set(matched_views))
            append_entries(entry, metadata, idxs, seen)
            stats["views_injected"] += len(matched_views)

        # +P: Common Join Paths for the generation prompt, plus the matched
        # clusters' question indices so history retrieval can be restricted to
        # them (basesql._topk_history_sqls does the same).
        if a.cluster:
            pp = sorted(set(res.get("paths") or []))
            paths_out[iid] = {"paths": pp,
                              "indices": [int(i) for i in (res.get("indices") or [])],
                              "cluster_ids": [int(c) for c in cids]}
            stats["paths"] += len(pp)
        else:
            paths_out[iid] = {"paths": [], "indices": [], "cluster_ids": []}

        stats["cols_after"] += len(entry["column_candidates"])

    n = max(1, stats["n"])
    print(f"\n  questions                 : {stats['n']}")
    print(f"  no matching cluster       : {stats['no_cluster']} "
          f"({100*stats['no_cluster']/n:.1f}%)")
    print(f"  mean columns before       : {stats['cols_before']/n:.1f}")
    print(f"  mean columns after        : {stats['cols_after']/n:.1f}")
    print(f"  mean cluster tables/q     : {stats['cluster_tables']/n:.2f}")
    print(f"  mean views injected/q     : {stats['views_injected']/n:.2f}")
    print(f"  mean join paths/q         : {stats['paths']/n:.2f}")

    if a.dry_run:
        print("\n  --dry_run: initial_candidates.json untouched")
        return

    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=1)
    with open(os.path.join(arm.log_path, "join_paths.json"), "w",
              encoding="utf-8") as f:
        json.dump(paths_out, f, ensure_ascii=False, indent=1)
    print(f"\n  wrote {os.path.basename(cand_path)} + join_paths.json")


if __name__ == "__main__":
    main()
