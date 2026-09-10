#!/usr/bin/env bash
# Full BIRD runs: base -> rap_opt2 -> rap_opt1, 767 questions each.
#
#   bash script/run_ldd_bird_all.sh
#
# Cheapest-first ordering is deliberate. Measured on the dry runs, per question:
#   opt2  103.4k input tokens   ->   79M input over 767 questions
#   opt1  221.7k input tokens   ->  170M input over 767 questions
# opt1 is the expensive arm because table-level injection reaches 1,533 columns
# on some questions, so it runs last and can be skipped after seeing the others.
#
# The masked few-shot index over the full 767-row history pool is built ONCE
# (with LLM masking, unlike the dry runs) and shared by all three arms; it is
# keyed only on the question and the base SQL column.
#
# Value indexes are prebuilt and shared per namespace:
#   base  -> _shared/vector_store/bird_org       (original 75 tables)
#   +R    -> _shared/vector_store/bird_renamed   (renamed 75 tables)
set -u
cd "$(dirname "$0")/.." || exit 1

PY=D:/miniconda3/envs/deepeye/python.exe
export PYTHONIOENCODING=utf-8
mkdir -p logs

now () { date '+%F %T'; }
say () { echo "[$(now)] $*"; }

run_stage () {   # $1 = runner name, $2 = log file, rest = extra args
  local runner="$1"; shift
  local log="$1"; shift
  "$PY" -u "runner/${runner}.py" "$@" >> "$log" 2>&1
  return $?
}

run_arm () {
  local arm="$1"
  export CONFIG_PATH="config/local/ldd/bird-${arm}.toml"
  local log="logs/bird_${arm}.log"
  : > "$log"

  say "================ bird/${arm} ================"
  [ -f "$CONFIG_PATH" ] || { say "missing $CONFIG_PATH"; return 1; }

  for stage in preprocess_dataset create_vector_db_parallel run_value_retrieval; do
    say "bird/${arm}: $stage"
    run_stage "$stage" "$log" || { say "bird/${arm}: $stage FAILED"; return 1; }
  done

  # One shared masked index over the FULL history pool, with LLM masking.
  # Presence of a manifest is not enough: the dry runs write a manifest for a
  # 40-row --skip_mask_llm index to the same path, and reusing that would give
  # every arm a truncated, unmasked ICL pool. Check the example count against
  # the pool size and rebuild when it does not match.
  IDX=workspace/runs/_shared/ldd/train_full_index/manifest.json
  WANT=$("$PY" -c "
import sys; sys.path.insert(0,'.')
from app.ldd.history import load_history_examples
print(len(load_history_examples('bird')))" 2>/dev/null)
  HAVE=$("$PY" -c "
import json,sys
try: print(json.load(open(r'$IDX',encoding='utf-8')).get('example_count',0))
except Exception: print(0)" 2>/dev/null)
  if [ "${HAVE:-0}" != "${WANT:-0}" ]; then
    say "bird/${arm}: few-shot index has ${HAVE:-0}/${WANT:-?} examples -- rebuilding with LLM masking"
    rm -rf workspace/runs/_shared/ldd/train_full_index
    run_stage build_few_shot_index "$log" --force || { say "few-shot index FAILED"; return 1; }
    HAVE=$("$PY" -c "
import json;print(json.load(open(r'$IDX',encoding='utf-8')).get('example_count',0))" 2>/dev/null)
    say "bird/${arm}: few-shot index built with ${HAVE} examples"
  else
    say "bird/${arm}: reusing the shared few-shot index (${HAVE} examples)"
  fi

  say "bird/${arm}: few-shot preparation"
  run_stage run_few_shot_preparation "$log" || { say "bird/${arm}: few-shot prep FAILED"; return 1; }

  say "bird/${arm}: schema linking"
  for attempt in 1 2 3; do
    run_stage run_schema_linking "$log" && break
    say "bird/${arm}: linking attempt $attempt failed -- retrying (it resumes)"
  done

  # 5.5 is a no-op for base and exits 0 without writing a snapshot
  say "bird/${arm}: APR injection"
  run_stage run_apr_injection "$log" || { say "bird/${arm}: APR injection FAILED"; return 1; }

  for stage in run_sql_generation run_sql_revision run_sql_selection; do
    say "bird/${arm}: $stage"
    for attempt in 1 2 3; do
      run_stage "$stage" "$log" && break
      say "bird/${arm}: $stage attempt $attempt failed -- retrying (it resumes)"
    done
  done

  say "bird/${arm}: export + score"
  run_stage export_ldd_results "$log" || say "bird/${arm}: EXPORT nonzero"
  grep -a "EX strict\|EX lenient\|scored\|no SQL" "$log" | tail -4

  say "bird/${arm}: token cost so far"
  "$PY" -u - <<'PYCOST' 2>/dev/null
import sys, statistics as st
sys.path.insert(0, ".")
from app.config import get_config
from app.dataset import load_dataset
c = get_config()
d = load_dataset(c.sql_selection_config.save_path)
i = [x.total_llm_cost["prompt_tokens"] for x in d if x.total_llm_cost]
o = [x.total_llm_cost["completion_tokens"] for x in d if x.total_llm_cost]
if i:
    print(f"    {len(i)} questions | input {sum(i)/1e6:.1f}M ({st.mean(i)/1000:.0f}k/q)"
          f" | output {sum(o)/1e6:.1f}M ({st.mean(o)/1000:.0f}k/q)")
PYCOST

  say "################ bird/${arm} FINISHED ################"
}

say "starting: base -> rap_opt2 -> rap_opt1 (cheapest first)"
run_arm base
run_arm rap_opt2
run_arm rap_opt1
say "all three arms complete"
