"""Create prompt JSON files for every module in an experiment directory."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import nullcontext
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
for import_dir in (REPO_ROOT, SRC_DIR):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

from scripts.create_json_prompt import create_json
from fewshot.few_shot import embedding_model_context, get_example_embeddings
from utils import (
    DEFAULT_EXAMPLE_MODULES_DIR,
    DEFAULT_EXAMPLE_RESPONSES_DIR,
    DEFAULT_TEMPLATE,
    DEFAULT_TEMPLATE_FS,
    DEFAULT_TEMPLATE_FS_GPT5,
    ROOT_DIR,
)


def create_batch_prompts(
    modules_dir,
    model,
    few_shot=2,
    prompts_output_dir=None,
    example_modules_dir=None,
    template_file=None,
    fewshot_selection="live",
    **kwargs,
):
    """Create prompts while preserving the format used by published caches."""
    models = model if isinstance(model, list) else [model]
    if len(models) != 1:
        raise ValueError("Exactly one model must be supplied")

    prompts_output_dir = prompts_output_dir or os.path.join(
        ROOT_DIR, "scripts", "prompts", f"{os.path.basename(modules_dir)}_batch"
    )
    template_file = template_file or (
        DEFAULT_TEMPLATE
        if not few_shot
        else DEFAULT_TEMPLATE_FS_GPT5
        if models[0] == "gpt-5"
        else DEFAULT_TEMPLATE_FS
    )
    example_modules_dir = example_modules_dir or DEFAULT_EXAMPLE_MODULES_DIR

    os.makedirs(prompts_output_dir, exist_ok=True)

    model_context = (
        embedding_model_context()
        if few_shot and fewshot_selection == "live"
        else nullcontext(None)
    )
    with model_context as embedding_model:
        example_embeddings = (
            get_example_embeddings(
                embedding_model=embedding_model,
                example_modules_dir=example_modules_dir,
            )
            if few_shot and fewshot_selection == "live"
            else None
        )

        for filename in sorted(os.listdir(modules_dir)):
            module_file = os.path.join(modules_dir, filename)
            if not filename.endswith((".v", ".sv")) or not os.path.isfile(module_file):
                continue
            for model_name in models:
                create_json(
                    embedding_model=embedding_model,
                    model_name=model_name,
                    few_shot=few_shot,
                    prompts_output_dir=prompts_output_dir,
                    example_embeddings=example_embeddings,
                    fewshot_selection=fewshot_selection,
                    module_file=module_file,
                    template_file=template_file,
                    **kwargs,
                )


def main():
    parser = argparse.ArgumentParser(
        description="Generate prompt JSON files for a module directory."
    )
    parser.add_argument("--modules_dir", required=True)
    parser.add_argument("--template_file")
    parser.add_argument("--prompts_output_dir", required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--few_shot", type=int, default=0)
    parser.add_argument(
        "--example_modules_dir", default=DEFAULT_EXAMPLE_MODULES_DIR
    )
    parser.add_argument(
        "--example_responses_dir", default=DEFAULT_EXAMPLE_RESPONSES_DIR
    )
    args = parser.parse_args()
    arguments = vars(args)
    models = arguments.pop("models")
    create_batch_prompts(model=models, **arguments)


if __name__ == "__main__":
    main()
