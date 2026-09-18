#!/usr/bin/env python3
"""Coordinate safe, bounded, deterministic forced-cache replay."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models import MODEL_SHORT_TO_FULL  # noqa: E402


MODELS = (
    "gpt-5",
    "claude-4",
    "claude-4-5-sonnet",
    "claude-4-5-haiku",
    "claude-4-5-opus",
    "claude-4-7-opus",
)
PIPELINES = ("agent", "non_agent")
FEWSHOTS = tuple(range(6))
EXPERIMENTS = ("main_experiment", "hard")
NUM_ITERATIONS = tuple(range(1, 11))
CACHE_DIR_NAMES = ("llm_cache", "eval_cache")


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0 or not value.strip().isdigit():
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


@dataclasses.dataclass(frozen=True)
class ReplayJob:
    ordinal: int
    model: str
    pipeline: str
    few_shot: int
    experiment: str
    num_iterations: int | None = None

    @property
    def stable_id(self) -> str:
        iteration = (
            f"-it{self.num_iterations:02d}"
            if self.num_iterations is not None
            else ""
        )
        return (
            f"{self.ordinal:04d}-{self.model}-{self.pipeline}"
            f"-fs{self.few_shot}-{self.experiment}{iteration}"
        )

    @property
    def run_directory_name(self) -> str:
        return (
            f"{self.model}_{self.pipeline}_{self.few_shot}_{self.experiment}"
        )

    @property
    def cache_relative_path(self) -> Path:
        return Path(self.experiment) / self.run_directory_name

    def workspace(self, results_root: Path) -> Path:
        return results_root / ".replay" / "jobs" / self.stable_id

    def stage_output_root(self, results_root: Path) -> Path:
        return self.workspace(results_root) / "output"

    def work_directory(self, results_root: Path) -> Path:
        return self.workspace(results_root) / "work"

    def coordinator_log(self, results_root: Path) -> Path:
        return (
            results_root
            / "results"
            / "metadata"
            / "replay-logs"
            / f"{self.stable_id}.log"
        )

    def staged_run_results(self, results_root: Path) -> Path:
        return (
            self.stage_output_root(results_root)
            / self.experiment
            / self.run_directory_name
            / "results"
        )

    def published_run_results(self, results_root: Path) -> Path:
        return (
            results_root
            / self.experiment
            / self.run_directory_name
            / "results"
        )

    def as_dict(self) -> dict:
        return {
            "id": self.stable_id,
            "ordinal": self.ordinal,
            "model": self.model,
            "pipeline": self.pipeline,
            "few_shot": self.few_shot,
            "experiment": self.experiment,
            "num_iterations": self.num_iterations,
            "cache_relative_path": self.cache_relative_path.as_posix(),
        }


@dataclasses.dataclass
class JobResult:
    job: ReplayJob
    returncode: int
    elapsed_seconds: float
    error: str | None = None
    skipped: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.skipped and self.error is None


class ActiveWorkerTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def exit(self) -> None:
        with self._lock:
            self.active -= 1


def build_jobs() -> list[ReplayJob]:
    jobs = []
    ordinal = 1
    for model in MODELS:
        for pipeline in PIPELINES:
            for few_shot in FEWSHOTS:
                for experiment in EXPERIMENTS:
                    if pipeline == "agent":
                        for num_iterations in NUM_ITERATIONS:
                            jobs.append(
                                ReplayJob(
                                    ordinal,
                                    model,
                                    pipeline,
                                    few_shot,
                                    experiment,
                                    num_iterations,
                                )
                            )
                            ordinal += 1
                    else:
                        jobs.append(
                            ReplayJob(
                                ordinal,
                                model,
                                pipeline,
                                few_shot,
                                experiment,
                            )
                        )
                        ordinal += 1
    if len(jobs) != 792:
        raise AssertionError(f"Replay matrix changed: expected 792, got {len(jobs)}")
    return jobs


def group_jobs_by_cache(jobs: Iterable[ReplayJob]) -> list[list[ReplayJob]]:
    """Affinity groups ensure a cache database has only one reader at a time."""
    groups: OrderedDict[Path, list[ReplayJob]] = OrderedDict()
    for job in jobs:
        groups.setdefault(job.cache_relative_path, []).append(job)
    return list(groups.values())


def _cache_directories(root: Path, jobs: Iterable[ReplayJob]) -> list[Path]:
    relative_paths = sorted({job.cache_relative_path for job in jobs})
    return [
        root / relative_path / cache_name
        for relative_path in relative_paths
        for cache_name in CACHE_DIR_NAMES
    ]


def validate_disjoint_caches(root: Path, jobs: Iterable[ReplayJob]) -> None:
    """Reject missing, symlinked, or inode-aliased cache inputs."""
    seen_directories: dict[Path, Path] = {}
    seen_inodes: dict[tuple[int, int], Path] = {}
    for cache_dir in _cache_directories(root, jobs):
        if not cache_dir.is_dir():
            raise RuntimeError(f"Required replay cache is missing: {cache_dir}")
        resolved = cache_dir.resolve()
        if resolved in seen_directories:
            raise RuntimeError(
                f"Replay cache paths alias each other: {cache_dir} and "
                f"{seen_directories[resolved]}"
            )
        seen_directories[resolved] = cache_dir
        for path in sorted(cache_dir.rglob("*")):
            if path.is_symlink():
                raise RuntimeError(f"Symlinked cache content is not allowed: {path}")
            if not path.is_file():
                continue
            stat_result = path.stat()
            inode = (stat_result.st_dev, stat_result.st_ino)
            if inode in seen_inodes:
                raise RuntimeError(
                    f"Hard-linked cache content is not allowed: {path} and "
                    f"{seen_inodes[inode]}"
                )
            seen_inodes[inode] = path


def cache_fingerprint(root: Path, jobs: Iterable[ReplayJob]) -> str:
    """Content fingerprint for all cache files used by replay."""
    digest = hashlib.sha256()
    for cache_dir in _cache_directories(root, jobs):
        relative_cache = cache_dir.relative_to(root).as_posix()
        digest.update(relative_cache.encode())
        for path in sorted(cache_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode())
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def snapshot_caches(
    artifact_root: Path, snapshot_root: Path, jobs: Iterable[ReplayJob]
) -> None:
    """Copy each distinct cache pair serially before workers are started."""
    if snapshot_root.exists():
        raise RuntimeError(f"Cache snapshot path already exists: {snapshot_root}")
    for source in _cache_directories(artifact_root, jobs):
        destination = snapshot_root / source.relative_to(artifact_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)


def make_tree_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def remove_read_only_tree(root: Path) -> None:
    if not root.exists():
        return
    root.chmod(0o755)
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    shutil.rmtree(root)


def _expected_module_count(job: ReplayJob) -> int:
    modules_dir = REPO_ROOT / "benchmarks" / job.experiment
    return len(
        [
            path
            for path in modules_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".v", ".sv"}
        ]
    )


def _expected_output_paths(job: ReplayJob, results_dir: Path) -> list[Path]:
    model = MODEL_SHORT_TO_FULL[job.model]
    if job.pipeline == "agent":
        iteration = job.num_iterations
        assert iteration is not None
        return [
            results_dir
            / (
                f"agent_conversations_fs{job.few_shot}_{model}_"
                f"{job.experiment}_num_iterations_{iteration}.json"
            ),
            results_dir
            / (
                f"agentic_detailed_lemma_records_{model}_fewshot_"
                f"{job.few_shot}_{job.experiment}_num_iterations_{iteration}.json"
            ),
            results_dir
            / "logs"
            / (
                f"experiment_agentic_{model}_{job.experiment}_fs_"
                f"{job.few_shot}_num_iterations_{iteration}.log"
            ),
            results_dir
            / "summaries"
            / (
                f"summary_agentic_{model}_fewshot_{job.few_shot}_"
                f"{job.experiment}_num_iterations_{iteration}.json"
            ),
            results_dir
            / "summaries"
            / (
                f"summary_aggregate_agentic_{model}_fewshot_{job.few_shot}_"
                f"{job.experiment}_num_iterations_{iteration}.json"
            ),
        ]

    prompt_suffix = (
        f"{job.experiment}_fs{job.few_shot}_ns5_"
        f"{model}_fewshot_prompt.txt"
    )
    output_stem = f"proposed_lemmas_{prompt_suffix}_ns5"
    safe_model = model.replace(":", "_")
    return [
        results_dir / f"{output_stem}.json",
        results_dir / f"{output_stem}.csv",
        results_dir / f"{output_stem}_eval_ebmc.json",
        results_dir / "logs" / f"evaluate_non_agentic_{prompt_suffix}_ns5.log",
        results_dir
        / "summaries"
        / (
            f"summary_non_agentic_{safe_model}_fewshot_{job.few_shot}_"
            f"{job.experiment}_ns5.json"
        ),
        results_dir
        / "summaries"
        / (
            f"summary_aggregate_non_agentic_{safe_model}_fewshot_"
            f"{job.few_shot}_{job.experiment}_ns5.json"
        ),
    ]


def validate_job_outputs(job: ReplayJob, results_root: Path) -> None:
    results_dir = job.staged_run_results(results_root)
    missing = [
        path for path in _expected_output_paths(job, results_dir) if not path.is_file()
    ]
    if missing:
        raise RuntimeError(
            "Missing expected replay outputs: "
            + ", ".join(str(path) for path in missing)
        )

    expected_modules = _expected_module_count(job)
    model = MODEL_SHORT_TO_FULL[job.model]
    if job.pipeline == "agent":
        assert job.num_iterations is not None
        summary_path = (
            results_dir
            / "summaries"
            / (
                f"summary_aggregate_agentic_{model}_fewshot_{job.few_shot}_"
                f"{job.experiment}_num_iterations_{job.num_iterations}.json"
            )
        )
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        actual_modules = payload.get("num_modules")
    else:
        safe_model = model.replace(":", "_")
        summary_path = (
            results_dir
            / "summaries"
            / (
                f"summary_non_agentic_{safe_model}_fewshot_{job.few_shot}_"
                f"{job.experiment}_ns5.json"
            )
        )
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        actual_modules = len(payload.get("modules", {}))
    if actual_modules != expected_modules:
        raise RuntimeError(
            f"{job.stable_id} produced {actual_modules} module summaries; "
            f"expected {expected_modules}"
        )


def _job_command(
    job: ReplayJob,
    python: Path,
    cache_snapshot_root: Path,
    results_root: Path,
    selection_cache: Path,
) -> list[str]:
    command = [
        str(python),
        str(REPO_ROOT / "scripts" / "entry_point.py"),
        "-model",
        job.model,
        "-pipeline",
        job.pipeline,
        "-few_shot",
        str(job.few_shot),
        "-modules_dir",
        str(REPO_ROOT / "benchmarks" / job.experiment),
        "-storage_dir",
        str(cache_snapshot_root),
        "-output_dir",
        str(job.stage_output_root(results_root)),
        "-work_dir",
        str(job.work_directory(results_root)),
        "-evaluation_cache_mode",
        "FORCE_CACHED",
        "--force_cached",
        "--replay-read-only",
    ]
    if job.few_shot > 0:
        command.extend(
            [
                "--fewshot-selection",
                "cached",
                "--fewshot-selection-cache",
                str(selection_cache),
            ]
        )
    if job.num_iterations is not None:
        command.extend(["-num_iterations", str(job.num_iterations)])
    return command


def run_subprocess_job(
    job: ReplayJob,
    python: Path,
    cache_snapshot_root: Path,
    results_root: Path,
    selection_cache: Path,
    tracker: ActiveWorkerTracker,
) -> JobResult:
    workspace = job.workspace(results_root)
    workspace.mkdir(parents=True, exist_ok=False)
    work_dir = job.work_directory(results_root)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "tmp").mkdir()
    log_path = job.coordinator_log(results_root)
    command = _job_command(
        job, python, cache_snapshot_root, results_root, selection_cache
    )
    environment = os.environ.copy()
    environment.update(
        {
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONHASHSEED": "0",
            "TMPDIR": str(work_dir / "tmp"),
        }
    )

    start = time.perf_counter()
    returncode = 1
    error = None
    tracker.enter()
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write("COMMAND: " + json.dumps(command) + "\n")
            log.flush()
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
            returncode = completed.returncode
        if returncode == 0:
            validate_job_outputs(job, results_root)
    except Exception as exc:
        error = str(exc)
        returncode = returncode or 1
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"COORDINATOR ERROR: {error}\n")
    finally:
        tracker.exit()
        shutil.rmtree(work_dir, ignore_errors=True)

    elapsed = time.perf_counter() - start
    with log_path.open("a", encoding="utf-8") as log:
        log.write(
            f"RESULT: returncode={returncode} elapsed_seconds={elapsed:.6f}\n"
        )
    return JobResult(job, returncode, elapsed, error=error)


def execute_job_groups(
    groups: list[list[ReplayJob]],
    workers: int,
    run_one: Callable[[ReplayJob], JobResult],
) -> list[JobResult]:
    """Run cache-affinity groups in a bounded pool and propagate failures."""
    stop_event = threading.Event()
    results: list[JobResult] = []
    result_lock = threading.Lock()

    def run_group(group: list[ReplayJob]) -> None:
        for index, job in enumerate(group):
            if stop_event.is_set():
                skipped = JobResult(job, 1, 0.0, skipped=True)
                with result_lock:
                    results.append(skipped)
                continue
            result = run_one(job)
            with result_lock:
                results.append(result)
            if not result.succeeded:
                stop_event.set()
                for remaining in group[index + 1 :]:
                    skipped = JobResult(remaining, 1, 0.0, skipped=True)
                    with result_lock:
                        results.append(skipped)
                break

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_group, group) for group in groups]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    return sorted(results, key=lambda result: result.job.ordinal)


def initialize_job_logs(jobs: Iterable[ReplayJob], results_root: Path) -> None:
    for job in jobs:
        path = job.coordinator_log(results_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(job.as_dict(), sort_keys=True) + "\n", encoding="utf-8"
        )


def _last_returncode(log_path: Path) -> int | None:
    if not log_path.is_file():
        return None
    matches = re.findall(
        r"^RESULT: returncode=(-?\d+)\b",
        log_path.read_text(encoding="utf-8", errors="replace"),
        flags=re.MULTILINE,
    )
    return int(matches[-1]) if matches else None


def _archive_attempt_log(log_path: Path, results_root: Path) -> None:
    if not log_path.is_file():
        return
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if "COMMAND:" not in text:
        return
    archive_dir = (
        results_root / "results" / "metadata" / "replay-attempts"
    )
    archive_dir.mkdir(parents=True, exist_ok=True)
    attempt = 1
    while True:
        destination = archive_dir / (
            f"{log_path.stem}-attempt{attempt}{log_path.suffix}"
        )
        if not destination.exists():
            log_path.replace(destination)
            return
        attempt += 1


def prepare_resume(
    jobs: list[ReplayJob], results_root: Path
) -> tuple[list[JobResult], list[ReplayJob]]:
    """Validate completed jobs and reset only incomplete job workspaces."""
    completed = []
    pending = []
    for job in jobs:
        log_path = job.coordinator_log(results_root)
        if _last_returncode(log_path) == 0:
            try:
                validate_job_outputs(job, results_root)
            except Exception:
                pass
            else:
                completed.append(JobResult(job, 0, 0.0))
                continue

        pending.append(job)
        _archive_attempt_log(log_path, results_root)
        shutil.rmtree(job.workspace(results_root), ignore_errors=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(job.as_dict(), sort_keys=True)
            + "\nRESUME: incomplete job will be retried\n",
            encoding="utf-8",
        )
    return completed, pending


def validate_resume_manifest(jobs: list[ReplayJob], results_root: Path) -> None:
    manifest_path = (
        results_root / "results" / "metadata" / "replay-manifest.json"
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid replay manifest {manifest_path}: {exc}") from exc
    expected = [job.as_dict() for job in jobs]
    if manifest != expected:
        raise RuntimeError(
            "Replay manifest does not match the current 792-job matrix"
        )


def publish_outputs(jobs: Iterable[ReplayJob], results_root: Path) -> None:
    """Merge successful, job-private outputs with collision detection."""
    for job in sorted(jobs, key=lambda item: item.ordinal):
        source_root = job.staged_run_results(results_root)
        destination_root = job.published_run_results(results_root)
        for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
            relative = source.relative_to(source_root)
            destination = destination_root / relative
            if destination.exists():
                raise RuntimeError(
                    f"Replay jobs produced a duplicate output path: {destination}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)


def _append_skipped_logs(results: Iterable[JobResult], results_root: Path) -> None:
    for result in results:
        if result.skipped:
            with result.job.coordinator_log(results_root).open(
                "a", encoding="utf-8"
            ) as log:
                log.write("RESULT: skipped after another replay job failed\n")


def write_summary(
    path: Path,
    *,
    workers: int,
    tracker: ActiveWorkerTracker,
    results: list[JobResult],
    started_at: datetime,
    elapsed_seconds: float,
    artifact_fingerprint_before: str,
    artifact_fingerprint_after: str,
    snapshot_fingerprint_before: str,
    snapshot_fingerprint_after: str,
) -> None:
    failures = [
        {
            "id": result.job.stable_id,
            "returncode": result.returncode,
            "error": result.error,
            "skipped": result.skipped,
        }
        for result in results
        if not result.succeeded
    ]
    payload = {
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed_seconds,
        "requested_workers": workers,
        "peak_active_workers": tracker.peak,
        "expected_jobs": 792,
        "completed_jobs": sum(result.succeeded for result in results),
        "failed_or_skipped_jobs": len(failures),
        "failures": failures,
        "artifact_cache_fingerprint_before": artifact_fingerprint_before,
        "artifact_cache_fingerprint_after": artifact_fingerprint_after,
        "artifact_cache_unchanged": (
            artifact_fingerprint_before == artifact_fingerprint_after
        ),
        "snapshot_cache_fingerprint_before": snapshot_fingerprint_before,
        "snapshot_cache_fingerprint_after": snapshot_fingerprint_after,
        "snapshot_cache_unchanged": (
            snapshot_fingerprint_before == snapshot_fingerprint_after
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-data-dir", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--workers", type=positive_int, default=1)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a validated interrupted replay checkpoint",
    )
    parser.add_argument(
        "--selection-cache",
        type=Path,
        default=REPO_ROOT / "data" / "fewshot_selection.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact_root = args.artifact_data_dir.resolve()
    results_root = args.results_dir.resolve()
    python = args.python.expanduser()
    if not python.is_absolute():
        python = (Path.cwd() / python).absolute()
    selection_cache = args.selection_cache.resolve()
    jobs = build_jobs()
    groups = group_jobs_by_cache(jobs)
    if len(groups) != 144:
        raise RuntimeError(
            f"Replay cache-affinity matrix changed: expected 144, got {len(groups)}"
        )

    started_at = datetime.now(timezone.utc)
    wall_start = time.perf_counter()
    tracker = ActiveWorkerTracker()
    summary_path = results_root / "results" / "metadata" / "replay-summary.json"
    manifest_path = results_root / "results" / "metadata" / "replay-manifest.json"
    print("Validating 144 disjoint artifact cache pairs...")
    validate_disjoint_caches(artifact_root, jobs)
    fingerprint_before = cache_fingerprint(artifact_root, jobs)

    snapshot_root = results_root / ".replay" / "cache-snapshot"
    if args.resume:
        validate_resume_manifest(jobs, results_root)
        if not snapshot_root.is_dir():
            raise RuntimeError(
                f"Replay cache snapshot is missing: {snapshot_root}"
            )
        completed_before, pending_jobs = prepare_resume(jobs, results_root)
        print(
            f"Resuming checkpoint: {len(completed_before)} completed jobs "
            f"validated, {len(pending_jobs)} jobs pending."
        )
    else:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                [job.as_dict() for job in jobs], indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        initialize_job_logs(jobs, results_root)
        print("Creating serial, results-local cache snapshot...")
        snapshot_caches(artifact_root, snapshot_root, jobs)
        completed_before = []
        pending_jobs = jobs

    validate_disjoint_caches(snapshot_root, jobs)
    snapshot_fingerprint_before = cache_fingerprint(snapshot_root, jobs)
    if args.resume and snapshot_fingerprint_before != fingerprint_before:
        raise RuntimeError(
            "Resume refused: artifact and checkpoint cache fingerprints differ"
        )
    make_tree_read_only(snapshot_root)

    print(
        f"Running {len(pending_jobs)} replay jobs in "
        f"{len(group_jobs_by_cache(pending_jobs))} cache-affinity "
        f"groups with at most {args.workers} workers..."
    )
    run_one = lambda job: run_subprocess_job(
        job,
        python,
        snapshot_root,
        results_root,
        selection_cache,
        tracker,
    )
    pending_results = execute_job_groups(
        group_jobs_by_cache(pending_jobs), args.workers, run_one
    )
    _append_skipped_logs(pending_results, results_root)
    results = sorted(
        completed_before + pending_results,
        key=lambda result: result.job.ordinal,
    )

    snapshot_fingerprint_after = cache_fingerprint(snapshot_root, jobs)
    fingerprint_after = cache_fingerprint(artifact_root, jobs)
    elapsed = time.perf_counter() - wall_start
    write_summary(
        summary_path,
        workers=args.workers,
        tracker=tracker,
        results=results,
        started_at=started_at,
        elapsed_seconds=elapsed,
        artifact_fingerprint_before=fingerprint_before,
        artifact_fingerprint_after=fingerprint_after,
        snapshot_fingerprint_before=snapshot_fingerprint_before,
        snapshot_fingerprint_after=snapshot_fingerprint_after,
    )

    failures = [result for result in results if not result.succeeded]
    if fingerprint_before != fingerprint_after:
        failures.append(
            JobResult(jobs[0], 1, 0.0, error="artifact cache fingerprint changed")
        )
    if snapshot_fingerprint_before != snapshot_fingerprint_after:
        failures.append(
            JobResult(jobs[0], 1, 0.0, error="snapshot cache fingerprint changed")
        )

    if failures:
        print(
            f"Replay failed: {sum(result.succeeded for result in results)}/792 "
            f"jobs completed; checkpoint preserved at {results_root}; "
            f"see {summary_path}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("Worker pool terminated successfully; publishing job outputs...")
    publish_outputs(jobs, results_root)
    remove_read_only_tree(snapshot_root)
    shutil.rmtree(results_root / ".replay", ignore_errors=True)
    print(
        f"Replay complete: 792/792 jobs, peak workers={tracker.peak}, "
        f"elapsed={elapsed:.3f}s"
    )


if __name__ == "__main__":
    main()
