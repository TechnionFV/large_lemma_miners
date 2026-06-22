#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--replay] [RESULTS_DIR]

Modes:
  (default)   Level 1 — generate tables from pre-computed result logs in
              \$ARTIFACT_DATA_DIR. No LLM or EBMC calls.

  --replay    Level 2 — replay the full experiment pipeline from disk caches
              (all LLM/eval calls are served from cache), then generate tables
              from the fresh outputs.

Environment:
  ARTIFACT_DATA_DIR   Path to the extracted Zenodo data directory (required).

Arguments:
  RESULTS_DIR         Output directory for tables/plots (default: ./results).
EOF
    exit 1
}

# --- Parse args ---
REPLAY=0
RESULTS_DIR=""

for arg in "$@"; do
    case "$arg" in
        --replay) REPLAY=1 ;;
        --help|-h) usage ;;
        *) RESULTS_DIR="$arg" ;;
    esac
done

RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"

if [ -z "${ARTIFACT_DATA_DIR:-}" ]; then
    echo "Error: ARTIFACT_DATA_DIR must be set to the extracted Zenodo artifact directory." >&2
    exit 1
fi

# --- Level 2: replay from caches ---
if [ "$REPLAY" -eq 1 ]; then
    echo "=== Level 2: Replaying experiments from disk caches ==="
    echo "Cache: $ARTIFACT_DATA_DIR"
    echo "Output: $RESULTS_DIR"
    echo ""

    MODELS=(gpt-5 claude-4 claude-4-5-sonnet claude-4-5-haiku claude-4-5-opus claude-4-7-opus)
    PIPELINES=(agent non_agent)
    FEWSHOTS=(0 1 2 3 4 5)
    EXPERIMENTS=(main_experiment hard)
    NUM_ITERATIONS=(1 2 3 4 5 6 7 8 9 10)

    for model in "${MODELS[@]}"; do
      for pipeline in "${PIPELINES[@]}"; do
        for fs in "${FEWSHOTS[@]}"; do
          for experiment in "${EXPERIMENTS[@]}"; do
            modules_dir="$SCRIPT_DIR/benchmarks/$experiment"
            if [ "$pipeline" = "agent" ]; then
              for ni in "${NUM_ITERATIONS[@]}"; do
                echo "[REPLAY] model=$model pipeline=$pipeline fs=$fs experiment=$experiment num_iterations=$ni"
                python "$SCRIPT_DIR/scripts/entry_point.py" \
                  -model "$model" \
                  -pipeline "$pipeline" \
                  -few_shot "$fs" \
                  -num_iterations "$ni" \
                  -modules_dir "$modules_dir" \
                  -storage_dir "$ARTIFACT_DATA_DIR" \
                  -output_dir "$RESULTS_DIR" \
                  -evaluation_cache_mode FORCE_CACHED \
                  --force_cached
              done
            else
              echo "[REPLAY] model=$model pipeline=$pipeline fs=$fs experiment=$experiment"
              python "$SCRIPT_DIR/scripts/entry_point.py" \
                -model "$model" \
                -pipeline "$pipeline" \
                -few_shot "$fs" \
                -modules_dir "$modules_dir" \
                -storage_dir "$ARTIFACT_DATA_DIR" \
                -output_dir "$RESULTS_DIR" \
                -evaluation_cache_mode FORCE_CACHED \
                --force_cached
            fi
          done
        done
      done
    done

    echo ""
    echo "=== Replay complete. Generating tables from fresh outputs... ==="
    ARTIFACT_DATA_DIR="$RESULTS_DIR" python "$SCRIPT_DIR/scripts/get_tables.py" \
        "$RESULTS_DIR/results"
else
    # --- Level 1: tables from pre-computed logs ---
    echo "=== Level 1: Generating tables from pre-computed logs ==="
    echo "Data: $ARTIFACT_DATA_DIR"
    echo "Output: $RESULTS_DIR"
    echo ""

    python "$SCRIPT_DIR/scripts/get_tables.py" "$RESULTS_DIR"
fi

echo ""
echo "=== Done. Outputs in: $RESULTS_DIR ==="
