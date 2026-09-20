#!/usr/bin/env bash
# Finish an arm whose agent loop was cut short, then rebuild everything downstream.
#
#   ./resume_arm.sh <dataset> <arm> [agent_procs]
#
# complete_schema.py resumes by skipping instances that already have a
# candidates/<id>.json, so it only processes what is missing. Everything after
# the agent loop is regenerated from scratch, because postprocess/final schemas/
# generation were built from an incomplete candidate set.
set -u
PY="${PY:-python}"
cd "$(dirname "$0")" || exit 1

DS="${1:?dataset}"
ARM="${2:?arm}"
PROCS="${3:-2}"
TOP_N=30; CANDIDATES=3; TASK=ldd

case "$ARM" in
  base) FLAGS="" ;;
  opt1) FLAGS="--view --cluster --mode opt1" ;;
  opt2) FLAGS="--view --cluster --mode opt2" ;;
  # +R variants: rename swaps the exposed universe to <ds>_renamed_tables /
  # <ds>_renamed_views and the history to workload_updated_SQL.
  rbase) FLAGS="--rename" ;;
  ropt1) FLAGS="--rename --view --cluster --mode opt1" ;;
  ropt2) FLAGS="--rename --view --cluster --mode opt2" ;;
  *) echo "unknown arm $ARM"; exit 1 ;;
esac

SUFFIX=$("$PY" -c "
import ldd_config as C
f='$FLAGS'
a=C.Arm(dataset='$DS', rename='--rename' in f,
        view='--view' in f, cluster='--cluster' in f,
        mode=('opt2' if 'opt2' in f else 'opt1'))
print(a.suffix)")
LOG="log_${DS}${SUFFIX}"
QFILE="questions_${DS}${SUFFIX}.json"

n_have=$(ls "$LOG/candidates" 2>/dev/null | wc -l)
n_want=$("$PY" -c "import json;print(len(json.load(open('$QFILE',encoding='utf-8'))))")
echo "################################################################"
echo "# resume $DS/$ARM   candidates $n_have / $n_want   procs=$PROCS"
echo "# started $(date)"
echo "################################################################"

step () { echo; echo ">>> [resume $DS/$ARM] $*"; }

# add_id.py / generate_schema --is_initial produce unfilled_pre_rule.json and
# schema_prompts/, which complete_schema.py requires; a fresh arm has neither.
if [ ! -d "$LOG/schema_prompts" ] || [ ! -f "$LOG/unfilled_pre_rule.json" ]; then
  step "3-4. id/name/code sweep + initial schema prompts"
  "$PY" -u add_id.py --log_path "$LOG" || exit 1
  "$PY" -u generate_schema.py --log_path "$LOG" --is_initial || exit 1
fi

step "5. agent loop (finishing the remainder)"
"$PY" -u complete_schema.py --log_path "$LOG" --num_threads "$PROCS" || exit 1

n_now=$(ls "$LOG/candidates" 2>/dev/null | wc -l)
echo ">>> candidates now: $n_now / $n_want"

step "clearing downstream artifacts built from the incomplete set"
rm -rf "$LOG/sql_gen" "$LOG/sql_revise" "$LOG/sql_selection" \
       "$LOG/final_schema_prompts" 2>/dev/null || true

step "6. postprocess"
"$PY" -u postprocess.py --log_path "$LOG" || exit 1

step "7. final schema prompts"
"$PY" -u generate_schema.py --log_path "$LOG" || exit 1

step "8. candidate generation ($CANDIDATES x DeepSeek-R1)"
"$PY" -u sql_generation.py --num_workers 6 --num_candidates "$CANDIDATES" \
      --data_file "$QFILE" --schema_dir "$LOG/final_schema_prompts" \
      --log_path "$LOG" --task "$TASK" || exit 1

step "9. candidate execution"
"$PY" -u sql_execution.py --num_workers 4 --num_candidates "$CANDIDATES" \
      --data_file "$QFILE" --log_path "$LOG" --task "$TASK" || exit 1

step "10. revision"
"$PY" -u sql_revise.py --num_workers 4 --num_candidates "$CANDIDATES" \
      --data_file "$QFILE" --schema_dir "$LOG/final_schema_prompts" \
      --log_path "$LOG" --task "$TASK" || exit 1

step "11. selection"
"$PY" -u sql_selection.py --log_path "$LOG" --num_candidates "$CANDIDATES" \
      --workers 8 --task "$TASK" || exit 1

step "12. score + export"
"$PY" -u export_results.py --dataset "$DS" $FLAGS --task "$TASK" || exit 1

echo
echo "################ resume done $DS/$ARM  $(date) ################"
