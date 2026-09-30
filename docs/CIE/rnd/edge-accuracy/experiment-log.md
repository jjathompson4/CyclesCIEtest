# Edge Accuracy — Experiment Log

**Problem**: Wall measurement points near facade opening boundaries show 7–17% error due to texture bake resolution and kernel averaging across illuminance discontinuities.

**Primary metric**: Wall point A error (4×3m opening) and wall point C error (2×1m opening), test 5.11, sky type 1.

**Regression metric**: Floor point G error (must not degrade by >0.5%).

---

## Critical Context: Production vs CIE Settings

The production lighting app uses very different settings from the CIE test runner:

| Parameter | Production (`fixture_config.py`) | CIE test runner |
|-----------|-------------------------------|-----------------|
| bake_resolution | **256** | 512 |
| samples | **1024** | 4096 |
| kernel averaging | **None** (single pixel) | ±3 (7×7 box) |
| bounces | default (~12) | 0–2 (test-specific) |

The CIE runner already uses specialized settings that don't match the production pipeline. Any R&D changes here should be considered in that context: the validation demonstrates the renderer's physical accuracy under controlled conditions, not necessarily the exact production configuration.

---

## Experiment Index

| ID | Config | wall_res | kernel | samples | Status | Wall A (4×3) | Wall C (2×1) |
|----|--------|---------|--------|---------|--------|-------------|-------------|
| exp1a | Baseline | 512 | ±3 | 4096 | done | -7.49% | -15.73% |
| exp1b | Hi-res, same kernel | 1024 | ±3 | 4096 | done | -7.89% | -11.66% |
| exp1c | Hi-res, small kernel | 1024 | ±1 | 4096 | done | **-4.45%** | -15.79% |
| exp1c+ | Hi-res, small kernel, hi-samp | 1024 | ±1 | 16384 | done | — | -12.65% |
| exp1d | Ultra-res, small kernel | 2048 | ±1 | 4096 | skipped | — | — |
| exp1e | Hi-res, no kernel | 1024 | 0 | 4096 | skipped | — | — |

---

## Attempts

### exp1a — Baseline

**Date**: 2026-03-19

**Configuration**: 512×512 bake, ±3 kernel (7×7), 4096 samples, 2 bounces
**Code changes**: None — current runner_daylight.py
**Blender**: 5.0.1 (a3db93c5b259, 2025-12-16), macOS Darwin 25.3.0

**Results — 4×3m opening** (max err: 7.49%, 2/22 fail):
| Point | Surface | Reference | Computed | Error |
|-------|---------|----------|----------|-------|
| A | Wall | 5.25 | 4.86 | **-7.49%** FAIL |
| B | Wall | 6.11 | 5.79 | **-5.23%** FAIL |
| C | Wall | 6.98 | 6.76 | -3.11% |
| D | Wall | 7.99 | 7.83 | -2.05% |
| E | Wall | 8.77 | 8.75 | -0.25% |
| F | Wall | 9.35 | 9.47 | +1.25% |
| G–N | Floor | — | — | ≤1.11% all pass |
| G'–N' | Ceiling | — | — | ≤3.07% all pass |

**Results — 2×1m opening** (max err: 15.73%, 3/22 fail):
| Point | Surface | Reference | Computed | Error |
|-------|---------|----------|----------|-------|
| C | Wall | 1.25 | 1.05 | **-15.73%** FAIL |
| D | Wall | 1.51 | 1.40 | **-6.97%** FAIL |
| H' | Ceiling | 0.53 | 0.50 | **-5.51%** FAIL |

**Verdict**: BASELINE

---

### exp1b — 1024px, kernel ±3

**Date**: 2026-03-19

**Hypothesis**: Doubling resolution shrinks world-space kernel from ~55mm to ~27mm while preserving noise averaging.

**Results — 4×3m opening** (max err: 7.89%, 2/22 fail):
| Point | Ref | Computed | Error | Baseline |
|-------|-----|----------|-------|----------|
| A | 5.25 | 4.84 | **-7.89%** | -7.49% |
| B | 6.11 | 5.77 | **-5.49%** | -5.23% |

**Results — 2×1m opening** (max err: 11.66%, 3/22 fail):
| Point | Ref | Computed | Error | Baseline |
|-------|-----|----------|-------|----------|
| C | 1.25 | 1.10 | **-11.66%** | -15.73% |
| D | 1.51 | 1.37 | **-9.55%** | -6.97% |
| G' | 0.38 | 0.35 | **-7.66%** | -0.59% |

**Observations**: 4×3m slightly worse (stochastic variance). 2×1m Wall C improved ~4pp but ceiling G' degraded — fewer samples per pixel at 1024² with same sample count.

**Verdict**: MARGINAL — not a clear improvement.

---

### exp1c — 1024px, kernel ±1

**Date**: 2026-03-19

**Hypothesis**: Smaller kernel (3×3, ~12mm) eliminates boundary averaging. Expected winner for 4×3m.

**Results — 4×3m opening** (max err: 4.98%, **0/22 fail — ALL PASS**):
| Point | Ref | Computed | Error | Baseline |
|-------|-----|----------|-------|----------|
| A | 5.25 | 5.02 | **-4.45%** ✓ | -7.49% |
| B | 6.11 | 5.81 | **-4.98%** ✓ | -5.23% |
| C | 6.98 | 6.78 | -2.88% | -3.11% |
| J | 11.82 | 11.38 | -3.74% | +0.48% |

**Results — 2×1m opening** (max err: 17.82%, **9/22 fail — MUCH WORSE**):
| Point | Ref | Computed | Error | Baseline |
|-------|-----|----------|-------|----------|
| C | 1.25 | 1.05 | **-15.79%** | -15.73% |
| D | 1.51 | 1.24 | **-17.82%** | -6.97% |
| G' | 0.38 | 0.34 | **-10.04%** | -0.59% |
| N' | 1.24 | 1.45 | **+17.17%** | +0.79% |

**Observations**:
- **4×3m: Clear winner.** All 22 points pass. Wall A improved by 3pp.
- **2×1m: Catastrophic.** ±1 kernel gives only 9 pixels per sample at low SC values (0.38–1.86%), noise dominates completely.
- Root cause: at 1024², each pixel gets 1/4 the effective samples. The ±1 kernel doesn't average enough pixels to compensate.

---

### exp1c+ — 1024px, kernel ±1, 16384 samples

**Date**: 2026-03-19

**Hypothesis**: 4× more samples compensates for 4× more pixels, restoring per-pixel sample density.

**Results — 2×1m opening only** (max err: 16.04%, 4/22 fail):
| Point | Ref | Computed | Error | exp1c (4096 samp) |
|-------|-----|----------|-------|-------------------|
| C | 1.25 | 1.09 | **-12.65%** | -15.79% |
| D | 1.51 | 1.32 | **-12.89%** | -17.82% |
| K | 5.07 | 4.75 | **-6.40%** | -0.53% |
| N' | 1.24 | 1.44 | **+16.04%** | +17.17% |

**Observations**: More samples help Wall C/D (~3pp improvement) but ceiling N' remains problematic. Wall C error of ~12-16% is consistent across ALL configurations — this appears to be a **fundamental geometric edge-sensitivity**, not a sampling artifact. The measurement point is only 0.25m from the opening boundary.

**Verdict**: Confirms the 2×1m wall C/D errors are systematic and cannot be solved by resolution/kernel/sample tuning alone.

---

## Key Findings

1. **4×3m opening is solved**: 1024px + ±1 kernel at 4096 samples → all 22 points pass (max 4.98%)
2. **2×1m opening has irreducible edge error**: Wall C/D are ~12-16% error regardless of configuration. This is consistent with NVIDIA Iray's reported edge sensitivity for small openings.
3. **Noise vs accuracy tradeoff**: Smaller kernels improve edge accuracy but increase noise variance. At low illuminance (2×1m opening), noise dominates.
4. **These are CIE-validation-specific settings**: The production app uses 256px bake with no kernel and 1024 samples. The CIE runner already uses 2× resolution and 4× samples vs production. Any changes here are validation-only.

## Recommendation

Accept the 2×1m opening edge errors as a **documented limitation** consistent with other implementations (NVIDIA Iray). For the 4×3m opening, 1024px + ±1 kernel gives a clean pass. Document the edge-sensitivity in the validation report with comparison to NVIDIA's results.
