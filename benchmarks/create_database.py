"""create_database.py — merge a directory of per-database SQLite files into one.

This is step 0 of the pipeline, before prep_database.py. The benchmarks ship one
SQLite file per database (BIRD's dev set is 11 files, Spider's is 19); every
experiment in this project runs against a single *union* database holding all of
them, because the whole point is to study a schema large enough that table
selection is hard. prep_database.py assumes that union already exists and adds
the renames, views and history rewrites on top; this script builds it.

WHAT IT PRESERVES, and why it matters

  DDL verbatim   Each table is created from the source's own
                 ``sqlite_master.sql`` text, unmodified. That keeps column
                 types, DEFAULTs, PRIMARY KEYs and -- critically -- FOREIGN KEY
                 declarations with their ON UPDATE/DELETE actions. The FK graph
                 is what the star and denormalisation catalogues are derived
                 from, so a merge that dropped or normalised it would silently
                 change downstream results.

  Explicit indexes and triggers are copied too. Implicit indexes (the ones
  SQLite creates for PRIMARY KEY / UNIQUE) come along with the DDL.

  Views are NOT copied by default: the union is meant to be base tables only,
  and every view in this project is generated later by prep_database.py. Pass
  --with-views to override.

NAME COLLISIONS. Two source databases may declare the same table name. BIRD has
none and Spider has none, but the script refuses to guess: by default it aborts
and lists the clashes. --on-collision prefix renames them to ``<db>_<table>``,
which changes the schema the models see, so it is opt-in and reported loudly.

RECREATING THE BENCHMARK LAYER

The union of base tables is only half of what the experiments run against. On
top of it sit three view families, all listed in _common/datasets.py:

    renamed_tables   one view per base table, exposing it under its +R name
    org_views        the workload-mined catalogue used by +A
    renamed_views    the same catalogue in the +R namespace

--dump_benchmark extracts those view definitions from a reference database into
a plain .sql file, in dependency order (renamed tables and mined views read the
base tables; renamed cluster views read the renamed tables, so they come last).
--recreate_benchmark replays that file onto a freshly merged database, which
reproduces the benchmark schema without needing the reference database at all.

    # 1. merge the shipped per-database files into the union of base tables
    python create_database.py --src databases/bird_base_databases \
                              --out databases/merged_bird_base.sqlite

    # 2. capture the benchmark view layer once, from a reference database
    python create_database.py --dataset bird \
                              --from-db databases/merged_bird.sqlite \
                              --dump_benchmark sql/bird_benchmark_views.sql

    # 3. anyone can now rebuild the full benchmark database from (1) + (2)
    python create_database.py --src databases/bird_base_databases \
                              --out databases/merged_bird.sqlite \
                              --recreate_benchmark sql/bird_benchmark_views.sql
"""

from __future__ import annotations

import argparse
import glob
import os
import sqlite3
import sys
from collections import OrderedDict, defaultdict


def q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def discover(src: str):
    """Return OrderedDict {db_name: sqlite_path}.

    Accepts either ``<src>/<db>/<db>.sqlite`` (the benchmark layout) or a flat
    directory of ``<src>/<db>.sqlite`` files.
    """
    found = OrderedDict()
    for p in sorted(glob.glob(os.path.join(src, "*", "*.sqlite"))
                    + glob.glob(os.path.join(src, "*", "*.db"))):
        found[os.path.basename(os.path.dirname(p))] = p
    if not found:
        for p in sorted(glob.glob(os.path.join(src, "*.sqlite"))
                        + glob.glob(os.path.join(src, "*.db"))):
            found[os.path.splitext(os.path.basename(p))[0]] = p
    return found


def objects(con, kind):
    """[(name, sql)] for tables/indexes/triggers, skipping SQLite internals and
    auto-created indexes (sql IS NULL)."""
    rows = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type=? "
        "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL", (kind,)).fetchall()
    return [(n, s) for n, s in rows]


# The three view families that make up the benchmark layer, in the order they
# must be created: the first two read base tables, the third reads the first.
VIEW_FAMILIES = ("renamed_tables", "org_views", "renamed_views")


def dump_benchmark(dataset: str, from_db: str, out_sql: str) -> None:
    """Write the benchmark view layer of `from_db` to a replayable .sql file."""
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from _common.datasets import DATASET_TABLES          # noqa: E402

    spec = DATASET_TABLES[dataset]
    con = sqlite3.connect(from_db)
    have = {n: s for n, s in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='view'")}
    con.close()

    os.makedirs(os.path.dirname(os.path.abspath(out_sql)) or ".", exist_ok=True)
    written, missing = 0, []
    with open(out_sql, "w", encoding="utf-8") as f:
        f.write(f"-- Benchmark view layer for {dataset}-Union.\n"
                f"-- Extracted from {os.path.basename(from_db)} by "
                f"create_database.py --dump_benchmark.\n"
                f"-- Replay onto a merged base database with "
                f"--recreate_benchmark.\n"
                f"-- Families are emitted in dependency order; the renamed "
                f"cluster views read the\n-- renamed table views, so they come "
                f"last.\n\n")
        for fam in VIEW_FAMILIES:
            names = spec.get(fam) or []
            f.write(f"\n-- ==== {fam} ({len(names)}) "
                    f"{'=' * max(0, 52 - len(fam))}\n")
            for n in names:
                sql = have.get(n)
                if not sql:
                    missing.append((fam, n))
                    continue
                f.write(f'DROP VIEW IF EXISTS "{n}";\n')
                f.write(sql.rstrip().rstrip(";") + ";\n")
                written += 1
    print(f"dumped {written} view definitions -> {out_sql}")
    for fam in VIEW_FAMILIES:
        print(f"   {fam:16s} {len(spec.get(fam) or [])}")
    if missing:
        print(f"   ! {len(missing)} listed views absent from {from_db}:")
        for fam, n in missing[:8]:
            print(f"       {fam}: {n}")


def recreate_benchmark(db_path: str, sql_path: str) -> None:
    """Replay a dumped benchmark view layer onto `db_path`."""
    script = open(sql_path, encoding="utf-8").read()
    con = sqlite3.connect(db_path)
    before = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0]
    con.executescript(script)
    con.commit()
    after = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0]
    # A view can be created over a missing table and only fail when queried, so
    # every view is executed once rather than trusted.
    bad = []
    for (n,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='view'").fetchall():
        try:
            con.execute(f"SELECT * FROM {q(n)} LIMIT 1").fetchone()
        except sqlite3.Error as e:
            bad.append((n, str(e)[:60]))
    con.close()
    print(f"applied {os.path.basename(sql_path)} -> {os.path.basename(db_path)}"
          f"   views {before} -> {after}")
    if bad:
        print(f"   ! {len(bad)} views do not execute:")
        for n, e in bad[:8]:
            print(f"       {n}: {e}")
    else:
        print("   all views execute")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", help="directory of per-database SQLite files")
    ap.add_argument("--out", help="path of the merged database")
    ap.add_argument("--dataset", default="bird", choices=("bird", "spider"))
    ap.add_argument("--from-db", dest="from_db",
                    help="reference database to extract the view layer from")
    ap.add_argument("--dump_benchmark", metavar="OUT.sql",
                    help="write the benchmark view layer to a .sql file and exit")
    ap.add_argument("--recreate_benchmark", metavar="IN.sql",
                    help="after merging (or on an existing --out), replay this "
                         "view layer onto the database")
    ap.add_argument("--with-views", action="store_true",
                    help="also copy views (default: base tables only)")
    ap.add_argument("--on-collision", choices=("abort", "prefix", "skip"),
                    default="abort")
    ap.add_argument("--all-dbs", dest="all_dbs", action="store_true",
                    help="merge every database found under --src instead of "
                         "restricting to the dataset's published union")
    ap.add_argument("--force", action="store_true",
                    help="overwrite --out if it already exists")
    ap.add_argument("--dry_run", action="store_true")
    a = ap.parse_args()

    # --- dump mode: read a reference database, write the .sql, done
    if a.dump_benchmark:
        if not a.from_db:
            sys.exit("--dump_benchmark needs --from-db <reference database>")
        dump_benchmark(a.dataset, a.from_db, a.dump_benchmark)
        return

    # --- replay-only mode: no merge, just apply the view layer to --out
    if a.recreate_benchmark and not a.src:
        if not a.out or not os.path.exists(a.out):
            sys.exit("--recreate_benchmark without --src needs an existing --out")
        recreate_benchmark(a.out, a.recreate_benchmark)
        return

    if not a.src or not a.out:
        sys.exit("provide --src and --out (or --dump_benchmark / "
                 "--recreate_benchmark on an existing --out)")

    dbs = discover(a.src)
    if not dbs:
        sys.exit(f"no .sqlite/.db files found under {a.src}")

    # A source directory may hold the benchmark's whole collection rather than
    # the subset the union is built from -- Spider ships 166 databases but
    # Spider-Union uses 19. Restrict to the dataset's own db_dict so the merge
    # reproduces the published union instead of everything on disk. This also
    # drops `singer`, which Spider-Union excludes for a table-name collision
    # with `concert_singer`.
    if not a.all_dbs:
        sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
        from _common.datasets import DATASET_TABLES      # noqa: E402
        want = {d.lower() for d in DATASET_TABLES[a.dataset]["db_dict"]}
        chosen = OrderedDict((k, v) for k, v in dbs.items() if k.lower() in want)
        missing = sorted(want - {k.lower() for k in chosen})
        skipped = len(dbs) - len(chosen)
        if missing:
            sys.exit(f"{len(missing)} database(s) in the {a.dataset} union are "
                     f"absent from {a.src}: {missing[:6]}")
        if skipped:
            print(f"restricting to the {a.dataset} union: {len(chosen)} of "
                  f"{len(dbs)} databases on disk ({skipped} not in db_dict)")
        dbs = chosen

    # ---- plan, and detect collisions before touching anything
    plan, owner = [], {}
    clashes = defaultdict(list)
    kinds = ["table"] + (["view"] if a.with_views else [])
    for db, path in dbs.items():
        con = sqlite3.connect(path)
        for kind in kinds:
            for name, sql in objects(con, kind):
                key = name.lower()
                if key in owner:
                    clashes[name].append(db)
                    clashes[name].insert(0, owner[key]) if len(
                        clashes[name]) == 1 else None
                owner.setdefault(key, db)
                plan.append((db, path, kind, name, sql))
        con.close()

    if clashes and a.on_collision == "abort":
        print("TABLE NAME COLLISIONS -- refusing to merge:")
        for n, ds in clashes.items():
            print(f"   {n}: {sorted(set(ds))}")
        sys.exit("re-run with --on-collision prefix|skip to decide explicitly")

    ntab = sum(1 for p in plan if p[2] == "table")
    print(f"{len(dbs)} source databases -> {ntab} tables"
          f"{' (+views)' if a.with_views else ''}")
    for db, path in dbs.items():
        n = sum(1 for p in plan if p[0] == db and p[2] == "table")
        print(f"   {db:26s} {n:3d} tables   {os.path.basename(path)}")
    if a.dry_run:
        print("\ndry run -- nothing written")
        return

    if os.path.exists(a.out):
        if not a.force:
            sys.exit(f"{a.out} exists; pass --force to overwrite")
        os.remove(a.out)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    out = sqlite3.connect(a.out)
    out.execute("PRAGMA foreign_keys=OFF")     # insertion order must not matter
    out.execute("PRAGMA journal_mode=OFF")
    made, copied, renamed = 0, 0, []

    for db, path in dbs.items():
        out.execute("ATTACH DATABASE ? AS src", (path,))
        for pdb, _, kind, name, sql in plan:
            if pdb != db or kind != "table":
                continue
            target = name
            if owner[name.lower()] != db:          # a collision we were told to handle
                if a.on_collision == "skip":
                    continue
                target = f"{db}_{name}"
                renamed.append((db, name, target))
                sql = sql.replace(name, target, 1)
            out.execute(sql)
            n = out.execute(
                f"INSERT INTO main.{q(target)} SELECT * FROM src.{q(name)}"
            ).rowcount
            made += 1
            copied += max(n, 0)
        # indexes and triggers after the data, so the load is not slowed by them
        scon = sqlite3.connect(path)
        for kind in ("index", "trigger"):
            for iname, isql in objects(scon, kind):
                try:
                    out.execute(isql)
                except sqlite3.Error as e:
                    print(f"   ! {db}: could not recreate {kind} {iname}: {e}")
        scon.close()
        out.commit()
        out.execute("DETACH DATABASE src")

    if a.with_views:
        for db, path in dbs.items():
            scon = sqlite3.connect(path)
            for vname, vsql in objects(scon, "view"):
                try:
                    out.execute(vsql)
                except sqlite3.Error as e:
                    print(f"   ! {db}: could not recreate view {vname}: {e}")
            scon.close()
        out.commit()

    if renamed:
        print(f"\nrenamed {len(renamed)} colliding tables:")
        for db, old, new in renamed:
            print(f"   {db}: {old} -> {new}")

    # ---- verify against the sources rather than trusting the writes
    print(f"\nwrote {a.out}")
    tabs = [r[0] for r in out.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]
    fks = sum(len(list(out.execute(f'PRAGMA foreign_key_list({q(t)})')))
              for t in tabs)
    print(f"   {len(tabs)} tables, {copied:,} rows, {fks} foreign-key edges")

    bad = 0
    for db, path in dbs.items():
        scon = sqlite3.connect(path)
        for name, _ in objects(scon, "table"):
            tgt = name if owner[name.lower()] == db else f"{db}_{name}"
            try:
                x = scon.execute(f"SELECT COUNT(*) FROM {q(name)}").fetchone()[0]
                y = out.execute(f"SELECT COUNT(*) FROM {q(tgt)}").fetchone()[0]
            except sqlite3.Error:
                continue
            if x != y:
                bad += 1
                print(f"   ! row mismatch {db}.{name}: source {x} merged {y}")
        scon.close()
    print(f"   row-count check: {'all tables match' if not bad else str(bad)+' MISMATCHES'}")
    out.close()

    if a.recreate_benchmark:
        print()
        recreate_benchmark(a.out, a.recreate_benchmark)


if __name__ == "__main__":
    main()
