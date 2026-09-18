import argparse
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from utils import ROOT_DIR
from evaluation import CacheMode, cachemode_type
from models import MODEL_SHORT_TO_FULL, MODEL_FULL_TO_SHORT
from experiment_agentic import experiment_agentic
from evaluate_non_agentic import evaluate_non_agentic
from fewshot.few_shot import (
    SelectionCacheError,
    load_fewshot_selection_cache,
    validate_selection_cache_for_modules,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-few_shot",
        type=int,
        default=1,
        help="The number of examples to use for few-shot, where 0 indicates no few-shot.",
    )
    parser.add_argument(
        "-model",
        choices=[
            "gpt-5",
            "claude-4",
            "claude-4-5-haiku",
            "claude-4-5-sonnet",
            "claude-4-5-opus",
            "claude-4-7-opus",
        ],
        help="LLM to prompt",
    )
    parser.add_argument(
        "-modules_dir",
        help="Directory of modules to evaluate",
        default=os.path.join(ROOT_DIR, "benchmarks/main_experiment"),
    )
    parser.add_argument(
        "-evaluation_cache_mode",
        type=cachemode_type,
        required=False,
        help=f"Cache mode. Options: {', '.join([m.name for m in CacheMode])}",
        default=CacheMode.FORCE_CACHED,
    )
    parser.add_argument(
        "--force_cached",
        action="store_true",
        help="Get lemmas for a prompt only if cached",
    )
    parser.add_argument(
        "--skip_prompts_creation",
        action="store_true",
        help="Skip creating the prompts, use when they exist in modules_dir and are up to date",
    )
    parser.add_argument(
        "-pipeline",
        choices=["agent", "non_agent"],
        help="Accepts either agent or non_agent",
    )
    parser.add_argument(
        "-storage_dir",
        help="Path to directory to read caches from",
        default=os.getenv("STORAGE_DIR", os.path.join(ROOT_DIR, "data")),
    )
    parser.add_argument(
        "-output_dir",
        help="Path to directory to write results to (defaults to storage_dir)",
        default=None,
    )
    parser.add_argument(
        "-work_dir",
        help="Job-local directory for temporary prompts",
        default=None,
    )
    parser.add_argument(
        "--fewshot-selection",
        choices=["live", "cached"],
        default="live",
        help="Select examples with live embeddings or a validated cache",
    )
    parser.add_argument(
        "--fewshot-selection-cache",
        default=os.path.join(ROOT_DIR, "data", "fewshot_selection.json"),
        help="Path to the permanent few-shot selection cache",
    )
    parser.add_argument(
        "--replay-read-only",
        action="store_true",
        help="Strict forced-cache replay: disable all cache writes and fail on misses",
    )
    parser.add_argument(
        "-num_samples", help="How many response samples to extract lemmas from"
    )
    parser.add_argument(
        "-num_iterations", help="Number of iterations for agentic setup", default=7
    )
    parser.add_argument("-ebmc_timeout", help="Timeout for ebmc", default=120)
    parser.add_argument(
        "-time_budget_s",
        type=float,
        default=None,
        help="Wall-clock budget (seconds) for the agentic loop "
        "(`logical_elapsed_s`). When the agent's accumulated "
        "logical time hits this, the loop stops with "
        "stop_reason='time_budget'. None = no budget. "
        "Ignored for the non-agent pipeline.",
    )
    parser.add_argument(
        "-cactus_cache_root",
        default=None,
        help="If set, read llm_cache per-module from <root>/<module_base>/llm_cache "
        "(produced by cactus runs) instead of the shared <storage>/llm_cache.",
    )

    args = parser.parse_args()
    experiment = os.path.basename(args.modules_dir)
    args.num_iterations = int(args.num_iterations)
    if args.replay_read_only:
        if not args.force_cached or args.evaluation_cache_mode != CacheMode.FORCE_CACHED:
            parser.error(
                "--replay-read-only requires --force_cached and "
                "-evaluation_cache_mode FORCE_CACHED"
            )
        if args.few_shot > 0 and args.fewshot_selection != "cached":
            parser.error(
                "--replay-read-only with few-shot prompts requires "
                "--fewshot-selection cached"
            )

    if args.few_shot > 0 and args.fewshot_selection == "cached":
        try:
            load_fewshot_selection_cache(args.fewshot_selection_cache)
            validate_selection_cache_for_modules(
                args.modules_dir, k=args.few_shot
            )
        except SelectionCacheError as exc:
            parser.error(str(exc))
    job_storage_path = os.path.join(
        args.storage_dir,
        experiment,
        f"{args.model}_{args.pipeline}_{args.few_shot}_{experiment}",
    )

    output_base = args.output_dir if args.output_dir else args.storage_dir
    job_output_path = os.path.join(
        output_base,
        experiment,
        f"{args.model}_{args.pipeline}_{args.few_shot}_{experiment}",
    )
    os.makedirs(job_output_path, exist_ok=True)
    os.makedirs(os.path.join(job_output_path, "results"), exist_ok=True)
    os.makedirs(os.path.join(job_output_path, "results", "summaries"), exist_ok=True)
    os.makedirs(os.path.join(job_output_path, "results", "logs"), exist_ok=True)
    work_dir = args.work_dir or os.path.join(job_output_path, "work")
    os.makedirs(work_dir, exist_ok=True)

    if args.num_samples is None:
        args.num_samples = 5

    args.model = MODEL_SHORT_TO_FULL.get(args.model, args.model)

    # Auto-derive cactus_cache_root for agent + fs=1 runs when:
    #   1. The user didn't pass -cactus_cache_root explicitly
    #   2. The conventional path (built by precopy_cactus_caches.py) exists on disk
    # Pattern (see scripts/cache_utils/precopy_cactus_caches.py):
    #   <storage_dir>/cactus/<experiment>/<model>_fs<few_shot>
    # Each module's cache lives under <root>/<module_base>/llm_cache.
    """ 
    if (
        args.cactus_cache_root is None
        and args.pipeline == "agent"
        and args.few_shot == 1
    ):
        model_short = MODEL_FULL_TO_SHORT.get(args.model, args.model)
        candidate = os.path.join(
            args.storage_dir,
            "cactus",
            experiment,
            f"{model_short}_fs{args.few_shot}",
        )
        if os.path.isdir(candidate):
            print(f"[INFO] Auto-detected cactus cache root: {candidate}")
            args.cactus_cache_root = candidate
    """
    if args.pipeline == "agent":
        experiment_agentic(
            storage_dir=job_storage_path,
            output_storage_dir=job_output_path,
            modules_dir=args.modules_dir,
            few_shot=args.few_shot,
            model=args.model,
            evaluation_cache_mode=args.evaluation_cache_mode,
            force_cached=args.force_cached,
            clear=False,
            num_iterations=args.num_iterations,
            ebmc_timeout=args.ebmc_timeout,
            cactus_cache_root=args.cactus_cache_root,
            time_budget_s=args.time_budget_s,
            work_dir=work_dir,
            fewshot_selection=args.fewshot_selection,
            cache_read_only=args.replay_read_only,
            strict_replay=args.replay_read_only,
        )
    else:
        evaluate_non_agentic(
            num_samples=args.num_samples,
            storage_dir=job_storage_path,
            output_storage_dir=job_output_path,
            modules_dir=args.modules_dir,
            model=args.model,
            evaluation_cache_mode=args.evaluation_cache_mode,
            force_cached=args.force_cached,
            skip_prompts_creation=args.skip_prompts_creation,
            few_shot=args.few_shot,
            ebmc_timeout=args.ebmc_timeout,
            work_dir=work_dir,
            fewshot_selection=args.fewshot_selection,
            cache_read_only=args.replay_read_only,
            strict_replay=args.replay_read_only,
        )
