import json
import os
import sys
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from utils import ROOT_DIR
from evaluation import LemmaEvaluator, CacheMode, cachemode_type
import pandas as pd
import copy
import re
from typing import List
import logging
import time


def vr_dict_to_json_log(vr_dict):
    return {
        **{
            key: val["verification_result"].value
            for key, val in vr_dict.items()
            if key != "lemma"
        },
        "lemma": vr_dict["lemma"],
    }


def get_log(json_file, output_file=None):

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = {
        "statistics": {
            "Total Modules": 0,
            "Total Lemmas": 0,
            "Correct": 0,
            "1-Ind.": 0,
            "1-Ind.w.p": 0,
        },
        "modules": {},
    }
    num_modules = 0

    for module, models in data.items():
        num_modules += 1
        solved = 0

        for model, representations in models.items():
            if model == "property stats":
                continue

            for _, lemmas_list in representations.items():
                results["modules"][module] = {}
                for lemma_entry in lemmas_list:
                    if LemmaEvaluator.solves(lemma_entry):
                        solved = 1

                    if len(lemma_entry["lemma"]) == 1:
                        bools = LemmaEvaluator.translate_entry_to_booleans(lemma_entry)
                        results["statistics"]["Total Lemmas"] += 1
                        results["statistics"]["Correct"] += bools["correct"]
                        results["statistics"]["1-Ind."] += bools["1-inductive"]
                        results["statistics"]["1-Ind.w.p"] += bools[
                            "1-inductive with property"
                        ]

            results["modules"][module]["solved with 1 induction"] = solved
            results["modules"][module]["solved with both"] = solved

    results["statistics"]["Total Modules"] = num_modules
    # out_json = os.path.join("results", f"log_non_agentic_{model_name}.json") if not output_file else output_file
    out_json = output_file if output_file else os.path.join(json_file, "log.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"Wrote JSON evaluation log to: {out_json}")


def get_summary_table(json_file, output_dir):
    logging.basicConfig(
        filename=f"results/solved_modules_{os.path.basename(json_file)}.log",
        filemode="w",
        format="%(asctime)s - %(message)s",
        level=logging.INFO,
    )
    num_modules = 0
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = {}

    for module, models in data.items():
        num_modules += 1
        solved = 0

        for model, representations in models.items():
            if model == "property stats":
                continue

            if model not in results:
                results[model] = {
                    "Total Modules": 0,
                    "Total Lemmas": 0,
                    "Correct": 0,
                    "1-Ind.": 0,
                    "1-Ind.w.p": 0,
                    "Solved": 0,
                    "Error": 0,
                }

            for _, lemmas_list in representations.items():
                for lemma_entry in lemmas_list:
                    if LemmaEvaluator.solves(lemma_entry):
                        logging.info(f"Solved module {module} with lemma {lemma_entry}")
                        solved = True
                    if len(lemma_entry["lemma"]) == 1:
                        bools = LemmaEvaluator.translate_entry_to_booleans(lemma_entry)
                        results[model]["Total Lemmas"] += 1
                        results[model]["Correct"] += bools["correct"]
                        results[model]["1-Ind."] += bools["1-inductive"]
                        results[model]["1-Ind.w.p"] += bools[
                            "1-inductive with property"
                        ]
                        results[model]["Error"] += bools["error"]

            results[model]["Solved"] += solved
            results[model]["Total Modules"] = num_modules

    df = pd.DataFrame.from_dict(results, orient="index")
    return df, results


def evaluate_lemmas(
    storage_dir,
    input_json_path,
    modules_dir,
    tool,
    cache_result=True,
    all_subsets=True,
    skip_correctness=False,
    evaluation_cache_mode=CacheMode.FORCE_CACHED,
    output_json_path=None,
    module_to_eval=None,
    disable_cache=False,
    aggregate=True,
    ebmc_timeout=120,
    strict_replay=False,
    **kwargs,
):
    assert not disable_cache or evaluation_cache_mode == CacheMode.NO_CACHE
    if not output_json_path:
        output_json_path = os.path.join(
            ROOT_DIR,
            f"scripts/results/{os.path.splitext(os.path.basename(input_json_path))[0]}_eval_{tool}.json",
        )

    with open(input_json_path, "r") as f:
        lemmas_dict = json.load(f)

    items = (
        sorted(lemmas_dict.items())
        if not module_to_eval
        else [(module_to_eval, lemmas_dict[module_to_eval])]
    )

    evaluation_dict = (
        copy.deepcopy(lemmas_dict)
        if not module_to_eval
        else {module_to_eval: copy.deepcopy(lemmas_dict[module_to_eval])}
    )

    for module, models in items:
        print(f"Processing module {module}")
        sv_file = next(
            (
                f
                for f in (
                    os.path.join(ROOT_DIR, f"{modules_dir}/{module}{ext}")
                    for ext in (".sv", ".v")
                )
                if os.path.exists(f)
            ),
            None,
        )

        if not sv_file:
            print(f"Error processing module {module}: module file not found. Skipping.")
            continue
        tcl_file = (
            os.path.join(ROOT_DIR, f"{modules_dir}/tcl_files/{module}.tcl")
            if tool == "jg"
            else None
        )

        lemma_evaluator = LemmaEvaluator(
            storage_dir,
            tool,
            sv_file,
            tcl_file,
            cache_result=cache_result,
            cache_mode=evaluation_cache_mode,
            ebmc_path="ebmc",
            skip_correctness=skip_correctness,
            timeout=ebmc_timeout,
            init_cache_with_no_cache_mode=(not disable_cache),
            cache_read_only=(
                evaluation_cache_mode == CacheMode.FORCE_CACHED
                or not cache_result
            ),
            fail_on_cache_miss=strict_replay,
        )
        logger = logging.getLogger(__name__)

        logger.info(f"Processing module {module}")

        # TODO: UPDATE, and later also with separate batches for different samples
        for model, data in models.items():
            for representation, lemmas in data.items():
                updated_lemmas = []
                lemmas_to_evaluate = remove_redundancies(lemmas["lemmas"])

                start = time.perf_counter()
                result_entries = lemma_evaluator.evaluate_subsets(lemmas_to_evaluate)
                end = time.perf_counter()
                for entry in result_entries:
                    to_be_appended = vr_dict_to_json_log(entry)
                    updated_lemmas.append(to_be_appended)

                evaluation_dict[module][model][representation] = updated_lemmas

        evaluation_dict[module]["property stats"] = lemma_evaluator.debug()[
            "verification_result"
        ].value

    with open(output_json_path, "w") as f:
        print("Writing evaluation results to", output_json_path)
        json.dump(evaluation_dict, f, indent=4)


_BODY_RE = re.compile(
    r"""^\s*            # leading space
        [^;]+;          # lemma name up to first semicolon (ignored)
        \s*(.*?)        # <-- capture the BODY
        \s*;?\s*        # optional trailing semicolon/space
        endproperty\b   # terminator
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)


def _normalize_ws(s: str) -> str:
    """Collapse all whitespace runs to a single space and strip ends."""
    return re.sub(r"\s+", " ", s).strip()


def remove_redundancies(lemmas: List[str]) -> List[str]:
    """
    Deduplicate lemma strings by their *body*.
    Lemmas are considered equal if the text between the first ';'
    (after the name) and 'endproperty' is the same (ignoring whitespace).

    Keeps the first occurrence of each unique body and preserves input order.
    Lemmas that don't match the expected pattern are kept as-is (and treated
    as unique unless their exact normalized text repeats).
    """
    seen = set()
    result = []

    for lemma in lemmas:
        m = _BODY_RE.search(lemma)
        if m:
            body_norm = _normalize_ws(m.group(1))
        else:
            # Fallback: normalize the whole lemma if pattern not matched
            body_norm = _normalize_ws(lemma)

        if body_norm not in seen:
            seen.add(body_norm)
            result.append(lemma)

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", help="Either 'ebmc' or 'jg'", default="ebmc")
    parser.add_argument(
        "-evaluation_cache_mode",
        type=cachemode_type,
        required=False,
        help=f"Cache mode. Options: {', '.join([m.name for m in CacheMode])}",
        default=CacheMode.FORCE_CACHED,
    )

    parser.add_argument(
        "--cache_result", action="store_true", help="Cache the evaluation results"
    )

    parser.add_argument(
        "-input_json_path", help="Path to the json file containing the proposed lemmas"
    )
    parser.add_argument(
        "-output_json_path", help="Path in which to store the evaluation results"
    )
    parser.add_argument(
        "-module_to_eval",
        default=None,
        help="Module to evaluate from the json file. Used for slurm script. Default is all modules",
    )
    parser.add_argument(
        "--all_subsets",
        action="store_true",
        help="Whether to compute 1-inductiveness for all subsets of correct lemmas",
    )
    parser.add_argument(
        "-modules_dir",
        help="Path to the directory containing the verilog modules. Expects to have a subdirectory 'tcl_files' with their corresponding tcl files",
    )
    parser.add_argument(
        "--correctness_only",
        action="store_true",
        help="Determine only whether each lemma is correct",
    )
    parser.add_argument(
        "--skip_correctness",
        action="store_true",
        help="Do not compute correctness of lemmas. Take from cache if exist. Meant for calling ebmc with jg correctness results",
    )
    args = parser.parse_args()

    evaluate_lemmas(**vars(args))


# Example usage:
#   python evaluate_lemmas.py -input_json_path <lemmas.json> --all_subsets \
#       -modules_dir <sv_dir> -module_to_eval gulwani_cegar2_5 -output_json_path check.json
