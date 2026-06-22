import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agentic import LLMAgent  # Update this with the actual import path
from evaluation import CacheMode, cachemode_type
from utils import ROOT_DIR
from collections import defaultdict
import json
import argparse
from tqdm import tqdm
import logging
import time
from utils import setup_logging
from pathlib import Path
from fewshot.few_shot import embedding_model_context
from diskcache import Cache


def run_conversations_on_dir(
    storage_dir,
    input_dir,
    evaluation_cache_mode,
    force_cached,
    few_shot=1,
    model_name="gpt-4o",
    clear=False,
    num_iterations=5,
    ebmc_timeout=120,
    cactus_cache_root=None,
    time_budget_s=None,
):
    """
    Run agentic conversations on every .sv module in `input_dir`.

    If `cactus_cache_root` is set, BOTH the per-module LLM cache and the
    per-module eval cache are read from
        <cactus_cache_root>/<module_base>/llm_cache
        <cactus_cache_root>/<module_base>/eval_cache
    (the layout produced by cactus runs via scripts/entry_point_single.py).
    Otherwise the shared <storage_dir>/llm_cache and <storage_dir>/eval_cache
    are used (legacy behavior).
    """
    results = {}
    shared_eval_cache = None
    shared_llm_cache = None
    if cactus_cache_root is None:
        shared_eval_cache = Cache(os.path.join(storage_dir, "eval_cache"))
        shared_llm_cache = Cache(os.path.join(storage_dir, "llm_cache"))
    with embedding_model_context() as embedding_model:
        for filename in tqdm(os.listdir(input_dir), desc="Processing files"):
            file_path = os.path.join(input_dir, filename)
            if not os.path.isfile(file_path) or not filename.endswith(".sv"):
                continue

            module_base = os.path.splitext(filename)[0]
            if cactus_cache_root is not None:
                per_module_llm_dir = os.path.join(
                    cactus_cache_root, module_base, "llm_cache"
                )
                per_module_eval_dir = os.path.join(
                    cactus_cache_root, module_base, "eval_cache"
                )
                if not os.path.isdir(per_module_llm_dir):
                    logging.getLogger(__name__).warning(
                        f"No cactus llm_cache for {module_base} at {per_module_llm_dir}; "
                        f"opening empty cache (will hit the LLM for any missing entries)."
                    )
                if not os.path.isdir(per_module_eval_dir):
                    logging.getLogger(__name__).warning(
                        f"No cactus eval_cache for {module_base} at {per_module_eval_dir}; "
                        f"opening empty cache (will re-run EBMC for any missing entries)."
                    )
                llm_cache = Cache(per_module_llm_dir)
                eval_cache = Cache(per_module_eval_dir)
            else:
                llm_cache = shared_llm_cache
                eval_cache = shared_eval_cache

            try:
                agent = LLMAgent(
                    eval_cache=eval_cache,
                    llm_cache=llm_cache,
                    storage_dir=storage_dir,
                    embedding_model=embedding_model,
                    module_file=file_path,
                    model_name=model_name,
                    cache_mode=evaluation_cache_mode,
                    force_cached=force_cached,
                    few_shot=few_shot,
                    clear=clear,
                    num_iterations=num_iterations,
                    ebmc_timeout=ebmc_timeout,
                    time_budget_s=time_budget_s,
                )
                result = agent.converse()
                results[filename] = result
            finally:
                if cactus_cache_root is not None:
                    llm_cache.close()
                    eval_cache.close()

    return results


def summarize_all_lemma_records(results_dict):
    aggregate = defaultdict(int)
    num_solved = 0

    for entry in results_dict.values():
        lemma_stats = entry.get("lemma records", {})
        for key, value in lemma_stats.items():
            aggregate[key] += value

        if entry.get("solved") is True:
            num_solved += 1

    aggregate["solved"] = num_solved
    aggregate["num_modules"] = len(results_dict)

    return dict(aggregate)


def output_detailed_json(results_dict, output_path):
    """Returns a json with the lemma records for each module"""

    detailed = {}
    for module, entry in results_dict.items():
        detailed[module] = {
            "solved": entry["solved"],
            "lemma records": entry.get("lemma records", {}),
            "solved_iteration": entry.get("solved_iteration"),
            "solved_time_s": entry.get("solved_time_s"),
            "iteration_times_s": entry.get("iteration_times_s"),
            "total_time_s": entry.get("total_time_s"),
            "stop_reason": entry.get("stop_reason"),
            "num_iterations_run": entry.get("num_iterations_run"),
        }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(detailed, f, ensure_ascii=False, indent=2, sort_keys=True)


def output_summary(input_path, output_path):
    with open(input_path, "r") as f:
        data = json.load(f)

    modules = {}
    stats = {
        "1-Ind.": 0,
        "1-Ind.w.p": 0,
        "Correct": 0,
        "Total Lemmas": 0,
        "Total Modules": 0,
    }

    for filename, rec in data.items():
        # Module name without extension (e.g., "itc99_b13_13" from "itc99_b13_13.sv")
        module_name = os.path.splitext(filename)[0]

        solved_flag = 1 if rec.get("solved", False) else 0
        modules[module_name] = {"solved": solved_flag}

        lr = rec.get("lemma records", {})
        stats["1-Ind."] += lr.get("1-inductive", 0)
        stats["1-Ind.w.p"] += lr.get("1-inductive with property", 0)
        stats["Correct"] += lr.get("correct", 0)
        stats["Total Lemmas"] += lr.get("total", 0)

    stats["Total Modules"] = len(modules)

    out = {"modules": modules, "statistics": stats}
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)


def experiment_agentic(
    modules_dir,
    few_shot,
    model,
    evaluation_cache_mode,
    storage_dir=None,
    output_storage_dir=None,
    force_cached=False,
    clear=False,
    num_iterations=5,
    exp_name=None,
    ebmc_timeout=120,
    cactus_cache_root=None,
    time_budget_s=None,
):

    storage_dir = storage_dir if storage_dir else ROOT_DIR
    output_storage_dir = output_storage_dir if output_storage_dir else storage_dir
    output_dir = os.path.join(output_storage_dir, "results")
    log_dir = os.path.join(output_dir, "logs")
    exp_id = exp_name or f"{model}_agent_{time.strftime('%Y%m%d-%H%M%S')}"
    log_file = (
        Path(log_dir)
        / f"experiment_agentic_{model}_{os.path.basename(modules_dir)}_fs_{few_shot}_num_iterations_{num_iterations}.log"
    )

    setup_logging(
        str(log_file), experiment_id=exp_id, level=logging.INFO, to_console=True
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting agentic evaluation")

    results = run_conversations_on_dir(
        storage_dir,
        modules_dir,
        few_shot=few_shot,
        model_name=model,
        force_cached=force_cached,
        evaluation_cache_mode=evaluation_cache_mode,
        clear=clear,
        num_iterations=num_iterations,
        ebmc_timeout=ebmc_timeout,
        cactus_cache_root=cactus_cache_root,
        time_budget_s=time_budget_s,
    )

    with open(
        os.path.join(
            output_dir,
            f"agent_conversations_fs{few_shot}_{model}_{os.path.basename(modules_dir)}_num_iterations_{num_iterations}.json",
        ),
        "w",
    ) as f:
        json.dump(results, f, indent=2)

    results_aggregate = summarize_all_lemma_records(results)

    out_json = os.path.join(
        output_dir,
        "summaries",
        f"summary_aggregate_agentic_{model}_fewshot_{few_shot}_{os.path.basename(modules_dir)}_num_iterations_{num_iterations}.json",
    )
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results_aggregate, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(results_aggregate)

    detailed_json_path = os.path.join(
        output_dir,
        f"agentic_detailed_lemma_records_{model}_fewshot_{few_shot}_{os.path.basename(modules_dir)}_num_iterations_{num_iterations}.json",
    )
    output_detailed_json(results, detailed_json_path)
    print(f"Wrote detailed lemma records to {detailed_json_path}")

    output_summary(
        detailed_json_path,
        os.path.join(
            output_dir,
            "summaries",
            f"summary_agentic_{model}_fewshot_{few_shot}_{os.path.basename(modules_dir)}_num_iterations_{num_iterations}.json",
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-few_shot",
        type=int,
        default=1,
        help="The number of examples to use for few-shot, where 0 indicates no few-shot.",
    )
    parser.add_argument("-model", help="LLM to use")
    parser.add_argument(
        "--force_cached", action="store_true", help="Use only cached responses"
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
        "-storage_dir", help="Path to save outputs in and read cache from"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete cached LLM responses for the agent prompts and recache",
    )
    args = parser.parse_args()

    experiment_agentic(**vars(args))
