#!/usr/bin/env bash
# Queue for the remaining LDD arms, MAXPAR arms in flight at a time.
#
#   ./run_queue.sh [MAXPAR]      default 2
#
# Sizing: one arm costs ~8.5 GB of Windows commit charge in candidate
# generation and ~10-12 GB in the agent loop (2 BGE + FAISS workers). The
# machine's commit limit is 56.3 GB. Tonight's WinError 1455 / std::bad_alloc
# failures happened at 46-50 GB committed, where 37.8 GB was held by non-
# experiment processes (a leaked dwm, VSCode, Chrome) rather than by the run.
# On a freshly booted machine the baseline is ~10 GB, so 2 arms (~24 GB) has
# wide margin and 3 would likely fit.
#
# Each arm is rebuilt from pristine retrieval rather than resumed mid-pipeline:
# apply_apr and add_id mutate initial_candidates.json in place, so re-entering
# at step 3 after a crash is not obviously idempotent. The gpu phase costs ~45 s
# of local GPU, which is cheaper than reasoning about that.
#
# Resumable: an arm that finished its api phase drops a marker in runlogs/ and
# is skipped on the next invocation, so this can be re-run after a reboot.
set -u
cd "$(dirname "$0")" || exit 1
PY="${PY:-python}"
MAXPAR="${1:-2}"
mkdir -p runlogs

# The 8 arms still outstanding after the retrieval-contamination audit, BIRD
# first. Four had contaminated retrieval (cache was non-empty when their gpu
# phase re-ran, so they got the NEXT 30 columns instead of the top 30) and
# their old output is archived under log_*_contaminated; three never finished;
# spider:ropt2 is a deliberate replicate of a clean, complete arm, kept
# alongside log_*_run1 to size run-to-run variance on its -0.2 result.
#
#   bird:a  bird:p  bird:rbase   contaminated -> full re-run
#   bird:pr                      clean, hung at 730/767 -> resumes
#   spider:rbase                 contaminated -> full re-run
#   spider:ar  spider:pr         clean, agent loop already complete -> resume at step 8
#   spider:ropt2                 replicate
QUEUE="bird:a bird:p bird:rbase bird:pr
       spider:rbase spider:ar spider:pr spider:ropt2"

# ARMS=... overrides the list, e.g. ARMS="bird:p" ./run_queue.sh 1 to run a
# single arm alongside a queue that is already in flight.
QUEUE="${ARMS:-$QUEUE}"

# arm -> prep_ldd_inputs flags. The db_names of base/rbase/opt1/opt2 and their
# +R forms were created by the original prep_all.sh and need no prep.
prep_flags () {
  case "$1" in
    a)  echo "--view --mode opt1" ;;
    p)  echo "--cluster --mode opt2" ;;
    ar) echo "--rename --view --mode opt1" ;;
    pr) echo "--rename --cluster --mode opt2" ;;
    *)  echo "-" ;;
  esac
}

run_one () {
  local ds="$1" arm="$2"
  local tag="${ds}_${arm}"
  local marker="runlogs/.done_${tag}"
  local flags; flags="$(prep_flags "$arm")"

  if [ -f "$marker" ]; then
    echo "[queue] $ds/$arm already done ($(cat "$marker")) -- skipping"
    return 0
  fi

  echo "[queue] >>> $ds/$arm start $(date '+%m-%d %H:%M:%S')"

  if [ "$flags" != "-" ]; then
    if ! "$PY" -u prep_ldd_inputs.py --dataset "$ds" $flags \
            > "runlogs/q_prep_${tag}.log" 2>&1; then
      echo "[queue] !! $ds/$arm PREP FAILED -- runlogs/q_prep_${tag}.log"; return 1
    fi
  fi

  if ! ./run_arm.sh "$ds" "$arm" gpu 2 > "runlogs/q_gpu_${tag}.log" 2>&1; then
    echo "[queue] !! $ds/$arm GPU FAILED -- runlogs/q_gpu_${tag}.log"; return 1
  fi
  grep -E "mean columns after|views injected|cluster tables" \
       "runlogs/q_gpu_${tag}.log" | sed "s|^|[queue] $ds/$arm   |"

  # AGENT_PROCS=1 by default. Each agent-loop worker loads BGE+torch and
  # reserves ~4 GB of Windows COMMIT (not RSS); at MAXPAR=2 two workers per arm
  # is 4 of them against a 52.2 GB commit limit, and the loser dies at spawn
  # with WinError 1455. The parent then blocks forever joining a dead child, so
  # the arm silently stalls at exactly half its instances instead of failing.
  if ! SKIP_EXPORT=1 ./run_arm.sh "$ds" "$arm" api "${AGENT_PROCS:-1}" \
          > "runlogs/q_api_${tag}.log" 2>&1; then
    echo "[queue] !! $ds/$arm API FAILED -- runlogs/q_api_${tag}.log"; return 1
  fi

  # An exit code of 0 is not proof of completion: killing run_arm.sh's shells
  # makes it return 0, which once marked a 730/767 arm as DONE. Require the
  # actual per-question selections before writing the marker.
  local want; want=$([ "$ds" = "bird" ] && echo 767 || echo 502)
  local log; log="log_${ds}$("$PY" -c "
import ldd_config as C
kw=dict(base=dict(), a=dict(view=True,mode='opt1'), p=dict(cluster=True,mode='opt2'),
        rbase=dict(rename=True), opt2=dict(view=True,cluster=True,mode='opt2'),
        ar=dict(rename=True,view=True,mode='opt1'),
        pr=dict(rename=True,cluster=True,mode='opt2'),
        ropt2=dict(rename=True,view=True,cluster=True,mode='opt2'))['$arm']
print(C.Arm(dataset='$ds',**kw).suffix)")"
  local got; got=$(ls -1 "$log/sql_selection/final" 2>/dev/null | wc -l)
  if [ "$got" -lt "$want" ]; then
    echo "[queue] !! $ds/$arm INCOMPLETE: $got/$want selections -- no marker written"
    return 1
  fi

  date '+%m-%d %H:%M:%S' > "$marker"
  echo "[queue] <<< $ds/$arm DONE $(date '+%m-%d %H:%M:%S')  ($got/$want)"
  return 0
}

echo "################ queue start $(date)  MAXPAR=$MAXPAR ################"
running=0
for spec in $QUEUE; do
  ds="${spec%%:*}"; arm="${spec##*:}"
  run_one "$ds" "$arm" &
  running=$((running + 1))
  if [ "$running" -ge "$MAXPAR" ]; then
    # `wait -n` yields the FINISHED job's exit status, so a failing arm makes
    # it return non-zero. Chaining `|| wait` here would then block on every
    # remaining job and silently collapse the queue to serial, so swallow the
    # status instead -- failures are recorded per-arm by run_one.
    wait -n 2>/dev/null || true
    running=$((running - 1))
  fi
done
wait

echo
echo "################ queue finished $(date) ################"
for spec in $QUEUE; do
  ds="${spec%%:*}"; arm="${spec##*:}"
  if [ -f "runlogs/.done_${ds}_${arm}" ]; then
    echo "  OK     $ds/$arm  $(cat runlogs/.done_${ds}_${arm})"
  else
    echo "  FAILED $ds/$arm"
  fi
done
echo "Exports were SKIPPED -- run export_results.py serially afterwards."
