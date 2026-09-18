from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from cache_utils import ImmutableDiskCache
from evaluation import CacheMode, LemmaEvaluator
from prompt_llms import LLMBase
from scripts.replay_coordinator import (
    JobResult,
    ReplayJob,
    build_jobs,
    execute_job_groups,
    group_jobs_by_cache,
)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class DummyLLM(LLMBase):
    def get_single_string_from_messages(self, messages):
        return messages[0]["content"]

    def _generate_responses(self, messages, num_samples=1, temperature=0.7):
        raise AssertionError("live generation must not run")


class RecordingCache(dict):
    def __init__(self):
        super().__init__()
        self.writes = 0

    def __setitem__(self, key, value):
        self.writes += 1
        super().__setitem__(key, value)


class ReplayTests(unittest.TestCase):
    def test_workers_help_and_validation(self):
        help_run = subprocess.run(
            [str(REPO_ROOT / "generate_tables.sh"), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(help_run.returncode, 0)
        self.assertIn("--workers N", help_run.stdout)

        for invalid in ("0", "-1", "abc", ""):
            run = subprocess.run(
                [
                    str(REPO_ROOT / "generate_tables.sh"),
                    "--replay",
                    "--workers",
                    invalid,
                    "/tmp/unused-replay-test",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2, invalid)
            self.assertIn("positive integer", run.stderr)

        resume = subprocess.run(
            [
                str(REPO_ROOT / "generate_tables.sh"),
                "--resume",
                "/tmp/unused-replay-test",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(resume.returncode, 2)
        self.assertIn("--resume requires --replay", resume.stderr)

    def test_matrix_and_job_paths_are_stable_and_unique(self):
        jobs = build_jobs()
        self.assertEqual(len(jobs), 792)
        self.assertEqual(len(group_jobs_by_cache(jobs)), 144)
        self.assertEqual(len({job.stable_id for job in jobs}), 792)
        root = Path("/replay")
        self.assertEqual(len({job.workspace(root) for job in jobs}), 792)
        self.assertEqual(
            len({job.stage_output_root(root) for job in jobs}), 792
        )
        self.assertEqual(len({job.coordinator_log(root) for job in jobs}), 792)

    def test_worker_failure_stops_later_jobs_and_is_reported(self):
        jobs = [
            ReplayJob(1, "gpt-5", "agent", 0, "hard", 1),
            ReplayJob(2, "gpt-5", "agent", 0, "hard", 2),
            ReplayJob(3, "gpt-5", "agent", 0, "hard", 3),
        ]

        def run_one(job):
            if job.ordinal == 2:
                return JobResult(job, 17, 0.0, error="intentional")
            return JobResult(job, 0, 0.0)

        results = execute_job_groups([jobs], workers=2, run_one=run_one)
        self.assertTrue(results[0].succeeded)
        self.assertEqual(results[1].returncode, 17)
        self.assertTrue(results[2].skipped)

    def test_worker_count_does_not_change_summaries(self):
        jobs = [
            ReplayJob(i, "gpt-5", "non_agent", i, "hard")
            for i in range(1, 5)
        ]
        groups = group_jobs_by_cache(jobs)

        def run(workers):
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp)

                def run_one(job):
                    time.sleep(0.005 * (5 - job.ordinal))
                    (output / f"{job.stable_id}.json").write_text(
                        json.dumps(
                            {"few_shot": job.few_shot, "solved": job.ordinal % 2},
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    return JobResult(job, 0, 0.0)

                results = execute_job_groups(groups, workers, run_one)
                self.assertTrue(all(result.succeeded for result in results))
                return {
                    path.name: json.loads(path.read_text(encoding="utf-8"))
                    for path in sorted(output.iterdir())
                }

        self.assertEqual(run(1), run(3))

    def test_immutable_cache_and_read_only_alias_lookup_do_not_write(self):
        from diskcache import Cache

        with tempfile.TemporaryDirectory() as temp:
            cache_dir = Path(temp) / "cache"
            cache = Cache(str(cache_dir))
            cache["key"] = [{"text": "value"}]
            cache.close()
            before = tree_digest(cache_dir)
            for path in cache_dir.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            cache_dir.chmod(0o555)

            immutable = ImmutableDiskCache(cache_dir)
            self.assertEqual(immutable["key"], [{"text": "value"}])
            immutable.close()
            self.assertEqual(before, tree_digest(cache_dir))

        recording = RecordingCache()
        model = DummyLLM(
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            storage_dir="/unused",
            cache=recording,
            cache_read_only=True,
        )
        messages = [{"role": "user", "content": "prompt"}]
        old_key = model._hash_query(messages, normalized=False)
        dict.__setitem__(recording, old_key, [{"text": "cached"}])
        result = model.get_from_cache(messages)
        self.assertTrue(result["cache_hit"])
        self.assertEqual(recording.writes, 0)

    def test_force_cached_evaluation_disables_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            module = Path(temp) / "module.sv"
            module.write_text(
                "module main(input logic clk);\n"
                "property prop;\n1;\nendproperty\nendmodule\n",
                encoding="utf-8",
            )
            evaluator = LemmaEvaluator(
                storage_dir=temp,
                tool="ebmc",
                verilog_file=str(module),
                cache={},
                cache_result=True,
                cache_mode=CacheMode.FORCE_CACHED,
            )
            self.assertFalse(evaluator.cache_result)
            with self.assertRaisesRegex(RuntimeError, "read-only"):
                evaluator._cache_result(
                    ["property lemma_1; 1; endproperty"],
                    "correctness_bounded",
                    {"verification_result": object()},
                    "all",
                )


if __name__ == "__main__":
    unittest.main()
