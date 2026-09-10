# Benchmarks

Six NL2SQL pipelines evaluated under the same three schema transformations.
Each takes a question CSV + a merged SQLite database and writes predictions
plus per-question prompt logs.

| Pipeline | Entry point | Strategy | LLM |
|---|---|---|---|
| **basesql** | [basesql/basesql.py](basesql/basesql.py) | link → generate → revise | API |
| **din-sql** | [din-sql/dinsql.py](din-sql/dinsql.py) | link → classify (easy/non-nested/nested) → generate → self-correct | API |
| **MAC-SQL** | [MAC-SQL/run_union.py](MAC-SQL/run_union.py) | Selector → Decomposer → Refiner (multi-agent) | API |
| **csc_sql** | [csc_sql/run_single_db.py](csc_sql/run_single_db.py) | sampling + merge/correction | local vLLM |
| **AutoLink** | [AutoLink/run/run_arm.sh](AutoLink/run/run_arm.sh) | agentic schema completion → candidates → selection | DeepSeek API |
| **DeepEye-SQL** | [DeepEye-SQL/script/run_ldd_spider_all.sh](DeepEye-SQL/script/run_ldd_spider_all.sh) | value retrieval → 3 linkers → generate → revise → select | API or local |

The first four share one CLI surface and are run from their own folder.
AutoLink and DeepEye-SQL are vendored upstream repos with our integration
layered on; they keep their own multi-step drivers — see
[AutoLink](#autolink) and [DeepEye-SQL](#deepeye-sql).

The three transformations map to the paper's operators:

| Flag | Paper name | Effect |
|---|---|---|
| `--rename` | Schema Renaming (**+R**) | LLM-renamed tables/columns, to resolve lexical ambiguity |
| `--view` | Schema Abstraction (**+A**) | inject pre-computed multi-table views, so the model skips complex joins |
| `--cluster` | Schema Partitioning (**+P**) | prune the prompt schema to a workload-mined partition |

---

## Layout

```
Logical-Database-Design/
├── csvs/                  nl2sql_<ds>.csv (eval) + sample_<ds>.csv (history)
├── databases/             merged_<ds>.sqlite            (gitignored)
├── mapping_files/         prep_<ds>[_renamed].json       (gitignored)
└── benchmarks/
    ├── _common/           LLM clients, schema builder, clusters, FK graph
    ├── create_database.py  step 0 — build the union DB
    ├── prep_database.py    step 1 — rename + clusters + views
    ├── recreate_database/  shipped view layer, CSVs, mapping
    ├── basesql/  din-sql/  MAC-SQL/  csc_sql/
    └── AutoLink/  DeepEye-SQL/
```

Paths resolve from `--dataset` relative to the LDD root, so the shared data
folders need no arguments.

---

## Quick start

**1. Build the union database.** The benchmarks ship one SQLite file per
database; every experiment runs against a single union of all of them. Bring
your own BIRD dev / Spider dev download — `databases/` is gitignored.

```bash
cd benchmarks
python create_database.py --dataset bird \
    --src ../databases/bird_base_databases \
    --out ../databases/merged_bird.sqlite \
    --recreate_benchmark recreate_database/bird_benchmark_views.sql
```

`--recreate_benchmark` replays the paper's exact view layer, so you skip the
LLM prep entirely. Full detail: **[PREP_DATABASE.md](PREP_DATABASE.md)**.

**2. Or generate your own schema prep** (one-time per database + history):

```bash
python prep_database.py --db_path ../databases/merged_bird.sqlite \
    --history_path ../csvs/sample_bird.csv --rename --cluster --view
```

**3. Install and set a key.**

```bash
pip install -r benchmarks/requirements.txt
export OPENAI_API_KEY=sk-...     # GEMINI_API_KEY for gemini-*, DEEPSEEK_API_KEY for AutoLink
```

No keys are embedded in code; all are read via `os.environ`.

**4. Run a pipeline with all three operators.**

```bash
cd benchmarks/basesql
python basesql.py --dataset bird --rename --view --cluster --history
```

Swap the folder and entry point for din-sql or MAC-SQL (which needs
`--output_file`). Add `--rows 20` for a smoke test.

---

## Common flags

Shared by basesql, din-sql, MAC-SQL and csc_sql, with identical names and
semantics. Bool toggles are `--flag` / `--no-flag`, never `--flag true`.
Defined in [`_common/cli_common.py`](_common/cli_common.py).

| Flag | Default | Purpose |
|---|---|---|
| `--dataset` | `spider` | `spider`, `bird`, or the BEAVER splits `dw`/`neutron`/`nova`. Drives default paths, table/view lists, log dir. |
| `--model` | `gpt-4.1-mini` | Names starting with `gemini` route to Google GenAI, else OpenAI. |
| `--csv_path` / `--db_path` | auto | Eval CSV / SQLite DB. |
| `--rows` | all | `N` = first N, `START:END` = half-open slice. |
| `--question_col` / `--sql_col` | auto | Read from the prep JSON's `columns` section if present. |
| `--rename` | off | +R. `--rename_v VAR` overrides the table list. |
| `--view` | off | +A. `--view_v VAR` overrides the pool. |
| `--cluster` | off | +P. Injects matched clusters' join paths and restricts history retrieval to cluster questions. Requires history. |
| `--cluster_filter` | **on with `--cluster`** | Also restricts the stage-2/3 schema to the cluster's tables. Pass `--no-cluster_filter` to inject join paths without pruning — that A/B is a real distinction, and which one the paper reports varies by pipeline and dataset. |
| `--history` | off | Top-K retrieval from `sample_<ds>.csv`. `--history_path FILE` implies it. Embedded with BGE-large-en-v1.5; K=3. |
| `--sample` | 100 | Percent of history to use. `<100` sub-samples at seed 42 **and** auto-maps the `_N` table/view/mapping variants. |
| `--use_linking COL` | none | Read stage-1 links from a CSV column and skip the linking call. How every published arm was run. |
| `--mapping_path` | auto | Prep JSON (`prep_<ds>[_renamed].json`). Also accepts flat legacy `name_mapping_*.json`. |
| `--per_db` | off | Restrict schema, views, clusters and retrieval to each question's `db_id`. |

Two `--view` variants build views on demand instead of using the pool, both
requiring `--use_linking`: `--view_adhoc` (LLM writes a fresh `CREATE VIEW`
per question) and `--view_relink` (match pool views, inject, re-run stage 1).

**Auto-resolved paths** — `csvs/nl2sql_{ds}.csv`,
`databases/merged_{ds}.sqlite`, `csvs/sample_{ds}.csv` (with `--history`),
`mapping_files/prep_{ds}[_renamed].json` (with `--rename`/`--cluster`). With
`--sample N`, each picks up its `_N` variant, along with `--rename_v` →
`{ds}_renamed_tables_{N}` and `--view_v` → `{ds}_{org,renamed}_views_{N}`.
Available variants are whatever exists in
[`_common/datasets.py`](_common/datasets.py) — currently `0` and `50`.

---

## Outputs

basesql and din-sql append columns to a copy of the input CSV; MAC-SQL writes
JSONL; csc_sql writes to `outputs/{dataset}/`. Per-question prompt logs go to
`logs/<pipeline>/<dataset>/run_<timestamp><suffix>/qNNNN.log`.

| Column | Contains |
|---|---|
| `linking{suffix}` | stage-1 links (or the `--use_linking` column verbatim) |
| `sql{suffix}` | generated SQL |
| `revised_sql{suffix}` | revised SQL — the final answer |

`{suffix}` encodes the flag combination (e.g.
`_rename_withview_clusterfilter_history_top3`) so configurations don't
collide. din-sql adds `dinsql_*` equivalents plus `dinsql_label{suffix}`.

---

## Pipeline notes

### basesql / din-sql

No extra flags. Prompts in [basesql/prompts.py](basesql/prompts.py) and
[din-sql/prompts.py](din-sql/prompts.py).

### MAC-SQL

| Flag | Purpose |
|---|---|
| `--output_file` | required — JSONL output path |
| `--fresh` | ignore prior output instead of resuming |
| `--without_selector` | Decomposer sees the full schema |
| `--linking_source` | `selector` (default) · `gold` · `disk` |
| `--linking_filename` | required with `disk` |

`selector` is the honest default: it runs the Selector once on the full schema
as a pre-pass and takes its picked tables, costing one extra call per row and
leaking nothing. `gold` reads `gt_tables` and is for smoke tests only. `disk`
loads a pre-computed linking JSON — four ship here:
`history_linking.json` / `workload_updated_history_linking.json` (BIRD, org /
+R) and `history_linking_spider.json` /
`renamed_history_linking_spider.json` (Spider). Those files are what the
published runs read, from a time when disk-loading was the only behaviour, so
`disk` is the path to bit-exact reproduction; `selector` re-links live and will
land near but not on the reported numbers.

### csc_sql

Sampling-and-merge over a local or remote vLLM server. Requires the three
model flags: `--model_table_link`, `--model_sql_generate`,
`--model_sql_merge` (typically a Qwen2.5-Coder-7B checkpoint).

| Group | Flags |
|---|---|
| Sampling | `--n_table_link` 4 · `--n_sql_generate` 8 · `--n_sql_merge` 4 · matching `--temperature_*` 0.8 · `--history_k` 3 · `--prompt_name` `think` · `--value_limit_num` 2 · `--seed` 42 |
| vLLM | `--visible_devices` · `--tensor_parallel_size` · `--gpu_memory_utilization` 0.90 · `--quantization` `bitsandbytes` · `--api_base_generate` / `--api_base_merge` for a remote server |
| Resume | `--stage1_from` `auto` · `--stage0_from` · `--skip_preprocess` · `--input_file` |
| Eval | `--run_eval` · `--eval_step` · `--eval_mode` `major_voting` · `--output_dir` · `--run_time` |

### AutoLink

Vendored from [wzy416/AutoLink](https://github.com/wzy416/AutoLink). Agentic
schema completion: an LLM iteratively calls retrieval / SQL-execution tools to
grow an initially incomplete schema, then generates candidates and selects by
execution majority. Needs `DEEPSEEK_API_KEY` (V3 for the agent loop, R1 for
candidates) and a GPU for BGE retrieval.

Our integration lives alongside upstream's `run/` scripts:

| File | Role |
|---|---|
| `ldd_config.py` | the six arms and their column/namespace choices |
| `ldd_runtime.py` | the history-SQL and common-join-path prompt blocks AutoLink has no notion of |
| `prep_ldd_inputs.py` | dumps the exposed object universe + question file per arm |
| `apply_apr.py` | injects +A views and +P cluster tables/join paths between retrieval and the agent loop |
| `object_lists.json` | the org / renamed / view object universe per dataset |

Arms are `base`, `opt1`, `opt2` and their `--rename` twins `rbase`, `ropt1`,
`ropt2`. Prep must run before the arm, and builds documents + embeddings for
every namespace at once:

```bash
cd benchmarks/AutoLink/run
./prep_all.sh spider              # add a row cap as a 2nd arg for a pilot
./run_arm.sh  spider ropt2        # +A+P+R
```

`run_arm.sh` writes to `run/log_<ds><suffix>/` (gitignored). Steps 1–11
produce the selected SQL at
`log_<ds><suffix>/sql_selection/final/<instance>/selected.sql`, with the
executed rows beside it in `result.csv`.

Step 12 calls `export_results.py`, which is **not shipped** — it scores the
arm and writes into `csvs/nl2sql_<ds>.csv`, so it lives with the analysis
scripts. Upstream AutoLink ships no evaluator of its own, so scoring an arm
means either restoring that script or scoring
`selected.sql` yourself. Note it does **not** use `compare_sql`: see
[Scoring](#scoring).

### DeepEye-SQL

Vendored from [HKUSTDial/DeepEye-SQL](https://github.com/HKUSTDial/DeepEye-SQL).
Config-driven rather than flag-driven, with its own Python env
(`pyproject.toml` / `uv.lock`).

```bash
cd benchmarks/DeepEye-SQL
cp config/template/ldd/config-ldd-spider.toml config/local/ldd/my-arm.toml
# edit: [llm_profiles] model/base_url/api_key, [embedding], and
#       [dataset] ldd_arm_name = base | rap_opt1 | rap_opt2
export CONFIG_PATH=config/local/ldd/my-arm.toml
bash script/run_ldd_spider_all.sh
```

The shipped templates carry **placeholder** URLs and default to a self-hosted
Qwen3-Coder-30B plus Qwen3-Embedding-0.6B; point them at whatever you have.
`config/local/` is gitignored — keep keys there, never in `template/`.
`[dataset] max_samples = N` caps the row count.

| File | Role |
|---|---|
| `app/ldd/` | arm config, history loading, object scope, rename map |
| `app/pipeline/apr/apr_injection.py` | stage 5.5 — injects +A views and +P clusters after linking |
| `app/dataset/ldd_dataset.py` | the `type = "ldd"` dataset adapter |
| `runner/run_schema_linking_phase_{a,b}.py` | splits linking so few-shot prep can see the cluster |
| `runner/run_value_retrieval_stub.py` | dry-run stand-in for value retrieval |

**Two things that bite.** First, `rap_opt2` is **two-phase and order-sensitive**:
phase A (direct + value linkers) → cluster-aware few-shot prep reading phase
A's snapshot → delete that snapshot → phase B (reversed linker). Running
few-shot prep *before* phase A makes the second call skip both items and emit
a snapshot with examples but no linking, and phase B then fails validation on
missing required fields. Second, real value retrieval indexes every TEXT
column — 3.4M distinct values / ~21 GB on merged_bird — so use
`run_value_retrieval_stub.py` for anything short of a full run, and note it
contributes no value links.

Scoring: upstream's own `runner/evaluation.py` and
`runner/benchmark_execution.py` both ship. Our `export_ldd_results` — which
writes into `csvs/nl2sql_<ds>.csv` — does not, and does not use `compare_sql`
either; see [Scoring](#scoring).

---

## Scoring

**All six pipelines report the same strict EX**, from
[`_common/evaluate.py`](_common/evaluate.py)'s `compare_sql`: execute both
sides against the same database and compare **`set(predicted) == set(gold)`**,
with a 15 s per-query timeout and raw bytes (`text_factory = bytes`). Any
execution error or timeout scores 0. Gold is always the original-namespace
`SQL` column — renamed tables and cluster views are views over the same rows,
so the reference result set is unchanged.

**AutoLink additionally reports a lenient metric**, and only AutoLink does.
That metric is not ours: it is `compare_pandas_table` in
[AutoLink/run/sql_selection.py](AutoLink/run/sql_selection.py), shipped
upstream and originally Spider 2.0's official comparator (AutoLink targets
Spider2.0-Lite). It transposes both results to column vectors and requires
every *gold* column to match some *predicted* column, tolerating extra
predicted columns, with `math.isclose(abs_tol=1e-2)` on numbers. AutoLink's
generation prompt is written for exactly that rule — *"the execution result can
be more than what is required by the question, but it must not be less"* — so
whole-result equality penalises predictions that answer the question and carry
extra columns. It is reported *alongside* strict EX, never instead of it, and
never applied to another pipeline.

Both exporters previously carried their own **strict** metric — multiset
equality with row order enforced when gold had `ORDER BY`, on `str()`-coerced
values — which made their EX incomparable with the other four. That is gone;
there is one strict metric, defined in one place, and the lenient one calls
upstream's function directly rather than a local copy. Re-scoring with
`compare_sql` moves every arm **up**, by 0.8–2.0 points on Spider-Union and
2.7–3.7 on BIRD-Union, because `set` collapses duplicate rows that multiset
equality was failing on.

---

## Datasets

`spider` and `bird` are wired end-to-end. Each defines, in
[`_common/datasets.py`](_common/datasets.py): `org_tables`, `renamed_tables`,
`org_views`, `renamed_views`, their `_0`/`_50` sampled variants, and a
`db_dict` of `db_id → tables` for `--per_db`. Add a dataset by appending to
`DATASET_TABLES`.

| | Databases | Tables | Rows | FK edges | Eval / history |
|---|---|---|---|---|---|
| BIRD-Union | 11 | 75 | 3,932,735 | 105 | 767 / 767 |
| Spider-Union | 19 | 78 | 539,844 | 63 | 502 / 502 |

### BEAVER splits (MySQL)

`dw`, `neutron`, `nova` are the three [BEAVER](https://arxiv.org/abs/2409.02038)
enterprise databases. They differ in three ways: each is standalone (no merge,
`--per_db` inapplicable); they live in **MySQL**, so `--db_path` resolves to
`mysql://<name>` and everything goes through
[`_common/db_backend.py`](_common/db_backend.py) with MySQL-dialect prompts;
and `--rename` / `--view` are unsupported until `prep_database.py` has been
run for a split.

| Split | Tables | Test | History | Declared FKs |
|---|---|---|---|---|
| `dw` | 97 | 2,894 | 2,893 | none |
| `neutron` | 175 | 509 | 508 | 163 |
| `nova` | 109 | 527 | 526 | 25 |

CSVs are built from BEAVER's `dev.json` with a 50/50 split at seed 40. Every
field is retained, but nothing feeds `domain_knowledge` into a prompt — these
are BEAVER's hint-free `setting=0`.

Credentials come from `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` /
`MYSQL_PASSWORD` (the names BEAVER's own evaluator uses). Process environment
wins; gaps fill from `MYSQL_ENV_FILE`, then `<LDD_ROOT>/.env`.

```bash
export MYSQL_ENV_FILE=/path/to/beaver/.env
pip install pymysql
python basesql.py --dataset dw --history
```

An explicit URI bypasses the environment: `--db_path "mysql://user:pass@host:3306/dw"`.

---

## See also

- [PREP_DATABASE.md](PREP_DATABASE.md) — building the database and the schema-prep phases
- [`_common/cli_common.py`](_common/cli_common.py) — shared argparse and path resolution
- [`_common/datasets.py`](_common/datasets.py) — every static table/view list
- [`_common/clusters.py`](_common/clusters.py) — frequent-pattern clustering
- [`_common/history.py`](_common/history.py) — history clusters from CSV
- [`_common/adhoc_view.py`](_common/adhoc_view.py) — LLM-designed views
