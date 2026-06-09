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
    Returns (sqlite_path, tables, cluster_prefix) for the given dataset + rename.
    cluster_prefix is the SQL-column prefix in the history CSV (e.g. '' → reads 'SQL',
    'renamed_' → reads 'renamed_SQL').

    The legacy on-disk schema-linking JSON has no default — when the user opts
    into ``--linking_source disk`` they must pass ``--linking_filename PATH``
    (absolute or relative) explicitly. Default linking is ``selector``.
    """
    if dataset == 'spider':
        sqlite_path = spider_constants.SQLITE_PATH
        tables = spider_constants.RENAMED_TABLES if rename else spider_constants.ORG_TABLES
        cluster_prefix = 'renamed_' if rename else ''
    elif dataset == 'bird':
        sqlite_path = BIRD_SQLITE_PATH
        tables = BIRD_RENAMED_TABLES if rename else BIRD_ORG_TABLES
        # cluster_prefix is the SQL-column prefix in the history CSV. Aligned
        # with basesql + prep_database: when --rename is on, the rewritten SQL
        # column is 'renamed_SQL' (written by prep_database Phase 5), not
        # 'workload_updated_SQL'.
        cluster_prefix = 'renamed_' if rename else ''
    else:
        raise ValueError(f"Unknown dataset: {dataset}")
    return sqlite_path, tables, cluster_prefix


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
from core.const import SELECTOR_NAME, SYSTEM_NAME
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
    cluster_filter: bool = False,
    cluster_path: str = None,
    linking_source: str = 'selector',
    view_sql_col_override: str = None,
    sql_col_override: str = None,
    column_suffix: str = "",
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
    question_cluster_map: list = []
    history_linking = None
    use_cluster_mode = False
    selected_cluster_views = None
    _view_schema_cache = {}

    # Build the per-INPUT-row linking that gates --cluster_filter. How we
    # derive `retrieved_tables` depends on --linking_source:
    #   - 'selector' (default): no pre-build here; we'll run Selector once per
    #     row with the full schema in the row loop below and read its
    #     extracted_schema. Honest (no gold leak), 1 extra LLM call per row.
    #   - 'gold': peek at df['gt_renamed_tables'] / df['gt_tables'] translated
    #     through table_to_view. Fast but uses gold labels — smoke tests only.
    #   - 'disk': load the legacy workload_updated_history_linking.json from
    #     this script's directory. May be stale w.r.t. current prep_database.
    need_linking = bool(history_csv) or view
    _t2v_lower: dict = {}
    if need_linking and cluster_path and os.path.exists(cluster_path):
        try:
            with open(cluster_path, encoding='utf-8') as _f:
                _prep = json.load(_f)
            if isinstance(_prep.get('rename'), dict) and 'table_to_view' in _prep['rename']:
                _t2v_lower = {str(k).lower(): str(v) for k, v in _prep['rename']['table_to_view'].items()}
            elif 'table_to_view' in _prep:
                _t2v_lower = {str(k).lower(): str(v) for k, v in _prep['table_to_view'].items()}
        except Exception:
            pass

    if need_linking and linking_source == 'gold':
        import ast as _ast_input

        def _parse_list_cell(_val):
            try:
                _tl = _ast_input.literal_eval(_val) if isinstance(_val, str) else _val
            except Exception:
                return None
            return list(_tl) if isinstance(_tl, (list, tuple)) else None

        _derived_input: dict = {}
        if 'gt_renamed_tables' in df.columns:
            for _i, _val in enumerate(df['gt_renamed_tables'].tolist()):
                _tl = _parse_list_cell(_val)
                if _tl is not None:
                    _derived_input[str(_i)] = [str(_t) for _t in _tl]
            _src = "df['gt_renamed_tables']"
        elif 'gt_tables' in df.columns:
            for _i, _val in enumerate(df['gt_tables'].tolist()):
                _tl = _parse_list_cell(_val)
                if _tl is None:
                    continue
                if rename and _t2v_lower:
                    _mapped = [_t2v_lower.get(str(_t).lower(), str(_t)) for _t in _tl]
                else:
                    _mapped = [str(_t) for _t in _tl]
                _derived_input[str(_i)] = _mapped
            _src = "df['gt_tables']" + (" -> table_to_view" if rename and _t2v_lower else "")
        else:
            _src = None

        if _derived_input:
            history_linking = _derived_input
            print(f"⚠️  GOLD-LABEL LINKING (testing only): derived per-row linking from {_src} ({len(_derived_input)} entries).")
        else:
            print("Note: --linking_source=gold requested but input CSV has no gt_tables / gt_renamed_tables column.")
    elif need_linking and linking_source == 'disk':
        # disk mode requires an explicit --linking_filename (absolute path or
        # path relative to this script's directory). No default — if you opt
        # into 'disk', you point at the file. This avoids silently picking up
        # a stale CamelCase legacy file from a prior naming convention.
        if not linking_filename:
            raise SystemExit(
                "--linking_source=disk requires --linking_filename PATH (absolute or relative to "
                + _THIS_DIR + ")."
            )
        linking_path = linking_filename if os.path.isabs(linking_filename) else os.path.join(_THIS_DIR, linking_filename)
        if os.path.exists(linking_path):
            with open(linking_path, 'r', encoding='utf-8') as f:
                history_linking = json.load(f)
            print(f"Loaded history linking from {linking_path} ({len(history_linking)} entries) [user-supplied disk file]")
        else:
            raise SystemExit(f"--linking_source=disk requested but file not found: {linking_path}")
    elif need_linking and linking_source == 'selector':
        print("Linking source: 'selector' — will run Selector once per row with full schema to pick tables for cluster_filter (1 extra LLM call per row, no gold leak).")

    # Pre-cache view schemas (needed whenever --view is on, with or without history)
    if view:
        # Priority order for the cluster-view list:
        #   1. prep_database JSON (cluster_path == args.mapping_path) — source of truth
        #      when --mapping_path is in use. Today's prep produces view names like
        #      'bank_account_dim_join_bank_district_dim' that don't share any prefix
        #      with the historical 'workload_updated_cluster<n>_...' scheme.
        #   2. dataset constants (spider only — bird returns None).
        #   3. DB introspection with the legacy '{cluster_prefix}cluster' filter
        #      (kept as last-resort fallback for older runs without a JSON).
        selected_cluster_views = None
        if cluster_path and os.path.exists(cluster_path):
            try:
                import sys as _sys_v
                _bench_root_v = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
                if _bench_root_v not in _sys_v.path:
                    _sys_v.path.insert(0, _bench_root_v)
                from _common.rename_mapping import load_active_views as _load_av
                _, _json_views = _load_av(cluster_path)
                if _json_views:
                    selected_cluster_views = _json_views
                    print(f"View list: {len(_json_views)} cluster_views from {os.path.basename(cluster_path)}")
            except Exception as _e:
                print(f"Note: could not read cluster_views from {cluster_path}: {_e}")
        if selected_cluster_views is None:
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

        # Load exact_clusters + question_cluster_map whenever clustering is
        # needed (history_linking present OR linking_source=='selector').
        # question_cluster_map is precomputed workload metadata — we use it to
        # look up history rows' cluster IDs at retrieval time so we can pick a
        # cluster for the test question WITHOUT touching any gt_* column.
        if history_linking is not None or linking_source == 'selector':
            exact_clusters = None
            if cluster_path and os.path.exists(cluster_path):
                print(f"Loading precomputed clusters from {cluster_path}")
                with open(cluster_path, encoding="utf-8") as f:
                    _payload = json.load(f)
                # Shape sniff: consolidated (nested 'cluster' section) /
                # legacy flat ('exact_clusters' at top) / raw list dump.
                if isinstance(_payload, list):
                    exact_clusters = _payload
                elif isinstance(_payload.get("cluster"), dict) and "exact_clusters" in _payload["cluster"]:
                    exact_clusters = _payload["cluster"]["exact_clusters"]
                    if "question_cluster_map" in _payload["cluster"]:
                        question_cluster_map = _payload["cluster"]["question_cluster_map"]
                elif "exact_clusters" in _payload:
                    exact_clusters = _payload["exact_clusters"]
                    if "question_cluster_map" in _payload:
                        question_cluster_map = _payload["question_cluster_map"]
                if exact_clusters:
                    print(f"Loaded {len(exact_clusters)} clusters" +
                          (f" + {len(question_cluster_map)} question_cluster_map entries" if question_cluster_map else ""))
                else:
                    print(f"  (no cluster section in {cluster_path}; building from history)")
            if not exact_clusters:
                print("Building clusters from history...")
                exact_clusters = build_clusters_from_history(history_df, cluster, view=view)
            use_cluster_mode = True
            print("Cluster mode enabled.")

        # Embedding load: we need ref_embs whenever (a) we're in the non-cluster
        # fallback path, or (b) linking_source=='selector' and cluster_filter is
        # off (we use embeddings + question_cluster_map to pick a cluster
        # without running Selector twice).
        _need_embs = (not use_cluster_mode) or (not use_cluster) or (
            linking_source == 'selector' and not cluster_filter
        )
        if _need_embs:
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
            has_clusters = exact_clusters is not None and (
                history_linking is not None or linking_source == 'selector'
            )
            if has_clusters:
                # Cluster mode: find relevant clusters and build filtered embeddings
                sql_col_name = f'{cluster}SQL'

                if linking_source == 'selector' and cluster_filter:
                    # Honest pre-pass: run Selector once with the FULL schema (no
                    # filtered_tables, no view_schema, no top_sqls), then read
                    # its extracted_schema to get candidate tables for cluster
                    # matching. Costs 1 extra LLM call per row, no gold leak.
                    #
                    # Selector's output format is {table: "keep_all"|"drop_all"|[cols]}.
                    # It emits ONE entry per table, including "drop_all" for
                    # tables it marks as irrelevant. To get the actually-relevant
                    # tables, keep only entries whose value is a non-empty
                    # column list (Selector actively picked columns) OR exactly
                    # "keep_all". Exclude "drop_all" and empty lists.
                    pre_pass_msg = init_message(idx, question, ground_truth)
                    pre_pass_msg['send_to'] = SELECTOR_NAME
                    pre_pass_msg['use_history'] = False  # keep the pre-pass prompt small
                    retrieved_tables = []
                    try:
                        chat_manager.chat_group[0].talk(pre_pass_msg)
                        _ext = pre_pass_msg.get('extracted_schema', {}) or {}
                        if isinstance(_ext, dict):
                            _kept = set()
                            for _t, _v in _ext.items():
                                if isinstance(_v, str):
                                    if _v.strip().lower() == "drop_all":
                                        continue
                                    _kept.add(str(_t))
                                elif isinstance(_v, (list, tuple)):
                                    if len(_v) > 0:
                                        _kept.add(str(_t))
                            retrieved_tables = sorted(_kept)
                    except Exception as _e:
                        print(f"DEBUG: idx={idx} selector pre-pass failed: {_e}")
                        retrieved_tables = []
                    # Fallback: if Selector kept "everything" (size close to the
                    # full schema), it didn't actually prune. Switch to the
                    # embedding+question_cluster_map approach so cluster_filter
                    # has a meaningful subset to work with.
                    _total = len(tables) if tables else 0
                    if _total and len(retrieved_tables) >= max(int(0.8 * _total), _total - 5):
                        if (ref_pairs is not None and ref_embs is not None
                                and question_cluster_map and exact_clusters):
                            try:
                                _top = topk_embedding_cosine_sim(question, ref_pairs, ref_embs, top_k=3)
                                _id_to_tables = {c['cluster_id']: c.get('tables', []) for c in exact_clusters}
                                _u: set = set()
                                for _x in _top:
                                    _i = _x[0]
                                    if _i < 0 or _i >= len(question_cluster_map):
                                        continue
                                    _cids = question_cluster_map[_i]
                                    if not isinstance(_cids, (list, tuple)):
                                        _cids = [_cids]
                                    for _cid in _cids:
                                        _u.update(_id_to_tables.get(_cid, []))
                                if _u:
                                    retrieved_tables = sorted(str(t) for t in _u)
                                    print(f"DEBUG: idx={idx} selector returned ~all tables; falling back to embedding+question_cluster_map")
                            except Exception:
                                pass
                    print(f"DEBUG: idx={idx}, linking_source=selector (pre-pass), retrieved_tables={retrieved_tables}")
                elif linking_source == 'selector' and not cluster_filter:
                    # cluster_filter=off → skip the Selector pre-pass (the main
                    # Selector pass sees the full schema either way, so a pre-pass
                    # would be redundant). To still pick a cluster for context
                    # injection without an extra LLM call AND without touching any
                    # gt_* column of the test row, we:
                    #   (a) BGE-embed the test question, find top-K nearest history
                    #       questions via cosine similarity, and
                    #   (b) look up those history rows' cluster IDs in
                    #       question_cluster_map (precomputed workload metadata),
                    #       then map each cluster ID to its tables via exact_clusters.
                    # No gt_tables / gt_columns are ever read.
                    retrieved_tables = []
                    if (ref_pairs is not None and ref_embs is not None
                            and question_cluster_map and exact_clusters):
                        try:
                            _top = topk_embedding_cosine_sim(question, ref_pairs, ref_embs, top_k=3)
                            _id_to_tables = {c['cluster_id']: c.get('tables', []) for c in exact_clusters}
                            _u: set = set()
                            for _x in _top:
                                _i = _x[0]
                                if _i < 0 or _i >= len(question_cluster_map):
                                    continue
                                _cids = question_cluster_map[_i]
                                if not isinstance(_cids, (list, tuple)):
                                    _cids = [_cids]
                                for _cid in _cids:
                                    _u.update(_id_to_tables.get(_cid, []))
                            retrieved_tables = sorted(str(t) for t in _u)
                        except Exception as _e:
                            print(f"DEBUG: idx={idx} embedding+cluster-id retrieval failed: {_e}")
                    print(f"DEBUG: idx={idx}, linking_source=selector (embedding→question_cluster_map, no pre-pass), retrieved_tables={retrieved_tables}")
                else:
                    # gold / disk: look up the pre-built history_linking dict.
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
                            _sql_col = sql_col_override or sql_col_name
                            _view_col = view_sql_col_override or f'{cluster}view_SQL'
                            top_sqls = " \n".join(history_df.loc[[x[0] for x in top_results], _sql_col].to_list())
                            if view:
                                top_sqls += " \n" + " \n".join(history_df.loc[[x[0] for x in top_results], _view_col].to_list())
                            paths_str = ', \n'.join(list(set(res['paths'])))
                            user_message['top_sqls'] = top_sqls
                            user_message['paths_str'] = paths_str
                        else:
                            user_message['top_sqls'] = ""
                            user_message['paths_str'] = ""
                    else:
                        top_results = topk_embedding_cosine_sim(question, ref_pairs, ref_embs, top_k=3)
                        _sql_col = sql_col_override or sql_col_name
                        _view_col = view_sql_col_override or f'{cluster}view_SQL'
                        top_sqls = " \n".join(history_df.loc[[x[0] for x in top_results], _sql_col].to_list())
                        if view:
                            top_sqls += " \n" + " \n".join(history_df.loc[[x[0] for x in top_results], _view_col].to_list())
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

    # Write predictions back to the input CSV so multiple runs accumulate
    # side-by-side, then compute EX for the final SQL column.
    import sys as _sys_wb
    _bench_root_wb = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if _bench_root_wb not in _sys_wb.path:
        _sys_wb.path.insert(0, _bench_root_wb)
    from _common.evaluate import write_back_to_input_csv
    _macsql_col = f"macsql{column_suffix}"
    _pred_df = pd.DataFrame(
        {_macsql_col: [replace_multiple_spaces(o.get('pred', '').strip()) for o in output_data]},
        index=[o['idx'] for o in output_data],
    )
    write_back_to_input_csv(
        csv_path=csv_path,
        df_predicted=_pred_df,
        column_names=[_macsql_col],
        final_sql_col=_macsql_col,
        db_path=sqlite_path,
        gold_sql_col="SQL",
        pipeline_tag="MAC-SQL",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run MAC-SQL with CSV input and single SQLite database. "
                    "CLI is aligned with basesql / din-sql / csc_sql — same flag names, "
                    "same toggle style (boolean store_true), same path semantics."
    )

    # --- Core (aligned with basesql) ---
    parser.add_argument('--dataset', type=str, default='bird', choices=['bird', 'spider'],
                        help="Dataset (bird or spider). Selects sqlite path, table/view lists, and linking file.")
    parser.add_argument('--csv_path', type=str, default=None,
                        help="Path to input CSV. If omitted, auto-resolves to "
                             "../../csvs/nl2sql_{dataset}.csv.")
    parser.add_argument('--db_path', type=str, default=None,
                        help="Path to SQLite database. If omitted, uses the dataset's built-in "
                             "constant (BIRD_SQLITE_PATH / spider_constants.SQLITE_PATH).")
    parser.add_argument('--model', type=str, default='gpt-4.1-mini',
                        help="OpenAI model. Default: gpt-4.1-mini (matches basesql/din-sql). "
                             "Overrides MODEL_NAME in core/api_config.py at runtime.")
    parser.add_argument('--output_file', type=str, default=None,
                        help="Path to output JSONL file. If omitted, auto-resolves to "
                             "<LDD>/outputs/MAC-SQL/<dataset>/run_<timestamp><suffix>.jsonl.")
    parser.add_argument('--log_file', type=str, default=None,
                        help="Path to prompt log file. If omitted, auto-resolves to "
                             "<LDD>/logs/MAC-SQL/<dataset>/run_<timestamp><suffix>.log.")
    parser.add_argument('--rows', type=str, default=None, metavar='SPEC',
                        help="Row selection. 'N' for the first N rows, or 'START:END' for a python-style "
                             "half-open slice (e.g. '100:150' = 50 rows starting at index 100).")
    parser.add_argument('--question_col', type=str, default=None,
                        help="Input-CSV column holding the question. If omitted, auto-resolves "
                             "from the mapping JSON's columns.question (default 'question').")
    parser.add_argument('--sql_col', type=str, default=None,
                        help="Input-CSV column holding the (optional) ground-truth SQL. If omitted, "
                             "auto-resolves from the mapping JSON's columns.sql (default 'SQL').")
    parser.add_argument('--fresh', action='store_true',
                        help="Ignore previous output and start over. Default: resume from prior --output_file.")

    # --- Selector control (MAC-SQL specific) ---
    parser.add_argument('--without_selector', action='store_true',
                        help='Skip schema pruning (Selector agent) — Decomposer sees the full schema.')

    # --- Schema variants (aligned bool flags) ---
    parser.add_argument('--rename', action='store_true',
                        help="Use renamed views (WORKLOAD_VIEWS) instead of original tables (ORG_TABLES).")
    parser.add_argument('--view', action='store_true',
                        help="Augment with view SQL, view paths, and cluster view schemas.")
    parser.add_argument('--mapping_path', type=str, default=None,
                        help="Path to name-mapping JSON. Only consulted when --rename is set. "
                             "If omitted, auto-resolves to ../../mapping_files/name_mapping_{dataset}.json.")

    # --- History (aligned 3-state: --history bool + --history_path) ---
    parser.add_argument('--history', action='store_true',
                        help="Enable history mode. When set with no --history_path, defaults to "
                             "../../csvs/sample_{dataset}.csv. Passing --history_path implicitly enables history.")
    parser.add_argument('--history_path', type=str, default=None,
                        help="Path to history CSV. Implies --history when provided.")
    parser.add_argument('--history_sql_col_prefix', type=str, default=None,
                        help="Override SQL-column prefix in history CSV. Normally auto-derived from "
                             "--dataset + --rename (bird/rename='workload_updated_', spider/rename='renamed_', "
                             "otherwise ''). Only pass when your history CSV uses a non-standard column name.")

    # --- Cluster (aligned with basesql --cluster + --cluster_filter) ---
    parser.add_argument('--cluster', action='store_true',
                        help="Restrict history retrieval to cluster-matched questions and inject "
                             "common-join-paths into the Decomposer's prompt.")
    parser.add_argument('--linking_source', type=str, default='selector',
                        choices=['selector', 'gold', 'disk'],
                        help="How to derive the per-row table list that gates --cluster_filter. "
                             "'selector' (default): run Selector once with the full schema as an honest "
                             "pre-pass, take its picked tables, then re-run Selector on the cluster-filtered "
                             "schema (1 extra LLM call per row, no gold leak). "
                             "'gold': peek at df['gt_tables'] translated through table_to_view — fast but "
                             "uses gold labels, valid only for smoke tests. "
                             "'disk': load a user-supplied schema-linking JSON; requires --linking_filename.")
    parser.add_argument('--linking_filename', type=str, default=None,
                        help="Required when --linking_source=disk. Absolute path to a per-row schema-linking "
                             "JSON, or a filename relative to benchmarks/MAC-SQL/. No default — if you opt "
                             "into 'disk', you point at the file explicitly.")
    parser.add_argument('--cluster_filter', action=argparse.BooleanOptionalAction, default=None,
                        help="Pre-filter the Selector's input schema to only tables in any matched cluster. "
                             "Empty match → fall back to full schema. Output paths auto-substitute "
                             "'_cluster' → '_clusterfilter'. Defaults to ON whenever --cluster is set; "
                             "pass --no-cluster_filter to inject clusters without filtering. "
                             "Has no effect when --cluster is off.")

    args = parser.parse_args()

    # --- Path auto-resolution (relative to this script's parent-parent = LDD root) ---
    _this_dir = _os.path.dirname(_os.path.abspath(__file__))
    _ldd_root = _os.path.abspath(_os.path.join(_this_dir, '..', '..'))
    if args.csv_path is None:
        args.csv_path = _os.path.join(_ldd_root, 'csvs', f'nl2sql_{args.dataset}.csv')
        print(f"[run_union] --csv_path auto-resolved to {args.csv_path}")

    # History gating (matches basesql semantics):
    #   --history_path FILE  -> implies --history, uses FILE
    #   --history alone      -> uses default ../../csvs/sample_{dataset}.csv
    #   neither              -> history disabled
    if args.history_path:
        args.history = True
    elif args.history:
        args.history_path = _os.path.join(_ldd_root, 'csvs', f'sample_{args.dataset}.csv')
        if not _os.path.exists(args.history_path):
            raise SystemExit(
                f"--history requested but default sample file not found at {args.history_path}. "
                f"Pass --history_path explicitly or drop --history."
            )
        print(f"[run_union] --history_path auto-resolved to {args.history_path}")

    # --cluster_filter defaults to args.cluster when not explicitly set
    if args.cluster_filter is None:
        args.cluster_filter = bool(args.cluster)

    # Cluster precomputed file: re-use --mapping_path (the consolidated prep config
    # holds both the rename mapping and the cluster section).
    if args.cluster and not args.mapping_path:
        _suffix = "_renamed" if args.rename else ""
        _cand = _os.path.join(_ldd_root, "mapping_files", f"prep_{args.dataset}{_suffix}.json")
        args.mapping_path = _cand
        if _os.path.exists(_cand):
            print(f"[run_union] --mapping_path auto-resolved to {_cand}")
        else:
            print(f"[run_union] --mapping_path auto-resolved to {_cand} "
                  f"(not found — will build clusters from history)")

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

    # Resolve dataset-specific sqlite path, table list, and default cluster prefix
    sqlite_path, tables, default_cluster = resolve_dataset_config(args.dataset, args.rename)
    if args.db_path:
        sqlite_path = args.db_path
        print(f"--db_path override: {sqlite_path}")
    if args.history_sql_col_prefix is None:
        args.history_sql_col_prefix = default_cluster

    # JSON-as-source-of-truth: when a mapping file is supplied, its top-level
    # ``tables`` drives the active table list — applies regardless of --rename,
    # since the JSON records the right list for whichever mode prep_database
    # ran in (original base names without --rename, renamed views with it).
    if args.mapping_path and _os.path.exists(args.mapping_path):
        import sys as _sys_for_view
        _bench_root_for_view = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), _os.pardir))
        if _bench_root_for_view not in _sys_for_view.path:
            _sys_for_view.path.insert(0, _bench_root_for_view)
        from _common.rename_mapping import load_active_views
        _json_tables, _json_views = load_active_views(args.mapping_path)
        if _json_tables:
            print(f"📋 --mapping_path: using {len(_json_tables)} tables from {_os.path.basename(args.mapping_path)}")
            tables = _json_tables

    # Fill --question_col / --sql_col / history_sql_col_prefix from the mapping
    # JSON's 'columns' section when the user did not pass them explicitly.
    # Precedence: explicit CLI > mapping JSON > static default.
    if args.mapping_path and _os.path.exists(args.mapping_path):
        import sys as _sys_for_cols
        _bench_root_for_cols = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), _os.pardir))
        if _bench_root_for_cols not in _sys_for_cols.path:
            _sys_for_cols.path.insert(0, _bench_root_for_cols)
        from _common.rename_mapping import load_active_columns
        _json_cols = load_active_columns(args.mapping_path)
        if args.question_col is None:
            args.question_col = _json_cols.get("question", "question")
            if _json_cols.get("question"):
                print(f"--question_col auto-resolved to {args.question_col!r} (from mapping JSON)")
        if args.sql_col is None:
            args.sql_col = _json_cols.get("sql", "SQL")
            if _json_cols.get("sql"):
                print(f"--sql_col auto-resolved to {args.sql_col!r} (from mapping JSON)")
        # MAC-SQL's history retrieval reads f'{prefix}SQL' / f'{prefix}view_SQL'.
        # Derive the prefix from columns.sql when the user did not set it.
        if args.history_sql_col_prefix is None and _json_cols.get("sql"):
            _sql_name = _json_cols["sql"]
            if _sql_name.endswith("SQL"):
                args.history_sql_col_prefix = _sql_name[:-3]
                print(f"--history_sql_col_prefix auto-resolved to {args.history_sql_col_prefix!r} (from mapping JSON columns.sql={_sql_name!r})")
        # Stash the full view_sql column name as an attribute so run_from_csv
        # can pass it through as view_sql_col_override. Without this, the
        # f'{prefix}view_SQL' construction silently writes 'view_SQL' when the
        # prep was run with a custom --view_sql_col (e.g. my_custom_view_sql).
        if _json_cols.get("view_sql"):
            args.view_sql_col = _json_cols["view_sql"]
            print(f"--view_sql_col auto-resolved to {args.view_sql_col!r} (from mapping JSON columns.view_sql)")
    if args.question_col is None:
        args.question_col = "question"
    if args.sql_col is None:
        args.sql_col = "SQL"
    if not hasattr(args, "view_sql_col"):
        args.view_sql_col = None

    # Parse --rows SPEC -> (start_pos, limit)
    _start_pos = 0
    _limit = 0
    if args.rows is not None:
        if ':' in args.rows:
            _a, _b = args.rows.split(':', 1)
            _start_pos = int(_a) if _a.strip() else 0
            _end = int(_b) if _b.strip() else 0
            _limit = (_end - _start_pos) if _end > 0 else 0
        else:
            _limit = int(args.rows)

    # cluster_filter: substitute '_cluster' → '_clusterfilter' in output_file + log_file
    def _cf_rewrite(p):
        if p and '_clusterfilter' not in p and '_cluster' in p:
            return p.replace('_cluster', '_clusterfilter')
        return p
    if args.cluster_filter:
        args.output_file = _cf_rewrite(args.output_file)
        args.log_file = _cf_rewrite(args.log_file)

    # Path auto-resolution: route artifacts under LDD/{outputs,logs}/MAC-SQL/<dataset>/
    # so they don't flood the benchmarks folder. Defaults mirror basesql's
    # naming: run_<timestamp><suffix>.{jsonl,log}.
    import sys as _sys
    import time as _time
    _bench_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if _bench_root not in _sys.path:
        _sys.path.insert(0, _bench_root)
    from _common.paths import default_log_dir, default_output_dir

    def _macsql_suffix(a: argparse.Namespace) -> str:
        s = ""
        if a.rename: s += "_rename"
        if a.view: s += "_withview"
        if a.cluster: s += "_clusterfilter" if a.cluster_filter else "_cluster"
        if a.history: s += "_history"
        if a.without_selector: s += "_noselector"
        if a.model and a.model != "gpt-4.1-mini":
            digits = "".join(c for c in a.model if c.isdigit())
            s += f"_gpt{digits}"
        return s

    _run_id = _time.strftime("%Y%m%d-%H%M%S")
    _run_tag = f"run_{_run_id}{_macsql_suffix(args)}"

    if args.output_file is None:
        args.output_file = os.path.join(
            default_output_dir("MAC-SQL", args.dataset), f"{_run_tag}.jsonl"
        )
    elif not os.path.isabs(args.output_file):
        args.output_file = os.path.join(
            default_output_dir("MAC-SQL", args.dataset), args.output_file
        )

    if args.log_file is None:
        args.log_file = os.path.join(
            default_log_dir("MAC-SQL", args.dataset), f"{_run_tag}.log"
        )
    elif not os.path.isabs(args.log_file):
        args.log_file = os.path.join(
            default_log_dir("MAC-SQL", args.dataset), args.log_file
        )

    os.makedirs(os.path.dirname(args.output_file) or '.', exist_ok=True)
    os.makedirs(os.path.dirname(args.log_file) or '.', exist_ok=True)

    # --model override: mutate MODEL_NAME in BOTH api_config and llm modules
    # (llm did `from core.api_config import MODEL_NAME` which creates a local
    # binding, so we must set both for the change to take effect everywhere).
    if args.model != 'gpt-4.1-mini':
        from core import api_config as _api_cfg
        from core import llm as _llm_mod
        _api_cfg.MODEL_NAME = args.model
        _llm_mod.MODEL_NAME = args.model
        print(f"--model override: {args.model}")

    print("Configuration:")
    print(f"  Dataset: {args.dataset}")
    print(f"  SQLite path: {sqlite_path}")
    print(f"  Tables: {len(tables)} ({'renamed' if args.rename else 'original'})")
    print(f"  Linking source: {args.linking_source}" + (f" (--linking_filename={args.linking_filename!r})" if getattr(args, 'linking_filename', None) else ""))
    print(f"  Input CSV: {args.csv_path}")
    print(f"  Output file: {args.output_file}")
    print(f"  Log file: {args.log_file}")
    print(f"  Rows: {args.rows or 'all'}  (start_pos={_start_pos}, limit={_limit})")
    print(f"  Without selector: {args.without_selector}")
    print(f"  Question col: {args.question_col}")
    print(f"  SQL col: {args.sql_col}")
    print(f"  Fresh start: {args.fresh}")
    print(f"  History CSV: {args.history_path}")
    print(f"  History SQL col prefix: '{args.history_sql_col_prefix}'")
    print(f"  Rename (use views): {args.rename}")
    print(f"  View mode: {args.view}")
    print(f"  Cluster: {args.cluster}")
    print(f"  Cluster-filter (schema pre-prune): {args.cluster_filter}")
    print()

    # Validate paths
    if not os.path.exists(args.csv_path):
        raise FileNotFoundError(f"CSV file not found: {args.csv_path}")
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")

    # Create output directory if needed
    out_dir = os.path.dirname(args.output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    run_from_csv(
        csv_path=args.csv_path,
        sqlite_path=sqlite_path,
        output_file=args.output_file,
        tables=tables,
        log_file=args.log_file,
        start_pos=_start_pos,
        without_selector=args.without_selector,
        question_col=args.question_col,
        sql_col=args.sql_col,
        fresh=args.fresh,
        history_csv=args.history_path,
        cluster=args.history_sql_col_prefix,
        rename=args.rename,
        view=args.view,
        use_history=bool(args.history_path),  # injection follows file presence (basesql semantics)
        use_cluster=args.cluster,
        dataset=args.dataset,
        linking_filename=getattr(args, 'linking_filename', None),
        limit=_limit,
        cluster_filter=args.cluster_filter,
        cluster_path=args.mapping_path,
        linking_source=args.linking_source,
        view_sql_col_override=getattr(args, 'view_sql_col', None),
        sql_col_override=None,  # MAC-SQL still constructs sql_col_name from prefix; only view_sql gets the JSON override for now
        column_suffix=_macsql_suffix(args),
    )
