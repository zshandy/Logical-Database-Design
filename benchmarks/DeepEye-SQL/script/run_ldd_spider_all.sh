#!/usr/bin/env bash
# Full SPIDER runs: base + opt2 v2, on gpt-4.1-mini then gpt-5.6-luna. 502 questions each.
#
#   bash script/run_ldd_spider_all.sh
#
# 4.1-mini runs FIRST. Per-arm cost is similar (~$37-44) but 4.1-mini emits no
# reasoning tokens so it finishes in roughly half the wall-clock, which means any
# spider-specific breakage that the 3-question dry run missed surfaces on the
# cheap, fast pair rather than 6 hours into luna.
#
# Two flows:
#   base   linear -- linking runs once, 5.5 is a no-op and exits 0
#   opt2   phase A (direct+value) -> cluster-aware prep -> phase B (reversed)
#          The snapshot chain must stay LINEAR: prep reads phase A's snapshot,
#          then that snapshot is removed so phase B falls back to prep's output,
#          which carries both the linking results and the examples. Getting this
#          wrong silently drops few_shot_examples and ICL returns nothing.
#
# Shared per NAMESPACE, built once and reused by both models:
#   value index   _shared/vector_store/spider_{org,renamed}
#   few-shot idx  _shared/ldd/index_spider_{org,renamed}
#   mask cache    _shared/ldd/spider_mask_cache.jsonl   (502 x 2 entries)
set -u
cd "$(dirname "$0")/.." || exit 1

PY=D:/miniconda3/envs/deepeye/python.exe
export PYTHONIOENCODING=utf-8
mkdir -p logs

now () { date '+%F %T'; }
say () { echo "[$(now)] $*"; }
run () {  # runner name, then extra args; retries because every stage resumes
  local n="$1"; shift
  for a in 1 2 3; do
    "$PY" -u "runner/$n.py" "$@" >> "$LOG" 2>&1 && return 0
    say "  $n attempt $a nonzero -- retrying (it resumes)"
  done
  return 1
}

# The shared index must hold the FULL pool with real LLM masking. Presence of a
# manifest is not enough: a dry run writes a 40-row --skip_mask_llm manifest, and
# reusing that gives every arm a truncated, unmasked ICL pool (this happened on
# bird). Compare example_count against the pool size and rebuild on mismatch.
ensure_index () {
  local idx want have
  idx=$("$PY" -c "
import sys; sys.path.insert(0,'.')
from app.config import get_config
print(get_config().few_shot_index_config.save_path)" 2>/dev/null | tr -d '\r')
  want=$("$PY" -c "
import sys; sys.path.insert(0,'.')
from app.config import get_config
from app.ldd.config import arm_of
from app.ldd.history import load_history_examples
a = arm_of(get_config().dataset_config)
print(len(load_history_examples('spider', rename=bool(a and a.rename))))" 2>/dev/null | tr -d '\r')
  have=$("$PY" -c "
import json
try: print(json.load(open(r'$idx/manifest.json',encoding='utf-8')).get('example_count',0))
except Exception: print(0)" 2>/dev/null | tr -d '\r')
  if [ "${have:-0}" != "${want:-0}" ]; then
    say "  few-shot index ${have:-0}/${want:-?} examples -- rebuilding with LLM masking"
    rm -rf "$idx"
    run build_few_shot_index --force || return 1
    have=$("$PY" -c "
import json;print(json.load(open(r'$idx/manifest.json',encoding='utf-8')).get('example_count',0))" 2>/dev/null | tr -d '\r')
    say "  few-shot index built: ${have} examples"
  else
    say "  reusing shared few-shot index (${have} examples)"
  fi
}

score_and_cost () {
  run export_ldd_results || say "  EXPORT nonzero"
  grep -a "EX strict\|EX lenient\|scored\|no SQL" "$LOG" | tail -4
  "$PY" -u - <<PYC 2>/dev/null
import sys, statistics as st
sys.path.insert(0, ".")
from app.config import get_config
from app.dataset import load_dataset
IN, OUT = ($IN_RATE, $OUT_RATE)
d = load_dataset(get_config().sql_selection_config.save_path)
i = [x.total_llm_cost["prompt_tokens"] for x in d if x.total_llm_cost]
o = [x.total_llm_cost["completion_tokens"] for x in d if x.total_llm_cost]
p = load_dataset(get_config().few_shot_index_config.prepared_save_path)
pi = po = 0
for x in p:
    tu = ((getattr(x, "few_shot_preparation_metadata", None) or {}).get("preliminary_sql") or {}).get("token_usage") or {}
    pi += tu.get("prompt_tokens", 0) or 0
    po += tu.get("completion_tokens", 0) or 0
if i:
    print(f"    pipeline in {sum(i)/1e6:.1f}M ({st.mean(i)/1000:.0f}k/q) out {sum(o)/1e6:.1f}M"
          f"  ->  \$ {sum(i)*IN + sum(o)*OUT:.2f}")
    print(f"    prep     in {pi/1e6:.1f}M out {po/1e6:.1f}M  ->  \$ {pi*IN + po*OUT:.2f}")
    print(f"    ARM TOTAL  \$ {sum(i)*IN + sum(o)*OUT + pi*IN + po*OUT:.2f}")
PYC
}

run_base () {
  export CONFIG_PATH="config/local/ldd/$1.toml"
  LOG="logs/$1.log"; : > "$LOG"
  say "================ $1 (base, linear) ================"
  [ -f "$CONFIG_PATH" ] || { say "missing $CONFIG_PATH"; return 1; }
  for s in preprocess_dataset create_vector_db_parallel run_value_retrieval; do
    say "  $s"; run "$s" || { say "  $s FAILED"; return 1; }
  done
  ensure_index || return 1
  say "  few-shot preparation";  run run_few_shot_preparation || return 1
  say "  schema linking";        run run_schema_linking       || return 1
  say "  APR injection (no-op)"; run run_apr_injection        || return 1
  for s in run_sql_generation run_sql_revision run_sql_selection; do
    say "  $s"; run "$s" || { say "  $s FAILED"; return 1; }
  done
  say "  export + score"; score_and_cost
  say "################ $1 DONE ################"
}

run_opt2 () {
  export CONFIG_PATH="config/local/ldd/$1.toml"
  LOG="logs/$1.log"; : > "$LOG"
  say "================ $1 (opt2 v2, two-phase) ================"
  [ -f "$CONFIG_PATH" ] || { say "missing $CONFIG_PATH"; return 1; }
  for s in preprocess_dataset create_vector_db_parallel run_value_retrieval; do
    say "  $s"; run "$s" || { say "  $s FAILED"; return 1; }
  done
  ensure_index || return 1
  local SL
  SL=$("$PY" -c "
import sys; sys.path.insert(0,'.')
from app.config import get_config
print(get_config().schema_linking_config.save_path)" 2>/dev/null | tr -d '\r')
  say "  5a. linking PHASE A (direct+value -> clusters)"
  run run_schema_linking_phase_a || return 1
  say "  4b. cluster-aware few-shot prep"
  run run_few_shot_preparation --input_path "$SL" || return 1
  rm -rf "$SL" "$SL".data "${SL%.snapshot}.artifacts"
  say "  5b. linking PHASE B (reversed only)"
  run run_schema_linking_phase_b || return 1
  say "  5.5 APR injection"; run run_apr_injection || return 1
  for s in run_sql_generation run_sql_revision run_sql_selection; do
    say "  $s"; run "$s" || { say "  $s FAILED"; return 1; }
  done
  say "  export + score"; score_and_cost
  say "################ $1 DONE ################"
}

say "SPIDER: 4 arms, 502 questions each. 4.1-mini pair first, then luna."

IN_RATE=0.40e-6; OUT_RATE=1.60e-6
run_base 41m-spider-base
run_opt2 41m-spider-rap_opt2

IN_RATE=0.20e-6; OUT_RATE=1.20e-6
run_base spider-base
run_opt2 spider-rap_opt2

say "all four spider arms complete"
