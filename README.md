# Large Lemma Miners — Reproducibility Artifact

Artifact for the IJCAI 2026 paper *"Large Lemma Miners: Can LLMs do Induction Proofs for Hardware?"*

## Repository Structure

```
benchmarks/
  main_experiment/    # 78 SystemVerilog benchmarks (main experiment, excluding hard subset)
  hard/               # hard subset + sota_timings/
scripts/
  get_tables.py       # single entry point for all paper tables & plots
  entry_point.py      # experiment runner (used for Level 2 replay)
  analysis/           # table/plot builders consumed by get_tables.py
  cactus/             # cactus plot generation
templates/            # prompt templates
src/                  # core source (agentic.py, evaluation.py, models.py, prompt_llms.py, utils.py)
```

## Prerequisites

```bash
pip install -r requirements.txt
```

The verification backend (EBMC) is only needed for live runs; both reproduction levels below use cached evaluation results.

## Artifact Data (Zenodo)

The artifact archive is published on Zenodo: <https://zenodo.org/records/20832562> (DOI: [10.5281/zenodo.20832562](https://doi.org/10.5281/zenodo.20832562)).

Download `artifact.tar.gz` (~835 MB) and extract it; it unpacks to an `artifact/` directory containing:

| Directory | Contents |
|-----------|----------|
| `main_experiment/` | Per-run directories with LLM caches, eval caches, and result summaries |
| `hard/` | Same structure for the hard benchmark subset |

Set the environment variable to point at the extracted `artifact/` directory:

```bash
export ARTIFACT_DATA_DIR=/path/to/artifact
```

---

## Level 1 — Reproduce Tables & Plots from Pre-computed Results

The artifact data directory contains pre-computed run results (result summaries for every configuration). This level regenerates all paper tables and figures directly from those summaries. No LLM calls, no EBMC calls.

```bash
export ARTIFACT_DATA_DIR=/path/to/extracted/artifact
./generate_tables.sh
```

Outputs appear under `results/tables/` and `results/plots/`:
- `tables/overall_from_experiments.{tex,csv}` — main results table
- `tables/timings_hard_all.{tex,json}` — timing comparison on hard benchmarks
- `tables/solved_unsolved_by_category.latex` — per-category breakdown
- `tables/fewshot_ablation.tex` — few-shot ablation table
- `plots/num_iterations_ablation_line.png` — iterations ablation plot

A build log is written to `results/metadata/build.log`.

---

## Level 2 — Replay from Caches (Full Pipeline Replay)

The run results in the artifact data can also be recomputed from scratch. This level re-executes the full experiment pipeline end-to-end, but all LLM and evaluation calls are served from disk caches. It regenerates the result summaries, then produces the same tables and plots as Level 1.

```bash
export ARTIFACT_DATA_DIR=/path/to/extracted/artifact
./generate_tables.sh --replay --workers 6 /path/to/new-replay-directory
```

`--workers N` defaults to 1 and requires a positive integer. Replay runs the
same 792 configurations as the paper artifact in a bounded worker pool. Every
configuration has a stable ID, private workspace/output staging area, and
separate log under `results/metadata/replay-logs/`.

The results directory must be new unless `--allow-existing-results` is passed
explicitly. Normal fresh replay does not need that option.

An interrupted replay can be continued without weakening that protection:

```bash
export ARTIFACT_DATA_DIR=/path/to/extracted/artifact
./generate_tables.sh --replay --resume --workers 6 /path/to/interrupted-replay
```

Resume validates the manifest, all completed outputs, and the read-only cache
snapshot. Completed jobs are skipped; interrupted attempts are archived under
`results/metadata/replay-attempts/` and retried in private workspaces.

## Deterministic Few-shot Selection

`data/fewshot_selection.json` stores the five nearest examples and cosine
similarities for every main and hard benchmark module. Keys are repository-
relative paths. Metadata records the pinned
`sentence-transformers/all-mpnet-base-v2` revision, sentence-transformers
version, maximum `k`, and SHA-256 hashes of benchmark modules and few-shot
inputs.

Replay automatically uses this cache for few-shot settings 1–5, so it does not
import or load the embedding model. Missing entries, changed inputs, or
requests above the cached maximum are errors. Ordinary experiments retain live
selection via `scripts/entry_point.py --fewshot-selection live`; cached
selection can be selected explicitly with:

```bash
python scripts/entry_point.py \
  --fewshot-selection cached \
  --fewshot-selection-cache data/fewshot_selection.json \
  ...
```
