"""Runtime helpers shared by the patched AutoLink scripts.

Four things AutoLink has no notion of, all needed to match LDD's configuration:

  1. History SQLs block      top-3 similar questions' gold SQL (+3 view SQL on +A)
  2. Common Join Paths block from the matched clusters (+P)
  3. Catalog masking         so an arm cannot discover objects it does not expose
  4. DeepSeek client         DEEPSEEK_API_KEY (Machine scope) + api.deepseek.com

Disjoint pools note
-------------------
nl2sql_<ds>.csv (eval) and sample_<ds>.csv (history) are DIFFERENT question sets
-- 0/767 row-aligned on bird, and not even the same set. So the history pool
never contains a tested question and no leave-one-out filtering is needed; this
matches basesql._topk_history_sqls exactly. ``row_index`` indexes the eval CSV,
which is a different space from the history CSV's index.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

# Vendored under <LDD>/benchmarks/, so the repo root is derived from this
# file's location rather than hardcoded -- the original absolute path only
# worked on the machine the experiments were run on.
LDD_BENCH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir))
if LDD_BENCH not in sys.path:
    sys.path.insert(0, LDD_BENCH)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ldd_config as C  # noqa: E402

TOP_K = 3
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 4. DeepSeek client
# ---------------------------------------------------------------------------
def deepseek_key() -> str:
    """DEEPSEEK_API_KEY, falling back to the Windows Machine scope.

    The key is set at Machine scope on this host, which python's os.environ does
    not see when launched from some shells.
    """
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','Machine')"],
            capture_output=True, text=True, timeout=30)
        k = (out.stdout or "").strip()
        if k:
            os.environ["DEEPSEEK_API_KEY"] = k
            return k
    except Exception:
        pass
    raise RuntimeError("DEEPSEEK_API_KEY not found (env or Machine scope)")


def deepseek_client():
    from openai import OpenAI
    return OpenAI(api_key=deepseek_key(), base_url="https://api.deepseek.com")


def reasoning_of(message) -> str:
    """DeepSeek-R1 exposes reasoning_content; other providers do not."""
    return getattr(message, "reasoning_content", None) or ""


# ---------------------------------------------------------------------------
# arm context, resolved from the log dir name so patched scripts stay thin
# ---------------------------------------------------------------------------
class ArmContext:
    """Everything the patched AutoLink scripts need, derived from --log_path."""

    _cache: Dict[str, "ArmContext"] = {}

    def __init__(self, log_path: str):
        self.log_path = log_path.rstrip("/\\")
        name = os.path.basename(self.log_path)          # log_bird<suffix>
        if not name.startswith("log_"):
            raise ValueError(f"unexpected log dir {name!r}")
        body = name[len("log_"):]
        self.dataset = "bird" if body.startswith("bird") else "spider"
        self.suffix = body[len(self.dataset):]           # e.g. _withview_cluster_history_opt1_ds

        self.rename = "_rename" in self.suffix
        self.view = "_withview" in self.suffix
        self.cluster = "_cluster" in self.suffix
        self.mode = "opt2" if "_opt2" in self.suffix else "opt1"
        self.db_name = f"merged_{self.dataset}{self.suffix}"
        self.questions_path = os.path.join(
            HERE, f"questions_{self.dataset}{self.suffix}.json")

        self.hist = C.HISTORY_COLS[(self.dataset, self.rename)]
        self._sample: Optional[pd.DataFrame] = None
        self._refs = None
        self._paths: Optional[dict] = None
        self._exposed: Optional[Tuple[Set[str], Set[str]]] = None

    @classmethod
    def get(cls, log_path: str) -> "ArmContext":
        key = os.path.abspath(log_path)
        with _LOCK:
            if key not in cls._cache:
                cls._cache[key] = cls(log_path)
            return cls._cache[key]

    # ---------------- questions ----------------
    def questions(self) -> dict:
        with open(self.questions_path, encoding="utf-8") as f:
            return json.load(f)

    # ---------------- 3. catalog masking ----------------
    def exposed(self) -> Tuple[Set[str], Set[str]]:
        if self._exposed is None:
            p = os.path.join(HERE, "exposed", f"{self.db_name}.json")
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            self._exposed = ({t.lower() for t in d["tables"]},
                             {v.lower() for v in d["views"]})
        return self._exposed

    def allowed(self) -> Set[str]:
        t, v = self.exposed()
        return t | v

    _CATALOG = re.compile(r"\bsqlite_(?:master|schema|temp_master)\b|"
                          r"\bpragma_table_list\b", re.I)
    _REF = re.compile(
        r"(?:\bFROM\s+|\bJOIN\s+|\bINTO\s+|\bUPDATE\s+|"
        r"pragma_table_info\s*\(\s*['\"]?|PRAGMA\s+table_info\s*\(\s*['\"]?)"
        r"[`\"\[]?([A-Za-z_]\w*)", re.I)
    _ALIAS = {f"t{i}" for i in range(1, 12)} | {"select"}

    def screen_sql(self, sql: str) -> Optional[str]:
        """Return an error string if the SQL reaches outside the arm's universe.

        Without this the base arm's agent can run
        ``SELECT name FROM sqlite_master`` against merged_<ds>.sqlite and
        discover all 596 views, silently turning it into a +A arm.
        """
        s = str(sql)
        if self._CATALOG.search(s):
            return ("[ERROR: catalog tables are not queryable. The complete list "
                    "of available tables is given in your input.]")
        allow = self.allowed()
        for mo in self._REF.finditer(s):
            name = mo.group(1)
            low = name.lower()
            if low in self._ALIAS or low in allow:
                continue
            return f"[ERROR: no such table: {name}]"
        return None

    # ---------------- 1. history block ----------------
    def _load_history(self):
        """Load the history CSV + reference embeddings exactly once.

        Double-checked locking: sql_generation runs num_candidates workers
        concurrently, and an unlocked ``if self._sample is None`` let all of them
        call ensure_bge_model() at the same time, which raced on the CUDA model
        and silently killed 2 of 3 candidates.
        """
        if self._sample is not None:
            return self._sample, self._refs
        with _LOCK:
            if self._sample is None:
                from _common.embeddings import (ensure_bge_model,
                                                prepare_reference_embeddings)
                sample = pd.read_csv(C.SAMPLE_CSV[self.dataset])
                ensure_bge_model()
                self._refs = prepare_reference_embeddings(
                    list(sample["question"].astype(str)))
                self._sample = sample          # publish last
        return self._sample, self._refs

    def history_block(self, row_index: int, question: str,
                      cluster_indices: Optional[Sequence[int]] = None) -> str:
        """``History SQLs:`` block -- 3 SQLs, or 6 when +A adds the view SQLs.

        Mirrors basesql._topk_history_sqls: when +P supplies cluster question
        indices, rank within them first and backfill globally if short of 3.
        No self-exclusion -- the eval and history pools are disjoint.
        """
        from _common.embeddings import (prepare_reference_embeddings,
                                        topk_embedding_cosine_sim)
        sample, refs = self._load_history()
        ref_texts, ref_embs = refs
        picked: List[int] = []

        if self.cluster and cluster_indices:
            valid = [i for i in cluster_indices if i in sample.index]
            if valid:
                qs = sample.loc[valid, "question"].astype(str).to_list()
                with _LOCK:
                    lr, le = prepare_reference_embeddings(qs, indices=valid)
                    res = topk_embedding_cosine_sim(question, lr, le, top_k=TOP_K)
                picked = [i for i, _t, _s in res][:TOP_K]

        if len(picked) < TOP_K:
            need = TOP_K - len(picked)
            with _LOCK:
                res = topk_embedding_cosine_sim(
                    question, ref_texts, ref_embs, top_k=TOP_K + len(picked) + 2)
            for i, _t, _s in res:
                if i in picked:
                    continue
                picked.append(i)
                if len(picked) >= TOP_K:
                    break
            picked = picked[:TOP_K]

        if not picked:
            return ""

        sql_col = self.hist["sql"]
        lines = sample.loc[picked, sql_col].astype(str).to_list()
        if self.view and self.hist["view_sql"]:
            lines += sample.loc[picked, self.hist["view_sql"]].astype(str).to_list()
        body = " \n".join(lines)
        return f"History SQLs:\n{body}\n"

    def cluster_indices(self, instance_id: str) -> List[int]:
        return list((self._join().get(instance_id) or {}).get("indices") or [])

    # ---------------- 2. join paths block ----------------
    def _join(self) -> dict:
        if self._paths is None:
            p = os.path.join(self.log_path, "join_paths.json")
            self._paths = json.load(open(p, encoding="utf-8")) \
                if os.path.exists(p) else {}
        return self._paths

    def paths_block(self, instance_id: str) -> str:
        if not self.cluster:
            return ""
        rec = self._join().get(instance_id)
        paths = rec.get("paths") if isinstance(rec, dict) else rec
        if not paths:
            return ""
        return "Common Join Paths:\n" + ", \n".join(paths) + "\n"

    def extra_blocks(self, instance_id: str, row_index: int,
                     question: str) -> str:
        """History + join paths, in LDD's block style, for the generation prompt."""
        out = []
        h = self.history_block(row_index, question,
                               self.cluster_indices(instance_id))
        if h:
            out.append(h)
        p = self.paths_block(instance_id)
        if p:
            out.append(p)
        return ("\n" + "\n".join(out) + "\n") if out else ""
