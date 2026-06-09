"""History → cluster construction."""

from __future__ import annotations

import ast
import json
import os
from typing import Optional

import pandas as pd

from .clusters import (
    assign_queries_to_clusters,
    compute_subsets_inplace,
    find_exact_query_patterns,
    simplify_sql,
)


def load_clusters_from_file(
    cluster_path: str,
    history_path: str,
    sample_pct: int = 100,
    random_state: int = 42,
):
    """Load precomputed clusters from disk + read the sample CSV.

    Returns ``(sample, exact_clusters, question_cluster_map)`` matching the
    signature of :func:`build_clusters_from_history` so callers can swap them.

    Supports two on-disk shapes:

    1. **Consolidated** (current ``prep_database`` output):
       ``{"cluster": {"exact_clusters": ..., "question_cluster_map": ..., ...}, ...}``
    2. **Legacy** flat format:
       ``{"exact_clusters": ..., "question_cluster_map": ..., "metadata": {...}}``

    Raises ``KeyError`` if neither shape's cluster section is present (callers
    should catch this and fall back to building from history).

    ``sample_pct`` must be 100 when loading: precomputed clusters reference
    indices into the full history, so subsampling would invalidate them.
    """
    if sample_pct != 100:
        raise SystemExit(
            f"Precomputed clusters were requested but --sample={sample_pct} (<100). "
            f"Cluster indices reference the full history; subsampling at runtime would "
            f"invalidate them. Drop --sample <100 or rerun prep_database with the same "
            f"--sample value so the saved clusters match."
        )

    with open(cluster_path, encoding="utf-8") as f:
        payload = json.load(f)

    # Shape sniffer
    if isinstance(payload.get("cluster"), dict) and "exact_clusters" in payload["cluster"]:
        section = payload["cluster"]
        meta = payload.get("metadata", {})
    elif "exact_clusters" in payload:
        section = payload
        meta = payload.get("metadata", {})
    else:
        raise KeyError(
            f"cluster file {cluster_path} has no cluster section "
            f"(neither 'cluster.exact_clusters' nor top-level 'exact_clusters')."
        )

    expected_n = meta.get("n_questions") or section.get("n_questions")
    sample = pd.read_csv(history_path)
    if expected_n is not None and expected_n != len(sample):
        print(
            f"⚠️  cluster file metadata says n_questions={expected_n} but history "
            f"CSV has {len(sample)} rows — cluster indices may not align. "
            f"This usually means the history CSV changed since the cluster file was built."
        )

    print(
        f"📂 loaded clusters from {cluster_path} "
        f"({len(section['exact_clusters'])} clusters, "
        f"{expected_n or '?'} questions, "
        f"min_frequency={meta.get('min_frequency') or section.get('min_frequency')}, "
        f"min_tables={meta.get('min_tables') or section.get('min_tables')})"
    )

    return sample, section["exact_clusters"], section["question_cluster_map"]


def build_clusters_from_history(
    history_path: str,
    sql_col: str,
    gt_tables_col: str,
    sample_pct: int = 100,
    random_state: int = 42,
):
    """Load a history sample CSV and build ``(sample, exact_clusters, question_cluster_map)``.

    Args:
        history_path: Path to the history CSV.
        sql_col: Column to read SQLs from (used for join-path extraction).
        gt_tables_col: Column listing the ground-truth tables for each row.
        sample_pct: Integer 1..100; if <100, randomly sub-samples the history
            CSV before building clusters/embeddings. Index is reset after
            sampling so downstream positional/label lookups stay consistent.
        random_state: Seed for reproducible sub-sampling.
    """
    sample = pd.read_csv(history_path)
    full_n = len(sample)

    if sample_pct < 100:
        sample = sample.sample(
            frac=sample_pct / 100.0, random_state=random_state
        ).reset_index(drop=True)
        print(
            f"🎲 Sub-sampled history: kept {len(sample)}/{full_n} rows "
            f"({sample_pct}%, seed={random_state})"
        )
        if len(sample) > 0:
            _first_q = str(sample.iloc[0].get("question", "<no question col>"))
            _first_sql = str(sample.iloc[0].get(sql_col, f"<no {sql_col!r} col>"))
            print(f"    first question: {_first_q!r}")
            print(f"    first SQL ({sql_col}): {_first_sql!r}")
    else:
        print(f"🗂  Using full history: {full_n} rows")

    path_list = [simplify_sql(s) for s in sample[sql_col].tolist()]
    question_list = list(sample["question"])
    t_list = [ast.literal_eval(x) for x in list(sample[gt_tables_col])]

    exact_clusters = find_exact_query_patterns(
        t_list, path_list, min_frequency=5, min_tables=2
    )
    question_cluster_map = assign_queries_to_clusters(
        t_list, exact_clusters, question_list, path_list, min_tables=2
    )
    compute_subsets_inplace(exact_clusters, t_list, path_list)

    print(f"✅ Total clusters built from history: {len(exact_clusters)}")
    return sample, exact_clusters, question_cluster_map
