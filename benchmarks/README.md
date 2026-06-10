# Benchmarks

Four NL2SQL pipelines that share a common dataset layout and CLI surface. Each
pipeline takes the same question CSV + SQLite DB, applies its own
schema-linking and SQL-generation strategy, and writes augmented CSVs +
per-question logs.

| Pipeline | Stages | Entry point | Strategy |
|----------|--------|-------------|----------|
| **basesql** | 3 | [basesql/basesql.py](basesql/basesql.py) | Schema-link → SQL gen → SQL revise |
| **din-sql** | 4 | [din-sql/dinsql.py](din-sql/dinsql.py) | Schema-link → classify (EASY / NON-NESTED / NESTED) → SQL gen (per-label) → self-correct |
| **csc_sql** | 3 | [csc_sql/run_single_db.py](csc_sql/run_single_db.py) | Table-link sampling → SQL gen sampling → merge/correction (uses local vLLM by default) |
| **MAC-SQL** | 3 | [MAC-SQL/run_union.py](MAC-SQL/run_union.py) | Selector (schema pruning) → Decomposer → Refiner (multi-agent) |

All four are designed to be **run from their own folder** so paths inside the
script can resolve relative siblings without arguments.

---

## Repository layout

```
Logical-Database-Design/
├── csvs/                       # nl2sql input CSVs + history sample CSVs
│   ├── nl2sql_spider.csv       #   spider questions to answer
│   ├── nl2sql_bird.csv         #   bird questions to answer
│   ├── sample_spider.csv       #   spider history (for --history mode)
│   └── sample_bird.csv         #   bird history
├── databases/                  # merged SQLite DBs (gitignored — drop your own here)
│   ├── merged_spider.sqlite
│   └── merged_bird.sqlite
├── mapping_files/              # name-mapping JSONs (for --rename mode)
│   ├── name_mapping_spider.json
│   └── name_mapping_bird.json
└── benchmarks/
    ├── _common/                # shared utilities (LLM clients, schema, clusters, …)
    ├── basesql/
    ├── din-sql/
    ├── csc_sql/
    └── MAC-SQL/
```

The four pipeline folders share the data folders above via relative
``../../{csvs,databases,mapping_files}/`` paths, auto-resolved from the
``--dataset`` flag.

---

## Quick start

End-to-end walkthrough to get from "fresh clone" to "running the pipeline
with all augmentations on". For the per-flag reference, see
[Common CLI flags](#common-cli-flags) and the per-pipeline sections below.

### Step 1 — Prepare your inputs

Drop three files into the LDD root. Defaults assume `<dataset>` is `bird` or
`spider`; pass `--db_path` / `--csv_path` / `--history_path` to point
elsewhere.

**(a) A merged SQLite database** at `databases/merged_<dataset>.sqlite`.

A single `.sqlite` file containing the base tables of **every source database
you want covered**, merged side by side into one file. Tables from different
source DBs just live in the same `.sqlite` — no namespacing required. The
prep step (and downstream baselines) use naming + workload signals to figure
out which tables came from which source. The file is gitignored; bring your
own.

**(b) A benchmark CSV** at `csvs/nl2sql_<dataset>.csv`.

Required columns (defaults; override with `--question_col` / `--sql_col`):

| Column | Default name | Purpose |
|--------|--------------|---------|
| Question | `question` | NL question to answer. |
| Gold SQL | `SQL` | Ground-truth SQL. Used only for EX accuracy / verification — predicted SQLs are produced either way. |
| (optional) DB tag | `db_id` | Source-DB id, used only by `--per_db` mode. |

**(c) A history CSV** at `csvs/sample_<dataset>.csv` (recommended).

Same shape as the benchmark CSV (`question` + `SQL` columns). This is the
workload that `prep_database.py` mines for table co-occurrence patterns and
that the baselines retrieve top-K similar SQLs from at inference time. If you
don't have a separate workload file, you can point `--history_path` at your
training-split CSV.

### Step 2 — Install dependencies

```bash
pip install -r benchmarks/requirements.txt
```

Then set the LLM API key for the model you'll use:

```bash
export OPENAI_API_KEY=sk-...      # default; required for gpt-* models
export GEMINI_API_KEY=...          # only when --model starts with 'gemini'
```

No keys are embedded in the code; everything is read via `os.environ.get`.

### Step 3 — Run `prep_database.py` once

`prep_database.py` is the schema-prep step. Given the merged sqlite + history
CSV from Step 1, it produces a single consolidated JSON
(`mapping_files/prep_<dataset>[_renamed].json`) holding the rename mapping,
the table-set clusters, and the cluster-view definitions. Every baseline
loads this JSON directly — you don't have to rerun prep_database per
baseline.

See **[PREP_DATABASE.md](PREP_DATABASE.md)** for the full phase-by-phase
walkthrough and the complete flag reference. The recommended command for
full-augmentation use is:

```bash
cd benchmarks
python prep_database.py \
    --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv \
    --rename --cluster --view
```

This is a one-time cost per (database, history) pair. The history CSV is
rewritten in place with new columns (`renamed_SQL`, `renamed_view_SQL`, ...)
and a timestamped backup. Cached prompts + raw LLM responses land under
`outputs/prep_database/<timestamp>/` for auditing.

### Step 4 — Run a pipeline with full augmentation

Full augmentation = `--rename --view --history --cluster` — the paper's
three schema transformations (Schema Renaming + Schema Abstraction + Schema
Partitioning) layered on top of history-driven top-K retrieval. The flag set
is shared across all four pipelines; the only thing that changes between
them is which folder you `cd` into.

```bash
cd benchmarks/basesql
python basesql.py --dataset bird --rename --view --history --cluster
```

For the other three baselines:

```bash
# DIN-SQL
cd benchmarks/din-sql
python dinsql.py --dataset bird --rename --view --history --cluster

# MAC-SQL (writes JSONL, needs --output_file)
cd benchmarks/MAC-SQL
python run_union.py --dataset bird --rename --view --history --cluster \
                    --output_file outputs/bird_run.jsonl

# CSC-SQL (local vLLM by default; pick checkpoints for each stage)
cd benchmarks/csc_sql
python run_single_db.py --dataset bird --rename --view --history --cluster \
                        --model_table_link   <checkpoint> \
                        --model_sql_generate <checkpoint> \
                        --model_sql_merge    <checkpoint>
```

Add `--rows 50` for a quick smoke test over the first 50 questions, or
`--rows 100:150` for a slice. CSC-SQL's pipeline-specific flags (vLLM,
remote API mode, sampling counts) are documented in
[CSC-SQL section](#csc_sql) below.

---

## Common CLI flags

**All four pipelines share the same flag names and the same toggle style.**
Bool toggles use `--flag` / `--no-flag` form (Python `argparse.BooleanOptionalAction`
or `store_true`) — never `--flag true/false` strings. Paths use the same names
across all four (`--csv_path`, `--db_path`, `--history_path`, `--mapping_path`,
…). Each pipeline's `parse_args()` adds **only** its pipeline-specific flags
on top — see the "Pipeline-specific flags" subsections below.

The shared definition for basesql + din-sql lives in
[`_common/cli_common.py`](_common/cli_common.py); csc_sql and MAC-SQL repeat
the same names with the same semantics in their own argparse blocks.

The three schema-transformation flags map directly to the three
transformations introduced in [the paper](../README.md):

| Flag | Paper name | What it does |
|------|------------|--------------|
| `--rename` | **Schema Renaming** | Switch to LLM-renamed tables/columns to resolve lexical ambiguity. |
| `--view` | **Schema Abstraction** | Inject pre-computed multi-table views so the model bypasses complex joins. |
| `--cluster` | **Schema Partitioning** | Prune the prompt schema to a workload-mined, question-relevant partition. |

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--dataset` | choice | `spider` | One of `spider`, `bird`. Drives default paths, table/view lists, and log folder. |
| `--model` | str | `gpt-4.1-mini` | Names starting with `gemini` route through Google GenAI; everything else uses OpenAI. |
| `--csv_path` | str | auto | Input CSV with questions. Defaults to `../../csvs/nl2sql_{dataset}.csv`. |
| `--db_path` | str | auto | SQLite DB. Defaults to `../../databases/merged_{dataset}.sqlite`. |
| `--rows` | str | all | Row selection. `N` = first N rows, `START:END` = python-style half-open slice. |
| `--question_col` | str | `question` | Input-CSV column holding the question. |
| `--sql_col` | str | `SQL` | Input-CSV column holding the (optional) ground-truth SQL. |

### History mode (`--history`)

3-state flag:

| Combo | Effect |
|-------|--------|
| neither `--history` nor `--history_path` | History disabled. |
| `--history` alone | Uses default `../../csvs/sample_{dataset}.csv`. |
| `--history_path FILE` | Uses `FILE`, **and** implicitly enables history. |

History sample CSVs are clustered, embedded via BGE-large-en-v1.5, and used
for top-K SQL retrieval during stages 2/3.

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--history` | bool | off | Turn history mode on. |
| `--history_path` | str | auto | Path to history CSV; implies `--history`. |
| `--sample` | int 1..100 | 100 | Percent of history rows to use. `<100` triggers a reproducible random sub-sample (seed=42) **and** auto-maps `_{N}` variants for bird/spider — see Auto-resolution below. |

### Schema renaming (`--rename`)

Switches base tables from `org_tables` to `renamed_tables` (which are
materialized as views in the merged sqlite). Triggers a translated FK block
in the prompt schema. Mitigates *lexical ambiguity* failures — e.g.
`molecule.label` carrying carcinogenicity values, which the model misses
because nothing in the identifier hints at the semantics.

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--rename` | bool | off | Use `renamed_tables` / `renamed_views` instead of `org_tables` / `org_views`. |
| `--rename_v` | str | auto | Override the renamed-tables list by module-variable name, e.g. `bird_renamed_tables_50`. Requires `--rename`. |
| `--mapping_path` | str | auto | Path to the name-mapping JSON. Defaults to `../../mapping_files/name_mapping_{dataset}.json`. Only used with `--rename`. |

### Schema abstraction (`--view`)

Per question, retrieves matching views from the pool by parsing stage-1
linked tables → view names. Mitigates *incomplete join path* failures by
giving the model a pre-computed multi-table view to draw from instead of
forcing it to infer the join. Two variants build views on demand:

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--view` | bool | off | Add matching pool views to the schema. |
| `--view_v` | str | auto | Override the views pool by module-variable name. Requires `--view`. |
| `--view_adhoc` | bool | off | LLM designs a fresh `CREATE VIEW` per question from stage-0 linked tables. Requires `--view` + `--use_linking`. |
| `--view_relink` | bool | off | Matches pre-defined views to stage-0 linked tables, injects them into stage 1, re-runs stage 1. Requires `--view` + `--use_linking`; mutually exclusive with `--view_adhoc`. |
| `--use_linking COLUMN` | str | none | CSV column name that already contains schema links. Skips stage-1 linking and uses this column directly. |

### Schema partitioning (`--cluster`)

Builds frequent table-set clusters from the history CSV (via
[`_common/clusters.py`](_common/clusters.py)) and uses them as workload-mined
partitions for both schema-restriction and history retrieval. Mitigates
*over-joining* failures by pruning tables outside the question's relevant
partition from the prompt schema.

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--cluster` | bool | off | Match each question to overlapping clusters; inject their common join paths into stage 2/3 prompts. Restricts top-K history retrieval to cluster questions. Requires `--history_path`. |
| `--cluster_filter` | bool | on when `--cluster` is set | Restrict the stage-2/3 schema to only the union of cluster tables. See [Notes](#notes) at the bottom for the default-on behaviour. |

### Per-database mode (`--per_db`)

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--per_db` | bool | off | Restrict base schema, views pool, clusters, and history retrieval to each question's `db_id` (from the input CSV's `db_id` column). Lazily caches per-db resources. Unknown `db_id`s warn and fall back to the full union. |

---

## More examples

Beyond the Quick Start above, these illustrate specific flag combinations
worth knowing about.

### DIN-SQL with a pre-computed linking column (skip stage 1)

```bash
cd Logical-Database-Design/benchmarks/din-sql
python dinsql.py --dataset bird --use_linking linking_gpt41 --history
```

### DIN-SQL with on-the-fly ad-hoc view creation

```bash
python dinsql.py --dataset bird --rename --view --view_adhoc \
                 --use_linking linking_renamed --history
```

### Gemini run (uses Google GenAI)

```bash
export GEMINI_API_KEY=...
python basesql.py --dataset spider --model gemini-2.5-flash-lite
```

### CSC-SQL with a remote vLLM server

```bash
cd Logical-Database-Design/benchmarks/csc_sql
python run_single_db.py \
    --dataset bird \
    --model_table_link    Qwen2.5-Coder-7B \
    --model_sql_generate  Qwen2.5-Coder-7B \
    --model_sql_merge     Qwen2.5-Coder-7B \
    --api_base_generate   http://192.168.1.100:8000/v1 \
    --api_base_merge      http://192.168.1.100:8001/v1 \
    --rename --view --history --cluster
```

### Sub-sampled history (`--sample 50`)

```bash
python basesql.py --dataset bird --rename --history --sample 50 --cluster
```

Auto-maps the 50%-sampled mapping file, table list, and views pool — no need
to pass `--mapping_path`, `--rename_v`, or `--view_v`.

### Slice rows for a quick smoke test

```bash
python basesql.py --dataset spider --rows 100:150     # 50 rows
python dinsql.py  --dataset bird   --rows 10           # first 10
```

---

## Outputs

Each pipeline writes per-question logs and an augmented output CSV / JSONL.

| Pipeline | Log dir | Output file |
|----------|---------|-------------|
| basesql (spider) | `logs/run_{timestamp}{suffix}/q{NNNN}.log` | `nl2sql_spider{suffix}_out.csv` |
| basesql (bird)   | `logs_bird/run_...`                            | `nl2sql_bird{suffix}_out.csv` |
| din-sql (spider) | `logs_din/run_...`                             | `nl2sql_spider{suffix}_dinsql_out.csv` |
| din-sql (bird)   | `logs_din_bird/run_...`                        | `nl2sql_bird{suffix}_dinsql_out.csv` |
| csc_sql          | `outputs/{dataset}/...`                        | `outputs/{dataset}/{run_time}/...` |
| MAC-SQL          | `--log_file` if set                            | `--output_file` (JSONL) |

The `{suffix}` encodes the flag combination (e.g. `_rename_withview_clusterfilter_history_perdb_top3_gpt41`)
so multiple configurations don't collide.

The augmented output CSV adds these columns to the input (basesql/din-sql):

| Column (basesql) | Contains |
|------------------|----------|
| `linking{suffix}` | Stage-1 schema links (or `--use_linking` column verbatim if stage 1 was skipped). |
| `sql{suffix}` | Stage-2 generated SQL. |
| `revised_sql{suffix}` | Stage-3 revised SQL (the final answer). |

DIN-SQL adds parallel `dinsql_*` columns plus `dinsql_label{suffix}` and
`dinsql_sub_questions{suffix}` from the stage-2 classifier.

---

## Auto-resolution defaults

When you don't pass `--csv_path`, `--db_path`, `--history_path`, or
`--mapping_path`, each pipeline resolves them relative to the LDD root
(two directories above the pipeline script):

| Flag | Default path |
|------|--------------|
| `--csv_path` | `../../csvs/nl2sql_{dataset}.csv` |
| `--db_path` | `../../databases/merged_{dataset}.sqlite` |
| `--history_path` | `../../csvs/sample_{dataset}.csv` (only when `--history` is set) |
| `--mapping_path` | `../../mapping_files/name_mapping_{dataset}.json` (only when `--rename` is set) |

When `--sample N` is passed with `N<100` and `--dataset` is `bird` or `spider`,
the following are auto-mapped to their `_N` variants (unless explicitly
overridden):

| Flag | Auto-mapped to |
|------|----------------|
| `--csv_path` | `../../csvs/nl2sql_{dataset}_{N}.csv` (if file exists) |
| `--history_path` | `../../csvs/sample_{dataset}_{N}.csv` |
| `--mapping_path` | `../../mapping_files/name_mapping_{dataset}_{N}.json` |
| `--rename_v` | `{dataset}_renamed_tables_{N}` (when `--rename` is set) |
| `--view_v` | `{dataset}_renamed_views_{N}` (with `--rename`) or `{dataset}_org_views_{N}` |

The supported `--sample` values are determined by which variants are present
in [`_common/datasets.py`](_common/datasets.py) — currently `0` and `50` for
both spider and bird.

---

## What can be used

### Datasets

`spider` and `bird` are wired end-to-end. Each has:

- An `org_tables` list (the source schema)
- A `renamed_tables` list (used with `--rename`)
- An `org_views` and `renamed_views` pool (used with `--view`)
- `_50` and `_0` sampled variants (used with `--sample 50` / `--sample 0`)
- A `db_dict` mapping `db_id → tables` for `--per_db` mode

All defined in [`_common/datasets.py`](_common/datasets.py). To add a new
dataset, append to `DATASET_TABLES` there.

### Models

Anything OpenAI accepts as a `chat.completions.create(model=...)` value, plus
Google GenAI models when the name starts with `gemini`. Defaults:

- basesql / din-sql / MAC-SQL: `gpt-4.1-mini`
- csc_sql: pass `--model_table_link` / `--model_sql_generate` /
  `--model_sql_merge` (typically a vLLM-hosted Qwen2.5-Coder checkpoint)

The pipeline ID suffixes appended to log dirs encode the model digits — e.g.
`gpt-4.1-mini` → `_gpt41`, `gemini-2.5-flash-lite` → `_gem25`,
`gpt-5.4-mini` → `_gpt54`.

### Rename variants

| Variable name pattern | Where defined | Used when |
|----------------------|---------------|-----------|
| `{dataset}_org_tables` | datasets.py | default (no `--rename`) |
| `{dataset}_renamed_tables` | datasets.py | `--rename` |
| `{dataset}_renamed_tables_{N}` | datasets.py | `--rename --sample N` |
| `{dataset}_org_views` | datasets.py | `--view` (no rename) |
| `{dataset}_org_views_{N}` | datasets.py | `--view --sample N` (no rename) |
| `{dataset}_renamed_views` | datasets.py | `--view --rename` |
| `{dataset}_renamed_views_{N}` | datasets.py | `--view --rename --sample N` |

You can override either tables or views explicitly:

```bash
python basesql.py --dataset bird --rename --rename_v bird_renamed_tables_0
python basesql.py --dataset bird --view   --view_v   bird_org_views_50
```

---

## Pipeline-specific flags

### basesql

No basesql-only flags — the common set above is complete. Stage prompts live
in [basesql/prompts.py](basesql/prompts.py); the per-question driver is in
[basesql/pipeline.py](basesql/pipeline.py).

### din-sql

Same flag set as basesql. Stages 2–4 swap in DIN-SQL-style classification +
nested/non-nested branching + self-correction; templates live in
[din-sql/prompts.py](din-sql/prompts.py) (16 templates spanning the 4 stages).

### csc_sql

CSC-SQL accepts the **common flags** (`--dataset`, `--csv_path`, `--db_path`,
`--rows`, `--question_col`, `--sql_col`, `--rename`, `--mapping_path`,
`--view`, `--history`, `--history_path`, `--cluster`, `--cluster_filter`)
with the same semantics as basesql. The additional flags below are
CSC-SQL-specific and exist because it has a sampling-and-merge architecture
running on a local (or remote) vLLM server.

**Models (required)** — CSC-SQL has 3 separately-configurable LLM stages:

| Flag | Purpose |
|------|---------|
| `--model_table_link` | Model name for stage 1 (table linking). |
| `--model_sql_generate` | Model name for stage 2 (SQL generation). |
| `--model_sql_merge` | Model name for stage 3 (merge / correction). |

**Sampling** — CSC-SQL draws multiple LLM samples per stage and votes:

| Flag | Default | Purpose |
|------|---------|---------|
| `--n_table_link` | 4 | Sampling count for stage 1. |
| `--n_sql_generate` | 8 | Sampling count for stage 2. |
| `--n_sql_merge` | 4 | Sampling count for stage 3. |
| `--temperature_table_link` | 0.8 | Stage 1 sampling temperature. |
| `--temperature_sql_generate` | 0.8 | Stage 2 sampling temperature. |
| `--temperature_sql_merge` | 0.8 | Stage 3 sampling temperature. |
| `--history_k` | 3 | Top-K history queries to retrieve (basesql/din-sql/MAC-SQL hardcode 3). |
| `--prompt_name` | `think` | Prompt variant. |
| `--bm25_index_path` | auto | BM25 column-value index. |
| `--value_limit_num` | 2 | Sampled values per column. |
| `--seed` | 42 | Random seed. |

**vLLM inference server** — for local GPU inference:

| Flag | Default | Purpose |
|------|---------|---------|
| `--visible_devices` | `0` | `CUDA_VISIBLE_DEVICES`. |
| `--tensor_parallel_size` | 1 | vLLM TP size. |
| `--gpu_memory_utilization` | 0.90 | vLLM GPU memory fraction. |
| `--quantization` | `bitsandbytes` | `bitsandbytes` (INT8) or `None` (bf16). |
| `--api_base_generate` | none | Remote vLLM server URL for stages 1+2 (skips local startup). |
| `--api_base_merge` | none | Remote vLLM server URL for stage 3. |

**Reuse / resume**:

| Flag | Default | Purpose |
|------|---------|---------|
| `--stage1_from` | `auto` | Reuse a prior run's stage-1 outputs. `auto`, `fresh`, or a path. |
| `--stage0_from` | none | Use a prior run's stage 1 as a stage-0 schema pre-prune. Requires `--cluster_filter`, `--cluster`, `--history_path`. |
| `--skip_preprocess` | off | Skip preprocessing; use existing `--input_file`. |
| `--input_file` | none | Pre-existing processed JSON (skips preprocessing). |

**Eval & output**:

| Flag | Default | Purpose |
|------|---------|---------|
| `--run_eval` | off | Run gold-SQL execution for EX accuracy. Predicted SQLs are still produced regardless. |
| `--eval_step` | `pipeline` | Which step to run/eval. |
| `--eval_mode` | `major_voting` | How to aggregate samples into a single SQL. |
| `--output_dir` | `outputs` | Where to write results. |
| `--run_time` | auto | Run-id suffix; defaults to current timestamp. |

### MAC-SQL

MAC-SQL is the original multi-agent design (Selector → Decomposer →
Refiner) with our schema-restriction additions bolted on. It accepts the
**common flags** with the same names and semantics as basesql:
`--dataset`, `--csv_path`, `--db_path`, `--rows`, `--question_col`,
`--sql_col`, `--rename`, `--mapping_path`, `--view`, `--history`,
`--history_path`, `--cluster`, `--cluster_filter`.

The flags below are MAC-SQL-specific:

| Flag | Default | Purpose |
|------|---------|---------|
| `--output_file` | required | Path to output JSONL file (MAC-SQL writes JSONL, not CSV). |
| `--log_file` | none | Path to prompt log file. |
| `--fresh` | off | Ignore previous output and start over. Default: resume from prior `--output_file`. |
| `--without_selector` | off | Skip the Selector agent entirely — Decomposer sees the full schema. (Conceptually distinct from `--use_linking` in basesql/din-sql.) |
| `--history_sql_col_prefix` | auto | Override the SQL-column prefix in the history CSV (auto-derived from `--dataset` + `--rename`: `workload_updated_` / `renamed_` / `''`). Rarely needed. |

---

## Notes

**`--cluster_filter` defaults to ON whenever `--cluster` is set.** That's the
configuration that consistently helps — `--cluster` injects join-path hints,
and `--cluster_filter` additionally restricts the stage-2/3 schema to only
the union of cluster tables. To A/B test the filter's contribution in
isolation (i.e. inject cluster join paths without schema restriction), pass
`--no-cluster_filter` alongside `--cluster`. The flag has no effect when
`--cluster` is off.

---

## See also

- [PREP_DATABASE.md](PREP_DATABASE.md) — full walkthrough for the schema-prep step (rename + clusters + cluster views)
- [`_common/cli_common.py`](_common/cli_common.py) — shared argparse + path resolvers
- [`_common/datasets.py`](_common/datasets.py) — all static table/view lists
- [`_common/clusters.py`](_common/clusters.py) — frequent-pattern clustering
- [`_common/adhoc_view.py`](_common/adhoc_view.py) — LLM-designed view creation
- [`_common/history.py`](_common/history.py) — history-clusters-from-CSV builder
- Per-pipeline README files in each subfolder (where present)
