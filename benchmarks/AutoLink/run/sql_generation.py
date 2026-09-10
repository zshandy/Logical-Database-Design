import os
import json
import time
import threading
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple
from openai import OpenAI
from config import *
from tqdm import tqdm
from ldd_runtime import ArmContext, deepseek_client, reasoning_of

class Config:
    INITIAL_RETRY_DELAY = 1
    MAX_RETRY_DELAY = 30

class DataLoader:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.data = None
        return cls._instance

    def load(self, data_file: str) -> Dict:
        if self.data is None:
            with open(data_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        return self.data

class SQLGenerator:
    def __init__(self, log_path: str = ""):
        self.client = deepseek_client()
        self.loader = DataLoader()
        # needed to resolve the arm (history + join-path blocks, question set)
        self.log_path = log_path

    def generate(self, instance_id: str, info: Dict, schema: str) -> Dict:
        question = info["question"]

        if instance_id.startswith("bq"):
            sql_type = BIGQUERY_DIALECT_OPTIMIZATION_SQL_GEN
            dialect = "BigQuery"
        elif instance_id.startswith("sf"):
            sql_type = SNOWFLAKE_DIALECT_OPTIMIZATION_SQL_GEN
            dialect = "SnowFlake"
        elif instance_id.startswith("local"):
            sql_type = SQLITE_DIALECT_OPTIMIZATION_SQL_GEN
            dialect = "SQLite"
        else:
            sql_type = ""
            dialect = "Unknown"

        prompt = SQL_GENERATION.replace("{PROMPT}", schema)
        prompt = prompt.replace("{QUESTION}", question)
        prompt = prompt.replace("{SQL_DIALECT_OPTIMIZATION}", sql_type)
        prompt = prompt.replace("{SQL_TYPE}", dialect)
        # History SQLs + Common Join Paths, in LDD's block style
        ctx = ArmContext.get(self.log_path)
        prompt = prompt.replace("{LDD_BLOCKS}", ctx.extra_blocks(
            instance_id, int(info.get("row_index", -1)), question))

        messages = [
            {"role": "user", "content": prompt}
        ]
        
        attempt = 0
        while True:
            try:
                response = self.client.chat.completions.create(
                    model="deepseek-reasoner",
                    messages=messages
                )
                reasoning_content = reasoning_of(response.choices[0].message)
                model_output = response.choices[0].message.content

                return {
                    "output": model_output,
                    "think": reasoning_content
                }

            except Exception as e:
                attempt += 1
                delay = min(
                    Config.INITIAL_RETRY_DELAY * (2 ** (attempt - 1)),
                    Config.MAX_RETRY_DELAY
                )
                print(
                    f"[Retry {attempt}] API call failed for {instance_id}, "
                    f"retrying in {delay}s"
                )
                time.sleep(delay)

def collect_tasks(schema_dir: str, log_path: str, task: str, num_candidates: int) -> List[Tuple[str, int]]:
    instance_ids = [f[:-4] for f in os.listdir(schema_dir) if f.endswith(".txt")]
    tasks = []
    for cid in range(num_candidates):
        for iid in instance_ids:
            out_file = f"{log_path}/sql_gen/{task}_sql_generation_{cid}/{iid}.txt"
            if not os.path.exists(out_file):
                tasks.append((iid, cid))
    return tasks

def run_task(
    generator: SQLGenerator,
    data: Dict,
    schema_dir: str,
    log_path: str,
    task: str,
    instance_id: str,
    candidate_idx: int
):
    schema_path = f"{schema_dir}/{instance_id}.txt"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = f.read()

    result = generator.generate(instance_id, data[instance_id], schema)

    os.makedirs(f"{log_path}/sql_gen/{task}_sql_generation_{candidate_idx}", exist_ok=True)
    os.makedirs(f"{log_path}/sql_gen/{task}_reasoning_{candidate_idx}", exist_ok=True)

    with open(f"{log_path}/sql_gen/{task}_sql_generation_{candidate_idx}/{instance_id}.txt", "w", encoding="utf-8") as f:
        f.write(result["output"])

    with open(f"{log_path}/sql_gen/{task}_reasoning_{candidate_idx}/{instance_id}.txt", "w", encoding="utf-8") as f:
        f.write(result["think"])

def sql_clean(log_path: str, task: str, candidate_idx: int):
    in_dir = f"{log_path}/sql_gen/{task}_sql_generation_{candidate_idx}"
    out_dir = f"{log_path}/sql_gen/{task}_sql_{candidate_idx}"
    os.makedirs(out_dir, exist_ok=True)

    for name in os.listdir(in_dir):
        if not name.endswith(".txt"):
            continue
        iid = name[:-4]
        with open(f"{in_dir}/{name}", "r", encoding="utf-8") as f:
            content = f.read()
        end = content.rfind("```")
        start = content.rfind("```sql", 0, end)
        if start != -1 and end != -1 and end > start:
            sql = content[start + 6:end].strip()
        else:
            sql = content.strip()
        with open(f"{out_dir}/{iid}.sql", "w", encoding="utf-8") as f:
            f.write(sql)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_workers", type=int, default=8)
    parser.add_argument("--num_candidates", type=int, default=3)
    parser.add_argument("--data_file", type=str, required=True)
    parser.add_argument("--schema_dir", type=str, required=True)
    parser.add_argument("--log_path", type=str, required=True)
    parser.add_argument("--task", type=str, default="r1_lite")
    args = parser.parse_args()

    os.makedirs(args.log_path, exist_ok=True)

    loader = DataLoader()
    data = loader.load(args.data_file)

    generator = SQLGenerator(args.log_path)
    tasks = collect_tasks(args.schema_dir, args.log_path, args.task, args.num_candidates)

    print(f"Total pending tasks: {len(tasks)}")

    with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
        futures = [
            executor.submit(
                run_task,
                generator,
                data,
                args.schema_dir,
                args.log_path,
                args.task,
                iid,
                cid
            )
            for iid, cid in tasks
        ]

        n_failed = 0
        for fut in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="SQL Generation",
            dynamic_ncols=True
        ):
            # The original loop discarded futures without calling result(), so a
            # failing candidate silently produced no file and only surfaced later
            # as a FileNotFoundError in sql_clean. Surface it here instead.
            try:
                fut.result()
            except Exception as e:
                n_failed += 1
                if n_failed <= 5:
                    print(f"  generation task failed: {type(e).__name__}: {e}")
        if n_failed:
            print(f"  WARNING: {n_failed}/{len(futures)} generation task(s) failed")


    print("SQL generation finished")

    with ThreadPoolExecutor(max_workers=args.num_candidates) as executor:
        futures = []
        for cid in range(args.num_candidates):
            futures.append(executor.submit(sql_clean, args.log_path, args.task, cid))
        for f in as_completed(futures):
            f.result()

    print("SQL cleaning finished")

if __name__ == "__main__":
    main()
