@echo off
setlocal
call conda activate openai-py39

set PY=python run_union.py
set IN="D:\WORK\PhD\column retrieval\spider_data\nl2sql.csv"
set HIST="D:\WORK\PhD\column retrieval\spider_data\sample.csv"
set DS=--dataset spider

@REM ----- Already-run combos (kept as reference, commented out) -----
@REM echo ===== 1. base (plain, most original) =====
@REM %PY% %DS% --input_csv %IN% --output_file output_base/results.jsonl --log_file outputs/spider/output_base/log.txt

@REM echo ===== 2. base + view =====
@REM %PY% %DS% --view true --input_csv %IN% --output_file output_base_view/results.jsonl --log_file outputs/spider/output_base_view/log.txt

@REM echo ===== 7. rename (plain) =====
@REM %PY% %DS% --rename true --input_csv %IN% --output_file output_renamed/results_top3.jsonl --log_file outputs/spider/output_renamed/log_top3.txt

@REM echo ===== 8. rename + view =====
@REM %PY% %DS% --rename true --view true --input_csv %IN% --output_file output_renamed_view/results_top3.jsonl --log_file outputs/spider/output_renamed_view/log_top3.txt

@REM echo ===== 3. base + history (top3 already done) =====
@REM %PY% %DS% --input_csv %IN% --history %HIST% --output_file output_base_history/results_top3.jsonl --log_file outputs/spider/output_base_history/log_top3.txt

@REM echo ===== 4. base + history + view (top3 already done) =====
@REM %PY% %DS% --input_csv %IN% --history %HIST% --view true --output_file output_base_history_view/results_top3.jsonl --log_file outputs/spider/output_base_history_view/log_top3.txt

@REM echo ===== 5. base + history + cluster (plain, top3 already done) =====
@REM %PY% %DS% --input_csv %IN% --history %HIST% --use_cluster true --output_file output_base_cluster/results_top3.jsonl --log_file outputs/spider/output_base_cluster/log_top3.txt

@REM echo ===== 6. base + history + cluster + view (plain, top3 already done) =====
@REM %PY% %DS% --input_csv %IN% --history %HIST% --use_cluster true --view true --output_file output_base_cluster_view/results_top3.jsonl --log_file outputs/spider/output_base_cluster_view/log_top3.txt

@REM echo ===== 9. rename + history (top3 already done) =====
@REM %PY% %DS% --rename true --input_csv %IN% --history %HIST% --output_file output_renamed_history/results_top3.jsonl --log_file outputs/spider/output_renamed_history/log_top3.txt

@REM echo ===== 10. rename + history + view (top3 already done) =====
@REM %PY% %DS% --rename true --input_csv %IN% --history %HIST% --view true --output_file output_renamed_history_view/results_top3.jsonl --log_file outputs/spider/output_renamed_history_view/log_top3.txt

@REM echo ===== 11. rename + history + cluster (plain, top3 already done) =====
@REM %PY% %DS% --rename true --input_csv %IN% --history %HIST% --use_cluster true --output_file output_renamed_cluster/results_top3.jsonl --log_file outputs/spider/output_renamed_cluster/log_top3.txt

@REM echo ===== 12. rename + history + cluster + view (plain, top3 already done) =====
@REM %PY% %DS% --rename true --input_csv %IN% --history %HIST% --use_cluster true --view true --output_file output_renamed_cluster_view/results_top3.jsonl --log_file outputs/spider/output_renamed_cluster_view/log_top3.txt

@REM ----- NEW: cluster_filter ablation (4 runs) -----

echo ===== 5cf. base + history + cluster + filter =====
%PY% %DS% --input_csv %IN% --history %HIST% --use_cluster true --cluster_filter true --output_file output_base_clusterfilter/results_top3.jsonl --log_file outputs/spider/output_base_clusterfilter/log_top3.txt

echo ===== 6cf. base + history + cluster + view + filter =====
%PY% %DS% --input_csv %IN% --history %HIST% --use_cluster true --view true --cluster_filter true --output_file output_base_clusterfilter_view/results_top3.jsonl --log_file outputs/spider/output_base_clusterfilter_view/log_top3.txt

echo ===== 11cf. rename + history + cluster + filter =====
%PY% %DS% --rename true --input_csv %IN% --history %HIST% --use_cluster true --cluster_filter true --output_file output_renamed_clusterfilter/results_top3.jsonl --log_file outputs/spider/output_renamed_clusterfilter/log_top3.txt

echo ===== 12cf. rename + history + cluster + view + filter =====
%PY% %DS% --rename true --input_csv %IN% --history %HIST% --use_cluster true --view true --cluster_filter true --output_file output_renamed_clusterfilter_view/results_top3.jsonl --log_file outputs/spider/output_renamed_clusterfilter_view/log_top3.txt

echo ===== ALL DONE =====
endlocal
