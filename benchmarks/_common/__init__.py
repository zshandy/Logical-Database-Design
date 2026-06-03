"""Shared utilities for benchmark pipelines (basesql, din-sql, ...).

Each pipeline lives in a sibling directory (e.g. ``benchmarks/basesql/``) and
imports from this package by inserting ``benchmarks/`` into ``sys.path`` at
the top of its entry-point script.
"""
