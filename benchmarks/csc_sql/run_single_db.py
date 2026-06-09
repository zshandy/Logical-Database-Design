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
    parser.add_argument("--output_dir", type=str, default="outputs",
                        help="Output root. The default sentinel 'outputs' resolves to "
                             "<LDD>/outputs/csc_sql/. Pass an explicit path to override.")
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
                        help="Use cluster-based filtering of history queries using Stage 1 results. "
                             "When --mapping_path points at a prep_database config file with a "
                             "'cluster' section, the precomputed clusters are loaded directly; "
                             "otherwise clusters are built from history at runtime.")
    parser.add_argument("--cluster_filter", action=argparse.BooleanOptionalAction, default=None,
                        help="After Stage 1 + cluster matching, replace Stage 1 predicted tables with the union of tables across matched clusters for downstream stages. "
                             "Defaults to ON whenever --cluster is set; pass --no-cluster_filter to inject clusters without filtering. "
                             "Has no effect when --cluster is off.")
    parser.add_argument("--stage0_from", type=str, default=None,
                        help="Path to a prior run's folder whose Stage 1 output will be used to pre-prune the schema BEFORE this run's Stage 1. "
                             "Per-question, the prior Stage 1 tables are matched to clusters, and the cluster-union is used to filter the schema passed to this Stage 1. "
                             "Requires --cluster_filter, --cluster, --history_path. Cannot be combined with an explicit --stage1_from. Forces --stage1_from fresh internally.")
    parser.add_argument("--run_eval", action="store_true",
                        help="Run gold-SQL execution for EX accuracy metrics. Off by default — predicted SQLs are still generated and voted without this; turn it on only when you actually want EX accuracy printed.")

    # Quantization
    parser.add_argument("--quantization", type=str, default="bitsandbytes",
                        help="quantization method: bitsandbytes (INT4/INT8 depending on model config + vLLM "
                             "version — for cycloneboy/* bnb-quantized variants this loads NF4), "
                             "None for bf16.")
    parser.add_argument("--max_model_len", type=int, default=None,
                        help="vLLM max_model_len override. Lower → smaller KV cache reservation → less VRAM "
                             "(at the cost of shorter context window). When omitted, uses infer.py's default "
                             "(32768 for inference, 12000 for train DBs).")

    # Remote API mode (optional — if not set, runs locally)
    parser.add_argument("--api_base_generate", type=str, default=None,
                        help="Remote vLLM server for Stage 1+2 (e.g. http://192.168.1.100:8000/v1)")
    parser.add_argument("--api_base_merge", type=str, default=None,
                        help="Remote vLLM server for Stage 3 (e.g. http://192.168.1.100:8001/v1)")

    # Testing
    parser.add_argument("--rows", type=str, default=None,
                        help="Row selection: 'N' for the first N rows, or 'START:END' for a python-style "
                             "half-open slice. Aligned with basesql / din-sql.")

    # Reuse previous outputs
    parser.add_argument("--stage1_from", type=str, default="auto",
                        help="'auto' (default): outputs/<dataset>/rename_linking if --rename else outputs/<dataset>/base_linking. "
                             "'fresh': run Stage 1 from scratch. Or a path to reuse (e.g. outputs/bird/base_linking)")

    # Preprocessing only
    parser.add_argument("--skip_preprocess", action="store_true", help="Skip preprocessing (use existing input_file)")
    parser.add_argument("--input_file", type=str, default=None, help="Pre-existing processed JSON (skips preprocessing)")

    args = parser.parse_args()

    # --cluster_filter defaults to args.cluster when not explicitly set
    if args.cluster_filter is None:
        args.cluster_filter = bool(args.cluster)

    # Cluster precomputed file: re-use --mapping_path (the consolidated prep config
    # holds both the rename mapping and the cluster section).
    if args.cluster and not args.mapping_path:
        _here = os.path.dirname(os.path.abspath(__file__))
        _ldd_root = os.path.abspath(os.path.join(_here, "..", ".."))
        _suffix = "_renamed" if args.rename else ""
        args.mapping_path = os.path.join(
            _ldd_root, "mapping_files", f"prep_{args.dataset}{_suffix}.json"
        )
        if os.path.exists(args.mapping_path):
            print(f"[csc_sql] --mapping_path auto-resolved to {args.mapping_path}")
        else:
            print(f"[csc_sql] --mapping_path auto-resolved to {args.mapping_path} "
                  f"(not found — will build clusters from history)")

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

    # Auto-resolve column names from the mapping JSON's `columns` section so
    # the user doesn't have to retype --question_col / --sql_col / etc. when
    # they were already specified at prep_database time. Sets args.sql_col,
    # args.view_sql_col, args.gt_tables_col on the namespace; explicit CLI
    # flags still win (handled inside resolve_column_defaults via None-check).
    import sys as _sys_for_cols
    _bench_root_for_cols = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if _bench_root_for_cols not in _sys_for_cols.path:
        _sys_for_cols.path.insert(0, _bench_root_for_cols)
    from _common.cli_common import resolve_column_defaults as _rcd
    _rcd(args, args.mapping_path, pipeline_tag="csc_sql")

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

    # Dataset-scoped output dir: <LDD>/outputs/csc_sql/<dataset>/<timestamp>/
    # Honours --output_dir override; otherwise resolves under the LDD outputs tree
    # so artifacts don't flood the benchmarks folder.
    if args.output_dir in (None, "", "outputs"):
        import sys as _sys
        _bench_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        if _bench_root not in _sys.path:
            _sys.path.insert(0, _bench_root)
        from _common.paths import default_output_dir, default_log_dir
        dataset_output_dir = default_output_dir("csc_sql", args.dataset)
    else:
        dataset_output_dir = os.path.join(args.output_dir, args.dataset)
        from _common.paths import default_log_dir
    run_dir = os.path.join(dataset_output_dir, args.run_time)
    os.makedirs(run_dir, exist_ok=True)

    # Log directory: <LDD>/logs/csc_sql/<dataset>/<run_time>/
    log_dir = default_log_dir("csc_sql", os.path.join(args.dataset, args.run_time))
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
            test_rows=args.rows,
            history_path=args.history_path,
            history_k=args.history_k,
            cluster=args.cluster,
            cluster_path=args.mapping_path,
            dataset_name=args.dataset,
            stage0_from=args.stage0_from,
            sql_col_override=getattr(args, 'sql_col', None),
            view_sql_col_override=getattr(args, 'view_sql_col', None),
            gt_tables_col_override=getattr(args, 'gt_tables_col', None),
        )

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

    # Step 1.5: Pre-pass Stage 1 to bootstrap stage0 when cluster_filter is on.
    # Mirrors MAC-SQL's selector pre-pass pattern:
    #   pass 1 — Stage 1 sees the full schema → picks candidate tables
    #   cluster lookup → union(matched cluster tables) = filtered schema
    #   rebuild prompts with that filtered schema (via existing --stage0_from)
    #   pass 2 — Stage 1 re-runs on the filtered schema (main pipeline below)
    # Only fires when --cluster --cluster_filter is on, no prior Stage 1 cache
    # is being reused, and --stage0_from wasn't passed explicitly.
    _need_prepass = (
        args.cluster and args.cluster_filter
        and link_tables_arg == "none"  # no Stage 1 cache being reused
        and args.stage0_from is None
        and not args.skip_preprocess
    )
    if _need_prepass:
        print("=" * 60)
        print("Step 1.5: Pre-pass Stage 1 (cluster_filter bootstrap)")
        print("=" * 60)
        prepass_run_time = f"{args.run_time}_prepass"
        prepass_run_dir = os.path.join(dataset_output_dir, prepass_run_time)
        os.makedirs(prepass_run_dir, exist_ok=True)
        prepass_log_dir = os.path.join(os.path.dirname(log_dir) or ".", prepass_run_time)
        os.makedirs(prepass_log_dir, exist_ok=True)
        prepass_cmd = (
            f"CUDA_VISIBLE_DEVICES={args.visible_devices} "
            f"python -m cscsql.model.pipeline_infer "
            f"--model_table_link '{model_table_link}' "
            f"--model_sql_generate '{args.model_sql_generate}' "
            f"--model_sql_merge '{args.model_sql_merge}' "
            f"--source single_db "
            f"--input_file '{input_file}' "
            f"--gold_file '{gold_file}' "
            f"--db_path '{args.db_path}' "
            f"--run_time {prepass_run_time} "
            f"--output_dir '{dataset_output_dir}' "
            f"--visible_devices {args.visible_devices} "
            f"--tensor_parallel_size {args.tensor_parallel_size} "
            f"--gpu_memory_utilization {args.gpu_memory_utilization} "
            f"--seed {args.seed} "
            f"--eval_step table_link "  # ONLY Stage 1
            f"--eval_mode {args.eval_mode} "
            f"--n_table_link {args.n_table_link} "
            f"--temperature_table_link {args.temperature_table_link} "
            f"--prompt_name {args.prompt_name} "
            f"--link_tables 'none' "
            f"--prompt_mode table "
            f"--max_few_shot 0 "
            f"--dataset {args.dataset} "
            f"--log_dir '{prepass_log_dir}'"
        )
        if args.quantization:
            prepass_cmd += f" --quantization {args.quantization}"
        if args.max_model_len is not None:
            prepass_cmd += f" --max_model_len {args.max_model_len}"
        print(f"Running pre-pass: {prepass_cmd}")
        os.system(prepass_cmd)

        # Use pre-pass output as stage0_from for the main pipeline.
        prepass_stage1_file = os.path.join(prepass_run_dir, "sampling_think_table_link.json")
        if os.path.exists(prepass_stage1_file):
            args.stage0_from = prepass_run_dir
            print(f"[pre-pass] Setting --stage0_from to {prepass_run_dir}")
            # Rebuild prompts so the MAIN Stage 1 sees the cluster-filtered schema.
            print("[pre-pass] Rebuilding prompts with cluster-filtered schema...")
            process_csv_to_prompts(
                csv_path=args.csv_path,
                db_path=args.db_path,
                output_path=input_file,
                bm25_index_path=args.bm25_index_path,
                value_limit_num=args.value_limit_num,
                rename=args.rename,
                view=args.view,
                test_rows=args.rows,
                history_path=args.history_path,
                history_k=args.history_k,
                cluster=args.cluster,
                cluster_path=args.mapping_path,
                dataset_name=args.dataset,
                stage0_from=args.stage0_from,
                sql_col_override=getattr(args, 'sql_col', None),
                view_sql_col_override=getattr(args, 'view_sql_col', None),
                gt_tables_col_override=getattr(args, 'gt_tables_col', None),
            )
        else:
            print(f"[pre-pass] WARNING: expected {prepass_stage1_file} but not found — falling back to single-pass Stage 1")

    # Step 2: Run inference pipeline
    print("=" * 60)
    print("Step 2: Running inference pipeline")
    print("=" * 60)

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
    if args.max_model_len is not None:
        pipeline_cmd += f" --max_model_len {args.max_model_len}"
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
        # Forward column overrides resolved from the mapping JSON's `columns`
        # section so the inference subprocess reads the right CSV columns.
        if getattr(args, 'sql_col', None):
            pipeline_cmd += f" --sql_col '{args.sql_col}'"
        if getattr(args, 'view_sql_col', None):
            pipeline_cmd += f" --view_sql_col '{args.view_sql_col}'"

    # Pass test offset for --test with --stage1_from alignment
    if args.rows and args.stage1_from and ':' in str(args.rows):
        test_offset = int(args.rows.split(':')[0])
        pipeline_cmd += f" --test_offset {test_offset}"

    print(f"Running: {pipeline_cmd}")
    os.system(pipeline_cmd)

    # Step 3: Write final SQLs back to the input CSV under unified naming.
    print("=" * 60)
    print("Step 3: Writing results back to CSV")
    print("=" * 60)

    import pandas as pd
    import glob

    # Find the final major voting SQL file from the last stage (sql_merge)
    voting_files = glob.glob(os.path.join(run_dir, "*_sql_merge_pred_major_voting_sqls.sql"))
    if not voting_files:
        voting_files = glob.glob(os.path.join(run_dir, "*_pred_major_voting_sqls.sql"))

    if voting_files:
        voting_file = sorted(voting_files)[-1]
        print(f"Reading final SQLs from: {voting_file}")
        with open(voting_file, "r") as f:
            pred_sqls = [line.strip() for line in f.readlines()]

        # Unified suffix grammar (matches basesql / din-sql / MAC-SQL):
        #   _rename / _withview / _clusterfilter or _cluster / _history / _stage0
        _suffix = ""
        if args.rename:
            _suffix += "_rename"
        if args.view:
            _suffix += "_withview"
        if args.cluster:
            if args.cluster_filter:
                _suffix += "_clusterfilter"
                if args.stage0_from:
                    _suffix += "_stage0"
            else:
                _suffix += "_cluster"
                if args.stage1_from and "clusterfilter" in str(args.stage1_from).lower():
                    _suffix += "_stage1cf"
        if args.history_path:
            _suffix += "_history"
        col_name = f"cscsql{_suffix}"

        # Row alignment: csc_sql predicts on a sliced range when --rows is set.
        # Build a DataFrame indexed by the original CSV row indices.
        df_input = pd.read_csv(args.csv_path)
        if args.rows is not None:
            spec = str(args.rows)
            if ":" in spec:
                a, b = spec.split(":", 1)
                start = int(a) if a.strip() else 0
                end = int(b) if b.strip() else len(df_input)
            else:
                start, end = 0, int(spec)
            expected = end - start
            if len(pred_sqls) != expected:
                print(f"WARNING: prediction count {len(pred_sqls)} != expected {expected} for --rows {spec}")
            idx_range = range(start, start + len(pred_sqls))
        else:
            if len(pred_sqls) != len(df_input):
                print(f"WARNING: prediction count {len(pred_sqls)} != input rows {len(df_input)}")
            idx_range = range(len(pred_sqls))
        df_pred = pd.DataFrame({col_name: pred_sqls}, index=list(idx_range))

        # Bench-root for _common import
        import sys as _sys_wb
        _bench_root_wb = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        if _bench_root_wb not in _sys_wb.path:
            _sys_wb.path.insert(0, _bench_root_wb)
        from _common.evaluate import write_back_to_input_csv
        write_back_to_input_csv(
            csv_path=args.csv_path,
            df_predicted=df_pred,
            column_names=[col_name],
            final_sql_col=col_name,
            db_path=args.db_path,
            gold_sql_col="SQL",
            pipeline_tag="csc_sql",
        )
    else:
        print("WARNING: No voting result files found in output directory")

    print("=" * 60)
    print(f"Done! Results in: {run_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
