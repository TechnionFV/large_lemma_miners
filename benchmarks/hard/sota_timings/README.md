# External SOTA timings for the `hard` benchmark

This directory ships pre-aggregated timings for the three external model-checking
tools used as baselines in Table 2 of the paper. The numbers here were collected
on the authors' machine once; the reproduction artifact merges them into
`runtime.py`'s per-module JSON via thin loaders (see `scripts/analysis/runtime.py`
— `update_json_with_ric3_times`, `update_json_with_jasper_times`,
`update_json_with_vcf`). Reproducers never re-run rIC3, JasperGold, or VCFormal.

The dev-only regeneration tool is `scripts/regenerate_sota_timings.py`; it is
not part of the reproduction pipeline.

## Files

### `ric3.json` — rIC3 timings (IC3-style model checker)

Shape: `Dict[module_name, {time, error, error_message}]`

- `time`: `float` seconds when a proof finished, `null` when the run timed out
  or errored.
- `error`: `null` on clean proofs; `"timeout"` when the one-hour limit was hit;
  `"result_false"` when rIC3 falsified the property; other string codes
  otherwise (see the parser in `regenerate_sota_timings.py`).
- `error_message`: free-text diagnostic (e.g., `"exit code 20"`).

Example (`buffer_32`):
```json
{"time": 0.01, "error": null, "error_message": "exit code 20"}
```

### `jasper.json` — Cadence JasperGold timings

Shape: `Dict[module_name, {time, error}]`

- `time`: `float` seconds when a proof finished, the literal string `"TIMEOUT"`
  when the one-hour limit was hit.
- `error`: `null` on clean proofs; `"CEX"` when Jasper reported a
  counterexample; other string codes otherwise.

Example (`buffer_32`):
```json
{"time": 188.0, "error": null}
```

### `vcf.json` — Synopsys VCFormal timings

Shape: `Dict[module_name, str]` (free-form).

- A numeric string like `"22.00"` is seconds.
- `"timeout ..."` (any capitalization) is normalized to `"TIMEOUT"` by the
  loader in `runtime.py` before being written into the output JSON.
- `"falsified"` means VCFormal reported a counterexample.

Example (`counter_66`): `"22.00"`.

## Collection provenance

- **Collection date**: approximately Q2–Q3 2025 (see the paper's camera-ready
  for the exact cutoff).
- **Hardware**: Amazon EC2 `m6i.32xlarge` (Intel Ice Lake, 128 vCPU, 512 GiB).
- **Per-query timeout**: one hour wall-clock for rIC3 and JasperGold. VCFormal
  entries include multi-hour timeouts carried over from the original run logs.
- **Tool versions**: rIC3 (authors' build, commit recorded in the paper),
  JasperGold 2024.09, VCFormal 2024.09.

## Module-name keying

Keys in every JSON match the SystemVerilog filename under
`artifact/benchmarks/hard/` with the trailing `_ebmc.sv` stripped (the same
normalization that `runtime.norm_module_key` applies before merging). For
example, `buffer_32_ebmc.sv` → key `buffer_32`.

## Overlap policy

The three modules that appear in both `main_experiment/` and `hard/`
(`ex100`, `ex8`, `gulwani_fig1a_3`) retain their rIC3/Jasper/VCF entries in
these files but are filtered out of the `hard` results tables by
`analyze_hard.py` (see Requirement 12 in the spec). Keeping the entries
lets `regenerate_sota_timings.py` be rerun end-to-end without special cases.
