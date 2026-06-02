import argparse
import os.path
import random
from copy import deepcopy
from typing import List, Dict

from cscsql.utils.common_utils import CommonUtils, parse_response
from cscsql.utils.file_utils import FileUtils
from cscsql.utils.infer_utils import (build_stop_token_ids,
                                          build_execute_sql_result,
                                          build_selection_vote_execute_sql_result,
                                          run_eval_major_vote, run_eval_major_vote_table)


def retrieve_history_for_questions(history_dir: str, input_questions: List[str],
                                   link_table_results: List, history_k: int = 7,
                                   use_clusters: bool = False,
                                   rename: bool = False, view: bool = False,
                                   dataset: str = "bird",
                                   cluster_filter: bool = False) -> Dict:
    """
    Retrieve top-k history SQLs per question at inference time.
    Uses precomputed embeddings + optionally clusters + Stage 1 table predictions.
    Returns dict: question_index_str -> {"history_sqls": str, "paths_str": str or None}
    """
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    from cscsql.service.process.process_single_db import (
        get_history_sql_cols, find_all_clusters_for_tables
    )

    # Load precomputed data
    emb_path = os.path.join(history_dir, "history_embeddings.npy")
    data_path = os.path.join(history_dir, "history_data.json")
    if not os.path.exists(emb_path) or not os.path.exists(data_path):
        print(f"WARNING: history files not found in {history_dir}")
        return {}

    history_embs = np.load(emb_path)
    history_data = FileUtils.load_json(data_path)
    sql_cols = get_history_sql_cols(rename, view, dataset=dataset)

    clusters = None
    if use_clusters:
        clusters_path = os.path.join(history_dir, "history_clusters.json")
        if os.path.exists(clusters_path):
            clusters = FileUtils.load_json(clusters_path)
            print(f"Loaded {len(clusters)} clusters")
        else:
            print(f"WARNING: --cluster set but {clusters_path} not found, falling back to full history")

    # Load embedding model
    model = SentenceTransformer('BAAI/bge-large-en-v1.5', device='cuda')
    #model = SentenceTransformer('BAAI/bge-large-en-v1.5', device='cpu')
    print(f"History retrieval: {len(history_embs)} entries, sql_cols={sql_cols}, clusters={'yes' if clusters else 'no'}")

    result = {}
    for idx, question in enumerate(input_questions):
        # Get Stage 1 predicted tables for this question
        predicted_tables = []
        if link_table_results is not None and idx < len(link_table_results):
            predicted_tables = link_table_results[idx]
            if isinstance(predicted_tables, dict):
                predicted_tables = list(predicted_tables.keys())

        paths_str = None
        candidate_indices = None
        cluster_tables = None  # union of tables across matched clusters (for --cluster_filter)

        # If clusters enabled and we have predicted tables, filter to cluster questions
        if clusters and predicted_tables:
            res = find_all_clusters_for_tables(predicted_tables, clusters)
            if res["indices"]:
                candidate_indices = res["indices"]
                paths_str = ', \n'.join(sorted(set(res['paths'])))
            # cluster_filter: expose matched-cluster table union for downstream override
            if cluster_filter and res.get("tables"):
                cluster_tables = sorted(set(res["tables"]))

        # Build target embedding
        target_emb = model.encode(
            ["query: " + str(question).strip()],
            normalize_embeddings=True
        )

        if candidate_indices is not None and len(candidate_indices) > 0:
            # Cluster mode: only search within cluster questions
            cluster_embs = history_embs[candidate_indices]
            similarities = cosine_similarity(target_emb, cluster_embs).flatten()
            top_local_idx = similarities.argsort()[::-1][:history_k]
            top_global_idx = [candidate_indices[i] for i in top_local_idx]
        else:
            # Full history mode (no clusters or fallback)
            similarities = cosine_similarity(target_emb, history_embs).flatten()
            top_global_idx = similarities.argsort()[::-1][:history_k].tolist()

        # Extract SQLs from all columns
        top_sqls = []
        for col in sql_cols:
            col_data = history_data.get(col, [])
            for i in top_global_idx:
                if i < len(col_data):
                    sql = str(col_data[i])
                    if sql and sql != 'nan':
                        top_sqls.append(sql.strip())

        history_sql_text = " \n".join(top_sqls) + " \n" if top_sqls else None

        if history_sql_text or cluster_tables:
            entry = {
                "history_sqls": history_sql_text,
                "paths_str": paths_str,
            }
            if cluster_tables:
                entry["cluster_tables"] = cluster_tables
            result[str(idx)] = entry

    print(f"Retrieved history for {len(result)} questions")
    return result


def generate_remote(api_base: str, model_name: str, chat_prompts: List[str],
                    n: int, temperature: float, max_tokens: int,
                    stop_token_ids: List[int] = None,
                    max_workers: int = 8, max_retries: int = 3) -> List[List[str]]:
    """Call a remote vLLM OpenAI-compatible server with parallel requests.
    Results returned in the original prompt order."""
    from openai import OpenAI
    from tqdm import tqdm
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    # Ensure api_base has http:// prefix
    if not api_base.startswith("http"):
        api_base = f"http://{api_base}"

    client = OpenAI(base_url=api_base, api_key="EMPTY")

    def _one_call(idx, prompt):
        for attempt in range(max_retries):
            try:
                response = client.completions.create(
                    model=model_name,
                    prompt=prompt,
                    n=n,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return idx, [choice.text for choice in response.choices]
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Remote API error (idx={idx}, final attempt): {e}")
                    return idx, [""] * n
                time.sleep(2 ** attempt)  # 1s, 2s, 4s backoff

    all_responses = [None] * len(chat_prompts)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_one_call, i, p) for i, p in enumerate(chat_prompts)]
        for fut in tqdm(as_completed(futures), total=len(futures), desc=f"Remote inference ({max_workers} workers)"):
            idx, responses = fut.result()
            all_responses[idx] = responses

    return all_responses

    
def generate_local(opt, model_path, chat_prompts, sampling_params, enable_lora, lora_request, max_model_len):
    """Load model locally with vLLM and generate."""
    from vllm import LLM
    from transformers import AutoConfig

    quantization = getattr(opt, 'quantization', None)
    load_format = "bitsandbytes" if quantization == "bitsandbytes" else "auto"

    llm = LLM(
        model=model_path,
        dtype="bfloat16",
        tensor_parallel_size=opt.tensor_parallel_size,
        max_model_len=max_model_len,
        seed=opt.seed,
        gpu_memory_utilization=opt.gpu_memory_utilization,
        swap_space=42,
        enforce_eager=True,
        enable_lora=enable_lora,
        max_lora_rank=opt.max_lora_rank,
        disable_custom_all_reduce=True,
        trust_remote_code=True,
        quantization=quantization,
        load_format=load_format
    )

    outputs = llm.generate(chat_prompts, sampling_params=sampling_params, lora_request=lora_request)
    all_responses = []
    for output in outputs:
        responses = [o.text for o in output.outputs]
        all_responses.append(responses)

    return all_responses


def make_prefix(dp: Dict, template_type='think',
                instruction_key='input_seq',
                current_few_shot=None,
                current_selection_vote_predict=None,
                prompt_mode="vote"):
    question_raw = dp[instruction_key] + dp.get("input", "")
    task_msg = "Please output only the final SQL query, starts with keyword `SELECT`."
    question_raw = question_raw.replace(task_msg, '')

    if prompt_mode == "table":
        task_msg = """Instructions:\n- Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.\n- The generated query should return all of the information asked in the question without any missing or extra information.\n- Before generating the final SQL query, please think through the steps of how to write the query."""
        question_raw = question_raw.replace(task_msg, '')

        task_msg2 = "Your task is to understand the schema and generate a valid SQL query to answer the question."
        new_task_msg2 = "Your task is to understand the schema and determine which tables are needed to generate the SQL queries that answer the questions."
        question_raw = question_raw.replace(task_msg2, new_task_msg2)

    if template_type == 'think':
        omni_output_format = """Output Format:\nIn your answer, please enclose the generated SQL query in a code block:\n```sql\n-- Your SQL query\n```\n\nTake a deep breath and think step by step to find the correct SQL query.\n"""
        question_raw = question_raw.replace(omni_output_format, '')

        sql_output_msg = """Show your work in <think> </think> tags. And return the final SQLite SQL query that starts with keyword `SELECT` in <answer> </answer> tags, \
for example <answer>SELECT AVG(rating_score) FROM movies</answer>. """

        if current_selection_vote_predict is not None and prompt_mode == "vote":
            sql_output_msg = """Show your work in <think> </think> tags. And return the final selection answer 'A' or 'B' in <answer> </answer> tags, \
for example <answer>A</answer>. """
        elif prompt_mode == "table":
            sql_output_msg = """Show your work in <think> </think> tags. And return the selected tables separate by comma in <answer> </answer> tags, \
for example <answer>Table1, Table2, Table3 , ...</answer>. """

        prefix = f"""You first thinks about the reasoning process in the mind and then provides the user with the answer.\n\
{question_raw}

Output Format:
{sql_output_msg} 

Let me solve this step by step."""


    else:
        prefix = dp[instruction_key] + dp.get("input", "")

        # add selection vote
        if current_selection_vote_predict is not None and prompt_mode == "vote":
            omni_output_format = """Output Format:\nIn your answer, please enclose the generated SQL query in a code block:\n```sql\n-- Your SQL query\n```\n\nTake a deep breath and think step by step to find the correct SQL query.\n"""
            selection_output_format = """Output Format:\nIn your answer, please enclose the final selection answer 'A' or 'B' in <answer> </answer> tags\n\nTake a deep breath and think step by step to find the correct candidate.\n"""
            prefix = prefix.replace(omni_output_format, selection_output_format)

    # add few shot
    task_msg = "Database Schema:"
    new_task_msg = "Database Schema:"
    few_shot_msg = ""
    if current_few_shot is not None and len(current_few_shot) > 0:
        few_shot_msg = CommonUtils.build_few_shot_example_msg(current_few_shot)
        new_task_msg = f"{few_shot_msg}\n\n{new_task_msg}"
        prefix = prefix.replace(task_msg, new_task_msg)

    return prefix


def build_prompt(raw_input_dataset: List[Dict],
                 prompt_name: str,
                 link_table_results=None,
                 few_shot_results=None,
                 few_shot_num=0,
                 predict_sql_results=None,
                 selection_vote_predict_sql_results=None,
                 is_train=False,
                 shuffle_ab=False,
                 prompt_mode="merge",
                 raw_data: List[Dict] = None,
                 db_path=None,
                 db_full_schema_config=None,
                 max_model_len=None,
                 view_ddls=None,
                 view_list=None,
                 history_data=None,
                 ):
    new_input_dataset = []
    for index, item in enumerate(raw_input_dataset):
        raw_one = None
        if raw_data:
            raw_one = raw_data[index]
            db_id = raw_one['db_id']
            item['id'] = index
            item['db_id'] = db_id
            target_sql = raw_one.get('SQL', raw_one.get('output_seq', raw_one.get('output', '')))

        current_few_shot = None
        if few_shot_results is not None and few_shot_num > 0:
            all_current_few_shot = few_shot_results[index]
            current_few_shot = all_current_few_shot[:few_shot_num]

        current_predict = None
        if predict_sql_results is not None and isinstance(predict_sql_results, dict):
            current_predict = predict_sql_results[index]

        current_selection_vote_predict = None
        if selection_vote_predict_sql_results is not None \
                and isinstance(selection_vote_predict_sql_results, dict):
            if index not in selection_vote_predict_sql_results:
                continue
            current_selection_vote_predict = selection_vote_predict_sql_results[index]

            if shuffle_ab and random.choice([0, 1]) == 1:
                old_current_selection_vote_predict = deepcopy(current_selection_vote_predict)
                current_selection_vote_predict['sql1'] = old_current_selection_vote_predict['sql2']
                current_selection_vote_predict['sql2'] = old_current_selection_vote_predict['sql1']
                current_selection_vote_predict['res1'] = old_current_selection_vote_predict['res2']
                current_selection_vote_predict['res2'] = old_current_selection_vote_predict['res1']
                current_selection_vote_predict['sql1_correctness'] = old_current_selection_vote_predict[
                    'sql2_correctness']
                current_selection_vote_predict['sql2_correctness'] = old_current_selection_vote_predict[
                    'sql1_correctness']

            item['id'] = current_selection_vote_predict['id']
            item['db_id'] = current_selection_vote_predict['db_id']
            item['vote_top2_correctness'] = current_selection_vote_predict['vote_top2_correctness']
            item['sql1_correctness'] = current_selection_vote_predict['sql1_correctness']
            item['sql2_correctness'] = current_selection_vote_predict['sql2_correctness']

            if prompt_mode == "vote":
                target = 'A' if current_selection_vote_predict['sql1_correctness'] == 1 else 'B'
            else:
                if current_selection_vote_predict['sql1_correctness'] == 1:
                    target = current_selection_vote_predict['sql1']
                elif current_selection_vote_predict['sql2_correctness'] == 1:
                    target = current_selection_vote_predict['sql2']
                else:
                    pass

                target = target_sql
            item['output'] = target

        prompt = make_prefix(item,
                             template_type=prompt_name,
                             current_few_shot=current_few_shot,
                             current_selection_vote_predict=current_selection_vote_predict,
                             prompt_mode=prompt_mode)
        current_predict_tables = link_table_results[index] if link_table_results is not None else []

        # --cluster_filter: replace Stage 1 tables with the cluster-union tables stored
        # by retrieve_history_for_questions. Falls back to Stage 1 tables if empty.
        if history_data:
            _h_entry = history_data.get(str(index), None)
            if isinstance(_h_entry, dict) and _h_entry.get("cluster_tables"):
                current_predict_tables = list(_h_entry["cluster_tables"])

        new_prompt = CommonUtils.build_link_table_from_ddl(prompt, current_predict_tables)

        new_prompt = CommonUtils.build_revision_prompt(new_prompt, predict_result=current_predict)
        if prompt_mode == "vote":
            new_prompt = CommonUtils.build_selection_vote_prompt(new_prompt,
                                                                 predict_result=current_selection_vote_predict)
        elif prompt_mode == "merge":
            new_prompt = CommonUtils.build_merge_generate_prompt(new_prompt,
                                                                 predict_result=current_selection_vote_predict)
            # Safeguard: if build_merge_generate_prompt's internal filtering failed
            # (common with renamed tables), re-apply Stage 1 table filtering
            if current_predict_tables:
                new_prompt = CommonUtils.build_link_table_from_ddl(new_prompt, current_predict_tables)

        # Inject views + history AFTER all prompt modifications (Stage 2+3 only)
        if prompt_mode != "table":
            # Build the injection text (views + history + paths)
            view_injection_text = ""
            history_injection_text = ""

            # --- VIEWS ---
            if view_ddls and view_list:
                # Use Stage 1 predicted tables for view matching
                tables_for_views = current_predict_tables
                # Fallback for Stage 3: get tables from selection_vote data
                if not tables_for_views and current_selection_vote_predict is not None:
                    tables_for_views = current_selection_vote_predict.get('link_tables', [])
                # Last resort: extract from schema section of prompt
                if not tables_for_views:
                    import re as _re
                    schema_start = new_prompt.find("Database Schema:")
                    schema_end = new_prompt.find("This schema describes the database's structure,")
                    if schema_start > 0 and schema_end > schema_start:
                        schema_section = new_prompt[schema_start:schema_end]
                        tables_for_views = _re.findall(r'CREATE TABLE\s+`?(\w+)`?\s*\(', schema_section)
                        # Filter out view names — only keep base tables
                        view_names_lower = {v.lower() for v in view_list}
                        tables_for_views = [t for t in tables_for_views if t.lower() not in view_names_lower]

                if tables_for_views:
                    from cscsql.service.process.process_single_db import find_matching_views
                    matching_views = find_matching_views(tables_for_views, view_list)
                    if matching_views:
                        view_injection_text = "\n\n".join(view_ddls[v] for v in matching_views if v in view_ddls)

            # --- HISTORY + PATHS ---
            if history_data:
                qid = item.get('id', index)
                h_entry = history_data.get(str(qid), history_data.get(str(index), None))
                if h_entry:
                    if isinstance(h_entry, dict):
                        history_sqls = h_entry.get("history_sqls", "")
                        paths_str = h_entry.get("paths_str", None)
                    else:
                        history_sqls = h_entry
                        paths_str = None

                    if history_sqls:
                        history_injection_text = f"History SQLs:\n{history_sqls}\n"
                        if paths_str:
                            history_injection_text += f"History Query Paths:\n{paths_str}\n\n"

            # --- INJECT INTO PROMPT ---
            if view_injection_text:
                end_marker = "This schema describes the database's structure,"
                marker_pos = new_prompt.find(end_marker)
                if marker_pos > 0:
                    new_prompt = new_prompt[:marker_pos] + view_injection_text + "\n\n" + new_prompt[marker_pos:]

            if history_injection_text:
                insert_marker = "Instructions:"
                marker_pos = new_prompt.rfind(insert_marker)
                if marker_pos > 0:
                    new_prompt = new_prompt[:marker_pos] + history_injection_text + new_prompt[marker_pos:]

        if prompt_mode == "table":
            db_uri = CommonUtils.get_db_path(db_root=db_path, db_id=db_id)
            schema_key = "single_db" if db_path.endswith(".sqlite") else db_id
            db_full_schema = db_full_schema_config[schema_key]

            link_column_names, link_tables, normal_tentative_schema = CommonUtils.extract_merge_schema_from_sql(
                sqls=[target_sql],
                db_uri=db_uri,
                db_full_schema=db_full_schema,
                question_id=index)
            item['output'] = link_tables
            item.pop('output_seq')

        item["input_seq"] = new_prompt
        new_input_dataset.append(item)

    return new_input_dataset


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--pretrained_model_name_or_path", type=str, default="/fs/fast/u2021000902/previous_nvme/xxx")
    parser.add_argument("--input_file", type=str, help="the input file path (prompts)")
    parser.add_argument("--output_file", type=str, help="the output file path (results)")
    parser.add_argument("--tensor_parallel_size", type=int, help="the number of used GPUs", default=4)
    parser.add_argument("--gpu_memory_utilization", type=float, help="gpu_memory_utilization", default=0.95)
    parser.add_argument("--n", type=int, help="the number of generated responses", default=4)
    parser.add_argument("--seed", type=int, help="seed", default=42)
    parser.add_argument("--temperature", type=float, help="temperature of llm's sampling", default=1.0)
    parser.add_argument("--prompt_name", type=str, help="prompt name", default='')
    parser.add_argument("--link_tables", type=str, default=None, help="predict sql path", )
    parser.add_argument("--few_shot_num", type=int, default=0, help="few shot num")
    parser.add_argument("--db_path", type=str, help="database path")
    parser.add_argument("--gold_file", type=str, help="gold sql path", default="none")
    parser.add_argument("--gen_sqls", type=str, default="", help="gen_sqls")
    parser.add_argument("--selection_vote", type=str, default="none", help="selection_vote")
    parser.add_argument("--prompt_mode", type=str, default="merge", help="prompt_mode")
    parser.add_argument("--max_lora_rank", type=int, default=64, help="max_lora_rank")
    parser.add_argument("--shuffle_ab", type=int, default=0, help="shuffle_ab")
    parser.add_argument("--system_prompt", type=str, default="default", help="system_prompt")
    parser.add_argument("--log_dir", type=str, default=None, help="directory to log prompts and responses per question")
    parser.add_argument("--quantization", type=str, default=None, help="quantization method (e.g. bitsandbytes)")
    parser.add_argument("--api_base", type=str, default=None, help="remote vLLM server URL (e.g. http://192.168.1.100:8000/v1). If set, uses remote mode.")
    parser.add_argument("--api_model", type=str, default=None, help="model name on the remote server (for API calls)")
    parser.add_argument("--view_ddls_file", type=str, default=None, help="path to view DDLs JSON file for view injection")
    parser.add_argument("--history_dir", type=str, default=None, help="directory with precomputed history (embeddings, data, clusters)")
    parser.add_argument("--history_k", type=int, default=5, help="top-k history queries to retrieve")
    parser.add_argument("--use_clusters", action="store_true", help="use cluster-based history filtering")
    parser.add_argument("--history_rename", action="store_true", help="history uses renamed SQL columns")
    parser.add_argument("--history_view", action="store_true", help="history includes view SQL columns")
    parser.add_argument("--dataset", type=str, default="bird", choices=["bird", "spider"], help="dataset name (affects table/view/SQL column lookups)")
    parser.add_argument("--test_offset", type=int, default=0, help="offset into link_table_results when using --test with --stage1_from")
    parser.add_argument("--cluster_filter", action="store_true",
                        help="After Stage 1 + cluster matching, replace per-question predicted tables with the union of tables across matched clusters (requires --use_clusters). Downstream schema DDL filter and view matching use this expanded set.")

    opt = parser.parse_args()
    print(opt)
    shuffle_ab = False if opt.shuffle_ab in ['0', 0] else True
    is_train = True if str(opt.db_path).find("train") > -1 else False

    max_model_len = 32768
    if is_train:
        max_model_len = 12000
    max_output_len = 1024  # (max_input_len + max_output_len) must <= max_model_len

    db_full_schema_config, db_sample_config = CommonUtils.get_all_db_full_schema_and_sample(db_root=opt.db_path)

    # get few shot example
    few_shot_results = None
    if opt.few_shot_num > 0:
        few_shot_results = CommonUtils.get_few_shot_list()

    predict_sql_results = build_execute_sql_result(opt.gen_sqls, db_path=opt.db_path)
    if opt.gen_sqls is not None and opt.gen_sqls not in ["none"] and predict_sql_results is None:
        print(f"predict_sql_results is None, please check your gen_sqls file, file name: {opt.gen_sqls}")

    selection_vote_predict_sql_results, all_predict_results = build_selection_vote_execute_sql_result(
        opt.selection_vote,
        db_path=opt.db_path,
        is_train=False,
        prompt_mode=opt.prompt_mode,
        input_file=opt.input_file)

    if opt.selection_vote is not None \
            and opt.selection_vote not in ["none"] \
            and selection_vote_predict_sql_results is None:
        print("selection_vote_predict_sql_results is None, "
              "please check your selection_vote file, file name: {opt.selection_vote}")

    parse_mode = 'sql'
    if selection_vote_predict_sql_results is not None and opt.prompt_mode == 'vote':
        parse_mode = 'selection_vote'
    elif opt.prompt_mode == 'table':
        parse_mode = 'table'

    raw_input_dataset = FileUtils.load_json(opt.input_file)
    if opt.db_path.endswith(".sqlite"):
        raw_data = raw_input_dataset  # single-db mode: input file has all needed fields
    else:
        raw_data = FileUtils.load_json(str(opt.db_path).replace("_databases", ".json"))

    link_table_results = CommonUtils.read_link_table(link_table_files=opt.link_tables,
                                                     is_train=is_train)

    # Slice link_table_results if test_offset is set (for --test with --stage1_from)
    if link_table_results and opt.test_offset > 0:
        n_input = len(raw_input_dataset)
        link_table_results = link_table_results[opt.test_offset:opt.test_offset + n_input]
        print(f"Sliced link_table_results to offset {opt.test_offset}, length {len(link_table_results)}")

    # Load view DDLs if provided
    loaded_view_ddls = None
    loaded_view_list = None
    if opt.view_ddls_file and os.path.exists(opt.view_ddls_file):
        loaded_view_ddls = FileUtils.load_json(opt.view_ddls_file)
        loaded_view_list = list(loaded_view_ddls.keys())
        print(f"Loaded {len(loaded_view_list)} view DDLs from {opt.view_ddls_file}")

    # Retrieve history at inference time (uses Stage 1 results for cluster filtering)
    loaded_history = None
    if opt.history_dir and os.path.exists(opt.history_dir) and opt.prompt_mode != "table":
        input_questions = [item.get("input_seq", item.get("question", "")) for item in raw_input_dataset]
        # Extract just the question text from the prompt
        for i, q in enumerate(input_questions):
            if "Question:" in q:
                q_start = q.find("Question:") + len("Question:")
                q_end = q.find("\n", q_start + 1)
                if q_end > q_start:
                    input_questions[i] = q[q_start:q_end].strip()

        loaded_history = retrieve_history_for_questions(
            history_dir=opt.history_dir,
            input_questions=input_questions,
            link_table_results=link_table_results,
            history_k=opt.history_k,
            use_clusters=opt.use_clusters,
            rename=opt.history_rename,
            view=opt.history_view,
            dataset=opt.dataset,
            cluster_filter=opt.cluster_filter,
        )

    # Validate: cluster_filter requires use_clusters
    if opt.cluster_filter and not opt.use_clusters:
        raise ValueError("--cluster_filter requires --use_clusters")

    input_dataset = build_prompt(raw_input_dataset,
                                 prompt_name=opt.prompt_name,
                                 link_table_results=link_table_results,
                                 few_shot_results=few_shot_results,
                                 few_shot_num=opt.few_shot_num,
                                 predict_sql_results=predict_sql_results,
                                 selection_vote_predict_sql_results=selection_vote_predict_sql_results,
                                 shuffle_ab=shuffle_ab,
                                 is_train=is_train,
                                 prompt_mode=opt.prompt_mode,
                                 raw_data=raw_data,
                                 db_path=opt.db_path,
                                 db_full_schema_config=db_full_schema_config,
                                 max_model_len=max_model_len,
                                 view_ddls=loaded_view_ddls,
                                 view_list=loaded_view_list,
                                 history_data=loaded_history,
                                 )

    use_remote = opt.api_base is not None

    # --- Tokenizer + config (needed for both modes) ---
    model_path = opt.pretrained_model_name_or_path
    enable_lora = False
    lora_request = None

    if use_remote:
        # Remote mode: use tokenizer from HF cache for chat template formatting
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        stop_token_ids = [151645]  # Qwen2.5 <|im_end|>
        print(f"REMOTE MODE: api_base={opt.api_base}")
    else:
        # Local mode: full model loading
        from transformers import AutoTokenizer, AutoConfig
        from vllm import SamplingParams
        from vllm.lora.request import LoRARequest

        lora_config_path = os.path.join(model_path, "adapter_config.json")
        if os.path.exists(lora_config_path):
            enable_lora = True
            lora_config = FileUtils.load_json(lora_config_path)
            model_path = lora_config.get("base_model_name_or_path", model_path)
            epoch = 1
            try:
                epoch = int(str(opt.pretrained_model_name_or_path).split("-")[-1])
            except:
                pass
            lora_request = LoRARequest(f"sft_adapter_{epoch}", epoch, opt.pretrained_model_name_or_path)
            print(f"use lora: r={lora_config['r']} lora_alpha={lora_config['lora_alpha']}")

        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
        stop_token_ids = config.eos_token_id if hasattr(config, "eos_token_id") else None
        if isinstance(stop_token_ids, int):
            stop_token_ids = [stop_token_ids]

    print("parse_mode:", parse_mode)
    print("max_model_len:", max_model_len)
    print("temperature:", opt.temperature)
    print("n:", opt.n)
    print("few_shot_num:", opt.few_shot_num)
    print("stop_token_ids:", stop_token_ids)

    # --- Build chat prompts ---
    system_prompt = "You are a helpful AI Assistant that provides well-reasoned and detailed responses. You first think about the reasoning process as an internal monologue and then provide the user with the answer. Respond in the following format: <think>\n...\n</think>\n<answer>\n...\n</answer>"

    chat_prompts = []
    for data in input_dataset:
        messages = []
        if opt.system_prompt == "none":
            system_prompt = ""
        elif opt.system_prompt == "default":
            system_prompt = system_prompt
        else:
            system_prompt = opt.system_prompt

        if len(system_prompt) > 10:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": data["input_seq"]})
        res = tokenizer.apply_chat_template(messages,
                                            add_generation_prompt=True,
                                            tokenize=False)

        chat_prompts.append(res)

    if chat_prompts:
        print(f"prompt[0]:")
        print(chat_prompts[0][:500] + "..." if len(chat_prompts[0]) > 500 else chat_prompts[0])
    print(f"Total prompts: {len(chat_prompts)}")

    # --- Generate ---
    if use_remote:
        api_model = opt.api_model or opt.pretrained_model_name_or_path
        all_responses = generate_remote(
            api_base=opt.api_base,
            model_name=api_model,
            chat_prompts=chat_prompts,
            n=opt.n,
            temperature=opt.temperature,
            max_tokens=max_output_len,
            stop_token_ids=stop_token_ids,
        )
    else:
        from vllm import SamplingParams
        sampling_params = SamplingParams(
            temperature=opt.temperature,
            max_tokens=max_output_len,
            n=opt.n,
            stop_token_ids=stop_token_ids
        )
        all_responses = generate_local(
            opt=opt,
            model_path=model_path,
            chat_prompts=chat_prompts,
            sampling_params=sampling_params,
            enable_lora=enable_lora,
            lora_request=lora_request,
            max_model_len=max_model_len,
        )

    results = []
    for data, responses in zip(input_dataset, all_responses):
        sqls = [parse_response(response, mode=parse_mode) for response in responses]

        data["responses"] = responses
        data["pred_sqls"] = sqls
        results.append(data)

    print(f"responses[0]:")
    print(results[0]["responses"][0])
    print(f"pred_sqls[0]:")
    print(results[0]["pred_sqls"][0])

    # Log prompts and responses per question
    stage_labels = {
        "table": "STAGE 1/3: Table Linking",
        "sql": "STAGE 2/3: SQL Generation",
        "selection_vote": "STAGE 3/3: SQL Merge/Correction",
    }
    # sql_merge also uses parse_mode="sql", distinguish by selection_vote being set
    if parse_mode == "sql" and opt.selection_vote not in [None, "none"]:
        current_stage_label = "STAGE 3/3: SQL Merge/Correction"
    else:
        current_stage_label = stage_labels.get(parse_mode, f"STAGE: {parse_mode}")

    if opt.log_dir:
        os.makedirs(opt.log_dir, exist_ok=True)
        for data, prompt in zip(results, chat_prompts):
            qid = data.get("id", 0)
            log_file = os.path.join(opt.log_dir, f"q{qid}.txt")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"{current_stage_label} | Question ID: {qid}\n")
                f.write(f"{'='*80}\n\n")
                f.write(f"--- PROMPT ---\n{prompt}\n\n")
                f.write(f"{'-'*60}\n")
                f.write(f"LLM RESPONSES ({len(data.get('responses', []))} completions)\n")
                f.write(f"{'-'*60}\n\n")
                for i, resp in enumerate(data.get("responses", [])):
                    parsed = data.get("pred_sqls", [""])[i] if i < len(data.get("pred_sqls", [])) else ""
                    f.write(f"--- RESPONSE {i+1}/{len(data['responses'])} ---\n{resp}\n")
                    f.write(f"--- PARSED ---\n{parsed}\n\n")

    if all_predict_results and len(all_predict_results) == len(raw_data):
        infer_ids = [item['id'] for item in results]
        for index, item in enumerate(all_predict_results):
            if item['id'] not in infer_ids:
                new_item = deepcopy(item)
                new_item['mode'] = "major_vote"
                new_item['pred_sqls'] = [item['sql'] for _ in range(opt.n)]
                new_item['responses'] = new_item['pred_sqls']
                results.append(new_item)

    results.sort(key=lambda x: int(x['id']))
    FileUtils.dump_json(opt.output_file, results)

    if parse_mode == "sql":
        vote_result = run_eval_major_vote(gold_file=opt.gold_file,
                            pred_file=opt.output_file,
                            db_path=opt.db_path,
                            config=opt.__dict__,
                            input_file=opt.input_file)

        # Log voting results
        if opt.log_dir and vote_result:
            vote_file = opt.output_file[:-5] + "_pred_major_voting_sqls.json"
            if os.path.exists(vote_file):
                voted_sqls = FileUtils.load_json(vote_file)
                for data, voted_sql in zip(results, voted_sqls):
                    qid = data.get("id", 0)
                    log_file = os.path.join(opt.log_dir, f"q{qid}.txt")
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"{'-'*60}\n")
                        f.write(f"VOTING RESULT ({current_stage_label})\n")
                        f.write(f"{'-'*60}\n")
                        f.write(f"Winner: {voted_sql}\n\n")

    if parse_mode == "table":
        # Log table linking voting result (aggregate predicted tables per question)
        if opt.log_dir:
            for data in results:
                qid = data.get("id", 0)
                all_tables = []
                for pred in data.get("pred_sqls", []):
                    if isinstance(pred, list):
                        all_tables.extend(pred)
                # Most frequent tables across all completions
                from collections import Counter
                table_counts = Counter(all_tables)
                voted_tables = sorted(table_counts.keys(), key=lambda t: -table_counts[t])
                log_file = os.path.join(opt.log_dir, f"q{qid}.txt")
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"{'-'*60}\n")
                    f.write(f"VOTING RESULT (STAGE 1/3: Table Linking)\n")
                    f.write(f"{'-'*60}\n")
                    f.write(f"Table votes: {dict(table_counts.most_common())}\n")
                    f.write(f"Selected tables: {voted_tables}\n\n")

        if len(opt.gold_file) > 10:
            run_eval_major_vote_table(gold_file=opt.gold_file,
                                      pred_file=opt.output_file,
                                      db_path=opt.db_path,
                                      config=opt.__dict__,
                                      input_file=opt.input_file)
