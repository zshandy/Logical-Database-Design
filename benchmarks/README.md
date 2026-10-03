# Benchmarks

Five text-to-SQL pipelines, run on the original schema and on the paper's
optimized schema.

## Quick start

You need Python 3.9, an OpenAI API key, and the BIRD dev databases
([bird-bench.github.io](https://bird-bench.github.io/) → `dev.zip` →
`dev_databases/`).

```bash
pip install -r benchmarks/requirements.txt
export OPENAI_API_KEY=sk-...
```

Then run two commands from the repository root:

```bash
# 1. Build the merged BIRD database with the paper's optimized schema
python benchmarks/create_database.py --dataset bird --src /path/to/dev_databases --out databases/merged_bird.sqlite --recreate_benchmark benchmarks/recreate_database/bird_benchmark_views.sql

# 2. Run BaseSQL with all three transformations on the first 20 questions
cd benchmarks/basesql && python basesql.py --dataset bird --history --rename --view --cluster --rows 20
```

Step 1 merges the 11 BIRD databases into one file and adds the optimized
schema as views. It also copies the question sets and mapping files into
`csvs/` and `mapping_files/`. It makes no LLM calls. In step 2, drop
`--rows 20` to run all 767 questions.

For Spider, download `spider.zip` from
[yale-lily.github.io/spider](https://yale-lily.github.io/spider) and change
step 1 to `--dataset spider --src /path/to/spider/database --out
databases/merged_spider.sqlite --recreate_benchmark
benchmarks/recreate_database/spider_benchmark_views.sql`. Then use
`--dataset spider` in step 2.

To build an optimized schema for your own database, see
**[PREP_DATABASE.md](PREP_DATABASE.md)**.

## Configurations

Every pipeline takes the same three flags. Leave all three off for the
baseline.

| Flag | Paper | Effect |
|---|---|---|
| `--view` | +A, Schema Abstraction | adds views that pre-join tables, so the model can skip joins |
| `--cluster` | +P, Schema Partitioning | narrows the schema to the tables the workload uses together |
| `--rename` | +R, Schema Renaming | uses the renamed tables and columns |

`--history` adds the three most similar history questions as examples. Every
run in the paper uses it.

## Output

- Each run adds its SQL and an EX column (`..._result`, 1 = correct) to
  `csvs/nl2sql_<ds>.csv`. The column names show the pipeline and the flags,
  e.g. `basesql_revised_sql_rename_withview_clusterfilter_history`.
- EX is printed at the end of the run.
- The prompts and responses for each question are saved under
  `logs/<pipeline>/<ds>/`.

## Pipelines

Run each pipeline from its own folder. The commands below run BIRD with all
three transformations. Change the flags for other configurations.

### BaseSQL

Links tables, generates SQL, then revises it. Needs `OPENAI_API_KEY`.

```bash
cd benchmarks/basesql
python basesql.py --dataset bird --history --rename --view --cluster
```

### DIN-SQL

Links tables, classifies the question, generates SQL, then self-corrects.
Needs `OPENAI_API_KEY`.

```bash
cd benchmarks/din-sql
python dinsql.py --dataset bird --history --rename --view --cluster
```

### MAC-SQL

Three agents: Selector, Decomposer and Refiner. Needs `OPENAI_API_KEY`.

```bash
cd benchmarks/MAC-SQL
python run_union.py --dataset bird --history --rename --view --cluster
```

It also writes a JSONL file to `outputs/MAC-SQL/<ds>/`. By default the
Selector picks the tables. To use the table links the paper's runs used, add
`--linking_source disk --linking_filename <file>` with one of the shipped
files: `history_linking.json` (BIRD), `workload_updated_history_linking.json`
(BIRD, +R), `history_linking_spider.json` (Spider) or
`renamed_history_linking_spider.json` (Spider, +R).

### CSC-SQL

Samples several SQL candidates with local models, then merges them. Needs
Linux (or WSL), a GPU and vLLM. Install it once:

```bash
cd benchmarks/csc_sql
pip install -r requirements.txt && pip install -e .
```

Then run:

```bash
python run_single_db.py --dataset bird --history --rename --view --cluster \
    --model_table_link cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-7B-Instruct \
    --model_sql_generate cycloneboy/CscSQL-Grpo-Qwen2.5-Coder-7B-Instruct \
    --model_sql_merge cycloneboy/CscSQL-Merge-Qwen2.5-Coder-7B-Instruct
```

On a smaller GPU, use the 3B models with `--quantization fp8` and a lower
`--gpu_memory_utilization`. Intermediate files go to `outputs/csc_sql/<ds>/`.

### AutoLink

An agent grows the schema step by step, then generates and selects SQL. Needs
`DEEPSEEK_API_KEY` and a GPU. Install `AutoLink/requirements.txt` first.

```bash
cd benchmarks/AutoLink/run
./prep_all.sh bird        # once per dataset; add a number (e.g. 20) to use only that many questions
./run_arm.sh bird apr     # +A+P+R
```

The arms are `base`, `a`, `p`, `r`, `ap`, `ar`, `pr` and `apr`, one per
configuration. `run_arm.sh` writes the SQL and EX into `csvs/nl2sql_<ds>.csv`
when it finishes.

## Common flags

BaseSQL, DIN-SQL, MAC-SQL and CSC-SQL share these flags.

| Flag | Default | Meaning |
|---|---|---|
| `--dataset` | `spider` | `bird` or `spider` (BEAVER: `dw`, `neutron`, `nova`) |
| `--rows` | all | `20` runs the first 20 questions; `100:200` runs a slice |
| `--model` | `gpt-4.1-mini` | models named `gemini-*` use `GEMINI_API_KEY` |
| `--history` | off | add the retrieved history examples |
| `--no-cluster_filter` | — | with `--cluster`: add the cluster's join paths but keep the full schema |
| `--csv_path`, `--db_path`, `--mapping_path` | auto | override the default file locations |

Run any entry point with `--help` for the full list. The shared flags are
defined in [`_common/cli_common.py`](_common/cli_common.py).

## Scoring

BaseSQL, DIN-SQL, MAC-SQL and CSC-SQL use `compare_sql` in
[`_common/evaluate.py`](_common/evaluate.py). It runs the predicted and the
gold SQL on the same database. They match when they return the same set of
rows. Errors and timeouts (15 s) count as wrong.

AutoLink uses its own comparator, `compare_pandas_table` in
[`AutoLink/run/sql_selection.py`](AutoLink/run/sql_selection.py), which its
prompt is written for. Its EX column ends in `_result_lenient`.

## Datasets

| | Databases | Tables | Test / history questions |
|---|---|---|---|
| BIRD-Union | 11 | 75 | 767 / 767 |
| Spider-Union | 19 | 78 | 502 / 502 |

The BEAVER splits (`dw`, `neutron`, `nova`) run on MySQL. Set `MYSQL_HOST`,
`MYSQL_PORT`, `MYSQL_USER` and `MYSQL_PASSWORD`, or point `MYSQL_ENV_FILE` at
a `.env` file. Then run e.g. `python basesql.py --dataset dw --history`.
`--rename` and `--view` need `prep_database.py` to be run on the split first.

## Files

| Path | Contents |
|---|---|
| `create_database.py` | builds the merged database; `--recreate_benchmark` adds the paper's optimized schema |
| `prep_database.py` | builds an optimized schema for a new database ([PREP_DATABASE.md](PREP_DATABASE.md)) |
| `recreate_database/` | the paper's optimized schema (`*_benchmark_views.sql`), question sets and mapping files |
| `_common/` | code the pipelines share: flags, schema prompts, clusters, scoring |
| `basesql/`, `din-sql/`, `MAC-SQL/`, `csc_sql/`, `AutoLink/` | the five pipelines |

These folders are created at the repository root: `databases/` (merged
SQLite files), `csvs/` (question sets, where results are written),
`mapping_files/` (rename and view lists), `logs/` and `outputs/`.
