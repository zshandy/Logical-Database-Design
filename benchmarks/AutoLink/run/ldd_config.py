"""Arm definitions for running AutoLink on the LDD merged schemas.

An "arm" is a combination of the three LDD schema transformations:

    +R  rename        swaps the exposed object universe org <-> renamed
    +A  abstraction   adds the cluster join-views to the exposed universe
    +P  partitioning  injects matched-cluster tables + join paths (universe unchanged)

Exposure rules (confirmed with the user):

    base / +P          org_tables only
    +A   / +A+P        org_tables + org_views
    +R   / +R+P        renamed_tables only
    +R+A / +R+A+P      renamed_tables + renamed_views

Never a mix of org and renamed. +P never changes the universe -- it only decides
which of the exposed objects get injected into the initial schema, plus history
filtering and the Common Join Paths block.

Column-name alignment was verified empirically (see notes on HISTORY_COLS): the
CSV column called ``renamed_SQL`` does NOT use the renamed table names in either
dataset, so it is deliberately unused here.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
# Vendored under <LDD>/benchmarks/, so the repo root is derived from this
# file's location rather than hardcoded -- the original absolute path only
# worked on the machine the experiments were run on.
LDD = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir))

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
# Verified by extracting FROM/JOIN targets from every row and matching them
# against the four object lists in run_spider.py:
#
#   bird  SQL                       99.4% bird_org_tables          -> org
#         workload_updated_SQL     100.0% bird_renamed_tables      -> renamed
#         workload_updated_view_SQL 50.3% bird_renamed_views       -> renamed +A
#                                   (byte-identical to renamed_view_SQL, 767/767)
#         renamed_SQL               95.3% bird_ORG_tables          -> NOT USABLE
#
#   spider SQL                     100.0% spider_org_tables        -> org
#          view_SQL                 49.7% spider_org_views         -> org +A
#          renamed_view_SQL         45.0% spider_renamed_views     -> renamed +A
#          renamed_SQL              96.4% spider_ORG_tables        -> NOT USABLE
#
# Spider therefore has no base-SQL history column aligned with
# spider_renamed_tables; the renamed arm is unsupported there until one exists.
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
    # Spider cluster views use a plain "cluster{id}_" prefix even when renamed
    # (documented in MAC-SQL's run_union.py).
    #
    # workload_updated_SQL did not originally exist for spider -- it was produced
    # by make_spider_renamed_history.py, which calls LDD's own
    # prep_database.rewrite_history_sqls (LLM rewrite + execution verification +
    # retry). Result: 502/502 verified against the original SQL, 502/502
    # referencing only spider_renamed_tables / spider_renamed_views.
    # spider's shipped renamed_SQL was 0/502 aligned and is deliberately unused.
    ("spider", True): {
        "sql": "workload_updated_SQL",
        "view_sql": "renamed_view_SQL",
        "gt_tables": "gt_workload_updated_tables",
        "view_prefix": "cluster",
    },
}

HISTORY_TOP_K = 3          # 3 from sql, plus 3 from view_sql when +A -> 6


@dataclass
class Arm:
    """One experimental configuration."""

    dataset: str = "bird"
    rename: bool = False               # +R
    view: bool = False                 # +A
    cluster: bool = False              # +P
    mode: str = "opt1"                 # opt1 | opt2 (only meaningful with P or A)
    top_n: int = 30
    max_turns: int = 6
    num_candidates: int = 3
    revise_attempts: int = 2
    model_tag: str = "ds"

    # ---------------- exposed universe ----------------
    def tables(self, lists: Dict[str, List[str]]) -> List[str]:
        key = "renamed_tables" if self.rename else "org_tables"
        return list(lists[f"{self.dataset}_{key}"])

    def views(self, lists: Dict[str, List[str]]) -> List[str]:
        if not self.view:
            return []
        key = "renamed_views" if self.rename else "org_views"
        return list(lists[f"{self.dataset}_{key}"])

    def exposed(self, lists: Dict[str, List[str]]) -> List[str]:
        """Full object universe the agent may see or retrieve."""
        return self.tables(lists) + self.views(lists)

    # ---------------- history wiring ----------------
    @property
    def hist(self) -> dict:
        return HISTORY_COLS[(self.dataset, self.rename)]

    def validate(self) -> None:
        h = self.hist
        if h["sql"] is None:
            raise ValueError(
                f"{self.dataset} rename={self.rename}: no history SQL column is "
                f"aligned with {self.dataset}_renamed_tables "
                f"(renamed_SQL uses ORIGINAL table names). Arm unsupported."
            )
        if self.mode not in ("opt1", "opt2"):
            raise ValueError(f"unknown mode {self.mode!r}")
        if self.mode == "opt2" and not self.cluster:
            raise ValueError("mode=opt2 requires cluster=True (it re-retrieves "
                             "inside the matched clusters)")

    # ---------------- naming ----------------
    @property
    def suffix(self) -> str:
        """Mirrors basesql's _build_suffix, with autolink's own additions."""
        s = ""
        if self.rename:
            s += "_rename"
        if self.view:
            s += "_withview"
        if self.cluster:
            s += "_cluster"
        s += "_history"
        if self.cluster or self.view:
            s += f"_{self.mode}"
        s += f"_{self.model_tag}"
        return s

    @property
    def schema_col(self) -> str:
        return f"autolink_schema{self.suffix}"

    @property
    def sql_col(self) -> str:
        return f"autolink_sql{self.suffix}"

    @property
    def result_col(self) -> str:
        return f"autolink_sql{self.suffix}_result"

    @property
    def log_path(self) -> str:
        return os.path.join(HERE, f"log_{self.dataset}{self.suffix}")

    @property
    def db_name(self) -> str:
        """Logical db name used in documents/ and embeddings/ paths.

        Distinct per arm because the exposed universe differs, so the vector
        store cannot be shared.
        """
        return f"merged_{self.dataset}{self.suffix}"


def load_object_lists(path: str = OBJECT_LISTS) -> Dict[str, List[str]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def base_arms(dataset: str = "bird", model_tag: str = "ds") -> List[Arm]:
    """The three pilot arms: base, opt1 (A+P), opt2 (A+P)."""
    return [
        Arm(dataset=dataset, model_tag=model_tag),
        Arm(dataset=dataset, view=True, cluster=True, mode="opt1", model_tag=model_tag),
        Arm(dataset=dataset, view=True, cluster=True, mode="opt2", model_tag=model_tag),
    ]
