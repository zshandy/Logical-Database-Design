"""LDD arm definitions for running DeepEye-SQL on the merged schemas.

An "arm" is a combination of the three LDD schema transformations:

    +R  rename        swaps the exposed object universe org <-> renamed
    +A  abstraction   makes the cluster join-views injectable after linking
    +P  partitioning  injects matched-cluster tables + Common Join Paths

Exposure rules (identical to the AutoLink port):

    base / +P          org_tables only
    +A   / +A+P        org_tables + org_views
    +R   / +R+P        renamed_tables only
    +R+A / +R+A+P      renamed_tables + renamed_views

Never a mix of org and renamed.

Where each transformation enters DeepEye-SQL
--------------------------------------------
+R  is applied at the very top, in step 1 (dataset construction): the object
    scope handed to load_database_schema_dict decides which 75/78 objects exist
    for the whole run. Everything downstream -- value index, all three linkers,
    closure, generators, checkers, selection -- reads that one schema dict.

+A / +P are applied between step 5 (schema linking) and step 6 (SQL
    generation), as their own runner. Views are deliberately NOT exposed at
    step 1: the linkers receive the full schema profile, and 139 objects /
    2728 columns measures ~121k tokens at stripping level 0 against a ~49k
    prompt budget, which would force progressive stripping to drop
    include_value_examples and silently discard every retrieved value from the
    linker prompts. Tables only is ~35k tokens and fits.

The renamed "tables" are CREATE VIEWs over the base tables inside
merged_<ds>.sqlite, so object enumeration can never use
``sqlite_master.type = 'table'`` -- it must go through the explicit lists.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
# Vendored under <LDD>/benchmarks/, so the repo root is derived from this
# file's location rather than hardcoded -- the original absolute path only
# worked on the machine the experiments were run on.
LDD = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, os.pardir))

# Extracted verbatim from spider_data/run_spider.py; 8 lists, both datasets.
OBJECT_LISTS = os.path.join(HERE, "object_lists.json")

MERGED_DB = {
    "bird": os.path.join(LDD, "databases", "merged_bird.sqlite"),
    "spider": os.path.join(LDD, "databases", "merged_spider.sqlite"),
}
NL2SQL_CSV = {
    "bird": os.path.join(LDD, "csvs", "nl2sql_bird.csv"),
    "spider": os.path.join(LDD, "csvs", "nl2sql_spider.csv"),
}
SAMPLE_CSV = {
    "bird": os.path.join(LDD, "csvs", "sample_bird.csv"),
    "spider": os.path.join(LDD, "csvs", "sample_spider.csv"),
}

# ---------------------------------------------------------------------------
# History / gold-table columns, per dataset and rename mode.
#
# Carried over verbatim from the AutoLink port, where the alignment was verified
# by extracting FROM/JOIN targets from every row and matching them against the
# four object lists:
#
#   bird  SQL                       99.4% bird_org_tables          -> org
#         workload_updated_SQL     100.0% bird_renamed_tables      -> renamed
#         workload_updated_view_SQL 50.3% bird_renamed_views       -> renamed +A
#         renamed_SQL               95.3% bird_ORG_tables          -> NOT USABLE
#
#   spider SQL                     100.0% spider_org_tables        -> org
#          view_SQL                 49.7% spider_org_views         -> org +A
#          renamed_view_SQL         45.0% spider_renamed_views     -> renamed +A
#          renamed_SQL              96.4% spider_ORG_tables        -> NOT USABLE
#
# spider's workload_updated_SQL was produced by AutoLink's
# make_spider_renamed_history.py (LDD rewrite_history_sqls: LLM rewrite +
# execution verification + retry), 502/502 verified.
# ---------------------------------------------------------------------------
HISTORY_COLS = {
    ("bird", False): {
        "sql": "SQL",
        "view_sql": "view_SQL",
        "gt_tables": "gt_tables",
        "view_prefix": "cluster",
    },
    ("bird", True): {
        "sql": "workload_updated_SQL",
        "view_sql": "workload_updated_view_SQL",
        "gt_tables": "gt_workload_updated_tables",
        "view_prefix": "workload_updated_cluster",
    },
    ("spider", False): {
        "sql": "SQL",
        "view_sql": "view_SQL",
        "gt_tables": "gt_tables",
        "view_prefix": "cluster",
    },
    ("spider", True): {
        "sql": "workload_updated_SQL",
        "view_sql": "renamed_view_SQL",
        "gt_tables": "gt_workload_updated_tables",
        "view_prefix": "cluster",
    },
}

HISTORY_TOP_K = 3          # 3 base SQLs, plus 3 view SQLs when +A -> 6


@lru_cache(maxsize=1)
def load_object_lists() -> Dict[str, List[str]]:
    with open(OBJECT_LISTS, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Arm:
    """One experimental configuration."""

    dataset: str = "bird"
    rename: bool = False               # +R
    view: bool = False                 # +A
    cluster: bool = False              # +P
    mode: str = "opt1"                 # opt1 | opt2 -- where AP enters linking
    model_tag: str = "q3c"             # Qwen3-Coder-30B-A3B by default

    # ---------------- exposed universe ----------------
    def tables(self) -> List[str]:
        lists = load_object_lists()
        key = "renamed_tables" if self.rename else "org_tables"
        return list(lists[f"{self.dataset}_{key}"])

    def views(self) -> List[str]:
        """Cluster views. Empty without +A; never exposed before step 5.5."""
        if not self.view:
            return []
        lists = load_object_lists()
        key = "renamed_views" if self.rename else "org_views"
        return list(lists[f"{self.dataset}_{key}"])

    def linking_scope(self) -> List[str]:
        """Objects visible to steps 1-5. Tables only -- see module docstring."""
        return self.tables()

    def full_scope(self) -> List[str]:
        """Objects that may appear after the 5.5 injection."""
        return self.tables() + self.views()

    # ---------------- history wiring ----------------
    @property
    def hist(self) -> dict:
        return HISTORY_COLS[(self.dataset, self.rename)]

    def validate(self) -> None:
        if self.dataset not in ("bird", "spider"):
            raise ValueError(f"unknown dataset {self.dataset!r}")
        if self.hist["sql"] is None:
            raise ValueError(
                f"{self.dataset} rename={self.rename}: no history SQL column is "
                f"aligned with {self.dataset}_renamed_tables. Arm unsupported."
            )
        if self.mode not in ("opt1", "opt2"):
            raise ValueError(f"unknown mode {self.mode!r}")
        if self.mode == "opt2" and not (self.view or self.cluster):
            raise ValueError("mode=opt2 is only meaningful with +A or +P")
        if not os.path.exists(MERGED_DB[self.dataset]):
            raise FileNotFoundError(MERGED_DB[self.dataset])

    # ---------------- naming ----------------
    @property
    def suffix(self) -> str:
        """basesql's naming convention, as used by every other LDD pipeline."""
        s = ""
        if self.rename:
            s += "_rename"
        if self.view:
            s += "_withview"
        if self.cluster:
            s += "_cluster"
        s += "_history"
        if self.view or self.cluster:
            s += f"_{self.mode}"
        s += f"_{self.model_tag}"
        return s

    @property
    def db_id(self) -> str:
        """The sqlite file stem, which is what keys the schema cache and the
        value index. Deliberately NOT arm-specific: the index depends only on the
        object namespace, so both +R arms share one build. Arm identity lives in
        ``suffix`` and in the output column names."""
        return f"merged_{self.dataset}"

    @property
    def db_path(self) -> str:
        return MERGED_DB[self.dataset]

    # ---------------- output columns ----------------
    @property
    def schema_col(self) -> str:
        return f"deepeye_schema{self.suffix}"

    @property
    def sql_col(self) -> str:
        return f"deepeye_sql{self.suffix}"

    @property
    def result_col(self) -> str:
        return f"deepeye_sql{self.suffix}_result"


# Only the untransformed baseline and the two full-APR variants are run.
#
#   opt1  AP enters after ALL linking is done (stage 5.5 only). The reversed
#         linker sees non-view SQL examples and the unrestricted history pool,
#         because nothing before 5.5 knows a cluster exists.
#   opt2  AP is derived from the DIRECT linker's tables alone, then the reversed
#         linker runs against a schema pruned to the matched cluster tables +
#         their views, with the history pool restricted to those clusters and
#         the example SQLs rendered from the view column.
#
# The value linker deliberately never seeds the cluster lookup: it fires on
# value overlap, which is noisy at the table level and would drag in
# false-positive clusters.
ARMS = {
    "base":     dict(rename=False, view=False, cluster=False, mode="opt1"),
    "rap_opt1": dict(rename=True,  view=True,  cluster=True,  mode="opt1"),
    "rap_opt2": dict(rename=True,  view=True,  cluster=True,  mode="opt2"),
}


def resolve_arm(value):
    """Return an Arm from whatever the caller has: Arm, dict, or None.

    save_dataset serialises the dataset config with model_dump(), which flattens
    the Arm dataclass into a plain dict. Any process that reads the arm back off
    a loaded snapshot therefore sees a dict, not an Arm. Every read site goes
    through here so that difference stops mattering.
    """
    if value is None or isinstance(value, Arm):
        return value
    if isinstance(value, dict):
        fields = {f for f in Arm.__dataclass_fields__}
        return Arm(**{k: v for k, v in value.items() if k in fields})
    raise TypeError(f"cannot resolve an Arm from {type(value).__name__}")


def arm_of(config):
    """The Arm attached to a dataset config (live or snapshot-restored)."""
    return resolve_arm(getattr(config, "ldd_arm", None))


def arm_from_name(name: str, dataset: str, model_tag: str = "q3c") -> Arm:
    if name not in ARMS:
        raise ValueError(f"unknown arm {name!r}; choose from {sorted(ARMS)}")
    arm = Arm(dataset=dataset, model_tag=model_tag, **ARMS[name])
    arm.validate()
    return arm
