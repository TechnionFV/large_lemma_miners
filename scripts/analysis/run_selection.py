"""Unified run-selection policy for analysis scripts.

`RunSelection` is one object that tells `collect_summary_files` (and its
sibling `discover_aggregate_summary_files`) which Run_Directories to
consider and which summary file(s) inside each to read.

The canonical `runs.json` used by every analysis downstream is generated
with the "all" policy: include every `(num_iterations, num_samples)`
combination present on disk. Each table builder then filters the
resulting dict to the specific num_iterations / ns values it cares about (paper
tables pin K=5, ns=5; ablations sweep).

    # canonical all-inclusive selection for runs.json
    RunSelection(
        agent_num_iterations="all",
        non_agent_num_samples="all",
        fewshots=[0, 1, 2],
        experiments=["main_experiment", "hard"],
        models=PAPER_MODEL_SHORTS,    # excludes gpt-4o
    )

    # legacy per-ablation selection — still supported for callers that
    # want to narrow the scan at the source
    RunSelection(
        agent_num_iterations="exact", agent_num_iterations_value=5,
        non_agent_num_samples="exact", non_agent_num_samples_value=5,
        ...
    )

See Requirement 13 and Design §5.9 for the rationale.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

Experiment = Literal["main_experiment", "hard"]
ParsedKey = tuple[str, int, str]  # (model, fewshot, experiment)


@dataclass(frozen=True)
class RunSelection:
    """Which Run_Directories and which summary files feed a given analysis.

    The `*_num_iterations` / `*_num_samples` fields accept one of three modes:
      - "all"          : keep every value present on disk. Use this for the
                         canonical runs.json generation so the downstream
                         table builders can filter independently.
      - "exact"        : keep a single specific value (requires the `_value`
                         field to be set).
      - "max_available": per (model, fewshot, experiment) group, keep only
                         the record with the largest value.

    Paper-table code should not rely on a specific selection to pin K=5 /
    ns=5 anymore; the filtering happens inside each table builder.
    """

    # Agentic pipeline: number of iterations of the LLM-verifier loop.
    agent_num_iterations: Literal["all", "max_available", "exact"] = "all"
    agent_num_iterations_value: int | None = None  # required iff mode == "exact"

    # Non-agentic pipeline: number of LLM response samples aggregated.
    non_agent_num_samples: Literal["all", "max_available", "exact"] = "all"
    non_agent_num_samples_value: int | None = None  # required iff mode == "exact"

    # Few-shot k ∈ {0, 1, 2}. None = all present.
    fewshots: list[int] | None = None

    # Which experiment subdirectories to scan.
    experiments: list[Experiment] = field(
        default_factory=lambda: ["main_experiment", "hard"]
    )

    # Allowed short model names. None = all present.
    # For paper tables, set to the six paper models (excludes gpt-4o).
    models: list[str] | None = None

    def __post_init__(self) -> None:
        if (
            self.agent_num_iterations == "exact"
            and self.agent_num_iterations_value is None
        ):
            raise ValueError(
                "RunSelection: agent_num_iterations='exact' requires "
                "agent_num_iterations_value to be set."
            )
        if (
            self.non_agent_num_samples == "exact"
            and self.non_agent_num_samples_value is None
        ):
            raise ValueError(
                "RunSelection: non_agent_num_samples='exact' requires "
                "non_agent_num_samples_value to be set."
            )
        if self.fewshots is not None and any(fs < 0 for fs in self.fewshots):
            raise ValueError(
                f"RunSelection: fewshots must be non-negative, got {self.fewshots!r}"
            )

    # ----- Small helpers used by the file enumerators -----

    def fewshot_allowed(self, fs: int) -> bool:
        return self.fewshots is None or fs in self.fewshots

    def model_allowed(self, model_short: str) -> bool:
        return self.models is None or model_short in self.models

    def agent_num_iterations_allowed(self, n: int) -> bool:
        """True iff `n` is permitted by the agent_num_iterations policy.

        "all" always True.
        "exact" True iff `n == value`.
        "max_available" always True here (the actual single-max collapse
        happens in `select_by_policy` after grouping).
        """
        if self.agent_num_iterations == "exact":
            return n == self.agent_num_iterations_value
        return True

    def non_agent_num_samples_allowed(self, n: int) -> bool:
        """True iff `n` is permitted by the non_agent_num_samples policy."""
        if self.non_agent_num_samples == "exact":
            return n == self.non_agent_num_samples_value
        return True


def select_by_policy(
    parsed_files: list[dict[str, Any]],
    *,
    mode: Literal["all", "max_available", "exact"],
    value: int | None,
    key: str,
) -> list[dict[str, Any]]:
    """Apply the selection policy to a list of parsed summary-file records.

    Each record is a dict with at least the keys:
        model     : short model name
        fewshot   : int
        experiment: str
        <key>     : int (the run parameter; `num_iterations` or `ns`)

    Semantics:
      - "all":           keep every record (no collapse).
      - "exact":         keep records whose <key> equals `value`.
      - "max_available": per (model, fewshot, experiment) group, keep one
                         record — the one with the largest <key>.

    Input ordering does not affect output contents; output is sorted by
    (experiment, model, fewshot, key) for determinism.
    """
    if mode == "all":
        picked = list(parsed_files)
    elif mode == "exact":
        picked = [p for p in parsed_files if p[key] == value]
    elif mode == "max_available":
        groups: dict[ParsedKey, list[dict[str, Any]]] = defaultdict(list)
        for p in parsed_files:
            groups[(p["model"], p["fewshot"], p["experiment"])].append(p)
        picked = [max(grp, key=lambda p: p[key]) for grp in groups.values() if grp]
    else:
        raise ValueError(f"Unknown mode {mode!r}")

    return sorted(
        picked, key=lambda p: (p["experiment"], p["model"], p["fewshot"], p[key])
    )
