import sqlite3
import json
import re
import glob
import os
import ast
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
import pandas as pd
import statistics
from func_timeout import func_set_timeout, FunctionTimedOut
from typing import List, Tuple, Union
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.sql_database import SQLDatabase
db_path_base = "D:/WORK/PhD/column retrieval/exp/bird/dev/dev_databases/"
if not os.environ.get("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
#CHAT = ChatOpenAI(model="gpt-3.5-turbo",temperature=0,max_tokens=2000)
CHAT = ChatOpenAI(model="gpt-4.1-mini",temperature=0,max_tokens=2000)

import argparse

def extract_json_block(text: str):
    """
    Extracts the JSON object from a ChatGPT response that may contain reasoning,
    code fences, or extra commentary.
    """
    text = text.replace(';\\"', ';"').replace('\\"SELECT', '"SELECT')
    if "```json" in text:
        match = re.search(r"```json(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0).strip()

    raise ValueError("No JSON found in response")


def parse_view_base_tables(view_name: str):
    """Extract base tables from a view name. Handles three shapes:
      - 'cluster<N>_<t1>_join_<t2>(_join_<tN>)*'
      - 'workload_updated_cluster<N>_<t1>_join_<t2>(_join_<tN>)*'
      - bare '<t1>_join_<t2>(_join_<tN>)*'  (no cluster prefix, e.g. bird_org_views_50)
    An optional trailing '_view' (single-table views like 'income_view') is stripped.
    """
    m = re.match(r'^(?:workload_updated_)?cluster\d+_(.+)$', view_name)
    core = m.group(1) if m else view_name
    if core.endswith('_view'):
        core = core[: -len('_view')]
    return core.split('_join_') if core else []


def find_matching_views(views_pool, retrieved_tables):
    """Return all views from the pool that contain at least one of retrieved_tables."""
    rt_lower = {str(t).lower() for t in retrieved_tables}
    out = []
    for v in views_pool:
        bases = parse_view_base_tables(v)
        if any(b.lower() in rt_lower for b in bases):
            out.append(v)
    return out


def append_log(log_dir: str, index: int, section: str, body: str) -> None:
    """Append a labeled section to the per-question log file."""
    fp = os.path.join(log_dir, f"q{int(index):04d}.log")
    with open(fp, "a", encoding="utf-8") as f:
        f.write(f"\n===== {section} =====\n")
        f.write(body if body is not None else "")
        f.write("\n")


def load_rename_mapping(mapping_path: str, org_keyed_columns: bool = False):
    """Load a name-mapping JSON and return:
       table_to_view:        {org_table_lower: renamed_view}  (case-insensitive keys)
       view_org_to_renamed:  {renamed_view: {org_col_lower: renamed_col}}

    org_keyed_columns: controls how the inner column dict is interpreted.
      False (spider): inner dict is {renamed_col: org_col}
      True  (bird):   inner dict is {org_col: renamed_col}
    """
    with open(mapping_path, encoding="utf-8") as f:
        m = json.load(f)
    # Case-insensitive table lookup (handles mixed-case org table names)
    table_to_view = {k.lower(): v for k, v in m["table_to_view"].items()}
    column_mapping = m["column_mapping"]
    view_org_to_renamed = {}
    for view, cols in column_mapping.items():
        if org_keyed_columns:
            view_org_to_renamed[view] = {k.lower(): v for k, v in cols.items()}
        else:
            view_org_to_renamed[view] = {v.lower(): k for k, v in cols.items()}
    return table_to_view, view_org_to_renamed


def fetch_org_fks(db_path: str, org_tables):
    """Return a list of (from_table, from_col, ref_table, ref_col) tuples for FKs
    declared between tables in `org_tables`. Reads PRAGMA foreign_key_list.
    """
    org_lower = {t.lower(): t for t in org_tables}
    out = []
    seen = set()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        for t in org_tables:
            try:
                rows = cur.execute(f"PRAGMA foreign_key_list('{t}')").fetchall()
            except sqlite3.DatabaseError:
                continue
            for row in rows:
                # (id, seq, ref_table, from_col, to_col, on_update, on_delete, match)
                ref_table = row[2]
                from_col = row[3]
                to_col = row[4]
                if not ref_table or not from_col or not to_col:
                    continue
                if ref_table.lower() not in org_lower:
                    continue
                key = (t.lower(), from_col.lower(), ref_table.lower(), to_col.lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append((t, from_col, ref_table, to_col))
    finally:
        conn.close()
    return out


def build_renamed_fk_block(db_path: str, org_tables, mapping_path: str,
                           org_keyed_columns: bool = False) -> str:
    """Translate each FK declared between `org_tables` into the renamed namespace
    and return a 'Foreign Keys:' block string.

    org_keyed_columns: passed through to load_rename_mapping (False=spider, True=bird).
    Returns "" if no FKs translate cleanly.
    """
    table_to_view, view_org_to_renamed = load_rename_mapping(mapping_path, org_keyed_columns)
    fks = fetch_org_fks(db_path, org_tables)

    lines = []
    skipped = []
    for from_t, from_c, ref_t, ref_c in fks:
        from_view = table_to_view.get(from_t.lower())
        ref_view = table_to_view.get(ref_t.lower())
        if not from_view or not ref_view:
            skipped.append((from_t, from_c, ref_t, ref_c, "table not in mapping"))
            continue
        from_renamed = view_org_to_renamed.get(from_view, {}).get(from_c.lower())
        ref_renamed = view_org_to_renamed.get(ref_view, {}).get(ref_c.lower())
        if not from_renamed or not ref_renamed:
            skipped.append((from_t, from_c, ref_t, ref_c, "column not in mapping"))
            continue
        lines.append(f"{from_view}.{from_renamed} = {ref_view}.{ref_renamed}")

    if skipped:
        print(f"⚠️  {len(skipped)}/{len(fks)} FK lines could not be translated:")
        for s in skipped[:10]:
            print(f"     {s}")
        if len(skipped) > 10:
            print(f"     ... and {len(skipped) - 10} more")

    if not lines:
        return ""

    return "Foreign Keys:\n" + "\n".join(sorted(set(lines))) + "\n\n"

#spider_syn = pd.read_csv("spider/revised_spider_syn.csv")
# spider_syn = pd.read_csv("spider/filtered_spider_syn_dataset.csv")
# #merged_schemas = pd.read_excel("merge_data_spider_new.xlsx")
# merged_schemas = pd.read_excel("merge_fk_only_spider_new.xlsx")

# db_path_base  = "D:/WORK/PhD/column retrieval/exp/spider/database/"
# schemas = list(spider_syn['database_schema'])
# dbs = list(spider_syn['db_id'])
# questions = list(spider_syn['question'])
# ground_truth_sqls = list(spider_syn['query'])

from openai import OpenAI
import os

# Lazy-initialized in main() based on --model
client = None          # OpenAI client (for --model gpt)
gemini_client = None   # Google GenAI client (for --model gemini)


def ensure_openai():
    """Lazy-init OpenAI client + LangChain CHAT. Only called when --model gpt or stage 1 needs GPT."""
    global CHAT, client
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY environment variable is not set.")
    if client is None:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if CHAT is None:
        CHAT = ChatOpenAI(
            model="gpt-4.1-mini", temperature=0, max_tokens=2000,
            openai_api_key=os.environ["OPENAI_API_KEY"],
        )


def ensure_gemini():
    """Lazy-init Google GenAI client. Only called when --model gemini."""
    global gemini_client
    if gemini_client is None:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise SystemExit("GEMINI_API_KEY environment variable is not set.")
        gemini_client = genai.Client(api_key=api_key)


def chat_with_chatgpt_DIN(prompt, model="gpt-4.1-mini"):
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        n=1, stream=False, temperature=0.0, max_completion_tokens=10000,
        top_p=1.0, frequency_penalty=0.0, presence_penalty=0.0,
    )
    return response.choices[0].message.content


def chat_with_gemini_DIN(prompt, model="gemini-2.5-flash-lite", response_fields=None):
    """Call Gemini. If response_fields is provided (e.g. {"SQL": str}), use structured output."""
    from google.genai import types
    from pydantic import create_model

    config_kwargs = dict(temperature=0.0, max_output_tokens=10000, top_p=1.0)
    if response_fields:
        schema_model = create_model("DynResponse", **{k: (v, ...) for k, v in response_fields.items()})
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = schema_model

    response = gemini_client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return response.text

def chat_with_claude(prompt: str, model: str = "claude-3-haiku-20240307") -> str:
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=2000,
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    # Claude returns a list of content blocks, extract text
    return "".join(block.text for block in response.content)

@func_set_timeout(60)
def execute_sql(cursor, sql):
    cursor.execute(sql)
    sql_res = cursor.fetchall()

    return sql_res

def compare_sql(predicted_sql, ground_truth, db_path):
    conn = sqlite3.connect(db_path, check_same_thread = False)
    conn.text_factory = bytes
    # Connect to the database
    cursor = conn.cursor()

    ground_truth_res = execute_sql(cursor, ground_truth)
    try:
        predicted_res = execute_sql(cursor, predicted_sql)
    except Exception as e:
        #print("raises an error: {}.".format(str(e)))
        return 0, None, ground_truth_res
    except FunctionTimedOut as fto:
        #print("raises an error: time out.")
        return 0, None, ground_truth_res

    res = 0
    if set(predicted_res) == set(ground_truth_res):
        res = 1
    return res, predicted_res, ground_truth_res

def get_database_schema(DB_URI: str, table_name: Union[str, List[str], None] = None, sample_rows: int = 3, include_views: bool = False) -> str:
    """Get the database schema from the database URI

    Args:
        DB_URI (str): Database URI
        table_name (str | list, optional): If str, extract schema for that single table.
                                           If list, extract schema for all tables in the list.
                                           If None, extracts schema for all tables.
        sample_rows (int): Number of sample rows to include. Set to 0 if datetime parsing errors occur.
        include_views (bool): If True, include views in the schema. Default is False.

    Returns:
        str: Database schema
    """
    db = SQLDatabase.from_uri("sqlite:///"+DB_URI, sample_rows_in_table_info=sample_rows, view_support=include_views)
    
    if table_name is None:
        return db.get_table_info_no_throw()
    elif isinstance(table_name, str):
        return db.get_table_info_no_throw(table_names=[table_name])
    elif isinstance(table_name, list):
        return db.get_table_info_no_throw(table_names=table_name)
    else:
        return db.get_table_info_no_throw()

@func_set_timeout(90)
# ⭐ NEW optional alias parameters
def generate_schema_prompt(
    db_path,
    num_rows=None,
    no_join=False,
    target_table="all",
    extracted_values=None,
    alias_map=None,          # ⭐ NEW
    alias_namespace="workload"   # ⭐ NEW
):
    full_schema_prompt_list = []
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if no_join:
        cursor.execute("""SELECT name FROM sqlite_master 
                          WHERE type='table' AND name != 'sqlite_sequence' 
                          AND name != 'sqlite_stat1' AND name not like '%_join_%';""")
    else:
        if target_table != "all":
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type in ('table', 'view') "
                "AND lower(name) = lower('{}');".format(target_table)
            )
        else:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type in ('table', 'view') "
                "AND name != 'sqlite_sequence' AND name != 'sqlite_stat1';"
            )

    tables = cursor.fetchall()
    schemas = {}

    if extracted_values is None:
        extracted_values = {}

    for table in tables:
        tname = table[0]
        if tname == "sqlite_sequence":
            continue

        # get original create SQL
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type in ('table','view') AND name=?",
            (tname,)
        )
        raw_sql = cursor.fetchone()[0]

        final_sql = raw_sql

        # ⭐ Inject inline alias comments inside CREATE TABLE body
        if alias_map and tname in alias_map:
            lines = raw_sql.split("\n")
            new_lines = []

            for line in lines:
                stripped = line.strip()
                tokens = stripped.split()

                if tokens:
                    raw_col_token = tokens[0].strip("`\"")  # ⭐ handles `id`, "id", id

                    if (
                        raw_col_token in alias_map[tname]
                        and alias_namespace in alias_map[tname][raw_col_token]
                        and "--" not in stripped
                    ):
                        alias_comment = alias_map[tname][raw_col_token][alias_namespace]
                        line = f"{line}    -- {alias_namespace} alias: {alias_comment}"

                new_lines.append(line)

            final_sql = "\n".join(new_lines)

        schemas[tname] = final_sql

        # ============================================================
        # existing row sample logic (unchanged)
        # ============================================================
        if num_rows:
            cur_table = tname
            cursor.execute("SELECT * FROM `{}` LIMIT {}".format(cur_table, num_rows))
            column_names = [description[0] for description in cursor.description]
            db_rows = cursor.fetchall()

            extracted_rows = []
            table_extracted = {
                col.split(".", 1)[1]: vals
                for col, vals in extracted_values.items()
                if col.split(".", 1)[0].lower() == cur_table.lower()
            }

            if table_extracted:
                max_len = max(len(vs) for vs in table_extracted.values())
                for i in range(max_len):
                    row_dict = {c: "" for c in column_names}
                    for col, vals in table_extracted.items():
                        if col in row_dict and i < len(vals):
                            row_dict[col] = vals[i]
                    extracted_rows.append(tuple(row_dict[c] for c in column_names))

            final_rows = list(db_rows) + extracted_rows

            rows_prompt = nice_look_table(column_names=column_names, values=final_rows)

            verbose_prompt = "/* \n {} rows from {}: \n {} \n */".format(
                len(final_rows), cur_table, rows_prompt
            )

            schemas[tname] = schemas[tname] + "\n\n" + verbose_prompt

    for _, v in schemas.items():
        full_schema_prompt_list.append(v)

    schema_prompt = "\n\n".join(full_schema_prompt_list)

    return schema_prompt

def nice_look_table(column_names: list, values: list):
    rows = []
    # Determine the maximum width of each column
    widths = [max(len(str(value[i])) for value in values + [column_names]) for i in range(len(column_names))]

    # Print the column names
    header = ''.join(f'{column.rjust(width)} ' for column, width in zip(column_names, widths))
    # print(header)
    # Print the values
    for value in values:
        row = ''.join(f'{str(v).rjust(width)} ' for v, width in zip(value, widths))
        rows.append(row)
    rows = "\n".join(rows)
    final_output = header + '\n' + rows
    return final_output

import pandas as pd
# df / sample are loaded inside main()


from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# Lazy-loaded — only initialized when --history is enabled (see ensure_bge_model)
model = None

def ensure_bge_model():
    """Lazy-load the BGE encoder; called only when --history is set."""
    global model
    if model is None:
        model = SentenceTransformer('BAAI/bge-large-en-v1.5', device='cuda')
    return model

# 1️⃣ Prepare reference embeddings
def prepare_reference_embeddings(str_list, indices=None):
    """
    Compute embeddings for a list of strings.
    If 'indices' is provided, they are used; otherwise defaults to [0..N-1].
    Returns:
        ref_pairs: [(index, text), ...]
        embeddings: np.ndarray
    """
    if indices is None:
        indices = list(range(len(str_list)))
    else:
        # Safety: ensure lengths match
        assert len(indices) == len(str_list), (
            f"indices length ({len(indices)}) must match str_list length ({len(str_list)})"
        )

    #embeddings = model.encode(str_list, normalize_embeddings=True)
    _m = ensure_bge_model()
    texts = ["passage: " + str(s).strip() for s in str_list]       # ⭐ BGE improvement
    embeddings = _m.encode(texts, normalize_embeddings=True)
    ref_pairs = list(zip(indices, str_list))
    return ref_pairs, embeddings

# 2️⃣ Query top-K matches
def topk_embedding_cosine_sim(target_str, ref_pairs, ref_embeddings, top_k=5):
    """
    Compare target string against precomputed embeddings of (index, text) pairs.
    Returns: [(index, text, similarity_score)]
    """
    # Embed target
    #target_emb = model.encode([target_str], normalize_embeddings=True)
    _m = ensure_bge_model()
    target_emb = _m.encode(
        ["query: " + str(target_str).strip()],                    # ⭐ BGE improvement
        normalize_embeddings=True
    )

    # Compute cosine similarity
    similarities = cosine_similarity(target_emb, ref_embeddings).flatten()

    # Get top-K sorted indices
    top_idx = similarities.argsort()[::-1][:top_k]

    # Map back to (original index, text)
    results = [
        (ref_pairs[i][0], ref_pairs[i][1], float(similarities[i]))
        for i in top_idx
    ]
    return results

# (embedding reference prep moved into main when history is enabled)


import re
import itertools
from collections import Counter, defaultdict
from typing import List, Tuple, Dict, Set, Optional
from itertools import combinations, chain
from sentence_transformers import SentenceTransformer, util
import torch
# import itertools
# sql = list(sample['SQL'])
# from lineagex import lineagex
# lx = lineagex(sql, dialect='sqlite')
# data = lx.output_dict
# t_list = []
# c_list = []
# for index in range(0, len(sample)):
#     if str(index) in data.keys():
#         lx_t = data[str(index)]['tables']
#         lx_c = []
#         for k, v in data[str(index)]['columns'].items():
#             lx_c.extend(list(itertools.chain.from_iterable(v)))
#         lx_c = list(set(lx_c))
#         t_list.append(lx_t)
#         c_list.append(lx_c)
#     else:
#         t_list.append([""])
#         c_list.append([""])
#         print("failed idx: ", index)

# ------------------------------------------------------------
# 🧱 NORMALIZATION HELPERS
# ------------------------------------------------------------

def normalize_table_name(name: str) -> str:
    """Normalize table name for comparison (schema/quotes removed)."""
    name = re.sub(r'^[A-Z_]+\.', '', name)  # remove schema prefix like FIBEN.
    name = name.replace('"', '').replace("'", "")
    return name.strip().upper()

def _cluster_norm_cache(clusters) -> Dict[int, Set[str]]:
    """Return cluster_id -> normalized table-name set."""
    return {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters
    }

# ------------------------------------------------------------
# 🔍 CLUSTER FINDING (STRICT)
# ------------------------------------------------------------

def find_best_cluster_combo_strict(query_tables, clusters):
    """
    Priority:
      1) Exact single-cluster match
      2) Subset of a single cluster (smallest cluster, then lowest ID)
      3) Subset of the union of two clusters (ONLY if no single superset)
         - minimize extras |union - qset|
         - minimize union size
         - lowest cluster IDs
      4) new
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return [], "new"

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = _cluster_norm_cache(clusters_sorted)

    # 1️⃣ exact
    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            return [c], "exact"

    # 2️⃣ single superset
    supersets = [
        c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])
    ]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        return [supersets[0]], "subset"

    # 3️⃣ combination of two clusters (only if no single superset)
    candidates = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    best_pair, best_key = None, None  # (extras, union_size, id1, id2)
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

    # 4️⃣ no match → new cluster
    return [], "new"

# ------------------------------------------------------------
# 🧠 INITIAL CLUSTER CREATION
# ------------------------------------------------------------

def find_exact_query_patterns(list_of_table_lists, path_list, min_frequency=5, min_tables=4):
    """
    Build initial frequent table clusters. Case-insensitive keys so rows whose
    gt_tables differ only by casing (e.g. ['Match','Country'] vs ['match','country'])
    are counted as the same pattern. First-seen casing is preserved for the output.
    """
    exact_patterns = Counter()
    pattern_paths = defaultdict(set)
    pattern_repr = {}  # key -> list of original-case table names (first-seen wins)

    for tables, path in zip(list_of_table_lists, path_list):
        key = frozenset(t.lower() for t in tables)
        exact_patterns[key] += 1
        pattern_paths[key].add(path)
        if key not in pattern_repr:
            seen = {}
            for t in tables:
                seen.setdefault(t.lower(), t)
            pattern_repr[key] = list(seen.values())

    clusters = []
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
                "combo_pairs": {}  # store idx -> (id1, id2) for subset_combo
            })
            cluster_id += 1

    clusters.sort(key=lambda x: (x["count"], x["num_tables"]), reverse=True)
    return clusters

# ------------------------------------------------------------
# 🧩 ASSIGN QUERIES TO CLUSTERS
# ------------------------------------------------------------

def assign_queries_to_clusters(list_of_table_lists, clusters, question_list, path_list, min_tables=4):
    """
    Additive assignment with strict combination matching.
    Each question belongs to exactly one cluster.
    For subset_combo, record the partner cluster id.
    """
    question_cluster_map = []
    question_combo_map = {}  # global idx -> (id1, id2)
    assigned_questions = set()
    next_cluster_id = max([c["cluster_id"] for c in clusters], default=0) + 1

    for idx, tables in enumerate(list_of_table_lists):
        if not tables or idx in assigned_questions:
            question_cluster_map.append(-1)
            continue

        matched, match_type = find_best_cluster_combo_strict(tables, clusters)
        qtext, qpath = question_list[idx], path_list[idx]

        # ---- Case 1: Exact or subset (single cluster)
        if len(matched) == 1:
            c = matched[0]
            c["indices"].append(idx)
            c["questions"].append(qtext)
            c["paths"].append(qpath)
            c["match_types"].append(match_type)
            question_cluster_map.append(c["cluster_id"])
            assigned_questions.add(idx)

        # ---- Case 2: Subset of combo of 2 clusters
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

        # ---- Case 3: New cluster
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

    # Recompute counts
    for c in clusters:
        c["count"] = len(c["indices"])

    question_cluster_map = [[n] for n in question_cluster_map]
    for k, v in question_combo_map.items():
        question_cluster_map[k] = list(v)

    return question_cluster_map

# ------------------------------------------------------------
# 📊 SUBSET COMPUTATION
# ------------------------------------------------------------

def compute_subsets_inplace(clusters, list_of_table_lists, path_list):
    """Compute subsets per cluster (normalize only for matching)."""
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

# ------------------------------------------------------------
# ✅ USAGE EXAMPLE
# ------------------------------------------------------------

min_tables = 2
w_flag = "workload_updated_"
def simplify_sql(query: str) -> str:
    """
    Given a SQL string, return the same SQL but with:
    - Projections replaced by SELECT *
    - Anything after the FROM/JOINs removed (WHERE, GROUP BY, ORDER BY, LIMIT...)
    """
    # Normalize whitespace
    q = " ".join(query.strip().split())
    
    # Find FROM ... part
    match = re.search(r"\bFROM\b", q, re.IGNORECASE)
    if not match:
        raise ValueError("No FROM clause found in query")

    from_start = match.start()

    # Cut at FROM
    q_from = q[from_start:]

    # # Stop at first WHERE/GROUP BY/ORDER BY/LIMIT
    stop_match = re.search(r"\b(WHERE|GROUP BY|ORDER BY|HAVING|LIMIT)\b", q_from, re.IGNORECASE)
    if stop_match:
        q_from = q_from[:stop_match.start()]

    # Build simplified SQL
    simplified = f"{q_from.strip()}"
    return simplified
# cluster construction moved into build_clusters_from_history() — called from main()

def normalize_table_name(name: str) -> str:
    """
    Normalize for equality/containment checks only.
    - Strip any schema prefix (lower/mixed/upper): schema.table -> table
    - Remove common quoting
    - Uppercase for robust matching
    """
    if name is None:
        return ""
    s = str(name).strip().strip('"').strip("'").strip('`').strip()
    # remove any single schema prefix like foo.bar (case-insensitive on characters)
    s = re.sub(r'^[A-Za-z0-9_]+\.', '', s)
    # also allow bracketed names [dbo].[Member] -> Member
    s = re.sub(r'^\[[^\]]+\]\.', '', s)
    return s.upper()

def _build_cluster_result(match_type, cluster_list, sqlite_path):
    """Merge cluster info and attach detected foreign keys (preserving original casing)."""
    tables = sorted(set(chain.from_iterable(c["tables"] for c in cluster_list)))
    paths  = sorted(set(chain.from_iterable(c.get("paths", []) for c in cluster_list)))
    cluster_ids = [c["cluster_id"] for c in cluster_list]

    fks = find_foreign_keys_between_tables(sqlite_path, tables) if sqlite_path else []

    return {
        "match_type": match_type,
        "cluster_ids": cluster_ids,
        "tables": tables,          # original casing from clusters
        "paths": paths,
        "foreign_keys": fks,       # original casing for table names
    }

def find_cluster_for_tables(query_tables, clusters, sqlite_path=None):
    """
    Guarantees: exact match first; otherwise find the minimal number of clusters
    whose union ⊇ query_tables (then minimize extras, then union size, then IDs).
    Output now matches find_all_clusters_for_tables (includes questions, indices).
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        # 🔹 ADDED: include missing fields for consistency
        return {
            "match_type": "new",
            "cluster_ids": [],
            "tables": [],
            "paths": [],
            "foreign_keys": [],
            "questions": [],
            "indices": [],
        }

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    # 1️⃣ Exact single cluster
    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            # 🔹 ADDED: include questions + indices
            return _build_cluster_result("exact", [c], sqlite_path) | {
                "questions": c.get("questions", []),
                "indices": c.get("indices", []),
            }

    # 2️⃣ Single-cluster superset
    supersets = [c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        c = supersets[0]
        # 🔹 ADDED: include questions + indices
        return _build_cluster_result("subset", [c], sqlite_path) | {
            "questions": c.get("questions", []),
            "indices": c.get("indices", []),
        }

    # 3️⃣ Minimal subset cover (fewest clusters)
    candidates = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    best_combo, best_key = None, None
    for r in range(2, len(candidates) + 1):
        for combo in combinations(candidates, r):
            u = set().union(*(norm_by_id[c["cluster_id"]] for c in combo))
            if qset.issubset(u):
                extras = len(u - qset)
                key = (r, extras, len(u), [c["cluster_id"] for c in combo])
                if best_key is None or key < best_key:
                    best_key, best_combo = key, combo
        if best_combo:
            break

    if best_combo:
        # 🔹 ADDED: merged questions + indices (like find_all_clusters_for_tables)
        all_questions = list(chain.from_iterable(c.get("questions", []) for c in best_combo))
        all_indices = list(chain.from_iterable(c.get("indices", []) for c in best_combo))
        seen_q, seen_i = set(), set()
        merged_q, merged_i = [], []
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

    # 4️⃣ No coverage → new
    # 🔹 ADDED: include missing fields
    return {
        "match_type": "new",
        "cluster_ids": [],
        "tables": [],
        "paths": [],
        "foreign_keys": [],
        "questions": [],
        "indices": [],
    }

def find_foreign_keys_between_tables(sqlite_path, tables):
    """
    Detect declared FKs via PRAGMA foreign_key_list for each table *as given*.
    - Membership checks use normalized names
    - Output preserves the original table names/casing provided in `tables`
    Returns: ["A.col=B.col", ...] with original table casing.
    """
    if not tables:
        return []

    # map normalized -> first seen original (for pretty printing)
    norm_to_orig = {}
    for t in tables:
        n = normalize_table_name(t)
        norm_to_orig.setdefault(n, t)

    norm_set = set(norm_to_orig.keys())
    out = set()

    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    try:
        for t in tables:
            t_norm = normalize_table_name(t)
            # PRAGMA table name: keep original text; single quotes are ok for SQLite identifiers in PRAGMA
            try:
                cur.execute(f"PRAGMA foreign_key_list('{t}')")
                rows = cur.fetchall()
            except sqlite3.DatabaseError:
                rows = []

            for row in rows:
                # row layout: (id, seq, table, from, to, on_update, on_delete, match, ...)
                ref_table_raw = row[2]
                from_col = row[3]
                to_col   = row[4]

                ref_norm = normalize_table_name(ref_table_raw)
                if t_norm in norm_set and ref_norm in norm_set:
                    lhs = f"{norm_to_orig[t_norm]}.{from_col}"
                    rhs = f"{norm_to_orig[ref_norm]}.{to_col}"
                    out.add(f"{lhs}={rhs}")
    finally:
        conn.close()

    return sorted(out)


# ============================================================
# --view_adhoc helpers: LLM-generated CREATE VIEW on linked tables
# ============================================================
def find_fk_conditions_for_view_adhoc(db_path, tables, rename_mode=False,
                                      mapping_path=None, ds_org_tables=None,
                                      org_keyed=False):
    """FK condition strings between pairs of `tables` in the active namespace.

    Non-rename: PRAGMA foreign_key_list via find_foreign_keys_between_tables.
    Rename: translate original FKs to the renamed namespace and filter to `tables`.
    Returns sorted list like ['T1.col=T2.col', ...] (empty if none found).
    """
    if not tables or len(tables) < 2:
        return []
    if not rename_mode:
        return find_foreign_keys_between_tables(db_path, tables)
    if not ds_org_tables or not mapping_path:
        return []
    tset = {t.lower() for t in tables}
    table_to_view, view_org_to_renamed = load_rename_mapping(mapping_path, org_keyed)
    out = set()
    for from_t, from_c, ref_t, ref_c in fetch_org_fks(db_path, ds_org_tables):
        from_view = table_to_view.get(from_t.lower())
        ref_view = table_to_view.get(ref_t.lower())
        if not from_view or not ref_view:
            continue
        if from_view.lower() not in tset or ref_view.lower() not in tset:
            continue
        from_renamed = view_org_to_renamed.get(from_view, {}).get(from_c.lower())
        ref_renamed = view_org_to_renamed.get(ref_view, {}).get(ref_c.lower())
        if not from_renamed or not ref_renamed:
            continue
        out.add(f"{from_view}.{from_renamed}={ref_view}.{ref_renamed}")
    return sorted(out)


def create_adhoc_view(db_path, tables, fk_conditions, model, is_gemini,
                      num_rows=3, max_attempts=3, excluded_views=None):
    """Ask the LLM for a CREATE VIEW over `tables` using `fk_conditions`, run it,
    and return (view_name, view_schema_prompt). Returns (None, None) on failure.

    If the view already exists in the DB, reuse it (no drop/recreate) — but only if
    its name is NOT in `excluded_views` (the pre-defined org_views/renamed_views pool).
    If the intended view_name itself collides with an excluded name, bail out to
    avoid stomping on a pre-existing cluster view.
    """
    if len(tables) < 2 or not fk_conditions:
        return None, None
    view_name = "_join_".join(tables)

    excluded_lc = {v.lower() for v in (excluded_views or [])}
    if view_name.lower() in excluded_lc:
        print(f"[adhoc view] ⛔ intended name {view_name!r} collides with a pre-defined "
              f"(cluster) view — falling back to base schema")
        return None, None

    # Per-table schemas (no joins) to ground the LLM
    base_pieces = []
    for t in tables:
        try:
            base_pieces.append(
                generate_schema_prompt(db_path=db_path, num_rows=num_rows,
                                       no_join=False, target_table=t)
            )
        except Exception:
            continue
    base_schema_for_prompt = "\n\n".join(base_pieces)

    prompt = f"""You are a database expert. Please give me the SQL script for creating the joined table on foreign keys.
The new view name should be in the format of `table1_join_table2` where table1 and table2 are the names of the tables that are joined together.
Keep all the original column, unless there is a name conflict.
In that case, change those columns from table1 into `table1_column`, and those columns from table2 into `table2_column`, only need to change the columns that has a name conflict.

Here is an example task:
###
Database Schema
CREATE TABLE Examination
(
    ID                 INTEGER          null,
    `Examination Date` DATE         null,
    `aCL IgG`          REAL        null,
    `aCL IgM`          REAL        null,
    ANA                INTEGER          null,
    `ANA Pattern`      TEXT null,
    `aCL IgA`          INTEGER          null,
    Diagnosis          TEXT null,
    KCT                TEXT null,
    RVVT               TEXT null,
    LAC                TEXT null,
    Symptoms           TEXT null,
    Thrombosis         INTEGER          null,
    foreign key (ID) references Patient (ID)
            on update cascade on delete cascade
)

CREATE TABLE Patient
(
    ID           INTEGER default 0 not null
        primary key,
    SEX          TEXT  null,
    Birthday     DATE          null,
    Description  DATE          null,
    `First Date` DATE          null,
    Admission    TEXT  null,
    Diagnosis    TEXT  null
)
###

Tables to be joined: ['Patient', 'Examination']
Join conditions: ['Examination.ID = Patient.ID']
New table name: Patient_join_Examination

Please respond with a JSON object structured as follows:

{{
    "chain_of_thought_reasoning": "The foreign key on these tables are the Patient.ID and Examination.ID and it is also in the join conditions. We need to join the Patient and Examination tables on the ID column. The new table name should be Patient_join_Examination. All columns from the Patient table has no conflict except the ID columns, so ID from Patient is renamed to Patient_ID, and ID from the Examination table is renamed to Examination_ID.",
    "SQL": "CREATE VIEW `Patient_join_Examination` AS SELECT `Patient`.`ID` AS `Patient_ID`, `Patient`.`SEX` AS `SEX`, `Patient`.`Birthday` AS `Birthday`, `Patient`.`Description` AS `Description`, `Patient`.`First Date` AS `First Date`, `Patient`.`Admission` AS `Admission`, `Patient`.`Diagnosis` AS `Diagnosis`, `Examination`.`ID` AS `Examination_ID`, `Examination`.`Examination Date` AS `Examination Date`, `Examination`.`aCL IgG` AS `aCL IgG`, `Examination`.`aCL IgM` AS `aCL IgM`, `Examination`.`ANA` AS `ANA`, `Examination`.`ANA Pattern` AS `ANA Pattern`, `Examination`.`aCL IgA` AS `aCL IgA`, `Examination`.`Diagnosis` AS `Diagnosis`, `Examination`.`KCT` AS `KCT`, `Examination`.`RVVT` AS `RVVT`, `Examination`.`LAC` AS `LAC`, `Examination`.`Symptoms` AS `Symptoms`, `Examination`.`Thrombosis` AS `Thrombosis` FROM `Patient` JOIN `Examination` ON `Examination`.`ID` = `Patient`.`ID`;"
}}

###
The new view name should be in the format of `table1_join_table2_join_...` where tables are joined together.
Keep all the original columns, unless there is a name conflict.
In that case, change those columns from tableA into `tableA_column`, and those columns from tableB into `tableB_column`, only need to change the columns that has a name conflict.
Now, here is a new schema for creating a new view:
{base_schema_for_prompt}

###

Tables to be joined: {list(tables)}
Join conditions: {fk_conditions}
New table name: {view_name}

Please respond with a JSON object structured as follows, and make sure each entry is there and follows the same format as the given format:
{{
    "chain_of_thought_reasoning": "Your thought process on how you arrived at the final SQL query",
    "SQL": "The CREATE VIEW SQL query for the new table based on the join conditions as well as the new column names."
}}

Carefully read the given schema, make sure all columns are there for the given table, do not hallucinate and mix up the columns between tables. If you follow all the instructions and answer correctly, I will give you 1 million dollars."""

    # If a view with this name already exists in the DB (persisted from a prior run
    # or the same run), reuse it IFF it is actually queryable (a previous failed attempt
    # can register a broken view with an invalid SELECT; those must be dropped and redone).
    _CONN_TIMEOUT = 60  # seconds — raise from sqlite3 default (5s) to survive contention
    _BUSY_PRAGMA_MS = 30_000

    def _view_status():
        """Return 'missing' | 'valid' | 'broken' for view_name."""
        try:
            conn = sqlite3.connect(db_path, timeout=_CONN_TIMEOUT)
            cur = conn.cursor()
            try:
                cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='view' AND lower(name)=lower(?)",
                    (view_name,),
                )
                row = cur.fetchone()
                if not row:
                    return "missing"
                # Query one row to validate the view's SELECT resolves.
                try:
                    cur.execute(f"SELECT * FROM `{row[0]}` LIMIT 1")
                    cur.fetchone()
                    return "valid"
                except Exception:
                    return "broken"
            finally:
                cur.close(); conn.close()
        except Exception:
            return "missing"

    def _drop_view():
        try:
            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=_CONN_TIMEOUT)
            cur = conn.cursor()
            cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
            execute_sql(cur, f"DROP VIEW IF EXISTS `{view_name}`")
            cur.close(); conn.close()
            return True
        except Exception as _e:
            print(f"[adhoc view]    ⚠️  could not DROP broken view {view_name!r}: "
                  f"{type(_e).__name__}: {_e}")
            return False

    status = _view_status()
    if status == "valid":
        # Already-exists + queryable → reuse (unless it collides with excluded pool)
        if view_name.lower() in excluded_lc:
            print(f"[adhoc view] ⛔ existing view {view_name!r} is in the pre-defined pool — "
                  f"refusing to reuse; falling back to base schema")
            return None, None
        print(f"[adhoc view] 🔁 reusing existing view {view_name!r} (valid, no recreate)")
        try:
            view_schema = generate_schema_prompt(
                db_path=db_path, num_rows=num_rows, no_join=False, target_table=view_name
            )
            return view_name, view_schema
        except Exception as e:
            print(f"[adhoc view]    ⚠️  reading existing view schema failed: "
                  f"{type(e).__name__}: {e} — dropping and recreating")
            _drop_view()
    elif status == "broken":
        print(f"[adhoc view] ⚠️  existing view {view_name!r} is BROKEN — dropping before recreate")
        _drop_view()

    print(f"[adhoc view] 🛠️  creating view {view_name!r}")
    print(f"[adhoc view]    tables ({len(tables)}): {list(tables)}")
    print(f"[adhoc view]    fk_conditions ({len(fk_conditions)}): {fk_conditions}")
    print(f"[adhoc view]    model={model!r} (gemini={is_gemini})")

    for attempt in range(max_attempts):
        try:
            print(f"[adhoc view]    → LLM attempt {attempt + 1}/{max_attempts}")
            if is_gemini:
                resp = chat_with_gemini_DIN(prompt, model=model,
                                            response_fields={"SQL": str})
            else:
                resp = chat_with_chatgpt_DIN(prompt, model=model)
            if resp.find("```json") != -1:
                resp = resp[resp.find("```json"):]
            parsed = ast.literal_eval(resp.replace("```json", "").replace("```", ""))
            create_sql = parsed["SQL"]
            preview = " ".join(str(create_sql).split())
            print(f"[adhoc view]    LLM CREATE VIEW (first 200 chars): {preview[:200]}")

            # Defensive: drop any broken view left by a previous failed attempt so
            # the fresh CREATE VIEW doesn't collide with a stale registration.
            _drop_view()

            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=_CONN_TIMEOUT)
            conn.text_factory = bytes
            cur = conn.cursor()
            try:
                cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
                execute_sql(cur, create_sql)
            finally:
                cur.close()
                conn.close()

            # Validate by reading the view's schema (this executes the SELECT and would
            # raise 'no such column' if the LLM's CREATE VIEW is semantically broken).
            view_schema = generate_schema_prompt(
                db_path=db_path, num_rows=num_rows, no_join=False, target_table=view_name
            )
            print(f"[adhoc view]    ✅ created {view_name!r} "
                  f"(schema {len(view_schema)} chars)")
            return view_name, view_schema
        except Exception as e:
            print(f"[adhoc view]    ❌ attempt {attempt + 1}/{max_attempts} failed: "
                  f"{type(e).__name__}: {e}")
            # Drop the broken view (if any) so it doesn't collide with the next attempt
            # or interfere with future questions in this session.
            _drop_view()
            continue
    print(f"[adhoc view]    ⛔ giving up on {view_name!r} after {max_attempts} attempts — "
          f"fall back to base schema")
    return None, None


# db_path comes from CLI args (--db_path) inside main()
def find_similar_question_cluster(
    question, clusters, question_cluster_map, model=None, top_k=1, sqlite_path=None
):
    """
    Returns top-k similar questions with their clusters, tables, paths, and FKs.
    FKs use original table casing.
    """
    if model is None:
        # model = SentenceTransformer('all-MiniLM-L6-v2',
        #                             device='cuda' if torch.cuda.is_available() else 'cpu')
        model = SentenceTransformer('BAAI/bge-large-en-v1.5',
                                    device='cuda' if torch.cuda.is_available() else 'cpu')
    # flatten all questions and keep their original indices
    all_questions, q_indices = [], []
    for c in clusters:
        for i, q in zip(c["indices"], c.get("questions", [])):
            all_questions.append(q)
            q_indices.append(i)

    if not all_questions:
        raise ValueError("No questions found in clusters.")

    all_embs = model.encode(all_questions, convert_to_tensor=True, normalize_embeddings=True)
    q_emb = model.encode(question, convert_to_tensor=True, normalize_embeddings=True)
    sims = util.cos_sim(q_emb, all_embs)[0]

    top_k = min(top_k, len(all_questions))
    top_indices = torch.topk(sims, k=top_k).indices.tolist()

    cluster_by_id = {c["cluster_id"]: c for c in clusters}
    results = []

    for idx in top_indices:
        sim_score = sims[idx].item()
        matched_question = all_questions[idx]
        original_idx = q_indices[idx]
        cluster_ids = question_cluster_map[original_idx] if original_idx < len(question_cluster_map) else []

        matched_tables, matched_paths = [], []
        for cid in cluster_ids:
            c = cluster_by_id.get(cid)
            if c:
                matched_tables.extend(c["tables"])         # keep original casing
                matched_paths.extend(c.get("paths", []))

        fks = find_foreign_keys_between_tables(sqlite_path, matched_tables) if sqlite_path else []

        results.append({
            "best_question": matched_question,
            "similarity": sim_score,
            "cluster_ids": cluster_ids,
            "tables": sorted(set(matched_tables)),         # original casing
            "paths": sorted(set(matched_paths)),
            "foreign_keys": fks,                           # original casing
        })

    return results
# (find_similar_question_cluster test removed — function still defined for use elsewhere)

def find_all_clusters_for_tables(query_tables, clusters, sqlite_path=None):
    """
    Enhanced version (contract-correct):
    - Returns ALL clusters that contain one or more of the tables from query_tables.
    - Keeps same input/output type and backward-compatible fields.
    - Also returns aligned 'questions' and 'indices' fields:
        * de-duplicated while preserving order
        * ith question corresponds to ith index
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return {
            "match_type": "new",
            "cluster_ids": [],
            "tables": [],
            "paths": [],
            "foreign_keys": [],
            "questions": [],
            "indices": [],
        }

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    # 1️⃣ Collect ALL clusters with ANY overlap
    overlapping_clusters = [
        c for c in clusters_sorted
        if (qset & norm_by_id[c["cluster_id"]])
    ]

    if not overlapping_clusters:
        return {
            "match_type": "new",
            "cluster_ids": [],
            "tables": [],
            "paths": [],
            "foreign_keys": [],
            "questions": [],
            "indices": [],
        }

    # 2️⃣ Determine match_type WITHOUT pruning overlap
    any_exact = any(qset == norm_by_id[c["cluster_id"]] for c in overlapping_clusters)
    any_subset = any(qset <  norm_by_id[c["cluster_id"]] for c in overlapping_clusters)

    if any_exact:
        match_type = "exact"
    elif any_subset:
        match_type = "subset"
    else:
        match_type = "partial"

    # 3️⃣ Merge questions + indices (aligned, de-duplicated, order preserved)
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

    # 4️⃣ Build final result using ALL overlapping clusters
    result = _build_cluster_result(match_type, overlapping_clusters, sqlite_path)
    result["questions"] = merged_questions
    result["indices"] = merged_indices
    return result
# res = find_all_clusters_for_tables(ast.literal_eval(df[f'gt_{w_flag}tables'][0]), exact_clusters, sqlite_path=db_path)
# print("------")
# print(res["cluster_ids"], res["match_type"])
# print("Foreign Keys:", res["foreign_keys"])


SYSTEM_SCHEMA_LINKING_TEMPLATE = """
You are an agent designed to find the schema_links for generating SQL queries for each question based on the database schema and Foreign keys.
Hint helps you to fine the correct schema_links.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

#
Question: Which year has the least number of movies that was released and what is the title of the movie in that year that has the highest number of rating score of 1?
Please respond with a JSON object structured as follows:
{{
    "chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked: "Which year" so we need column = [movies.movie_release_year]
"number of movies" so we need column = [movies.movie_id]
"title of the movie" so we need column = [movies.movie_title]
"rating score" so we need column = [ratings.rating_score]
Based on the columns and tables, we need these Foreign_keys = [movies.movie_id = ratings.movie_id].
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [1]",
    "schema_links": [`movies`.`movie_release_year`, `movies`.`movie_title`, `ratings`.`rating_score`, `movies`.`movie_id=ratings.movie_id`, 1]
}}


Schema of the database with sample rows:
#
CREATE TABLE lists (
        user_id INTEGER, 
        list_id INTEGER NOT NULL, 
        list_title TEXT, 
        list_movie_number INTEGER, 
        list_update_timestamp_utc TEXT, 
        list_creation_timestamp_utc TEXT, 
        list_followers INTEGER, 
        list_url TEXT, 
        list_comments INTEGER, 
        list_description TEXT, 
        list_cover_image_url TEXT, 
        list_first_image_url TEXT, 
        list_second_image_url TEXT, 
        list_third_image_url TEXT, 
        PRIMARY KEY (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id)
)

/*
3 rows from lists table:
user_id list_id list_title      list_movie_number       list_update_timestamp_utc       list_creation_timestamp_utc     list_followers  list_url        list_commentslist_description list_cover_image_url    list_first_image_url    list_second_image_url   list_third_image_url
88260493        1       Films that made your kid sister cry     5       2019-01-24 19:16:18     2009-11-11 00:02:21     5       http://mubi.com/lists/films-that-made-your-kid-sister-cry     3       <p>Don’t be such a baby!!</p>
<p><strong>bold</strong></p>    https://assets.mubicdn.net/images/film/3822/image-w1280.jpg?1445914994  https://assets.mubicdn.net/images/film/3822/image-w320.jpg?1445914994 https://assets.mubicdn.net/images/film/506/image-w320.jpg?1543838422    https://assets.mubicdn.net/images/film/485/image-w320.jpg?1575331204
45204418        2       Headscratchers  3       2018-12-03 15:12:20     2009-11-11 00:05:11     1       http://mubi.com/lists/headscratchers    2       <p>Films that need at least two viewings to really make sense.</p>
<p>Or at least… they did for <em>       https://assets.mubicdn.net/images/film/4343/image-w1280.jpg?1583331932  https://assets.mubicdn.net/images/film/4343/image-w320.jpg?1583331932 https://assets.mubicdn.net/images/film/159/image-w320.jpg?1548864573    https://assets.mubicdn.net/images/film/142/image-w320.jpg?1544094102
48905025        3       Sexy Time Movies        7       2019-05-30 03:00:07     2009-11-11 00:20:00     6       http://mubi.com/lists/sexy-time-movies  5       <p>Films that get you in the mood…for love. In development.</p>
<p>Remarks</p>
<p><strong>Enter the    https://assets.mubicdn.net/images/film/3491/image-w1280.jpg?1564112978  https://assets.mubicdn.net/images/film/3491/image-w320.jpg?1564112978https://assets.mubicdn.net/images/film/2377/image-w320.jpg?1564675204    https://assets.mubicdn.net/images/film/2874/image-w320.jpg?1546574412
*/

CREATE TABLE lists_users (
        user_id INTEGER NOT NULL, 
        list_id INTEGER NOT NULL, 
        list_update_date_utc TEXT, 
        list_creation_date_utc TEXT, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_avatar_image_url TEXT, 
        user_cover_image_url TEXT, 
        user_eligible_for_trial TEXT, 
        user_has_payment_method TEXT, 
        PRIMARY KEY (user_id, list_id), 
        FOREIGN KEY(list_id) REFERENCES lists (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists (user_id)
)

/*
3 rows from lists_users table:
user_id list_id list_update_date_utc    list_creation_date_utc  user_trialist   user_subscriber user_avatar_image_url   user_cover_image_url    user_eligible_for_trial       user_has_payment_method
85981819        1969    2019-11-26      2009-12-18      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        3946    2020-05-01      2010-01-30      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        6683    2020-04-12      2010-03-31      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
*/

#
Question: Among the lists created by user 4208563, which one has the highest number of followers? Indicate how many followers it has and whether the user was a subscriber or not when he created the list.
Please respond with a JSON object structured as follows:
{{
    "chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked:
"user" so we need column = [lists_users.user_id]
"number of followers" so we need column = [lists.list_followers]
"user was a subscriber or not" so we need column = [lists_users.user_subscriber]
Based on the columns and tables, we need these Foreign_keys = [lists.user_id = lists_user.user_id,lists.list_id = lists_user.list_id].
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [1, 4208563]",
    "schema_links": [`lists`.`list_followers`,`lists_users`.`user_subscriber`,`lists`.`user_id = lists_users`.`user_id`,`lists`.`list_id = lists_users`.`list_id`,`lists_users`.`user_id`, 4208563, 1]
}}"""

HUMAN_SCHEMA_LINKING_TEMPLATE = """
For the given question, find the schema links between the question and the table.
###
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
A: Let's think step by step. In the question , we are asked:
"""

SYSTEM_SCHEMA_LINKING_TEMPLATE_JOIN = """
You are an agent designed to find the schema_links for generating SQL queries for each question based on the database schema and Foreign keys.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

CREATE VIEW `movies_join_ratings` AS
SELECT
  `movies`.`movie_id` AS `movies_movie_id`,
  `movies`.`movie_title`,
  `movies`.`movie_release_year`,
  `movies`.`movie_url`,
  `movies`.`movie_title_language`,
  `movies`.`movie_popularity`,
  `movies`.`movie_image_url`,
  `movies`.`director_id`,
  `movies`.`director_name`,
  `movies`.`director_url`,
  `ratings`.`movie_id` AS `ratings_movie_id`,
  `ratings`.`rating_id`,
  `ratings`.`rating_url`,
  `ratings`.`rating_score`,
  `ratings`.`rating_timestamp_utc`,
  `ratings`.`critic`,
  `ratings`.`critic_likes`,
  `ratings`.`critic_comments`,
  `ratings`.`user_id`,
  `ratings`.`user_trialist`,
  `ratings`.`user_subscriber`,
  `ratings`.`user_eligible_for_trial`,
  `ratings`.`user_has_payment_method`
FROM `movies`
JOIN `ratings` ON `ratings`.`movie_id` = `movies`.`movie_id` 

 /* 3 rows from movies_join_ratings: 
 movies_movie_id                movie_title movie_release_year                                      movie_url movie_title_language movie_popularity                                           movie_image_url director_id director_name                     director_url ratings_movie_id rating_id                                            rating_url rating_score rating_timestamp_utc critic critic_likes critic_comments  user_id user_trialist user_subscriber user_eligible_for_trial user_has_payment_method 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          15610495 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495                    3           2017-06-10 12:38:33   None            0               0 41579158             0               0                       1                       0 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          10704606 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606                    2           2014-08-15 23:42:31   None            0               0 85981819             1               1                       0                       1 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          10177114 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114                    2           2014-01-30 13:21:57   None            0               0  4208563             0               0                       1                       1  
 */
#
 
Question: Which year has the least number of movies that was released and what is the title of the movie in that year that has the highest number of rating score of 1?
Please respond with a JSON object structured as follows:
{{
    "chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked: 
Based on the columns and tables, we need to join movies and ratings, so we can use the table that is the joined result of movies and ratings tables: movies_join_ratings.
Since we are using the joined table, there is no need for foreign keys, and columns should come from that table as well.
"Which year" so we need column = [movies_join_ratings.movie_release_year]
"number of movies" so we need column = [movies_join_ratings.movies_movie_id]
"title of the movie" so we need column = [movies_join_ratings.movie_title]
"rating score" so we need column = [movies_join_ratings.rating_score]
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [1]",
    "schema_links": [`movies_join_ratings`.`movie_release_year`, `movies_join_ratings`.`movie_title`, `movies_join_ratings`.`rating_score`, `movies_join_ratings`.`movies_movie_id`, 1]
}}

Question: How many users gave \"Pavee Lackeen: The Traveller Girl\" movie a rating score of 4?
Please respond with a JSON object structured as follows:
{{
    "chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked:
Based on the columns and tables, we need to join movies and ratings, so we can use the table that is the joined result of movies and ratings tables: movies_join_ratings.
Since we are using the joined table, there is no need for foreign keys, and columns should come from that table as well
"users" so we need column = [movies_join_ratings.user_id]
\"Pavee Lackeen: The Traveller Girl\" movie so we need column = [movies_join_ratings.movie_title]
"rating score" so we need column = [movies_join_ratings.rating_score]
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [4, \"Pavee Lackeen: The Traveller Girl\"].",
    "schema_links": [`movies_join_ratings`.`user_id`, `movies_join_ratings`.`movie_title`, movies_join_ratings.rating_score, 4, \"Pavee Lackeen: The Traveller Girl\"]
}}"""  # noqa: E501

import logging
import random
import time
import itertools
#from prompt_utils import *
#from db_utils import * 
from typing import Dict, List, Optional, Union, Any

@func_set_timeout(15)
def val_execute_sql(db_path: str, sql: str, fetch: Union[str, int] = "all") -> Any:
    """
    Executes an SQL query on a database and fetches results.
    
    Args:
        db_path (str): The path to the database file.
        sql (str): The SQL query to execute.
        fetch (Union[str, int]): How to fetch the results. Options are "all", "one", "random", or an integer.
        
    Returns:
        Any: The fetched results based on the fetch argument.
    
    Raises:
        Exception: If an error occurs during SQL execution.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            if fetch == "all":
                return cursor.fetchall()
            elif fetch == "one":
                return cursor.fetchone()
            elif fetch == "random":
                samples = cursor.fetchmany(10)
                return random.choice(samples) if samples else []
            elif isinstance(fetch, int):
                return cursor.fetchmany(fetch)
            else:
                raise ValueError("Invalid fetch argument. Must be 'all', 'one', 'random', or an integer.")
    except Exception as e:
        logging.error(f"Error in execute_sql: {e}\nSQL: {sql}")
        raise e
    except FunctionTimedOut as fto:
        logging.error(f"Function timed-out in execute_sql: {fto}\nSQL: {sql}")
        raise e
    
def validate_sql_query(db_path: str, sql: str, max_returned_rows: int = 30) -> Dict[str, Union[str, Any]]:
    """
    Validates an SQL query by executing it and returning the result.
    
    Args:
        db_path (str): The path to the database file.
        sql (str): The SQL query to validate.
        max_returned_rows (int): The maximum number of rows to return.
        
    Returns:
        dict: A dictionary with the SQL query, result, and status.
    """
    try:
        result = val_execute_sql(db_path, sql, fetch=max_returned_rows)
        if len(result) != 0:
            return {"SQL": sql, "RESULT": result, "STATUS": "NON EMPTY RESULT"}
        else:
            return {"SQL": sql, "RESULT": result, "STATUS": "EMPTY RESULT"}
    except Exception as e:
        logging.error(f"Error in validate_sql_query: {e}")
        return {"SQL": sql, "RESULT": str(e), "STATUS": "ERROR"}
    except FunctionTimedOut as e:
        logging.error(f"Function timed-out in execute_sql: {e}")
        return {"SQL": sql, "RESULT": str(e), "STATUS": "ERROR"}

@func_set_timeout(15)
def execute_sql(cursor, sql):
    cursor.execute(sql)
    sql_res = cursor.fetchall()

    return sql_res

def list_tables_and_views(sqlite_path):
    """
    Returns a sorted list of all user-defined tables and views in a SQLite database.
    """
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type IN ('table', 'view')
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
    """)

    results = [row[0] for row in cursor.fetchall()]

    conn.close()
    return results

def get_column_count(conn, table_or_view_name):
    """Return the number of columns in a SQLite table or view."""
    cur = conn.cursor()
    # Using double quotes to handle table names with spaces or special chars
    cur.execute(f'PRAGMA table_info("{table_or_view_name}");')
    return len(cur.fetchall())

def check_auto_views_have_matching_columns(sqlite_path, selected_views, prefix, check_from_clause=False):
    conn = sqlite3.connect(sqlite_path)
    mismatches = []

    for view_name in selected_views:
        if not check_from_clause and not view_name.startswith(prefix):
            continue

        base_tables = []
        if check_from_clause:
            try:
                res = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", 
                    (view_name,)
                ).fetchone()
                
                if res and res[0]:
                    sql_def = res[0]
                    # Find all table names following FROM or JOIN
                    # This regex looks for patterns like 'FROM table' or 'JOIN table'
                    # It accounts for optional quotes and schema prefixes
                    matches = re.findall(r'(?:FROM|JOIN)\s+["\']?(\w+)["\']?', sql_def, re.IGNORECASE)
                    if matches:
                        # Use a list to keep all occurrences if you expect duplicate columns 
                        # from the same table being joined, or set() if unique tables.
                        # Based on your prompt, we want all tables involved.
                        base_tables = matches
            except Exception as e:
                mismatches.append((view_name, "N/A", f"sql_lookup_error: {str(e)}"))
                continue
        else:
            base_tables = [view_name.replace(prefix, "", 1)]

        if not base_tables:
            mismatches.append((view_name, "N/A", "could_not_determine_base_tables"))
            continue

        try:
            # 1. Get the actual column count of the view
            view_cols = get_column_count(conn, view_name)
            
            # 2. Get the sum of column counts for all inferred base tables
            total_base_cols = 0
            for table in base_tables:
                total_base_cols += get_column_count(conn, table)
            
            # 3. Mismatch check
            if view_cols != total_base_cols:
                mismatches.append({
                    "view": view_name,
                    "tables_found": base_tables,
                    "view_count": view_cols,
                    "expected_sum": total_base_cols
                })

        except Exception as e:
            mismatches.append((view_name, str(base_tables), f"error: {str(e)}"))

    conn.close()
    return mismatches

# ============================================================
# Base table / view lists (CLI-controlled, per-dataset)
# ============================================================

# ----- SPIDER -----
spider_org_tables = ['conductor', 'orchestra', 'performance', 'show', 'airlines', 'airports', 'flights', 'Highschooler', 'Friend', 'Likes', 'players', 'matches', 'rankings', 'battle', 'ship', 'death', 'TV_Channel', 'TV_series', 'Cartoon', 'city', 'country', 'countrylanguage', 'course', 'teacher', 'course_arrange', 'Ref_Feature_Types', 'Ref_Property_Types', 'Other_Available_Features', 'Properties', 'Other_Property_Features', 'Ref_Template_Types', 'Templates', 'Documents', 'Paragraphs', 'continents', 'countries', 'car_makers', 'model_list', 'car_names', 'cars_data', 'poker_player', 'people', 'Addresses', 'Courses', 'Departments', 'Degree_Programs', 'Sections', 'Semesters', 'Students', 'Student_Enrolment', 'Student_Enrolment_Courses', 'Transcripts', 'Transcript_Contents', 'Breeds', 'Charges', 'Sizes', 'Treatment_Types', 'Owners', 'Dogs', 'Professionals', 'Treatments', 'Student', 'Has_Pet', 'Pets', 'employee', 'shop', 'hiring', 'evaluation', 'AREA_CODE_STATE', 'CONTESTANTS', 'stadium', 'singer', 'concert', 'singer_in_concert', 'museum', 'visitor', 'visit', 'VOTES']
spider_renamed_tables = ['conductors', 'orchestras', 'performances', 'shows', 'airline_companies', 'airport_locations', 'flight_schedules', 'highschoolers', 'friends', 'student_likes', 'tennis_players', 'tennis_matches', 'tennis_rankings', 'battles', 'ships', 'deaths', 'tv_channels', 'tv_series_episodes', 'cartoons', 'cities', 'countries_info', 'country_languages', 'courses_info', 'teachers', 'course_arrangements', 'feature_types', 'property_types', 'available_features', 'property_listings', 'property_features', 'template_types', 'document_templates', 'managed_documents', 'document_paragraphs', 'continent_info', 'car_countries', 'car_manufacturers', 'car_models', 'car_make_names', 'car_data', 'poker_players', 'people_info', 'student_addresses', 'university_courses', 'university_departments', 'degree_programs_info', 'course_sections', 'academic_semesters', 'university_students', 'student_enrollments', 'student_enrolled_courses', 'student_transcripts', 'transcript_contents_info', 'dog_breeds', 'vet_charges', 'dog_sizes', 'vet_treatment_types', 'dog_owners', 'vet_dogs', 'vet_professionals', 'vet_treatments', 'pet_students', 'student_has_pet', 'student_pets', 'shop_employees', 'retail_shops', 'shop_hiring', 'employee_evaluations', 'state_area_codes', 'voting_contestants', 'contestant_votes', 'stadiums', 'singers', 'concerts', 'concert_singers', 'museums', 'museum_visitors', 'museum_visits']
spider_org_views = ['cluster1_CARS_DATA_join_CAR_NAMES', 'cluster2_concert_join_stadium', 'cluster3_Documents_join_Templates', 'cluster4_Dogs_join_Treatments', 'cluster5_Professionals_join_Treatments', 'cluster6_Dogs_join_Owners', 'cluster7_AIRLINES_join_FLIGHTS', 'cluster8_AIRPORTS_join_FLIGHTS', 'cluster9_Friend_join_Highschooler', 'cluster10_Highschooler_join_Likes', 'cluster11_has_pet_join_student', 'cluster12_has_pet_join_pets_join_student', 'cluster13_people_join_poker_player', 'cluster14_TV_Channel_join_Cartoon', 'cluster15_country_join_countrylanguage', 'cluster16_death', 'cluster17_death_join_ship', 'cluster18_battle', 'cluster19_CAR_MAKERS_join_COUNTRIES', 'cluster20_continents', 'cluster21_CAR_MAKERS_join_MODEL_LIST', 'cluster22_singer', 'cluster23_concert_join_singer_in_concert', 'cluster24_teacher', 'cluster25_course_arrange_join_teacher', 'cluster26_course_join_course_arrange_join_teacher', 'cluster27_Documents_join_Paragraphs', 'cluster28_Ref_Template_Types', 'cluster29_Treatment_Types_join_Treatments_join_Professionals', 'cluster30_Breeds_join_Dogs', 'cluster31_Charges', 'cluster32_employee_join_evaluation', 'cluster33_hiring_join_shop', 'cluster34_visit_join_visitor', 'cluster35_museum', 'cluster36_orchestra', 'cluster37_show', 'cluster38_conductor_join_orchestra', 'cluster39_orchestra_join_performance', 'cluster40_Other_Available_Features_join_Ref_Feature_Types', 'cluster41_Properties_join_Ref_Property_Types', 'cluster42_Addresses', 'cluster43_Semesters_join_Student_Enrolment', 'cluster44_Courses_join_Sections', 'cluster45_Students', 'cluster46_Degree_Programs', 'cluster47_Transcript_Contents_join_Transcripts', 'cluster48_Courses_join_Student_Enrolment_Courses', 'cluster49_Degree_Programs_join_Departments', 'cluster50_Degree_Programs_join_Student_Enrolment_join_Students', 'cluster51_TV_series', 'cluster52_CONTESTANTS_join_VOTES', 'cluster53_AREA_CODE_STATE', 'cluster54_city_join_country_join_countrylanguage', 'cluster55_players', 'cluster56_matches', 'cluster57_rankings']
spider_org_views_50 = ['cluster1_CARS_DATA_join_CAR_NAMES', 'cluster2_concert_join_stadium', 'cluster3_Documents_join_Templates', 'cluster5_Professionals_join_Treatments', 'cluster6_Dogs_join_Owners', 'cluster7_AIRLINES_join_FLIGHTS', 'cluster8_AIRPORTS_join_FLIGHTS', 'cluster9_Friend_join_Highschooler', 'cluster11_has_pet_join_student', 'cluster13_people_join_poker_player', 'cluster14_TV_Channel_join_Cartoon', 'cluster15_country_join_countrylanguage', 'cluster19_CAR_MAKERS_join_COUNTRIES', 'cluster21_CAR_MAKERS_join_MODEL_LIST', 'cluster26_course_join_course_arrange_join_teacher', 'cluster29_Treatment_Types_join_Treatments_join_Professionals', 'cluster30_Breeds_join_Dogs', 'cluster32_employee_join_evaluation', 'cluster33_hiring_join_shop', 'cluster34_visit_join_visitor', 'cluster38_conductor_join_orchestra', 'cluster39_orchestra_join_performance', 'cluster40_Other_Available_Features_join_Ref_Feature_Types', 'cluster41_Properties_join_Ref_Property_Types', 'cluster43_Semesters_join_Student_Enrolment', 'cluster44_Courses_join_Sections', 'cluster49_Degree_Programs_join_Departments', 'cluster52_CONTESTANTS_join_VOTES', 'CONTINENTS_join_COUNTRIES', 'Student_Enrolment_join_Students', 'battle_join_ship_join_death']
spider_renamed_views = ['cluster1_car_data_join_car_make_names', 'cluster2_car_countries_join_car_manufacturers', 'cluster3_car_manufacturers_join_car_models', 'cluster4_concerts_join_stadiums', 'cluster5_document_templates_join_managed_documents', 'cluster6_vet_dogs_join_vet_treatments', 'cluster7_vet_professionals_join_vet_treatments', 'cluster8_dog_owners_join_vet_dogs', 'cluster9_airline_companies_join_flight_schedules', 'cluster10_airport_locations_join_flight_schedules', 'cluster11_friends_join_highschoolers', 'cluster12_highschoolers_join_student_likes', 'cluster13_pet_students_join_student_has_pet', 'cluster14_pet_students_join_student_has_pet_join_student_pets', 'cluster15_people_info_join_poker_players', 'cluster16_cartoons_join_tv_channels', 'cluster17_countries_info_join_country_languages', 'cluster18_deaths', 'cluster19_deaths_join_ships', 'cluster20_battles', 'cluster21_continent_info', 'cluster22_singers', 'cluster23_concert_singers_join_concerts', 'cluster24_teachers', 'cluster25_course_arrangements_join_teachers', 'cluster26_course_arrangements_join_courses_info_join_teachers', 'cluster27_document_paragraphs_join_managed_documents', 'cluster28_template_types', 'cluster29_vet_professionals_join_vet_treatment_types_join_vet_treatments', 'cluster30_dog_breeds_join_vet_dogs', 'cluster31_vet_charges', 'cluster32_employee_evaluations_join_shop_employees', 'cluster33_retail_shops_join_shop_hiring', 'cluster34_museum_visitors_join_museum_visits', 'cluster35_museums', 'cluster36_orchestras', 'cluster37_shows', 'cluster38_conductors_join_orchestras', 'cluster39_orchestras_join_performances', 'cluster40_available_features_join_feature_types', 'cluster41_property_listings_join_property_types', 'cluster42_student_addresses', 'cluster43_academic_semesters_join_student_enrollments', 'cluster44_course_sections_join_university_courses', 'cluster45_university_students', 'cluster46_degree_programs_info', 'cluster47_student_transcripts_join_transcript_contents_info', 'cluster48_student_enrolled_courses_join_university_courses', 'cluster49_degree_programs_info_join_university_departments', 'cluster50_degree_programs_info_join_student_enrollments_join_university_students', 'cluster51_tv_series_episodes', 'cluster52_contestant_votes_join_voting_contestants', 'cluster53_state_area_codes', 'cluster54_cities_join_countries_info_join_country_languages', 'cluster55_tennis_players', 'cluster56_tennis_matches', 'cluster57_tennis_rankings']
spider_renamed_tables_0 = ['music_festival_conductor', 'music_symphony_orchestra', 'music_live_performance', 'music_tour_show', 'aviation_airlines', 'aviation_airports', 'aviation_flights', 'edu_highschooler_details', 'edu_student_friendships', 'edu_student_crushes', 'wta_tennis_athletes', 'wta_tournament_matches', 'wta_player_standings', 'naval_historical_battle', 'naval_fleet_ship', 'naval_battle_casualties', 'broadcast_tv_channel', 'broadcast_tv_series', 'broadcast_cartoon_shows', 'global_city_demographics', 'global_country_profiles', 'global_spoken_languages', 'academy_course_catalog', 'academy_teaching_staff', 'academy_course_schedule', 'realty_feature_categories', 'realty_property_categories', 'realty_available_amenities', 'realty_housing_properties', 'realty_property_amenities', 'docsys_template_types', 'docsys_standard_templates', 'docsys_generated_documents', 'docsys_document_paragraphs', 'automotive_continents', 'automotive_origin_countries', 'automotive_manufacturers', 'automotive_model_list', 'automotive_make_names', 'automotive_technical_data', 'casino_poker_player_stats', 'casino_poker_people', 'univ_student_addresses', 'univ_offered_courses', 'univ_academic_departments', 'univ_degree_programs', 'univ_course_sections', 'univ_academic_semesters', 'univ_enrolled_students', 'univ_student_enrollments', 'univ_enrollment_courses', 'univ_official_transcripts', 'univ_transcript_contents', 'animal_clinic_breeds', 'animal_clinic_service_fees', 'animal_clinic_sizes', 'animal_clinic_procedure_types', 'animal_clinic_pet_owners', 'animal_clinic_canine_patients', 'animal_clinic_personnel', 'animal_clinic_administered_treatments', 'dorm_student_owners', 'dorm_student_pet_ownership', 'dorm_pet_animals', 'retail_store_employees', 'retail_store_branches', 'retail_store_hiring_records', 'retail_employee_evaluations', 'talent_show_area_codes', 'talent_show_contestants', 'live_music_stadium', 'live_music_singer', 'live_music_concert', 'live_music_concert_lineup', 'culture_museum_info', 'culture_museum_visitor', 'culture_museum_visit_logs', 'talent_show_votes']
spider_renamed_tables_50 = ['music_conductor', 'music_orchestra', 'music_performance', 'music_show', 'flight_airline', 'flight_airport', 'airline_flight', 'high_schooler', 'high_school_friend', 'high_school_like', 'tennis_player', 'tennis_match', 'tennis_ranking', 'naval_battle', 'naval_ship', 'naval_death', 'tv_broadcasting_channel', 'tv_episodic_series', 'tv_cartoon', 'world_city', 'world_country', 'world_country_language', 'school_course', 'school_teacher', 'school_course_arrangement', 'property_feature_type', 'real_estate_type', 'property_available_feature', 'real_estate_property', 'property_specific_feature', 'document_template_type', 'document_template', 'managed_document', 'document_paragraph', 'car_continent', 'car_country', 'car_maker', 'car_model', 'car_name', 'automotive_data_specs', 'poker_player_record', 'poker_person', 'university_address', 'university_course', 'university_department', 'university_degree_program', 'university_section', 'university_semester', 'university_student', 'university_enrollment', 'university_enrolled_course', 'university_transcript', 'university_transcript_content', 'dog_breed', 'vet_charge', 'dog_size', 'vet_treatment_type', 'dog_owner', 'vet_dog', 'vet_professional', 'vet_treatment', 'pet_student', 'student_pet_link', 'student_pet', 'retail_employee', 'retail_shop', 'retail_hiring', 'retail_evaluation', 'state_area_code', 'voting_contestant', 'contestant_vote', 'concert_stadium', 'concert_singer', 'music_concert', 'concert_singer_link', 'museum_entity', 'museum_visitor', 'museum_visit']
spider_renamed_views_50 = ['world_country_join_world_country_language', 'automotive_data_specs_join_car_name', 'vet_professional_join_vet_treatment', 'airline_flight_join_flight_airport', 'concert_stadium_join_music_concert', 'high_school_friend_join_high_schooler', 'music_conductor_join_music_orchestra', 'tv_broadcasting_channel_join_tv_cartoon', 'airline_flight_join_flight_airline', 'car_continent_join_car_country', 'contestant_vote_join_voting_contestant', 'document_template_join_managed_document', 'university_enrollment_join_university_semester', 'dog_owner_join_vet_dog', 'retail_employee_join_retail_evaluation', 'car_country_join_car_maker', 'car_maker_join_car_model', 'vet_professional_join_vet_treatment_join_vet_treatment_type', 'music_orchestra_join_music_performance', 'poker_person_join_poker_player_record', 'pet_student_join_student_pet_link', 'school_course_join_school_course_arrangement_join_school_teacher', 'real_estate_property_join_real_estate_type', 'museum_visit_join_museum_visitor', 'property_available_feature_join_property_feature_type', 'university_course_join_university_section', 'retail_hiring_join_retail_shop', 'university_enrollment_join_university_student', 'university_degree_program_join_university_department', 'naval_battle_join_naval_ship_join_naval_death', 'dog_breed_join_vet_dog']

spider_db_dict = {'battle_death': ['battle', 'ship', 'death'],
 'car_1': ['continents',
  'countries',
  'car_makers',
  'model_list',
  'car_names',
  'cars_data'],
 'concert_singer': ['stadium', 'singer', 'concert', 'singer_in_concert'],
 'course_teach': ['course', 'teacher', 'course_arrange'],
 'cre_Doc_Template_Mgt': ['Ref_Template_Types',
  'Templates',
  'Documents',
  'Paragraphs'],
 'dog_kennels': ['Breeds',
  'Charges',
  'Sizes',
  'Treatment_Types',
  'Owners',
  'Dogs',
  'Professionals',
  'Treatments'],
 'employee_hire_evaluation': ['employee', 'shop', 'hiring', 'evaluation'],
 'flight_2': ['airlines', 'airports', 'flights'],
 'museum_visit': ['museum', 'visitor', 'visit'],
 'network_1': ['Highschooler', 'Friend', 'Likes'],
 'orchestra': ['conductor', 'orchestra', 'performance', 'show'],
 'pets_1': ['Student', 'Has_Pet', 'Pets'],
 'poker_player': ['poker_player', 'people'],
 'real_estate_properties': ['Ref_Feature_Types',
  'Ref_Property_Types',
  'Other_Available_Features',
  'Properties',
  'Other_Property_Features'],
 'student_transcripts_tracking': ['Addresses',
  'Courses',
  'Departments',
  'Degree_Programs',
  'Sections',
  'Semesters',
  'Students',
  'Student_Enrolment',
  'Student_Enrolment_Courses',
  'Transcripts',
  'Transcript_Contents'],
 'tvshow': ['TV_Channel', 'TV_series', 'Cartoon'],
 'voter_1': ['AREA_CODE_STATE', 'CONTESTANTS', 'VOTES'],
 'world_1': ['city', 'country', 'countrylanguage'],
 'wta_1': ['players', 'matches', 'rankings']}

# ----- BIRD -----
bird_org_tables = ['Country', 'Examination', 'Laboratory', 'League', 'Match', 'Patient', 'Player', 'Player_Attributes', 'Team', 'Team_Attributes', 'account', 'alignment', 'atom', 'attendance', 'attribute', 'badges', 'bond', 'budget', 'card', 'cards', 'circuits', 'client', 'colour', 'comments', 'connected', 'constructorResults', 'constructorStandings', 'constructors', 'customers', 'disp', 'district', 'driverStandings', 'drivers', 'event', 'expense', 'foreign_data', 'frpm', 'gasstations', 'gender', 'hero_attribute', 'hero_power', 'income', 'lapTimes', 'legalities', 'loan', 'major', 'member', 'molecule', 'order', 'pitStops', 'postHistory', 'postLinks', 'posts', 'products', 'publisher', 'qualifying', 'race', 'races', 'results', 'rulings', 'satscores', 'schools', 'seasons', 'set_translations', 'sets', 'status', 'superhero', 'superpower', 'tags', 'trans', 'transactions_1k', 'users', 'votes', 'yearmonth', 'zip_code']
bird_renamed_tables = ['Bank_Accounts', 'Bank_Cards', 'Bank_Clients', 'Bank_Dispositions', 'Bank_Districts', 'Bank_Loans', 'Bank_Orders', 'Bank_Transactions', 'Chem_Atoms', 'Chem_Bonds', 'Chem_Links', 'Chem_Molecules', 'Club_Attendance', 'Club_Budgets', 'Club_Events', 'Club_Expenses', 'Club_Income', 'Club_Majors', 'Club_Members', 'Club_Zips', 'Education_Lunch_Aid', 'Education_SAT_Stats', 'Education_Schools', 'Energy_Customers', 'Energy_Products', 'Energy_Sales', 'Energy_Stations', 'Energy_Usage', 'F1_Constructor_Results', 'F1_Constructor_Standings', 'F1_Constructors', 'F1_Driver_Standings', 'F1_Drivers', 'F1_Lap_Times', 'F1_Pit_Stops', 'F1_Qualifying', 'F1_Races', 'F1_Results', 'F1_Seasons', 'F1_Status_Codes', 'F1_Tracks', 'Forum_Badges', 'Forum_Comments', 'Forum_History', 'Forum_Links', 'Forum_Posts', 'Forum_Tags', 'Forum_Users', 'Forum_Votes', 'Hero_Alignments', 'Hero_Attribute_Types', 'Hero_Attributes', 'Hero_Colors', 'Hero_Genders', 'Hero_Power_Map', 'Hero_Profiles', 'Hero_Publishers', 'Hero_Races', 'Hero_Superpowers', 'MTG_Card_Foreign_Data', 'MTG_Cards', 'MTG_Legality', 'MTG_Rulings', 'MTG_Set_Translations', 'MTG_Sets', 'Medical_Exams', 'Medical_Lab_Results', 'Medical_Patients', 'Soccer_Countries', 'Soccer_Leagues', 'Soccer_Matches', 'Soccer_Player_Stats', 'Soccer_Players', 'Soccer_Team_Stats', 'Soccer_Teams']
bird_org_views = ['cluster10_atom_join_bond_join_molecule', 'cluster11_cards_join_legalities', 'cluster12_cards_join_rulings', 'cluster13_cards_join_set_translations', 'cluster14_cards_join_foreign_data', 'cluster15_set_translations_join_sets', 'cluster16_cards_join_sets', 'cluster17_posts_join_users', 'cluster18_badges_join_users', 'cluster19_comments_join_posts', 'cluster1_frpm_join_schools', 'cluster20_posthistory_join_posts_join_users', 'cluster21_hero_power_join_superhero_join_superpower', 'cluster22_publisher_join_superhero', 'cluster23_colour_join_superhero', 'cluster24_race_join_superhero', 'cluster25_circuits_join_races', 'cluster26_drivers_join_qualifying', 'cluster27_races_join_results', 'cluster28_drivers_join_results', 'cluster29_driverstandings_join_drivers_join_races', 'cluster2_satscores_join_schools', 'cluster30_drivers_join_races_join_results', 'cluster31_league_join_match', 'cluster32_player_join_player_attributes', 'cluster33_team_join_team_attributes', 'cluster34_laboratory_join_patient', 'cluster35_examination_join_patient', 'cluster36_examination_join_laboratory_join_patient', 'cluster37_examination_join_laboratory', 'cluster38_major_join_member', 'cluster39_budget_join_event', 'cluster3_account_join_district', 'cluster40_member_join_zip_code', 'cluster41_expense_join_member', 'cluster42_customers_join_yearmonth', 'cluster43_gasstations_join_transactions_1k', 'cluster44_account_join_district_join_loan', 'cluster45_account_join_trans', 'cluster46_card_join_client_join_disp', 'cluster47_account_join_client_join_order', 'cluster48_posts_join_tags', 'cluster49_votes', 'cluster4_client_join_district', 'cluster50_postlinks_join_posts', 'cluster51_attribute_join_hero_attribute_join_publisher_join_superhero', 'cluster52_attribute_join_gender_join_hero_attribute_join_superhero', 'cluster53_alignment_join_superhero', 'cluster54_constructorstandings_join_constructors', 'cluster55_races_join_seasons', 'cluster56_drivers_join_laptimes', 'cluster57_races_join_results_join_status', 'cluster58_drivers_join_pitstops_join_races', 'cluster59_circuits_join_races_join_pitstops_join_results', 'cluster5_atom_join_bond', 'cluster60_country_join_league', 'cluster61_country_join_match_join_player', 'cluster62_attendance_join_event_join_member', 'cluster63_income_join_member', 'cluster64_customers_join_transactions_1k_join_products', 'cluster6_bond_join_molecule', 'cluster7_atom_join_connected', 'cluster8_atom_join_molecule', 'cluster9_bond_join_connected']
bird_org_views_50 = ["Laboratory_join_Patient", "major_join_member", "atom_join_molecule", "set_translations_join_sets", "cards_join_foreign_data", "posts_join_users", "Team_join_Team_Attributes", "account_join_district", "circuits_join_races", "frpm_join_schools", "Player_join_Player_Attributes", "budget_join_event", "satscores_join_schools", "badges_join_users", "publisher_join_superhero", "comments_join_posts", "expense_join_member", "Country_join_League", "account_join_disp", "League_join_Match", "drivers_join_lapTimes", "colour_join_superhero", "circuits_join_pitStops_join_races_join_results", "postHistory_join_posts_join_users", "postHistory_join_posts_join_users_join_votes", "Examination_join_Patient", "card_join_disp", "constructorStandings_join_constructors", "race_join_superhero", "races_join_seasons", "gasstations_join_products_join_transactions_1k", "client_join_district", "cards_join_legalities", "bond_join_connected", "account_join_client_join_loan", "account_join_client_join_disp_join_trans", "gender_join_superhero", "attendance_join_event", "hero_power_join_superhero_join_superpower", "customers_join_yearmonth", "drivers_join_qualifying", "income_view", "major_join_member_join_zip_code", "attendance_join_event_join_income_join_member", "tags_view", "account_join_order", "hero_attribute_view", "attribute_join_hero_attribute_join_publisher_join_superhero", "cards_join_legalities_join_rulings", "alignment_join_publisher_join_superhero", "Country_join_Match_join_Player"]
bird_renamed_views = ['workload_updated_cluster10_Chem_Atoms_join_Chem_Bonds_join_Chem_Molecules', 'workload_updated_cluster11_MTG_Cards_join_MTG_Legality', 'workload_updated_cluster12_MTG_Cards_join_MTG_Rulings', 'workload_updated_cluster13_MTG_Cards_join_MTG_Set_Translations', 'workload_updated_cluster14_MTG_Card_Foreign_Data_join_MTG_Cards', 'workload_updated_cluster15_MTG_Set_Translations_join_MTG_Sets', 'workload_updated_cluster16_MTG_Cards_join_MTG_Sets', 'workload_updated_cluster17_Forum_Posts_join_Forum_Users', 'workload_updated_cluster18_Forum_Badges_join_Forum_Users', 'workload_updated_cluster19_Forum_Comments_join_Forum_Posts', 'workload_updated_cluster1_Education_Lunch_Aid_join_Education_Schools', 'workload_updated_cluster20_Forum_History_join_Forum_Posts_join_Forum_Users', 'workload_updated_cluster21_Hero_Power_Map_join_Hero_Profiles_join_Hero_Superpowers', 'workload_updated_cluster22_Hero_Profiles_join_Hero_Publishers', 'workload_updated_cluster23_Hero_Colors_join_Hero_Profiles', 'workload_updated_cluster24_Hero_Profiles_join_Hero_Races', 'workload_updated_cluster25_F1_Races_join_F1_Tracks', 'workload_updated_cluster26_F1_Drivers_join_F1_Qualifying', 'workload_updated_cluster27_F1_Races_join_F1_Results', 'workload_updated_cluster28_F1_Drivers_join_F1_Results', 'workload_updated_cluster29_F1_Driver_Standings_join_F1_Drivers_join_F1_Races', 'workload_updated_cluster2_Education_SAT_Stats_join_Education_Schools', 'workload_updated_cluster30_F1_Drivers_join_F1_Races_join_F1_Results', 'workload_updated_cluster31_Soccer_Leagues_join_Soccer_Matches', 'workload_updated_cluster32_Soccer_Player_Stats_join_Soccer_Players', 'workload_updated_cluster33_Soccer_Team_Stats_join_Soccer_Teams', 'workload_updated_cluster34_Medical_Lab_Results_join_Medical_Patients', 'workload_updated_cluster35_Medical_Exams_join_Medical_Patients', 'workload_updated_cluster36_Medical_Exams_join_Medical_Lab_Results_join_Medical_Patients', 'workload_updated_cluster37_Medical_Exams_join_Medical_Lab_Results', 'workload_updated_cluster38_Club_Majors_join_Club_Members', 'workload_updated_cluster39_Club_Budgets_join_Club_Events', 'workload_updated_cluster3_Bank_Accounts_join_Bank_Districts', 'workload_updated_cluster40_Club_Members_join_Club_Zips', 'workload_updated_cluster41_Club_Expenses_join_Club_Members', 'workload_updated_cluster42_Energy_Customers_join_Energy_Usage', 'workload_updated_cluster43_Energy_Sales_join_Energy_Stations', 'workload_updated_cluster44_Bank_Accounts_join_Bank_Districts_join_Bank_Loans', 'workload_updated_cluster45_Bank_Accounts_join_Bank_Transactions', 'workload_updated_cluster46_Bank_Cards_join_Bank_Clients_join_Bank_Dispositions', 'workload_updated_cluster47_Bank_Accounts_join_Bank_Clients_join_Bank_Orders', 'workload_updated_cluster48_Forum_Posts_join_Forum_Tags', 'workload_updated_cluster49_Forum_Votes', 'workload_updated_cluster4_Bank_Clients_join_Bank_Districts', 'workload_updated_cluster50_Forum_Links_join_Forum_Posts', 'workload_updated_cluster51_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Profiles_join_Hero_Publishers', 'workload_updated_cluster52_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Genders_join_Hero_Profiles', 'workload_updated_cluster53_Hero_Alignments_join_Hero_Profiles', 'workload_updated_cluster54_F1_Constructor_Standings_join_F1_Constructors', 'workload_updated_cluster55_F1_Races_join_F1_Seasons', 'workload_updated_cluster56_F1_Drivers_join_F1_Lap_Times', 'workload_updated_cluster57_F1_Races_join_F1_Results_join_F1_Status_Codes', 'workload_updated_cluster58_F1_Drivers_join_F1_Pit_Stops_join_F1_Races', 'workload_updated_cluster59_F1_Pit_Stops_join_F1_Races_join_F1_Results_join_F1_Tracks', 'workload_updated_cluster5_Chem_Atoms_join_Chem_Bonds', 'workload_updated_cluster60_Soccer_Countries_join_Soccer_Leagues', 'workload_updated_cluster61_Soccer_Countries_join_Soccer_Matches_join_Soccer_Players', 'workload_updated_cluster62_Club_Attendance_join_Club_Events_join_Club_Members', 'workload_updated_cluster63_Club_Income_join_Club_Members', 'workload_updated_cluster64_Energy_Customers_join_Energy_Products_join_Energy_Sales', 'workload_updated_cluster6_Chem_Bonds_join_Chem_Molecules', 'workload_updated_cluster7_Chem_Atoms_join_Chem_Links', 'workload_updated_cluster8_Chem_Atoms_join_Chem_Molecules', 'workload_updated_cluster9_Chem_Bonds_join_Chem_Links']
bird_renamed_tables_0 = ['AcademicMajor', 'AccountDisposition', 'AccountTransaction', 'AthletePlayer', 'AtomConnectivity', 'BankAccount', 'BankClient', 'BankPaymentOrder', 'BiologicalGender', 'BiologicalRace', 'CaliforniaSchool', 'CardFormatLegality', 'CardOfficialRuling', 'CardSetCollection', 'CardTranslation', 'ChemicalBond', 'ChemicalMolecule', 'CommunityEvent', 'CreditLoan', 'DriverLapTiming', 'DriverSeasonStandings', 'EventAttendance', 'EventBudget', 'F1Driver', 'F1Season', 'ForumPost', 'ForumUser', 'FuelStation', 'FuelTransaction', 'GeographicCountry', 'GrandPrixRace', 'HeroAttributeValue', 'HeroMoralAlignment', 'HeroPowerAssignment', 'HeroPowerCapability', 'HeroTraitCategory', 'InventoryProduct', 'LabTestResults', 'LinkedPosts', 'MagicCard', 'MediaPublisher', 'MedicalExamination', 'MedicalPatient', 'MolecularAtom', 'MonthlyUtilityConsumption', 'OrganizationExpense', 'OrganizationIncome', 'OrganizationMember', 'PaymentCard', 'PitStopLog', 'PlayerSkillAttributes', 'PostComment', 'PostRevisionHistory', 'PostTagMetadata', 'PostVote', 'PostalLocation', 'QualifyingSession', 'RaceResultDetails', 'RaceStatusDescription', 'RaceTrackCircuit', 'RacingTeam', 'RegionalDemographics', 'RetailCustomer', 'SchoolPovertyFreeMeals', 'SchoolSATPerformance', 'SetTitleTranslation', 'SoccerMatch', 'SportsLeague', 'SportsTeam', 'SuperheroProfile', 'TeamPerformanceAttributes', 'TeamRaceResults', 'TeamSeasonStandings', 'UserBadge', 'VisualColor']
bird_renamed_tables_50 = ["NationalTerritory", "FootballCompetitionLeague", "FootballClub", "FootballAthlete", "AthletePhysicalStatistic", "ClubStrategyMetric", "FootballGameMatch", "HospitalPatientDetail", "MedicalExamRecord", "LabDiagnosticMetric", "FinancialAccountDetail", "BankClientProfile", "AccountLegalDisposition", "CreditCardDetail", "GeographicDistrictStatistic", "BankCreditLoan", "FinancialPaymentOrder", "FinancialAccountTransaction", "SuperheroIdentity", "CharacterAlignment", "SuperheroTrait", "SuperhumanAbility", "SuperheroAttributeScore", "SuperheroPowerMapping", "VisualAppearanceColor", "ContentSeriesPublisher", "HeroicSpecieType", "BiologicalSexCategory", "ToxicologyMolecule", "MolecularAtomPart", "MolecularBondType", "AtomConnectionLink", "ForumPlatformUser", "CommunityDiscussionPost", "DiscussionThreadComment", "UserRecognitionBadge", "DiscussionTopicTag", "UserReactionVote", "PostRevisionTimeline", "InternalPostReference", "StudentClubEvent", "StudentClubMember", "UniversityFieldOfStudy", "EventFundingPlan", "ClubTransactionExpense", "StudentClubIncome", "EventParticipationRecord", "LocationPostalDetail", "ProfessionalRaceDriver", "RacingConstructorTeam", "GrandPrixEvent", "RacingTrackVenue", "RaceFinishingPlacement", "DriverSeasonRank", "ConstructorSeasonRank", "TeamRacePerformance", "RaceQualifyingDetail", "RaceLapTiming", "RacePitStopLog", "ChampionshipSeason", "RaceStatusCondition", "EducationalInstitution", "SchoolMealProgramMetric", "StandardizedSATScore", "GameTradingCard", "CardReleaseSet", "CardLocalLanguageName", "CardInternationalTranslation", "CardLegalityRule", "CardGameplayRuling", "UtilityServiceCustomer", "FuelServiceStation", "FuelProductCategory", "EnergySaleTransaction", "EnergyMonthlyUsage"]
bird_renamed_views_50 = ["HospitalPatientDetail_join_LabDiagnosticMetric", "StudentClubMember_join_UniversityFieldOfStudy", "MolecularAtomPart_join_ToxicologyMolecule", "CardLocalLanguageName_join_CardReleaseSet", "CardInternationalTranslation_join_GameTradingCard", "CommunityDiscussionPost_join_ForumPlatformUser", "ClubStrategyMetric_join_FootballClub", "FinancialAccountDetail_join_GeographicDistrictStatistic", "GrandPrixEvent_join_RacingTrackVenue", "EducationalInstitution_join_SchoolMealProgramMetric", "AthletePhysicalStatistic_join_FootballAthlete", "EventFundingPlan_join_StudentClubEvent", "EducationalInstitution_join_StandardizedSATScore", "ForumPlatformUser_join_UserRecognitionBadge", "ContentSeriesPublisher_join_SuperheroIdentity", "CommunityDiscussionPost_join_DiscussionThreadComment", "ClubTransactionExpense_join_StudentClubMember", "FootballCompetitionLeague_join_NationalTerritory", "AccountLegalDisposition_join_FinancialAccountDetail", "FootballCompetitionLeague_join_FootballGameMatch", "ProfessionalRaceDriver_join_RaceLapTiming", "SuperheroIdentity_join_VisualAppearanceColor", "GrandPrixEvent_join_RaceFinishingPlacement_join_RacePitStopLog_join_RacingTrackVenue", "CommunityDiscussionPost_join_ForumPlatformUser_join_PostRevisionTimeline", "CommunityDiscussionPost_join_ForumPlatformUser_join_PostRevisionTimeline_join_UserReactionVote", "HospitalPatientDetail_join_MedicalExamRecord", "AccountLegalDisposition_join_CreditCardDetail", "ConstructorSeasonRank_join_RacingConstructorTeam", "HeroicSpecieType_join_SuperheroIdentity", "ChampionshipSeason_join_GrandPrixEvent", "EnergySaleTransaction_join_FuelProductCategory_join_FuelServiceStation", "BankClientProfile_join_GeographicDistrictStatistic", "CardLegalityRule_join_GameTradingCard", "AtomConnectionLink_join_MolecularBondType", "BankClientProfile_join_BankCreditLoan_join_FinancialAccountDetail", "AccountLegalDisposition_join_BankClientProfile_join_FinancialAccountDetail_join_FinancialAccountTransaction", "BiologicalSexCategory_join_SuperheroIdentity", "EventParticipationRecord_join_StudentClubEvent", "SuperheroIdentity_join_SuperheroPowerMapping_join_SuperhumanAbility", "EnergyMonthlyUsage_join_UtilityServiceCustomer", "ProfessionalRaceDriver_join_RaceQualifyingDetail", "StudentClubIncome_view", "LocationPostalDetail_join_StudentClubMember_join_UniversityFieldOfStudy", "EventParticipationRecord_join_StudentClubEvent_join_StudentClubIncome_join_StudentClubMember", "DiscussionTopicTag_view", "FinancialAccountDetail_join_FinancialPaymentOrder", "SuperheroAttributeScore_view", "ContentSeriesPublisher_join_SuperheroAttributeScore_join_SuperheroIdentity_join_SuperheroTrait", "CardGameplayRuling_join_CardLegalityRule_join_GameTradingCard", "CharacterAlignment_join_ContentSeriesPublisher_join_SuperheroIdentity", "FootballAthlete_join_FootballGameMatch_join_NationalTerritory"]

bird_db_dict = {'california_schools': ['frpm', 'satscores', 'schools'],
 'card_games': ['cards',
  'foreign_data',
  'legalities',
  'rulings',
  'sets',
  'set_translations'],
 'codebase_community': ['badges',
  'comments',
  'postHistory',
  'postLinks',
  'posts',
  'tags',
  'users',
  'votes'],
 'debit_card_specializing': ['customers',
  'gasstations',
  'products',
  'transactions_1k',
  'yearmonth'],
 'european_football_2': ['Country',
  'League',
  'Match',
  'Player',
  'Player_Attributes',
  'Team',
  'Team_Attributes'],
 'financial': ['account',
  'card',
  'client',
  'disp',
  'district',
  'loan',
  'order',
  'trans'],
 'formula_1': ['circuits',
  'constructorResults',
  'constructors',
  'constructorStandings',
  'drivers',
  'driverStandings',
  'lapTimes',
  'pitStops',
  'qualifying',
  'races',
  'results',
  'seasons',
  'status'],
 'student_club': ['attendance',
  'budget',
  'event',
  'expense',
  'income',
  'major',
  'member',
  'zip_code'],
 'superhero': ['alignment',
  'attribute',
  'colour',
  'gender',
  'hero_attribute',
  'hero_power',
  'publisher',
  'race',
  'superhero',
  'superpower'],
 'thrombosis_prediction': ['Examination', 'Laboratory', 'Patient'],
 'toxicology': ['atom', 'bond', 'connected', 'molecule']}


# Lookup dict used by --dataset
DATASET_TABLES = {
    "spider": {
        "org_tables": spider_org_tables,
        "renamed_tables": spider_renamed_tables,
        "org_views": spider_org_views,
        "renamed_views": spider_renamed_views,
        "db_dict": spider_db_dict,
    },
    "bird": {
        "org_tables": bird_org_tables,
        "renamed_tables": bird_renamed_tables,
        "org_views": bird_org_views,
        "renamed_views": bird_renamed_views,
        "db_dict": bird_db_dict,
    },
}

# ============================================================
# History → cluster construction
# ============================================================
def build_clusters_from_history(
    history_path: str,
    sql_col: str,
    gt_tables_col: str,
    sample_pct: int = 100,
    random_state: int = 42,
):
    """Load history sample CSV and build (sample, exact_clusters, question_cluster_map).

    sql_col: column to read SQLs from (used for join-path extraction).
    gt_tables_col: column listing the ground-truth tables for each row.
    sample_pct: integer 1..100; if <100, randomly sub-samples the history CSV
                before building clusters/embeddings. Index is reset after sampling
                so downstream positional/label lookups stay consistent.
    random_state: seed for reproducible sub-sampling.
    """
    sample = pd.read_csv(history_path)
    full_n = len(sample)

    if sample_pct < 100:
        sample = sample.sample(frac=sample_pct / 100.0, random_state=random_state).reset_index(drop=True)
        print(f"🎲 Sub-sampled history: kept {len(sample)}/{full_n} rows ({sample_pct}%, seed={random_state})")
        if len(sample) > 0:
            _first_q   = str(sample.iloc[0].get("question", "<no question col>"))
            _first_sql = str(sample.iloc[0].get(sql_col, f"<no {sql_col!r} col>"))
            print(f"    first question: {_first_q!r}")
            print(f"    first SQL ({sql_col}): {_first_sql!r}")
    else:
        print(f"🗂  Using full history: {full_n} rows")

    path_list = [simplify_sql(s) for s in sample[sql_col].tolist()]
    question_list = list(sample['question'])
    t_list = [ast.literal_eval(x) for x in list(sample[gt_tables_col])]

    exact_clusters = find_exact_query_patterns(t_list, path_list, min_frequency=5, min_tables=2)
    question_cluster_map = assign_queries_to_clusters(
        t_list, exact_clusters, question_list, path_list, min_tables=2
    )
    compute_subsets_inplace(exact_clusters, t_list, path_list)

    print(f"✅ Total clusters built from history: {len(exact_clusters)}")
    return sample, exact_clusters, question_cluster_map


# ============================================================
# CLI parsing
# ============================================================
def parse_args():
    p = argparse.ArgumentParser(description="Run NL2SQL pipeline (linking → SQL → revise)")
    p.add_argument("--dataset", choices=["spider", "bird"], default="spider",
                   help="Dataset to run on. Controls which table/view lists are used and "
                        "where logs are written (logs/ vs logs_bird/). Default: spider.")
    p.add_argument("--model", default="gpt-4.1-mini",
                   help="Model name for stages 2/3. Any string starting with 'gemini' uses "
                        "Google GenAI; anything else uses OpenAI. Default: gpt-4.1-mini.")
    p.add_argument("--csv_path", default=None,
                   help="Path to nl2sql CSV (input questions). If omitted, defaults to "
                        "../../csvs/nl2sql_{dataset}.csv (relative to this script).")
    p.add_argument("--db_path", default=None,
                   help="Path to the SQLite database file. If omitted, defaults to "
                        "../../databases/merged_{dataset}.sqlite (relative to this script).")
    p.add_argument("--history", action="store_true",
                   help="Enable history mode. When set with no --history_path, defaults to "
                        "../../csvs/sample_{dataset}.csv (relative to this script). "
                        "Passing --history_path implicitly enables history mode.")
    p.add_argument("--history_path", default=None,
                   help="Path to sample/history CSV. Implies --history when provided. "
                        "If --history is set without this flag, defaults to "
                        "../../csvs/sample_{dataset}.csv.")
    p.add_argument("--sample", type=int, default=100, metavar="N",
                   help="Integer 1..100; percent of the history CSV to use. <100 triggers a "
                        "reproducible random sub-sample (seed=42) before clusters/embeddings "
                        "are built. For --dataset bird, N<100 also auto-maps bird_renamed_tables_N / "
                        "bird_renamed_views_N / bird_org_views_N / name_mapping_bird_N.json when "
                        "--rename_v / --view_v / --mapping_path are not explicitly set. Default 100.")
    p.add_argument("--rename", action="store_true",
                   help="Use renamed_tables/renamed_views instead of org_tables/org_views. "
                        "Renamed base tables are stored as views in the sqlite db, so this also "
                        "switches base-schema generation to get_database_schema().")
    p.add_argument("--rename_v", default=None, metavar="VAR",
                   help="Name of a module-level Python variable (a list) whose contents "
                        "override the default renamed-tables list (e.g. --rename_v bird_renamed_tables_0). "
                        "Only used with --rename. If unset, falls back to the dataset's default "
                        "(spider_renamed_tables / bird_renamed_tables).")
    p.add_argument("--view", action="store_true",
                   help="Add matching views from the views pool (picked per question via "
                        "Stage-1 table → view-name parsing) to the schema.")
    p.add_argument("--view_v", default=None, metavar="VAR",
                   help="Name of a module-level Python variable (a list of view names) to use "
                        "as the views pool, overriding the dataset default and any auto-derived "
                        "pool from --rename_v. Requires --view.")
    p.add_argument("--view_adhoc", action="store_true",
                   help="Ad-hoc view creation (requires --view and --use_linking). "
                        "Reads linked tables from the --use_linking column (stage 0), asks the LLM "
                        "for a CREATE VIEW joining them on foreign keys, creates the view in the DB, "
                        "and injects the view's schema into all 3 stages (linking/gen/revision). "
                        "Stage 1 still runs. Suffix token '_uselinking' is replaced by '_adhoclinking'.")
    p.add_argument("--view_relink", action="store_true",
                   help="Re-link mode (requires --view and --use_linking). "
                        "Reads linked tables from --use_linking (stage 0), picks matching pre-defined "
                        "views from the views pool (same mechanism as plain --view), injects those "
                        "view schemas into stage 1 and runs stage 1 to produce a fresh linking, then "
                        "uses the same augmented schema for stages 2/3. If <2 linked tables, stage 1 "
                        "is skipped and the --use_linking value is used as-is. Mutually exclusive "
                        "with --view_adhoc. Suffix token '_uselinking' is replaced by '_relinking'.")
    p.add_argument("--cluster", action="store_true",
                   help="Inject the matching clusters' common join paths into the SQL gen / revise "
                        "prompts. When combined with --history_path, also restricts top-K history "
                        "retrieval to questions belonging to the matched clusters.")
    p.add_argument("--cluster_filter", action="store_true",
                   help="Restrict the stage-2/3 schema (and --view matched views / --view_adhoc "
                        "view reuse) to only the tables that belong to the matched clusters. "
                        "Stage 1 is unaffected. Requires --cluster. If no clusters match for a "
                        "question, falls back to the full schema for that question.")
    p.add_argument("--use_linking", default=None, metavar="COLUMN",
                   help="Column name in input CSV that already contains schema links. "
                        "When set, the linking LLM stage is skipped and this column is used directly.")
    p.add_argument(
        "--mapping_path", default=None,
        help="Path to the name-mapping JSON (e.g. name_mapping_spider.json or name_mapping_bird.json). "
             "Only used when --rename is set. Default: auto-selected per --dataset.",
    )
    p.add_argument("--per_db", action="store_true",
                   help="Per-db mode: restrict base schema, views pool, clusters, and history "
                        "retrieval to each question's db_id (read from the 'db_id' column). "
                        "Requires DATASET_TABLES[dataset]['db_dict'] to be populated. "
                        "Unknown db_ids fall back to the full union with a warning.")
    p.add_argument("--rows", default=None, metavar="SPEC",
                   help="Row selection. Either 'N' for the first N rows, or 'START:END' "
                        "for a python-style half-open slice (e.g. '100:150' = 50 rows starting at index 100). "
                        "Default: all rows.")
    return p.parse_args()


def apply_row_selection(df, spec):
    """Slice df according to --rows. Returns the sliced df with original indices preserved."""
    if spec is None:
        return df
    if ":" in spec:
        a, b = spec.split(":", 1)
        start = int(a) if a.strip() else 0
        end = int(b) if b.strip() else len(df)
        return df.iloc[start:end]
    return df.iloc[: int(spec)]


# ============================================================
# Main
# ============================================================
def main():
    args = parse_args()

    # Auto-resolve csv_path / db_path / history_path from --dataset when not explicitly provided.
    # This script is expected to run from <LDD_ROOT>/benchmarks/spider_data/, so the shared data
    # folders (databases/, mapping_files/, csvs/) sit two levels up.
    _this_dir = os.path.dirname(os.path.abspath(__file__))                   # .../benchmarks/spider_data/
    _ldd_root = os.path.abspath(os.path.join(_this_dir, "..", ".."))         # .../Logical-Database-Design/
    if args.csv_path is None:
        args.csv_path = os.path.join(_ldd_root, "csvs", f"nl2sql_{args.dataset}.csv")
        print(f"[run_spider] --csv_path auto-resolved to {args.csv_path}")
    if args.db_path is None:
        args.db_path = os.path.join(_ldd_root, "databases", f"merged_{args.dataset}.sqlite")
        print(f"[run_spider] --db_path auto-resolved to {args.db_path}")

    # History gating: --history_path implies --history; --history alone uses the default file;
    # neither flag → history mode disabled.
    if args.history_path:
        args.history = True
    elif args.history:
        args.history_path = os.path.join(_ldd_root, "csvs", f"sample_{args.dataset}.csv")
        if not os.path.exists(args.history_path):
            raise SystemExit(
                f"--history requested but default sample file not found at {args.history_path}. "
                f"Pass --history_path explicitly or drop --history."
            )
        print(f"[run_spider] --history_path auto-resolved to {args.history_path}")
    else:
        args.history_path = None

    for _label, _path in (("--csv_path", args.csv_path), ("--db_path", args.db_path)):
        if not os.path.exists(_path):
            raise SystemExit(f"{_label} not found at {_path}. Pass {_label} explicitly.")
    db_path = args.db_path

    # ----- validate flag combos -----
    if args.cluster and not args.history_path:
        raise SystemExit("--cluster requires --history_path (clusters are built from the sample CSV).")
    if args.cluster_filter and not args.cluster:
        raise SystemExit("--cluster_filter requires --cluster.")
    if not (1 <= args.sample <= 100):
        raise SystemExit(f"--sample must be between 1 and 100, got {args.sample}")
    if args.sample != 100 and not args.history_path:
        raise SystemExit("--sample <100 requires --history_path (sampling applies to the history CSV).")
    if args.view_adhoc:
        if not args.view:
            raise SystemExit("--view_adhoc requires --view.")
        if not args.use_linking:
            raise SystemExit("--view_adhoc requires --use_linking.")
    if args.view_relink:
        if not args.view:
            raise SystemExit("--view_relink requires --view.")
        if not args.use_linking:
            raise SystemExit("--view_relink requires --use_linking.")
        if args.view_adhoc:
            raise SystemExit("--view_relink and --view_adhoc are mutually exclusive.")
    if args.rename_v and not args.rename:
        raise SystemExit("--rename_v requires --rename.")
    if args.view_v and not args.view:
        raise SystemExit("--view_v requires --view.")

    # ----- --sample N: auto-map _N variants for bird/spider when not explicitly overridden -----
    # Only triggers when N<100. Sets args.rename_v / args.view_v as shortcuts, letting the
    # downstream rename_v/view_v logic handle mapping_path + pool derivation uniformly.
    # Explicit --rename_v/--view_v/--mapping_path always win.
    if args.sample != 100 and args.dataset in ("bird", "spider"):
        _s = str(args.sample)
        _rt  = f"{args.dataset}_renamed_tables_{_s}"
        _rv  = f"{args.dataset}_renamed_views_{_s}"
        _ov  = f"{args.dataset}_org_views_{_s}"
        _map = f"name_mapping_{args.dataset}_{_s}.json"
        _script_dir = os.path.dirname(os.path.abspath(__file__))             # .../benchmarks/spider_data/
        # Mapping files live at <LDD_ROOT>/mapping_files (two levels up from this script).
        _ldd_mapping_dir = os.path.abspath(os.path.join(_script_dir, "..", "..", "mapping_files"))

        # Validate required variables / files exist up-front.
        missing = []
        if globals().get(_rt) is None: missing.append(f"module variable {_rt!r}")
        if globals().get(_rv) is None: missing.append(f"module variable {_rv!r}")
        if globals().get(_ov) is None: missing.append(f"module variable {_ov!r}")
        if not (os.path.exists(os.path.join(_ldd_mapping_dir, _map))
                or os.path.exists(os.path.join(_script_dir, _map))):
            missing.append(f"mapping file {_map!r} (looked in {_ldd_mapping_dir} and {_script_dir})")
        if missing:
            raise SystemExit(
                f"--sample {args.sample} requires these to exist but they are missing: "
                + "; ".join(missing)
            )

        # Auto-set --rename_v (only meaningful with --rename).
        if args.rename and not args.rename_v:
            args.rename_v = _rt
            print(f"[--sample {args.sample}] auto-set --rename_v={_rt!r}")

        # Auto-set --view_v (only meaningful with --view). Rename state selects which pool.
        if args.view and not args.view_v:
            args.view_v = _rv if args.rename else _ov
            print(f"[--sample {args.sample}] auto-set --view_v={args.view_v!r}")
        # Note: mapping_path is auto-derived from --rename_v via existing logic downstream.

    # ----- model init -----
    is_gemini = args.model.startswith("gemini")
    if is_gemini:
        ensure_gemini()
        # Under gemini, stage 1 also routes through gemini — no openai needed.
    else:
        ensure_openai()

    df = pd.read_csv(args.csv_path)
    df = apply_row_selection(df, args.rows)
    print(f"📄 Running on {len(df)} rows from {args.csv_path} (dataset={args.dataset}, model={args.model})")

    # ----- dataset-specific table/view lists -----
    ds = DATASET_TABLES[args.dataset]
    ds_org_tables = ds["org_tables"]
    ds_db_dict = ds["db_dict"]
    base_tables = ds["renamed_tables"] if args.rename else ds["org_tables"]
    extra_views_pool = ds["renamed_views"] if args.rename else ds["org_views"]

    # ----- --rename_v override (tables + views pool) -----
    # rename_v variable name convention: "{dataset}_renamed_tables[_<suffix>]".
    # When matched:
    #   - default mapping file → "name_mapping_{dataset}[_<suffix>].json"
    #   - default views pool   → globals()["{dataset}_renamed_views[_<suffix>]"] (empty if missing)
    _rename_v_suffix = None
    if args.rename and args.rename_v:
        _custom = globals().get(args.rename_v)
        if _custom is None:
            raise SystemExit(
                f"--rename_v {args.rename_v!r} not found as a module-level variable in run_spider.py."
            )
        if not isinstance(_custom, list) or not all(isinstance(t, str) for t in _custom):
            raise SystemExit(
                f"--rename_v {args.rename_v!r} must be a list of strings; got {type(_custom).__name__}."
            )
        print(f"📝 --rename_v: overriding renamed_tables with {args.rename_v!r} ({len(_custom)} tables)")
        base_tables = _custom

        import re as _re_rv
        _m = _re_rv.match(r"^(spider|bird)_renamed_tables(?:_(\w+))?$", args.rename_v)
        if _m:
            _rename_v_suffix = _m.group(2)  # "0", "50", or None for bare "bird_renamed_tables"
            _views_var = args.rename_v.replace("_renamed_tables", "_renamed_views")
            _custom_views = globals().get(_views_var)
            if _custom_views is None:
                print(f"⚠️  --rename_v: no views list {_views_var!r} defined — views pool is empty")
                extra_views_pool = []
            else:
                if not isinstance(_custom_views, list) or not all(isinstance(v, str) for v in _custom_views):
                    raise SystemExit(
                        f"{_views_var!r} must be a list of strings; got {type(_custom_views).__name__}."
                    )
                print(f"📝 --rename_v: using views pool {_views_var!r} ({len(_custom_views)} views)")
                extra_views_pool = _custom_views
        else:
            print(f"⚠️  --rename_v {args.rename_v!r} does not match '{{dataset}}_renamed_tables[_<suffix>]' — "
                  f"views pool and mapping file fall back to dataset defaults.")

    # ----- --view_v explicit views-pool override (wins over --rename_v auto-derivation) -----
    _view_v_suffix = None
    if args.view_v:
        _custom_views_v = globals().get(args.view_v)
        if _custom_views_v is None:
            raise SystemExit(
                f"--view_v {args.view_v!r} not found as a module-level variable in run_spider.py."
            )
        if not isinstance(_custom_views_v, list) or not all(isinstance(v, str) for v in _custom_views_v):
            raise SystemExit(
                f"--view_v {args.view_v!r} must be a list of strings; got {type(_custom_views_v).__name__}."
            )
        print(f"📝 --view_v: overriding views pool with {args.view_v!r} ({len(_custom_views_v)} views)")
        extra_views_pool = _custom_views_v
        import re as _re_vv
        _m_vv = _re_vv.match(r".+_(\d+)$", args.view_v)
        if _m_vv:
            _view_v_suffix = _m_vv.group(1)

    # ----- --per_db validation -----
    if args.per_db:
        if not ds_db_dict:
            raise SystemExit(
                f"--per_db requires DATASET_TABLES['{args.dataset}']['db_dict'] to be populated. "
                f"Currently empty for dataset={args.dataset!r}."
            )
        if "db_id" not in df.columns:
            raise SystemExit("--per_db requires a 'db_id' column in the input CSV.")

    # ----- history CSV column names (rename-aware; honor --rename_v suffix) -----
    # With --rename_v bird_renamed_tables_50 the renamed-history columns are expected to
    # carry a matching _<suffix> (e.g. "renamed_SQL_50", "renamed_view_SQL_50"). These
    # columns must be pre-populated in the history sample CSV; see _rename_v_suffix above.
    if args.rename:
        _tail = f"_{_rename_v_suffix}" if _rename_v_suffix else ""
        hist_sql_col       = f"renamed_SQL{_tail}"
        hist_view_sql_col  = f"renamed_view_SQL{_tail}"
        hist_gt_tables_col = f"gt_renamed_tables{_tail}"
    else:
        hist_sql_col       = "SQL"
        hist_view_sql_col  = "view_SQL"
        hist_gt_tables_col = "gt_tables"
    TOP_K = 3

    # ----- base schema -----
    # When --rename, the base tables are stored as VIEWS in the sqlite db, so use
    # get_database_schema with view_support enabled. Otherwise use the original
    # per-table generate_schema_prompt path.
    print(f"📚 Building base schema from {len(base_tables)} tables...")
    # Sanity check: warn if any requested base tables aren't actually present in the sqlite,
    # since generate_schema_prompt / get_database_schema silently skip missing names.
    _present = {n.lower() for n in list_tables_and_views(db_path)}
    _missing = [t for t in base_tables if t.lower() not in _present]
    if _missing:
        print(f"⚠️  {len(_missing)}/{len(base_tables)} base tables NOT found in {db_path}: {_missing}")

    # Use generate_schema_prompt for both modes — it reads sample rows via raw sqlite
    # cursor (no type coercion), so it handles non-ISO date strings in views/tables alike.
    base_schema = "\n\n".join(
        generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=t)
        for t in base_tables
    ) + "\n\n"

    # ----- FK injection for --rename -----
    # Bird mapping has {org_col: renamed_col} inner dicts; spider has {renamed_col: org_col}.
    _org_keyed = (args.dataset == "bird")
    mapping_path = None
    if args.rename:
        script_dir = os.path.dirname(os.path.abspath(__file__))              # .../benchmarks/spider_data/
        # Mapping files live at <LDD_ROOT>/mapping_files (two levels up); legacy fallback is script_dir.
        _ldd_mapping_dir = os.path.abspath(os.path.join(script_dir, "..", "..", "mapping_files"))
        _default_mapping = f"name_mapping_{args.dataset}"
        if _rename_v_suffix:
            _default_mapping += f"_{_rename_v_suffix}"
        _default_mapping += ".json"

        if args.mapping_path:
            mapping_path = args.mapping_path
        else:
            _ldd_candidate    = os.path.join(_ldd_mapping_dir, _default_mapping)
            _legacy_candidate = os.path.join(script_dir, _default_mapping)
            if os.path.exists(_ldd_candidate):
                mapping_path = _ldd_candidate
            elif os.path.exists(_legacy_candidate):
                mapping_path = _legacy_candidate
            else:
                mapping_path = _ldd_candidate  # report the primary-default path in the error below
        if not os.path.exists(mapping_path):
            raise SystemExit(
                f"--rename needs a mapping file but {mapping_path} does not exist. "
                f"Pass --mapping_path explicitly."
            )
        fk_block = build_renamed_fk_block(db_path, ds_org_tables, mapping_path,
                                          org_keyed_columns=_org_keyed)
        if fk_block:
            base_schema += fk_block
            print(f"🔗 Injected {fk_block.count(chr(10)) - 2} renamed FK lines into base_schema")
        else:
            print("⚠️  No FKs translated to renamed namespace — base_schema unchanged.")

    # ----- history-derived structures -----
    sample = None
    exact_clusters = None
    question_cluster_map = None
    ref_texts = None
    ref_embs = None

    if args.history_path:
        sample, exact_clusters, question_cluster_map = build_clusters_from_history(
            args.history_path,
            sql_col=hist_sql_col,
            gt_tables_col=hist_gt_tables_col,
            sample_pct=args.sample,
        )
        print("🧠 Loading BGE encoder and building reference embeddings from history...")
        ensure_bge_model()
        ref_texts, ref_embs = prepare_reference_embeddings(list(sample['question']))

    # ---------------- --per_db setup (lazy cache) ----------------
    # Strategy: build per-db_id resources on first encounter, reuse on subsequent rows.
    # Per-db resources: (base_schema, extra_views_pool, exact_clusters, sample, ref_texts, ref_embs)
    # For unknown db_ids, fall back to the globals above.
    per_db_cache = {}           # db_id -> tuple of 6 resources
    _per_db_warned = set()      # db_ids we've already warned about (unknown)

    # Normalize db_dict values into the ACTIVE namespace (renamed if --rename, else org).
    # db_dict values are ORG names; with --rename we translate via mapping.
    _db_tables_active = {}      # db_id -> list of tables in the active namespace
    if args.per_db:
        if args.rename:
            # Reuse the mapping_path already resolved above (honors --mapping_path and --rename_v).
            _table_to_view, _ = load_rename_mapping(mapping_path, org_keyed_columns=_org_keyed)
            for db_id, tables in ds_db_dict.items():
                mapped = []
                for t in tables:
                    rn = _table_to_view.get(t.lower())
                    if rn:
                        mapped.append(rn)
                    else:
                        print(f"⚠️  --per_db --rename: db_id={db_id!r} table {t!r} has no rename mapping, skipping")
                _db_tables_active[db_id] = mapped
        else:
            _db_tables_active = {k: list(v) for k, v in ds_db_dict.items()}
        print(f"📦 --per_db active with {len(_db_tables_active)} db_ids")

    def resolve_per_db(db_id):
        """Return (base_schema, extra_views_pool, exact_clusters, sample, ref_texts, ref_embs)
        for this db_id — using cached values or falling back to globals."""
        if not args.per_db or db_id is None or db_id not in _db_tables_active:
            if args.per_db and db_id is not None and db_id not in _db_tables_active and db_id not in _per_db_warned:
                print(f"⚠️  --per_db: db_id={db_id!r} not in db_dict, falling back to full union for this question")
                _per_db_warned.add(db_id)
            return base_schema, extra_views_pool, exact_clusters, sample, ref_texts, ref_embs

        if db_id in per_db_cache:
            return per_db_cache[db_id]

        db_tables = _db_tables_active[db_id]
        db_tables_lower = {t.lower() for t in db_tables}
        print(f"🔧 --per_db: building resources for db_id={db_id!r} ({len(db_tables)} tables)")

        # --- base schema: per-table generate_schema_prompt ---
        pieces = []
        for t in db_tables:
            try:
                pieces.append(generate_schema_prompt(
                    db_path=db_path, num_rows=3, no_join=False, target_table=t
                ))
            except Exception as _e:
                logging.warning(f"generate_schema_prompt failed for {t!r}: {_e}")
        _bs = "\n\n".join(p for p in pieces if p) + "\n\n"

        # --- FK block for --rename ---
        if args.rename:
            # Reuse the already-resolved mapping_path from the main --rename block above
            # (which prefers Logical-Database-Design/mapping_files, falls back to script dir).
            _fk = build_renamed_fk_block(
                db_path, ds_db_dict[db_id], mapping_path,
                org_keyed_columns=_org_keyed,
            )
            if _fk:
                _bs += _fk

        # --- views pool: keep only views whose base tables ALL lie in db_tables ---
        _vp = []
        if extra_views_pool:
            for v in extra_views_pool:
                bases = parse_view_base_tables(v)
                if bases and all(b.lower() in db_tables_lower for b in bases):
                    _vp.append(v)

        # --- clusters: keep only clusters whose tables are a subset of db_tables ---
        _ec = None
        if exact_clusters is not None:
            _ec = [
                c for c in exact_clusters
                if all(t.lower() in db_tables_lower for t in c["tables"])
            ]

        # --- history sample subset + per-db BGE embeddings ---
        _sp = None
        _rt = None
        _re = None
        if sample is not None and "db_id" in sample.columns:
            _sp = sample[sample["db_id"] == db_id].reset_index(drop=True)
            if len(_sp) > 0:
                _rt, _re = prepare_reference_embeddings(list(_sp["question"]))

        per_db_cache[db_id] = (_bs, _vp, _ec, _sp, _rt, _re)
        return per_db_cache[db_id]

    # ----- log/output suffix and folder -----
    suffix = ""
    if args.rename:
        suffix += "_rename"
    if args.view:
        suffix += "_withview"
    if args.cluster:
        suffix += "_clusterfilter" if args.cluster_filter else "_cluster"
    if args.history_path:
        suffix += f"_history{args.sample}" if args.sample < 100 else "_history"
    if args.use_linking:
        if args.view_adhoc:
            suffix += "_adhoclinking"
        elif args.view_relink:
            suffix += "_relinking"
        else:
            suffix += "_uselinking"
    if args.per_db:
        # _top3 only when TOP_K history retrieval is actually in use.
        suffix += "_perdb_top3" if args.history_path else "_perdb"
    # Append rename_v / view_v level marker for non-history runs (history already encodes
    # it via _history{N}). Avoids collision when 50% and 100% variants share other flags.
    if not args.history_path:
        _level = _rename_v_suffix or _view_v_suffix
        if _level:
            suffix += f"_{_level}"
    # Model suffix: extract digits from model name → e.g. "gpt-4.1-mini" → "gpt41",
    # "gemini-2.5-flash-lite" → "gem25", "gpt-5.4-mini" → "gpt54"
    import re as _re
    _model_digits = "".join(_re.findall(r"\d", args.model))
    if is_gemini:
        suffix += f"_gem{_model_digits}"
    elif args.model != "gpt-4.1-mini":
        suffix += f"_gpt{_model_digits}"

    run_id = time.strftime("%Y%m%d-%H%M%S")
    log_base = f"logs_{args.dataset}" if args.dataset != "spider" else "logs"
    log_dir = os.path.join(log_base, f"run_{run_id}{suffix}")
    os.makedirs(log_dir, exist_ok=True)
    print(f"📂 Logging prompts to: {log_dir}")

    linking_col = f"linking{suffix}"
    sql_col = f"sql{suffix}"
    revised_sql_col = f"revised_sql{suffix}"

    failed_idx = []

    # --view_adhoc: cache successful views keyed by frozenset(lowered table names).
    # Failures are NOT cached so each question can retry past LLM flakiness.
    adhoc_view_cache = {}

    for index, row in df.iterrows():
        log_file = os.path.join(log_dir, f"q{int(index):04d}.log")
        # Resolve per-db resources for this question (no-ops if --per_db is off)
        _q_db_id = row.get("db_id") if "db_id" in df.columns else None
        _q_bs, _q_vp, _q_ec, _q_sp, _q_rt, _q_re = resolve_per_db(_q_db_id)
        for attempt in range(3):
            try:
                # Clear log for this attempt so a successful retry replaces partial output
                open(log_file, "w", encoding="utf-8").close()
                append_log(log_dir, index, "QUESTION", str(row['question']))

                # ---- Stage 0 (when --view_adhoc or --view_relink): parse tables from --use_linking ----
                adhoc_view_name = None
                adhoc_view_schema_str = None
                adhoc_skip_stage1 = False  # view_adhoc: <2 linked tables → use --use_linking value as-is
                relink_matched_views_schema = None  # view_relink: concatenated matched-view schemas
                relink_skip_stage1 = False
                stage0_tables = []
                if args.view_adhoc or args.view_relink:
                    stage0_value = row[args.use_linking]
                    mode_label = "adhoc view" if args.view_adhoc else "relink"
                    append_log(log_dir, index, f"STAGE 0: {mode_label} seed (from --use_linking)",
                               f"column={args.use_linking}\nvalue={stage0_value}")
                    try:
                        sl0 = ast.literal_eval(stage0_value) if isinstance(stage0_value, str) else stage0_value
                    except Exception:
                        sl0 = []
                    temp_list = [x.replace('`', '').lower() for x in sl0 if isinstance(x, str)]
                    col_list = []
                    for i in temp_list:
                        if len(i.split(".")) == 2 and "=" not in i:
                            col_list.append(i)
                        elif len(i.split("=")) == 2:
                            tt = i.split("=")
                            if len(tt[0].strip().split(".")) == 2:
                                col_list.append(tt[0].strip())
                            if len(tt[1].strip().split(".")) == 2:
                                col_list.append(tt[1].strip())
                    stage0_tables_lower = list({x.split(".")[0] for x in col_list if len(x.split(".")) == 2})
                    bt_lookup = {t.lower(): t for t in base_tables}
                    stage0_tables = [bt_lookup[t] for t in stage0_tables_lower if t in bt_lookup]

                    tag = "adhoc view" if args.view_adhoc else "relink"
                    print(f"[{tag}] q{int(index):04d}: stage-0 linked tables "
                          f"({len(stage0_tables)}): {stage0_tables}")

                if args.view_adhoc:

                    if len(stage0_tables) >= 2:
                        cache_key = frozenset(t.lower() for t in stage0_tables)
                        if cache_key in adhoc_view_cache:
                            adhoc_view_name, adhoc_view_schema_str = adhoc_view_cache[cache_key]
                            print(f"[adhoc view] q{int(index):04d}: 🎯 cache HIT → {adhoc_view_name!r}")
                            append_log(log_dir, index,
                                       f"STAGE 0: adhoc view cache HIT ({adhoc_view_name})",
                                       adhoc_view_schema_str or "")
                        else:
                            print(f"[adhoc view] q{int(index):04d}: cache MISS → discovering FKs")
                            fk_conds = find_fk_conditions_for_view_adhoc(
                                db_path, stage0_tables,
                                rename_mode=args.rename,
                                mapping_path=mapping_path,
                                ds_org_tables=ds_org_tables,
                                org_keyed=_org_keyed,
                            )
                            if fk_conds:
                                adhoc_view_name, adhoc_view_schema_str = create_adhoc_view(
                                    db_path, stage0_tables, fk_conds,
                                    model=args.model, is_gemini=is_gemini,
                                    excluded_views=(list(ds.get("org_views", []))
                                                    + list(ds.get("renamed_views", []))),
                                )
                                if adhoc_view_name:
                                    adhoc_view_cache[cache_key] = (adhoc_view_name, adhoc_view_schema_str)
                                    append_log(log_dir, index,
                                               f"STAGE 0: adhoc view created ({adhoc_view_name})",
                                               adhoc_view_schema_str)
                                else:
                                    append_log(log_dir, index,
                                               "STAGE 0: adhoc view FAILED (LLM) — stage-1 uses base schema",
                                               f"tables={stage0_tables}\nfk_conditions={fk_conds}")
                            else:
                                print(f"[adhoc view] q{int(index):04d}: ⚠️  no FKs among "
                                      f"{stage0_tables} → fall back to base schema")
                                append_log(log_dir, index,
                                           "STAGE 0: no FK conditions found — stage-1 uses base schema",
                                           f"tables={stage0_tables}")
                    else:
                        adhoc_skip_stage1 = True
                        print(f"[adhoc view] q{int(index):04d}: ⚠️  only {len(stage0_tables)} "
                              f"linked table(s) → SKIPPING stage 1, reusing --use_linking value")
                        append_log(log_dir, index,
                                   "STAGE 0: <2 linked tables — stage-1 SKIPPED, reusing --use_linking value",
                                   f"tables={stage0_tables}")

                if args.view_relink:
                    if len(stage0_tables) >= 2:
                        if _q_vp:
                            matched_views_s0 = find_matching_views(_q_vp, stage0_tables)
                        else:
                            matched_views_s0 = []
                        if matched_views_s0:
                            relink_matched_views_schema = "\n\n".join(
                                generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=v)
                                for v in matched_views_s0
                            )
                            print(f"[relink] q{int(index):04d}: matched {len(matched_views_s0)} view(s) "
                                  f"from stage-0 tables → {matched_views_s0}")
                            append_log(log_dir, index,
                                       f"STAGE 0: relink matched {len(matched_views_s0)} view(s)",
                                       f"views={matched_views_s0}")
                        else:
                            relink_skip_stage1 = True
                            print(f"[relink] q{int(index):04d}: no views matched stage-0 tables "
                                  f"→ SKIPPING stage 1, reusing --use_linking value")
                            append_log(log_dir, index,
                                       "STAGE 0: relink — no matching views — stage-1 SKIPPED, "
                                       "reusing --use_linking value",
                                       f"tables={stage0_tables}")
                    else:
                        relink_skip_stage1 = True
                        print(f"[relink] q{int(index):04d}: ⚠️  only {len(stage0_tables)} "
                              f"linked table(s) → SKIPPING stage 1, reusing --use_linking value")
                        append_log(log_dir, index,
                                   "STAGE 0: <2 linked tables — stage-1 SKIPPED, reusing --use_linking value",
                                   f"tables={stage0_tables}")

                # Stage-1 input schema: base + (adhoc view | relink matched views) when applicable.
                stage1_input_schema = _q_bs
                if args.view_adhoc and adhoc_view_schema_str:
                    stage1_input_schema = _q_bs + "\n\n" + adhoc_view_schema_str + "\n\n"
                elif args.view_relink and relink_matched_views_schema:
                    stage1_input_schema = _q_bs + "\n\n" + relink_matched_views_schema + "\n\n"

                # ---- Stage 1: schema linking ----
                # Skip stage 1 when:
                #   - --use_linking is set AND neither --view_adhoc nor --view_relink is ON, OR
                #   - --view_adhoc is ON and stage 0 yielded <2 linked tables, OR
                #   - --view_relink is ON and stage 0 yielded <2 linked tables.
                skip_stage1 = args.use_linking and (
                    (not args.view_adhoc and not args.view_relink)
                    or adhoc_skip_stage1
                    or relink_skip_stage1
                )
                if skip_stage1:
                    schema_links = row[args.use_linking]
                    if args.view_adhoc:
                        reason = "<2 linked tables under --view_adhoc"
                    elif args.view_relink:
                        reason = ("no view to justify re-linking under --view_relink "
                                  "(<2 tables or no matching views)")
                    else:
                        reason = "read from column"
                    append_log(log_dir, index, f"STAGE 1: linking (skipped — {reason})",
                               f"column={args.use_linking}\nvalue={schema_links}")
                else:
                    if args.view_adhoc:
                        use_join_template = bool(adhoc_view_schema_str)
                    elif args.view_relink:
                        use_join_template = bool(relink_matched_views_schema)
                    else:
                        use_join_template = bool(args.view)
                    sys_template = SYSTEM_SCHEMA_LINKING_TEMPLATE_JOIN if use_join_template else SYSTEM_SCHEMA_LINKING_TEMPLATE
                    system_schema_linking_prompt = SystemMessagePromptTemplate.from_template(sys_template)
                    human_schema_linking_prompt = HumanMessagePromptTemplate.from_template(HUMAN_SCHEMA_LINKING_TEMPLATE)
                    schema_linking_prompt = ChatPromptTemplate.from_messages(
                        [system_schema_linking_prompt, human_schema_linking_prompt]
                    )
                    linking_prompt_text = schema_linking_prompt.format(
                        question=row['question'], schema=stage1_input_schema
                    )
                    # Under gemini, route stage 1 through gemini (structured output) to keep
                    # models aligned across stages. Otherwise stay on LangChain + GPT-4.1-mini.
                    # If the LLM call OR parse fails AND --use_linking is set, fall back to
                    # the pre-computed linking column instead of re-raising (recovers gemini
                    # repetition-loop failures without triggering the attempt-level retry).
                    try:
                        if is_gemini:
                            append_log(log_dir, index, "STAGE 1 PROMPT: schema linking (gemini)",
                                       linking_prompt_text)
                            chatbot_response = chat_with_gemini_DIN(
                                linking_prompt_text, model=args.model,
                                response_fields={"schema_links": list},
                            )
                        else:
                            append_log(log_dir, index, "STAGE 1 PROMPT: schema linking",
                                       linking_prompt_text)
                            linking_chain = LLMChain(llm=CHAT, prompt=schema_linking_prompt)
                            chatbot_response = linking_chain.run(question=row['question'], schema=stage1_input_schema)
                        append_log(log_dir, index, "STAGE 1 RESPONSE", chatbot_response)
                        _cleaned = re.sub(r'//.*', '', chatbot_response.replace("```json", "").replace("```", ""))
                        try:
                            schema_links = ast.literal_eval(_cleaned)['schema_links']
                        except (SyntaxError, ValueError):
                            # Wrap bare backtick identifiers like `x`.`y` -> "`x`.`y`" so ast.literal_eval succeeds.
                            _fixed = re.sub(r'([\[,]\s*)(`[^`]+`(?:\.`[^`]+`)*)', r'\1"\2"', _cleaned)
                            schema_links = ast.literal_eval(_fixed)['schema_links']
                        schema_links = str(schema_links)
                    except Exception as _stage1_err:
                        if args.use_linking:
                            schema_links = row[args.use_linking]
                            print(f"[stage 1] q{int(index):04d}: fresh linking FAILED "
                                  f"({type(_stage1_err).__name__}: {_stage1_err}) — "
                                  f"falling back to --use_linking column")
                            append_log(log_dir, index,
                                       "STAGE 1 FAILED — falling back to --use_linking",
                                       f"error={type(_stage1_err).__name__}: {_stage1_err}\n"
                                       f"fallback column={args.use_linking}\nvalue={schema_links}")
                            schema_links = str(schema_links)
                        else:
                            raise
                df.at[index, linking_col] = str(schema_links)

                # ---- Parse Stage-1 schema links → retrieved_tables (used by --view and --cluster) ----
                retrieved_tables = []
                if args.view or args.cluster:
                    sl_raw = schema_links
                    if isinstance(sl_raw, str):
                        sl_raw = ast.literal_eval(sl_raw)
                    temp_list = [x.replace('`', '').lower() for x in sl_raw if isinstance(x, str)]
                    col_list = []
                    for i in temp_list:
                        if len(i.split(".")) == 2 and "=" not in i:
                            col_list.append(i)
                        elif len(i.split("=")) == 2:
                            t = i.split("=")
                            if len(t[0].strip().split(".")) == 2:
                                col_list.append(t[0].strip())
                            if len(t[1].strip().split(".")) == 2:
                                col_list.append(t[1].strip())
                    retrieved_tables = list({x.split(".")[0] for x in col_list if len(x.split(".")) == 2})

                # ---- Cluster lookup (only --cluster needs it) ----
                cluster_res = None
                if args.cluster and _q_ec is not None and retrieved_tables:
                    cluster_res = find_all_clusters_for_tables(
                        retrieved_tables, _q_ec, sqlite_path=db_path
                    )

                # ---- Cluster filter: optionally restrict stage-2/3 base schema + FKs + views ----
                apply_cluster_filter = False
                effective_base = None
                cluster_set_lc = None
                if args.cluster_filter and cluster_res is not None and cluster_res.get("tables"):
                    _cluster_tables = cluster_res["tables"]
                    _bt_lookup = {t.lower(): t for t in base_tables}
                    cluster_tables_oc = [_bt_lookup.get(t.lower(), t) for t in _cluster_tables]
                    cluster_set_lc = {t.lower() for t in cluster_tables_oc}

                    effective_base = "\n\n".join(
                        generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=t)
                        for t in cluster_tables_oc
                    ) + "\n\n"

                    # FKs between cluster tables only (dedup'd; rename-aware via the helper)
                    _fk_lines = find_fk_conditions_for_view_adhoc(
                        db_path, cluster_tables_oc,
                        rename_mode=args.rename,
                        mapping_path=mapping_path,
                        ds_org_tables=ds_org_tables,
                        org_keyed=_org_keyed,
                    )
                    if _fk_lines:
                        effective_base += "Foreign Keys:\n" + "\n".join(
                            fk.replace("=", " = ") for fk in _fk_lines
                        ) + "\n\n"

                    apply_cluster_filter = True
                    append_log(log_dir, index,
                               "CLUSTER FILTER: restricted schema to cluster tables",
                               f"tables ({len(cluster_tables_oc)}): {cluster_tables_oc}\n"
                               f"fks ({len(_fk_lines)}): {_fk_lines}")
                elif args.cluster_filter:
                    append_log(log_dir, index,
                               "CLUSTER FILTER: no matched clusters — falling back to full schema",
                               "")

                # ---- Build updated_schema (inject views matching the Stage-1 tables) ----
                if args.view_adhoc:
                    if apply_cluster_filter:
                        # Rebuild from cluster-filtered base; keep the adhoc view only if its
                        # tables are entirely inside the cluster table set.
                        updated_schema = effective_base
                        if (adhoc_view_schema_str and stage0_tables
                                and all(t.lower() in cluster_set_lc for t in stage0_tables)):
                            updated_schema += adhoc_view_schema_str + "\n\n"
                    else:
                        updated_schema = stage1_input_schema
                elif args.view_relink:
                    if apply_cluster_filter:
                        # Treat same as plain --view path when cluster_filter is on: rebuild
                        # matched views (pre-defined pool) restricted to cluster tables.
                        updated_schema = effective_base
                        if args.view and _q_vp and retrieved_tables:
                            matched_views = find_matching_views(_q_vp, retrieved_tables)
                            matched_views = [
                                v for v in matched_views
                                if all(b.lower() in cluster_set_lc for b in parse_view_base_tables(v))
                            ]
                            if matched_views:
                                updated_schema += "\n\n" + "\n\n".join(
                                    generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=v)
                                    for v in matched_views
                                ) + "\n\n"
                    else:
                        updated_schema = stage1_input_schema
                else:
                    updated_schema = effective_base if apply_cluster_filter else _q_bs
                    if args.view and _q_vp and retrieved_tables:
                        matched_views = find_matching_views(_q_vp, retrieved_tables)
                        if apply_cluster_filter:
                            matched_views = [
                                v for v in matched_views
                                if all(b.lower() in cluster_set_lc for b in parse_view_base_tables(v))
                            ]
                        if matched_views:
                            updated_schema += "\n\n" + "\n\n".join(
                                generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=v)
                                for v in matched_views
                            ) + "\n\n"

                # ---- Top-K history SQL retrieval (--history_path) ----
                top_sqls = ""
                if args.history_path and _q_rt is not None and _q_sp is not None and len(_q_sp) > 0:
                    # Choose retrieval pool: filtered by clusters (--cluster) or the per-db (or global) sample.
                    if args.cluster and cluster_res is not None and cluster_res.get('indices'):
                        cand_indices = cluster_res['indices']
                        # cand_indices are from the ORIGINAL (global) sample; map question text via _q_sp or sample
                        src_df = _q_sp if _q_sp is not None else sample
                        # Filter indices that still exist after any subsetting
                        valid = [i for i in cand_indices if i in src_df.index]
                        if valid:
                            cand_questions = src_df.loc[valid, 'question'].astype(str).to_list()
                            local_refs, local_embs = prepare_reference_embeddings(
                                cand_questions, indices=valid
                            )
                            top_results = topk_embedding_cosine_sim(
                                row['question'], local_refs, local_embs, top_k=TOP_K
                            )
                        else:
                            top_results = []
                        # Top-up from per-db (or global) pool when the cluster pool yielded
                        # fewer than TOP_K — preserves cluster picks first, then adds the
                        # next-best questions from the same db without duplicating indices.
                        if len(top_results) < TOP_K:
                            already = {r[0] for r in top_results}
                            extras_needed = TOP_K - len(top_results)
                            backup = topk_embedding_cosine_sim(
                                row['question'], _q_rt, _q_re, top_k=TOP_K + len(already)
                            )
                            extras = [r for r in backup if r[0] not in already][:extras_needed]
                            top_results = list(top_results) + extras
                    else:
                        top_results = topk_embedding_cosine_sim(
                            row['question'], _q_rt, _q_re, top_k=TOP_K
                        )
                    top_indices = [x[0] for x in top_results]
                    top_sqls = " \n".join(
                        _q_sp.loc[top_indices, hist_sql_col].astype(str).to_list()
                    )
                    if args.view:
                        top_sqls += " \n" + " \n".join(
                            _q_sp.loc[top_indices, hist_view_sql_col].astype(str).to_list()
                        )

                # ---- Cluster join paths (--cluster) ----
                paths_str = ""
                if args.cluster and cluster_res is not None:
                    paths_str = ', \n'.join(sorted(set(cluster_res.get('paths', []))))

                # Optional history/cluster prompt sections — headers only appear when content exists
                history_block = f"        History SQLs:\n        {top_sqls}\n\n" if top_sqls else ""
                paths_block = f"        Common Join Paths:\n        {paths_str}\n\n" if paths_str else ""

                # Extra instructions appended only when history SQLs are present
                history_instructions_gen = (
                    "        12. Make use of the history SQL, it can provide very useful informations such as common joins, common selections and common projections.\n"
                    "        13. The history SQLs can be very similar to the actual answer, so make use of them, you should try to make small changes to them to get the desired SQL.\n"
                    "        14. Priority should be given to columns that have been explicitly matched with examples relevant to the question's context.\n"
                ) if top_sqls else ""
                history_instructions_rev = (
                    "        14. Make use of the history SQL, it can provide very useful informations such as common joins, common selections and common projections.\n"
                    "        15. The history SQLs can be very similar to the actual answer, so make use of them, you should try to make small changes to them to get the desired SQL.\n"
                    "        16. Priority should be given to columns that have been explicitly matched with examples relevant to the question's context.\n"
                ) if top_sqls else ""

                # ---- Stage 2: first SQL generation ----
                gen_prompt = f"""You are a data science expert.
        Below, you are presented with a database schema and a question.
        Your task is to read the schema, understand the question, and generate a valid SQLite query to answer the question.
        Before generating the final SQL query think step by step on how to write the query.

        Database Schema
        ###
        {updated_schema}

        ###
        This schema offers an in-depth description of the database's architecture, detailing tables, columns, primary keys, foreign keys, and any pertinent information regarding relationships or constraints. Special attention should be given to the examples listed beside each column, as they directly hint at which columns are relevant to our query.

        Database admin instructions:
        1. When you need to find the highest or lowest values based on a certain condition, using ORDER BY + LIMIT 1 is prefered over using MAX/MIN within sub queries.
        2. If predicted query includes an ORDER BY clause to sort the results, you should only include the column(s) used for sorting in the SELECT clause if the question specifically ask for them. Otherwise, omit these columns from the SELECT.
        3. If the question doesn't specify exactly which columns to select, between name column and id column, prefer to select id column.
        4. Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.
        5. Predicted query should return all of the information asked in the question without any missing or extra information.
        6. For key phrases mentioned in the question, we have provided the most similar values within the columns denoted by "-- examples" in front of the corresponding column names. This is a crucial hint indicating the correct columns to use for your SQL query.
        7. No matter of how many things the question asks, you should only return one SQL query as the answer having all the information asked in the question, seperated by a comma.
        8. Never use || to concatenate columns in the SELECT. Rather output the columns as they are.
        9. If you are joining multiple tables, make sure to use alias names for the tables and use the alias names to reference the columns in the query. Use T1, T2, T3, ... as alias names.
        10. If you are doing a logical operation on a column, such as mathematical operations and sorting, make sure to filter null values within those columns.
        11. Use ` around table and column names to avoid any confusions.
{history_instructions_gen}
        ###
        Question:
        {row['question']}

        Schema Linking:
        {schema_links}

{history_block}{paths_block}
        Please respond with a JSON object structured as follows:

        {{
            "chain_of_thought_reasoning": "Your thought process on how you arrived at the final SQL query.",
            "SQL": "Your SQL query in a single string."
        }}

        Priority should be given to columns that have been explicitly matched with examples relevant to the question's context.

        Take a deep breath and think step by step to find the correct sqlite SQL query. If you follow all the instructions and generate the correct query, I will give you 1 million dollars."""
                append_log(log_dir, index, "STAGE 2 PROMPT: SQL generation", gen_prompt)
                if is_gemini:
                    chatbot_response = chat_with_gemini_DIN(gen_prompt, model=args.model, response_fields={"SQL": str})
                    sql = json.loads(chatbot_response)["SQL"]
                else:
                    chatbot_response = chat_with_chatgpt_DIN(gen_prompt, model=args.model)
                    sql = json.loads(extract_json_block(chatbot_response))["SQL"].replace("```sql", "").replace("```", "")
                append_log(log_dir, index, "STAGE 2 RESPONSE", chatbot_response)
                df.at[index, sql_col] = sql
                print(index, sql)

                # ---- Stage 3: SQL revision ----
                query_result = validate_sql_query(db_path=db_path, sql=sql)
                rev_prompt = f"""Objective: Your objective is to make sure a query follows the database admin instructions and use the correct conditions.

        Database Schema:   
        ### 
        {updated_schema}

        ###
        Database admin instructions:
        1. When you need to find the highest or lowest values based on a certain condition, using ORDER BY + LIMIT 1 is prefered over using MAX/MIN within sub queries.
        2. If predicted query includes an ORDER BY clause to sort the results, you should only include the column(s) used for sorting in the SELECT clause if the question specifically ask for them. Otherwise, omit these columns from the SELECT.
        3. If the question doesn't specify exactly which columns to select, between name column and id column, prefer to select id column.
        4. Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.
        5. Predicted query should return all of the information asked in the question without any missing or extra information.
        7. For key phrases mentioned in the question, we have provided the most similar values within the columns denoted by "-- examples" in front of the corresponding column names. This is a crucial hint indicating the correct columns to use for your SQL query.
        8. No matter of how many things the question asks, you should only return one SQL query as the answer having all the information asked in the question, seperated by a comma.
        9. Using || ' ' ||  to concatenate is string is banned and using that is punishable by death. Never concatenate columns in the SELECT clause.
        10. If you are joining multiple tables, make sure to use alias names for the tables and use the alias names to reference the columns in the query. Use T1, T2, T3, ... as alias names.
        11. If you are doing a logical operation on a column, such as mathematical operations and sorting, make sure to filter null values within those columns.
        12. When ORDER BY is used, just include the column name in the ORDER BY in the SELECT clause when explicitly asked in the question. Otherwise, do not include the column name in the SELECT clause.
        13. Use ` around table and column names to avoid any confusions.
{history_instructions_rev}        ###

        Question:
        {row['question']}

        Schema Linking:
        {schema_links}

{history_block}{paths_block}
        Predicted query:
        {sql}

        Query status:
        {query_result['STATUS']}

        Query result:
        {query_result['RESULT']}

        Please respond with a JSON object structured as follows (if the sql query is correct, return the query as it is):

        {{
            "chain_of_thought_reasoning": "Your thought process on how you arrived at the solution. You don't need to explain the instructions that are satisfied.",
            "revised_SQL": "Your revised SQL query."
        }}

        Take a deep breath and think step by step to find the correct sqlite SQL query. If you follow all the instructions and generate the correct query, I will give you 1 million dollars."""
                append_log(log_dir, index, "STAGE 3 PROMPT: SQL revision", rev_prompt)
                if is_gemini:
                    chatbot_response = chat_with_gemini_DIN(rev_prompt, model=args.model, response_fields={"revised_SQL": str})
                else:
                    chatbot_response = chat_with_chatgpt_DIN(rev_prompt, model=args.model)
                append_log(log_dir, index, "STAGE 3 RESPONSE", chatbot_response)
                try:
                    if is_gemini:
                        revised_sql = json.loads(chatbot_response)["revised_SQL"]
                    else:
                        revised_sql = ast.literal_eval(
                            chatbot_response.replace("```json", "").replace("```", "")
                                            .replace(';\\"', ';"').replace('\\"SELECT', '"SELECT')
                        )['revised_SQL'].replace("```sql", "").replace("```", "")
                except Exception as e:
                    logging.error(f"Error parsing chatbot response: {e}")
                    revised_sql = sql  # Fallback to original SQL
                df.at[index, revised_sql_col] = revised_sql
                append_log(log_dir, index, "FINAL revised_sql", revised_sql)
                print("revised:", index, revised_sql)
                break
            except Exception as e:
                print(f"Attempt {attempt+1} failed for index {index}: {e}")
                if attempt < 2:  # not the last attempt
                    time.sleep(1 * (attempt + 1))  # optional delay between retries
                else:
                    failed_idx.append(index)
                    print(f"❌ Giving up after 3 attempts on index {index}")

        # Incremental save every 100 rows (crash resilience)
        if (list(df.index).index(index) + 1) % 100 == 0:
            _inc_path = os.path.join(log_dir, f"{os.path.splitext(os.path.basename(args.csv_path))[0]}{suffix}_out.csv")
            df.to_csv(_inc_path, index=False)
            print(f"💾 Incremental save at row {index}")

    # Save augmented CSV (linking + sql + revised_sql columns) into the run's log dir
    base_name = os.path.splitext(os.path.basename(args.csv_path))[0]
    out_path = os.path.join(log_dir, f"{base_name}{suffix}_out.csv")
    df.to_csv(out_path, index=False)
    print(f"💾 Saved results to: {out_path}")
    print(f"Failed indices: {failed_idx}")


if __name__ == "__main__":
    main()