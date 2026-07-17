# Logical-Database-Design

## The Case for Text-to-SQL Friendly Logical Database Design

NL2SQL pipelines fail in predictable, structural ways: they miss join paths,
over-join irrelevant tables, and misread cryptic identifiers. This work treats
the schema itself as a tuning target — given a base schema 𝒮 and a workload 𝓗
of question/SQL pairs, an **offline schema transformation** step produces an
optimized schema 𝒮′ that any off-the-shelf text-to-SQL pipeline can consume
unchanged.

Three composable transformations cover the three failure modes:

- **Schema Abstraction** (`--view`) — pre-computed multi-table views that let
  the model bypass complex joins
- **Schema Partitioning** (`--cluster`) — workload-mined table clusters that
  prune contextual noise from the prompt schema
- **Schema Renaming** (`--rename`) — LLM-rewritten table/column names that
  resolve lexical ambiguity between question and schema

![Pipeline](imgs/pipeline.png)

Each transformation targets a specific class of failure on the base schema 𝒮.
Worked examples on the BIRD chemistry schema — incomplete join path, erroneous
over-join, and lexical ambiguity — together with the matching mitigation:

![Failure modes and mitigations](imgs/paper_diagram-5-1.png)

---

## Paper

[The Case for Text-to-SQL Friendly Logical Database Design (arXiv:2606.03145)](https://arxiv.org/abs/2606.03145)

## Code

The four NL2SQL pipelines (basesql, din-sql, csc_sql, MAC-SQL) plus the
schema-prep script live under [`benchmarks/`](benchmarks/):

- [`benchmarks/README.md`](benchmarks/README.md) — 4-step quick start + flag reference for all four pipelines
- [`benchmarks/PREP_DATABASE.md`](benchmarks/PREP_DATABASE.md) — schema-prep walkthrough (rename + cluster + view artifacts)
