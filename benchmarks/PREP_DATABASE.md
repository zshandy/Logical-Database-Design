# Building and preparing the database

Two steps sit before any pipeline runs:

- **`create_database.py`** merges the benchmarks' per-database SQLite files
  into one union database, and can replay the paper's exact view layer.
- **`prep_database.py`** is the LLM-assisted schema prep. It produces one
  consolidated JSON — the "prep JSON" — that every pipeline reads to know
  which tables are active, how columns were renamed, which table-sets cluster
  together, and which cluster-views exist.

If you only want to reproduce the paper, you need step 1 and the shipped
`.sql` — **not** step 2. See
[Recreating the published database](#recreating-the-published-database).

---

## Step 1 — `create_database.py`

The benchmarks ship one SQLite file per database (BIRD dev: 11; Spider dev:
20, of which the published Spider-Union uses 19). Every experiment here runs
against a single *union* of them, because the point of the study is a schema
large enough that table selection is genuinely hard.

**Get the source databases first.** They are the benchmarks' own files and are
not redistributed here — `databases/` is gitignored. Download the dev splits
yourself:

- BIRD: <https://bird-bench.github.io/> → `dev.zip`, whose `dev_databases/`
  holds the 11 per-database directories.
- Spider: <https://yale-lily.github.io/spider> → `spider.zip`, whose
  `database/` holds all 166 (Spider-Union uses 19 of them; `--dataset spider`
  selects them for you).

Point `--src` at whichever directory you unpacked them into — the layout on
disk does not matter and nothing has to be moved into `databases/`. `--src`
accepts the benchmark's nested form (`<src>/<db>/<db>.sqlite`) or a flat
directory of `<db>.sqlite`, and every other path is an explicit argument too,
so you can keep the downloads wherever they already live:

```bash
python create_database.py --dataset bird \
    --src /path/to/bird/dev_databases \
    --out /path/to/merged_bird_base.sqlite
```

| Flag | Default | Notes |
|---|---|---|
| `--src` / `--out` | — | source directory / merged output path |
| `--dataset` | `bird` | Restricts the merge to that dataset's **published union**, read from `_common/datasets.py`. This matters: a full Spider download has 166 database directories but Spider-Union uses 19 — without the restriction you silently build a different, much larger schema. |
| `--all-dbs` | off | merge everything under `--src` instead |
| `--on-collision` | `abort` | Two sources declaring the same table name. `abort` lists the clashes; `prefix` renames to `<db>_<table>`; `skip` keeps the first. BIRD and Spider have zero collisions, so this never fires — it exists so a different corpus can't silently lose a table. |
| `--with-views` | off | also copy views (the union is base tables only) |
| `--force` / `--dry_run` | off | overwrite `--out` / report and exit |

**What it preserves.** Each table is created from the source's own
`sqlite_master.sql` text, unmodified — so types, DEFAULTs, PRIMARY KEYs and
FOREIGN KEYs survive verbatim. Not cosmetic: the FK graph is what the star and
denormalisation catalogues derive from, so a merge that dropped or normalised
FKs would silently change downstream results. Explicit indexes and triggers
are copied too.

| Dataset | Source DBs | Tables | Rows | FK edges |
|---|---|---|---|---|
| BIRD-Union | 11 | 75 | 3,932,735 | 105 |
| Spider-Union | 19 | 78 | 539,844 | 63 |

Row counts match the sources table-for-table.

---

## Recreating the published database

On top of the base tables sit three view families, catalogued in
[`_common/datasets.py`](_common/datasets.py):

| Family | Used by |
|---|---|
| `renamed_tables` | +R — one view per base table under its renamed identifiers |
| `org_views` | +A — the workload-mined cluster catalogue |
| `renamed_views` | +A+R — the same catalogue over the renamed tables |

Re-running `prep_database.py` will **not** reproduce them, because the rename
and view-creation phases are LLM calls. So the exact layer ships as SQL and
replays offline.

Everything below is in [`recreate_database/`](recreate_database/):

| File | Contents |
|---|---|
| `bird_benchmark_views.sql` | 203 `CREATE VIEW` — 75 renamed tables + 64 org + 64 renamed |
| `spider_benchmark_views.sql` | 192 — 78 renamed tables + 57 org + 57 renamed |
| `name_mapping_{bird,spider}.json` | `table_to_view`, `column_mapping`, `columns` |
| `sample_{bird,spider}_min.csv` | history pool — 767 × 11 / 502 × 8 |
| `nl2sql_{bird,spider}_min.csv` | eval set + published predictions — 767 × 105 / 502 × 102 |

The `.sql` files are emitted in dependency order with per-family banners:
renamed tables and mined views read the base tables, and the renamed cluster
views read the renamed table views, so those come last.

```bash
# 1. merge the shipped per-database files
python create_database.py --dataset bird \
    --src ../databases/bird_base_databases --out ../databases/merged_bird_base.sqlite

# 2. capture the view layer from a reference DB (already done — this is how
#    the shipped .sql was produced)
python create_database.py --dataset bird --from-db ../databases/merged_bird.sqlite \
    --dump_benchmark recreate_database/bird_benchmark_views.sql

# 3. rebuild the full benchmark DB from (1) + (2) — no LLM, no reference DB
python create_database.py --dataset bird \
    --src ../databases/bird_base_databases --out ../databases/merged_bird.sqlite \
    --recreate_benchmark recreate_database/bird_benchmark_views.sql
```

Step 3 also accepts an existing `--out` with no `--src`, replaying the view
layer onto that database. Verified: recreation produces exactly the 203 and
192 views, all returning row counts identical to the reference databases.

### Columns in the shipped CSVs

`sample_<ds>_min.csv` is the history pool (the demonstrations retrieved at
inference time); `nl2sql_<ds>_min.csv` is the evaluation set. Spider's
benchmark files carry no `question_id`, `evidence` or `difficulty`, hence its
lower column counts.

**Inputs** — what the pipeline reads:

| Column | In | Purpose |
|---|---|---|
| `question_id`, `db_id`, `question`, `evidence`, `SQL`, `difficulty` | both | the benchmark's own fields; `SQL` is the gold used for execution scoring |
| `gt_tables` | both | ground-truth table set; drives cluster mining, so **+P cannot be reproduced without it** |
| `view_SQL` | sample | the demonstration rendered against the mined views — the second half of the top-k×2 block +A shows the model |
| `renamed_SQL`, `gt_renamed_tables`, `renamed_view_SQL` | sample | the same three in the +R namespace |
| `base_linking_41m_{org,renamed}` | nl2sql | recorded stage-1 linking. Reusing it via `--use_linking` is how every published arm skipped stage 1, so it is required to reproduce them *exactly* rather than approximately. |

`name_mapping_<ds>.json` carries a `columns` section declaring which of those
`--rename` should read (`sql: renamed_SQL`, `gt_tables: gt_renamed_tables`,
`view_sql: renamed_view_SQL`). Without it the pipeline defaults to `sql=SQL`,
the *original* namespace — a renamed schema with original-namespace
demonstrations, which degrades silently rather than erroring.

**Outputs** — the published predictions, for inspection; a reproduction should
regenerate these rather than read them:

```
<approach>_sql[_<config>]_<backbone>          the model's final SQL
<approach>_sql[_<config>]_<backbone>_result   1 if it matched gold on execution
```

| Part | Values |
|---|---|
| approach | `basesql`, `dinsql`, `macsql`, `cscsql` |
| config | *(omitted for baseline)*, `A`, `P`, `R`, `AP`, `AR`, `PR`, `APR` |
| backbone | `41m` (gpt-4.1-mini), `54m` (gpt-5.4-mini), `gem25` (gemini-2.5-flash-lite) |

e.g. `basesql_sql_41m`, `cscsql_sql_APR_41m_result`. All four approaches ship
at `41m`; `54m` and `gem25` are BaseSQL-only, matching the backbone table. 48
prediction + 48 result columns per dataset. The 50%-history ablation is not
shipped.

---

## Step 2 — `prep_database.py`

Only needed to prepare a **new** database. Each phase is independently gated.

| Phase | Flag | What it does |
|---|---|---|
| 1. Backup | always | copies the input to `<db>.bak.<timestamp>` before any modification |
| 2. Rename call | `--rename` | one prompt asking for a `CREATE VIEW` per base table — same rows and column order, with `AS` renames. Prompt and raw response are cached. |
| 3. Apply views | `--rename` | executes each view and checks its column count against the base table; re-prompts up to `--max_retries`, then falls back to identity |
| 4. Rename mapping | `--rename` | writes the `rename` section (`table_to_view`, `column_mapping`) and switches `tables` from originals to renamed views |
| 5. History rewrite | `--rename` + history | rewrites each history SQL against the renamed views, **verified by executing both and comparing result sets**; failures retry, then fall back to the original with `result=0` |
| 6. Cluster mining | `--cluster` (implied by `--view`) | no LLM — mines frequent table-set clusters from history ([`_common/clusters.py`](_common/clusters.py)). Saved to the JSON only with `--cluster`; in-memory when `--view` alone. |
| 7. Cluster views | `--view` | one `CREATE VIEW` per ≥2-table cluster joining on FKs. Retries `--view_max_create_retries`, then falls back to a code-based FK-walker using the schema plus JOIN edges seen in history. Skips clusters with no non-cartesian join. |
| 8. History rewrite (view) | `--view` + history | as phase 5, but the LLM may also use cluster views |

Every LLM call caches its prompt, raw response and parsed JSON to
`<LDD>/outputs/prep_database/<timestamp>/`, keyed by phase and attempt, so
each decision stays auditable. Labels: `prompt`/`raw`/`response` (phase 2),
`retryN` (3), `rewrite_*` (5), `view_create_cN_attemptM` and
`..._codefallback` (7), `view_rewrite_*` (8). Persistent failures appear in
the closing summary and, for renames, as identity entries in the JSON.

### Inputs

**Merged SQLite** (required) — default `<LDD>/databases/merged_<dataset>.sqlite`,
or `--db_path`. Backed up before any write.

**History CSV** (optional but needed for phases 5–8) — `--history` uses
`<LDD>/csvs/sample_<dataset>.csv`; `--history_path FILE` implies `--history`.
Needs a question column (`--question_col`, default `question`) and an
executable gold-SQL column (`--sql_col`, default `SQL`); every rewrite is
execution-verified against it. Other columns are preserved verbatim. The file
is **rewritten in place** with a timestamped backup, adding `renamed_SQL`,
`renamed_SQL_result`, `gt_renamed_tables`, `renamed_view_SQL`,
`renamed_view_SQL_result`.

### Flags

| Flag | Default | Notes |
|---|---|---|
| `--rename` / `--cluster` / `--view` | off | phase gates (2–5 / 6 / 6–8) |
| `--model` | `gpt-4.1-mini` | names starting with `gemini` route to Google GenAI |
| `--output_mapping_path` | `mapping_files/prep_<stem>[_renamed].json` | bare filename resolves under `mapping_files/`; absolute is used verbatim |
| `--cache_dir` | `outputs/prep_database/<timestamp>/` | prompts and responses |
| `--num_rows` / `--max_tokens` | 3 / 32000 | sample rows per table in the prompt / output cap |
| `--max_retries` | 3 | phase-3 view re-prompts |
| `--rewrite_max_retries` | 5 | phase-5 retries |
| `--view_max_create_retries` | 3 | phase-7 retries before the code fallback |
| `--view_max_rewrite_retries` | 5 | phase-8 retries |
| `--min_frequency` / `--min_tables` | 5 / 2 | a table-set needs this many history questions, and this many tables, to become a cluster |
| `--cluster_col` / `--cluster_sql_col` | inferred | history columns holding table lists / SQL for join paths. Default `gt_renamed_tables` with `--rename`, else `gt_tables`; missing → extracted from SQL via sqlglot. |
| `--dry_run` / `--cache_only` / `--from_cache PATH` | off | build the prompt and exit / stop after caching / skip the call and run phases 3–5 from a cached response |

Environment: `OPENAI_API_KEY`, or `GEMINI_API_KEY` for `gemini-*`. Both read
via `os.environ.get` in [`_common/llm.py`](_common/llm.py); nothing is
embedded. Core deps are `openai`, `google-genai`, `sqlglot`, `pandas`,
`func_timeout` (see [requirements.txt](requirements.txt)).

### Examples

```bash
# full pipeline — the recommended combination
python prep_database.py --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv --rename --cluster --view

# rename only, no history
python prep_database.py --db_path ../databases/merged_bird.sqlite --rename

# cluster views over the ORIGINAL schema, to isolate +A
python prep_database.py --db_path ../databases/merged_spider.sqlite \
    --history_path ../csvs/sample_spider.csv --cluster --view

# mine clusters only — no LLM call at all
python prep_database.py --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv --cluster

# preview the prompt before paying for it
python prep_database.py --db_path ../databases/merged_bird.sqlite --rename --dry_run
```

### Output: the prep JSON

All sections are optional — present only if the phase ran.

```jsonc
{
  "metadata": { "db_path": "...", "dataset_stem": "bird",
                "rename": true, "cluster": true, "view": true,
                "built_at": "2026-06-08T17:14:46" },

  // active tables for downstream pipelines: renamed views with --rename,
  // original base tables without
  "tables": ["chem_atom_dim", "club_member_roster", "..."],

  // history-CSV columns this run used; pipelines read these so you don't
  // have to retype --question_col / --sql_col
  "columns": { "question": "question", "sql": "renamed_SQL",
               "gt_tables": "gt_renamed_tables",
               "view_sql": "renamed_view_SQL" },

  "rename": { "table_to_view": { "atom": "chem_atom_dim" },
              "column_mapping": { "chem_atom_dim": { "atom_id": "atom_pk" } } },

  "cluster": { "cluster_col": "gt_renamed_tables", "min_frequency": 5,
               "min_tables": 2, "n_questions": 1534, "n_clusters": 47,
               "exact_clusters": [{ "cluster_id": 0, "tables": [], "paths": [] }],
               "question_cluster_map": { "0": [3, 7] } },

  "view": { "n_clusters": 47, "n_views_created": 39, "n_views_skipped": 8,
            "cluster_views": ["chem_atom_dim_join_chem_bond_xref"],
            "skipped_clusters": [{ "cluster_id": 12, "reason": "..." }] }
}
```

Pipelines load it through
[`_common/rename_mapping.py`](_common/rename_mapping.py)'s
`load_active_views`, which auto-detects the present sections.
