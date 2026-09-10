"""DRY-RUN ONLY: pass-through stand-in for step 3 (value retrieval).

Why this exists
---------------
Steps 2-3 build a per-column vector index over every TEXT column of the
database. On BIRD-dev that is a small per-database index. On merged_bird.sqlite
it is **3,419,638 distinct TEXT values across 359 columns** -- 21 GB of vectors
at 1536 dims, or 5 GB at 384 -- because the code's "Selective Value Extraction"
is only a declared-type filter (``_is_text_column_type``); the paper's stated
heuristics for excluding UUIDs and numeric identifiers are not implemented, so
columns like Forum_History.revision_id (193,951 values) and
Forum_Comments.created_at (174,100) get indexed in full.

That is a real-run infrastructure problem, not something a dry run should pay.
This stub therefore writes the two fields the downstream stages actually read:

    retrieved_values                      = {}
    database_schema_after_value_retrieval = database_schema

Consequences, stated plainly:
  * the value linker returns {} (it iterates retrieved_values), so linking is
    direct + reversed only -- 18.0% column recall standing alone in the paper,
    and the one component the LDD integration does not touch
  * schema profiles carry no retrieved value examples, so linker prompts are
    smaller than in a real run

Everything the LDD work actually changes -- object scope / +R, opt1 vs opt2
linking, stage 5.5, join paths, view-SQL ICL, generation, revision, selection --
is exercised normally.

    uv run runner/run_value_retrieval_stub.py
"""

import sys
sys.path.append(".")

from app.dataset import load_dataset, save_dataset
from app.logger import configure_logger, logger


def main() -> None:
    from app.config import get_config

    app_config = get_config()
    configure_logger(app_config.logger_config.print_level)

    dataset = load_dataset(app_config.dataset_config.save_path)
    zero = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for data_item in dataset:
        data_item.question_keywords = []
        data_item.retrieved_values = {}
        data_item.database_schema_after_value_retrieval = data_item.database_schema
        data_item.value_retrieval_time = 0.0
        data_item.value_retrieval_llm_cost = dict(zero)
        data_item.total_time = data_item.total_time or 0.0
        data_item.total_llm_cost = data_item.total_llm_cost or dict(zero)

    save_dataset(dataset, app_config.value_retrieval_config.save_path)
    logger.warning(
        f"DRY RUN: value retrieval stubbed for {len(dataset)} items -- "
        f"value linker will contribute nothing. Snapshot: "
        f"{app_config.value_retrieval_config.save_path}"
    )


if __name__ == "__main__":
    main()
