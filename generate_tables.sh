#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--replay] [--resume] [--workers N] [--allow-existing-results] [RESULTS_DIR]

Modes:
  (default)   Level 1 — generate tables from pre-computed result logs in
              \$ARTIFACT_DATA_DIR. No LLM or EBMC calls.

  --replay    Level 2 — replay the full experiment pipeline from disk caches
              (all LLM/eval calls are served from cache), then generate tables
              from the fresh outputs.

  --workers N Number of bounded replay workers (default: 1). N must be a
              positive integer. Agent iteration jobs sharing one cache are
              serialized even when N is greater than one.

  --resume    Resume an interrupted --replay in its existing RESULTS_DIR.
              Completed jobs are validated and skipped. This does not require
              or imply --allow-existing-results.

  --allow-existing-results
              Allow RESULTS_DIR to exist. Existing files may be replaced.
              Without this flag, the script refuses to use an existing path.

Environment:
  ARTIFACT_DATA_DIR   Path to the extracted Zenodo data directory (required).
  PYTHON              Python interpreter to use (default: python3).

Arguments:
  RESULTS_DIR         New output directory for tables/plots (default: ./results).
EOF
    exit 0
}

# --- Parse args ---
REPLAY=0
RESUME=0
WORKERS=1
ALLOW_EXISTING_RESULTS=0
RESULTS_DIR=""

while [ "$#" -gt 0 ]; do
    arg="$1"
    case "$arg" in
        --replay) REPLAY=1 ;;
        --resume) RESUME=1 ;;
        --workers)
            if [ "$#" -lt 2 ]; then
                echo "Error: --workers requires a positive integer." >&2
                exit 2
            fi
            WORKERS="$2"
            shift
            ;;
        --workers=*)
            WORKERS="${arg#*=}"
            ;;
        --allow-existing-results) ALLOW_EXISTING_RESULTS=1 ;;
        --help|-h) usage ;;
        --*)
            echo "Error: unknown option '$arg'." >&2
            echo "Run $(basename "$0") --help for usage." >&2
            exit 2
            ;;
        *)
            if [ -n "$RESULTS_DIR" ]; then
                echo "Error: only one RESULTS_DIR may be specified." >&2
                exit 2
            fi
            RESULTS_DIR="$arg"
            ;;
    esac
    shift
done

case "$WORKERS" in
    ''|*[!0-9]*)
        echo "Error: --workers must be a positive integer; got '$WORKERS'." >&2
        exit 2
        ;;
esac
if [ "$WORKERS" -eq 0 ]; then
    echo "Error: --workers must be a positive integer; got '$WORKERS'." >&2
    exit 2
fi

if [ "$REPLAY" -eq 0 ] && [ "$WORKERS" -ne 1 ]; then
    echo "Error: --workers is only valid with --replay." >&2
    exit 2
fi
if [ "$RESUME" -eq 1 ] && [ "$REPLAY" -eq 0 ]; then
    echo "Error: --resume requires --replay." >&2
    exit 2
fi
if [ "$RESUME" -eq 1 ] && [ "$ALLOW_EXISTING_RESULTS" -eq 1 ]; then
    echo "Error: --resume and --allow-existing-results are mutually exclusive." >&2
    exit 2
fi

RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"

if [ -z "${ARTIFACT_DATA_DIR:-}" ]; then
    echo "Error: ARTIFACT_DATA_DIR must be set to the extracted Zenodo artifact directory." >&2
    exit 1
fi

if [ ! -d "$ARTIFACT_DATA_DIR" ]; then
    echo "Error: ARTIFACT_DATA_DIR is not a directory: $ARTIFACT_DATA_DIR" >&2
    exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Error: Python interpreter '$PYTHON_BIN' was not found." >&2
    echo "Set PYTHON to the interpreter where requirements.txt is installed." >&2
    exit 1
fi

if [ "$RESUME" -eq 1 ]; then
    if [ ! -d "$RESULTS_DIR" ]; then
        echo "Error: resume results directory does not exist: $RESULTS_DIR" >&2
        exit 1
    fi
    if [ ! -f "$RESULTS_DIR/results/metadata/replay-manifest.json" ] ||
       [ ! -d "$RESULTS_DIR/.replay/cache-snapshot" ]; then
        echo "Error: RESULTS_DIR is not an interrupted replay checkpoint: $RESULTS_DIR" >&2
        exit 1
    fi
elif [ "$ALLOW_EXISTING_RESULTS" -eq 0 ]; then
    if [ -e "$RESULTS_DIR" ] || [ -L "$RESULTS_DIR" ]; then
        echo "Error: results path already exists: $RESULTS_DIR" >&2
        echo "Choose a new RESULTS_DIR. To intentionally reuse it, pass --allow-existing-results." >&2
        exit 1
    fi

    mkdir -p "$(dirname "$RESULTS_DIR")"
    if ! mkdir "$RESULTS_DIR"; then
        echo "Error: could not create new results directory: $RESULTS_DIR" >&2
        exit 1
    fi
elif [ -e "$RESULTS_DIR" ] && [ ! -d "$RESULTS_DIR" ]; then
    echo "Error: results path exists but is not a directory: $RESULTS_DIR" >&2
    exit 1
else
    mkdir -p "$RESULTS_DIR"
fi

RUNTIME_CACHE_DIR="${RESULTS_DIR}/.runtime-cache"
mkdir -p "$RUNTIME_CACHE_DIR/matplotlib" "$RUNTIME_CACHE_DIR/fontconfig"
export MPLBACKEND="${MPLBACKEND:-Agg}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-$RUNTIME_CACHE_DIR/matplotlib}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$RUNTIME_CACHE_DIR}"

# --- Level 2: replay from caches ---
if [ "$REPLAY" -eq 1 ]; then
    REPLAY_START_SECONDS=$SECONDS
    echo "=== Level 2: Replaying experiments from disk caches ==="
    echo "Cache: $ARTIFACT_DATA_DIR"
    echo "Output: $RESULTS_DIR"
    echo ""

    echo "Workers: $WORKERS"
    COORDINATOR_ARGS=(
        --artifact-data-dir "$ARTIFACT_DATA_DIR" \
        --results-dir "$RESULTS_DIR" \
        --python "$PYTHON_BIN" \
        --workers "$WORKERS" \
        --selection-cache "$SCRIPT_DIR/data/fewshot_selection.json"
    )
    if [ "$RESUME" -eq 1 ]; then
        COORDINATOR_ARGS+=(--resume)
    fi
    "$PYTHON_BIN" "$SCRIPT_DIR/scripts/replay_coordinator.py" \
        "${COORDINATOR_ARGS[@]}"

    echo ""
    echo "=== Worker pool terminated. Generating tables from fresh outputs... ==="
    ARTIFACT_DATA_DIR="$RESULTS_DIR" "$PYTHON_BIN" "$SCRIPT_DIR/scripts/get_tables.py" \
        "$RESULTS_DIR/results"
    if grep -q '^\[WARNING\]' "$RESULTS_DIR/results/metadata/build.log"; then
        echo "Error: table generation completed with warnings; see build.log." >&2
        exit 1
    fi
    REPLAY_TOTAL_SECONDS=$((SECONDS - REPLAY_START_SECONDS))
    printf '%s\n' "$REPLAY_TOTAL_SECONDS" \
        > "$RESULTS_DIR/results/metadata/replay-total-elapsed-seconds.txt"
else
    # --- Level 1: tables from pre-computed logs ---
    echo "=== Level 1: Generating tables from pre-computed logs ==="
    echo "Data: $ARTIFACT_DATA_DIR"
    echo "Output: $RESULTS_DIR"
    echo ""

    "$PYTHON_BIN" "$SCRIPT_DIR/scripts/get_tables.py" "$RESULTS_DIR"
fi

echo ""
echo "=== Done. Outputs in: $RESULTS_DIR ==="
