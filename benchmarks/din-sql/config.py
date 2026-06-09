"""CLI argument parsing, validation, and auto-mapping for DIN-SQL.

Same flag set as BaseSQL (the two pipelines accept the same options); only the
program name and the pipeline tag emitted in log lines differ.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional


_BENCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BENCH_DIR not in sys.path:
    sys.path.insert(0, _BENCH_DIR)

from _common import datasets as _ds  # noqa: E402
from _common.cli_common import (  # noqa: E402
    add_common_args,
    default_cluster_filter,
    resolve_column_defaults,
    resolve_mapping_path,
    resolve_paths,
)
from _common.paths import default_mapping_path  # noqa: E402


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    """Build and parse the DIN-SQL CLI."""
    p = argparse.ArgumentParser(
        prog="dinsql",
        description="DIN-SQL: 4-stage NL2SQL pipeline (linking → classify → SQL gen → self-correct).",
    )
    add_common_args(p)
    return p.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    """Validate flag combinations; raise SystemExit on bad combos."""
    if args.cluster and not args.history_path:
        raise SystemExit(
            "--cluster requires --history_path (clusters are built from the sample CSV)."
        )
    # --cluster_filter defaults to args.cluster (see default_cluster_filter);
    # without --cluster it's a no-op (no cluster_res to filter on), so no validation needed.
    if args.view_adhoc:
        if not args.view:
            raise SystemExit("--view_adhoc requires --view.")
        if not args.use_linking:
            raise SystemExit("--view_adhoc requires --use_linking.")
    if args.view_relink:
        if not args.view:
            raise SystemExit("--view_relink requires --view.")
        if not args.use_linking:
            raise SystemExit("--view_relink requires --use_linking.")
        if args.view_adhoc:
            raise SystemExit("--view_relink and --view_adhoc are mutually exclusive.")
    if args.rename_v and not args.rename:
        raise SystemExit("--rename_v requires --rename.")
    if args.view_v and not args.view:
        raise SystemExit("--view_v requires --view.")
    if not (1 <= args.sample <= 100):
        raise SystemExit(f"--sample must be between 1 and 100, got {args.sample}")
    if args.sample != 100 and not args.history_path:
        raise SystemExit(
            "--sample <100 requires --history_path (sampling applies to the history CSV)."
        )


def apply_sample_auto_mapping(args: argparse.Namespace) -> None:
    """Auto-set --rename_v / --view_v / mapping path for --sample <100."""
    if args.sample == 100 or args.dataset not in ("bird", "spider"):
        return

    n = str(args.sample)
    rt_name = f"{args.dataset}_renamed_tables_{n}"
    rv_name = f"{args.dataset}_renamed_views_{n}"
    ov_name = f"{args.dataset}_org_views_{n}"

    missing = []
    if getattr(_ds, rt_name, None) is None:
        missing.append(f"module variable {rt_name!r}")
    if getattr(_ds, rv_name, None) is None:
        missing.append(f"module variable {rv_name!r}")
    if getattr(_ds, ov_name, None) is None:
        missing.append(f"module variable {ov_name!r}")
    map_path = default_mapping_path(args.dataset, args.sample)
    if not os.path.exists(map_path):
        missing.append(f"mapping file at {map_path}")
    if missing:
        raise SystemExit(
            f"--sample {args.sample} requires these to exist but they are missing: "
            + "; ".join(missing)
        )

    if args.rename and not args.rename_v:
        args.rename_v = rt_name
        print(f"[dinsql] [--sample {args.sample}] auto-set --rename_v={rt_name!r}")
    if args.view and not args.view_v:
        args.view_v = rv_name if args.rename else ov_name
        print(f"[dinsql] [--sample {args.sample}] auto-set --view_v={args.view_v!r}")


def resolve_rename_v_suffix(rename_v: Optional[str]) -> Optional[str]:
    if not rename_v:
        return None
    m = re.match(r"^(spider|bird)_renamed_tables(?:_(\w+))?$", rename_v)
    return m.group(2) if m else None


def resolve_view_v_suffix(view_v: Optional[str]) -> Optional[str]:
    if not view_v:
        return None
    m = re.match(r".+_(\d+)$", view_v)
    return m.group(1) if m else None


def lookup_module_list(name: str, flag: str) -> list:
    val = getattr(_ds, name, None)
    if val is None:
        raise SystemExit(
            f"{flag} {name!r} not found as a module-level variable in _common.datasets."
        )
    if not isinstance(val, list) or not all(isinstance(t, str) for t in val):
        raise SystemExit(
            f"{flag} {name!r} must be a list of strings; got {type(val).__name__}."
        )
    return val


__all__ = [
    "parse_args",
    "validate_args",
    "apply_sample_auto_mapping",
    "resolve_paths",
    "resolve_mapping_path",
    "resolve_column_defaults",
    "resolve_rename_v_suffix",
    "resolve_view_v_suffix",
    "lookup_module_list",
    "default_cluster_filter",
]
