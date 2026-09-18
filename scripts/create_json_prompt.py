"""Build the prompt JSON consumed by :mod:`src.prompt_llms`.

The prompt text intentionally matches the implementation used to produce the
published caches. Even whitespace changes alter the cache key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
for import_dir in (REPO_ROOT, SRC_DIR):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

from fewshot.few_shot import get_example_embeddings, get_k_nearest
from utils import (
    DEFAULT_EXAMPLE_MODULES_DIR,
    DEFAULT_EXAMPLE_RESPONSES_DIR,
    DEFAULT_TEMPLATE,
    DEFAULT_TEMPLATE_FS,
    DEFAULT_TEMPLATE_FS_GPT5,
)


def read_file(filename):
    """Read a UTF-8 text file."""
    with open(filename, "r", encoding="utf-8") as f:
        return f.read()


def create_fs_prompt(
    embedding_model,
    template_file,
    module_file,
    example_embeddings_dict,
    example_modules_dir,
    example_responses_dir,
    k,
    selection_mode="live",
):
    """Create the exact few-shot prompt format used by the paper runs."""
    k_nearest = get_k_nearest(
        embedding_model=embedding_model,
        filepath=module_file,
        examples=example_embeddings_dict,
        k=k,
        selection_mode=selection_mode,
    )
    template_content = read_file(template_file)
    verilog_content = read_file(module_file)
    full_prompt = f"{template_content}\n\n\n# Examples: \n\n"
    for ind, (fname, _) in enumerate(k_nearest):
        with open(
            os.path.join(example_modules_dir, fname), "r", encoding="utf-8"
        ) as f:
            example_content = f.read()

        response_name = f"{os.path.splitext(os.path.basename(fname))[0]}.txt"
        with open(
            os.path.join(example_responses_dir, response_name),
            "r",
            encoding="utf-8",
        ) as f:
            example_response = f.read()

        full_prompt += (
            f"## Example {ind + 1} Input Module:\n\n{example_content}\n"
            f"## Example {ind + 1} Response:\n\n{example_response} \n\n"
        )

    full_prompt += (
        "# Your Turn:\nFollow the steps above for the following module and "
        f"property: {verilog_content}"
    )
    return full_prompt


def create_basic_prompt(template_file, module_file):
    template_content = read_file(template_file)
    verilog_content = read_file(module_file)
    return f"{template_content}\n\n{verilog_content}"


def create_json(
    module_file,
    model_name,
    embedding_model=None,
    output_file=None,
    prompts_output_dir=None,
    few_shot=0,
    template_file=None,
    example_modules_dir=DEFAULT_EXAMPLE_MODULES_DIR,
    example_responses_dir=DEFAULT_EXAMPLE_RESPONSES_DIR,
    example_embeddings=None,
    fewshot_selection="live",
    **kwargs,
):
    """Combine a template and SystemVerilog module into a prompt JSON file."""
    del kwargs

    if template_file is None:
        template_file = (
            DEFAULT_TEMPLATE
            if not few_shot
            else DEFAULT_TEMPLATE_FS_GPT5
            if model_name == "gpt-5"
            else DEFAULT_TEMPLATE_FS
        )

    output_file = output_file or generate_output_filename(
        template_file, module_file, model_name
    )
    if prompts_output_dir:
        output_file = os.path.join(prompts_output_dir, output_file)

    module_file_base_name = os.path.splitext(os.path.basename(module_file))[0]
    template_file_base_name = os.path.splitext(os.path.basename(template_file))[0]

    if not few_shot:
        full_prompt = create_basic_prompt(template_file, module_file)
    else:
        if example_modules_dir is None or example_responses_dir is None:
            raise ValueError("Few-shot example directories must be provided")
        if example_embeddings is None and fewshot_selection == "live":
            example_embeddings = get_example_embeddings(
                embedding_model=embedding_model,
                example_modules_dir=example_modules_dir,
            )
        full_prompt = create_fs_prompt(
            embedding_model,
            template_file,
            module_file,
            example_embeddings,
            example_modules_dir,
            example_responses_dir,
            few_shot,
            selection_mode=fewshot_selection,
        )

    if "claude" in model_name:
        full_prompt = "\n\nHuman: " + full_prompt + "\n\nAssistant: "

    data = {
        "prompt": full_prompt,
        "model_name": model_name,
        "module_name": module_file_base_name,
        "representation": template_file_base_name,
    }

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    return str(output_path)


def generate_output_filename(template_file, module_file, model_name):
    template_name = os.path.splitext(os.path.basename(template_file))[0]
    module_name = os.path.splitext(os.path.basename(module_file))[0]
    clean_model_name = model_name.split("/")[-1]
    return f"{template_name}_{module_name}_{clean_model_name}.json"


def main():
    parser = argparse.ArgumentParser(
        description="Generate a JSON prompt from a template and module."
    )
    parser.add_argument("--template_file", help="Path to the prompt template.")
    parser.add_argument("--module_file", required=True)
    parser.add_argument("--model_name", required=True)
    parser.add_argument("-o", "--output")
    parser.add_argument("--prompts_output_dir")
    parser.add_argument("--few_shot", type=int, default=2)
    parser.add_argument(
        "--example_modules_dir", default=DEFAULT_EXAMPLE_MODULES_DIR
    )
    parser.add_argument(
        "--example_responses_dir", default=DEFAULT_EXAMPLE_RESPONSES_DIR
    )
    args = parser.parse_args()
    create_json(**vars(args))


if __name__ == "__main__":
    main()
