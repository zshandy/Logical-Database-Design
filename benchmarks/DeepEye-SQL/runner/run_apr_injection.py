"""Stage 5.5: LDD +A/+P injection between schema linking and SQL generation.

    uv run runner/run_apr_injection.py

Reads the schema-linking snapshot and writes its own, so it is idempotent: a
re-run recomputes from the same input instead of injecting a second time.
Skipped automatically for arms without +A or +P.
"""

import sys
sys.path.append(".")

from app.dataset import load_dataset, save_dataset
from app.logger import configure_logger, logger
from app.pipeline.apr import APRInjector


def main() -> None:
    from app.config import get_config

    app_config = get_config()
    configure_logger(app_config.logger_config.print_level)

    from app.ldd.config import arm_of
    arm = arm_of(app_config.dataset_config)
    if arm is None:
        logger.info("dataset.ldd_arm is not set -- not an LDD run, nothing to inject")
        return
    if not (arm.view or arm.cluster):
        logger.info(f"arm {arm.suffix} has neither +A nor +P -- nothing to inject")
        return

    stage = app_config.apr_injection_config
    dataset = load_dataset(app_config.schema_linking_config.save_path)
    injector = APRInjector(arm, history_top_k=stage.history_top_k,
                           max_join_paths=stage.max_join_paths)

    totals = {"n": 0, "no_cluster": 0, "cluster_tables": 0, "views": 0,
              "paths": 0, "cols_before": 0, "cols_after": 0}
    for data_item in dataset:
        if data_item.final_linked_tables_and_columns is None:
            logger.warning(f"item {data_item.question_id} has no linked schema; skipping")
            continue
        stats = injector.inject(data_item)
        totals["n"] += 1
        totals["no_cluster"] += int(stats["clusters"] == 0)
        for key in ("cluster_tables", "views", "paths", "cols_before", "cols_after"):
            totals[key] += stats[key]

    n = max(1, totals["n"])
    logger.info(
        f"APR injection [{arm.suffix}] {totals['n']} items | "
        f"no matching cluster {totals['no_cluster']} ({100*totals['no_cluster']/n:.1f}%) | "
        f"columns {totals['cols_before']/n:.1f} -> {totals['cols_after']/n:.1f} | "
        f"cluster tables {totals['cluster_tables']/n:.2f} | "
        f"views {totals['views']/n:.2f} | join paths {totals['paths']/n:.2f}"
    )
    save_dataset(dataset, stage.save_path)
    logger.info(f"APR injection snapshot saved: {stage.save_path}")


if __name__ == "__main__":
    main()
