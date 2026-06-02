#!/bin/bash
# Exit immediately if any command fails
set -e 

echo "Activating Conda Environment..."
# This is required to make conda work inside a bash script
eval "$(conda shell.bash hook)"
conda activate cscsql

echo "====================================="
echo "1. view"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --view \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/base"

echo "====================================="
echo "3. rename + view"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --rename --view \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/rename"

echo "====================================="
echo "4. base + history"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --history_path "/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv" \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/base"

echo "====================================="
echo "5. base + cluster + history"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --history_path "/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv" \
    --cluster \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/base"

echo "====================================="
echo "6. rename + history"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --history_path "/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv" \
    --rename \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/rename"

echo "====================================="
echo "7. view + history"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --history_path "/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv" \
    --view \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/base"

echo "====================================="
echo "8. cluster + view + history"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --history_path "/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv" \
    --cluster --view \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/base"

echo "====================================="
echo "9. cluster + rename + history"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --history_path "/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv" \
    --cluster --rename \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/rename"

echo "====================================="
echo "10. rename + view + history"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --history_path "/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv" \
    --rename --view \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/rename"

echo "====================================="
echo "11. rename + cluster + view + history"
echo "====================================="
python run_single_db.py \
    --csv_path "/mnt/d/WORK/PhD/column retrieval/spider_data/nl2sql.csv" \
    --db_path "/mnt/d/WORK/PhD/column retrieval/spider_data/merged_spider.sqlite" \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-3B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-3B-Instruct \
    --bm25_index_path outputs/bm25_index_spider \
    --api_base_generate http://142.58.48.211:8081/v1 \
    --api_base_merge http://142.58.48.211:8082/v1 \
    --history_path "/mnt/d/WORK/PhD/column retrieval/spider_data/sample.csv" \
    --rename --cluster --view \
    --dataset spider \
    --stage1_from "/mnt/d/WORK/PhD/column retrieval/csc_sql/outputs/rename"

echo "====================================="
echo "ALL EXPERIMENTS COMPLETE!"
echo "====================================="