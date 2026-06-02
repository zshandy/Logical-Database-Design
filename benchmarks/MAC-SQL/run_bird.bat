@echo off
setlocal
call conda activate openai-py39

set PY=python run_union.py
set IN="D:\WORK\PhD\column retrieval\exp\bird schema opt\nl2sql.csv"
set HIST="D:\WORK\PhD\column retrieval\exp\bird schema opt\sample.csv"
set DS=--dataset bird

@REM All 8 history combinations for bird.
@REM Linking is read from MAC-SQL-main/history_linking.json (base) or
@REM workload_updated_history_linking.json (rename) — MAC-SQL never computes
@REM linking itself, it's always loaded from those pre-existing files.
@REM All runs are --fresh to start clean (no resume from prior outputs).

@REM echo ===== 1. base + history =====
@REM %PY% %DS% --input_csv %IN% --history %HIST% --fresh --output_file output_base_history/results.jsonl --log_file outputs/bird/output_base_history/log.txt

@REM echo ===== 8. rename + history + cluster + view =====
@REM %PY% %DS% --rename true --input_csv %IN% --history %HIST% --use_cluster true --view true --fresh --output_file output_renamed_cluster_view/results.jsonl --log_file outputs/bird/output_renamed_cluster_view/log.txt

@REM echo ===== 2. base + history + view =====
@REM %PY% %DS% --input_csv %IN% --history %HIST% --view true --fresh --output_file output_base_history_view/results.jsonl --log_file outputs/bird/output_base_history_view/log.txt

@REM echo ===== 3. base + history + cluster =====
@REM %PY% %DS% --input_csv %IN% --history %HIST% --use_cluster true --fresh --output_file output_base_cluster/results.jsonl --log_file outputs/bird/output_base_cluster/log.txt

@REM echo ===== 4. base + history + cluster + view =====
@REM %PY% %DS% --input_csv %IN% --history %HIST% --use_cluster true --view true --fresh --output_file output_base_cluster_view/results.jsonl --log_file outputs/bird/output_base_cluster_view/log.txt

@REM echo ===== 5. rename + history =====
@REM %PY% %DS% --rename true --input_csv %IN% --history %HIST% --fresh --output_file output_renamed_history/results.jsonl --log_file outputs/bird/output_renamed_history/log.txt

@REM echo ===== 6. rename + history + view =====
@REM %PY% %DS% --rename true --input_csv %IN% --history %HIST% --view true --fresh --output_file output_renamed_history_view/results.jsonl --log_file outputs/bird/output_renamed_history_view/log.txt

@REM echo ===== 7. rename + history + cluster =====
@REM %PY% %DS% --rename true --input_csv %IN% --history %HIST% --use_cluster true --fresh --output_file output_renamed_cluster/results.jsonl --log_file outputs/bird/output_renamed_cluster/log.txt


@REM ===== Cluster-filter reruns (--cluster_filter true) =====
@REM These use --cluster_filter true which pre-prunes the Selector's schema input
@REM to tables found in matched clusters. Output paths use '_clusterfilter' so
@REM they don't collide with the plain '_cluster' runs above.

echo ===== 3cf. base + history + cluster + filter =====
%PY% %DS% --input_csv %IN% --history %HIST% --use_cluster true --cluster_filter true --fresh --output_file output_base_clusterfilter/results.jsonl --log_file outputs/bird/output_base_clusterfilter/log.txt

echo ===== 4cf. base + history + cluster + view + filter =====
%PY% %DS% --input_csv %IN% --history %HIST% --use_cluster true --view true --cluster_filter true --fresh --output_file output_base_clusterfilter_view/results.jsonl --log_file outputs/bird/output_base_clusterfilter_view/log.txt

echo ===== 7cf. rename + history + cluster + filter =====
%PY% %DS% --rename true --input_csv %IN% --history %HIST% --use_cluster true --cluster_filter true --fresh --output_file output_renamed_clusterfilter/results.jsonl --log_file outputs/bird/output_renamed_clusterfilter/log.txt

echo ===== 8cf. rename + history + cluster + view + filter =====
%PY% %DS% --rename true --input_csv %IN% --history %HIST% --use_cluster true --view true --cluster_filter true --fresh --output_file output_renamed_clusterfilter_view/results.jsonl --log_file outputs/bird/output_renamed_clusterfilter_view/log.txt

echo ===== ALL DONE =====
endlocal

