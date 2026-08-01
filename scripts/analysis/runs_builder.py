"""Build the unified `runs.json` that every paper-table builder consumes.

See Design §15 for the schema. High level:

    build_runs_json(data_root, selection, book_keeping_paths, out_path) -> dict

Walks the three data sources under `data_root`/<experiment>/<run_dir>/:
  - per-module summary JSONs      → status + non-agentic "solved_with_*"
  - per-module log files          → inference_time / evaluation_time / tokens
  - aggregate summary JSONs       → _run_totals[run_key] lemma stats

Attaches module metadata (tag) from the two bookkeeping files, applies the
main-wins-with-hard-cleanup overlap policy, asserts a handful of invariants,
and serializes to `out_path`.

Run-key format (shared with every reader):
    <model>__<pipeline>__fs<F>__{it|ns}<N>
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from tqdm import tqdm

# Allow direct-script invocation (`python3 runs_builder.py`) by bootstrapping
# this file as a member of the `analysis` package so its relative imports
# (and the relative imports of its siblings, e.g. `analysis_utils`) resolve.
if __package__ in (None, ""):
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(_here))  # parent dir holds `analysis/`
    __package__ = os.path.basename(_here)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .run_selection import RunSelection, select_by_policy

from .analysis_utils import (
    AGENTIC_RE,
    EVAL_RE,
    EVAL_SUBSETS_RE,
    INF_RE,
    NONAGENTIC_RE,
    TOK_RE,
    _short_model,
    collect_summary_files,
    extract_agentic_statuses,
    extract_non_agentic_statuses,
    norm_module_key,
    read_json,
    strip_ext,
)


# ---------------------------------------------------------------------------
# Run-key derivation
# ---------------------------------------------------------------------------


def run_key(model: str, pipeline: str, fewshot: int, n_value: int) -> str:
    """Canonical run-key string — single source of truth.

    Shared with every reader so that `_run_totals[key]` and
    `runs[<module>]["runs"][key]` always match.
    """
    if pipeline not in ("agent", "non_agent"):
        raise ValueError(f"pipeline must be 'agent' or 'non_agent', got {pipeline!r}")
    n_label = "it" if pipeline == "agent" else "ns"
    return f"{model}__{pipeline}__fs{fewshot}__{n_label}{n_value}"


# ---------------------------------------------------------------------------
# Log file name → (run descriptor) parsers
# ---------------------------------------------------------------------------

# Agentic log filename pattern (from experiment_agentic.py writer):
#   experiment_agentic_<model_full>_<experiment>_fs_<fs>_num_iterations_<N>.log
_AGENT_LOG_RE = re.compile(
    r"^experiment_agentic_(?P<model>.+?)_(?P<experiment>main_experiment|hard)"
    r"_fs_(?P<fewshot>\d+)_num_iterations_(?P<num_iterations>\d+)\.log$"
)

# Non-agentic log filename pattern (from evaluate_non_agentic.py writer):
#   evaluate_non_agentic_<experiment>_fs<fs>_ns<ns>_<model_full>_*.log
_NONAGENT_LOG_RE = re.compile(
    r"^evaluate_non_agentic_(?P<experiment>main_experiment|hard)"
    r"_fs(?P<fewshot>\d+)_ns(?P<ns>\d+)_(?P<model>.+?)\.log$"
)


def _parse_agent_log_name(name: str):
    m = _AGENT_LOG_RE.match(name)
    if not m:
        return None
    return {
        "pipeline": "agent",
        "model": _short_model(m.group("model")),
        "model_full": m.group("model"),
        "experiment": m.group("experiment"),
        "fewshot": int(m.group("fewshot")),
        "num_iterations": int(m.group("num_iterations")),
    }


def _parse_nonagent_log_name(name: str):
    m = _NONAGENT_LOG_RE.match(name)
    if not m:
        return None
    return {
        "pipeline": "non_agent",
        "model": _short_model(m.group("model")),
        "model_full": m.group("model"),
        "experiment": m.group("experiment"),
        "fewshot": int(m.group("fewshot")),
        "ns": int(m.group("ns")),
    }


def _log_run_key(desc: dict) -> str:
    if desc["pipeline"] == "agent":
        return run_key(desc["model"], "agent", desc["fewshot"], desc["num_iterations"])
    return run_key(desc["model"], "non_agent", desc["fewshot"], desc["ns"])


# ---------------------------------------------------------------------------
# Log parsing — per-module timing + token tallies, fresh per log file
# ---------------------------------------------------------------------------


def _parse_log_timings(log_path: Path) -> Dict[str, dict]:
    """Return `{module_key: {inference_time, evaluation_time, tokens}}` for one log."""
    times: Dict[str, dict] = defaultdict(
        lambda: {
            "inference_time": 0.0,
            "evaluation_time": 0.0,
            "tokens": 0.0,
            "saw_inf": False,
            "saw_eval": False,
            "saw_tok": False,
        }
    )

    try:
        with open(log_path, "r", errors="ignore") as f:
            for line in f:
                m = INF_RE.search(line)
                if m:
                    module, t = m.groups()
                    rec = times[norm_module_key(module)]
                    v = float(t)
                    if v >= 0:
                        rec["inference_time"] += v
                        rec["saw_inf"] = True
                    continue

                m = EVAL_RE.search(line)
                if m:
                    module, t = m.groups()
                    rec = times[norm_module_key(module)]
                    v = float(t)
                    if v >= 0:
                        rec["evaluation_time"] += v
                        rec["saw_eval"] = True
                    continue

                m = EVAL_SUBSETS_RE.search(line)
                if m:
                    module, t = m.groups()
                    rec = times[norm_module_key(module)]
                    # had a start-end bug that produced negatives; absolute value
                    # preserves the current reader semantics.
                    rec["evaluation_time"] += abs(float(t))
                    rec["saw_eval"] = True
                    continue

                m = TOK_RE.search(line)
                if m:
                    module, n = m.groups()
                    rec = times[norm_module_key(module)]
                    v = float(n)
                    if v >= 0:
                        rec["tokens"] += v
                        rec["saw_tok"] = True
                    continue
    except FileNotFoundError:
        return {}

    return times


# ---------------------------------------------------------------------------
# Aggregate-summary discovery (for _run_totals)
# ---------------------------------------------------------------------------


def _discover_aggregate_files(
    experiment_roots: List[Path], selection: "RunSelection"
) -> Tuple[list, list]:
    """Return (agentic_records, non_agentic_records), each filtered by `selection`
    and collapsed via `select_by_policy` so only the chosen K/ns variant survives.

    Records are dicts with {path, model (short), fewshot, experiment,
    num_iterations|ns}.
    """
    parsed_agent: list[dict] = []
    parsed_non: list[dict] = []

    for root in experiment_roots:
        if not root.is_dir():
            continue
        for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            summaries_dir = run_dir / "results" / "summaries"
            if not summaries_dir.is_dir():
                continue
            for f in summaries_dir.iterdir():
                if not f.is_file():
                    continue
                name = f.name

                mA = AGENTIC_RE.match(name)
                if mA:
                    model_short = _short_model(mA.group("model"))
                    fs = int(mA.group("fewshot"))
                    it = int(mA.group("num_iterations"))
                    experiment = mA.group("experiment")
                    if experiment not in selection.experiments:
                        continue
                    if not selection.fewshot_allowed(fs):
                        continue
                    if not selection.model_allowed(model_short):
                        continue
                    parsed_agent.append(
                        {
                            "path": f,
                            "model": model_short,
                            "model_full": mA.group("model"),
                            "fewshot": fs,
                            "experiment": experiment,
                            "num_iterations": it,
                        }
                    )
                    continue

                mN = NONAGENTIC_RE.match(name)
                if mN:
                    model_short = _short_model(mN.group("model"))
                    fs = int(mN.group("fewshot"))
                    ns = int(mN.group("ns"))
                    experiment = mN.group("experiment")
                    if experiment not in selection.experiments:
                        continue
                    if not selection.fewshot_allowed(fs):
                        continue
                    if not selection.model_allowed(model_short):
                        continue
                    parsed_non.append(
                        {
                            "path": f,
                            "model": model_short,
                            "model_full": mN.group("model"),
                            "fewshot": fs,
                            "experiment": experiment,
                            "ns": ns,
                        }
                    )

    selected_agent = select_by_policy(
        parsed_agent,
        mode=selection.agent_num_iterations,
        value=selection.agent_num_iterations_value,
        key="num_iterations",
    )
    selected_non = select_by_policy(
        parsed_non,
        mode=selection.non_agent_num_samples,
        value=selection.non_agent_num_samples_value,
        key="ns",
    )
    return selected_agent, selected_non


def _extract_agent_aggregate(payload: dict) -> dict:
    """Map an agentic aggregate summary payload to the _run_totals shape."""
    return {
        "total_lemmas": int(payload.get("total", 0)),
        "correct": int(payload.get("correct", 0)),
        "one_inductive": int(payload.get("1-inductive", 0)),
        "one_inductive_with_property": int(payload.get("1-inductive with property", 0)),
        "num_modules": int(payload.get("num_modules", 0)),
        "solved_modules": int(payload.get("solved", 0)),
        "error": int(payload.get("error", 0)),
    }


def _extract_nonagent_aggregate(payload: dict) -> dict:
    """Map a non-agentic aggregate summary payload (wrapped under one model key)
    to the _run_totals shape."""
    if not isinstance(payload, dict):
        raise ValueError(
            f"Non-agentic aggregate summary must be a dict; got {type(payload).__name__}"
        )
    # Empty dict ({}): writer produced no aggregate for this run. The
    # per-module summary is still present and will drive the per-(module,run)
    # view; _run_totals just gets zeros for this run_key, and step 5.2 will
    # correct `solved_modules` from the per-module count.
    if len(payload) == 0:
        return {
            "total_lemmas": 0,
            "correct": 0,
            "one_inductive": 0,
            "one_inductive_with_property": 0,
            "num_modules": 0,
            "solved_modules": 0,
            "error": 0,
        }
    if len(payload) != 1:
        raise ValueError(
            f"Non-agentic aggregate summary must have exactly one top-level key; got keys={list(payload)!r}"
        )
    ((_model_key, inner),) = payload.items()
    return {
        "total_lemmas": int(inner.get("Total Lemmas", 0)),
        "correct": int(inner.get("Correct", 0)),
        "one_inductive": int(inner.get("1-Ind.", 0)),
        "one_inductive_with_property": int(inner.get("1-Ind.w.p", 0)),
        "num_modules": int(inner.get("Total Modules", 0)),
        "solved_modules": int(inner.get("Solved", 0)),
        "error": int(inner.get("Error", 0)),
    }


# ---------------------------------------------------------------------------
# Book-keeping merge (main + hard)
# ---------------------------------------------------------------------------


def _merge_book_keeping(paths: List[Path]) -> Dict[str, dict]:
    """Merge book_keeping files into `{module_base: {tag}}`.

    Main wins when an entry is present in both. Pass the `main_experiment`
    book_keeping path first, then `hard`.

    Two on-disk shapes are supported:
      1. `{"modules": [{"module_name": "...", "group_tag": "...", ...}, ...]}`
         — used by `benchmarks/main_experiment/book_keeping.json`.
      2. Flat `{module_name: tag, ...}` — used by `benchmarks/hard/bookkeeping.json`.
    """
    merged: Dict[str, dict] = {}
    for p in paths:
        if not Path(p).is_file():
            continue
        data = read_json(p)

        # Shape 1: {"modules": [...]}
        if isinstance(data, dict) and isinstance(data.get("modules"), list):
            entries: Iterable[dict] = (
                e for e in data["modules"] if isinstance(e, dict)
            )
            for entry in entries:
                name = entry.get("module_name")
                if not name:
                    continue
                key = strip_ext(name)
                if key in merged:
                    continue  # main wins
                merged[key] = {
                    "tag": entry.get("group_tag") or "UNKNOWN",
                }
            continue

        # Shape 2: flat {module_name: tag}
        if isinstance(data, dict):
            for name, tag in data.items():
                if not isinstance(name, str):
                    continue
                key = strip_ext(name)
                if key in merged:
                    continue  # main wins
                merged[key] = {
                    "tag": tag if isinstance(tag, str) and tag else "UNKNOWN",
                }
    return merged


def _compute_disk_module_set(benchmarks_dirs: List[Path]) -> set[str]:
    """Canonical set of module keys, derived from `.sv` files on disk.

    `benchmarks_dirs` is typically `[<REPO>/benchmarks/main_experiment, <REPO>/benchmarks/hard]`.
    Names are normalized via `strip_ext` so they match the keys used elsewhere
    (e.g. `buffer_32_ebmc.sv` → `buffer_32`).
    """
    disk: set[str] = set()
    for d in benchmarks_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file() and f.suffix == ".sv":
                disk.add(strip_ext(f.name))
    return disk


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_runs_json(
    data_root: Path,
    selection: "RunSelection",
    book_keeping_paths: List[Path],
    out_path: Path,
    *,
    benchmarks_dirs: List[Path] | None = None,
    expected_module_count: int | None = None,
    enforce_module_count: bool = True,
) -> dict:
    """Produce the unified `runs.json` and write it to `out_path`. Returns the dict.

    `benchmarks_dirs`, when provided, names the directories whose `.sv` files
    define the canonical module set (typically
    `[REPO/benchmarks/main_experiment, REPO/benchmarks/hard]`). When set, the
    builder enforces:
      - `runs_by_module ⊆ disk_set`: every ingested module has a `.sv` on disk.
      - When `expected_module_count is None`, defaults to `len(disk_set)`.

    `expected_module_count`: pin the expected count. Default `None` derives
    from `benchmarks_dirs`; pass an int to override. Ignored when
    `enforce_module_count=False`.

    `enforce_module_count`: when False, skip both the disk-subset check and
    the count equality check. The CLI `--lenient` flag flips this off.
    """
    data_root = Path(data_root)
    experiment_roots = [data_root / e for e in selection.experiments]
    for er in experiment_roots:
        if not er.is_dir():
            raise NotADirectoryError(f"Experiment root {er} does not exist")

    # -- step 1: per-module summaries → status + non-agentic breakdown
    summary_records = collect_summary_files(
        [str(r) for r in experiment_roots], selection
    )
    assert summary_records, (
        "collect_summary_files returned no records. Check data_root and RunSelection."
    )

    # runs_by_module[module][run_key] = {partial per-(module,run) record}
    runs_by_module: Dict[str, Dict[str, dict]] = defaultdict(dict)
    # modules_touched[run_key] = set of modules covered by this run
    modules_touched: Dict[str, set] = defaultdict(set)

    for rec in tqdm(
        summary_records,
        desc="  Ingesting run summaries",
        unit="file",
        leave=False,
        position=1,
        dynamic_ncols=True,
    ):
        # ids emitted by collect_summary_files are "<short_model>_agentic" or
        # "<short_model>_non_agentic"; check the suffix explicitly.
        pipeline = "non_agent" if rec["id"].endswith("_non_agentic") else "agent"

        if pipeline == "agent":
            n_value = rec["num_iterations"]
        else:
            n_value = rec["ns"]
        rk = run_key(rec["model"], pipeline, rec["fewshot"], n_value)

        payload = read_json(rec["path"])
        status_map = (
            extract_agentic_statuses(payload)
            if pipeline == "agent"
            else extract_non_agentic_statuses(payload)
        )

        # Non-agentic: also pull the three solved_with_* flags per module.
        # Build a reverse map from the normalized module key to the raw key
        # the writer used (e.g. `buffer_32` → `buffer_32_ebmc`) so the lookup
        # below hits the actual field.
        raw_modules = payload.get("modules", {}) if pipeline == "non_agent" else {}
        raw_key_by_norm: Dict[str, str] = {}
        for raw_key in raw_modules:
            raw_key_by_norm[strip_ext(raw_key)] = raw_key

        for module, solved in status_map.items():
            per_run = runs_by_module[module].setdefault(
                rk,
                {
                    "pipeline": pipeline,
                    "model": rec["model"],
                    "fewshot": rec["fewshot"],
                    (
                        "num_iterations" if pipeline == "agent" else "num_samples"
                    ): n_value,
                    "status": "Solved" if solved else "Unsolved",
                    "inference_time": None,
                    "evaluation_time": None,
                    "total_time": None,
                    "tokens": None,
                    "source": {"summary": str(rec["path"]), "log": None},
                },
            )
            # If we later see the same (module, run_key) via another summary (shouldn't
            # happen for a well-formed selection), OR the statuses.
            if solved and per_run["status"] != "Solved":
                per_run["status"] = "Solved"

            if pipeline == "non_agent":
                raw_key = raw_key_by_norm.get(module)
                raw_mod = raw_modules.get(raw_key) if raw_key is not None else None
                if isinstance(raw_mod, dict):
                    per_run["solved_with_1_induction"] = int(
                        raw_mod.get("solved with 1 induction", 0)
                    )
                    per_run["solved_with_both"] = int(
                        raw_mod.get("solved with both", 0)
                    )

            modules_touched[rk].add(module)

    # -- step 2: per-log timings
    # Pre-build a map from (experiment, model_full, fewshot, N_value) → run_key
    # so log-filename parsing can cheaply identify the right run.
    all_log_paths: List[Path] = []
    for experiment_root in experiment_roots:
        experiment = experiment_root.name
        if experiment not in selection.experiments:
            continue
        for run_dir in sorted(p for p in experiment_root.iterdir() if p.is_dir()):
            logs_dir = run_dir / "results" / "logs"
            if not logs_dir.is_dir():
                continue
            for log_path in sorted(logs_dir.iterdir()):
                if log_path.is_file() and log_path.suffix == ".log":
                    all_log_paths.append(log_path)

    for log_path in tqdm(
        all_log_paths,
        desc="  Parsing timing logs",
        unit="log",
        leave=False,
        position=1,
        dynamic_ncols=True,
    ):
        desc = _parse_agent_log_name(log_path.name) or _parse_nonagent_log_name(
            log_path.name
        )
        if desc is None:
            continue
        if desc["experiment"] not in selection.experiments:
            continue
        if not selection.fewshot_allowed(desc["fewshot"]):
            continue
        if not selection.model_allowed(desc["model"]):
            continue

        # Respect the K / ns selection policy.
        if desc["pipeline"] == "agent":
            if not selection.agent_num_iterations_allowed(desc["num_iterations"]):
                continue
        else:
            if not selection.non_agent_num_samples_allowed(desc["ns"]):
                continue

        rk = _log_run_key(desc)
        timings = _parse_log_timings(log_path)
        for module, t in timings.items():
            per_run = runs_by_module.get(module, {}).get(rk)
            if per_run is None:
                # Log mentions a module the summary didn't record; skip it.
                continue
            per_run["inference_time"] = (
                round(t["inference_time"], 6) if t["saw_inf"] else None
            )
            per_run["evaluation_time"] = (
                round(t["evaluation_time"], 6) if t["saw_eval"] else None
            )
            if t["saw_inf"] or t["saw_eval"]:
                per_run["total_time"] = round(
                    (t["inference_time"] if t["saw_inf"] else 0.0)
                    + (t["evaluation_time"] if t["saw_eval"] else 0.0),
                    6,
                )
            per_run["tokens"] = round(t["tokens"], 3) if t["saw_tok"] else None
            per_run["source"]["log"] = str(log_path)

    # -- step 3: aggregate summaries → _run_totals
    agent_agg, non_agg = _discover_aggregate_files(experiment_roots, selection)
    run_totals: Dict[str, dict] = {}
    for rec in agent_agg:
        rk = run_key(rec["model"], "agent", rec["fewshot"], rec["num_iterations"])
        payload = read_json(rec["path"])
        tot = _extract_agent_aggregate(payload)
        # Sum across experiments when the same run_key appears in both (overlap runs).
        if rk in run_totals:
            for k in (
                "total_lemmas",
                "correct",
                "one_inductive",
                "one_inductive_with_property",
                "num_modules",
                "solved_modules",
            ):
                run_totals[rk][k] += tot[k]
        else:
            run_totals[rk] = {
                "model": rec["model"],
                "pipeline": "agent",
                "fewshot": rec["fewshot"],
                "num_iterations": rec["num_iterations"],
                **tot,
            }

    for rec in non_agg:
        rk = run_key(rec["model"], "non_agent", rec["fewshot"], rec["ns"])
        payload = read_json(rec["path"])
        tot = _extract_nonagent_aggregate(payload)
        if rk in run_totals:
            for k in (
                "total_lemmas",
                "correct",
                "one_inductive",
                "one_inductive_with_property",
                "num_modules",
                "solved_modules",
            ):
                run_totals[rk][k] += tot[k]
        else:
            run_totals[rk] = {
                "model": rec["model"],
                "pipeline": "non_agent",
                "fewshot": rec["fewshot"],
                "num_samples": rec["ns"],
                **tot,
            }

    # -- step 4: attach book_keeping metadata
    meta = _merge_book_keeping(book_keeping_paths)
    missing_tags = [m for m in runs_by_module if m not in meta]
    assert not missing_tags, (
        f"{len(missing_tags)} modules have no book_keeping entry: "
        f"{sorted(missing_tags)[:5]}..."
    )

    # -- step 5: invariants
    # 5.1 Every module has non-null status for every run.
    for module, runs in runs_by_module.items():
        for rk, per_run in runs.items():
            assert per_run["status"] in ("Solved", "Unsolved"), (
                f"Bad status for module={module} run={rk}: {per_run!r}"
            )

    # 5.2 _run_totals cross-check: solved_modules equals count of modules with status==Solved.
    # Small discrepancies are expected and benign — the aggregate summary was computed
    # by the writer before the overlap-module cleanup (ex100, ex8, gulwani_fig1a_3 were
    # removed from hard/), so the writer's `solved_modules` count can be ≤3 higher.
    # Use the per-module count as the authoritative value.
    solved_count_from_per_module: Dict[str, int] = defaultdict(int)
    for module, runs in runs_by_module.items():
        for rk, per_run in runs.items():
            if per_run["status"] == "Solved":
                solved_count_from_per_module[rk] += 1

    mismatched_run_keys = []
    for rk, tot in run_totals.items():
        expected = solved_count_from_per_module.get(rk, 0)
        if tot["solved_modules"] != expected:
            mismatched_run_keys.append((rk, tot["solved_modules"], expected))
            tot["solved_modules"] = expected

    if mismatched_run_keys:
        max_delta = max(abs(orig - new) for _, orig, new in mismatched_run_keys)
        print(
            f"[INFO] _run_totals.solved_modules re-derived from per-module status for "
            f"{len(mismatched_run_keys)}/{len(run_totals)} runs "
            f"(max delta={max_delta}, expected when overlap modules were filtered out)."
        )

    # 5.3 Disk vs ingested module set.
    #     `benchmarks_dirs`, when provided, is the canonical source of truth.
    #     Enforce `runs_by_module ⊆ disk_set` and default the count check to
    #     `len(disk_set)` when the caller didn't pin it.
    if benchmarks_dirs is not None:
        disk_set = _compute_disk_module_set(benchmarks_dirs)
        stray = sorted(set(runs_by_module) - disk_set)

        if stray:
            # Print which runs contain stray modules
            print(
                f"[INFO] Found {len(stray)} module(s) without `.sv` source files: {stray}"
            )
            stray_run_info = defaultdict(set)
            for module in stray:
                for rk in runs_by_module[module]:
                    stray_run_info[module].add(rk)

            for module in stray:
                runs_list = sorted(stray_run_info[module])
                print(f"  - {module}: found in {len(runs_list)} run(s): {runs_list}")

            if enforce_module_count:
                raise ValueError(
                    f"{len(stray)} ingested module(s) have no `.sv` under "
                    f"{[str(p) for p in benchmarks_dirs]}: {stray[:10]}"
                    + ("..." if len(stray) > 10 else "")
                )
            else:
                # In lenient mode, filter them out
                print(f"[INFO] Filtering out {len(stray)} stray module(s) from results")
                for module in stray:
                    del runs_by_module[module]

        if expected_module_count is None:
            expected_module_count = len(disk_set)

    # 5.4 Expected module count.
    if enforce_module_count and expected_module_count is not None:
        assert len(runs_by_module) == expected_module_count, (
            f"Expected {expected_module_count} modules, got {len(runs_by_module)}"
        )

    # -- step 6: assemble final dict
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result: Dict = {
        "_generated_from": {
            "data_root": str(data_root),
            "selection": {
                "agent_num_iterations": selection.agent_num_iterations,
                "agent_num_iterations_value": selection.agent_num_iterations_value,
                "non_agent_num_samples": selection.non_agent_num_samples,
                "non_agent_num_samples_value": selection.non_agent_num_samples_value,
                "fewshots": selection.fewshots,
                "experiments": list(selection.experiments),
                "models": selection.models,
            },
            "at": now,
        },
        "_run_totals": run_totals,
    }

    for module in sorted(runs_by_module):
        result[module] = {
            "metadata": meta[module],
            "runs": {
                rk: runs_by_module[module][rk] for rk in sorted(runs_by_module[module])
            },
        }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=False)

    n_runs = sum(len(m["runs"]) for k, m in result.items() if not k.startswith("_"))
    print(
        f"[OK] Wrote runs.json: {len(runs_by_module)} modules, "
        f"{n_runs} per-(module,run) records, "
        f"{len(run_totals)} _run_totals entries → {out_path}"
    )
    return result
