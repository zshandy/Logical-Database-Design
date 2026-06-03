"""LDD root and default-path resolution.

Layout (relative to ``LDD/``)::

    Logical-Database-Design/
    ├── csvs/                        # input nl2sql CSVs + history samples
    ├── databases/                   # merged_spider.sqlite, merged_bird.sqlite
    ├── mapping_files/               # name_mapping_*.json
    └── benchmarks/
        ├── _common/                 # this package
        ├── basesql/
        └── din-sql/

Pipeline entry-points are expected to live at
``benchmarks/<pipeline>/<entrypoint>.py``, so ``LDD_ROOT`` is two levels up
from this file's directory.
"""

from __future__ import annotations

import os
from typing import Optional


LDD_ROOT: str = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)

CSV_DIR: str = os.path.join(LDD_ROOT, "csvs")
DB_DIR: str = os.path.join(LDD_ROOT, "databases")
MAPPING_DIR: str = os.path.join(LDD_ROOT, "mapping_files")


def default_csv_path(dataset: str, sample: int = 100) -> str:
    """Default input CSV: ``csvs/nl2sql_{dataset}.csv`` (or ``_{sample}`` variant)."""
    if sample is not None and sample < 100:
        return os.path.join(CSV_DIR, f"nl2sql_{dataset}_{sample}.csv")
    return os.path.join(CSV_DIR, f"nl2sql_{dataset}.csv")


def default_db_path(dataset: str) -> str:
    """Default sqlite DB: ``databases/merged_{dataset}.sqlite``."""
    return os.path.join(DB_DIR, f"merged_{dataset}.sqlite")


def default_history_path(dataset: str, sample: int = 100) -> str:
    """Default history sample CSV: ``csvs/sample_{dataset}.csv``."""
    if sample is not None and sample < 100:
        return os.path.join(CSV_DIR, f"sample_{dataset}_{sample}.csv")
    return os.path.join(CSV_DIR, f"sample_{dataset}.csv")


def default_mapping_path(dataset: str, sample: int = 100) -> str:
    """Default name-mapping JSON: ``mapping_files/name_mapping_{dataset}.json``."""
    if sample is not None and sample < 100:
        return os.path.join(MAPPING_DIR, f"name_mapping_{dataset}_{sample}.json")
    return os.path.join(MAPPING_DIR, f"name_mapping_{dataset}.json")


def resolve_path(value: Optional[str], default: str) -> str:
    """Return ``value`` if truthy, otherwise ``default``."""
    return value if value else default
