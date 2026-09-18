from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fewshot.few_shot import (
    SelectionCacheError,
    clear_fewshot_selection_cache,
    embedding_model_context,
    get_example_embeddings,
    get_k_nearest,
    load_fewshot_selection_cache,
    sha256_file,
    validate_selection_cache_for_modules,
)


class FewshotSelectionCacheTests(unittest.TestCase):
    def tearDown(self):
        clear_fewshot_selection_cache()

    def _make_cache(self, root: Path) -> tuple[Path, Path]:
        examples = root / "fewshot" / "examples_raw"
        benchmarks = root / "benchmarks" / "main_experiment"
        examples.mkdir(parents=True)
        benchmarks.mkdir(parents=True)
        example = examples / "example.sv"
        module = benchmarks / "module.sv"
        example.write_text("module example; endmodule\n", encoding="utf-8")
        module.write_text("module target; endmodule\n", encoding="utf-8")
        payload = {
            "schema_version": 1,
            "metadata": {
                "max_k": 1,
                "example_input_hashes": {
                    "fewshot/examples_raw/example.sv": sha256_file(example)
                },
            },
            "modules": {
                "benchmarks/main_experiment/module.sv": {
                    "input_sha256": sha256_file(module),
                    "nearest": [
                        {"filename": "example.sv", "similarity": 0.75}
                    ],
                }
            },
        }
        cache = root / "data" / "fewshot_selection.json"
        cache.parent.mkdir()
        cache.write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
        return cache, module

    def test_cached_selection_is_strict_and_does_not_import_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache, module = self._make_cache(root)
            sys.modules.pop("sentence_transformers", None)
            load_fewshot_selection_cache(cache, repository_root=root)

            self.assertEqual(
                get_k_nearest(
                    None, module, None, k=1, selection_mode="cached"
                ),
                [("example.sv", 0.75)],
            )
            self.assertNotIn("sentence_transformers", sys.modules)

            with self.assertRaisesRegex(
                SelectionCacheError, "exceeds selection-cache maximum"
            ):
                get_k_nearest(
                    None, module, None, k=2, selection_mode="cached"
                )

            missing = module.with_name("missing.sv")
            missing.write_text("module missing; endmodule\n", encoding="utf-8")
            with self.assertRaisesRegex(SelectionCacheError, "has no entry"):
                get_k_nearest(
                    None, missing, None, k=1, selection_mode="cached"
                )

            module.write_text("module changed; endmodule\n", encoding="utf-8")
            with self.assertRaisesRegex(SelectionCacheError, "hash changed"):
                get_k_nearest(
                    None, module, None, k=1, selection_mode="cached"
                )

    def test_shipped_cache_covers_all_benchmarks(self):
        cache = REPO_ROOT / "data" / "fewshot_selection.json"
        payload = load_fewshot_selection_cache(cache)
        main = validate_selection_cache_for_modules(
            REPO_ROOT / "benchmarks" / "main_experiment", 5
        )
        hard = validate_selection_cache_for_modules(
            REPO_ROOT / "benchmarks" / "hard", 5
        )
        self.assertEqual(len(main) + len(hard), 109)
        self.assertEqual(len(payload["modules"]), 109)
        self.assertEqual(payload["metadata"]["max_k"], 5)
        self.assertEqual(
            payload["metadata"]["sentence_transformers_version"], "5.1.0"
        )

    @unittest.skipUnless(
        os.environ.get("RUN_LIVE_FEWSHOT_TESTS") == "1",
        "set RUN_LIVE_FEWSHOT_TESTS=1 for the pinned-model integration test",
    )
    def test_shipped_cached_and_live_orderings_match(self):
        payload = load_fewshot_selection_cache(
            REPO_ROOT / "data" / "fewshot_selection.json"
        )
        with embedding_model_context(local_files_only=True) as model:
            examples = get_example_embeddings(
                model, REPO_ROOT / "fewshot" / "examples_raw"
            )
            for key in sorted(payload["modules"]):
                module = REPO_ROOT / key
                live = get_k_nearest(
                    model, module, examples, 5, selection_mode="live"
                )
                cached = get_k_nearest(
                    None, module, None, 5, selection_mode="cached"
                )
                self.assertEqual(
                    [name for name, _ in cached],
                    [name for name, _ in live],
                    key,
                )


if __name__ == "__main__":
    unittest.main()
