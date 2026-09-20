#!/usr/bin/env bash
# Run one LDD arm end-to-end through AutoLink (schema linking + SQL generation).
#
#   ./run_arm.sh <dataset> <arm> [limit]
#     dataset : bird | spider
#     arm     : base | opt1 | opt2
#     limit   : optional question cap (pilot); omit for the full set
#
# Documents + embeddings are built once for ALL arms by prep_all.sh, because
# generate_docs.py / embedding_docs.py rebuild every db_name namespace at once.
set -u
PY="${PY:-python}"
cd "$(dirname "$0")" || exit 1

DS="${1:?dataset}"
ARM="${2:?arm}"
PHASE="${3:-all}"          # gpu | api | all
AGENT_PROCS="${4:-2}"      # processes in the agent loop (each loads BGE)

TOP_N=30
CANDIDATES=3
TASK=ldd
WORKERS_GEN=6
WORKERS_EXEC=4
WORKERS_REV=4
WORKERS_SEL=8

case "$ARM" in
  base) FLAGS="" ;;
  opt1) FLAGS="--view --cluster --mode opt1" ;;
  opt2) FLAGS="--view --cluster --mode opt2" ;;
  # +R variants: rename swaps the exposed universe to <ds>_renamed_tables /
  # <ds>_renamed_views and the history to workload_updated_SQL.
  rbase) FLAGS="--rename" ;;
  ropt1) FLAGS="--rename --view --cluster --mode opt1" ;;
  ropt2) FLAGS="--rename --view --cluster --mode opt2" ;;
  # single-operator and pair arms. +A / +A+R are necessarily opt1:
  # Arm.validate() rejects opt2 without cluster, because opt2 IS the
  # re-retrieve-inside-matched-clusters step.
  a)     FLAGS="--view --mode opt1" ;;
  p)     FLAGS="--cluster --mode opt2" ;;
  ar)    FLAGS="--rename --view --mode opt1" ;;
  pr)    FLAGS="--rename --cluster --mode opt2" ;;
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

echo "################################################################"
echo "# arm      : $DS / $ARM"
echo "# suffix   : $SUFFIX"
echo "# log dir  : $LOG"
echo "# questions: $QFILE"
echo "# started  : $(date)"
echo "################################################################"

step () { echo; echo ">>> [$DS/$ARM] $*"; }

# PHASE=seeded: retrieval was materialised by seed_arm.py from a donor arm
# sharing the same exposed universe, so step 1 must NOT run (it would
# overwrite initial_candidates.json). apply_apr still does.
if [ "$PHASE" = "seeded" ] && [ -n "$FLAGS" ]; then
  step "2. +A/+P injection ($ARM) [seeded retrieval]"
  "$PY" -u apply_apr.py --dataset "$DS" $FLAGS --top_n "$TOP_N" || exit 1
fi

if [ "$PHASE" = "gpu" ] || [ "$PHASE" = "all" ]; then
# retrieve_topk_schema.get_next_k_results passes the arm's accumulated
# cache["used_indices"] as excluded_indices, so retrieval is STATEFUL: run it a
# second time on the same log dir and it returns the NEXT top_n columns instead
# of the top_n. Nothing in the pipeline resets that state, so a re-run silently
# hands the arm a schema of near-irrelevant columns. Clearing cache/ + status/
# is what makes "step 1" mean the same thing on every invocation.
step "1. initial retrieval (top-$TOP_N)"
if [ -d "$LOG/cache" ] || [ -d "$LOG/status" ]; then
  echo "  clearing prior retrieval state ($(ls -1 "$LOG/cache" 2>/dev/null | wc -l) cache, $(ls -1 "$LOG/status" 2>/dev/null | wc -l) status)"
  rm -rf "$LOG/cache" "$LOG/status"
fi
"$PY" -u retrieve_topk_schema.py --log_path "$LOG" --top_n "$TOP_N" \
      --data_file "$QFILE" || exit 1

# Gate: a pristine retrieval consumes exactly top_n columns per instance. Any
# instance with used_count > top_n means the cache was not empty and this arm
# is running on shifted columns -- fail here rather than spend API on it.
"$PY" - "$LOG" "$TOP_N" <<'PYEOF' || exit 1
import json, os, sys
log, top_n = sys.argv[1], int(sys.argv[2])
sdir = os.path.join(log, "status")
bad = []
for f in os.listdir(sdir):
    d = json.load(open(os.path.join(sdir, f), encoding="utf-8"))
    if d.get("used_count") != top_n:
        bad.append((f, d.get("used_count")))
if bad:
    print(f"  !! RETRIEVAL NOT PRISTINE: {len(bad)} instances with used_count != {top_n}")
    for f, n in bad[:5]:
        print(f"       {f}: used_count={n}")
    sys.exit(1)
print(f"  retrieval verified pristine: {len(os.listdir(sdir))} instances, used_count={top_n}")
PYEOF

if [ -n "$FLAGS" ]; then
  step "2. +A/+P injection ($ARM)"
  "$PY" -u apply_apr.py --dataset "$DS" $FLAGS --top_n "$TOP_N" || exit 1
fi
fi   # end gpu phase

if [ "$PHASE" = "gpu" ]; then
  echo; echo "################ gpu phase done $DS/$ARM  $(date) ################"
  exit 0
fi

step "3. id/name/code sweep"
"$PY" -u add_id.py --log_path "$LOG" || exit 1

step "4. initial schema prompts"
"$PY" -u generate_schema.py --log_path "$LOG" --is_initial || exit 1

step "5. agent loop (DeepSeek-V3, max 6 turns, $AGENT_PROCS procs)"
"$PY" -u complete_schema.py --log_path "$LOG" --num_threads "$AGENT_PROCS" || exit 1

step "6. postprocess"
"$PY" -u postprocess.py --log_path "$LOG" || exit 1

step "7. final schema prompts"
"$PY" -u generate_schema.py --log_path "$LOG" || exit 1

step "8. candidate generation ($CANDIDATES x DeepSeek-R1)"
"$PY" -u sql_generation.py --num_workers "$WORKERS_GEN" \
      --num_candidates "$CANDIDATES" --data_file "$QFILE" \
      --schema_dir "$LOG/final_schema_prompts" --log_path "$LOG" --task "$TASK" || exit 1

step "9. candidate execution"
"$PY" -u sql_execution.py --num_workers "$WORKERS_EXEC" \
      --num_candidates "$CANDIDATES" --data_file "$QFILE" \
      --log_path "$LOG" --task "$TASK" || exit 1

step "10. revision of failed candidates (max 2 attempts)"
"$PY" -u sql_revise.py --num_workers "$WORKERS_REV" \
      --num_candidates "$CANDIDATES" --data_file "$QFILE" \
      --schema_dir "$LOG/final_schema_prompts" --log_path "$LOG" --task "$TASK" || exit 1

step "11. selection (execution majority + pairwise tiebreak)"
"$PY" -u sql_selection.py --log_path "$LOG" \
      --num_candidates "$CANDIDATES" --workers "$WORKERS_SEL" --task "$TASK" || exit 1

# export_results.py does a read-modify-write of csvs/nl2sql_<ds>.csv. Three
# concurrent arms would race and silently drop each other's columns, so the
# driver sets SKIP_EXPORT=1 and runs the exports serially afterwards.
if [ "${SKIP_EXPORT:-0}" = "1" ]; then
  echo; echo ">>> [$DS/$ARM] 12. export SKIPPED (SKIP_EXPORT=1) -- run serially"
  echo "################ done $DS/$ARM  $(date) ################"
  exit 0
fi

step "12. score + export to nl2sql_${DS}.csv"
"$PY" -u export_results.py --dataset "$DS" $FLAGS --task "$TASK" || exit 1

echo
echo "################ done $DS/$ARM  $(date) ################"
