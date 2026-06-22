from scripts.create_json_prompt import create_json
from prompt_llms import prompt_llms
from utils import (
    DEFAULT_REPAIR_TEMPLATE,
    DEFAULT_TEMPLATE_FS,
    ROOT_DIR,
)
import json
from typing import List, Union  # , Dict, Union, Optional
import os
from utils import extract_json_block, extract_lemmas
from evaluation import LemmaEvaluator, VerificationResult, CacheMode
import argparse
import re
import logging
import time


class LLMAgent:
    def __init__(
        self,
        storage_dir,
        module_file,
        model_name,
        embedding_model,
        eval_cache=None,
        llm_cache=None,
        initial_template=DEFAULT_TEMPLATE_FS,
        repair_template=DEFAULT_REPAIR_TEMPLATE,
        few_shot=1,
        output_file_prefix="",
        show_cex=False,
        num_iterations=5,
        cache_mode=CacheMode.CACHE_LENIENT,
        force_cached=False,
        old_eval=False,
        clear=False,
        ebmc_timeout=120,
        time_budget_s=None,
    ):
        self.module_file = module_file
        self.file_basename = os.path.splitext(os.path.basename(self.module_file))[0]
        self.model_name = model_name
        self.embedding_model = embedding_model
        self.initial_template = initial_template
        self.repair_template = repair_template
        self.few_shot = few_shot
        self.counter = 0
        self.output_file_prefix = output_file_prefix
        self.num_iterations = num_iterations
        self.time_budget_s = time_budget_s
        self.evaluator = LemmaEvaluator(
            storage_dir=storage_dir,
            cache=eval_cache,
            tool="ebmc",
            verilog_file=self.module_file,
            cache_mode=cache_mode,
            init_cache_with_no_cache_mode=True,
            timeout=ebmc_timeout,
        )
        self.show_cex = show_cex
        self.proposed_lemmas = []
        self.correct_lemmas = []
        self.lemma_records = {
            "total": 0,
            "correct": 0,
            "1-inductive": 0,
            "1-inductive with property": 0,
            "error": 0,
        }
        self.solved = False
        self.force_cached = force_cached
        self.old_eval = old_eval
        self.clear = clear
        self.storage_dir = storage_dir
        self.llm_cache = llm_cache
        # Timing state (populated in converse())
        self.logical_elapsed_s = 0.0
        self.iteration_times_s = []
        self.solved_iteration = None
        self.solved_time_s = None
        self.stop_reason = None
        self.total_time_s = None

    @staticmethod
    def _no_json_block_message(info):
        message_error = f"Your last response did not follow the expected format. It yielded the following error: {info}"
        json_format_reminder = """Provide the proposed lemmas in a JSON block as follows:
    <json>
    {
    "lemmas": [
        {
            "lemma": "property lemma_<index>; <SVA lemma>; endproperty",
            "explanation": "<Concise rationale here>"
        }
    ]
    // ... additional lemmas in sequential order as needed
    }
    </json>"""

        return message_error + json_format_reminder

    def _get_next_json_filename(self):
        base_dir = os.path.join(ROOT_DIR, "scripts/agent_jsons")
        os.makedirs(base_dir, exist_ok=True)
        basename = f"{self.output_file_prefix}_{self.model_name}_{self.file_basename}_{self.counter}.json"
        return os.path.join(base_dir, basename)

    def _create_initial_prompt(self):
        output_file = self._get_next_json_filename()
        # few_shot = True if self.few_shot > 0 else False
        create_json(
            embedding_model=self.embedding_model,
            template_file=self.initial_template,
            module_file=self.module_file,
            model_name=self.model_name,
            output_file=output_file,
            few_shot=self.few_shot,
        )

        with open(output_file, "r") as f:
            data = json.load(f)

        return [{"role": "user", "content": data["prompt"]}]

    """ Returns the path to a JSON file containing the prompt parameters, formatted for compatibility with prompt_llms"""

    def _json_from_conversation(self, conversation):
        new_file_path = self._get_next_json_filename()
        data = {
            "model_name": self.model_name,
            "module_name": self.file_basename,
            "messages": conversation,
        }

        with open(new_file_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return new_file_path

    def _stop(self, eval):
        # If we're already over budget at iteration entry, don't run another
        # `_check_all_correct` sweep — that re-runs `evaluate_subsets` and
        # can be expensive even on a warm cache.
        if self.time_budget_s and self.logical_elapsed_s >= self.time_budget_s:
            self.stop_reason = "time_budget"
            return True
        self._check_all_correct()

        if self.solved:
            self.stop_reason = self.stop_reason or "solved"
            return True
        if self.counter >= self.num_iterations:
            self.stop_reason = "max_iterations"
            return True
        return False

    def _prompt_conversation(self, conversation: List):
        json_file_path = self._json_from_conversation(conversation)
        try:
            res = prompt_llms(
                json_file_path,
                storage_dir=self.storage_dir,
                cache=self.llm_cache,
                force_cached=self.force_cached,
                clear=self.clear,
            )
        except ValueError as e:
            print(f"[Error]: {e}")
            return {"cache_hit": False, "response": None}
        finally:
            if os.path.exists(json_file_path):
                os.remove(json_file_path)
        if res["response"] is None:
            return res
        assert len(res["response"]) == 1
        return res
        # return res['response'][0]['text']

    def _eval_reply(self, eval_so_far, new_assistant_reply):
        success, info = extract_json_block(new_assistant_reply)
        if not success:
            return (success, info)
        lemmas = extract_lemmas(info)

        results = self._evaluate_lemmas(lemmas)  # returns a list now
        self._update_records(results)

        return (True, results)

    def _update_records(self, new_lemmas):
        if any([self.evaluator.solves(new_lemma) for new_lemma in new_lemmas]):
            self.solved = True

        singletons = self.evaluator.get_singleton_entries(new_lemmas)
        for new_lemma in singletons:
            bools = self.evaluator.translate_entry_to_booleans(new_lemma)
            if not any(
                d.get("lemma") == new_lemma["lemma"] for d in self.proposed_lemmas
            ):
                self.proposed_lemmas.append(new_lemma)
                self.lemma_records["total"] += 1
                self.lemma_records["1-inductive"] += bools["1-inductive"]
                self.lemma_records["correct"] += bools["correct"]
                self.lemma_records["1-inductive with property"] += bools[
                    "1-inductive with property"
                ]
                self.lemma_records["error"] += bools["error"]
                if bools["correct"]:
                    self.correct_lemmas.append(new_lemma)

    @staticmethod
    def extract_error(text: str, line_num: int | None = None) -> str | None:
        """
        Extracts the error block starting with 'line <N>:' (or any 'line <number>:')
        and continuing until 'CONVERSION ERROR' if present, otherwise to the end.
        """
        if line_num is not None:
            pattern = rf"(line {int(line_num)}:.*?)(?:CONVERSION ERROR|$)"
        else:
            pattern = r"(line \d+:.*?)(?:CONVERSION ERROR|$)"

        match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else text.strip()

    def _repair_message(
        self,
        conversation: List[dict[str, str]],
        eval: Union[List[dict[str, str]], None],
    ):

        if not eval[0]:  # no json block
            return self._no_json_block_message(eval[1])

        message = []
        # Give general reminders every two rounds
        if not self.counter % 2:
            with open(self.repair_template, "r") as f:
                template_lines = f.readlines()
                message.extend(template_lines)

        singleton_entries = self.evaluator.get_singleton_entries(eval[1])
        for lemma_dict in singleton_entries:
            message.append(f"\n// Feedback for {lemma_dict['lemma'][0]}: ")
            correctness_field = lemma_dict["correct"]
            bools = LemmaEvaluator.translate_entry_to_booleans(lemma_dict)  # new

            if bools["1-inductive with property"]:
                message.append(
                    "The conjunction of the lemma and the property is 1-inductive, so the lemma helps prove the property. Good job!"
                )  # there are cases where this field is true, but correctness times out

            elif correctness_field["verification_result"] == VerificationResult.PROVEN:
                message.append(f"The lemma is correct.")
                message.append(
                    "However, it does not form a 1-inductive argument when conjoined with the property. Please give a better lemma."
                )

            elif correctness_field["verification_result"] == VerificationResult.CEX:
                if self.show_cex:
                    message.append("The lemma is incorrect. Here is a counterexample: ")
                    message.append(correctness_field["info"])
                else:
                    message.append("The lemma is incorrect. Repair or replace it.")

            elif correctness_field["verification_result"] == VerificationResult.ERROR:
                message.append("There's an error with the lemma: ")
                error = self.extract_error(correctness_field["info"])
                if not error:
                    print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
                    print(f"empty message extracted for: {correctness_field['info']}")
                message.append(error)

            elif correctness_field["verification_result"] == VerificationResult.TIMEOUT:
                message.append(
                    "The lemma timed out and its correctness could not be determined."
                )

            else:
                raise RuntimeError(
                    f"Unexpected verification result (uncached?): {correctness_field['verification_result']}"
                )

        return "\n".join(message)

    def _update_conversation(
        self, conversation: List[dict[str, str]], new_assistant_reply: str, eval
    ):
        conversation.append({"role": "assistant", "content": new_assistant_reply})
        next_user_message = self._repair_message(conversation, eval)
        if not next_user_message or not next_user_message.strip():
            next_user_message = (
                "Please propose new lemmas. Follow the JSON format specified earlier."
            )
        conversation.append({"role": "user", "content": next_user_message})
        return conversation

    def _check_all_correct(self):
        """Verify the accumulated correct lemmas one more time and update
        `self.solved`. Logical EBMC time is added to `self.logical_elapsed_s`
        per-entry (mirrors the `_eval_reply` accounting in `converse`), so
        cached EBMC results contribute their preserved `time` fields.
        """
        correct_lemmas = [
            lemma["lemma"][0] for lemma in self.correct_lemmas
        ]  # TODO: no need to check correctness, already done in evaluate_subsets
        if not len(correct_lemmas):
            return

        verification_result_entries = self._evaluate_lemmas(correct_lemmas)
        self.logical_elapsed_s += self._extract_eval_time(
            (True, verification_result_entries)
        )

        # if any(self.evaluator.solves(entry) for entry in verification_result_entries):
        for entry in verification_result_entries:
            if self.evaluator.solves(entry):
                self.solved = True
                logger = logging.getLogger(__name__)
                logger.info(f"Solved module {self.file_basename} with lemmas {entry}")
                break

    def _evaluate_lemmas(self, lemmas: Union[str, List[str]]):
        return self.evaluator.evaluate_subsets(lemmas)

        # if (res["correct"] == VerificationResult.CEX and "info" not in res["correct"].keys()): Migrated to evaluator
        #     print(res["correct"])
        #     print(self.file_basename)
        #     assert False

    def _get_conv_results(self, conversation, eval):
        return {
            "lemma records": self.lemma_records,
            "solved": self.solved,
            "conversation": conversation,
            "solved_iteration": self.solved_iteration,
            "solved_time_s": self.solved_time_s,
            "iteration_times_s": self.iteration_times_s,
            "total_time_s": self.total_time_s,
            "total_wall_time_s": self.total_wall_time_s,
            "stop_reason": self.stop_reason,
            "num_iterations_run": self.counter,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
        }

    def _extract_eval_time(self, eval_result) -> float:
        """Extract the total logical evaluation time from eval results.

        Each verification result entry (correct, 1-inductive, etc.) has a 'time'
        field representing the original EBMC runtime — whether the result came
        from cache or was computed live. This gives consistent logical time
        regardless of cache state.

        Returns 0 if eval failed (no JSON block) or has no time info.
        """
        if not eval_result or not eval_result[0]:
            # eval_result is (False, error_info) — no valid JSON block
            return 0.0

        # eval_result is (True, results_list) where results_list is from evaluate_subsets
        results_list = eval_result[1]
        total_time = 0.0
        verification_keys = ("correct", "1-inductive", "1-inductive with property")

        for entry in results_list:
            if not isinstance(entry, dict):
                continue
            for key in verification_keys:
                vr = entry.get(key)
                if isinstance(vr, dict):
                    t = vr.get("time", 0)
                    if isinstance(t, (int, float)) and t > 0 and t != float("inf"):
                        total_time += t

        return total_time

    def converse(self):
        self.logical_elapsed_s = 0.0
        self.iteration_times_s = []
        self.solved_iteration = None
        self.solved_time_s = None
        self.stop_reason = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        wall_start = time.perf_counter()

        conversation = self._create_initial_prompt()
        eval = None

        while not self._stop(eval):
            iter_logical_start = self.logical_elapsed_s

            res = self._prompt_conversation(conversation)
            _, reply = res.values()
            if (
                not reply
            ):  # exception thrown in prompting / not cached and in FORCE_CACHED mode
                self.stop_reason = "prompt_error"
                break

            # Accumulate LLM inference time from cached/live response
            # This is the original inference time regardless of whether it came from cache
            llm_time = reply[0].get("time", 0) if isinstance(reply[0], dict) else 0
            if llm_time > 0:
                self.logical_elapsed_s += llm_time

            # Accumulate token usage
            if isinstance(reply[0], dict):
                self.total_input_tokens += reply[0].get("input_tokens", 0)
                self.total_output_tokens += reply[0].get("output_tokens", 0)

            assert len(reply) == 1
            reply = reply[0]["text"]

            eval = self._eval_reply(eval, reply)
            # Accumulate evaluation time from the verification results.
            # Each result entry has time fields that represent the original EBMC time
            # whether the result came from cache or was computed live.
            eval_logical_time = self._extract_eval_time(eval)
            self.logical_elapsed_s += eval_logical_time

            conversation = self._update_conversation(conversation, reply, eval)
            self.counter += 1

            iter_logical_time = self.logical_elapsed_s - iter_logical_start
            self.iteration_times_s.append(iter_logical_time)

            if self.solved and self.solved_iteration is None:
                self.solved_iteration = self.counter  # 1-indexed
                self.solved_time_s = self.logical_elapsed_s

        self.total_time_s = self.logical_elapsed_s
        self.total_wall_time_s = time.perf_counter() - wall_start
        return self._get_conv_results(conversation, eval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module_file", help="Path to module file")
    parser.add_argument("-model_name", help="LLM to prompt")
    args = parser.parse_args()

    agent = LLMAgent(module_file=args.module_file, model_name=args.model_name)
    res = agent.converse()
