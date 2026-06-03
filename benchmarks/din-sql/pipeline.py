"""DIN-SQL per-question pipeline orchestration (4 stages).

Stages:
  1. Schema linking (LLM)
  2. Classification + decomposition (LLM)
  3. SQL generation, branching on label (EASY / NON-NESTED / NESTED)
  4. Self-correction (LLM only; no execution between stages 3 and 4)

Top-level entry is :func:`run`.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_BENCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BENCH_DIR not in sys.path:
    sys.path.insert(0, _BENCH_DIR)

from langchain.chains import LLMChain  # noqa: E402

from _common import llm as _llm  # noqa: E402
from _common.adhoc_view import (  # noqa: E402
    create_adhoc_view,
    find_fk_conditions_for_view_adhoc,
)
from _common.clusters import find_all_clusters_for_tables  # noqa: E402
from _common.datasets import DATASET_TABLES  # noqa: E402
from _common.embeddings import (  # noqa: E402
    ensure_bge_model,
    prepare_reference_embeddings,
    topk_embedding_cosine_sim,
)
from _common.history import build_clusters_from_history  # noqa: E402
from _common.llm import (  # noqa: E402
    chat_with_chatgpt,
    chat_with_gemini,
    ensure_gemini,
    ensure_openai,
)
from _common.logging_utils import append_log  # noqa: E402
from _common.parsers import (  # noqa: E402
    apply_row_selection,
    extract_json_block,
    parse_retrieved_tables_from_links,
)
from _common.rename_mapping import (  # noqa: E402
    build_renamed_fk_block,
    load_rename_mapping,
)
from _common.schema import (  # noqa: E402
    generate_schema_prompt,
    get_database_schema,
    get_database_schema_manual,
    list_tables_and_views,
)
from _common.views import find_matching_views, parse_view_base_tables  # noqa: E402

from . import prompts as _prompts  # noqa: E402
from .config import (  # noqa: E402
    apply_sample_auto_mapping,
    default_cluster_filter,
    lookup_module_list,
    parse_args,
    resolve_mapping_path,
    resolve_paths,
    resolve_rename_v_suffix,
    resolve_view_v_suffix,
    validate_args,
)


log = logging.getLogger(__name__)

TOP_K = 3
ATTEMPTS_PER_QUESTION = 3


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

@dataclass
class PipelineState:
    args: argparse.Namespace
    db_path: str
    is_gemini: bool

    ds_org_tables: List[str]
    ds_db_dict: Dict[str, List[str]]
    base_tables: List[str]
    extra_views_pool: List[str]
    base_schema: str

    mapping_path: Optional[str]
    org_keyed: bool
    rename_v_suffix: Optional[str]

    hist_sql_col: str
    hist_view_sql_col: str
    hist_gt_tables_col: str

    sample: Optional[pd.DataFrame] = None
    exact_clusters: Optional[list] = None
    question_cluster_map: Optional[list] = None
    ref_texts: Optional[list] = None
    ref_embs: Optional[Any] = None

    db_tables_active: Dict[str, List[str]] = field(default_factory=dict)
    per_db_cache: Dict[str, Tuple] = field(default_factory=dict)
    per_db_warned: set = field(default_factory=set)

    log_dir: str = ""
    suffix: str = ""
    linking_col: str = ""
    label_col: str = ""
    subq_col: str = ""
    sql_col_out: str = ""
    revised_sql_col_out: str = ""

    # Pre-built LangChain prompt templates (depend on flags, fixed across questions).
    schema_linking_prompt: Any = None
    classification_prompt: Any = None
    easy_prompt: Any = None
    non_nested_prompt: Any = None
    nested_prompt: Any = None
    correction_prompt: Any = None

    failed_idx: List[int] = field(default_factory=list)


def _build_base_schema_rename_aware(
    db_path: str,
    base_tables: List[str],
    *,
    rename: bool,
) -> str:
    """Build base schema. With ``rename``, use ``get_database_schema`` (with a
    manual sqlite fallback for views with DATE-as-int columns). Without rename,
    use ``generate_schema_prompt``.
    """
    print(f"📚 Building base schema from {len(base_tables)} tables...")
    present = {n.lower() for n in list_tables_and_views(db_path)}
    missing = [t for t in base_tables if t.lower() not in present]
    if missing:
        print(f"⚠️  {len(missing)}/{len(base_tables)} base tables NOT found in {db_path}: {missing}")

    if rename:
        pieces = []
        rescued = []
        for t in base_tables:
            try:
                pieces.append(get_database_schema(db_path, [t], sample_rows=3, include_views=True))
            except TypeError:
                pieces.append(get_database_schema_manual(db_path, [t], sample_rows=3))
                rescued.append(t)
        if rescued:
            print(
                f"⚠️  {len(rescued)} rename views fell back to get_database_schema_manual "
                f"(date-coercion): {rescued}"
            )
        return "\n\n".join(pieces) + "\n\n"

    pieces = []
    for i, t in enumerate(base_tables):
        print(f"  [{i+1}/{len(base_tables)}] {t}", end="\r")
        pieces.append(generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=t))
    print()
    return "\n\n".join(pieces) + "\n\n"


def _history_column_names(rename: bool, rename_v_suffix: Optional[str]) -> Tuple[str, str, str]:
    if rename:
        tail = f"_{rename_v_suffix}" if rename_v_suffix else ""
        return f"renamed_SQL{tail}", f"renamed_view_SQL{tail}", f"gt_renamed_tables{tail}"
    return "SQL", "view_SQL", "gt_tables"


def _build_suffix(args: argparse.Namespace, is_gemini: bool,
                  rename_v_suffix: Optional[str], view_v_suffix: Optional[str]) -> str:
    suffix = ""
    if args.rename:
        suffix += "_rename"
    if args.view:
        suffix += "_withview"
    if args.cluster:
        suffix += "_clusterfilter" if args.cluster_filter else "_cluster"
    if args.history_path:
        suffix += f"_history{args.sample}" if args.sample < 100 else "_history"
    if args.use_linking:
        if args.view_adhoc:
            suffix += "_adhoclinking"
        elif args.view_relink:
            suffix += "_relinking"
        else:
            suffix += "_uselinking"
    if args.per_db:
        suffix += "_perdb_top3" if args.history_path else "_perdb"
    if not args.history_path:
        level = rename_v_suffix or view_v_suffix
        if level:
            suffix += f"_{level}"
    model_digits = "".join(re.findall(r"\d", args.model))
    if is_gemini:
        suffix += f"_gem{model_digits}"
    elif args.model != "gpt-4.1-mini":
        suffix += f"_gpt{model_digits}"
    return suffix


def setup(args: argparse.Namespace, df: pd.DataFrame) -> PipelineState:
    """Build the one-time pipeline state from ``args`` (already resolved/validated)."""
    is_gemini = args.model.startswith("gemini")
    if is_gemini:
        ensure_gemini()
    else:
        ensure_openai(chat_max_tokens=10000)

    ds = DATASET_TABLES[args.dataset]
    ds_org_tables = ds["org_tables"]
    ds_db_dict = ds["db_dict"]
    base_tables = ds["renamed_tables"] if args.rename else ds["org_tables"]
    extra_views_pool = ds["renamed_views"] if args.rename else ds["org_views"]

    rename_v_suffix = resolve_rename_v_suffix(args.rename_v)
    view_v_suffix = resolve_view_v_suffix(args.view_v)

    if args.rename and args.rename_v:
        custom = lookup_module_list(args.rename_v, "--rename_v")
        print(f"📝 --rename_v: overriding renamed_tables with {args.rename_v!r} ({len(custom)} tables)")
        base_tables = custom

        if rename_v_suffix is not None or args.rename_v.endswith("_tables"):
            views_var = args.rename_v.replace("_renamed_tables", "_renamed_views")
            try:
                custom_views = lookup_module_list(views_var, f"derived views pool {views_var!r}")
                print(f"📝 --rename_v: using views pool {views_var!r} ({len(custom_views)} views)")
                extra_views_pool = custom_views
            except SystemExit:
                print(f"⚠️  --rename_v: no views list {views_var!r} defined — views pool is empty")
                extra_views_pool = []
        else:
            print(
                f"⚠️  --rename_v {args.rename_v!r} does not match "
                f"'{{dataset}}_renamed_tables[_<suffix>]' — views pool falls back to dataset default."
            )

    if args.view_v:
        custom_views = lookup_module_list(args.view_v, "--view_v")
        print(f"📝 --view_v: overriding views pool with {args.view_v!r} ({len(custom_views)} views)")
        extra_views_pool = custom_views

    if args.per_db:
        if not ds_db_dict:
            raise SystemExit(
                f"--per_db requires DATASET_TABLES['{args.dataset}']['db_dict'] to be populated."
            )
        if "db_id" not in df.columns:
            raise SystemExit("--per_db requires a 'db_id' column in the input CSV.")

    org_keyed = (args.dataset == "bird")
    mapping_path = resolve_mapping_path(args, "dinsql") if args.rename else None
    if args.rename and mapping_path and not os.path.exists(mapping_path):
        raise SystemExit(
            f"--rename needs a mapping file but {mapping_path} does not exist. "
            f"Pass --mapping_path explicitly."
        )

    base_schema = _build_base_schema_rename_aware(
        args.db_path, list(base_tables), rename=args.rename
    )

    if args.rename and mapping_path:
        fk_block = build_renamed_fk_block(
            args.db_path, list(ds_org_tables), mapping_path, org_keyed_columns=org_keyed
        )
        if fk_block:
            base_schema += fk_block
            print(f"🔗 Injected {fk_block.count(chr(10)) - 2} renamed FK lines into base_schema")
        else:
            print("⚠️  No FKs translated to renamed namespace — base_schema unchanged.")

    hist_sql_col, hist_view_sql_col, hist_gt_tables_col = _history_column_names(
        args.rename, rename_v_suffix
    )

    state = PipelineState(
        args=args,
        db_path=args.db_path,
        is_gemini=is_gemini,
        ds_org_tables=list(ds_org_tables),
        ds_db_dict=dict(ds_db_dict),
        base_tables=list(base_tables),
        extra_views_pool=list(extra_views_pool),
        base_schema=base_schema,
        mapping_path=mapping_path,
        org_keyed=org_keyed,
        rename_v_suffix=rename_v_suffix,
        hist_sql_col=hist_sql_col,
        hist_view_sql_col=hist_view_sql_col,
        hist_gt_tables_col=hist_gt_tables_col,
    )

    if args.history_path:
        sample, exact_clusters, question_cluster_map = build_clusters_from_history(
            args.history_path,
            sql_col=hist_sql_col,
            gt_tables_col=hist_gt_tables_col,
            sample_pct=args.sample,
        )
        print("🧠 Loading BGE encoder and building reference embeddings from history...")
        ensure_bge_model()
        ref_texts, ref_embs = prepare_reference_embeddings(list(sample["question"]))
        state.sample = sample
        state.exact_clusters = exact_clusters
        state.question_cluster_map = question_cluster_map
        state.ref_texts = ref_texts
        state.ref_embs = ref_embs

    if args.per_db:
        if args.rename:
            table_to_view, _ = load_rename_mapping(mapping_path, org_keyed_columns=org_keyed)
            for db_id, tables in state.ds_db_dict.items():
                mapped = []
                for t in tables:
                    rn = table_to_view.get(t.lower())
                    if rn:
                        mapped.append(rn)
                    else:
                        print(
                            f"⚠️  --per_db --rename: db_id={db_id!r} table {t!r} "
                            f"has no rename mapping, skipping"
                        )
                state.db_tables_active[db_id] = mapped
        else:
            state.db_tables_active = {k: list(v) for k, v in state.ds_db_dict.items()}
        print(f"📦 --per_db active with {len(state.db_tables_active)} db_ids")

    suffix = _build_suffix(args, is_gemini, rename_v_suffix, view_v_suffix)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    log_base = f"logs_din_{args.dataset}" if args.dataset != "spider" else "logs_din"
    log_dir = os.path.join(log_base, f"run_{run_id}{suffix}")
    os.makedirs(log_dir, exist_ok=True)
    print(f"📂 Logging prompts to: {log_dir}")

    state.suffix = suffix
    state.log_dir = log_dir
    state.linking_col = f"dinsql_linking{suffix}"
    state.label_col = f"dinsql_label{suffix}"
    state.subq_col = f"dinsql_sub_questions{suffix}"
    state.sql_col_out = f"dinsql_sql{suffix}"
    state.revised_sql_col_out = f"dinsql_revised_sql{suffix}"

    state.schema_linking_prompt = _prompts.make_schema_linking_prompt()
    state.classification_prompt = _prompts.make_classification_prompt()
    state.easy_prompt = _prompts.make_easy_prompt()
    state.non_nested_prompt = _prompts.make_non_nested_prompt(use_view=args.view)
    state.nested_prompt = _prompts.make_nested_prompt(use_view=args.view)
    state.correction_prompt = _prompts.make_self_correction_prompt()

    return state


def _resolve_per_db(state: PipelineState, db_id: Optional[str]):
    args = state.args
    if not args.per_db or db_id is None or db_id not in state.db_tables_active:
        if (args.per_db and db_id is not None
                and db_id not in state.db_tables_active
                and db_id not in state.per_db_warned):
            print(
                f"⚠️  --per_db: db_id={db_id!r} not in db_dict, "
                f"falling back to full union for this question"
            )
            state.per_db_warned.add(db_id)
        return (state.base_schema, state.extra_views_pool, state.exact_clusters,
                state.sample, state.ref_texts, state.ref_embs)

    if db_id in state.per_db_cache:
        return state.per_db_cache[db_id]

    db_tables = state.db_tables_active[db_id]
    db_tables_lower = {t.lower() for t in db_tables}
    print(f"🔧 --per_db: building resources for db_id={db_id!r} ({len(db_tables)} tables)")

    pieces = []
    rescued = []
    for t in db_tables:
        if args.rename:
            try:
                pieces.append(get_database_schema(state.db_path, [t], sample_rows=3, include_views=True))
            except TypeError:
                pieces.append(get_database_schema_manual(state.db_path, [t], sample_rows=3))
                rescued.append(t)
        else:
            try:
                pieces.append(generate_schema_prompt(
                    db_path=state.db_path, num_rows=3, no_join=False, target_table=t
                ))
            except Exception as _e:
                log.warning("generate_schema_prompt failed for %r: %s", t, _e)
    bs = "\n\n".join(p for p in pieces if p) + "\n\n"

    if args.rename and state.mapping_path:
        fk = build_renamed_fk_block(
            state.db_path, state.ds_db_dict[db_id], state.mapping_path,
            org_keyed_columns=state.org_keyed,
        )
        if fk:
            bs += fk

    vp = []
    if state.extra_views_pool:
        for v in state.extra_views_pool:
            bases = parse_view_base_tables(v)
            if bases and all(b.lower() in db_tables_lower for b in bases):
                vp.append(v)

    ec = None
    if state.exact_clusters is not None:
        ec = [c for c in state.exact_clusters
              if all(t.lower() in db_tables_lower for t in c["tables"])]

    sp = None
    rt = None
    re_ = None
    if state.sample is not None and "db_id" in state.sample.columns:
        sp = state.sample[state.sample["db_id"] == db_id].reset_index(drop=True)
        if len(sp) > 0:
            rt, re_ = prepare_reference_embeddings(list(sp["question"]))

    state.per_db_cache[db_id] = (bs, vp, ec, sp, rt, re_)
    return state.per_db_cache[db_id]


# ---------------------------------------------------------------------------
# Stage helpers (stage 0/1 mirror basesql; stage 2/3/4 are DIN-SQL-specific)
# ---------------------------------------------------------------------------

def _run_stage0_adhoc_view(
    state: PipelineState, index: int, row,
    stage0_tables: List[str], adhoc_view_cache: Dict,
) -> Tuple[Optional[str], Optional[str], bool]:
    args = state.args
    if len(stage0_tables) < 2:
        print(f"[adhoc view] q{int(index):04d}: ⚠️  only {len(stage0_tables)} "
              f"linked table(s) → SKIPPING stage 1, reusing --use_linking value")
        append_log(state.log_dir, index,
                   "STAGE 0: <2 linked tables — stage-1 SKIPPED, reusing --use_linking value",
                   f"tables={stage0_tables}")
        return None, None, True

    cache_key = frozenset(t.lower() for t in stage0_tables)
    if cache_key in adhoc_view_cache:
        name, schema_str = adhoc_view_cache[cache_key]
        print(f"[adhoc view] q{int(index):04d}: 🎯 cache HIT → {name!r}")
        append_log(state.log_dir, index,
                   f"STAGE 0: adhoc view cache HIT ({name})", schema_str or "")
        return name, schema_str, False

    print(f"[adhoc view] q{int(index):04d}: cache MISS → discovering FKs")
    fk_conds = find_fk_conditions_for_view_adhoc(
        state.db_path, stage0_tables,
        rename_mode=args.rename, mapping_path=state.mapping_path,
        ds_org_tables=state.ds_org_tables, org_keyed=state.org_keyed,
    )
    if not fk_conds:
        print(f"[adhoc view] q{int(index):04d}: ⚠️  no FKs among "
              f"{stage0_tables} → fall back to base schema")
        append_log(state.log_dir, index,
                   "STAGE 0: no FK conditions found — stage-1 uses base schema",
                   f"tables={stage0_tables}")
        return None, None, False

    excluded = list(DATASET_TABLES[args.dataset].get("org_views", [])) + list(
        DATASET_TABLES[args.dataset].get("renamed_views", [])
    )
    name, schema_str = create_adhoc_view(
        state.db_path, stage0_tables, fk_conds,
        model=args.model, is_gemini=state.is_gemini, excluded_views=excluded,
    )
    if name:
        adhoc_view_cache[cache_key] = (name, schema_str)
        append_log(state.log_dir, index,
                   f"STAGE 0: adhoc view created ({name})", schema_str)
    else:
        append_log(state.log_dir, index,
                   "STAGE 0: adhoc view FAILED (LLM) — stage-1 uses base schema",
                   f"tables={stage0_tables}\nfk_conditions={fk_conds}")
    return name, schema_str, False


def _run_stage0_relink(
    state: PipelineState, index: int, row,
    stage0_tables: List[str], q_views_pool: List[str],
) -> Tuple[Optional[str], bool]:
    if len(stage0_tables) < 2:
        print(f"[relink] q{int(index):04d}: ⚠️  only {len(stage0_tables)} "
              f"linked table(s) → SKIPPING stage 1, reusing --use_linking value")
        append_log(state.log_dir, index,
                   "STAGE 0: <2 linked tables — stage-1 SKIPPED, reusing --use_linking value",
                   f"tables={stage0_tables}")
        return None, True

    matched = find_matching_views(q_views_pool, stage0_tables) if q_views_pool else []
    if not matched:
        print(f"[relink] q{int(index):04d}: no views matched stage-0 tables "
              f"→ SKIPPING stage 1, reusing --use_linking value")
        append_log(state.log_dir, index,
                   "STAGE 0: relink — no matching views — stage-1 SKIPPED, "
                   "reusing --use_linking value", f"tables={stage0_tables}")
        return None, True

    schema_str = "\n\n".join(
        generate_schema_prompt(db_path=state.db_path, num_rows=3, no_join=False, target_table=v)
        for v in matched
    )
    print(f"[relink] q{int(index):04d}: matched {len(matched)} view(s) "
          f"from stage-0 tables → {matched}")
    append_log(state.log_dir, index,
               f"STAGE 0: relink matched {len(matched)} view(s)",
               f"views={matched}")
    return schema_str, False


def _parse_stage0_tables(stage0_value, base_tables: List[str]) -> List[str]:
    try:
        tables_lower = set(parse_retrieved_tables_from_links(stage0_value))
    except Exception:
        tables_lower = set()
    bt_lookup = {t.lower(): t for t in base_tables}
    return [bt_lookup[t] for t in tables_lower if t in bt_lookup]


def _run_stage1_linking(
    state: PipelineState, index: int, row, stage1_input_schema: str,
) -> str:
    args = state.args
    chat_prompt = state.schema_linking_prompt
    prompt_text = chat_prompt.format(question=row[state.args.question_col], schema=stage1_input_schema)
    try:
        if state.is_gemini:
            append_log(state.log_dir, index, "STAGE 1 PROMPT: schema linking (gemini)", prompt_text)
            response = chat_with_gemini(
                prompt_text, model=args.model, response_fields={"schema_links": list}
            )
        else:
            append_log(state.log_dir, index, "STAGE 1 PROMPT: schema linking", prompt_text)
            chain = LLMChain(llm=_llm.get_chat(), prompt=chat_prompt)
            response = chain.run(question=row[state.args.question_col], schema=stage1_input_schema)
        append_log(state.log_dir, index, "STAGE 1 RESPONSE", response)
        cleaned = re.sub(r"//.*", "", response.replace("```json", "").replace("```", ""))
        try:
            schema_links = ast.literal_eval(cleaned)["schema_links"]
        except (SyntaxError, ValueError):
            fixed = re.sub(r"([\[,]\s*)(`[^`]+`(?:\.`[^`]+`)*)", r'\1"\2"', cleaned)
            schema_links = ast.literal_eval(fixed)["schema_links"]
        return str(schema_links)
    except Exception as err:
        if args.use_linking:
            schema_links = row[args.use_linking]
            print(f"[stage 1] q{int(index):04d}: fresh linking FAILED "
                  f"({type(err).__name__}: {err}) — falling back to --use_linking column")
            append_log(state.log_dir, index,
                       "STAGE 1 FAILED — falling back to --use_linking",
                       f"error={type(err).__name__}: {err}\n"
                       f"fallback column={args.use_linking}\nvalue={schema_links}")
            return str(schema_links)
        raise


def _build_updated_schema(
    state: PipelineState,
    *,
    stage1_input_schema: str,
    q_base_schema: str,
    q_views_pool: List[str],
    adhoc_view_schema_str: Optional[str],
    relink_matched_views_schema: Optional[str],
    retrieved_tables: List[str],
    cluster_res: Optional[dict],
    stage0_tables: List[str],
) -> Tuple[str, bool, Optional[set]]:
    args = state.args
    apply_cluster_filter = False
    effective_base = None
    cluster_set_lc = None
    if args.cluster_filter and cluster_res is not None and cluster_res.get("tables"):
        bt_lookup = {t.lower(): t for t in state.base_tables}
        cluster_tables_oc = [bt_lookup.get(t.lower(), t) for t in cluster_res["tables"]]
        cluster_set_lc = {t.lower() for t in cluster_tables_oc}

        effective_base = "\n\n".join(
            generate_schema_prompt(db_path=state.db_path, num_rows=3, no_join=False, target_table=t)
            for t in cluster_tables_oc
        ) + "\n\n"

        fk_lines = find_fk_conditions_for_view_adhoc(
            state.db_path, cluster_tables_oc,
            rename_mode=args.rename, mapping_path=state.mapping_path,
            ds_org_tables=state.ds_org_tables, org_keyed=state.org_keyed,
        )
        if fk_lines:
            effective_base += (
                "Foreign Keys:\n"
                + "\n".join(fk.replace("=", " = ") for fk in fk_lines)
                + "\n\n"
            )
        apply_cluster_filter = True

    if args.view_adhoc:
        if apply_cluster_filter:
            updated = effective_base
            if (adhoc_view_schema_str and stage0_tables
                    and all(t.lower() in cluster_set_lc for t in stage0_tables)):
                updated += adhoc_view_schema_str + "\n\n"
        else:
            updated = stage1_input_schema
    elif args.view_relink:
        if apply_cluster_filter:
            updated = effective_base
            if args.view and q_views_pool and retrieved_tables:
                matched = find_matching_views(q_views_pool, retrieved_tables)
                matched = [
                    v for v in matched
                    if all(b.lower() in cluster_set_lc for b in parse_view_base_tables(v))
                ]
                if matched:
                    updated += "\n\n" + "\n\n".join(
                        generate_schema_prompt(
                            db_path=state.db_path, num_rows=3, no_join=False, target_table=v
                        )
                        for v in matched
                    ) + "\n\n"
        else:
            updated = stage1_input_schema
    else:
        updated = effective_base if apply_cluster_filter else q_base_schema
        if args.view and q_views_pool and retrieved_tables:
            matched = find_matching_views(q_views_pool, retrieved_tables)
            if apply_cluster_filter:
                matched = [
                    v for v in matched
                    if all(b.lower() in cluster_set_lc for b in parse_view_base_tables(v))
                ]
            if matched:
                updated += "\n\n" + "\n\n".join(
                    generate_schema_prompt(
                        db_path=state.db_path, num_rows=3, no_join=False, target_table=v
                    )
                    for v in matched
                ) + "\n\n"

    return updated, apply_cluster_filter, cluster_set_lc


def _topk_history_sqls(
    state: PipelineState, index: int, row,
    q_sample, q_ref_texts, q_ref_embs,
    cluster_res: Optional[dict],
) -> str:
    args = state.args
    if not (args.history_path and q_ref_texts is not None and q_sample is not None and len(q_sample) > 0):
        return ""

    if args.cluster and cluster_res is not None and cluster_res.get("indices"):
        cand_indices = cluster_res["indices"]
        src_df = q_sample if q_sample is not None else state.sample
        valid = [i for i in cand_indices if i in src_df.index]
        if valid:
            cand_questions = src_df.loc[valid, "question"].astype(str).to_list()
            local_refs, local_embs = prepare_reference_embeddings(cand_questions, indices=valid)
            top_results = topk_embedding_cosine_sim(
                row[state.args.question_col], local_refs, local_embs, top_k=TOP_K
            )
        else:
            top_results = []
        if len(top_results) < TOP_K:
            already = {r[0] for r in top_results}
            extras_needed = TOP_K - len(top_results)
            backup = topk_embedding_cosine_sim(
                row[state.args.question_col], q_ref_texts, q_ref_embs, top_k=TOP_K + len(already)
            )
            extras = [r for r in backup if r[0] not in already][:extras_needed]
            top_results = list(top_results) + extras
    else:
        top_results = topk_embedding_cosine_sim(
            row[state.args.question_col], q_ref_texts, q_ref_embs, top_k=TOP_K
        )

    top_indices = [x[0] for x in top_results]
    top_sqls = " \n".join(
        q_sample.loc[top_indices, state.hist_sql_col].astype(str).to_list()
    )
    if args.view:
        top_sqls += " \n" + " \n".join(
            q_sample.loc[top_indices, state.hist_view_sql_col].astype(str).to_list()
        )
    return top_sqls


def _run_stage2_classification(
    state: PipelineState, index: int, row,
    updated_schema: str, schema_links: str,
    history_block: str, paths_block: str,
) -> Tuple[str, list]:
    """Stage 2: classify the query as EASY/NON-NESTED/NESTED and extract sub-questions."""
    args = state.args
    prompt_text = state.classification_prompt.format(
        question=row[state.args.question_col],
        schema=updated_schema,
        schema_links=schema_links,
        history_block=history_block,
        paths_block=paths_block,
    )
    append_log(state.log_dir, index, "STAGE 2 PROMPT: classification", prompt_text)
    if state.is_gemini:
        response = chat_with_gemini(prompt_text, model=args.model)
    else:
        response = chat_with_chatgpt(prompt_text, model=args.model)
    append_log(state.log_dir, index, "STAGE 2 RESPONSE", response)
    class_json = json.loads(extract_json_block(response))
    label = class_json.get("Label", "NON-NESTED")
    sub_questions = class_json.get("sub-questions", [])
    return label, sub_questions


def _run_stage3_generation(
    state: PipelineState, index: int, row,
    updated_schema: str, schema_links: str, label: str, sub_questions: list,
    history_block: str, paths_block: str,
) -> str:
    """Stage 3: branch on ``label`` and generate SQL."""
    args = state.args
    if "EASY" in label:
        template = state.easy_prompt
        kwargs = dict(
            question=row[state.args.question_col], schema=updated_schema, schema_links=schema_links,
            history_block=history_block, paths_block=paths_block,
        )
    elif "NON-NESTED" in label:
        template = state.non_nested_prompt
        kwargs = dict(
            question=row[state.args.question_col], schema=updated_schema, schema_links=schema_links,
            history_block=history_block, paths_block=paths_block,
        )
    else:
        template = state.nested_prompt
        kwargs = dict(
            question=row[state.args.question_col], schema=updated_schema, schema_links=schema_links,
            sub_questions=sub_questions, history_block=history_block, paths_block=paths_block,
        )
    prompt_text = template.format(**kwargs)
    append_log(state.log_dir, index, f"STAGE 3 PROMPT: SQL generation ({label})", prompt_text)
    if state.is_gemini:
        response = chat_with_gemini(prompt_text, model=args.model, response_fields={"SQL": str})
        sql_query = json.loads(response)["SQL"]
    else:
        response = chat_with_chatgpt(prompt_text, model=args.model)
        sql_query = json.loads(extract_json_block(response))["SQL"].replace("```sql", "").replace("```", "")
    append_log(state.log_dir, index, "STAGE 3 RESPONSE", response)
    return sql_query


def _run_stage4_correction(
    state: PipelineState, index: int, row,
    updated_schema: str, sql_query: str,
    history_block: str, paths_block: str,
) -> str:
    """Stage 4: self-correction. Returns the revised SQL (or original on parse failure)."""
    args = state.args
    prompt_text = state.correction_prompt.format(
        question=row[state.args.question_col], schema=updated_schema, sql_query=sql_query,
        history_block=history_block, paths_block=paths_block,
    )
    append_log(state.log_dir, index, "STAGE 4 PROMPT: self-correction", prompt_text)
    if state.is_gemini:
        response = chat_with_gemini(
            prompt_text, model=args.model, response_fields={"Revised_SQL": str}
        )
    else:
        response = chat_with_chatgpt(prompt_text, model=args.model)
    append_log(state.log_dir, index, "STAGE 4 RESPONSE", response)
    try:
        if state.is_gemini:
            revised_sql = json.loads(response)["Revised_SQL"]
        else:
            revised_sql = json.loads(extract_json_block(response))["Revised_SQL"].replace("```sql", "").replace("```", "")
    except Exception as e:
        log.error("idx %s: error parsing correction response: %s", index, e)
        revised_sql = sql_query
    return revised_sql


def run_question(
    state: PipelineState, df: pd.DataFrame, index, row,
    adhoc_view_cache: Dict,
) -> None:
    """Run the full 4-stage pipeline for a single question (with retries)."""
    args = state.args
    log_file = os.path.join(state.log_dir, f"q{int(index):04d}.log")
    q_base_schema, q_views_pool, q_clusters, q_sample, q_ref_texts, q_ref_embs = (
        _resolve_per_db(state, row.get("db_id") if "db_id" in df.columns else None)
    )

    for attempt in range(ATTEMPTS_PER_QUESTION):
        try:
            open(log_file, "w", encoding="utf-8").close()
            question = row[state.args.question_col]
            append_log(state.log_dir, index, "QUESTION", str(question))

            # ---- Stage 0 ----
            adhoc_view_name = None
            adhoc_view_schema_str = None
            adhoc_skip_stage1 = False
            relink_matched_views_schema = None
            relink_skip_stage1 = False
            stage0_tables: List[str] = []

            if args.view_adhoc or args.view_relink:
                stage0_value = row[args.use_linking]
                mode_label = "adhoc view" if args.view_adhoc else "relink"
                append_log(state.log_dir, index,
                           f"STAGE 0: {mode_label} seed (from --use_linking)",
                           f"column={args.use_linking}\nvalue={stage0_value}")
                stage0_tables = _parse_stage0_tables(stage0_value, state.base_tables)
                print(f"[{mode_label}] q{int(index):04d}: stage-0 linked tables "
                      f"({len(stage0_tables)}): {stage0_tables}")

            if args.view_adhoc:
                adhoc_view_name, adhoc_view_schema_str, adhoc_skip_stage1 = (
                    _run_stage0_adhoc_view(state, index, row, stage0_tables, adhoc_view_cache)
                )
            if args.view_relink:
                relink_matched_views_schema, relink_skip_stage1 = (
                    _run_stage0_relink(state, index, row, stage0_tables, q_views_pool)
                )

            stage1_input_schema = q_base_schema
            if args.view_adhoc and adhoc_view_schema_str:
                stage1_input_schema = q_base_schema + "\n\n" + adhoc_view_schema_str + "\n\n"
            elif args.view_relink and relink_matched_views_schema:
                stage1_input_schema = q_base_schema + "\n\n" + relink_matched_views_schema + "\n\n"

            # ---- Stage 1 ----
            skip_stage1 = args.use_linking and (
                (not args.view_adhoc and not args.view_relink)
                or adhoc_skip_stage1
                or relink_skip_stage1
            )
            if skip_stage1:
                schema_links = row[args.use_linking]
                if args.view_adhoc:
                    reason = "<2 linked tables under --view_adhoc"
                elif args.view_relink:
                    reason = ("no view to justify re-linking under --view_relink "
                              "(<2 tables or no matching views)")
                else:
                    reason = "read from column"
                append_log(state.log_dir, index, f"STAGE 1: linking (skipped — {reason})",
                           f"column={args.use_linking}\nvalue={schema_links}")
            else:
                schema_links = _run_stage1_linking(state, index, row, stage1_input_schema)
            df.at[index, state.linking_col] = str(schema_links)

            # ---- Parse links → retrieved_tables ----
            retrieved_tables: List[str] = []
            if args.view or args.cluster:
                try:
                    retrieved_tables = parse_retrieved_tables_from_links(schema_links)
                except Exception as e:
                    log.warning("idx %s: failed to parse schema_links: %s", index, e)

            # ---- Cluster lookup + updated_schema ----
            cluster_res = None
            if args.cluster and q_clusters is not None and retrieved_tables:
                cluster_res = find_all_clusters_for_tables(
                    retrieved_tables, q_clusters, sqlite_path=state.db_path
                )

            updated_schema, apply_cluster_filter, cluster_set_lc = _build_updated_schema(
                state,
                stage1_input_schema=stage1_input_schema,
                q_base_schema=q_base_schema,
                q_views_pool=q_views_pool,
                adhoc_view_schema_str=adhoc_view_schema_str,
                relink_matched_views_schema=relink_matched_views_schema,
                retrieved_tables=retrieved_tables,
                cluster_res=cluster_res,
                stage0_tables=stage0_tables,
            )
            if apply_cluster_filter and cluster_res is not None and cluster_res.get("tables"):
                bt_lookup = {t.lower(): t for t in state.base_tables}
                cluster_tables_oc = [bt_lookup.get(t.lower(), t) for t in cluster_res["tables"]]
                fk_lines = find_fk_conditions_for_view_adhoc(
                    state.db_path, cluster_tables_oc,
                    rename_mode=args.rename, mapping_path=state.mapping_path,
                    ds_org_tables=state.ds_org_tables, org_keyed=state.org_keyed,
                )
                append_log(state.log_dir, index,
                           "CLUSTER FILTER: restricted schema to cluster tables",
                           f"tables ({len(cluster_tables_oc)}): {cluster_tables_oc}\n"
                           f"fks ({len(fk_lines)}): {fk_lines}")
            elif args.cluster_filter:
                append_log(state.log_dir, index,
                           "CLUSTER FILTER: no matched clusters — falling back to full schema", "")

            # ---- History + cluster paths ----
            top_sqls = _topk_history_sqls(
                state, index, row, q_sample, q_ref_texts, q_ref_embs, cluster_res
            )
            paths_str = ""
            if args.cluster and cluster_res is not None:
                paths_str = ", \n".join(sorted(set(cluster_res.get("paths", []))))
            history_block = f"History SQLs:\n{top_sqls}\n\n" if top_sqls else ""
            paths_block = f"Common Join Paths:\n{paths_str}\n\n" if paths_str else ""

            # ---- Stage 2 ----
            label, sub_questions = _run_stage2_classification(
                state, index, row, updated_schema, schema_links, history_block, paths_block
            )
            df.at[index, state.label_col] = str(label)
            df.at[index, state.subq_col] = str(sub_questions)
            print(f"[{index}] label={label}")

            # ---- Stage 3 ----
            sql_query = _run_stage3_generation(
                state, index, row, updated_schema, schema_links, label, sub_questions,
                history_block, paths_block,
            )
            df.at[index, state.sql_col_out] = sql_query
            print(f"[{index}] sql: {sql_query}")

            # ---- Stage 4 ----
            revised_sql = _run_stage4_correction(
                state, index, row, updated_schema, sql_query, history_block, paths_block,
            )
            one_liner = (revised_sql or sql_query or "SELECT * FROM table").replace("\n", " ").replace("\r", " ")
            df.at[index, state.revised_sql_col_out] = one_liner
            append_log(state.log_dir, index, "FINAL revised_sql", one_liner)
            print(f"[{index}] revised: {one_liner}")
            return

        except Exception as e:
            print(f"Attempt {attempt + 1} failed for index {index}: {e}")
            if attempt < ATTEMPTS_PER_QUESTION - 1:
                time.sleep(1 * (attempt + 1))
            else:
                state.failed_idx.append(index)
                print(f"❌ Giving up after {ATTEMPTS_PER_QUESTION} attempts on index {index}")


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

def run(argv: Optional[list] = None) -> None:
    """Main entry point for the DIN-SQL CLI."""
    args = parse_args(argv)
    resolve_paths(args, pipeline_tag="dinsql")

    for label, path in (("--csv_path", args.csv_path), ("--db_path", args.db_path)):
        if not os.path.exists(path):
            raise SystemExit(f"{label} not found at {path}. Pass {label} explicitly.")

    validate_args(args)
    default_cluster_filter(args)
    apply_sample_auto_mapping(args)

    df = pd.read_csv(args.csv_path)
    df = apply_row_selection(df, args.rows)
    print(
        f"📄 Running on {len(df)} rows from {args.csv_path} "
        f"(dataset={args.dataset}, model={args.model})"
    )

    state = setup(args, df)
    adhoc_view_cache: Dict = {}

    for i, (index, row) in enumerate(df.iterrows()):
        run_question(state, df, index, row, adhoc_view_cache)
        if (i + 1) % 100 == 0:
            inc_path = os.path.join(
                state.log_dir,
                f"{os.path.splitext(os.path.basename(args.csv_path))[0]}{state.suffix}_dinsql_out.csv",
            )
            df.to_csv(inc_path, index=False)
            print(f"💾 Incremental save at row {index}")

    base_name = os.path.splitext(os.path.basename(args.csv_path))[0]
    out_path = os.path.join(state.log_dir, f"{base_name}{state.suffix}_dinsql_out.csv")
    df.to_csv(out_path, index=False)
    print(f"💾 Saved results to: {out_path}")
    print(f"Failed indices: {state.failed_idx}")
