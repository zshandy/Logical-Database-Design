"""Cluster discovery, matching, and SQL helpers used by clustering pipelines.

A *cluster* groups history questions whose ``gt_tables`` overlap; it provides
canonical join paths (``paths``) that pipelines inject into stage-2/3 prompts
to bias the LLM toward known-good SQL skeletons.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from itertools import chain, combinations
from typing import Dict, List, Optional, Sequence, Set


def normalize_table_name(name: Optional[str]) -> str:
    """Normalize for equality / containment checks only.

    - Strip a single schema prefix (``schema.table`` → ``table``)
    - Strip a bracketed schema prefix (``[dbo].[Member]`` → ``Member``)
    - Strip common quoting (``"``, ``'``, `````)
    - Uppercase for robust matching
    """
    if name is None:
        return ""
    s = str(name).strip().strip('"').strip("'").strip("`").strip()
    s = re.sub(r"^[A-Za-z0-9_]+\.", "", s)
    s = re.sub(r"^\[[^\]]+\]\.", "", s)
    return s.upper()


def _cluster_norm_cache(clusters: Sequence[dict]) -> Dict[int, Set[str]]:
    """Return ``{cluster_id: set(normalized table names)}``."""
    return {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters
    }


def simplify_sql(query: str) -> str:
    """Return ``query`` with everything after the FROM/JOIN block stripped
    (so two queries can be compared by join path alone).
    """
    q = " ".join(query.strip().split())
    match = re.search(r"\bFROM\b", q, re.IGNORECASE)
    if not match:
        raise ValueError("No FROM clause found in query")
    q_from = q[match.start():]
    stop_match = re.search(
        r"\b(WHERE|GROUP BY|ORDER BY|HAVING|LIMIT)\b", q_from, re.IGNORECASE
    )
    if stop_match:
        q_from = q_from[: stop_match.start()]
    return q_from.strip()


def find_foreign_keys_between_tables(sqlite_path: str, tables: Sequence[str]) -> List[str]:
    """Detect declared FKs via PRAGMA foreign_key_list for each table *as given*.

    Membership checks use normalized names; output preserves the original table
    casing provided in ``tables`` (returned as ``"A.col=B.col"`` strings).
    """
    if not tables:
        return []

    from . import db_backend
    if db_backend.is_mysql(sqlite_path):
        return db_backend.find_foreign_keys_between_tables(sqlite_path, tables)

    norm_to_orig: Dict[str, str] = {}
    for t in tables:
        n = normalize_table_name(t)
        norm_to_orig.setdefault(n, t)

    norm_set = set(norm_to_orig.keys())
    out: Set[str] = set()

    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    try:
        for t in tables:
            t_norm = normalize_table_name(t)
            try:
                cur.execute(f"PRAGMA foreign_key_list('{t}')")
                rows = cur.fetchall()
            except sqlite3.DatabaseError:
                rows = []

            for row in rows:
                ref_table_raw = row[2]
                from_col = row[3]
                to_col = row[4]

                ref_norm = normalize_table_name(ref_table_raw)
                if t_norm in norm_set and ref_norm in norm_set:
                    lhs = f"{norm_to_orig[t_norm]}.{from_col}"
                    rhs = f"{norm_to_orig[ref_norm]}.{to_col}"
                    out.add(f"{lhs}={rhs}")
    finally:
        conn.close()

    return sorted(out)


def find_best_cluster_combo_strict(query_tables: Sequence[str], clusters: Sequence[dict]):
    """Strict-matching variant used by ``assign_queries_to_clusters``.

    Priority: (1) exact, (2) single superset, (3) subset of two-cluster union,
    (4) no match → caller will create a new cluster.
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return [], "new"

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = _cluster_norm_cache(clusters_sorted)

    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            return [c], "exact"

    supersets = [
        c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])
    ]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        return [supersets[0]], "subset"

    candidates = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    best_pair, best_key = None, None
    for i, c1 in enumerate(candidates):
        s1 = norm_by_id[c1["cluster_id"]]
        for c2 in candidates[i + 1:]:
            s2 = norm_by_id[c2["cluster_id"]]
            union = s1 | s2
            if qset.issubset(union):
                extras = len(union - qset)
                key = (
                    extras,
                    len(union),
                    min(c1["cluster_id"], c2["cluster_id"]),
                    max(c1["cluster_id"], c2["cluster_id"]),
                )
                if best_key is None or key < best_key:
                    best_key = key
                    best_pair = (c1, c2)
    if best_pair:
        return [best_pair[0], best_pair[1]], "subset_combo"

    return [], "new"


def find_exact_query_patterns(
    list_of_table_lists: Sequence[Sequence[str]],
    path_list: Sequence[str],
    min_frequency: int = 5,
    min_tables: int = 4,
) -> List[dict]:
    """Build initial frequent table-set clusters from history.

    Case-insensitive keys so rows whose ``gt_tables`` differ only by casing are
    counted as the same pattern. First-seen casing is preserved.
    """
    exact_patterns: Counter = Counter()
    pattern_paths: Dict[frozenset, Set[str]] = defaultdict(set)
    pattern_repr: Dict[frozenset, List[str]] = {}

    for tables, path in zip(list_of_table_lists, path_list):
        key = frozenset(t.lower() for t in tables)
        exact_patterns[key] += 1
        pattern_paths[key].add(path)
        if key not in pattern_repr:
            seen: Dict[str, str] = {}
            for t in tables:
                seen.setdefault(t.lower(), t)
            pattern_repr[key] = list(seen.values())

    clusters: List[dict] = []
    cluster_id = 1
    for pattern, count in exact_patterns.items():
        if count >= min_frequency and len(pattern) >= min_tables:
            clusters.append({
                "cluster_id": cluster_id,
                "tables": sorted(pattern_repr[pattern]),
                "num_tables": len(pattern),
                "count": count,
                "paths": sorted(list(pattern_paths[pattern])),
                "questions": [],
                "indices": [],
                "match_types": [],
                "subsets": {},
                "combo_pairs": {},
            })
            cluster_id += 1

    clusters.sort(key=lambda x: (x["count"], x["num_tables"]), reverse=True)
    return clusters


def assign_queries_to_clusters(
    list_of_table_lists: Sequence[Sequence[str]],
    clusters: List[dict],
    question_list: Sequence[str],
    path_list: Sequence[str],
    min_tables: int = 4,
) -> List[List[int]]:
    """Additive assignment with strict combination matching.

    Each question belongs to exactly one cluster (creates a new singleton if no
    coverage is found). For ``subset_combo`` matches, the partner cluster id is
    recorded alongside the primary.
    """
    question_cluster_map: List[int] = []
    question_combo_map: Dict[int, tuple] = {}
    assigned_questions: Set[int] = set()
    next_cluster_id = max([c["cluster_id"] for c in clusters], default=0) + 1

    for idx, tables in enumerate(list_of_table_lists):
        if not tables or idx in assigned_questions:
            question_cluster_map.append(-1)
            continue

        matched, match_type = find_best_cluster_combo_strict(tables, clusters)
        qtext, qpath = question_list[idx], path_list[idx]

        if len(matched) == 1:
            c = matched[0]
            c["indices"].append(idx)
            c["questions"].append(qtext)
            c["paths"].append(qpath)
            c["match_types"].append(match_type)
            question_cluster_map.append(c["cluster_id"])
            assigned_questions.add(idx)

        elif len(matched) == 2:
            c1, c2 = matched
            primary = c1 if c1["cluster_id"] < c2["cluster_id"] else c2
            partner = c2 if primary is c1 else c1

            primary["indices"].append(idx)
            primary["questions"].append(qtext)
            primary["paths"].append(qpath)
            primary["match_types"].append(match_type)
            primary["combo_pairs"][idx] = (primary["cluster_id"], partner["cluster_id"])

            question_combo_map[idx] = (primary["cluster_id"], partner["cluster_id"])
            question_cluster_map.append(primary["cluster_id"])
            assigned_questions.add(idx)

        else:
            new_cluster = {
                "cluster_id": next_cluster_id,
                "tables": sorted(set(tables)),
                "num_tables": len(set(tables)),
                "count": 1,
                "paths": [qpath],
                "questions": [qtext],
                "indices": [idx],
                "match_types": ["new"],
                "subsets": {},
                "combo_pairs": {},
            }
            clusters.append(new_cluster)
            question_cluster_map.append(next_cluster_id)
            assigned_questions.add(idx)
            next_cluster_id += 1

    for c in clusters:
        c["count"] = len(c["indices"])

    question_cluster_map_out: List[List[int]] = [[n] for n in question_cluster_map]
    for k, v in question_combo_map.items():
        question_cluster_map_out[k] = list(v)

    return question_cluster_map_out


def compute_subsets_inplace(
    clusters: Sequence[dict],
    list_of_table_lists: Sequence[Sequence[str]],
    path_list: Sequence[str],
) -> None:
    """Annotate each cluster with its strict subset patterns (in-place)."""
    for c in clusters:
        subset_indices: Dict[frozenset, List[int]] = defaultdict(list)
        cluster_norm = {normalize_table_name(t) for t in c["tables"]}
        extra_paths: Set[str] = set()

        for idx in c["indices"]:
            q_norm = frozenset(
                normalize_table_name(t) for t in list_of_table_lists[idx]
            )
            if q_norm < cluster_norm:
                subset_indices[q_norm].append(idx)
                extra_paths.add(path_list[idx])

        c["paths"] = sorted(set(c["paths"]).union(extra_paths))
        c["subsets"] = {
            ", ".join(sorted(list(k))): v for k, v in subset_indices.items()
        }


def _build_cluster_result(
    match_type: str,
    cluster_list: Sequence[dict],
    sqlite_path: Optional[str],
) -> dict:
    """Merge cluster info and attach detected foreign keys (original casing)."""
    tables = sorted(set(chain.from_iterable(c["tables"] for c in cluster_list)))
    paths = sorted(set(chain.from_iterable(c.get("paths", []) for c in cluster_list)))
    cluster_ids = [c["cluster_id"] for c in cluster_list]

    fks = find_foreign_keys_between_tables(sqlite_path, tables) if sqlite_path else []

    return {
        "match_type": match_type,
        "cluster_ids": cluster_ids,
        "tables": tables,
        "paths": paths,
        "foreign_keys": fks,
    }


def _empty_cluster_result() -> dict:
    return {
        "match_type": "new",
        "cluster_ids": [],
        "tables": [],
        "paths": [],
        "foreign_keys": [],
        "questions": [],
        "indices": [],
    }


def find_cluster_for_tables(
    query_tables: Sequence[str],
    clusters: Sequence[dict],
    sqlite_path: Optional[str] = None,
) -> dict:
    """Find the minimum number of clusters whose union covers ``query_tables``.

    Tries (1) exact match, (2) single superset, (3) minimal subset cover.
    Output includes the merged ``questions`` and ``indices`` from selected clusters.
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return _empty_cluster_result()

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            return _build_cluster_result("exact", [c], sqlite_path) | {
                "questions": c.get("questions", []),
                "indices": c.get("indices", []),
            }

    supersets = [
        c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])
    ]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        c = supersets[0]
        return _build_cluster_result("subset", [c], sqlite_path) | {
            "questions": c.get("questions", []),
            "indices": c.get("indices", []),
        }

    candidates = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    best_combo, best_key = None, None
    for r in range(2, len(candidates) + 1):
        for combo in combinations(candidates, r):
            u: Set[str] = set().union(*(norm_by_id[c["cluster_id"]] for c in combo))
            if qset.issubset(u):
                extras = len(u - qset)
                key = (r, extras, len(u), [c["cluster_id"] for c in combo])
                if best_key is None or key < best_key:
                    best_key, best_combo = key, combo
        if best_combo:
            break

    if best_combo:
        all_questions = list(chain.from_iterable(c.get("questions", []) for c in best_combo))
        all_indices = list(chain.from_iterable(c.get("indices", []) for c in best_combo))
        seen_q: Set[str] = set()
        seen_i: Set[int] = set()
        merged_q: List[str] = []
        merged_i: List[int] = []
        for q, i in zip(all_questions, all_indices):
            if i not in seen_i and q not in seen_q:
                merged_q.append(q)
                merged_i.append(i)
                seen_q.add(q)
                seen_i.add(i)
        res = _build_cluster_result("subset_combo", list(best_combo), sqlite_path)
        res["questions"] = merged_q
        res["indices"] = merged_i
        return res

    return _empty_cluster_result()


def find_all_clusters_for_tables(
    query_tables: Sequence[str],
    clusters: Sequence[dict],
    sqlite_path: Optional[str] = None,
) -> dict:
    """Return ALL clusters that share at least one table with ``query_tables``.

    ``match_type`` is ``exact`` if any cluster's table set equals ``query_tables``,
    ``subset`` if any cluster strictly supersets, otherwise ``partial``. The
    merged ``questions``/``indices`` lists are de-duplicated (order preserved).
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return _empty_cluster_result()

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    overlapping_clusters = [
        c for c in clusters_sorted if (qset & norm_by_id[c["cluster_id"]])
    ]

    if not overlapping_clusters:
        return _empty_cluster_result()

    any_exact = any(qset == norm_by_id[c["cluster_id"]] for c in overlapping_clusters)
    any_subset = any(qset < norm_by_id[c["cluster_id"]] for c in overlapping_clusters)

    if any_exact:
        match_type = "exact"
    elif any_subset:
        match_type = "subset"
    else:
        match_type = "partial"

    seen_indices: Set[int] = set()
    merged_questions: List[str] = []
    merged_indices: List[int] = []

    for c in overlapping_clusters:
        qs = c.get("questions", [])
        ix = c.get("indices", [])
        for q, i in zip(qs, ix):
            if i not in seen_indices:
                merged_questions.append(q)
                merged_indices.append(i)
                seen_indices.add(i)

    result = _build_cluster_result(match_type, overlapping_clusters, sqlite_path)
    result["questions"] = merged_questions
    result["indices"] = merged_indices
    return result
