# -*- coding: utf-8 -*-
"""
Run script for MAC-SQL with CSV input and single SQLite database.
Uses the _union templates (no evidence, simplified schema).
Uses the original pipeline via ChatManagerUnion.
"""

# =============================================================================
# DATASET CONSTANTS - paths resolved relative to this file's location.
# This file is expected to live at <LDD_ROOT>/benchmarks/MAC-SQL/run_union.py,
# so the shared data folders (databases/, mapping_files/, csvs/) sit two levels up.
# Spider equivalents live in core/spider_constants.py.
# =============================================================================
import os as _os
_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))                     # .../benchmarks/MAC-SQL/
_LDD_ROOT = _os.path.abspath(_os.path.join(_THIS_DIR, "..", ".."))           # LDD root

BIRD_SQLITE_PATH  = _os.path.join(_LDD_ROOT, "databases", "merged_bird.sqlite")
BIRD_MAPPING_PATH = _os.path.join(_LDD_ROOT, "mapping_files", "name_mapping_bird.json")

# Bird: base tables and renamed workload views
BIRD_ORG_TABLES = ['Country', 'Examination', 'Laboratory', 'League', 'Match', 'Patient', 'Player', 'Player_Attributes', 'Team', 'Team_Attributes', 'account', 'alignment', 'atom', 'attendance', 'attribute', 'badges', 'bond', 'budget', 'card', 'cards', 'circuits', 'client', 'colour', 'comments', 'connected', 'constructorResults', 'constructorStandings', 'constructors', 'customers', 'disp', 'district', 'driverStandings', 'drivers', 'event', 'expense', 'foreign_data', 'frpm', 'gasstations', 'gender', 'hero_attribute', 'hero_power', 'income', 'lapTimes', 'legalities', 'loan', 'major', 'member', 'molecule', 'order', 'pitStops', 'postHistory', 'postLinks', 'posts', 'products', 'publisher', 'qualifying', 'race', 'races', 'results', 'rulings', 'satscores', 'schools', 'seasons', 'set_translations', 'sets', 'status', 'superhero', 'superpower', 'tags', 'trans', 'transactions_1k', 'users', 'votes', 'yearmonth', 'zip_code']

BIRD_RENAMED_TABLES = ['Bank_Accounts', 'Bank_Cards', 'Bank_Clients', 'Bank_Dispositions', 'Bank_Districts', 'Bank_Loans', 'Bank_Orders', 'Bank_Transactions', 'Chem_Atoms', 'Chem_Bonds', 'Chem_Links', 'Chem_Molecules', 'Club_Attendance', 'Club_Budgets', 'Club_Events', 'Club_Expenses', 'Club_Income', 'Club_Majors', 'Club_Members', 'Club_Zips', 'Education_Lunch_Aid', 'Education_SAT_Stats', 'Education_Schools', 'Energy_Customers', 'Energy_Products', 'Energy_Sales', 'Energy_Stations', 'Energy_Usage', 'F1_Constructor_Results', 'F1_Constructor_Standings', 'F1_Constructors', 'F1_Driver_Standings', 'F1_Drivers', 'F1_Lap_Times', 'F1_Pit_Stops', 'F1_Qualifying', 'F1_Races', 'F1_Results', 'F1_Seasons', 'F1_Status_Codes', 'F1_Tracks', 'Forum_Badges', 'Forum_Comments', 'Forum_History', 'Forum_Links', 'Forum_Posts', 'Forum_Tags', 'Forum_Users', 'Forum_Votes', 'Hero_Alignments', 'Hero_Attribute_Types', 'Hero_Attributes', 'Hero_Colors', 'Hero_Genders', 'Hero_Power_Map', 'Hero_Profiles', 'Hero_Publishers', 'Hero_Races', 'Hero_Superpowers', 'MTG_Card_Foreign_Data', 'MTG_Cards', 'MTG_Legality', 'MTG_Rulings', 'MTG_Set_Translations', 'MTG_Sets', 'Medical_Exams', 'Medical_Lab_Results', 'Medical_Patients', 'Soccer_Countries', 'Soccer_Leagues', 'Soccer_Matches', 'Soccer_Player_Stats', 'Soccer_Players', 'Soccer_Team_Stats', 'Soccer_Teams']

from core import spider_constants


def resolve_dataset_config(dataset: str, rename: bool):
    """
    Returns (sqlite_path, tables, linking_filename, cluster_prefix) for the given dataset + rename.
    cluster_prefix is the SQL-column prefix in the history CSV (e.g. '' → reads 'SQL',
    'renamed_' → reads 'renamed_SQL'). linking_filename is under the MAC-SQL-main directory.
    """
    if dataset == 'spider':
        sqlite_path = spider_constants.SQLITE_PATH
        tables = spider_constants.RENAMED_TABLES if rename else spider_constants.ORG_TABLES
        linking_filename = 'renamed_history_linking_spider.json' if rename else 'history_linking_spider.json'
        cluster_prefix = 'renamed_' if rename else ''
    elif dataset == 'bird':
        sqlite_path = BIRD_SQLITE_PATH
        tables = BIRD_RENAMED_TABLES if rename else BIRD_ORG_TABLES
        linking_filename = 'workload_updated_history_linking.json' if rename else 'history_linking.json'
        cluster_prefix = 'workload_updated_' if rename else ''
    else:
        raise ValueError(f"Unknown dataset: {dataset}")
    return sqlite_path, tables, linking_filename, cluster_prefix


def get_cluster_view_list(dataset: str, rename: bool):
    """Return the list of cluster view names for the given dataset + rename."""
    if dataset == 'spider':
        return spider_constants.RENAMED_VIEWS if rename else spider_constants.ORG_VIEWS
    # Bird path falls back to sqlite introspection via list_tables_and_views
    return None

# =============================================================================

from core.chat_manager import ChatManagerUnion
from core.utils import replace_multiple_spaces, load_jsonl_file
from core.schema_generator import generate_schema_prompt
from core.const import SYSTEM_NAME
from tqdm import tqdm
import pandas as pd
import time
import argparse
import os
import json
import traceback
import re
import ast
import sqlite3
from collections import Counter, defaultdict
from itertools import chain


def parse_view_tables(view_name):
    """Extract constituent table names from a view name like 'cluster19_deaths_join_ships'."""
    m = re.match(r'^(?:workload_updated_)?cluster\d+_(.+)$', view_name)
    if not m:
        return []
    return m.group(1).split('_join_')


def build_clusters_from_view_names(view_list):
    """Build cluster dicts directly from view names, without needing a history CSV.
    Used when --view is on but --history is not (view-only mode)."""
    clusters = []
    for view_name in view_list:
        m = re.match(r'^(?:workload_updated_)?cluster(\d+)_', view_name)
        if not m:
            continue
        cid = int(m.group(1))
        tables = parse_view_tables(view_name)
        if not tables:
            continue
        clusters.append({
            "cluster_id": cid,
            "tables": sorted(set(tables)),
            "num_tables": len(set(tables)),
            "count": 0,
            "paths": [],
            "questions": [],
            "indices": [],
            "match_types": [],
            "subsets": {},
            "combo_pairs": {},
        })
    return clusters


def list_tables_and_views(db_path):
    """List all tables and views from a SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name")
    names = [row[0] for row in cursor.fetchall()]
    conn.close()
    return names


# =============================================================================
# Embedding-based history SQL retrieval
# =============================================================================
_embedding_model = None

def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('BAAI/bge-large-en-v1.5', device='cuda')
    return _embedding_model

def prepare_reference_embeddings(str_list, indices=None):
    """Compute embeddings for a list of strings."""
    model = _get_embedding_model()
    if indices is None:
        indices = list(range(len(str_list)))
    else:
        assert len(indices) == len(str_list), (
            f"indices length ({len(indices)}) must match str_list length ({len(str_list)})"
        )
    texts = ["passage: " + str(s).strip() for s in str_list]
    embeddings = model.encode(texts, normalize_embeddings=True)
    ref_pairs = list(zip(indices, str_list))
    return ref_pairs, embeddings

def topk_embedding_cosine_sim(target_str, ref_pairs, ref_embeddings, top_k=5):
    """Compare target string against precomputed embeddings. Returns [(index, text, score)]."""
    from sklearn.metrics.pairwise import cosine_similarity
    model = _get_embedding_model()
    target_emb = model.encode(
        ["query: " + str(target_str).strip()],
        normalize_embeddings=True
    )
    similarities = cosine_similarity(target_emb, ref_embeddings).flatten()
    top_idx = similarities.argsort()[::-1][:top_k]
    results = [
        (ref_pairs[i][0], ref_pairs[i][1], float(similarities[i]))
        for i in top_idx
    ]
    return results


# =============================================================================
# Cluster-based history SQL retrieval
# =============================================================================

def normalize_table_name(name: str) -> str:
    """Normalize table name for comparison (schema/quotes removed)."""
    if name is None:
        return ""
    s = str(name).strip().strip('"').strip("'").strip('`').strip()
    s = re.sub(r'^[A-Za-z0-9_]+\.', '', s)
    s = re.sub(r'^\[[^\]]+\]\.', '', s)
    return s.upper()


def _cluster_norm_cache(clusters):
    """Return cluster_id -> normalized table-name set."""
    return {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters
    }


def find_best_cluster_combo_strict(query_tables, clusters):
    """Find best cluster match for query tables."""
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return [], "new"

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = _cluster_norm_cache(clusters_sorted)

    # 1. exact
    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            return [c], "exact"

    # 2. single superset
    supersets = [c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        return [supersets[0]], "subset"

    # 3. combination of two clusters
    candidates = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    best_pair, best_key = None, None
    for i, c1 in enumerate(candidates):
        s1 = norm_by_id[c1["cluster_id"]]
        for c2 in candidates[i + 1:]:
            s2 = norm_by_id[c2["cluster_id"]]
            union = s1 | s2
            if qset.issubset(union):
                extras = len(union - qset)
                key = (extras, len(union),
                       min(c1["cluster_id"], c2["cluster_id"]),
                       max(c1["cluster_id"], c2["cluster_id"]))
                if best_key is None or key < best_key:
                    best_key = key
                    best_pair = (c1, c2)
    if best_pair:
        return [best_pair[0], best_pair[1]], "subset_combo"

    # 4. no match
    return [], "new"


def find_exact_query_patterns(list_of_table_lists, path_list, min_frequency=5, min_tables=2):
    """Build initial frequent table clusters."""
    exact_patterns = Counter()
    pattern_paths = defaultdict(set)

    for tables, path in zip(list_of_table_lists, path_list):
        key = frozenset(tables)
        exact_patterns[key] += 1
        pattern_paths[key].add(path)

    clusters = []
    cluster_id = 1
    for pattern, count in exact_patterns.items():
        if count >= min_frequency and len(pattern) >= min_tables:
            clusters.append({
                "cluster_id": cluster_id,
                "tables": sorted(pattern),
                "num_tables": len(pattern),
                "count": count,
                "paths": sorted(list(pattern_paths[pattern])),
                "questions": [],
                "indices": [],
                "match_types": [],
                "subsets": {},
                "combo_pairs": {}
            })
            cluster_id += 1

    clusters.sort(key=lambda x: (x["count"], x["num_tables"]), reverse=True)
    return clusters


def assign_queries_to_clusters(list_of_table_lists, clusters, question_list, path_list, min_tables=2):
    """Assign queries to clusters."""
    question_cluster_map = []
    question_combo_map = {}
    assigned_questions = set()
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
                "combo_pairs": {}
            }
            clusters.append(new_cluster)
            question_cluster_map.append(next_cluster_id)
            assigned_questions.add(idx)
            next_cluster_id += 1

    for c in clusters:
        c["count"] = len(c["indices"])

    question_cluster_map = [[n] for n in question_cluster_map]
    for k, v in question_combo_map.items():
        question_cluster_map[k] = list(v)

    return question_cluster_map


def compute_subsets_inplace(clusters, list_of_table_lists, path_list):
    """Compute subsets per cluster."""
    for c in clusters:
        subset_indices = defaultdict(list)
        cluster_norm = {normalize_table_name(t) for t in c["tables"]}
        extra_paths = set()

        for idx in c["indices"]:
            q_norm = frozenset(normalize_table_name(t) for t in list_of_table_lists[idx])
            if q_norm < cluster_norm:
                subset_indices[q_norm].append(idx)
                extra_paths.add(path_list[idx])

        c["paths"] = sorted(set(c["paths"]).union(extra_paths))
        c["subsets"] = {
            ", ".join(sorted(list(k))): v for k, v in subset_indices.items()
        }


def simplify_sql(query: str) -> str:
    """Simplify SQL to just FROM/JOIN part."""
    q = " ".join(query.strip().split())
    match = re.search(r"\bFROM\b", q, re.IGNORECASE)
    if not match:
        return ""
    from_start = match.start()
    q_from = q[from_start:]
    stop_match = re.search(r"\b(WHERE|GROUP BY|ORDER BY|HAVING|LIMIT)\b", q_from, re.IGNORECASE)
    if stop_match:
        q_from = q_from[:stop_match.start()]
    return q_from.strip()


def find_foreign_keys_between_tables(db_path, tables):
    """Find FKs between the given tables."""
    if not tables:
        return []
    tables_upper = {t.upper() for t in tables}
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    fks = []
    for table in tables:
        try:
            cursor.execute(f"PRAGMA foreign_key_list(`{table}`)")
            for fk in cursor.fetchall():
                from_col, to_table, to_col = fk[3], fk[2], fk[4]
                if to_table and to_table.upper() in tables_upper:
                    fks.append(f"{table}.`{from_col}` = {to_table}.`{to_col}`")
        except:
            pass
    conn.close()
    return fks


def _build_cluster_result(match_type, cluster_list, sqlite_path):
    """Merge cluster info and attach detected foreign keys."""
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


def find_all_clusters_for_tables(query_tables, clusters, sqlite_path=None):
    """Find all clusters that contain one or more of the query tables."""
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return {
            "match_type": "new", "cluster_ids": [], "tables": [], "paths": [],
            "foreign_keys": [], "questions": [], "indices": [],
        }

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    overlapping_clusters = [
        c for c in clusters_sorted
        if (qset & norm_by_id[c["cluster_id"]])
    ]

    if not overlapping_clusters:
        return {
            "match_type": "new", "cluster_ids": [], "tables": [], "paths": [],
            "foreign_keys": [], "questions": [], "indices": [],
        }

    any_exact = any(qset == norm_by_id[c["cluster_id"]] for c in overlapping_clusters)
    any_subset = any(qset < norm_by_id[c["cluster_id"]] for c in overlapping_clusters)

    if any_exact:
        match_type = "exact"
    elif any_subset:
        match_type = "subset"
    else:
        match_type = "partial"

    seen_indices = set()
    merged_questions = []
    merged_indices = []

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


def build_clusters_from_history(history_df, w_flag, view=False, min_tables=2, min_frequency=5):
    """Build clusters from history dataframe once."""
    path_list = []
    for index, row in history_df.iterrows():
        try:
            path_list.append(simplify_sql(row[f'{w_flag}SQL']))
            if view:
                path_list.append(simplify_sql(row[f'{w_flag}view_SQL']))
        except:
            path_list.append("")

    question_list = list(history_df['question'])

    # Parse table lists
    tables_col = f'gt_{w_flag}tables'
    if tables_col not in history_df.columns:
        raise ValueError(f"History CSV must have '{tables_col}' column for cluster mode")

    t_list = []
    for x in history_df[tables_col]:
        try:
            t_list.append(ast.literal_eval(x) if isinstance(x, str) else x)
        except:
            t_list.append([])

    exact_clusters = find_exact_query_patterns(t_list, path_list, min_frequency=min_frequency, min_tables=min_tables)
    assign_queries_to_clusters(t_list, exact_clusters, question_list, path_list, min_tables=min_tables)
    compute_subsets_inplace(exact_clusters, t_list, path_list)

    print(f"✅ Total clusters found: {len(exact_clusters)}")
    for c in exact_clusters[:5]:
        print(f"📊 Cluster {c['cluster_id']} — {c['count']} queries | {c['num_tables']} tables")

    return exact_clusters


def init_message(idx: int, question: str, ground_truth: str = '') -> dict:
    """Create message dict from question."""
    return {
        "idx": idx,
        "db_id": "union_db",
        "query": question,
        "extracted_schema": {},
        "ground_truth": ground_truth,
        "difficulty": "unknown",
        "send_to": SYSTEM_NAME
    }


def run_from_csv(
    csv_path: str,
    sqlite_path: str,
    output_file: str,
    tables: list,
    log_file: str = None,
    start_pos: int = 0,
    without_selector: bool = False,
    question_col: str = 'question',
    sql_col: str = 'SQL',
    fresh: bool = False,
    history_csv: str = None,
    cluster: str = '',
    rename: bool = False,
    view: bool = False,
    use_history: bool = True,
    use_cluster: bool = False,
    dataset: str = 'bird',
    linking_filename: str = None,
    limit: int = 0,
    cluster_filter: bool = False
):
    """Run MAC-SQL pipeline from CSV input using original pipeline."""

    # Clear output file if fresh start requested
    if fresh and os.path.exists(output_file):
        os.remove(output_file)
        print(f"Fresh start: cleared {output_file}")

    # Load CSV
    df = pd.read_csv(csv_path)
    if limit and limit > 0:
        df = df.iloc[:limit].copy()
        print(f"--limit {limit}: truncated to first {len(df)} rows")
    print(f"Loaded {len(df)} rows from {csv_path}")
    print(f"Columns: {list(df.columns)}")

    # Prepare history embeddings / linking / view schemas
    ref_pairs = None
    ref_embs = None
    history_df = None
    exact_clusters = None
    history_linking = None
    use_cluster_mode = False
    selected_cluster_views = None
    _view_schema_cache = {}

    # Load linking file if we need clusters (either for history retrieval or view injection)
    need_linking = bool(history_csv) or view
    if need_linking:
        linking_basename = linking_filename or f"{cluster}history_linking.json"
        # Linking files live alongside this script (.../benchmarks/MAC-SQL/<linking_basename>).
        linking_path = os.path.join(_THIS_DIR, linking_basename)
        if os.path.exists(linking_path):
            with open(linking_path, 'r', encoding='utf-8') as f:
                history_linking = json.load(f)
            print(f"Loaded history linking from {linking_path} ({len(history_linking)} entries)")
        else:
            print(f"Note: Linking file not found: {linking_path}")

    # Pre-cache view schemas (needed whenever --view is on, with or without history)
    if view:
        spider_view_list = get_cluster_view_list(dataset, rename)
        if spider_view_list is not None:
            selected_cluster_views = spider_view_list
        else:
            cluster_prefix = f"{cluster}cluster"
            all_db_objects = list_tables_and_views(sqlite_path)
            selected_cluster_views = [x for x in all_db_objects if x.startswith(cluster_prefix) and not x.startswith(cluster_prefix + "workload_")]
        for view_name in selected_cluster_views:
            schema_str, _ = generate_schema_prompt(sqlite_path, [view_name])
            _view_schema_cache[view_name] = schema_str
        print(f"Cached {len(_view_schema_cache)} cluster view schemas.")

    # Build clusters: from history if available, else from view names directly (view-only mode)
    if history_csv:
        history_df = pd.read_csv(history_csv)
        sql_col_name = f'{cluster}SQL'
        assert 'question' in history_df.columns, f"History CSV must have 'question' column"
        assert sql_col_name in history_df.columns, f"History CSV must have '{sql_col_name}' column"

        if history_linking is not None:
            print("Building clusters from history...")
            exact_clusters = build_clusters_from_history(history_df, cluster, view=view)
            use_cluster_mode = True
            print("Cluster mode enabled.")

        if not use_cluster_mode or not use_cluster:
            print(f"Loading history embeddings from {history_csv} ({len(history_df)} rows, SQL col: '{sql_col_name}')...")
            ref_pairs, ref_embs = prepare_reference_embeddings(list(history_df['question']))
            print(f"History embeddings ready.")
    elif view and history_linking is not None and selected_cluster_views:
        # View-only mode: build a minimal cluster list from the view names themselves
        print("Building clusters from view names (view-only mode, no history)...")
        exact_clusters = build_clusters_from_view_names(selected_cluster_views)
        print(f"Built {len(exact_clusters)} clusters from view names.")

    # Initialize chat manager (uses original pipeline)
    chat_manager = ChatManagerUnion(
        sqlite_path=sqlite_path,
        tables=tables,
        log_path=log_file,
        dataset_name=dataset,
        without_selector=without_selector,
        rename=rename
    )

    # Resume from checkpoint (skipped if fresh)
    finished_ids = set()
    if os.path.exists(output_file):
        output_data = load_jsonl_file(output_file)
        for o in output_data:
            finished_ids.add(o['idx'])
        print(f"Resuming: {len(finished_ids)} already completed")

    # Process each row
    with open(output_file, 'a+', encoding='utf-8') as fp:
        total = len(df)
        for idx, row in tqdm(df.iterrows(), total=total):
            if idx < start_pos or idx in finished_ids:
                continue

            question = row[question_col]
            ground_truth = row.get(sql_col, '') if sql_col in df.columns else ''

            print(f"\n\n{'='*60}")
            print(f"Processing {idx}/{total}: {question[:100]}...")
            print(f"{'='*60}\n")

            user_message = init_message(idx, question, ground_truth)
            user_message['use_history'] = use_history

            # Add history SQLs and/or view schema (cluster-based)
            has_clusters = exact_clusters is not None and history_linking is not None
            if has_clusters:
                # Cluster mode: find relevant clusters and build filtered embeddings
                sql_col_name = f'{cluster}SQL'

                # Get retrieved tables from linking (try both str and int keys)
                idx_key = str(idx) if str(idx) in history_linking else idx
                col_list = history_linking.get(idx_key, history_linking.get(str(idx), []))
                print(f"DEBUG: idx={idx}, idx_key={idx_key}, col_list={col_list}")

                # Extract table names from column list (format: "table.column" or just "table")
                retrieved_tables = list(set(
                    x.split(".")[0] if "." in x else x
                    for x in col_list
                ))

                # Find clusters (needed for view_schema and optionally for top_sqls)
                res = None
                if len(retrieved_tables) > 0 and exact_clusters:
                    res = find_all_clusters_for_tables(retrieved_tables, exact_clusters, sqlite_path=sqlite_path)

                    # Debug: print and log cluster info
                    cluster_debug = f"DEBUG: retrieved_tables={retrieved_tables}, clusters_found={res.get('cluster_ids', [])}, match_type={res.get('match_type', 'N/A')}, num_questions={len(res.get('questions', []))}"
                    print(cluster_debug)
                    if log_file:
                        with open(log_file, 'a', encoding='utf-8') as lf:
                            lf.write(f"\n{'='*60}\nIDX={idx} | {cluster_debug}\n{'='*60}\n")

                # Cluster-filter: prune the Selector's input schema to tables in matched clusters.
                # Gated on --use_cluster (required per design). Empty match → no filter, fall back to full schema.
                if cluster_filter and use_cluster and res and res.get('tables'):
                    allowed_set = set(tables)
                    filtered = [t for t in res['tables'] if t in allowed_set]
                    if filtered:
                        user_message['filtered_tables'] = filtered

                # Compute top_sqls / paths_str (only when history is available)
                if history_df is not None:
                    sql_col_name = f'{cluster}SQL'
                    if use_cluster:
                        if res and res['questions'] and res['indices']:
                            temp_texts, temp_embs = prepare_reference_embeddings(res['questions'], indices=res['indices'])
                            top_results = topk_embedding_cosine_sim(question, temp_texts, temp_embs, top_k=3)
                            top_sqls = " \n".join(history_df.loc[[x[0] for x in top_results], sql_col_name].to_list())
                            if view:
                                top_sqls += " \n" + " \n".join(history_df.loc[[x[0] for x in top_results], f'{cluster}view_SQL'].to_list())
                            paths_str = ', \n'.join(list(set(res['paths'])))
                            user_message['top_sqls'] = top_sqls
                            user_message['paths_str'] = paths_str
                        else:
                            user_message['top_sqls'] = ""
                            user_message['paths_str'] = ""
                    else:
                        top_results = topk_embedding_cosine_sim(question, ref_pairs, ref_embs, top_k=3)
                        top_sqls = " \n".join(history_df.loc[[x[0] for x in top_results], sql_col_name].to_list())
                        if view:
                            top_sqls += " \n" + " \n".join(history_df.loc[[x[0] for x in top_results], f'{cluster}view_SQL'].to_list())
                        user_message['top_sqls'] = top_sqls

                # View mode: look up cached cluster view schemas (independent of use_cluster)
                if view and res and res.get('cluster_ids'):
                    # Spider cluster view names start with plain "cluster{id}_" regardless of rename.
                    # Bird uses the {cluster} prefix ("" for base, "workload_updated_" for renamed).
                    cluster_prefix = "cluster" if dataset == 'spider' else f"{cluster}cluster"
                    selected_clusters_names = [f'{cluster_prefix}{x}_' for x in res['cluster_ids']]
                    selected_clusters_filtered = [name for name in selected_cluster_views if name.startswith(tuple(selected_clusters_names))]
                    if selected_clusters_filtered:
                        view_schema_str = "\n".join(_view_schema_cache[name] for name in selected_clusters_filtered if name in _view_schema_cache)
                        if view_schema_str:
                            user_message['view_schema'] = view_schema_str

            elif ref_pairs is not None:
                # Non-cluster mode: use precomputed embeddings
                sql_col_name = f'{cluster}SQL'
                top_results = topk_embedding_cosine_sim(question, ref_pairs, ref_embs, top_k=3)
                top_sqls = " \n".join(history_df.loc[[x[0] for x in top_results], sql_col_name].to_list())
                user_message['top_sqls'] = top_sqls

            try:
                chat_manager.start(user_message)

                # Clean up message before saving
                for key in ['desc_str', 'fk_str', 'send_to', 'top_sqls', 'paths_str', 'view_schema', 'use_history']:
                    user_message.pop(key, None)

                print(json.dumps(user_message, ensure_ascii=False), file=fp, flush=True)
                print(f"\nPredicted SQL: {user_message.get('pred', 'N/A')}")

            except Exception as e:
                traceback.print_exc()
                print(f"Exception: {e}")
                time.sleep(5)

    print(f"\nResults saved to {output_file}")

    # Export evaluation format
    out_dir = os.path.dirname(output_file) or '.'
    eval_file = f"{out_dir}/predict_results.json"

    output_data = load_jsonl_file(output_file)
    output_data = sorted(output_data, key=lambda x: x['idx'])

    eval_results = []
    for o in output_data:
        pred_sql = replace_multiple_spaces(o.get('pred', '').strip())
        eval_results.append({
            'idx': o['idx'],
            'question': o['query'],
            'predicted_sql': pred_sql,
            'ground_truth': o.get('ground_truth', '')
        })

    with open(eval_file, 'w', encoding='utf-8') as f:
        json.dump(eval_results, f, ensure_ascii=False, indent=2)
    print(f"Evaluation file saved to {eval_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run MAC-SQL with CSV input and single SQLite database")
    parser.add_argument('--input_csv', type=str, required=True, help='Path to input CSV file')
    parser.add_argument('--output_file', type=str, required=True, help='Path to output JSONL file')
    parser.add_argument('--log_file', type=str, default=None, help='Path to log file for prompts')
    parser.add_argument('--start_pos', type=int, default=0, help='Start position (for resuming)')
    parser.add_argument('--without_selector', action='store_true', help='Skip schema pruning')
    parser.add_argument('--question_col', type=str, default='question', help='Column name for questions')
    parser.add_argument('--sql_col', type=str, default='SQL', help='Column name for ground truth SQL')
    parser.add_argument('--fresh', action='store_true', help='Start fresh, ignore previous results')
    parser.add_argument('--history', type=str, default=None,
                        help="Path to history CSV file with 'question' and 'SQL' columns. If provided, uses embedding-based matching to find similar SQLs and uses _history templates.")
    parser.add_argument('--cluster', type=str, default=None,
                        help="Override SQL-column prefix in history CSV. Normally auto-derived from --dataset + --rename "
                             "(bird/rename='workload_updated_', spider/rename='renamed_', otherwise ''). "
                             "Only pass this if your history CSV uses a non-standard column name.")
    parser.add_argument('--rename', type=lambda x: x.lower() == 'true', default=False,
                        help="True to use renamed views (WORKLOAD_VIEWS). False (default) to use original tables (ORG_TABLES).")
    parser.add_argument('--view', type=lambda x: x.lower() == 'true', default=False,
                        help="True to augment cluster mode with view SQL, view paths, and cluster view schemas.")
    parser.add_argument('--use_history', type=lambda x: x.lower() == 'true', default=True,
                        help="If False (and --view True), use base prompt templates without top_sqls/paths_str. Default True.")
    parser.add_argument('--use_cluster', type=lambda x: x.lower() == 'true', default=False,
                        help="If True, restrict history retrieval to cluster-matched questions and inject paths_str. "
                             "If False (default), retrieve top_sqls from the full history pool and do not inject paths_str.")
    parser.add_argument('--dataset', type=str, default='bird', choices=['bird', 'spider'],
                        help="Dataset to run (bird or spider). Selects sqlite path, table/view lists, and linking file.")
    parser.add_argument('--limit', type=int, default=0,
                        help="If > 0, only process the first N rows of the input CSV (for quick testing).")
    parser.add_argument('--cluster_filter', type=lambda x: x.lower() == 'true', default=False,
                        help="If True (requires --use_cluster true), pre-filter the Selector's input schema to only "
                             "the tables found in any matched cluster (union of res['tables']). "
                             "Empty match → fall back to full schema. Output paths auto-substitute '_cluster' → '_clusterfilter'.")
    parser.add_argument('--mapping_path', type=str, default=None,
                        help="Path to name-mapping JSON. Only consulted when --rename is set. "
                             "If omitted, defaults to ../../mapping_files/name_mapping_{dataset}.json "
                             "(relative to this script). Spider uses core.spider_constants.MAPPING_PATH; "
                             "bird uses agents.SelectorUnion.MAPPING_PATH — passing this overrides both.")

    args = parser.parse_args()

    # --mapping_path: override the module-level mapping constant for the active dataset.
    if args.mapping_path:
        if not _os.path.exists(args.mapping_path):
            raise ValueError(f"--mapping_path {args.mapping_path} does not exist.")
        if args.dataset == "spider":
            from core import spider_constants as _sc
            _sc.MAPPING_PATH = args.mapping_path
        else:  # bird
            from core.agents import SelectorUnion as _sel
            _sel.MAPPING_PATH = args.mapping_path
        print(f"--mapping_path override: {args.mapping_path}")

    # Validate: cluster_filter requires use_cluster
    if args.cluster_filter and not args.use_cluster:
        raise ValueError("--cluster_filter true requires --use_cluster true")

    # Resolve dataset-specific sqlite path, table list, linking file, and cluster prefix
    sqlite_path, tables, linking_filename, default_cluster = resolve_dataset_config(args.dataset, args.rename)
    if args.cluster is None:
        args.cluster = default_cluster

    # cluster_filter: substitute '_cluster' → '_clusterfilter' in output_file and log_file
    # so ablation results don't collide with plain --use_cluster runs.
    # Idempotent: only rewrite if the path doesn't already contain '_clusterfilter'.
    def _cf_rewrite(p):
        if p and '_clusterfilter' not in p and '_cluster' in p:
            return p.replace('_cluster', '_clusterfilter')
        return p
    if args.cluster_filter:
        args.output_file = _cf_rewrite(args.output_file)
        args.log_file = _cf_rewrite(args.log_file)

    # Auto-prefix output_file with outputs/{dataset}/ when the path is relative,
    # so bird and spider runs never collide at the repo root.
    if not os.path.isabs(args.output_file):
        if not args.output_file.replace('\\', '/').startswith(f'outputs/{args.dataset}/'):
            args.output_file = os.path.join('outputs', args.dataset, args.output_file)

    print("Configuration:")
    print(f"  Dataset: {args.dataset}")
    print(f"  SQLite path: {sqlite_path}")
    print(f"  Tables: {len(tables)} ({'renamed' if args.rename else 'original'})")
    print(f"  Linking file: {linking_filename}")
    print(f"  Input CSV: {args.input_csv}")
    print(f"  Output file: {args.output_file}")
    print(f"  Log file: {args.log_file}")
    print(f"  Start pos: {args.start_pos}")
    print(f"  Without selector: {args.without_selector}")
    print(f"  Question col: {args.question_col}")
    print(f"  SQL col: {args.sql_col}")
    print(f"  Fresh start: {args.fresh}")
    print(f"  History CSV: {args.history}")
    print(f"  Cluster: '{args.cluster}'")
    print(f"  Rename (use views): {args.rename}")
    print(f"  View mode: {args.view}")
    print(f"  Use history prompts: {args.use_history}")
    print(f"  Use cluster filtering: {args.use_cluster}")
    print(f"  Cluster-filter (schema pre-prune): {args.cluster_filter}")
    print()

    # Validate paths
    if not os.path.exists(args.input_csv):
        raise FileNotFoundError(f"CSV file not found: {args.input_csv}")
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")

    # Create output directory if needed
    out_dir = os.path.dirname(args.output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    run_from_csv(
        csv_path=args.input_csv,
        sqlite_path=sqlite_path,
        output_file=args.output_file,
        tables=tables,
        log_file=args.log_file,
        start_pos=args.start_pos,
        without_selector=args.without_selector,
        question_col=args.question_col,
        sql_col=args.sql_col,
        fresh=args.fresh,
        history_csv=args.history,
        cluster=args.cluster,
        rename=args.rename,
        view=args.view,
        use_history=args.use_history,
        use_cluster=args.use_cluster,
        dataset=args.dataset,
        linking_filename=linking_filename,
        limit=args.limit,
        cluster_filter=args.cluster_filter
    )
