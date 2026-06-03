"""Shared CLI plumbing — argparse fragments and post-parse path resolution.

The actual ``argparse.ArgumentParser`` lives in each pipeline (so help text
can be pipeline-specific), but the flag set, defaults, and the auto-resolution
of ``--csv_path`` / ``--db_path`` / ``--history_path`` / ``--mapping_path`` are
shared.
"""

from __future__ import annotations

import argparse
import os
from typing import Optional

from .paths import (
    default_csv_path,
    default_db_path,
    default_history_path,
    default_mapping_path,
)


def add_common_args(p: argparse.ArgumentParser) -> None:
    """Register the common flag set on a pipeline's argparse parser."""
    p.add_argument(
        "--dataset",
        choices=["spider", "bird"],
        default="spider",
        help="Dataset. Controls table/view lists, default paths, and log dir. "
             "Default: spider.",
    )
    p.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="Model name for stages 2/3 (and beyond). Any string starting with "
             "'gemini' uses Google GenAI; anything else uses OpenAI. "
             "Default: gpt-4.1-mini.",
    )
    p.add_argument(
        "--csv_path",
        default=None,
        help="Path to nl2sql input CSV. If omitted, auto-resolves to "
             "<LDD>/csvs/nl2sql_{dataset}.csv.",
    )
    p.add_argument(
        "--db_path",
        default=None,
        help="Path to the SQLite database file. If omitted, auto-resolves to "
             "<LDD>/databases/merged_{dataset}.sqlite.",
    )
    p.add_argument(
        "--history",
        action="store_true",
        help="Enable history mode. With no --history_path, defaults to "
             "<LDD>/csvs/sample_{dataset}.csv. Passing --history_path implies --history.",
    )
    p.add_argument(
        "--history_path",
        default=None,
        help="Path to sample/history CSV. Implies --history when provided.",
    )
    p.add_argument(
        "--sample",
        type=int,
        default=100,
        metavar="N",
        help="Integer 1..100; percent of the history CSV to use. <100 triggers "
             "a reproducible random sub-sample (seed=42). For --dataset bird, "
             "N<100 also auto-maps the bird_renamed_tables_N / _views_N variants "
             "and the name_mapping_bird_N.json mapping file when --rename_v / "
             "--view_v / --mapping_path are not explicitly set. Default 100.",
    )
    p.add_argument(
        "--rename",
        action="store_true",
        help="Use renamed_tables/renamed_views instead of org_tables/org_views.",
    )
    p.add_argument(
        "--rename_v",
        default=None,
        metavar="VAR",
        help="Override the renamed-tables list with a named module variable "
             "(e.g. bird_renamed_tables_0). Requires --rename.",
    )
    p.add_argument(
        "--view",
        action="store_true",
        help="Add matching views from the views pool to the schema per question.",
    )
    p.add_argument(
        "--view_v",
        default=None,
        metavar="VAR",
        help="Override the views pool with a named module variable. Requires --view.",
    )
    p.add_argument(
        "--view_adhoc",
        action="store_true",
        help="Ad-hoc view creation. Reads linked tables from --use_linking (stage 0), "
             "asks the LLM for a CREATE VIEW over them, and injects the view "
             "schema into later stages. Requires --view and --use_linking.",
    )
    p.add_argument(
        "--view_relink",
        action="store_true",
        help="Re-link mode. Reads linked tables from --use_linking, picks matching "
             "pre-defined views from the views pool, injects them into stage 1 "
             "and re-runs stage 1. Requires --view and --use_linking; mutually "
             "exclusive with --view_adhoc.",
    )
    p.add_argument(
        "--cluster",
        action="store_true",
        help="Inject matching clusters' common join paths into stage 2/3 prompts. "
             "With --history also restricts top-K history retrieval to questions "
             "in the matched clusters.",
    )
    p.add_argument(
        "--cluster_filter",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Restrict the stage-2/3 schema to only tables in matched clusters. "
             "Defaults to ON whenever --cluster is set; pass --no-cluster_filter "
             "to inject cluster join paths without filtering the schema. "
             "Has no effect when --cluster is off.",
    )
    p.add_argument(
        "--use_linking",
        default=None,
        metavar="COLUMN",
        help="Column name in the input CSV that already contains schema links. "
             "When set, the stage-1 linking LLM call is skipped.",
    )
    p.add_argument(
        "--mapping_path",
        default=None,
        help="Path to the name-mapping JSON. Only used when --rename is set. "
             "If omitted, auto-resolves to <LDD>/mapping_files/name_mapping_{dataset}.json.",
    )
    p.add_argument(
        "--per_db",
        action="store_true",
        help="Per-db mode: restrict base schema, views pool, clusters, and history "
             "retrieval to each question's db_id (read from the 'db_id' column).",
    )
    p.add_argument(
        "--rows",
        default=None,
        metavar="SPEC",
        help="Row selection. Either 'N' for the first N rows, or 'START:END' "
             "for a python-style half-open slice.",
    )
    p.add_argument(
        "--question_col",
        default="question",
        metavar="COLUMN",
        help="Name of the input-CSV column holding the natural-language question. "
             "Default: 'question'.",
    )
    p.add_argument(
        "--sql_col",
        default="SQL",
        metavar="COLUMN",
        help="Name of the input-CSV column holding the (optional) ground-truth SQL. "
             "Default: 'SQL'. Pipelines that don't read gold SQL ignore this.",
    )


def default_cluster_filter(args: argparse.Namespace) -> None:
    """Default ``--cluster_filter`` to the value of ``--cluster`` when not explicitly
    set (``BooleanOptionalAction`` leaves it as ``None``). Mutates ``args`` in place.
    """
    if getattr(args, "cluster_filter", None) is None:
        args.cluster_filter = bool(getattr(args, "cluster", False))


def resolve_paths(args: argparse.Namespace, pipeline_tag: str = "pipeline") -> None:
    """Fill in default paths for ``--csv_path`` / ``--db_path`` / ``--history_path`` /
    ``--mapping_path`` based on ``--dataset`` and ``--sample``.

    Mutates ``args`` in place. Pass ``pipeline_tag`` (e.g. ``"basesql"``) so
    log lines identify the source.
    """
    sample = getattr(args, "sample", 100)

    if args.csv_path is None:
        args.csv_path = default_csv_path(args.dataset, sample)
        print(f"[{pipeline_tag}] --csv_path auto-resolved to {args.csv_path}")
    if args.db_path is None:
        args.db_path = default_db_path(args.dataset)
        print(f"[{pipeline_tag}] --db_path auto-resolved to {args.db_path}")

    # History gating: --history_path implies --history; --history alone uses
    # the default file; neither flag → history disabled.
    if args.history_path:
        args.history = True
    elif args.history:
        args.history_path = default_history_path(args.dataset, sample)
        if not os.path.exists(args.history_path):
            raise SystemExit(
                f"--history requested but default sample file not found at "
                f"{args.history_path}. Pass --history_path explicitly or drop --history."
            )
        print(f"[{pipeline_tag}] --history_path auto-resolved to {args.history_path}")


def resolve_mapping_path(
    args: argparse.Namespace,
    pipeline_tag: str = "pipeline",
) -> Optional[str]:
    """Return the mapping JSON path for ``--rename`` mode.

    If ``args.mapping_path`` is set, returns it; otherwise auto-resolves from
    ``--dataset`` and ``--sample``. Returns ``None`` if ``--rename`` is unset.
    """
    if not getattr(args, "rename", False):
        return None
    if args.mapping_path:
        return args.mapping_path
    sample = getattr(args, "sample", 100)
    path = default_mapping_path(args.dataset, sample)
    print(f"[{pipeline_tag}] --mapping_path auto-resolved to {path}")
    args.mapping_path = path
    return path
