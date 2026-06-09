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
LOG_DIR: str = os.path.join(LDD_ROOT, "logs")
OUTPUT_DIR: str = os.path.join(LDD_ROOT, "outputs")


def default_log_dir(benchmark: str, subdir: str = "") -> str:
    """Per-benchmark log directory: ``<LDD>/logs/<benchmark>[/<subdir>]``.

    ``benchmark`` is the baseline name (e.g. ``basesql``, ``din-sql``,
    ``csc_sql``, ``MAC-SQL``, ``prep_database``). ``subdir`` is whatever the
    caller wants to organize under (e.g. ``"bird/run_20260605-164333_rename"``).
    The directory is NOT created here — the caller decides when to mkdir.
    """
    base = os.path.join(LOG_DIR, benchmark)
    return os.path.join(base, subdir) if subdir else base


def default_output_dir(benchmark: str, subdir: str = "") -> str:
    """Per-benchmark output directory: ``<LDD>/outputs/<benchmark>[/<subdir>]``.

    Same contract as :func:`default_log_dir` but for output artifacts (final
    CSVs, JSONLs, predictions). Keeps results out of the benchmarks tree.
    """
    base = os.path.join(OUTPUT_DIR, benchmark)
    return os.path.join(base, subdir) if subdir else base


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


def default_mapping_path(dataset: str, sample: int = 100, rename: bool = True) -> str:
    """Default consolidated prep-config JSON: ``mapping_files/prep_{dataset}[_renamed].json``.

    The file produced by ``prep_database`` is a single consolidated config that
    contains the rename mapping, cluster artifacts, and views list as nested
    sections. The loaders (``load_rename_mapping``, ``load_clusters_from_file``)
    accept both this consolidated shape and the older flat files
    (``name_mapping_*.json``, ``cluster_*.json``) for backward compatibility.

    The ``_renamed`` suffix mirrors prep_database's convention when ``--rename``
    was used at build time.
    """
    suffix = "_renamed" if rename else ""
    if sample is not None and sample < 100:
        return os.path.join(MAPPING_DIR, f"prep_{dataset}_{sample}{suffix}.json")
    return os.path.join(MAPPING_DIR, f"prep_{dataset}{suffix}.json")


def resolve_path(value: Optional[str], default: str) -> str:
    """Return ``value`` if truthy, otherwise ``default``."""
    return value if value else default
