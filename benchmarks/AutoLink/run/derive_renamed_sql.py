"""Derive a renamed-table SQL column from the original ``SQL`` column.

Spider has no history column written against ``spider_renamed_tables``:

    SQL              -> spider_org_tables          (100.0%)
    renamed_SQL      -> spider_ORG_tables          ( 96.4%)  descriptive columns only
    renamed_view_SQL -> renamed tables + views     (55/45%)  but is the +A history

BIRD solves this with ``workload_updated_SQL``. This module reconstructs the
equivalent by applying ``name_mapping_<ds>.json`` (``table_to_view`` +
``column_mapping``) to ``SQL`` -- the same mapping LDD's own ``--rename`` path
consumes.

Because BIRD *has* the ground-truth column, running this on BIRD measures how
faithful the derivation is before we trust it on Spider. See ``--validate``.
"""

from __future__ import annotations

import argparse
import ast
import collections
import io
import json
import os
import re
import sys
from typing import Dict, Tuple

import pandas as pd

import ldd_config as C

MAPPING = {
    "bird": os.path.join(C.LDD, "mapping_files", "name_mapping_bird.json"),
    "spider": os.path.join(C.LDD, "mapping_files", "name_mapping_spider.json"),
}

# `x` or "x" or [x] or bare identifier
_IDENT = re.compile(r'`([^`]+)`|"([^"]+)"|\[([^\]]+)\]|\b([A-Za-z_][A-Za-z0-9_]*)\b')
_ALIASES = {f"t{i}" for i in range(1, 12)}

# Single-quoted string literals must pass through untouched -- BIRD's `school`
# column maps to `school_name`, which would corrupt values like
# 'continuation school'. Doubled '' is SQLite's escaped quote.
_LITERAL = re.compile(r"'(?:[^']|'')*'")

# SQL keywords are never rewritten even when they collide with an object name.
# BIRD has a table literally called `order`, so without this ORDER BY becomes
# "Bank_Orders BY".
_KEYWORDS = {
    "select", "distinct", "from", "where", "group", "by", "order", "having",
    "limit", "offset", "join", "inner", "left", "right", "outer", "full",
    "cross", "on", "using", "as", "and", "or", "not", "in", "like", "glob",
    "between", "is", "null", "exists", "case", "when", "then", "else", "end",
    "union", "all", "intersect", "except", "asc", "desc", "cast", "count",
    "sum", "avg", "min", "max", "abs", "round", "length", "substr", "replace",
    "coalesce", "ifnull", "nullif", "iif", "strftime", "date", "datetime",
    "julianday", "real", "integer", "text", "numeric", "blob", "over",
    "partition", "row_number", "rank", "dense_rank", "with", "recursive",
    "values", "insert", "update", "delete", "set", "into", "collate", "escape",
}


def load_mapping(dataset: str) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, int]]:
    """Return (table_map, column_map, stats).

    ``column_map`` is global and lower-cased. A column name that maps to
    *different* targets in different tables is ambiguous and deliberately
    excluded -- rewriting it without resolving the alias->table binding would be
    a guess. The count of excluded names is reported.
    """
    with open(MAPPING[dataset], encoding="utf-8") as f:
        m = json.load(f)

    table_map = {str(k).lower(): str(v) for k, v in m["table_to_view"].items()}

    per_name: Dict[str, set] = collections.defaultdict(set)
    for _tbl, raw in m["column_mapping"].items():
        cols = ast.literal_eval(raw) if isinstance(raw, str) else raw
        for src, dst in cols.items():
            per_name[str(src).lower()].add(str(dst))

    column_map, ambiguous = {}, 0
    for name, targets in per_name.items():
        if len(targets) == 1:
            column_map[name] = next(iter(targets))
        else:
            ambiguous += 1

    return table_map, column_map, {"ambiguous_columns": ambiguous,
                                   "tables": len(table_map),
                                   "columns": len(column_map)}


def rewrite(sql: str, table_map: Dict[str, str], column_map: Dict[str, str]) -> str:
    """Rewrite table and column identifiers.

    Aliases, SQL keywords, and the contents of string literals are left alone.
    """
    def sub(mo: re.Match) -> str:
        raw = next(g for g in mo.groups() if g is not None)
        low = raw.lower()
        if low in _ALIASES or low in _KEYWORDS:
            return mo.group(0)
        if low in table_map:
            return table_map[low]
        if low in column_map:
            new = column_map[low]
            # keep backticks when the target needs them
            return f"`{new}`" if re.search(r"\s", new) else new
        return mo.group(0)

    # split on string literals and rewrite only the code between them
    out, pos = [], 0
    for lit in _LITERAL.finditer(str(sql)):
        out.append(_IDENT.sub(sub, str(sql)[pos:lit.start()]))
        out.append(lit.group(0))
        pos = lit.end()
    out.append(_IDENT.sub(sub, str(sql)[pos:]))
    return "".join(out)


def canon(q: str) -> str:
    q = re.sub(r'[`"\[\]]', "", str(q).lower())
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"\s*([,()=<>!.])\s*", r"\1", q)
    return q.strip().rstrip(";")


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=["bird", "spider"], default="spider")
    p.add_argument("--validate", action="store_true",
                   help="BIRD only: compare the derivation against workload_updated_SQL")
    p.add_argument("--write", action="store_true",
                   help="add derived_renamed_SQL to sample_<ds>.csv (backs up first)")
    a = p.parse_args()

    tmap, cmap, stats = load_mapping(a.dataset)
    lists = C.load_object_lists()
    rt = {x.lower() for x in lists[f"{a.dataset}_renamed_tables"]}
    print(f"=== {a.dataset} mapping ===")
    print(f"  tables mapped     : {stats['tables']}")
    print(f"  columns mapped    : {stats['columns']}")
    print(f"  ambiguous skipped : {stats['ambiguous_columns']}")
    print(f"  targets landing in {a.dataset}_renamed_tables: "
          f"{sum(1 for v in tmap.values() if v.lower() in rt)}/{len(tmap)}")

    samp = pd.read_csv(C.SAMPLE_CSV[a.dataset])
    derived = samp["SQL"].map(lambda q: rewrite(q, tmap, cmap))

    def refs(q):
        return {m.lower() for m in re.findall(
            r"(?:FROM|JOIN)\s+[`\"\[]?([A-Za-z_]\w*)", str(q), re.I)}

    cnt = collections.Counter()
    for v in derived:
        cnt.update(refs(v))
    tot = sum(cnt.values())
    ot = {x.lower() for x in lists[f"{a.dataset}_org_tables"]}
    print(f"\n  derived SQL FROM/JOIN targets: "
          f"{100*sum(c for t,c in cnt.items() if t in rt)/tot:.1f}% renamed_tables, "
          f"{100*sum(c for t,c in cnt.items() if t in ot)/tot:.1f}% org_tables")

    if a.validate:
        if "workload_updated_SQL" not in samp.columns:
            sys.exit("--validate needs workload_updated_SQL (BIRD only)")
        gold = samp["workload_updated_SQL"]
        eq = sum(1 for d, g in zip(derived, gold) if canon(d) == canon(g))
        print(f"\n  VALIDATION vs workload_updated_SQL: {eq}/{len(samp)} "
              f"({100*eq/len(samp):.1f}%) canonically identical")
        bad = [i for i in range(len(samp)) if canon(derived[i]) != canon(gold[i])]
        for i in bad[:4]:
            print(f"\n  --- row {i}")
            print(f"    derived: {canon(derived[i])[:140]}")
            print(f"    gold   : {canon(gold[i])[:140]}")

    if a.write:
        path = C.SAMPLE_CSV[a.dataset]
        bak = path.replace(".csv", ".pre_derive.csv")
        if not os.path.exists(bak):
            samp.to_csv(bak, index=False)
            print(f"\n  backup -> {os.path.basename(bak)}")
        samp["derived_renamed_SQL"] = derived
        samp.to_csv(path, index=False)
        print(f"  wrote derived_renamed_SQL into {os.path.basename(path)}")


if __name__ == "__main__":
    main()
