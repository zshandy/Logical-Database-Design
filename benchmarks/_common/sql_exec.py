"""SQL execution wrappers (timeouts, compare, validate)."""

from __future__ import annotations

import logging
import random
import sqlite3
from typing import Any, Dict, Tuple, Union

from func_timeout import FunctionTimedOut, func_set_timeout


@func_set_timeout(60)
def execute_sql(cursor, sql: str):
    """Execute a SQL statement against an open cursor (60s timeout)."""
    cursor.execute(sql)
    return cursor.fetchall()


def compare_sql(
    predicted_sql: str,
    ground_truth: str,
    db_path: str,
) -> Tuple[int, Any, Any]:
    """Execute ``predicted_sql`` and ``ground_truth`` and compare results as sets.

    Returns ``(match, predicted_res, ground_truth_res)`` where ``match`` is 1 if
    the result sets are equal, 0 otherwise (including on error/timeout).
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.text_factory = bytes
    cursor = conn.cursor()

    ground_truth_res = execute_sql(cursor, ground_truth)
    try:
        predicted_res = execute_sql(cursor, predicted_sql)
    except Exception:
        return 0, None, ground_truth_res
    except FunctionTimedOut:
        return 0, None, ground_truth_res

    res = 1 if set(predicted_res) == set(ground_truth_res) else 0
    return res, predicted_res, ground_truth_res


@func_set_timeout(15)
def val_execute_sql(db_path: str, sql: str, fetch: Union[str, int] = "all") -> Any:
    """Execute a SQL query and fetch results. ``fetch`` ∈ ``{"all","one","random",<int>}``."""
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            if fetch == "all":
                return cursor.fetchall()
            elif fetch == "one":
                return cursor.fetchone()
            elif fetch == "random":
                samples = cursor.fetchmany(10)
                return random.choice(samples) if samples else []
            elif isinstance(fetch, int):
                return cursor.fetchmany(fetch)
            else:
                raise ValueError(
                    "Invalid fetch argument. Must be 'all', 'one', 'random', or an integer."
                )
    except Exception as e:
        logging.error(f"Error in execute_sql: {e}\nSQL: {sql}")
        raise


def validate_sql_query(
    db_path: str,
    sql: str,
    max_returned_rows: int = 30,
) -> Dict[str, Union[str, Any]]:
    """Run ``sql`` and return ``{SQL, RESULT, STATUS}``.

    STATUS is one of ``NON EMPTY RESULT``, ``EMPTY RESULT``, ``ERROR``.
    """
    try:
        result = val_execute_sql(db_path, sql, fetch=max_returned_rows)
        if len(result) != 0:
            return {"SQL": sql, "RESULT": result, "STATUS": "NON EMPTY RESULT"}
        return {"SQL": sql, "RESULT": result, "STATUS": "EMPTY RESULT"}
    except Exception as e:
        logging.error(f"Error in validate_sql_query: {e}")
        return {"SQL": sql, "RESULT": str(e), "STATUS": "ERROR"}
    except FunctionTimedOut as e:
        logging.error(f"Function timed-out in execute_sql: {e}")
        return {"SQL": sql, "RESULT": str(e), "STATUS": "ERROR"}
