"""Few-shot example selection.

Public API:
    embedding_model_context()
        Context manager that lazily imports `sentence_transformers` and
        yields a loaded model.
    get_example_embeddings(model, dir)
        Compute embeddings for every `.sv` file in `dir`.
    get_k_nearest(model, filepath, examples, k=3)
        Return the top-k nearest example files by cosine similarity.
    load_fewshot_selection_cache(path)
        Load the pre-computed `data/fewshot_selection.json` so that
        `get_k_nearest` answers from cache without needing
        `sentence_transformers`. See Design §16.
    cache_miss_summary() / fewshot_selection_cache_loaded()
        Introspection helpers for tests and the `--fewshot-selection`
        CLI surface.

When the cache is loaded and a module is found there, `get_k_nearest`
never touches the embedding model argument — callers can pass `None`.
This lets `entry_point.py --fewshot-selection cached` skip the model
import entirely when the cache has every module (the paper case).
"""

from __future__ import annotations

import atexit
import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np



logger = logging.getLogger(__name__)


# --------------------------------------------------------------------
# Embedding-model context (lazy sentence_transformers import)
# --------------------------------------------------------------------


@contextmanager
def embedding_model_context():
    """Context manager for the embedding model.

    `sentence_transformers` is imported lazily so that modules downstream of
    few_shot (e.g. entry_point.py in cache-only mode) don't force an install
    of transformers/torch when they never invoke the few-shot path.
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-mpnet-base-v2")
    try:
        yield model
    finally:
        del model
        import gc

        gc.collect()


# --------------------------------------------------------------------
# Embedding helpers (live path)
# --------------------------------------------------------------------


def cosine_similarity(a, b):
    return np.dot(a, b)


def get_example_embeddings(embedding_model, example_modules_dir):
    """Compute and return `{filename: embedding}` for every `.sv` file
    under `example_modules_dir`.
    """
    example_texts = []
    example_files = []

    for fname in os.listdir(example_modules_dir):
        if fname.endswith(".sv"):
            with open(
                os.path.join(example_modules_dir, fname), "r", encoding="utf-8"
            ) as f:
                example_texts.append(f.read())
                example_files.append(fname)

    example_embeddings = embedding_model.encode(
        example_texts,
        normalize_embeddings=True,
        num_workers=16,
        show_progress_bar=True,
    )
    assert len(example_embeddings) == len(example_texts)
    return {example_files[i]: example_embeddings[i] for i in range(len(example_files))}


# --------------------------------------------------------------------
# Selection-cache singleton
# --------------------------------------------------------------------

_SELECTION_CACHE: dict | None = None
_CACHE_PATH: Path | None = None
_CACHE_MISSED_MODULES: set[str] = set()


def load_fewshot_selection_cache(path: Path | str) -> dict:
    """Load the shipped `data/fewshot_selection.json` into a process-wide
    singleton. Subsequent `get_k_nearest` calls consult the singleton
    before computing anything live. See Design §16.
    """
    global _SELECTION_CACHE, _CACHE_PATH
    path = Path(path)
    _SELECTION_CACHE = json.loads(path.read_text(encoding="utf-8"))
    _CACHE_PATH = path
    atexit.register(_log_cache_miss_summary)

    modules_count = len(_SELECTION_CACHE.get("modules", {}))
    max_k = _SELECTION_CACHE.get("_generated_from", {}).get("max_k_cached", "?")
    logger.info(
        "Loaded fewshot selection cache: %s (%d modules, max_k=%s)",
        path,
        modules_count,
        max_k,
    )
    return _SELECTION_CACHE


def fewshot_selection_cache_loaded() -> bool:
    return _SELECTION_CACHE is not None


def cache_miss_summary() -> list[str]:
    return sorted(_CACHE_MISSED_MODULES)


def _log_cache_miss_summary() -> None:
    if not _CACHE_MISSED_MODULES:
        return
    count = len(_CACHE_MISSED_MODULES)
    sample = sorted(_CACHE_MISSED_MODULES)
    logger.warning(
        "fewshot_selection cache miss for %d module(s): %s. "
        "This usually means the sentence_transformers library has shifted "
        "from the version used to build the cache (%s). "
        "Live recompute was used for these modules and will produce a "
        "different top-k ordering than the cache.",
        count,
        ", ".join(sample[:10]) + ("..." if count > 10 else ""),
        _CACHE_PATH if _CACHE_PATH else "<not loaded>",
    )


def max_k_cached() -> int | None:
    """Return the maximum k the loaded cache can serve, or None if not loaded."""
    if _SELECTION_CACHE is None:
        return None
    return int(_SELECTION_CACHE.get("_generated_from", {}).get("max_k_cached", 0))


# --------------------------------------------------------------------
# Core lookup
# --------------------------------------------------------------------


def get_k_nearest(embedding_model, filepath, examples, k: int = 3):
    """Return the top-k (filename, similarity) pairs nearest to the input.

    If the selection cache is loaded and contains `basename(filepath)`,
    returns `top_5_nearest[:k]` from the cache — `embedding_model` and
    `examples` are ignored. Otherwise falls back to a live
    sentence_transformers call, recording the miss for the end-of-run
    warning summary.
    """
    module_name = os.path.basename(filepath)

    # Cache hit — no embedding model needed.
    if _SELECTION_CACHE is not None:
        cached = _SELECTION_CACHE.get("modules", {}).get(module_name)
        if cached is not None:
            top5 = cached.get("top_5_nearest", [])
            if k > len(top5):
                # Cache doesn't have enough entries for this request.
                raise ValueError(
                    f"Requested k={k} exceeds max_k_cached="
                    f"{len(top5)} for module {module_name!r}. "
                    f"Regenerate {_CACHE_PATH} with --k-max {k}."
                )
            return [tuple(e) for e in top5[:k]]
        _CACHE_MISSED_MODULES.add(module_name)

    # Live path (either cache not loaded, or module missing from cache).
    if embedding_model is None:
        raise RuntimeError(
            f"get_k_nearest called with embedding_model=None but no cache "
            f"entry for {module_name!r}. Either pass an embedding model, "
            f"or load a selection cache that covers this module."
        )

    with open(filepath, "r", encoding="utf-8") as f:
        new_input_text = f.read()

    new_embedding = embedding_model.encode(new_input_text, normalize_embeddings=True)

    sims = {
        fname: cosine_similarity(new_embedding, emb) for fname, emb in examples.items()
    }
    top_items = sorted(sims.items(), key=lambda item: item[1], reverse=True)[:k]
    return top_items
