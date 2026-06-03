"""History → cluster construction."""

from __future__ import annotations

import ast

import pandas as pd

from .clusters import (
    assign_queries_to_clusters,
    compute_subsets_inplace,
    find_exact_query_patterns,
    simplify_sql,
)


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
