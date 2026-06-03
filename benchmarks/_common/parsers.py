"""Regex/JSON extractors for LLM responses.

These helpers don't depend on a specific pipeline — they extract structured
data (JSON blocks, SQL statements, schema link lists, classification labels)
from the free-form text that LLMs emit.
"""

from __future__ import annotations

import ast
import re
from typing import List, Optional, Tuple


def extract_json_block(text: str) -> str:
    """Extract the JSON object from a ChatGPT response that may contain reasoning,
    code fences, or extra commentary.
    """
    text = text.replace(';\\"', ';"').replace('\\"SELECT', '"SELECT')
    if "```json" in text:
        match = re.search(r"```json(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0).strip()

    raise ValueError("No JSON found in response")


def extract_schema_links(input_text: str) -> List[str]:
    """Extract a ``Schema_links: [...]`` list from a stage-1 LLM response."""
    pattern = r"Schema_links:\s*\[(.*?)\]"
    match = re.search(pattern, input_text)
    if match:
        schema_links_str = match.group(1)
        return [link.strip() for link in schema_links_str.split(",")]
    return []


def extract_label_and_sub_questions(input_text: str) -> Tuple[str, List[str]]:
    """Extract a stage-2 ``Label: "..."`` + ``sub_questions: [...]`` block."""
    label_pattern = r'Label:\s*"(.*?)"'
    sub_questions_pattern = r"sub_questions:\s*\[(.*?)\]"

    label_match = re.search(label_pattern, input_text)
    sub_questions_match = re.search(sub_questions_pattern, input_text)

    label = label_match.group(1) if label_match else ""

    sub_questions: List[str] = []
    if sub_questions_match:
        sub_questions_str = sub_questions_match.group(1)
        sub_questions = [q.strip() for q in sub_questions_str.split(",")]

    return label, sub_questions


def extract_sql_query(input_text: str) -> Optional[str]:
    """Extract ``SQL: <stmt>`` from a stage-3 response."""
    sql_pattern = r"SQL:\s*(.*?)$"
    match = re.search(sql_pattern, input_text, re.DOTALL)
    return match.group(1).strip() if match else None


def extract_revised_sql_query(input_text: str) -> Optional[str]:
    """Extract ``Revised_SQL: <stmt>`` from a stage-4 (self-correction) response."""
    sql_pattern = r"Revised_SQL:\s*(.*?)$"
    match = re.search(sql_pattern, input_text, re.DOTALL)
    return match.group(1).strip() if match else None


def parse_retrieved_tables_from_links(schema_links) -> List[str]:
    """Parse ``schema_links`` (list or stringified list) → list of unique
    lowercase table names referenced in any ``table.column`` or
    ``table.col = table.col`` entry.
    """
    sl_raw = schema_links
    if isinstance(sl_raw, str):
        sl_raw = ast.literal_eval(sl_raw)
    temp_list = [x.replace("`", "").lower() for x in sl_raw if isinstance(x, str)]
    col_list: List[str] = []
    for i in temp_list:
        if len(i.split(".")) == 2 and "=" not in i:
            col_list.append(i)
        elif len(i.split("=")) == 2:
            t = i.split("=")
            if len(t[0].strip().split(".")) == 2:
                col_list.append(t[0].strip())
            if len(t[1].strip().split(".")) == 2:
                col_list.append(t[1].strip())
    return list({x.split(".")[0] for x in col_list if len(x.split(".")) == 2})


def apply_row_selection(df, spec: Optional[str]):
    """Slice ``df`` according to ``--rows``.
    ``'N'`` → first N; ``'START:END'`` → ``iloc[START:END]``.
    """
    if spec is None:
        return df
    if ":" in spec:
        a, b = spec.split(":", 1)
        start = int(a) if a.strip() else 0
        end = int(b) if b.strip() else len(df)
        return df.iloc[start:end]
    return df.iloc[: int(spec)]
