import os
import json
import csv
import sys
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from utils import extract_json_block, extract_lemmas, ROOT_DIR
from prompt_llms import prompt_llms
from tqdm import tqdm
from diskcache import Cache


def add_lemmas(lemma_data, module_name, llm_model, lemmas, representation):
    """Stores lemmas in lemma_data dictionary for structured saving."""
    if module_name not in lemma_data:
        lemma_data[module_name] = {}

    if llm_model not in lemma_data[module_name]:
        lemma_data[module_name][llm_model] = {}

    lemma_data[module_name][llm_model][representation] = {"lemmas": lemmas}


def save_lemmas_to_csv(lemma_data, csv_file):
    """Saves the lemma dictionary to a CSV file."""
    os.makedirs(os.path.dirname(csv_file), exist_ok=True)

    with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["Module Name", "LLM Model", "Lemma #", "Lemma", "Representation"]
        )

        for module, llm_models in lemma_data.items():
            for llm_model, representation_dict in llm_models.items():
                for representation in representation_dict.keys():
                    for idx, lemma in enumerate(
                        representation_dict[representation]["lemmas"], start=1
                    ):
                        writer.writerow([module, llm_model, idx, lemma, representation])

    print(f"[INFO] Lemmas saved to {csv_file}")


def save_lemmas_to_json(lemma_data, json_file):
    """Saves the lemma dictionary to a JSON file."""
    os.makedirs(os.path.dirname(json_file), exist_ok=True)

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(lemma_data, f, indent=4)

    print(f"[INFO] Lemmas saved to {json_file}")


def process_prompts(
    storage_dir,
    prompts_dir,
    force_cached,
    json_output_path=None,
    csv_output_path=None,
    num_responses_to_return=1,
    cache_more=False,
    clear=False,
    aggregate=True,
    **kwargs,
):
    """Iterates over all prompt files in the directory, prompts llms and outputs returned lemmas in a ."""
    lemma_data = {}
    llm_cache = Cache(os.path.join(storage_dir, "llm_cache"))
    for prompt_file in tqdm(
        os.listdir(prompts_dir), desc="Running inference on prompt files"
    ):
        if not prompt_file.endswith(".json"):
            continue

        prompt_path = os.path.join(prompts_dir, prompt_file)
        print(f"[INFO] Processing {prompt_path}...")

        with open(prompt_path, "r", encoding="utf-8") as f:
            json_prompt = json.load(f)

        # Run the LLM and extract JSON response
        try:
            result = prompt_llms(
                prompt_path,
                cache=llm_cache,
                storage_dir=storage_dir,
                force_cached=force_cached,
                num_responses_to_return=num_responses_to_return,
                cache_more=cache_more,
                clear=clear,
                **kwargs,
            )

        except Exception as e:
            print(f"[ERROR]: {e}. Skipping.")
            continue

        llm_responses = result["response"]

        if force_cached and not result["cache_hit"]:
            assert llm_responses == None
            print(f"[FORCE CACHE] No cached response for {prompt_file}. Skipping.")
            continue

        print(f"Number of returned responses: {len(llm_responses)}")

        lemmas = []
        for response in llm_responses:
            # Previously: json_block = extract_json_block(response)
            json_block = extract_json_block(response["text"])
            if not json_block[0]:
                print(
                    f"[ERROR] No valid JSON block extracted from a response to {prompt_file}. Skipping."
                )
                continue

            new_lemmas = extract_lemmas(json_block[1])
            if not new_lemmas:
                print(
                    f"[ERROR] No lemmas found for a response to {prompt_file}. Skipping."
                )
                continue

            if aggregate:
                lemmas += new_lemmas
            else:
                lemmas.append(new_lemmas)

        # Extract module name, LLM model, representation
        module_name = json_prompt["module_name"]
        llm_model = json_prompt["model_name"]
        representation = json_prompt["representation"]

        add_lemmas(lemma_data, module_name, llm_model, lemmas, representation)

    # print(lemmas)
    # Save to CSV and JSON

    OUTPUT_CSV = (
        os.path.join(
            ROOT_DIR,
            f"scripts/results/proposed_lemmas_{os.path.basename(prompts_dir)}.csv",
        )
        if not csv_output_path
        else csv_output_path
    )
    OUTPUT_JSON = (
        os.path.join(
            ROOT_DIR,
            f"scripts/results/proposed_lemmas_{os.path.basename(prompts_dir)}.json",
        )
        if not json_output_path
        else json_output_path
    )
    save_lemmas_to_csv(lemma_data, OUTPUT_CSV)
    save_lemmas_to_json(lemma_data, OUTPUT_JSON)


# Run the processing function
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force_cached",
        action="store_true",
        help="Get lemmas for a prompt only if cached",
    )
    parser.add_argument("-prompts_dir", help="Path to directory with prompts")
    parser.add_argument("-output_csv", help="Path of the output csv file")
    parser.add_argument("-output_json", help="Path of the output json file")
    parser.add_argument(
        "-num_samples",
        help="How many reponse samples to extract lemmas from",
        default=1,
    )
    args = parser.parse_args()

    process_prompts(args.prompts_dir, args.force_cached)
