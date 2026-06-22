"""Shared primitives for the runs-based analysis pipeline.

Exposes:
  - Regexes for log-line parsing and filename matching
  - `_short_model`: maps full model IDs (e.g. `us.anthropic.claude-opus-4-5-...`)
    to the short names used in Paper_Tables (e.g. `claude-4-5-opus`).
  - `norm_module_key` / `strip_ext`: canonical module-name keys.
  - `load_book_keeping`: tag lookup + per-tag totals from `book_keeping.json`.
  - `collect_summary_files`: per-module summary enumerator driven by
    `RunSelection` (see `scripts/analysis/run_selection.py`).
  - `extract_{agentic,non_agentic}_statuses`: readers for the per-module
    summary JSONs.

After task 7d (runs.json migration) the legacy log-enumerator and
normalizer helpers (`collect_logs_from_exp_root`, `parse_setting_from_filename`,
`normalize_{agentic,nonagentic}_stats`, `load_tag_map`, `ensure_sv_name`)
are gone; `runs_builder.build_runs_json` is the only consumer of the
per-(module, run) view.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from itertools import chain
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .run_selection import RunSelection, select_by_policy


# =========================
# Regexes
# =========================

# Log-line extractors (used by runs_builder._parse_log_timings).
INF_RE = re.compile(
    r"Module:\s+(\S+)\s+Inference time for sampled responses:\s+([0-9.]+)"
)
EVAL_RE = re.compile(r"Evaluated lemmas for module\s+(\S+)\s+in\s+([0-9.]+)\s+seconds")
EVAL_SUBSETS_RE = re.compile(
    r"Extra overhead in evaluate_subsets for module (\S+) is ([\d.]+) seconds"
)
TOK_RE = re.compile(
    r"Module:\s+(\S+)\s+Total tokens for sampled responses:\s+([0-9]+(?:\.[0-9]+)?)"
)

# Per-module summary filenames (used by collect_summary_files).
_SUMMARY_AGENTIC_RE = re.compile(
    r"^summary_agentic_(?P<model>.+?)_fewshot_(?P<fewshot>\d+)"
    r"_(?P<experiment>main_experiment|hard)"
    r"_num_iterations_(?P<num_iterations>\d+)\.json$"
)
_SUMMARY_NON_AGENTIC_RE = re.compile(
    r"^summary_non_agentic_(?P<model>.+?)_fewshot_(?P<fewshot>\d+)"
    r"_(?P<experiment>main_experiment|hard)"
    r"_ns(?P<ns>\d+)\.json$"
)

# Aggregate summary filenames (used by runs_builder._discover_aggregate_files).
AGENTIC_RE = re.compile(
    r"^summary_aggregate_agentic_"
    r"(?P<model>.+?)_fewshot_(?P<fewshot>\d+)_"
    r"(?P<experiment>main_experiment|hard)_num_iterations_(?P<num_iterations>\d+)\.json$"
)
NONAGENTIC_RE = re.compile(
    r"^summary_aggregate_non_agentic_(?P<model>.+?)_fewshot_(?P<fewshot>\d+)"
    r"_(?P<experiment>main_experiment|hard)_ns(?P<ns>\d+)\.json$"
)


# =========================
# Module-name keys
# =========================


def strip_ext(name: str) -> str:
    base = os.path.basename(name)
    for suffix in (
        "_ebmc.sv",
        "_jasper.sv",
        "_ric3.sv",
        ".sv",
        "_ebmc",
        "_jasper",
        "_ric3",
        "_jasper.aig.out",
    ):
        if base.lower().endswith(suffix):
            return base[: -len(suffix)]
    for suffix in (".sv", ".v", ".svh", ".sva"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def norm_module_key(name: str) -> str:
    """Normalize to a stable module key (strip path and common HDL extensions)."""
    return strip_ext(name)


# =========================
# JSON I/O
# =========================


def read_json(path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# Short model names
# =========================


def _short_model(model: str) -> str:
    """Map a full model ID (anywhere in the input string) to a short name.

    Short names are what appear in Run_Directory names, paper tables, and the
    `PAPER_MODEL_SHORTS` list in `src/models.py`. This function is the
    inverse of `src.models.MODEL_SHORT_TO_FULL` applied substring-wise (the
    input may be embedded in a longer filename).
    """
    model = model.lower()
    # Order matters: the more-specific patterns (4-5-*, 4-7-*) must come before
    # the less-specific `claude-sonnet-4`.
    if "claude-haiku-4-5" in model or "claude-4-5-haiku" in model:
        return "claude-4-5-haiku"
    if "claude-sonnet-4-5" in model or "claude-4-5-sonnet" in model:
        return "claude-4-5-sonnet"
    if "claude-opus-4-5" in model or "claude-4-5-opus" in model:
        return "claude-4-5-opus"
    if "claude-opus-4-7" in model or "claude-4-7-opus" in model:
        return "claude-4-7-opus"
    if "claude-sonnet-4" in model:
        # Upstream Run_Directory naming uses `claude-4` (not `claude-4-sonnet`)
        # for the 2025-05-14 Sonnet release. Keep single source of truth with
        # src/models.py.
        return "claude-4"
    if "claude-3-7" in model:
        return "claude-3-7"
    if "claude" in model:
        m = re.search(r"claude[-_]?\d+[-_]?\d*", model)
        return m.group(0).replace("_", "-") if m else "claude"
    if "gpt-5" in model:
        return "gpt-5"
    if "gpt-4" in model:
        return "gpt-4o"
    return model.split("-")[0]


# =========================
# Book-keeping loader
# =========================


def load_book_keeping(path: str) -> Tuple[Dict[str, str], Dict[str, int]]:
    """Return (module_base -> group_tag, group_tag -> count).

    Count totals exclude entries with a `deleted` field.
    """
    data = read_json(path)
    mapping: Dict[str, str] = {}
    tag_totals: Dict[str, int] = defaultdict(int)

    for entry in data.get("modules", []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("module_name")
        if not name:
            continue
        tag_clean = entry.get("group_tag") or "UNKNOWN"
        mapping[strip_ext(name)] = tag_clean
        if "deleted" not in entry:
            tag_totals[tag_clean] += 1

    return mapping, dict(tag_totals)


# =========================
# Per-module summary statuses
# =========================


def extract_non_agentic_statuses(payload: dict) -> Dict[str, bool]:
    """Return `{module_base: solved_bool}` from a non-agentic per-module summary.

    Non-agentic's "Solved" criterion is the `solved with both` flag (i.e. both
    the full-lemma-set and the 1-inductive-subset checks pass). See task 7c.16
    for the note on how this differs from agentic's "Solved".
    """
    out = {}
    for mod_key, stats in payload.get("modules", {}).items():
        solved_val = False
        if isinstance(stats, dict):
            for k in [
                "solved with both",
                "is solved for both",
                "solved_with_both",
                "both_solved",
            ]:
                if k in stats:
                    solved_val = bool(stats[k])
                    break
        out[strip_ext(mod_key)] = solved_val
    return out


def extract_agentic_statuses(payload: dict) -> Dict[str, bool]:
    """Return `{module_base: solved_bool}` from an agentic per-module summary.

    Agentic "Solved" comes from the single `solved` field on each module;
    a module is solved if any iteration of the verifier loop proved the
    property from the lemmas the agent proposed.
    """
    out = {}
    for mod_key, stats in payload.get("modules", {}).items():
        if isinstance(stats, dict):
            out[strip_ext(mod_key)] = bool(stats.get("solved", 0))
    return out


# =========================
# File enumerator (RunSelection-driven)
# =========================


def collect_summary_files(
    roots: List[str], selection: "RunSelection"
) -> List[Dict[str, str]]:
    """Find per-module summary JSONs under each `<root>/<run_dir>/results/summaries/`.

    Returns a list of records `{"id": "<short_model>_<pipeline>", "path": ...,
    "model", "fewshot", "experiment", "num_iterations" | "ns"}`. The policy
    in `selection` decides which combinations contribute.
    """
    parsed_agentic: list[dict] = []
    parsed_non_agentic: list[dict] = []

    all_experiments = chain.from_iterable(
        ((root, run_dir_name) for run_dir_name in os.listdir(root)) for root in roots
    )

    for root, run_dir_name in all_experiments:
        summaries = os.path.join(root, run_dir_name, "results", "summaries")
        if not os.path.isdir(summaries):
            continue

        for fname in os.listdir(summaries):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(summaries, fname)

            m = _SUMMARY_AGENTIC_RE.match(fname)
            if m:
                model_full = m.group("model")
                model_short = _short_model(model_full)
                experiment = m.group("experiment")
                fs = int(m.group("fewshot"))
                it = int(m.group("num_iterations"))
                if experiment not in selection.experiments:
                    continue
                if not selection.fewshot_allowed(fs):
                    continue
                if not selection.model_allowed(model_short):
                    continue
                parsed_agentic.append(
                    {
                        "id": f"{model_short}_agentic",
                        "path": path,
                        "model": model_short,
                        "fewshot": fs,
                        "experiment": experiment,
                        "num_iterations": it,
                    }
                )
                continue

            m = _SUMMARY_NON_AGENTIC_RE.match(fname)
            if m:
                model_full = m.group("model")
                model_short = _short_model(model_full)
                experiment = m.group("experiment")
                fs = int(m.group("fewshot"))
                ns = int(m.group("ns"))
                if experiment not in selection.experiments:
                    continue
                if not selection.fewshot_allowed(fs):
                    continue
                if not selection.model_allowed(model_short):
                    continue
                parsed_non_agentic.append(
                    {
                        "id": f"{model_short}_non_agentic",
                        "path": path,
                        "model": model_short,
                        "fewshot": fs,
                        "experiment": experiment,
                        "ns": ns,
                    }
                )

    selected_agentic = select_by_policy(
        parsed_agentic,
        mode=selection.agent_num_iterations,
        value=selection.agent_num_iterations_value,
        key="num_iterations",
    )
    selected_non_agentic = select_by_policy(
        parsed_non_agentic,
        mode=selection.non_agent_num_samples,
        value=selection.non_agent_num_samples_value,
        key="ns",
    )

    return selected_agentic + selected_non_agentic
