"""View-name parsing and matching utilities."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence

# Base tables for pool views whose names do not encode them -- e.g. ASR's
# free-form catalogue (``avg_enrollment_by_charter_status``). Filled only by
# ``--view_bases_from_db``; empty otherwise, so name parsing is unchanged.
_VIEW_BASES: Dict[str, List[str]] = {}


def register_view_bases(mapping: Dict[str, Sequence[str]]) -> None:
    """Record ``{view_name: [base tables]}`` resolved from view definitions."""
    _VIEW_BASES.update({k: list(v) for k, v in mapping.items()})


def parse_view_base_tables(view_name: str) -> List[str]:
    """Extract base tables from a view name. Handles three shapes:

      - ``cluster<N>_<t1>_join_<t2>(_join_<tN>)*``
      - ``workload_updated_cluster<N>_<t1>_join_<t2>(_join_<tN>)*``
      - bare ``<t1>_join_<t2>(_join_<tN>)*``  (no cluster prefix, e.g. ``bird_org_views_50``)

    An optional trailing ``_view`` (single-table views like ``income_view``) is stripped.
    """
    if view_name in _VIEW_BASES:
        return list(_VIEW_BASES[view_name])
    m = re.match(r"^(?:workload_updated_)?cluster\d+_(.+)$", view_name)
    core = m.group(1) if m else view_name
    if core.endswith("_view"):
        core = core[: -len("_view")]
    return core.split("_join_") if core else []


def find_matching_views(
    views_pool: Sequence[str],
    retrieved_tables: Iterable[str],
) -> List[str]:
    """Return all views from the pool that contain at least one of retrieved_tables."""
    rt_lower = {str(t).lower() for t in retrieved_tables}
    out: List[str] = []
    for v in views_pool:
        bases = parse_view_base_tables(v)
        if any(b.lower() in rt_lower for b in bases):
            out.append(v)
    return out
