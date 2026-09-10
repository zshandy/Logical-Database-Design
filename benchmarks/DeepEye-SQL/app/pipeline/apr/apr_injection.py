"""Stage 5.5 -- the LDD +A/+P injection, between schema linking and generation.

Reads the schema-linking snapshot, writes its own. Never mutates its input, so
re-running cannot double-inject.

What it does, per question
--------------------------
  1. clusters   = find_all_clusters_for_tables(linked tables)      [LDD helper]
  2. +P         add every column of every matched cluster table
  3. +A         add every column of each matched cluster view
  4.            re-run filter_used_database_schema -- DeepEye's own closure, so
                PK/FK completion is applied to the injected objects too
  5. +P         Common Join Paths for the generation prompts
  6. +A/+P      re-select the history examples: restrict the ranked pool to
                matched-cluster questions (+P), render the view SQL column (+A)

Why the source schema has to be rebuilt here
--------------------------------------------
Steps 1-5 run with an object scope of tables only, so the item's schema dict has
no views in it at all. filter_used_database_schema silently drops any name it
cannot find, so injecting view columns against that dict would be a no-op. The
stage therefore loads the full (tables + views) schema once and merges it under
the item's value-retrieval schema, which preserves the retrieved value examples
on the base columns while making view columns resolvable.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Vendored under <LDD>/benchmarks/, so the repo root is derived from this
# file's location rather than hardcoded -- the original absolute path only
# worked on the machine the experiments were run on.
LDD_BENCH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, os.pardir))
if LDD_BENCH not in sys.path:
    sys.path.insert(0, LDD_BENCH)

from _common.clusters import find_all_clusters_for_tables  # noqa: E402
from _common.history import build_clusters_from_history  # noqa: E402

from app.db_utils import filter_used_database_schema  # noqa: E402
from app.ldd.config import SAMPLE_CSV, Arm  # noqa: E402
from app.ldd.history import load_history, render_sql, sql_variants  # noqa: E402
from app.ldd.object_scope import set_object_scope  # noqa: E402
from app.logger import logger  # noqa: E402


def views_for_clusters(cluster_ids: Sequence[int], all_views: Sequence[str],
                       prefix: str) -> List[str]:
    """Views whose name starts with ``<prefix><cluster_id>_``.

    Both view lists are numbered 1..64 (bird) / 1..57 (spider), so this is a
    clean id join. prefix is "cluster" for org and for spider renamed, and
    "workload_updated_cluster" for bird renamed.
    """
    wanted = tuple(f"{prefix}{cid}_" for cid in cluster_ids)
    if not wanted:
        return []
    return [v for v in all_views if v.startswith(wanted)]


def load_full_schema(arm: Arm) -> Dict[str, Any]:
    """Schema dict over the arm's tables AND views, loaded once per run."""
    from app.db_utils.schema import load_database_schema_dict

    set_object_scope(arm.full_scope())
    try:
        return load_database_schema_dict(arm.db_path)
    finally:
        # leave the process back on the linking scope so nothing else widens
        set_object_scope(arm.linking_scope())


def merge_source_schema(item_schema: Dict[str, Any],
                        full_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Value-retrieval schema, widened with the objects it does not carry.

    Base tables keep their retrieved value examples (that is the whole point of
    starting from the item's own dict); views are added from the full load.
    """
    merged = {
        "db_id": item_schema.get("db_id", full_schema.get("db_id")),
        "db_path": item_schema.get("db_path", full_schema.get("db_path")),
        "db_type": item_schema.get("db_type", "sqlite"),
        "tables": dict(item_schema.get("tables", {})),
    }
    for name, table in full_schema.get("tables", {}).items():
        merged["tables"].setdefault(name, table)
    return merged


class APRInjector:
    def __init__(self, arm: Arm, history_top_k: int = 3, max_join_paths: int = 0):
        self.arm = arm
        self.history_top_k = history_top_k
        # 0 = no cap. Every join path of every matched cluster goes into the
        # block, matching AutoLink's apply_apr, which never capped either. A cap
        # of 20 was silently dropping ~20% of the routes (mean 18.3 paths per
        # question, max 38), and a truncated path list is worse than a long one:
        # the model cannot tell a missing route from a nonexistent one.
        self.max_join_paths = max_join_paths
        self.all_views = arm.views()                 # [] unless +A
        self.hist = arm.hist

        # Clusters are built from the history CSV keyed on the arm's gt_tables
        # column, so cluster table names live in the same namespace as the
        # linked tables (original for base, renamed for +R).
        _sample, self.clusters, _qcm = build_clusters_from_history(
            SAMPLE_CSV[arm.dataset],
            sql_col=self.hist["sql"],
            gt_tables_col=self.hist["gt_tables"],
        )
        self.history = load_history(arm.dataset)
        self.full_schema = load_full_schema(arm)
        logger.info(
            f"APR injector: arm={arm.suffix} clusters={len(self.clusters)} "
            f"views={len(self.all_views)} prefix={self.hist['view_prefix']!r} "
            f"full schema objects={len(self.full_schema.get('tables', {}))}"
        )

    # ---------------- opt2: AP context for the reversed linker ----------------
    def clusters_for(self, tables: Sequence[str]) -> Dict[str, Any]:
        """Matched clusters for a seed table set.

        In opt2 the seed is the DIRECT linker's tables only. The value linker is
        deliberately excluded: it fires on cell-value overlap, which is noisy at
        table granularity and would pull in false-positive clusters.
        """
        return find_all_clusters_for_tables(sorted(set(tables)), self.clusters)

    def reversed_context(self, data_item: Any, result: Dict[str, Any],
                         reselect_history: bool = True) -> Dict[str, Any]:
        """Install the opt2 phase-B context on the item; returns what to restore.

        The reversed linker reads exactly two fields --
        ``database_schema_after_value_retrieval`` for its schema profile and
        ``few_shot_examples`` for its ICL block -- so swapping those two is
        enough to make it AP-aware without touching the linker itself.

        Schema is pruned to the matched cluster tables plus their views, so this
        is a focused second pass inside the clusters rather than a re-link over
        the whole catalogue. Value examples already retrieved for base columns
        survive, since the pruned dict is filtered from the item's own schema.
        """
        saved = {
            "database_schema_after_value_retrieval": data_item.database_schema_after_value_retrieval,
            "few_shot_examples": data_item.few_shot_examples,
            "common_join_paths": getattr(data_item, "common_join_paths", None),
        }
        cluster_ids = list(result.get("cluster_ids") or [])
        if not cluster_ids:
            return saved

        # Schema for phase B: the matched cluster TABLES plus their VIEWS. Both,
        # not either -- the views are what let the draft SQL skip writing the
        # join, and the base tables are what let it reach a column the view does
        # not surface. Pruning to the clusters is what keeps it focused; the full
        # 798-column catalogue would reintroduce the noise +P is meant to remove.
        keep: Dict[str, List[str]] = {}
        if self.arm.cluster:
            keep.update(self._columns_of([str(t) for t in (result.get("tables") or [])]))
        if self.arm.view:
            matched = views_for_clusters(cluster_ids, self.all_views, self.hist["view_prefix"])
            keep.update(self._columns_of(matched))
        if not keep:
            return saved

        source = merge_source_schema(
            data_item.database_schema_after_value_retrieval or data_item.database_schema,
            self.full_schema,
        )
        data_item.database_schema_after_value_retrieval = filter_used_database_schema(source, keep)
        if reselect_history:
            self._reselect_history(data_item, [int(i) for i in (result.get("indices") or [])])

        # +P: the reversed linker is the only linker that writes joins, so it is
        # the only one a join route can help. Same block, same formatting as the
        # generators and checkers get at stage 5.5.
        if self.arm.cluster:
            data_item.common_join_paths = self._join_paths(result)
        return saved

    @staticmethod
    def restore(data_item: Any, saved: Dict[str, Any]) -> None:
        for field_name, value in saved.items():
            setattr(data_item, field_name, value)

    def _join_paths(self, result: Dict[str, Any]) -> List[str]:
        """Every distinct join path of the matched clusters (uncapped by default)."""
        paths = sorted(set(result.get("paths") or []))
        if self.max_join_paths and self.max_join_paths > 0:
            paths = paths[: self.max_join_paths]
        return paths

    def cluster_schema(self, data_item: Any, result: Dict[str, Any]):
        """The pruned cluster schema (cluster tables + their views), or None.

        Used by two callers that must agree: the reversed linker in phase B and
        the few-shot preparation stage, which generates its preliminary SQL over
        the same objects instead of the full 75-table catalogue (43.4k -> ~10k
        tokens per question).
        """
        cluster_ids = list(result.get("cluster_ids") or [])
        if not cluster_ids:
            return None
        keep: Dict[str, List[str]] = {}
        if self.arm.cluster:
            keep.update(self._columns_of([str(t) for t in (result.get("tables") or [])]))
        if self.arm.view:
            keep.update(self._columns_of(
                views_for_clusters(cluster_ids, self.all_views, self.hist["view_prefix"])))
        if not keep:
            return None
        source = merge_source_schema(
            data_item.database_schema_after_value_retrieval or data_item.database_schema,
            self.full_schema,
        )
        return filter_used_database_schema(source, keep)

    def join_paths_for(self, result: Dict[str, Any]) -> List[str]:
        return self._join_paths(result) if self.arm.cluster else []

    def cluster_row_indices(self, result: Dict[str, Any]) -> List[int]:
        return [int(i) for i in (result.get("indices") or [])]

    # ---------------- schema injection ----------------
    def _columns_of(self, objects: Sequence[str]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        tables = self.full_schema.get("tables", {})
        for name in objects:
            table = tables.get(name)
            if table is None:
                continue
            out[name] = list(table.get("columns", {}).keys())
        return out

    def inject(self, data_item: Any) -> Dict[str, Any]:
        """Rewrite database_schema_after_schema_linking; return per-item stats."""
        linked = data_item.final_linked_tables_and_columns or {}
        stats = {"clusters": 0, "cluster_tables": 0, "views": 0, "paths": 0,
                 "cols_before": sum(len(c) for c in linked.values()),
                 "cols_after": 0, "history_indices": 0}

        # opt2 already matched clusters from the direct linker in phase A; reuse
        # that result rather than recomputing from the post-union table set, so
        # the schema injection, the join paths and what the reversed linker saw
        # all describe the same clusters.
        result = getattr(data_item, "ldd_cluster_result", None)
        if not result:
            result = find_all_clusters_for_tables(sorted(linked.keys()), self.clusters)
        cluster_ids = list(result.get("cluster_ids") or [])
        stats["clusters"] = len(cluster_ids)

        merged: Dict[str, List[str]] = {t: list(c) for t, c in linked.items()}

        if self.arm.cluster and cluster_ids:
            cluster_tables = [str(t) for t in (result.get("tables") or [])]
            for name, columns in self._columns_of(cluster_tables).items():
                merged.setdefault(name, [])
                merged[name] = sorted(set(merged[name]) | set(columns))
            stats["cluster_tables"] = len(cluster_tables)

        if self.arm.view and cluster_ids:
            matched = views_for_clusters(cluster_ids, self.all_views,
                                         self.hist["view_prefix"])
            for name, columns in self._columns_of(matched).items():
                merged.setdefault(name, [])
                merged[name] = sorted(set(merged[name]) | set(columns))
            stats["views"] = len(matched)

        source = merge_source_schema(
            data_item.database_schema_after_value_retrieval or data_item.database_schema,
            self.full_schema,
        )
        data_item.database_schema_after_schema_linking = filter_used_database_schema(source, merged)
        data_item.final_linked_tables_and_columns = merged
        stats["cols_after"] = sum(len(c) for c in merged.values())

        paths: List[str] = []
        if self.arm.cluster:
            paths = self._join_paths(result)
        data_item.common_join_paths = paths
        stats["paths"] = len(paths)

        indices = [int(i) for i in (result.get("indices") or [])]
        stats["history_indices"] = len(indices)
        self._reselect_history(data_item, indices)
        return stats

    # ---------------- history / ICL re-selection ----------------
    def _row_index_of(self, example: Dict[str, Any]) -> Optional[int]:
        source_id = str(example.get("source_example_id") or "")
        if source_id.startswith("ldd:"):
            try:
                return int(source_id.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                return None
        return None

    def _example_from_row(self, row_index: int, score: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if row_index not in self.history.index:
            return None
        row = self.history.loc[row_index]
        variants = sql_variants(self.arm.dataset, row)
        sql = render_sql({"sql_variants": variants}, self.arm, use_view=self.arm.view)
        if not sql:
            return None
        return {
            "question": str(row.get("question", "")),
            "evidence": "",
            "sql": sql,
            "source_example_id": f"ldd:{self.arm.dataset}:{row_index}",
            "source_db_id": f"merged_{self.arm.dataset}",
            "retrieval_score": score,
        }

    def _reselect_history(self, data_item: Any, cluster_row_indices: Sequence[int]) -> None:
        """+P restricts the ranked pool to cluster questions; +A shows view SQL.

        The ranked pool comes from step 4 -- same masked-question retrieval, same
        scores. Nothing is re-embedded and no LLM is called; only which of the
        already-ranked rows survive, and which SQL column is printed, change.
        """
        if not (self.arm.cluster or self.arm.view):
            return

        metadata = getattr(data_item, "few_shot_preparation_metadata", None) or {}
        pool: List[Tuple[int, Optional[float]]] = []
        for entry in (metadata.get("ranked_pool") or []):
            row_index = entry.get("row_index")
            if row_index is not None:
                pool.append((int(row_index), entry.get("score")))
        if not pool:
            # step 4 predates the ranked_pool patch: fall back to the 3 kept
            for example in (data_item.few_shot_examples or []):
                row_index = self._row_index_of(example)
                if row_index is not None:
                    pool.append((row_index, example.get("retrieval_score")))
        if not pool:
            return

        allowed = {int(i) for i in cluster_row_indices}
        if self.arm.cluster and allowed:
            inside = [p for p in pool if p[0] in allowed]
            outside = [p for p in pool if p[0] not in allowed]
            ordered = inside + outside          # backfill, never a short block
        else:
            ordered = pool

        examples: List[Dict[str, Any]] = []
        for row_index, score in ordered:
            example = self._example_from_row(row_index, score)
            if example is not None:
                examples.append(example)
            if len(examples) >= self.history_top_k:
                break
        if examples:
            data_item.few_shot_examples = examples
