"""Deterministic live and cached few-shot example selection."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager
from pathlib import Path

import numpy as np


logger = logging.getLogger(__name__)

EMBEDDING_MODEL_ID = "sentence-transformers/all-mpnet-base-v2"
EMBEDDING_MODEL_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
SELECTION_CACHE_SCHEMA_VERSION = 1


class SelectionCacheError(RuntimeError):
    """Raised when a cached few-shot selection cannot be used safely."""


@contextmanager
def embedding_model_context(
    model_id: str = EMBEDDING_MODEL_ID,
    revision: str = EMBEDDING_MODEL_REVISION,
    local_files_only: bool | None = None,
):
    """Load the embedding model lazily.

    Importing this module never imports sentence-transformers. Cached replay
    can therefore run without loading the embedding stack.
    """
    from sentence_transformers import SentenceTransformer

    kwargs = {"revision": revision}
    if local_files_only is not None:
        kwargs["local_files_only"] = local_files_only
    model = SentenceTransformer(model_id, **kwargs)
    try:
        yield model
    finally:
        del model
        import gc

        gc.collect()


def cosine_similarity(a, b):
    return np.dot(a, b)


def _sorted_module_files(directory: Path | str) -> list[Path]:
    directory = Path(directory)
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".v", ".sv"}
    )


def get_example_embeddings(embedding_model, example_modules_dir):
    """Return embeddings keyed by filename, with deterministic input order."""
    if embedding_model is None:
        raise ValueError("An embedding model is required for live selection")

    example_paths = _sorted_module_files(example_modules_dir)
    example_texts = [path.read_text(encoding="utf-8") for path in example_paths]
    example_embeddings = embedding_model.encode(
        example_texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    if len(example_embeddings) != len(example_paths):
        raise RuntimeError("Embedding model returned an unexpected result count")
    return {
        path.name: example_embeddings[index]
        for index, path in enumerate(example_paths)
    }


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SELECTION_CACHE: dict | None = None
_CACHE_PATH: Path | None = None
_CACHE_REPOSITORY_ROOT: Path | None = None


def clear_fewshot_selection_cache() -> None:
    """Reset process-local cache state (primarily useful for tests)."""
    global _SELECTION_CACHE, _CACHE_PATH, _CACHE_REPOSITORY_ROOT
    _SELECTION_CACHE = None
    _CACHE_PATH = None
    _CACHE_REPOSITORY_ROOT = None


def _relative_key(path: Path | str, repository_root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise SelectionCacheError(
            f"Input {resolved} is outside selection-cache repository root "
            f"{repository_root}"
        ) from exc


def _validate_hashes(
    hashes: dict[str, str], repository_root: Path, description: str
) -> None:
    for relative_path in sorted(hashes):
        path = repository_root / relative_path
        if not path.is_file():
            raise SelectionCacheError(
                f"{description} is missing: {relative_path} "
                f"(selection cache: {_CACHE_PATH})"
            )
        actual = sha256_file(path)
        expected = hashes[relative_path]
        if actual != expected:
            raise SelectionCacheError(
                f"{description} hash changed for {relative_path}: "
                f"expected {expected}, got {actual}"
            )


def load_fewshot_selection_cache(
    path: Path | str, repository_root: Path | str | None = None
) -> dict:
    """Load and validate a permanent selection cache."""
    global _SELECTION_CACHE, _CACHE_PATH, _CACHE_REPOSITORY_ROOT

    cache_path = Path(path).resolve()
    if not cache_path.is_file():
        raise SelectionCacheError(f"Few-shot selection cache not found: {cache_path}")

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectionCacheError(
            f"Could not read few-shot selection cache {cache_path}: {exc}"
        ) from exc

    if payload.get("schema_version") != SELECTION_CACHE_SCHEMA_VERSION:
        raise SelectionCacheError(
            f"Unsupported selection-cache schema "
            f"{payload.get('schema_version')!r}; expected "
            f"{SELECTION_CACHE_SCHEMA_VERSION}"
        )

    metadata = payload.get("metadata")
    modules = payload.get("modules")
    if not isinstance(metadata, dict) or not isinstance(modules, dict):
        raise SelectionCacheError(
            f"Selection cache {cache_path} must contain metadata and modules objects"
        )

    max_k = metadata.get("max_k")
    if not isinstance(max_k, int) or max_k <= 0:
        raise SelectionCacheError(
            f"Selection cache {cache_path} has invalid metadata.max_k={max_k!r}"
        )

    root = (
        Path(repository_root).resolve()
        if repository_root is not None
        else cache_path.parent.parent.resolve()
    )
    _SELECTION_CACHE = payload
    _CACHE_PATH = cache_path
    _CACHE_REPOSITORY_ROOT = root

    example_hashes = metadata.get("example_input_hashes")
    if not isinstance(example_hashes, dict) or not example_hashes:
        clear_fewshot_selection_cache()
        raise SelectionCacheError(
            f"Selection cache {cache_path} has no example_input_hashes metadata"
        )
    try:
        _validate_hashes(example_hashes, root, "Few-shot example input")
    except Exception:
        clear_fewshot_selection_cache()
        raise

    logger.info(
        "Loaded few-shot selection cache %s (%d modules, max_k=%d)",
        cache_path,
        len(modules),
        max_k,
    )
    return payload


def fewshot_selection_cache_loaded() -> bool:
    return _SELECTION_CACHE is not None


def max_k_cached() -> int | None:
    if _SELECTION_CACHE is None:
        return None
    return int(_SELECTION_CACHE["metadata"]["max_k"])


def _cached_selection(filepath: Path | str, k: int) -> list[tuple[str, float]]:
    if _SELECTION_CACHE is None or _CACHE_REPOSITORY_ROOT is None:
        raise SelectionCacheError(
            "Cached few-shot selection requested before loading a cache"
        )
    if k <= 0:
        return []

    max_k = max_k_cached()
    if max_k is None or k > max_k:
        raise SelectionCacheError(
            f"Requested k={k} exceeds selection-cache maximum {max_k}"
        )

    key = _relative_key(filepath, _CACHE_REPOSITORY_ROOT)
    entry = _SELECTION_CACHE["modules"].get(key)
    if entry is None:
        raise SelectionCacheError(
            f"Selection cache {_CACHE_PATH} has no entry for {key}"
        )

    actual_hash = sha256_file(filepath)
    expected_hash = entry.get("input_sha256")
    if actual_hash != expected_hash:
        raise SelectionCacheError(
            f"Benchmark input hash changed for {key}: expected "
            f"{expected_hash}, got {actual_hash}"
        )

    nearest = entry.get("nearest")
    if not isinstance(nearest, list) or len(nearest) < k:
        raise SelectionCacheError(
            f"Selection cache entry for {key} contains only "
            f"{len(nearest) if isinstance(nearest, list) else 0} choices; "
            f"k={k} was requested"
        )

    result: list[tuple[str, float]] = []
    for choice in nearest[:k]:
        if not isinstance(choice, dict):
            raise SelectionCacheError(f"Malformed cached selection for {key}")
        filename = choice.get("filename")
        similarity = choice.get("similarity")
        if not isinstance(filename, str) or not isinstance(
            similarity, (int, float)
        ):
            raise SelectionCacheError(f"Malformed cached selection for {key}")
        result.append((filename, float(similarity)))
    return result


def validate_selection_cache_for_modules(
    modules_dir: Path | str, k: int
) -> list[str]:
    """Validate complete cache coverage and hashes for a benchmark directory."""
    keys = []
    for module_path in _sorted_module_files(modules_dir):
        _cached_selection(module_path, k)
        assert _CACHE_REPOSITORY_ROOT is not None
        keys.append(_relative_key(module_path, _CACHE_REPOSITORY_ROOT))
    return keys


def get_k_nearest(
    embedding_model,
    filepath,
    examples,
    k: int = 3,
    selection_mode: str = "live",
):
    """Return top-k ``(example filename, cosine similarity)`` pairs.

    ``selection_mode='cached'`` is strict: misses, changed inputs, and requests
    above the cached maximum fail instead of falling back to embeddings.
    """
    if selection_mode == "cached":
        return _cached_selection(filepath, k)
    if selection_mode != "live":
        raise ValueError(
            f"Unknown few-shot selection mode {selection_mode!r}; "
            "expected 'live' or 'cached'"
        )
    if embedding_model is None or examples is None:
        raise ValueError("Live few-shot selection requires embeddings")
    if k <= 0:
        return []

    new_input_text = Path(filepath).read_text(encoding="utf-8")
    new_embedding = embedding_model.encode(
        new_input_text, normalize_embeddings=True
    )
    similarities = (
        (filename, float(cosine_similarity(new_embedding, embedding)))
        for filename, embedding in examples.items()
    )
    return sorted(similarities, key=lambda item: (-item[1], item[0]))[:k]
