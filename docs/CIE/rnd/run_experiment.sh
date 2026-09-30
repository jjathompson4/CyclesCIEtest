#!/bin/bash
# ─────────────────────────────────────────────────────────────
# R&D Experiment Runner
# ─────────────────────────────────────────────────────────────
#
# Usage:
#   ./run_experiment.sh <experiment_id> [--full]
#
# Examples:
#   ./run_experiment.sh exp1a          # Edge accuracy baseline (minimal: type 1 only)
#   ./run_experiment.sh exp1c          # Edge accuracy: 1024px, kernel ±1
#   ./run_experiment.sh exp2b          # Glass: flat τ=0.91
#   ./run_experiment.sh exp1c --full   # Run all 15 sky types (slow)
#   ./run_experiment.sh combined       # Run full regression suite with current runner
#
# Before running:
#   1. Make the code changes described in the experiment log
#   2. Verify with: grep -n 'wall_res\|kernel\|0\.96\|0\.91' runner_daylight.py
#
# Output:
#   Results are saved to the experiment's results/ subdirectory
# ─────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENGINE_DIR="$PROJECT_ROOT/engine"
RUNNER="cie171/runner_daylight.py"
RND_DIR="$SCRIPT_DIR"

EXP_ID="${1:-}"
FULL_MODE="${2:-}"

if [ -z "$EXP_ID" ]; then
    echo "Usage: $0 <experiment_id> [--full]"
    echo ""
    echo "Edge accuracy experiments:"
    echo "  exp1a  — Baseline (512px, kernel ±3)"
    echo "  exp1b  — 1024px, kernel ±3"
    echo "  exp1c  — 1024px, kernel ±1"
    echo "  exp1d  — 2048px, kernel ±1"
    echo "  exp1e  — 1024px, no kernel"
    echo ""
    echo "Glass absorption experiments:"
    echo "  exp2a  — Baseline (Fresnel (1-F)² × 0.96)"
    echo "  exp2b  — Flat τ = 0.91"
    echo "  exp2c  — Polynomial τ(cos θ)"
    echo ""
    echo "Combined:"
    echo "  combined — Full regression with both fixes"
    echo ""
    echo "Options:"
    echo "  --full  — Run all 15 sky types (default: type 1 only)"
    exit 1
fi

# ── Determine sky types to run ──
if [ "$FULL_MODE" = "--full" ]; then
    SKY_TYPES=$(seq 1 15)
    echo "Mode: FULL (all 15 sky types)"
else
    SKY_TYPES="1"
    echo "Mode: MINIMAL (sky type 1 only)"
fi

# ── Helper: run a single test ──
run_test() {
    local test_id="$1"
    local opening="$2"
    local sky_type="$3"
    local results_dir="$4"

    echo ""
    echo "━━━ Test $test_id | Opening $opening | Sky type $sky_type ━━━"

    cd "$ENGINE_DIR"
    blender --background --python "$RUNNER" -- \
        --test "$test_id" --opening "$opening" --sky-type "$sky_type"

    # Copy result JSON to experiment results dir
    local src_dir="$SCRIPT_DIR/../results/test_${test_id}"
    local json_file="blender_${opening}_type$(printf '%02d' "$sky_type").json"

    if [ -f "$src_dir/$json_file" ]; then
        cp "$src_dir/$json_file" "$results_dir/"
        echo "  → Saved to $results_dir/$json_file"
    else
        echo "  ⚠ Result file not found: $src_dir/$json_file"
        # Try alternate naming
        local alt_file="blender_${opening}_type${sky_type}.json"
        if [ -f "$src_dir/$alt_file" ]; then
            cp "$src_dir/$alt_file" "$results_dir/"
            echo "  → Saved (alt name) to $results_dir/$alt_file"
        fi
    fi
}

# ── Edge accuracy experiments ──
run_edge_experiment() {
    local exp_dir_name="$1"
    local results_dir="$RND_DIR/edge-accuracy/results/$exp_dir_name"
    mkdir -p "$results_dir"

    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  Edge Accuracy: $EXP_ID                     ║"
    echo "╚══════════════════════════════════════════════╝"
    echo "Results → $results_dir"

    # Print current config for verification
    echo ""
    echo "Current runner config (verify before proceeding):"
    cd "$ENGINE_DIR"
    grep -n 'wall_res\|floor_res\|ceil_res\|kernel =' "$RUNNER" | head -20
    echo ""
    read -p "Config looks correct? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Make code changes first, then re-run."
        exit 1
    fi

    local start_time=$(date +%s)

    for sky in $SKY_TYPES; do
        run_test 5.11 4x3 "$sky" "$results_dir"
        run_test 5.11 2x1 "$sky" "$results_dir"
    done

    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    echo ""
    echo "Total time: ${elapsed}s ($(( elapsed / 60 ))m $(( elapsed % 60 ))s)"
    echo "$elapsed" > "$results_dir/timing.txt"
}

# ── Glass absorption experiments ──
run_glass_experiment() {
    local exp_dir_name="$1"
    local results_dir="$RND_DIR/glass-absorption/results/$exp_dir_name"
    mkdir -p "$results_dir"

    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  Glass Absorption: $EXP_ID                  ║"
    echo "╚══════════════════════════════════════════════╝"
    echo "Results → $results_dir"

    # Print current config for verification
    echo ""
    echo "Current glass config (verify before proceeding):"
    cd "$ENGINE_DIR"
    grep -n '0\.96\|0\.91\|Fresnel\|transparent.*Color\|polynomial' "$RUNNER" | head -20
    echo ""
    read -p "Config looks correct? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Make code changes first, then re-run."
        exit 1
    fi

    local start_time=$(date +%s)

    # Primary: 5.12 2×1m (worst case for grazing angles)
    for sky in $SKY_TYPES; do
        run_test 5.12 2x1 "$sky" "$results_dir"
    done

    # Regression: 5.12 4×3m and 5.10 4×4 (type 1 only for regression)
    run_test 5.12 4x3 1 "$results_dir"
    run_test 5.10 4x4 1 "$results_dir"

    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    echo ""
    echo "Total time: ${elapsed}s ($(( elapsed / 60 ))m $(( elapsed % 60 ))s)"
    echo "$elapsed" > "$results_dir/timing.txt"
}

# ── Combined regression suite ──
run_combined() {
    local results_dir="$RND_DIR/combined/results"
    mkdir -p "$results_dir"

    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  Combined Fix — Full Regression Suite       ║"
    echo "╚══════════════════════════════════════════════╝"
    echo "Results → $results_dir"

    local start_time=$(date +%s)

    # 5.11 — both openings, all sky types
    for sky in $SKY_TYPES; do
        run_test 5.11 4x3 "$sky" "$results_dir"
        run_test 5.11 2x1 "$sky" "$results_dir"
    done

    # 5.12 — both openings, all sky types
    for sky in $SKY_TYPES; do
        run_test 5.12 4x3 "$sky" "$results_dir"
        run_test 5.12 2x1 "$sky" "$results_dir"
    done

    # 5.9 and 5.10 — spot check (types 1, 5, 12)
    for sky in 1 5 12; do
        run_test 5.9  1x1 "$sky" "$results_dir"
        run_test 5.9  4x4 "$sky" "$results_dir"
        run_test 5.10 1x1 "$sky" "$results_dir"
        run_test 5.10 4x4 "$sky" "$results_dir"
    done

    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    echo ""
    echo "══════════════════════════════════════════════"
    echo "Combined regression complete."
    echo "Total time: ${elapsed}s ($(( elapsed / 60 ))m $(( elapsed % 60 ))s)"
    echo "$elapsed" > "$results_dir/timing.txt"
}

# ── Dispatch ──
case "$EXP_ID" in
    exp1a) run_edge_experiment "exp1a-512-k3" ;;
    exp1b) run_edge_experiment "exp1b-1024-k3" ;;
    exp1c) run_edge_experiment "exp1c-1024-k1" ;;
    exp1d) run_edge_experiment "exp1d-2048-k1" ;;
    exp1e) run_edge_experiment "exp1e-1024-k0" ;;
    exp2a) run_glass_experiment "exp2a-flat-096" ;;
    exp2b) run_glass_experiment "exp2b-flat-091" ;;
    exp2c) run_glass_experiment "exp2c-polynomial" ;;
    combined) run_combined ;;
    *)
        echo "Unknown experiment: $EXP_ID"
        echo "Run $0 without arguments for usage."
        exit 1
        ;;
esac

echo ""
echo "Done. Next steps:"
echo "  1. Review results in the experiment's results/ directory"
echo "  2. Fill in the experiment-log.md entry with results"
echo "  3. Update the experiment index table"
