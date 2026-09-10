"""Produce Spider's missing renamed-table history column using LDD's own rewriter.

Why this exists
---------------
Spider has no history SQL column written against ``spider_renamed_tables``:

    SQL              -> spider_org_tables      100.0%
    renamed_SQL      -> spider_ORG_tables       96.4%   (descriptive columns only,
                                                         plus 3 tables in a THIRD
                                                         naming family)
    renamed_view_SQL -> renamed tables + views  55/45%  (this is the +A history)

BIRD fills that slot with ``workload_updated_SQL``. Rather than reconstruct it
with regex substitution (tried, and it only reproduced BIRD's ground truth 28.9%
of the time), this calls ``prep_database.rewrite_history_sqls`` -- the same
LLM-rewrite-with-verification path that produced BIRD's column. It executes both
the original and rewritten SQL, compares result sets, checks that only renamed
objects are referenced, and retries failures.

Run against BIRD first with --validate to confirm the wiring reproduces
``workload_updated_SQL``, then against Spider for real.

Usage
-----
    python make_spider_renamed_history.py --dataset bird   --dry_run
    python make_spider_renamed_history.py --dataset spider
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from argparse import Namespace

# Vendored under <LDD>/benchmarks/, so the repo root is derived from this
# file's location rather than hardcoded -- the original absolute path only
# worked on the machine the experiments were run on.
LDD_BENCH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir))
sys.path.insert(0, LDD_BENCH)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ldd_config as C  # noqa: E402
from _common.llm import ensure_gemini, ensure_openai  # noqa: E402
from prep_database import rewrite_history_sqls  # noqa: E402

MAPPING = {
    "bird": os.path.join(C.LDD, "mapping_files", "name_mapping_bird.json"),
    "spider": os.path.join(C.LDD, "mapping_files", "name_mapping_spider.json"),
}

# Output column per dataset. BIRD already has workload_updated_SQL, so a BIRD run
# is only ever a wiring check and writes to a scratch column.
OUT_COL = {
    "bird": "autolink_check_renamed_SQL",
    "spider": "workload_updated_SQL",
}


def build_args(dataset: str, model: str, retries: int, out_col: str) -> Namespace:
    """The exact fields rewrite_history_sqls and its helpers read off args."""
    return Namespace(
        db_path=C.MERGED_DB[dataset],
        history_path=C.SAMPLE_CSV[dataset],
        question_col="question",
        sql_col="SQL",
        renamed_sql_col=out_col,
        rewrite_max_retries=retries,
        model=model,
        max_tokens=32000,
        rename=True,
        # cluster/view phases are not reached from this entry point, but the
        # helpers reference these attributes, so they must exist.
        cluster_col=None,
        cluster_sql_col=None,
        min_frequency=5,
        min_tables=2,
        output_mapping_path=None,
    )


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=["bird", "spider"], default="spider")
    p.add_argument("--model", default="gpt-4.1-mini")
    p.add_argument("--rewrite_max_retries", type=int, default=5)
    p.add_argument("--out_col", default=None,
                   help="override the output column name")
    p.add_argument("--dry_run", action="store_true",
                   help="report what would run, touch nothing")
    a = p.parse_args()

    out_col = a.out_col or OUT_COL[a.dataset]
    with open(MAPPING[a.dataset], encoding="utf-8") as f:
        mapping = json.load(f)

    lists = C.load_object_lists()
    rt = {x.lower() for x in lists[f"{a.dataset}_renamed_tables"]}
    targets = set(mapping["table_to_view"].values())
    landing = sum(1 for t in targets if t.lower() in rt)

    print("=" * 66)
    print(f"[spider-history] dataset      : {a.dataset}")
    print(f"[spider-history] db           : {os.path.basename(C.MERGED_DB[a.dataset])}")
    print(f"[spider-history] history CSV  : {os.path.basename(C.SAMPLE_CSV[a.dataset])}")
    print(f"[spider-history] mapping      : {os.path.basename(MAPPING[a.dataset])}")
    print(f"[spider-history] output column: {out_col}")
    print(f"[spider-history] table_to_view: {len(targets)} targets, "
          f"{landing} land in {a.dataset}_renamed_tables")
    print("=" * 66)

    if landing != len(targets):
        print(f"  WARNING: {len(targets)-landing} mapping target(s) are NOT in "
              f"{a.dataset}_renamed_tables — the rewrite would produce names the "
              f"arm does not expose.")

    if a.dry_run:
        print("\n--dry_run: nothing written.")
        print(f"  would add: {out_col}, {out_col}_result, "
              f"gt_{out_col.replace('_SQL','')}_tables")
        return

    # prep_database's own main() does this before the rewrite phase; calling the
    # function as a library skips that, and without it every row fails with
    # "OpenAI client not initialized" and silently falls back to the original SQL.
    if a.model.startswith("gemini"):
        ensure_gemini()
    else:
        ensure_openai()
    print(f"[spider-history] LLM client initialized for {a.model}")

    args = build_args(a.dataset, a.model, a.rewrite_max_retries, out_col)
    cache_dir = os.path.join(C.HERE, "cache", f"history_rewrite_{a.dataset}")
    os.makedirs(cache_dir, exist_ok=True)
    stem = f"merged_{a.dataset}"

    # writes <out_col>, <out_col>_result, gt_<stem>_tables back into the CSV,
    # with its own .bak.<ts> backup
    rewrite_history_sqls(args, mapping, args.db_path, cache_dir, stem)


if __name__ == "__main__":
    main()
