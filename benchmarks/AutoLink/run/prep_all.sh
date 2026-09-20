#!/usr/bin/env bash
# Build the shared inputs for all three arms of one dataset.
#
#   ./prep_all.sh <dataset> [limit]
#
# generate_docs.py and embedding_docs.py rebuild EVERY db_name namespace found
# under resource/databases/sqlite/, so they must run once after all three arms'
# dumps exist -- not per arm.
set -eu
PY="${PY:-python}"
cd "$(dirname "$0")" || exit 1

DS="${1:?dataset}"
LIMIT="${2:-}"
LIMIT_ARGS=""
[ -n "$LIMIT" ] && LIMIT_ARGS="--limit $LIMIT --stratify"

echo "=== prep: $DS ${LIMIT:+(pilot $LIMIT)} ==="

for spec in "base:" "opt1:--view --cluster --mode opt1" "opt2:--view --cluster --mode opt2"             "rbase:--rename" "ropt1:--rename --view --cluster --mode opt1"             "ropt2:--rename --view --cluster --mode opt2"; do
  name="${spec%%:*}"; flags="${spec#*:}"
  echo; echo ">>> dumps + questions: $DS/$name"
  "$PY" -u prep_ldd_inputs.py --dataset "$DS" $flags --top_n 30 $LIMIT_ARGS
done

echo; echo ">>> column documents (all arms)"
"$PY" -u generate_docs.py

echo; echo ">>> embeddings + FAISS (all arms)"
"$PY" -u embedding_docs.py 2>&1 | grep -viE "it/s|^\s*$" | tail -4

echo; echo "=== prep done: $DS ==="
