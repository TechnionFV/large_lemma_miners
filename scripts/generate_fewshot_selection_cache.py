#!/usr/bin/env python3
"""Generate and verify the permanent few-shot selection cache."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fewshot.few_shot import (  # noqa: E402
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    SELECTION_CACHE_SCHEMA_VERSION,
    clear_fewshot_selection_cache,
    embedding_model_context,
    get_example_embeddings,
    get_k_nearest,
    load_fewshot_selection_cache,
    sha256_file,
)


DEFAULT_OUTPUT = REPO_ROOT / "data" / "fewshot_selection.json"
BENCHMARK_DIRS = (
    REPO_ROOT / "benchmarks" / "main_experiment",
    REPO_ROOT / "benchmarks" / "hard",
)
EXAMPLE_INPUT_DIR = REPO_ROOT / "fewshot" / "examples_raw"
EXAMPLE_RESPONSE_DIR = REPO_ROOT / "fewshot" / "examples_full"


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def module_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".v", ".sv"}
    )


def file_hashes(paths: list[Path]) -> dict[str, str]:
    return {relative(path): sha256_file(path) for path in sorted(paths)}


def build_cache(model, max_k: int) -> dict:
    examples = module_files(EXAMPLE_INPUT_DIR)
    benchmarks = sorted(
        path for directory in BENCHMARK_DIRS for path in module_files(directory)
    )
    response_files = sorted(
        path for path in EXAMPLE_RESPONSE_DIR.iterdir() if path.is_file()
    )
    example_embeddings = get_example_embeddings(model, EXAMPLE_INPUT_DIR)

    modules = {}
    for module_path in benchmarks:
        nearest = get_k_nearest(
            model,
            module_path,
            example_embeddings,
            k=max_k,
            selection_mode="live",
        )
        modules[relative(module_path)] = {
            "input_sha256": sha256_file(module_path),
            "nearest": [
                {"filename": filename, "similarity": similarity}
                for filename, similarity in nearest
            ],
        }

    return {
        "schema_version": SELECTION_CACHE_SCHEMA_VERSION,
        "metadata": {
            "embedding_model": {
                "identifier": EMBEDDING_MODEL_ID,
                "revision": EMBEDDING_MODEL_REVISION,
            },
            "sentence_transformers_version": importlib.metadata.version(
                "sentence-transformers"
            ),
            "max_k": max_k,
            "benchmark_input_hashes": file_hashes(benchmarks),
            "example_input_hashes": file_hashes(examples),
            "example_response_hashes": file_hashes(response_files),
        },
        "modules": modules,
    }


def verify_cache(payload: dict, model) -> None:
    clear_fewshot_selection_cache()
    cache_path = Path(payload["_cache_path"])
    load_fewshot_selection_cache(cache_path, repository_root=REPO_ROOT)
    examples = get_example_embeddings(model, EXAMPLE_INPUT_DIR)
    max_k = payload["metadata"]["max_k"]

    mismatches = []
    for key in sorted(payload["modules"]):
        module_path = REPO_ROOT / key
        live = get_k_nearest(
            model, module_path, examples, k=max_k, selection_mode="live"
        )
        cached = get_k_nearest(
            None, module_path, None, k=max_k, selection_mode="cached"
        )
        if [name for name, _ in live] != [name for name, _ in cached]:
            mismatches.append(
                {
                    "module": key,
                    "live": [name for name, _ in live],
                    "cached": [name for name, _ in cached],
                }
            )
    if mismatches:
        raise RuntimeError(
            "Cached/live few-shot ordering mismatch:\n"
            + json.dumps(mismatches, indent=2, sort_keys=True)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-k", type=int, default=5)
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow Hugging Face downloads (generation is offline by default)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Recompute every live top-k ordering after writing the cache",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_k <= 0:
        raise SystemExit("--max-k must be a positive integer")

    with embedding_model_context(
        local_files_only=not args.allow_download
    ) as model:
        payload = build_cache(model, args.max_k)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if args.verify:
            verify_payload = dict(payload)
            verify_payload["_cache_path"] = str(args.output.resolve())
            verify_cache(verify_payload, model)

    print(
        f"Wrote {args.output} with {len(payload['modules'])} modules "
        f"and max_k={args.max_k}"
    )
    if args.verify:
        print("Verified cached/live top-k ordering for every module")


if __name__ == "__main__":
    main()
