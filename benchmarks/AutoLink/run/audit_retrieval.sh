#!/usr/bin/env bash
# Contamination audit: is each arm's stored top-30 the TRUE top-30?
#
# retrieve_topk_schema.get_next_k_results passes the arm's accumulated
# cache["used_indices"] as excluded_indices, and nothing resets cache/ or
# status/. So a second retrieval on the same log dir returns the NEXT 30
# columns rather than the top 30. Arms whose retrieval ran once are fine;
# arms whose gpu phase re-ran are shifted.
#
# This re-runs retrieval into a pristine scratch dir (empty cache) for each
# arm and diffs the result against what the arm actually used. GPU only, no
# API spend.
set -u
cd "$(dirname "$0")" || exit 1
PY="${PY:-python}"
SCRATCH=audit_scratch
mkdir -p "$SCRATCH" runlogs

ARMS_BIRD="base a p rbase opt2 ar pr ropt2"
ARMS_SPIDER="base a p rbase opt2 ar pr ropt2"

suffix_of () {   # dataset arm -> Arm.suffix
  "$PY" -c "
import ldd_config as C
f='$2'
kw=dict(base=dict(), a=dict(view=True,mode='opt1'), p=dict(cluster=True,mode='opt2'),
        rbase=dict(rename=True), opt2=dict(view=True,cluster=True,mode='opt2'),
        ar=dict(rename=True,view=True,mode='opt1'),
        pr=dict(rename=True,cluster=True,mode='opt2'),
        ropt2=dict(rename=True,view=True,cluster=True,mode='opt2'))[f]
a=C.Arm(dataset='$1',**kw); a.validate(); print(a.suffix)"
}

for DS in bird spider; do
  eval "ARMS=\$ARMS_${DS^^}"
  for ARM in $ARMS; do
    SFX=$(suffix_of "$DS" "$ARM") || continue
    LOG="log_${DS}${SFX}"
    QF="questions_${DS}${SFX}.json"
    OUTD="$SCRATCH/${DS}${SFX}"
    if [ ! -f "$LOG/initial_candidates.json" ]; then
      echo "SKIP  $DS/$ARM  (no candidates)"; continue
    fi
    if [ ! -f "$QF" ]; then
      echo "SKIP  $DS/$ARM  (no questions file $QF)"; continue
    fi
    if [ -f "$OUTD/initial_candidates.json" ]; then
      echo "HAVE  $DS/$ARM  (fresh retrieval already done)"; continue
    fi
    rm -rf "$OUTD"; mkdir -p "$OUTD"
    echo ">>> $DS/$ARM  fresh retrieval -> $OUTD"
    "$PY" -u retrieve_topk_schema.py --log_path "$OUTD" --top_n 30 \
          --data_file "$QF" > "runlogs/audit_${DS}_${ARM}.log" 2>&1 \
      || echo "!!  $DS/$ARM retrieval FAILED (see runlogs/audit_${DS}_${ARM}.log)"
  done
done
echo "################ audit retrievals done $(date) ################"
