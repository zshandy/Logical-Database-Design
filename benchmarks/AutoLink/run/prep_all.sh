#!/usr/bin/env bash
# Build the shared inputs for the paper's eight arms of one dataset
# (base a p r ap ar pr apr, as run_arm.sh names them).
#
#   ./prep_all.sh <dataset> [limit]
#
# generate_docs.py and embedding_docs.py rebuild EVERY db_name namespace found
# under resource/databases/sqlite/, so they must run once after all arms'
# dumps exist -- not per arm.
set -eu
PY="${PY:-python}"
cd "$(dirname "$0")" || exit 1

DS="${1:?dataset}"
LIMIT="${2:-}"
LIMIT_ARGS=""
[ -n "$LIMIT" ] && LIMIT_ARGS="--limit $LIMIT --stratify"

echo "=== prep: $DS ${LIMIT:+(pilot $LIMIT)} ==="

for spec in "base:" "a:--view --mode opt1" "p:--cluster --mode opt2" "r:--rename" "ap:--view --cluster --mode opt2" "ar:--rename --view --mode opt1" "pr:--rename --cluster --mode opt2" "apr:--rename --view --cluster --mode opt2"; do
  name="${spec%%:*}"; flags="${spec#*:}"
  echo; echo ">>> dumps + questions: $DS/$name"
  "$PY" -u prep_ldd_inputs.py --dataset "$DS" $flags --top_n 30 $LIMIT_ARGS
done

echo; echo ">>> column documents (all arms)"
"$PY" -u generate_docs.py

echo; echo ">>> embeddings + FAISS (all arms)"
"$PY" -u embedding_docs.py 2>&1 | grep -viE "it/s|^\s*$" | tail -4

echo; echo "=== prep done: $DS ==="
