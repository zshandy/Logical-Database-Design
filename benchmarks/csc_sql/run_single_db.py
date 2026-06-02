"""
End-to-end entry point for running CSC-SQL pipeline with a single database.

Usage:
    python run_single_db.py \
        --csv_path data/bird_dev.csv \
        --db_path data/merged.sqlite \
        --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
        --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
        --output_dir outputs

CSV must have columns: question, db_id, SQL
(db_id is kept for compatibility but ignored — all queries run against the single DB)
"""
import os
import argparse

from cscsql.utils.time_utils import TimeUtils

RUN_TIME = TimeUtils.now_str_short()


def main():
    parser = argparse.ArgumentParser(description="CSC-SQL pipeline with single database")

    # Required
    parser.add_argument("--csv_path", type=str, default=None,
                        help="Path to CSV (question, db_id, SQL). If omitted, defaults to "
                             "../../csvs/nl2sql_{dataset}.csv (relative to this script).")
    parser.add_argument("--db_path", type=str, default=None,
                        help="Path to single SQLite database file. If omitted, defaults to "
                             "../../databases/merged_{dataset}.sqlite (relative to this script).")
    parser.add_argument("--model_table_link", type=str, default=None,
                        help="Table linking model (defaults to model_sql_generate)")
    parser.add_argument("--model_sql_generate", type=str, required=True, help="SQL generation model")
    parser.add_argument("--model_sql_merge", type=str, required=True, help="SQL merge/correction model")

    # Optional
    parser.add_argument("--output_dir", type=str, default="outputs")
    parser.add_argument("--run_time", type=str, default=None)
    parser.add_argument("--visible_devices", type=str, default="0")
    parser.add_argument("--tensor_parallel_size", type=int, default=1)
    parser.add_argument("--gpu_memory_utilization", type=float, default=0.90)
    parser.add_argument("--seed", type=int, default=42)

    # Table linking config
    parser.add_argument("--n_table_link", type=int, default=4, help="sampling count for table linking")
    parser.add_argument("--temperature_table_link", type=float, default=0.8)

    # Pipeline config
    parser.add_argument("--eval_step", type=str, default="pipeline",
                        help="pipeline stage: pipeline (all 3 stages), sql_pipeline (generate+merge), sql_generate, sql_merge")
    parser.add_argument("--eval_mode", type=str, default="major_voting",
                        help="eval mode: major_voting, greedy_search, all")
    parser.add_argument("--n_sql_generate", type=int, default=8, help="sampling count for SQL generation")
    parser.add_argument("--temperature_sql_generate", type=float, default=0.8)
    parser.add_argument("--n_sql_merge", type=int, default=4, help="sampling count for SQL merge")
    parser.add_argument("--temperature_sql_merge", type=float, default=0.8)
    parser.add_argument("--prompt_name", type=str, default="think")

    # BM25
    parser.add_argument("--bm25_index_path", type=str, default=None,
                        help="Directory for BM25 index (skip BM25 if not set)")
    parser.add_argument("--value_limit_num", type=int, default=2, help="Sampled values per column")
    parser.add_argument("--rename", action="store_true",
                        help="Use renamed tables instead of original table names")
    parser.add_argument("--mapping_path", type=str, default=None,
                        help="Path to name-mapping JSON. Only consulted when --rename is set. "
                             "If omitted, defaults to ../../mapping_files/name_mapping_{dataset}.json "
                             "(relative to this script).")
    parser.add_argument("--view", action="store_true",
                        help="Inject view DDLs into Stage 2+3 prompts")
    parser.add_argument("--dataset", type=str, default="bird", choices=["bird", "spider"],
                        help="Dataset: 'bird' or 'spider' (controls which table/view lists and SQL columns to use)")

    # History
    parser.add_argument("--history", action="store_true",
                        help="Enable history mode. When set with no --history_path, defaults to "
                             "../../csvs/sample_{dataset}.csv (relative to this script). "
                             "Passing --history_path implicitly enables history mode.")
    parser.add_argument("--history_path", type=str, default=None,
                        help="Path to history CSV with question + SQL columns. Implies --history "
                             "when provided. If --history is set without this flag, defaults to "
                             "../../csvs/sample_{dataset}.csv.")
    parser.add_argument("--history_k", type=int, default=3,
                        help="Number of top-k similar history queries to retrieve")
    parser.add_argument("--cluster", action="store_true",
                        help="Use cluster-based filtering of history queries using Stage 1 results")
    parser.add_argument("--cluster_filter", action="store_true",
                        help="After Stage 1 + cluster matching, replace Stage 1 predicted tables with the union of tables across matched clusters for downstream stages. Requires --cluster.")
    parser.add_argument("--stage0_from", type=str, default=None,
                        help="Path to a prior run's folder whose Stage 1 output will be used to pre-prune the schema BEFORE this run's Stage 1. "
                             "Per-question, the prior Stage 1 tables are matched to clusters, and the cluster-union is used to filter the schema passed to this Stage 1. "
                             "Requires --cluster_filter, --cluster, --history_path. Cannot be combined with an explicit --stage1_from. Forces --stage1_from fresh internally.")
    parser.add_argument("--run_eval", action="store_true",
                        help="Run gold-SQL execution for EX accuracy metrics. Off by default — predicted SQLs are still generated and voted without this; turn it on only when you actually want EX accuracy printed.")

    # Quantization
    parser.add_argument("--quantization", type=str, default="bitsandbytes",
                        help="quantization method: bitsandbytes (INT8), None for bf16")

    # Remote API mode (optional — if not set, runs locally)
    parser.add_argument("--api_base_generate", type=str, default=None,
                        help="Remote vLLM server for Stage 1+2 (e.g. http://192.168.1.100:8000/v1)")
    parser.add_argument("--api_base_merge", type=str, default=None,
                        help="Remote vLLM server for Stage 3 (e.g. http://192.168.1.100:8001/v1)")

    # Testing
    parser.add_argument("--test", type=str, default=None,
                        help="Row slice for testing: '5' for first 5 rows, '10:15' for rows 10-14")

    # Reuse previous outputs
    parser.add_argument("--stage1_from", type=str, default="auto",
                        help="'auto' (default): outputs/<dataset>/rename_linking if --rename else outputs/<dataset>/base_linking. "
                             "'fresh': run Stage 1 from scratch. Or a path to reuse (e.g. outputs/bird/base_linking)")

    # Preprocessing only
    parser.add_argument("--skip_preprocess", action="store_true", help="Skip preprocessing (use existing input_file)")
    parser.add_argument("--input_file", type=str, default=None, help="Pre-existing processed JSON (skips preprocessing)")

    args = parser.parse_args()

    # Auto-resolve csv_path / db_path / history_path from --dataset when not explicitly provided.
    # This script is expected to run from .../benchmarks/csc_sql/, so the shared data folders
    # (databases/, mapping_files/, csvs/) sit two levels up.
    _this_dir = os.path.dirname(os.path.abspath(__file__))                   # .../benchmarks/csc_sql/
    _ldd_root = os.path.abspath(os.path.join(_this_dir, "..", ".."))         # .../Logical-Database-Design/
    if args.csv_path is None:
        args.csv_path = os.path.join(_ldd_root, "csvs", f"nl2sql_{args.dataset}.csv")
        print(f"[run_single_db] --csv_path auto-resolved to {args.csv_path}")
    if args.db_path is None:
        args.db_path = os.path.join(_ldd_root, "databases", f"merged_{args.dataset}.sqlite")
        print(f"[run_single_db] --db_path auto-resolved to {args.db_path}")

    # History gating: --history_path implies --history; --history alone uses the default file;
    # neither flag → history mode disabled.
    if args.history_path:
        args.history = True
    elif args.history:
        args.history_path = os.path.join(_ldd_root, "csvs", f"sample_{args.dataset}.csv")
        if not os.path.exists(args.history_path):
            raise FileNotFoundError(
                f"--history requested but default sample file not found at {args.history_path}. "
                f"Pass --history_path explicitly or drop --history."
            )
        print(f"[run_single_db] --history_path auto-resolved to {args.history_path}")
    else:
        args.history_path = None

    for _label, _path in (("--csv_path", args.csv_path), ("--db_path", args.db_path)):
        if not os.path.exists(_path):
            raise FileNotFoundError(
                f"{_label} not found at {_path}. Pass {_label} explicitly."
            )

    # --mapping_path: override the module-level mapping constant for the active dataset.
    if args.mapping_path:
        if not os.path.exists(args.mapping_path):
            raise FileNotFoundError(
                f"--mapping_path {args.mapping_path} does not exist."
            )
        from cscsql.service.process import process_single_db as _pp
        if args.dataset == "bird":
            _pp._BIRD_MAPPING_PATH = args.mapping_path
        else:
            _pp._SPIDER_MAPPING_PATH = args.mapping_path
        print(f"[run_single_db] --mapping_path override: {args.mapping_path}")

    # Validate: --cluster_filter requires --cluster
    if args.cluster_filter and not args.cluster:
        raise ValueError("--cluster_filter requires --cluster")

    # Validate: --stage0_from requires --cluster_filter, --cluster, --history_path
    if args.stage0_from:
        if not args.cluster_filter:
            raise ValueError("--stage0_from requires --cluster_filter")
        if not args.cluster:
            raise ValueError("--stage0_from requires --cluster")
        if not args.history_path:
            raise ValueError("--stage0_from requires --history_path")
        # Mutually exclusive with user-specified --stage1_from (non-default)
        if args.stage1_from not in (None, "auto"):
            raise ValueError("--stage0_from cannot be combined with an explicit --stage1_from; Stage 1 is forced to fresh when stage0 is active")
        # Force Stage 1 to run fresh — the pre-pruned schema is new, prior Stage 1 caches don't apply
        args.stage1_from = "fresh"
        # Validate the stage0 path exists and has the expected file
        stage0_link_file = os.path.join(args.stage0_from, "sampling_think_table_link.json")
        if not os.path.exists(stage0_link_file):
            raise FileNotFoundError(f"--stage0_from path missing sampling_think_table_link.json: {stage0_link_file}")
        print(f"--stage0_from: pre-Stage1 schema pruning enabled, using {stage0_link_file}")

    if args.run_time is None:
        args.run_time = RUN_TIME

    # Dataset-scoped output dir: outputs/<dataset>/<timestamp>/
    dataset_output_dir = os.path.join(args.output_dir, args.dataset)
    run_dir = os.path.join(dataset_output_dir, args.run_time)
    os.makedirs(run_dir, exist_ok=True)

    # Create log directory: log/<run_time>/
    log_dir = os.path.join("log", args.run_time)
    os.makedirs(log_dir, exist_ok=True)
    print(f"Logging prompts/responses to: {log_dir}")

    # Step 1: Preprocess CSV → JSON prompts
    if args.input_file and args.skip_preprocess:
        input_file = args.input_file
        gold_file = input_file.replace(".json", "_gold.sql")
        print(f"Skipping preprocessing, using: {input_file}")
    else:
        input_file = os.path.join(run_dir, "processed_prompts.json")
        gold_file = os.path.join(run_dir, "processed_prompts_gold.sql")

    # Default: skip gold-SQL execution (the slow eval phase). Passing a short path (len<=10)
    # causes pipeline_infer to skip gold-SQL loading and execute_gold_sqls_parallel entirely.
    # Use --run_eval to opt in to EX accuracy printing.
    if not args.run_eval:
        gold_file = "none"
        print("Gold SQL execution skipped by default (use --run_eval to enable EX accuracy metrics)")

        print("=" * 60)
        print("Step 1: Preprocessing CSV → prompts")
        print("=" * 60)

        from cscsql.service.process.process_single_db import process_csv_to_prompts
        process_csv_to_prompts(
            csv_path=args.csv_path,
            db_path=args.db_path,
            output_path=input_file,
            bm25_index_path=args.bm25_index_path,
            value_limit_num=args.value_limit_num,
            rename=args.rename,
            view=args.view,
            test_rows=args.test,
            history_path=args.history_path,
            history_k=args.history_k,
            cluster=args.cluster,
            dataset_name=args.dataset,
            stage0_from=args.stage0_from,
        )

    # Step 2: Run inference pipeline
    print("=" * 60)
    print("Step 2: Running inference pipeline")
    print("=" * 60)

    # Default table_link model to sql_generate model if not specified
    model_table_link = args.model_table_link or args.model_sql_generate

    # Handle --stage1_from: reuse Stage 1 output from a previous run
    eval_step = args.eval_step
    link_tables_arg = "none"
    stage1_from = args.stage1_from
    # Resolve "auto" to the appropriate default directory (dataset-aware)
    if stage1_from == "auto":
        stage1_from = os.path.join("outputs", args.dataset, "rename_linking" if args.rename else "base_linking")
    if stage1_from and stage1_from != "fresh":
        stage1_file = os.path.join(stage1_from, "sampling_think_table_link.json")
        if os.path.exists(stage1_file):
            link_tables_arg = stage1_file
            eval_step = "sql_pipeline"  # skip Stage 1
            print(f"Reusing Stage 1 from: {stage1_file}")
        else:
            print(f"WARNING: --stage1_from='{stage1_from}' but file not found: {stage1_file}, running Stage 1 fresh")

    # Build pipeline_infer command
    # Note: we use --source single_db and pass --db_path as the .sqlite file
    pipeline_cmd = (
        f"CUDA_VISIBLE_DEVICES={args.visible_devices} "
        f"python -m cscsql.model.pipeline_infer "
        f"--model_table_link '{model_table_link}' "
        f"--model_sql_generate '{args.model_sql_generate}' "
        f"--model_sql_merge '{args.model_sql_merge}' "
        f"--source single_db "
        f"--input_file '{input_file}' "
        f"--gold_file '{gold_file}' "
        f"--db_path '{args.db_path}' "
        f"--run_time {args.run_time} "
        f"--output_dir '{dataset_output_dir}' "
        f"--visible_devices {args.visible_devices} "
        f"--tensor_parallel_size {args.tensor_parallel_size} "
        f"--gpu_memory_utilization {args.gpu_memory_utilization} "
        f"--seed {args.seed} "
        f"--eval_step {eval_step} "
        f"--eval_mode {args.eval_mode} "
        f"--n_table_link {args.n_table_link} "
        f"--temperature_table_link {args.temperature_table_link} "
        f"--n_sql_generate {args.n_sql_generate} "
        f"--temperature_sql_generate {args.temperature_sql_generate} "
        f"--n_sql_merge {args.n_sql_merge} "
        f"--temperature_sql_merge {args.temperature_sql_merge} "
        f"--prompt_name {args.prompt_name} "
        f"--link_tables '{link_tables_arg}' "
        f"--gen_sqls none "
        f"--selection_vote none "
        f"--prompt_mode merge "
        f"--max_few_shot 0 "
        f"--dataset {args.dataset} "
        f"--log_dir '{log_dir}'"
    )
    if args.quantization:
        pipeline_cmd += f" --quantization {args.quantization}"
    if args.api_base_generate:
        pipeline_cmd += f" --api_base_generate '{args.api_base_generate}'"
    if args.api_base_merge:
        pipeline_cmd += f" --api_base_merge '{args.api_base_merge}'"
    if args.view:
        view_ddls_file = os.path.join(run_dir, "processed_prompts_view_ddls.json")
        if os.path.exists(view_ddls_file):
            pipeline_cmd += f" --view_ddls_file '{view_ddls_file}'"
        else:
            print(f"WARNING: --view is set but view DDLs file not found: {view_ddls_file}")
    if args.history_path:
        # History is now retrieved at inference time using precomputed data in run_dir
        pipeline_cmd += f" --history_dir '{run_dir}' --history_k {args.history_k}"
        if args.cluster:
            pipeline_cmd += " --use_clusters"
        # Skip --cluster_filter flag downstream when stage0 already did the schema pruning at preprocessing.
        # Otherwise the post-Stage1 cluster_tables override would double-apply an already-done transformation.
        if args.cluster_filter and not args.stage0_from:
            pipeline_cmd += " --cluster_filter"
        if args.rename:
            pipeline_cmd += " --history_rename"
        if args.view:
            pipeline_cmd += " --history_view"

    # Pass test offset for --test with --stage1_from alignment
    if args.test and args.stage1_from and ':' in str(args.test):
        test_offset = int(args.test.split(':')[0])
        pipeline_cmd += f" --test_offset {test_offset}"

    print(f"Running: {pipeline_cmd}")
    os.system(pipeline_cmd)

    # Step 3: Write final SQLs back to the input CSV as "base_cscsql" column
    print("=" * 60)
    print("Step 3: Writing results back to CSV")
    print("=" * 60)

    import pandas as pd
    import glob

    # Find the final major voting SQL file from the last stage (sql_merge)
    voting_files = glob.glob(os.path.join(run_dir, "*_sql_merge_pred_major_voting_sqls.sql"))
    if not voting_files:
        # Fallback: try sql_generate if no merge stage
        voting_files = glob.glob(os.path.join(run_dir, "*_pred_major_voting_sqls.sql"))

    if voting_files:
        # Use the most recent one
        voting_file = sorted(voting_files)[-1]
        print(f"Reading final SQLs from: {voting_file}")

        with open(voting_file, "r") as f:
            pred_sqls = [line.strip() for line in f.readlines()]

        df = pd.read_csv(args.csv_path)
        col_name = "base_cscsql"
        if args.dataset != "bird":
            col_name += f"_{args.dataset}"
        if args.rename:
            col_name += "_renamed"
        if args.view:
            col_name += "_withview"
        if args.history_path:
            col_name += "_withhistory"
        if args.cluster:
            if args.cluster_filter and args.stage0_from:
                col_name += "_clusterfiltered_stage0"
            elif args.cluster_filter:
                col_name += "_clusterfiltered"
            else:
                col_name += "_clustered"
                # If the user reused a pre-filtered Stage 1 cache (path contains "clusterfilter")
                # but didn't pass --cluster_filter, mark the column so it's distinguishable from
                # plain --cluster runs that used the regular linking cache.
                if args.stage1_from and "clusterfilter" in str(args.stage1_from).lower():
                    col_name += "_stage1cf"

        # Write to a separate output CSV to avoid corrupting the input
        output_csv = os.path.join(run_dir, f"results_{col_name}.csv")

        if len(pred_sqls) == len(df):
            df[col_name] = pred_sqls
            df.to_csv(output_csv, index=False)
            print(f"Wrote {len(pred_sqls)} predictions to '{output_csv}' column '{col_name}'")
        else:
            print(f"WARNING: mismatch — {len(pred_sqls)} predictions vs {len(df)} rows in CSV")
            # Save predictions only
            output_csv = os.path.join(run_dir, f"pred_sqls_{col_name}.csv")
            pd.DataFrame({col_name: pred_sqls}).to_csv(output_csv, index=False)
            print(f"Saved predictions separately to: {output_csv}")
    else:
        print("WARNING: No voting result files found in output directory")

    print("=" * 60)
    print(f"Done! Results in: {run_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
