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
./generate_tables.sh --replay
```

This iterates over all `(model, pipeline, fewshot, num_iterations)` configurations and replays them from the cached LLM/evaluation responses. The outputs should match Level 1 exactly.
