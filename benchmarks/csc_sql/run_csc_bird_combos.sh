#!/bin/bash
# Run the remaining 7 csc_sql bird combos (5-11) sequentially.
# Uses 7B model + RunPod endpoints, matching the recent base/rename runs.
# Stage 1 auto-reuses from outputs/bird/{base,rename}/sampling_think_table_link.json.
# Stops on first error via `set -e`.

set -euo pipefail

CSV="/mnt/d/WORK/PhD/column retrieval/exp/bird schema opt/nl2sql.csv"
DB="/mnt/d/WORK/PhD/column retrieval/exp/merged_schema_fk.sqlite"
HIST="/mnt/d/WORK/PhD/column retrieval/exp/bird schema opt/sample.csv"
MODEL_GEN="cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-7B-Instruct"
MODEL_MERGE="cycloneboy/CscSQL-Merge-Qwen2.5-Coder-7B-Instruct"
BM25="outputs/bird/bm25_index"
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
        "$@"
}

# run_csc "1. rename"                                  --rename
# run_csc "5. base + cluster + history"                --cluster --stage1_from outputs/bird/base_linking_clusterfilter
# run_csc "11. rename + cluster + view + history"      --rename --cluster --view --stage1_from outputs/bird/rename_linking_clusterfilter
# run_csc "7. view + history"                          --view
run_csc "8. cluster + view + history"                --cluster --view --stage1_from outputs/bird/base_linking_clusterfilter
run_csc "9. cluster + rename + history"              --cluster --rename --stage1_from outputs/bird/rename_linking_clusterfilter
run_csc "10. rename + view + history"                --rename --view

# run_csc "5. base + cluster + history"                --cluster
# run_csc "8. cluster + view + history"                --cluster --view
run_csc "9. cluster + rename + history"              --cluster --rename
run_csc "11. rename + cluster + view + history"      --rename --cluster --view
echo ""
echo "========================================================================"
echo "[$(date +'%Y-%m-%d %H:%M:%S')]  ALL 10 COMBOS DONE"
echo "========================================================================"