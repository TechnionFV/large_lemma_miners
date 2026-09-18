import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from utils import ROOT_DIR, clear_directory, DEFAULT_TEMPLATE_FS, setup_logging
from create_batch_prompts import create_batch_prompts
from get_lemmas import process_prompts
from evaluate_lemmas import evaluate_lemmas, get_summary_table, get_log
from evaluation import CacheMode, cachemode_type


def evaluate_non_agentic(
    modules_dir,
    model,
    storage_dir=None,
    output_storage_dir=None,
    few_shot=1,
    num_samples: int = 1,
    tool="ebmc",
    cache_more=False,
    force_cached=False,
    clear=False,
    evaluation_cache_mode=CacheMode.FORCE_CACHED,
    template_file=DEFAULT_TEMPLATE_FS,
    separate=False,
    exp_name=None,
    skip_prompts_creation=False,
    ebmc_timeout=120,
    work_dir=None,
    fewshot_selection="live",
    cache_read_only=False,
    strict_replay=False,
):
    assert os.path.isdir(modules_dir)

    modules_dir_basename = os.path.basename(os.path.normpath(modules_dir))
    model_names_string = model

    prompts_dir_suffix = (
        f"{modules_dir_basename}_fs{few_shot}_ns{num_samples}"
        f"_{model_names_string}_{os.path.basename(template_file)}"
    )
    prompts_dir = (
        os.path.join(work_dir, "prompts")
        if work_dir
        else os.path.join(ROOT_DIR, "scripts", "prompts", prompts_dir_suffix)
    )
    aggregate = not separate

    # Reads (caches) come from `storage_dir`. Writes (results, summaries,
    # logs) go to `output_storage_dir` when supplied; otherwise they default
    # to `storage_dir` for backwards compatibility with single-location runs.
    storage_dir = storage_dir if storage_dir else ROOT_DIR
    output_storage_dir = output_storage_dir if output_storage_dir else storage_dir
    output_dir = os.path.join(output_storage_dir, "results")
    log_dir = os.path.join(output_dir, "logs")

    output_path_str = (
        f"proposed_lemmas_{prompts_dir_suffix}_ns{num_samples}"
        if aggregate
        else f"proposed_lemmas_{prompts_dir_suffix}_ns{num_samples}_no_aggregate"
    )
    output_json_lemmas = os.path.join(output_dir, f"{output_path_str}.json")
    output_csv_lemmas = os.path.join(output_dir, f"{output_path_str}.csv")
    output_json_eval = f"{os.path.splitext(output_json_lemmas)[0]}_eval_{tool}.json"

    arguments_dict = {
        "input_json_path": output_json_lemmas,
        "output_json_path": output_json_eval,
        "cache_result": not (
            cache_read_only or evaluation_cache_mode == CacheMode.FORCE_CACHED
        ),
        "storage_dir": storage_dir,
        "modules_dir": modules_dir,
        "model": model,
        "few_shot": few_shot,
        "num_samples": num_samples,
        "tool": tool,
        "cache_more": cache_more,
        "force_cached": force_cached,
        "clear": clear,
        "evaluation_cache_mode": evaluation_cache_mode,
        "template_file": template_file,
        "separate": separate,
        "exp_name": exp_name,
        "skip_prompts_creation": skip_prompts_creation,
        "ebmc_timeout": ebmc_timeout,
        "fewshot_selection": fewshot_selection,
        "cache_read_only": cache_read_only,
        "strict_replay": strict_replay,
    }

    if not skip_prompts_creation:
        os.makedirs(prompts_dir, exist_ok=True)
        clear_directory(prompts_dir)
        create_batch_prompts(prompts_output_dir=prompts_dir, **arguments_dict)
    else:
        assert os.path.isdir(prompts_dir)

    exp_id = exp_name or f"{model}_{num_samples}_{time.strftime('%Y%m%d-%H%M%S')}"
    log_file = (
        Path(log_dir) / f"evaluate_non_agentic_{prompts_dir_suffix}_ns{num_samples}.log"
    )
    setup_logging(
        str(log_file), experiment_id=exp_id, level=logging.INFO, to_console=True
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting non-agentic evaluation")

    process_prompts(
        storage_dir=storage_dir,
        prompts_dir=prompts_dir,
        force_cached=force_cached,
        json_output_path=output_json_lemmas,
        csv_output_path=output_csv_lemmas,
        num_responses_to_return=num_samples,
        cache_more=cache_more,
        clear=clear,
        aggregate=aggregate,
        cache_read_only=cache_read_only,
        strict_cache=strict_replay,
    )
    evaluate_lemmas(**arguments_dict)
    df, results = get_summary_table(output_json_eval, output_dir=output_dir)

    aggregate_summary_path = os.path.join(
        output_dir,
        "summaries",
        f"summary_aggregate_non_agentic_{model.replace(':', '_')}"
        f"_fewshot_{few_shot}_{modules_dir_basename}_ns{num_samples}.json",
    )
    os.makedirs(os.path.dirname(aggregate_summary_path), exist_ok=True)
    with open(aggregate_summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Wrote aggregate results JSON to: {aggregate_summary_path}")

    summary_output_file = os.path.join(
        output_dir,
        "summaries",
        f"summary_non_agentic_{model.replace(':', '_')}"
        f"_fewshot_{few_shot}_{modules_dir_basename}_ns{num_samples}.json",
    )
    get_log(output_json_eval, output_file=summary_output_file)
    print(df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force_cached",
        action="store_true",
        help="Get lemmas for a prompt only if cached",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear cached responses for specified llm and recache",
    )
    parser.add_argument(
        "-evaluation_cache_mode",
        type=cachemode_type,
        required=False,
        help=f"Cache mode. Options: {', '.join(m.name for m in CacheMode)}",
        default=CacheMode.FORCE_CACHED,
    )
    parser.add_argument("-modules_dir", help="Path to directory with prompts")
    parser.add_argument(
        "-few_shot",
        type=int,
        help="Number of few-shot examples (0 disables few-shot)",
        default=1,
    )
    parser.add_argument(
        "-num_samples",
        type=int,
        help="How many response samples to extract lemmas from",
        default=1,
    )
    parser.add_argument("-model", help="LLM to prompt")
    parser.add_argument("-tool", default="ebmc")
    parser.add_argument("--cache_more", action="store_true", default=False)
    parser.add_argument(
        "--skip_prompts_creation",
        action="store_true",
        help="Skip creating the prompts; use when they already exist",
    )
    parser.add_argument(
        "-template_file",
        help="Path to the prompt template file",
        required=False,
        default=DEFAULT_TEMPLATE_FS,
    )
    parser.add_argument(
        "--separate",
        action="store_true",
        help="Evaluate the lemmas for each sample separately",
    )
    parser.add_argument("--exp-name", default=None, help="Name/id for this experiment")

    args = parser.parse_args()
    if not args.modules_dir:
        args.modules_dir = os.path.join(ROOT_DIR, "benchmarks", "main_experiment")

    evaluate_non_agentic(**vars(args))


# Example:
#   python3 evaluate_non_agentic.py --force_cached -evaluation_cache_mode FORCE_CACHED \
#       -few_shot 1 -num_samples 5 -model claude-3-7 --skip_prompts_creation --exclude_implication
