import subprocess
import re
import os
from enum import Enum
import hashlib
from typing import List, Union
import time
import copy
import logging
from cache_utils import open_cache

ebmc_executable = os.getenv("EBMC_PATH", "ebmc")

JG_CORRECT_TIMEOUT = 20
JG_HELPFUL_TIMEOUT = 600
BMC_BOUND = 5
EBMC_K_FOR_INDUCTION = 5
EBMC_BMC_BOUND = 30
EBMC_TIMEOUT = 120


class VerificationResult(Enum):
    PROVEN = 1
    CEX = 2
    TIMEOUT = 3
    ERROR = 4
    UNCACHED = 5
    INCONCLUSIVE = 6


class CacheMode(Enum):
    FORCE_CACHED = (
        1  # Computes nothing. If queries don't exist in cache, returns UNCACHED
    )
    CACHE_LENIENT = 2  # Computes queries that do not exist in cache
    CACHE_PICKY = 3  # Computes results that do not exist in cache + inconclusive/error/timeout results
    NO_CACHE = 4  # Computes everything


def cachemode_type(value: str) -> CacheMode:
    try:
        return CacheMode[value]
    except KeyError:
        raise argparse.ArgumentTypeError(
            f"Invalid cache mode '{value}'. Valid options: {', '.join([m.name for m in CacheMode])}"
        )


def make_list(x):
    return sorted(x) if isinstance(x, list) else [x]


class VerilogModule:
    """Handles Verilog file modifications such as stripping assertions and adding assumptions."""

    def __init__(self, filepath, tcl_filepath=None):
        self.filepath = filepath
        self.module_name = os.path.splitext(os.path.basename(filepath))[0]
        with open(filepath, "r") as f:
            self.lines = f.readlines()

        self.lines_with_lemmas = self.lines

        self.top = "main"
        self.tcl = {"tcl_filepath": tcl_filepath, "tcl_lines": None}
        if tcl_filepath:
            with open(tcl_filepath, "r") as f:
                self.tcl["tcl_lines"] = f.readlines()

        self._initial_insert_at = self._find_insert_at_index()
        self._insert_at = self._initial_insert_at
        assert self._insert_at > 0 and self._insert_at < len(self.lines)
        self.rst_exists = self.find_reset(self.lines)
        self.num_lemmas = 0

    @staticmethod
    def find_reset(verilog_lines: List):
        text = "\n".join(verilog_lines)
        pattern = re.compile(r"\binput(?:\s+(?:reg|logic|wire))?\s+rst\b", re.MULTILINE)
        return bool(pattern.search(text))

    def get_config(self):
        return {"top": self.top}

    def _get_top(self):
        for line in self.lines:
            words = line.split()
            if "module" in words:
                top = words[words.index("module") + 1]  # Extract next word
                return top

    def get_names_string(self, properties: list[str]):
        """Returns a string of the names of properties from a list of named property declaration"""
        names = [self.get_property_name(property) for property in properties]
        names = [name for name in names if name]
        if not names:
            return ""
        numbers = [int(s.split("_")[1]) for s in names]
        start = min(numbers)
        end = max(numbers)
        return f"lemmas{start}_{end}"

    def get_property_name(self, property: str):
        """Extracts the name of a property from a named property declaration"""
        match = re.search(r"\bproperty\s+(\w+)\s*;", property)
        if match:
            return match.group(1)
        else:
            return property

    def insert_lemmas_description(self, lemmas_to_insert: list[str]):
        """
        Writes to self.lines_with_lemmas the verilog module with the input lemmas, assuming
        they are named declaration constructs only, without assume/assert directives.
        """
        lemmas = [lemma + "\n" for lemma in lemmas_to_insert]
        if not lemmas:
            return
        lines_with_lemmas = self.lines_with_lemmas[:]
        lines_with_lemmas[self._insert_at : self._insert_at] = lemmas
        self.lines_with_lemmas = lines_with_lemmas
        self._insert_at = self._find_insert_at_index()

    def is_property_declaration(self, some_string):
        match = re.search(
            r"property\s+\w+\s*;.*?endproperty\s*", some_string, re.DOTALL
        )
        return match

    def get_directives(self, properties, mode):
        """
        When mode == 'debug', 'assert property(prop);' is added to the sv file, to determine whether it's 1-inductive alone.
        """
        directives = []
        property_names = [self.get_property_name(property) for property in properties]
        ands = " and ".join(property_names)
        ors = " or ".join(property_names)
        match mode:
            case "correctness" | "correctness_bounded":
                directives = [f"assert property({ands}); \n"]
            case "one_induction" | "k_induction" | "one_induction_buechi":
                directives = [f"assert property({ands}); \n"]
            case "one_inductive_with_prop" | "one_inductive_with_prop_buechi":
                property_names_with_prop = [
                    self.get_property_name(property) for property in properties
                ] + ["prop"]
                ands_with_prop = " and ".join(property_names_with_prop)
                directives = [f"assert property({ands_with_prop}); \n"]
            case "timing_with_lemmas":
                for property_name in property_names:
                    directives.append[f"assume property ({property_name}); \n"]
                    directives.append[f"assert property (prop); \n "]
            case "timing_without_lemmas" | "debug" | "debug_buechi":
                directives = [f"assert property (prop); \n"]

        return directives

    def insert_directive_for_properties(self, properties, mode, new_file_path):
        """
        Writes to new_file_path the verilog module with an assume/assert directive for
        the property. Property can either be a property name, or a named property declaration,
        in which case it is assumed it was already added to self.lines_with_lemmas.
        mode: one of {"one_induction", "correctness", "one_inductive_with_prop", "debug"}
        """
        lines_to_copy = self.lines_with_lemmas

        directives = self.get_directives(properties, mode)

        lines_to_copy[self._insert_at : self._insert_at] = directives

        with open(new_file_path, "w", encoding="utf-8") as f:
            f.writelines(lines_to_copy)

    def clear_lemmas(self):
        self.num_lemmas = 0
        self.lines_with_lemmas = self.lines
        self._insert_at = self._initial_insert_at

    def _find_insert_at_index(self):
        # pattern = re.compile(r"^\s*endproperty")
        pattern = re.compile(r"^.*endproperty\s*(//.*)?$")
        matched_indices = [
            i for i, line in enumerate(self.lines_with_lemmas) if pattern.match(line)
        ]
        if len(matched_indices) == 0:
            raise ValueError(f"No property found for file {self.filepath}")

        return matched_indices[-1] + 1

    def get_property(self):
        """Returns the sva property for the module"""
        content = "".join(self.lines)
        # print(content)

        match = re.search(r"property prop;\s*(.*?)\s*endproperty", content, re.S)
        # print(match)
        if match:
            return match.group(1)
        else:
            raise ValueError("No property found.")

    def _write_new_tcl(self, new_file_path, new_tcl_path, engine=None):
        """Writes to tcl_file_path a tcl script which runs verilog_file_path"""
        assert self.tcl["tcl_lines"] is not None
        modified_lines = []
        if "all" == engine or engine == None:
            modified_lines = [
                f"analyze -sv09 {new_file_path}\n" if "analyze -sv09" in line else line
                for line in self.tcl["tcl_lines"]
            ]
        else:
            # turns off proof simplification, as well
            for line in self.tcl["tcl_lines"]:
                # Replace analyze line if needed
                if "analyze -sv09" in line:
                    modified_lines.append(f"analyze -sv09 {new_file_path}\n")
                else:
                    modified_lines.append(line)

                # Insert after "elaborate" line
                if line.strip().startswith("elaborate"):
                    modified_lines.append(f"set_engine_mode {engine}\n")
                    modified_lines.append("set_proof_simplification off\n")

        with open(new_tcl_path, "w") as f:
            f.writelines(modified_lines)


class LemmaEvaluator:
    """Evaluates a lemma using JG/EBMC."""

    def __init__(
        self,
        storage_dir,
        tool,
        verilog_file,
        cache=None,
        tcl_file=None,
        cache_result=True,
        ebmc_path=ebmc_executable,
        skip_correctness=False,
        cache_mode=CacheMode.FORCE_CACHED,
        init_cache_with_no_cache_mode=True,
        only_singletons=False,
        timeout=EBMC_TIMEOUT,
        cache_read_only=False,
        fail_on_cache_miss=False,
    ):
        if tool not in ["jg", "ebmc"]:
            raise ValueError(
                "Please specify a model checker to use, either ebmc or JasperGold"
            )
        self.module = VerilogModule(verilog_file, tcl_file)
        self.ebmc_path = ebmc_path
        self.tool = tool
        self.timeout = timeout
        self.cache = cache

        if self.cache == None and (
            cache_mode != CacheMode.NO_CACHE or init_cache_with_no_cache_mode
        ):
            self.cache = open_cache(
                os.path.join(storage_dir, "eval_cache"),
                read_only=(cache_read_only or cache_mode == CacheMode.FORCE_CACHED),
            )

        self.cache_read_only = cache_read_only or cache_mode == CacheMode.FORCE_CACHED
        self.cache_result = cache_result and not self.cache_read_only
        self.fail_on_cache_miss = fail_on_cache_miss
        self.skip_correctness = skip_correctness
        self.cache_mode = cache_mode
        self.only_singletons = only_singletons

    def _extract_lemma_body(self, lemma: str) -> str:
        """
        Extract the body of a SystemVerilog property lemma.
        Assumes format: property <name>; <body> ; endproperty
        """
        match = re.search(
            r"property\s+\w+\s*;\s*(.*?)\s*;?\s*endproperty", lemma, re.DOTALL
        )
        if match:
            body = match.group(1).strip()
            if not body:
                raise ValueError("Lemma body is empty")
        else:
            raise ValueError(f"Could not extract body from lemma:\n{lemma}")

        return body

    def _hash_query(
        self, lemmas: list, mode: str, engine: str, tool: str = None
    ) -> str:
        """Generate a hash for the lemma, mode and module name to use as a cache key."""
        if not tool:
            tool = self.tool
        try:
            lemmas_rep = "\n".join(
                sorted([self._extract_lemma_body(lemma) for lemma in lemmas])
            )
        except ValueError:
            lemmas_rep = "\n".join(sorted([lemma for lemma in lemmas]))

        return hashlib.sha256(
            f"{lemmas_rep}-{mode}-{engine}-{self.module.module_name}-{tool}".encode()
        ).hexdigest()

    @staticmethod
    def translate_entry_to_booleans(
        lemma_entry: Union[dict[str, Union[str, int], dict[str, Union[str, dict]]]],
    ) -> dict[str, bool]:
        def is_proven(result):
            if isinstance(result, dict):
                result = result.get("verification_result")
            return (
                result == VerificationResult.PROVEN
                or result == VerificationResult.PROVEN.value
            )

        def is_cex(result):
            if isinstance(result, dict):
                result = result.get("verification_result")
            return (
                result == VerificationResult.CEX
                or result == VerificationResult.CEX.value
            )

        def is_error(result):
            if isinstance(result, dict):
                result = result.get("verification_result")
            return (
                result == VerificationResult.ERROR
                or result == VerificationResult.ERROR.value
            )

        return {
            "correct": (is_proven(lemma_entry["1-inductive"]))
            or (
                is_proven(lemma_entry["correct"])
                and not is_cex(lemma_entry["1-inductive"])
            ),
            "1-inductive": is_proven(lemma_entry["1-inductive"]),
            "1-inductive with property": is_proven(
                lemma_entry["1-inductive with property"]
            ),
            "error": is_error(lemma_entry["correct"]),
        }

    @staticmethod
    def solves(lemma_specs: Union[dict[str, str], dict[str, dict]], **kwargs) -> bool:
        if not isinstance(lemma_specs, dict):
            raise ValueError(f"Expected dict, got {type(lemma_specs)}")
        bools = LemmaEvaluator.translate_entry_to_booleans(lemma_specs)
        return bools["1-inductive with property"]

    def _get_all_verification_results(self, lemmas: Union[str, List[str]]) -> dict:
        lemmas = make_list(lemmas)
        res = {
            "lemma": lemmas,
            "correct": self.is_correct(lemmas),
            "1-inductive": self.is_one_inductive(lemmas),
            "implies": {"verification_result": VerificationResult.UNCACHED, "time": -1},
            "implied": {"verification_result": VerificationResult.UNCACHED, "time": -1},
            "1-inductive with property": self.is_one_inductive_with_property(lemmas),
        }

        return res

    def get_singleton_entries(self, lemmas: Union[str, List[str]]) -> List[dict]:
        return [lemma for lemma in lemmas if len(lemma["lemma"]) == 1]

    def evaluate_subsets(self, lemmas: Union[str, List[str]]) -> List:
        if isinstance(lemmas, str):
            lemmas = [lemmas]

        singleton_entries = [
            self._get_all_verification_results(lemma) for lemma in lemmas
        ]
        start_t = time.perf_counter()
        if self.only_singletons:
            return singleton_entries

        results = copy.deepcopy(singleton_entries)
        booleans = [
            self.translate_entry_to_booleans(entry) for entry in singleton_entries
        ]

        if any([self.solves(entry) for entry in singleton_entries]):
            return results

        correct_pairs = [
            (singleton_entries[i], booleans[i])
            for i in range(len(lemmas))
            if booleans[i].get("correct", False)
        ]

        sorted_correct_pairs = sorted(
            correct_pairs,
            key=lambda x: (
                not x[1]["1-inductive"],
                self._extract_lemma_body(x[0]["lemma"][0]),
            ),
        )
        sorted_correct_lemmas = [scp[0]["lemma"][0] for scp in sorted_correct_pairs]
        end_t = time.perf_counter()
        logger = logging.getLogger(__name__)
        logger.info(
            f"Extra overhead in evaluate_subsets for module {self.module.module_name} is {end_t - start_t} seconds"
        )

        for i in range(1, len(sorted_correct_lemmas) + 1):
            prefix = sorted_correct_lemmas[:i]
            res = self._get_all_verification_results(prefix)
            results.append(res)
            if self.solves(res):
                break

        return results

    def _cache_result(self, lemmas: list, mode: str, res: dict, engine: str):
        if self.cache_read_only:
            raise RuntimeError("Cannot write to a read-only evaluation cache")
        cache_key = self._hash_query(lemmas, mode, engine)
        assert res["verification_result"] != VerificationResult.UNCACHED
        if not cache_key:
            return
        self.cache[cache_key] = res

    def _get_from_cache(self, lemmas: list, mode: str, engine="all", tool=None):
        cache_key = self._hash_query(lemmas, mode, engine, tool)
        if not cache_key or cache_key not in self.cache:
            return
        try:
            cached_dict = self.cache[cache_key]
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Cache retrieval error for key {cache_key}: {e}")
            return
        return cached_dict

    def rename_lemmas(self, lemmas: List):
        for i in range(len(lemmas)):
            new_name = f"lemma_{self.module.num_lemmas + i}"
            lemmas[i] = re.sub(r"(property\s+).*?;", rf"\1{new_name};", lemmas[i])

        self.module.num_lemmas += len(lemmas)

    def is_property_construct(self, lemma):
        pattern = r"^\s*property\s+.*;\s+.*;\s+endproperty\s*$"
        return bool(re.match(pattern, lemma, flags=re.DOTALL))

    def _strip_unused_trace(self, res, trace):
        """Return a copy of `res` without the CEX trace `info` when `trace=False`.
        Cached entries are kept intact; this only affects what callers receive.
        """
        if trace or not isinstance(res, dict):
            return res
        if res.get("verification_result") != VerificationResult.CEX:
            return res
        if "info" not in res:
            return res
        stripped = {k: v for k, v in res.items() if k != "info"}
        return stripped

    def process_lemmas(
        self, lemmas, mode, engine="all", trace=False, keep_previous_lemmas=False
    ):
        """
        Creates a suitable sv and tcl files for the lemma with the given mode and runs JasperGold on them.
        Args:
            lemma (str): The lemma to add to the sv file.
            mode (str): one of: correctness, one_induction, one_inductive_with_prop, debug
        """
        assert len(lemmas) or mode == "debug" or mode == "debug_buechi"
        if False in [self.is_property_construct(lemma) for lemma in lemmas]:
            return {
                "verification_result": VerificationResult.ERROR,
                "time": 0,
                "info": "Not all lemmas are valid property constructs.",
                "malformed": True,
            }

        logger = logging.getLogger(__name__)
        if not keep_previous_lemmas:
            self.module.clear_lemmas()

        if self.cache_mode != CacheMode.NO_CACHE:
            full_res = self._get_from_cache(lemmas, mode, engine)
            if full_res is not None:
                res = full_res["verification_result"]
                if (
                    (
                        res != VerificationResult.TIMEOUT
                        and res != VerificationResult.ERROR
                    )
                    or self.cache_mode == CacheMode.CACHE_LENIENT
                    or self.cache_mode == CacheMode.FORCE_CACHED
                ):
                    logger.info(
                        f"Evaluated lemmas for module {self.module.module_name} in {full_res['time']} seconds"
                    )
                    return self._strip_unused_trace(full_res, trace)

            elif self.cache_mode == CacheMode.FORCE_CACHED:
                if self.fail_on_cache_miss:
                    raise RuntimeError(
                        "Evaluation cache miss for "
                        f"module={self.module.module_name} mode={mode} "
                        f"engine={engine}"
                    )
                return {
                    "verification_result": VerificationResult.UNCACHED,
                    "time": float("inf"),
                }

        lemmas_copy = copy.deepcopy(
            lemmas
        )  # there was a bug without it in the case that the property construct is incorrect and the lemma's body could not be extracted, so the whole lemma construct was cached.
        self.rename_lemmas(lemmas_copy)

        base_name = os.path.splitext(os.path.basename(self.module.filepath))[0]
        temp_lemmas_path = os.path.join(
            os.path.dirname(self.module.filepath), "temp_lemmas"
        )
        os.makedirs(temp_lemmas_path, exist_ok=True)
        properties_name_string = self.module.get_names_string(lemmas_copy)

        new_tcl_path = os.path.join(
            temp_lemmas_path,
            f"{base_name}.temp_{properties_name_string}_{mode}_{self.module.module_name}_{engine}.tcl",
        )
        new_file_path = os.path.join(
            temp_lemmas_path,
            f"{base_name}.temp_{properties_name_string}_{mode}_{self.module.module_name}.sv",
        )

        self.module.insert_lemmas_description(lemmas_copy)
        try:
            self.module.insert_directive_for_properties(
                lemmas_copy, mode=mode, new_file_path=new_file_path
            )
            max_depth = max(
                [self.get_property_depth(lemma) for lemma in lemmas_copy]
                + [self.get_property_depth(self.module.get_property)]
            )

            if self.tool == "jg":
                res = self.run_jg(new_tcl_path)

            elif self.tool == "ebmc":
                res = self.run_ebmc(
                    new_file_path, depth=max_depth, mode=mode, trace=True
                )
                logger.info(
                    f"Evaluated lemmas for module {self.module.module_name} in {res['time']} seconds"
                )

            if self.cache_result:
                self._cache_result(lemmas, mode, res, engine)
        finally:
            for f_path in [new_tcl_path, new_file_path]:
                self.remove_temp_file(f_path)

        return self._strip_unused_trace(res, trace)

    def get_property_depth(self, property: str):
        return 100

    def is_one_inductive(self, lemma):
        if self.tool != "ebmc":
            assert self.cache_mode == CacheMode.FORCE_CACHED

        res = self.process_lemmas(lemmas=make_list(lemma), mode="one_induction")
        if res["verification_result"] != VerificationResult.ERROR:
            return res
        return self.process_lemmas(lemmas=make_list(lemma), mode="one_induction_buechi")

    def is_one_inductive_with_property(self, lemma):
        if self.tool != "ebmc":
            assert self.cache_mode == CacheMode.FORCE_CACHED

        res_no_buechi = self.process_lemmas(
            lemmas=make_list(lemma), mode="one_inductive_with_prop"
        )
        if res_no_buechi["verification_result"] != VerificationResult.ERROR:
            return res_no_buechi
        return self.process_lemmas(
            lemmas=make_list(lemma), mode="one_inductive_with_prop_buechi"
        )

    def remove_temp_file(self, file_path):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

    def debug(self):
        """Runs the property alone (no lemmas) to collect baseline info."""
        res_no_buechi = self.process_lemmas([], mode="debug")
        if res_no_buechi["verification_result"] != VerificationResult.ERROR:
            return res_no_buechi
        return self.process_lemmas([], mode="debug_buechi")

    def is_correct(self, lemma, trace=False):
        res_ebmc_bounded = self.process_lemmas(
            make_list(lemma), "correctness_bounded", trace=trace
        )

        if self.skip_correctness:
            return {"verification_result": VerificationResult.UNCACHED, "time": -1}

        return res_ebmc_bounded

    def run_jg(self, tcl_file_path, timeout):
        subprocess.run("rm -rf jgproject", shell=True)
        command = f"jg -batch {tcl_file_path}"
        try:
            start = time.perf_counter()
            res = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=timeout,
                shell=True,
            )
            end = time.perf_counter()
        except subprocess.TimeoutExpired:
            return {"verification_result": VerificationResult.TIMEOUT, "time": timeout}
        except Exception:
            return {
                "verification_result": VerificationResult.ERROR,
                "time": float("inf"),
            }

        if any("ERROR" in line for line in res.stdout.splitlines()):
            return {
                "verification_result": VerificationResult.ERROR,
                "time": float("inf"),
            }

        return self.extract_jg_res(res.stdout.splitlines(), time=end - start)

    def extract_jg_res(self, output_log, time=0):
        proven = any("- proven" in line and "1 (100%)" in line for line in output_log)
        res = VerificationResult.PROVEN if proven else VerificationResult.CEX

        ipf057_pattern = r'^INFO \(IPF057\):.*The property ".*\._assert_.*" was proven in ([\d.]+) s\.'
        ipf055_pattern = (
            r'^INFO \(IPF055\):.*for the property ".*\._assert_.*" in ([\d.]+) s\.'
        )
        ipf057_code_line = [
            line for line in output_log if re.match(ipf057_pattern, line)
        ]
        ipf055_code_line = [
            line for line in output_log if re.match(ipf055_pattern, line)
        ]

        assert len(ipf057_code_line) + len(ipf055_code_line) == 1

        matched_line = (ipf057_code_line + ipf055_code_line)[0]
        match = re.search(r"in ([\d.]+) s\.", matched_line)
        assert match, "Couldn't find the time in the matched line"

        run_time_seconds = float(match.group(1))
        return {
            "verification_result": res,
            "time_internal": run_time_seconds,
            "time_external": time,
        }

    def extract_trace(self, ebmc_output):
        match = re.search(
            r"Counterexample:\s*\n(?:\s*\n)*(.+?)(?:\Z)", ebmc_output, re.DOTALL
        )
        return match.group(1).strip() if match else ""

    def extract_error_message(self, ebmc_output):
        match = re.search(r"line \d+: (.*)", ebmc_output, re.DOTALL)
        if match:
            return match.group(1)

        return ""

    def run_ebmc(self, sv_file_path, mode, depth=BMC_BOUND, trace=False):
        """Runs EBMC on the given Verilog file and returns True if it passes verification.
        Arguments:
        mode - one of "one_induction", "correctness", "correctness_bounded", "k_induction"
        """

        command = ""
        match mode:
            case "correctness":
                command = f"ebmc {sv_file_path}"

            case "one_induction" | "one_inductive_with_prop" | "debug":
                command = f"ebmc {sv_file_path} --k-induction --bound 1"

            case (
                "one_induction_buechi"
                | "one_inductive_with_prop_buechi"
                | "debug_buechi"
            ):
                command = f"ebmc {sv_file_path} --k-induction --buechi --bound 1"

            case "correctness_bounded":
                command = f"ebmc {sv_file_path} --bound {EBMC_BMC_BOUND}"

            case "k_induction":
                command = (
                    f"ebmc {sv_file_path} --k-induction --bound {EBMC_K_FOR_INDUCTION}"
                )

            case "k_induction_buechi":
                command = f"ebmc {sv_file_path} --k-induction --buechi --bound {EBMC_K_FOR_INDUCTION}"

            case "timing_with_lemmas" | "timing_without_lemmas":
                command = f"ebmc {sv_file_path} --bound 30"

        if self.module.rst_exists:
            command += f" --reset rst"

        command += f" --trace "

        try:
            start = time.perf_counter()
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=True,
                errors="replace",
            )
            end = time.perf_counter()
        except subprocess.TimeoutExpired as e:
            return {
                "verification_result": VerificationResult.TIMEOUT,
                "time": e.timeout,
            }

        pattern = r"^\*\* Results:.* PROVED\s*$" if mode == "correctness" else "PROVED"

        if re.search(pattern, result.stdout, re.DOTALL | re.MULTILINE):
            return {
                "verification_result": VerificationResult.PROVEN,
                "time": end - start,
            }

        if "REFUTED" in result.stdout or "INCONCLUSIVE" in result.stdout:
            if "REFUTED" in result.stdout:
                cex_trace = self.extract_trace(result.stdout)
                if cex_trace:
                    return {
                        "verification_result": VerificationResult.CEX,
                        "time": end - start,
                        "info": cex_trace,
                    }
                return {
                    "verification_result": VerificationResult.CEX,
                    "time": end - start,
                    "info": "No trace extracted",
                }
            return {
                "verification_result": VerificationResult.INCONCLUSIVE,
                "time": end - start,
            }

        if "FAILURE:" in result.stdout or "Assertion failure" in result.stdout:
            error_message = self.extract_error_message(result.stdout)
            return {
                "verification_result": VerificationResult.ERROR,
                "time": end - start,
                "info": error_message,
            }

        if result.stderr != "":
            return {
                "verification_result": VerificationResult.ERROR,
                "time": end - start,
                "info": result.stderr,
            }

        if re.search(
            r"^\*\* Results:.*PROVED up to bound.*",
            result.stdout,
            re.MULTILINE | re.DOTALL,
        ):
            return {
                "verification_result": VerificationResult.TIMEOUT,
                "time": end - start,
            }

        return {"verification_result": VerificationResult.TIMEOUT, "time": end - start}
