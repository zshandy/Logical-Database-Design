"""BGE sentence-transformer embeddings + cosine similarity helpers."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


_model = None  # lazy-loaded SentenceTransformer


def ensure_bge_model():
    """Lazy-load the BGE encoder on CUDA; called only when history is enabled."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-large-en-v1.5", device="cuda")
    return _model


def prepare_reference_embeddings(
    str_list: Sequence[str],
    indices: Optional[Sequence[int]] = None,
) -> Tuple[List[Tuple[int, str]], np.ndarray]:
    """Compute BGE embeddings for ``str_list``.

    If ``indices`` is provided, they are paired with each entry; otherwise
    defaults to ``[0..N-1]``. Texts are prefixed with ``"passage: "`` per BGE
    convention.

    Returns ``(ref_pairs, embeddings)``.
    """
    if indices is None:
        indices = list(range(len(str_list)))
    else:
        assert len(indices) == len(str_list), (
            f"indices length ({len(indices)}) must match str_list length ({len(str_list)})"
        )

    _m = ensure_bge_model()
    texts = ["passage: " + str(s).strip() for s in str_list]
    embeddings = _m.encode(texts, normalize_embeddings=True)
    ref_pairs = list(zip(indices, str_list))
    return ref_pairs, embeddings


def topk_embedding_cosine_sim(
    target_str: str,
    ref_pairs: Sequence[Tuple[int, str]],
    ref_embeddings: np.ndarray,
    top_k: int = 5,
) -> List[Tuple[int, str, float]]:
    """Compare ``target_str`` against precomputed reference embeddings and
    return the top ``top_k`` matches as ``(index, text, similarity)``.
    """
    _m = ensure_bge_model()
    target_emb = _m.encode(
        ["query: " + str(target_str).strip()],
        normalize_embeddings=True,
    )

    similarities = cosine_similarity(target_emb, ref_embeddings).flatten()
    top_idx = similarities.argsort()[::-1][:top_k]

    return [
        (ref_pairs[i][0], ref_pairs[i][1], float(similarities[i]))
        for i in top_idx
    ]
