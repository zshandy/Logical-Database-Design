#!/bin/bash
# Spider csc_sql combos.
# - Base + history is assumed already done (outputs/spider/base/).
# - 7 plain combos cover the rest of the standard 8 history variants.
# - 4 stage1cf variants reuse the cluster-filter Stage 1 caches with no runtime override.
# Launch only AFTER both `outputs/spider/base_linking_clusterfilter/` and
# `outputs/spider/rename_linking_clusterfilter/` are present (run_single_db will error otherwise).

set -euo pipefail

CSV="/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv"
DB="/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite"
HIST="/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv"
MODEL_GEN="cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-7B-Instruct"
MODEL_MERGE="cycloneboy/CscSQL-Merge-Qwen2.5-Coder-7B-Instruct"
BM25="outputs/spider/bm25_index"
API_GEN="https://gojsj8ut5g2tu6-8081.proxy.runpod.net/v1"
API_MERGE="https://gojsj8ut5g2tu6-8082.proxy.runpod.net/v1"

run_csc() {
    local label="$1"; shift
    echo ""
    echo "========================================================================"
    echo "[$(date +'%Y-%m-%d %H:%M:%S')]  $label"
    echo "========================================================================"
    python run_single_db.py \
        --csv_path "$CSV" \
        --db_path "$DB" \
        --model_sql_generate "$MODEL_GEN" \
        --model_sql_merge "$MODEL_MERGE" \
        --bm25_index_path "$BM25" \
        --api_base_generate "$API_GEN" \
        --api_base_merge "$API_MERGE" \
        --history_path "$HIST" \
        --dataset spider \
        "$@"
}

# ------- Plain combos (Stage 1 auto-loaded from outputs/spider/{base,rename}_linking) -------

run_csc "6. rename + history"                          --rename
run_csc "7. view + history"                            --view
run_csc "10. rename + view + history"                  --rename --view
run_csc "5. base + cluster + history"                  --cluster
run_csc "8. cluster + view + history"                  --cluster --view
run_csc "9. cluster + rename + history"                --cluster --rename
run_csc "11. rename + cluster + view + history"        --rename --cluster --view

# ------- stage1cf variants (Stage 1 from pre-pruned cache, no runtime override) -------
# These need outputs/spider/{base,rename}_linking_clusterfilter to exist.

run_csc "5cf. base + cluster + stage1cf"               --cluster --stage1_from outputs/spider/base_linking_clusterfilter
run_csc "8cf. cluster + view + stage1cf"               --cluster --view --stage1_from outputs/spider/base_linking_clusterfilter
run_csc "9cf. cluster + rename + stage1cf"             --cluster --rename --stage1_from outputs/spider/rename_linking_clusterfilter
run_csc "11cf. rename + cluster + view + stage1cf"     --rename --cluster --view --stage1_from outputs/spider/rename_linking_clusterfilter

echo ""
echo "========================================================================"
echo "[$(date +'%Y-%m-%d %H:%M:%S')]  ALL 11 SPIDER COMBOS DONE"
echo "========================================================================"
