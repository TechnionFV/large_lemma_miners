#!/usr/bin/env python3
"""Generate paper tables and plots from experiment data.

Outputs:
    tables/overall_from_experiments.{tex,csv}
    tables/timings_hard_all.{tex,json}
    tables/solved_unsolved_by_category.latex
    tables/fewshot_ablation.tex
    plots/num_iterations_ablation_line.png

Usage:
    python scripts/get_tables.py results/
    python scripts/get_tables.py results/ --tables overall timings
    python scripts/get_tables.py results/ --lenient

Available table names:
    overall             : tables/overall_from_experiments.{tex,csv}
    timings             : tables/timings_hard_all.{tex,json}
    categories          : tables/solved_unsolved_by_category.latex
    fewshot-ablation    : tables/fewshot_ablation.tex
    iterations-ablation : plots/num_iterations_ablation_line.png

Inputs:
    <ARTIFACT_DATA_DIR>/main_experiment/ and <ARTIFACT_DATA_DIR>/hard/
    benchmarks/main_experiment/book_keeping.json
    benchmarks/hard/bookkeeping.json
    benchmarks/hard/sota_timings/{ric3,jasper,vcf}.json

Environment:
    ARTIFACT_DATA_DIR : path to extracted Zenodo data (default: <repo>/data)
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
from pathlib import Path

from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.runs_builder import build_runs_json
from analysis.table_helpers import (
    build_num_iterations_ablation_plots,
    build_table1_from_runs,
    build_table2_from_runs,
    build_table3_from_runs,
    build_table4_from_runs,
    filter_runs,
)
from models import PAPER_MODEL_SHORTS
from analysis.run_selection import RunSelection


ALL_TABLES = (
    "overall",
    "timings",
    "categories",
    "fewshot-ablation",
    "iterations-ablation",
)

ALL_FEWSHOTS = list(range(6))  # 0–5
ALL_NUM_ITERATIONS = list(range(1, 11))  # 1–10
NUM_SAMPLES = 5

MAIN_FEWSHOTS = list(range(5))  # 0–4
MAIN_NUM_ITERATIONS = 7


def _check_data_roots(main_root: Path, hard_root: Path) -> None:
    missing = [
        p for p in (main_root, hard_root) if not p.is_dir() or not any(p.iterdir())
    ]
    if missing:
        msg = (
            "Required experiment data missing.\n"
            f"  Missing or empty: {', '.join(str(p) for p in missing)}\n\n"
            "Download the Zenodo release (or set ARTIFACT_DATA_DIR) and retry. See README.md."
        )
        sys.exit(msg)


def _ingestion_selection() -> RunSelection:
    return RunSelection(
        agent_num_iterations="all",
        agent_num_iterations_value=None,
        non_agent_num_samples="exact",
        non_agent_num_samples_value=NUM_SAMPLES,
        fewshots=ALL_FEWSHOTS,
        experiments=["main_experiment", "hard"],
        models=PAPER_MODEL_SHORTS,
    )


@contextlib.contextmanager
def _redirect_stdout_to(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log_file:
        old_stdout = sys.stdout
        sys.stdout = log_file
        try:
            yield log_file
        finally:
            sys.stdout = old_stdout


def _collect_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(f for f in directory.rglob("*") if f.is_file())


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "results_dir",
        type=Path,
        help="Output directory for tables/, plots/, and metadata/.",
    )
    p.add_argument(
        "--tables",
        nargs="+",
        default=["all"],
        help=(
            "Which tables to emit. Space-separated subset of "
            f"{list(ALL_TABLES)} or 'all' (default)."
        ),
    )
    p.add_argument(
        "--lenient",
        action="store_true",
        help="Skip strict module-count invariants (use with partial data).",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    selected = set(ALL_TABLES) if "all" in args.tables else set(args.tables)
    for t in selected:
        if t not in ALL_TABLES:
            sys.exit(
                f"Unknown table {t!r}; expected a subset of {list(ALL_TABLES)} or 'all'."
            )

    data_env = os.environ.get("ARTIFACT_DATA_DIR")
    data_root = Path(data_env) if data_env else REPO_ROOT / "data"

    results_dir = args.results_dir.resolve()
    tables_dir = results_dir / "tables"
    plots_dir = results_dir / "plots"
    metadata_dir = results_dir / "metadata"
    for d in (tables_dir, plots_dir, metadata_dir):
        d.mkdir(parents=True, exist_ok=True)

    log_path = metadata_dir / "build.log"

    sv_dir = REPO_ROOT / "benchmarks" / "main_experiment"
    main_book_keeping = sv_dir / "book_keeping.json"
    hard_tags_path = REPO_ROOT / "benchmarks" / "hard" / "bookkeeping.json"

    _check_data_roots(data_root / "main_experiment", data_root / "hard")

    # One stage for data ingestion plus one per selected table. The progress
    # bar writes to stderr (the console); every print() from the builders is
    # captured in build.log via the stdout redirect below.
    stages = ["ingest"] + [t for t in ALL_TABLES if t in selected]
    pbar = tqdm(
        total=len(stages),
        desc="get_tables",
        unit="stage",
        position=0,
        dynamic_ncols=True,
        file=sys.stderr,
    )

    def _begin_stage(name: str) -> None:
        pbar.set_description(f"[{name}]")
        print(f"\n===== stage: {name} =====")  # goes to build.log

    with _redirect_stdout_to(log_path):
        _begin_stage("ingest run data")
        runs_json = build_runs_json(
            data_root=data_root,
            selection=_ingestion_selection(),
            book_keeping_paths=[main_book_keeping, hard_tags_path],
            out_path=metadata_dir / "runs.json",
            benchmarks_dirs=[
                REPO_ROOT / "benchmarks" / "main_experiment",
                REPO_ROOT / "benchmarks" / "hard",
            ],
            enforce_module_count=not args.lenient,
        )

        main_runs = filter_runs(
            runs_json,
            fewshots=MAIN_FEWSHOTS,
            agent_num_iterations=MAIN_NUM_ITERATIONS,
            non_agent_num_samples=NUM_SAMPLES,
        )
        pbar.update(1)

        if "overall" in selected:
            _begin_stage("overall table")
            build_table1_from_runs(main_runs, out_dir=tables_dir)
            pbar.update(1)

        if "timings" in selected:
            _begin_stage("timings table")
            build_table2_from_runs(
                main_runs,
                out_dir=tables_dir,
                sota_timings_dir=REPO_ROOT / "benchmarks" / "hard" / "sota_timings",
                hard_tags_path=hard_tags_path,
                fewshot_variants=[(sorted(MAIN_FEWSHOTS), "all")],
            )
            pbar.update(1)

        if "categories" in selected:
            _begin_stage("categories table")
            build_table3_from_runs(
                main_runs,
                out_path=tables_dir / "solved_unsolved_by_category.latex",
            )
            pbar.update(1)

        if "fewshot-ablation" in selected:
            _begin_stage("fewshot ablation table")
            fewshot_ablation_runs = filter_runs(
                runs_json,
                fewshots=ALL_FEWSHOTS,
                agent_num_iterations=MAIN_NUM_ITERATIONS,
                non_agent_num_samples=NUM_SAMPLES,
            )
            build_table4_from_runs(
                fewshot_ablation_runs,
                out_tex=None,
                coarse_out_tex=tables_dir / "fewshot_ablation.tex",
                fewshots=ALL_FEWSHOTS,
            )
            pbar.update(1)

        if "iterations-ablation" in selected:
            _begin_stage("iterations ablation plot")
            iterations_runs = filter_runs(
                runs_json,
                fewshots=MAIN_FEWSHOTS,
                non_agent_num_samples=NUM_SAMPLES,
            )
            build_num_iterations_ablation_plots(
                iterations_runs,
                ks=ALL_NUM_ITERATIONS,
                non_agent_num_samples=NUM_SAMPLES,
                out_dir=plots_dir,
            )
            pbar.update(1)

    pbar.set_description("done")
    pbar.close()

    # Surface a one-line summary of anything noteworthy captured in the log.
    log_text = log_path.read_text(encoding="utf-8")
    n_warnings = len(re.findall(r"^\[WARNING\]", log_text, flags=re.MULTILINE))
    n_infos = len(re.findall(r"^\[INFO\]", log_text, flags=re.MULTILINE))
    print(
        f"Build log: {log_path} "
        f"({n_warnings} warning(s), {n_infos} info message(s))"
    )

    print("Outputs:")
    all_outputs = (
        _collect_files(tables_dir)
        + _collect_files(plots_dir)
        + _collect_files(metadata_dir)
    )
    for f in all_outputs:
        print(f)


if __name__ == "__main__":
    main()
