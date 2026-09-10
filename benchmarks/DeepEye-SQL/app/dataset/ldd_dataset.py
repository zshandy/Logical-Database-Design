"""Dataset over the LDD merged schemas -- this is where +R is applied.

One SQLite file per dataset (merged_<ds>.sqlite) holds four object universes
side by side: original tables, renamed tables, original cluster views and
renamed cluster views. The arm picks one table universe; setting the object
scope here is what makes the whole run see it, because every later stage reads
the schema dict this class builds and the value index is enumerated through the
same load_table_names.

Views are deliberately NOT in the step-1 scope even on +A arms. They arrive at
stage 5.5. Exposing all 139 objects here measures ~121k tokens of schema profile
against a ~49k prompt budget, which would force progressive stripping to drop
include_value_examples and silently discard every retrieved value from the
linker prompts. Tables only is ~35k and fits.

Evidence is blanked at construction: the LDD runs use no hints and no column
descriptions anywhere, and DataItem.evidence is threaded into the keyword
extractor, both LLM linkers, all three generators, seven checkers and the
selection adjudicator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from tqdm import tqdm

from app.ldd.config import NL2SQL_CSV, Arm, arm_of
from app.ldd.object_scope import set_object_scope
from app.logger import logger
from app.services import get_schema_service

from .dataset import BaseDataset, DataItem


class LDDDataset(BaseDataset):
    """nl2sql_<ds>.csv evaluated against merged_<ds>.sqlite under one arm."""

    _name = "ldd"

    def _arm(self) -> Arm:
        arm = arm_of(self._config)
        if arm is None:
            raise ValueError("dataset.ldd_arm is required for type = 'ldd'")
        arm.validate()
        return arm

    def _load_data(self) -> List[DataItem]:
        arm = self._arm()

        scope = arm.linking_scope()
        set_object_scope(scope)
        logger.info(
            f"LDD arm {arm.suffix}: object scope = {len(scope)} objects "
            f"({'renamed' if arm.rename else 'original'} tables); "
            f"views injected at stage 5.5: {len(arm.views())}"
        )

        frame = pd.read_csv(NL2SQL_CSV[arm.dataset])
        if self._config.max_samples is not None:
            frame = frame.iloc[: self._config.max_samples]

        database_path = arm.db_path
        database_schema = get_schema_service().load_sqlite_schema(database_path)
        loaded = len(database_schema.get("tables", {}))
        if loaded != len(scope):
            logger.warning(
                f"schema loaded {loaded} objects but the arm scope lists {len(scope)}"
            )

        data: List[DataItem] = []
        for row_index, row in tqdm(frame.iterrows(), total=len(frame), desc="Loading data"):
            question = str(row.get("question", "")).strip()
            gold_sql = str(row.get("SQL", "")).strip()
            if not question:
                continue
            data.append(
                DataItem(
                    question_id=int(row_index),
                    question=question,
                    evidence="",            # no hints anywhere in the LDD runs
                    gold_sql=gold_sql,      # original namespace; see rename_map
                    difficulty=str(row.get("difficulty", "") or ""),
                    # the sqlite file stem, NOT the arm name: the value index,
                    # the schema dict's db_id and the vector store are all keyed
                    # on it, and an arm-specific id makes every value lookup miss
                    database_id=Path(database_path).stem,
                    database_path=database_path,
                    database_schema=database_schema,
                )
            )
        return data

    def _get_database_path(self, database_id: str) -> str:
        return self._arm().db_path

    def get_all_database_paths(self) -> List[str]:
        return [self._arm().db_path]
