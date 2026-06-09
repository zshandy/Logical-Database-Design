"""Shared write-back-to-input-CSV + EX evaluation helpers.

After a baseline finishes generating predictions for some subset of rows, it
calls :func:`write_back_to_input_csv` to:

  1. Merge the new prediction columns (e.g. ``basesql_revised_sql_<suffix>``)
     into the **input** CSV — multiple runs accumulate side-by-side without
     overwriting each other (different suffixes → different column names).
  2. Compute the EX result for the final-SQL column via :func:`compare_sql`
     and write it to ``<final_sql_col>_result`` (0/1 per row).
  3. Save the merged frame back to the input CSV path.

The per-run output CSV/JSONL in ``LDD/outputs/<baseline>/...`` stays as-is
(immutable audit copy).
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional

import pandas as pd
from func_timeout import FunctionTimedOut, func_set_timeout


@func_set_timeout(15)
def _execute_sql(cursor, sql: str):
    cursor.execute(sql)
    return cursor.fetchall()


def compare_sql(
    predicted_sql: str,
    ground_truth: str,
    db_path: str,
    index=None,
    verbose: bool = True,
):
    """Return ``(ex_result, predicted_rows, ground_truth_rows)``.

    ``ex_result`` is 1 when ``set(predicted_rows) == set(ground_truth_rows)``,
    0 otherwise (including when either query raises or times out at 15s).
    Verbose mode prints a diagnostic when prediction differs from gold.
    """
    conn = None
    ground_truth_res: list = []
    try:
        conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
        conn.text_factory = bytes
        cursor = conn.cursor()

        # 1. Execute ground truth (silent failure — gold can be malformed too).
        try:
            ground_truth_res = _execute_sql(cursor, ground_truth)
        except (Exception, FunctionTimedOut):
            return 0, None, []

        # 2. Execute prediction (verbose error reporting).
        try:
            predicted_res = _execute_sql(cursor, predicted_sql)
        except FunctionTimedOut:
            if verbose:
                print(f"{index}\n  predicted sql: {predicted_sql}\n  ground truth: {ground_truth}\n  raises an error: time out.\n  --------------------")
            return 0, None, ground_truth_res
        except Exception as e:
            if verbose:
                print(f"{index}\n  predicted sql: {predicted_sql}\n  ground truth: {ground_truth}\n  raises an error: {e}.\n  --------------------")
            return 0, None, ground_truth_res

        # 3. Set-based matching.
        if set(predicted_res) == set(ground_truth_res):
            return 1, predicted_res, ground_truth_res
        if verbose:
            print(f"{index}\n  predicted sql: {predicted_sql}\n  ground truth: {ground_truth}\n  set mismatch\n  --------------------")
        return 0, predicted_res, ground_truth_res
    finally:
        if conn is not None:
            try:
                conn.interrupt()
                conn.close()
            except Exception:
                pass


def write_back_to_input_csv(
    csv_path: str,
    df_predicted: pd.DataFrame,
    column_names: List[str],
    final_sql_col: str,
    db_path: str,
    gold_sql_col: str = "SQL",
    pipeline_tag: str = "",
):
    """Merge prediction columns from ``df_predicted`` into the input CSV at
    ``csv_path``, compute EX for ``final_sql_col`` vs ``gold_sql_col``, and
    overwrite the file.

    - ``column_names`` are copied by row index. Rows not in ``df_predicted.index``
      keep whatever value the input CSV had (NaN if the column is new).
    - ``<final_sql_col>_result`` is filled only for rows present in
      ``df_predicted.index`` AND with non-null prediction + gold.
    - Result column is created if missing; existing values for rows not in
      this run are preserved.
    """
    full_df = pd.read_csv(csv_path)

    # 1. Merge prediction columns (by row index).
    for col in column_names:
        if col not in full_df.columns:
            full_df[col] = pd.NA
        if col not in df_predicted.columns:
            continue
        for idx in df_predicted.index:
            if idx not in full_df.index:
                continue
            val = df_predicted.at[idx, col]
            # Skip NaN-valued cells so a partial run doesn't blank out a
            # previously-populated cell from another run with the same suffix.
            try:
                if pd.isna(val):
                    continue
            except (TypeError, ValueError):
                pass
            full_df.at[idx, col] = val

    # 2. Compute EX for the final SQL column.
    result_col = f"{final_sql_col}_result"
    if result_col not in full_df.columns:
        full_df[result_col] = pd.NA

    results: list = []
    if final_sql_col in full_df.columns and gold_sql_col in full_df.columns:
        for idx in df_predicted.index:
            if idx not in full_df.index:
                continue
            pred = full_df.at[idx, final_sql_col]
            gold = full_df.at[idx, gold_sql_col]
            try:
                if pd.isna(pred) or pd.isna(gold):
                    continue
            except (TypeError, ValueError):
                pass
            res, _, _ = compare_sql(str(pred), str(gold), db_path, index=idx, verbose=True)
            full_df.at[idx, result_col] = res
            results.append(res)
    else:
        missing = [c for c in (final_sql_col, gold_sql_col) if c not in full_df.columns]
        tag = f"[{pipeline_tag}] " if pipeline_tag else ""
        print(f"{tag}⚠️  EX skipped — missing column(s): {missing}")

    # 3. Save back.
    full_df.to_csv(csv_path, index=False)

    tag = f"[{pipeline_tag}] " if pipeline_tag else ""
    print(f"{tag}💾 wrote {len(column_names)} prediction column(s) + {result_col} to {csv_path}")
    if results:
        ex_score = sum(results) / len(results)
        print(f"{tag}📊 EX = {sum(results)}/{len(results)} = {ex_score:.4f}")
