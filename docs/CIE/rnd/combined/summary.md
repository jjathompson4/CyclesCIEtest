# R&D Summary — Edge Accuracy & Glass Absorption

**Date**: 2026-03-19
**Status**: COMPLETE — recommendations finalized

---

## Executive Summary

Two systematic errors were investigated:

1. **Wall-edge accuracy** (7–17% at boundary points): **Partially solved.** 1024px bake + ±1 kernel fixes the 4×3m opening (all points pass). The 2×1m opening has irreducible ~12-16% edge error that is geometric, not sampling-related. Consistent with NVIDIA Iray's reported edge sensitivity.

2. **Angle-dependent glass absorption** (15–19% at grazing angles): **Cannot be improved** within Cycles' constraints. Blender bug #54006 prevents using Glass BSDF for bake operations. Our Transparent BSDF + manual Fresnel workaround is the best available model. Both alternative approaches (flat τ=0.91, CIE polynomial) performed worse.

---

## Findings That Inform Production

### Electric Lighting: Ship As-Is

CIE tests 5.2–5.8 validate the core physics for electric lighting calculations:
- Point sources (5.2): 0.99% max error
- Area sources (5.3): 4.94% max error
- Flux conservation (5.4): 0.28% max error
- Diffuse reflection (5.6): 0.25% max error
- Internal obstructions (5.7): 1.07% max error
- Multi-bounce interreflection (5.8): 1.79% max error (ρ ≤ 0.80)

No glass in the light path. No edge-sensitivity issues (smooth illuminance distributions from IES fixtures). Current production settings are appropriate.

### Daylight: Cycles Has Fundamental Glass Limitation

The Transparent BSDF workaround for glass is adequate for validation but has a known accuracy ceiling. For production daylight features, either:
1. Accept the limitation for large windows (4×3m test passes)
2. Use a secondary engine (Radiance) for glazing calculations
3. Wait for Blender to fix bug #54006

### Production Pipeline Settings

| Parameter | Electric (current) | Daylight (future) | CIE validation |
|-----------|-------------------|-------------------|----------------|
| bake_resolution | **256** | 512 (near openings) | 512–1024 |
| RENDER_SAMPLES | **1024** | 4096 | 4096 |
| kernel | **0** (single pixel) | ±1 (3×3) | ±1 to ±3 |
| MAX_BOUNCES | None (~12) | 2+ | test-specific |

**Rationale**: Electric calcs have smooth illuminance fields from IES fixtures — low resolution and no kernel are fine. Daylight calcs have sharp discontinuities at opening boundaries and noisier sky illumination — higher resolution, more samples, and mild kernel averaging are needed.

**Do NOT change production electric settings** based on this R&D. The current 256px/1024 sample config is validated and performant. Only adjust when implementing daylight features.

---

## Experiments Conducted

### Edge Accuracy (4 experiments)

| ID | Config | 4×3m Wall A | 2×1m Wall C | Result |
|----|--------|------------|------------|--------|
| exp1a | 512px, ±3, 4096 samp | -7.49% | -15.73% | Baseline |
| exp1b | 1024px, ±3, 4096 samp | -7.89% | -11.66% | Marginal |
| exp1c | 1024px, ±1, 4096 samp | **-4.45%** | -15.79% | **Winner (4×3)** |
| exp1c+ | 1024px, ±1, 16384 samp | — | -12.65% | Noise-limited |

**Key insight**: Resolution + kernel improvements only help when illuminance values are high enough for clean signal. Low-SC points near small openings are noise-dominated regardless of settings.

### Glass Absorption (3 experiments)

| ID | Glass model | 2×1m N error | 2×1m N' error | Result |
|----|------------|-------------|--------------|--------|
| exp2a | Fresnel (1-F)² × 0.96 | -15.01% | -14.51% | Baseline (best) |
| exp2b | Flat τ = 0.91 | +110.78% | +113.72% | Rejected |
| exp2c | CIE polynomial τ(cos θ) | +36.66% | +40.55% | Rejected |

**Key insight**: The problem is not the glass model math — it's that Cycles can only use Transparent BSDF (a color filter) instead of volumetric Glass BSDF (which handles Fresnel + refraction + absorption physically). NVIDIA Iray doesn't have this limitation because its Glass BSDF works correctly with all ray types.

---

## Code Artifacts

All experiments used `runner_daylight_rnd.py` (copy of original, not modifying production code).

| File | Purpose |
|------|---------|
| `engine/cie171/runner_daylight_rnd.py` | R&D runner with CLI params for bake_res, kernel, samples, glass_model |
| `docs/CIE/rnd/runner_daylight_original.py` | Pristine backup of original runner |
| `docs/CIE/rnd/glass-absorption/fit_polynomial.py` | CIE Table 15 polynomial fitting script |
| `docs/CIE/rnd/glass-absorption/fit_results.json` | Polynomial coefficients (degree 4) |

**Original production code is untouched.** No changes were made to `runner_daylight.py`, `calc_grid_bake.py`, `fixture_config.py`, or `scene_builder.py`.

---

## Recommendations for Next Steps

1. **Continue CIE validation** with existing settings for remaining tests (5.5, 5.6 scenarios 1+3, Section 4)
2. **Write the formal validation report** — enough data exists for a credible report covering 11 test cases
3. **Document edge-sensitivity and glass limitations** as known deviations in the report, citing NVIDIA's similar findings
4. **Do not change production pipeline settings** until daylight features are being developed
5. **When implementing daylight**: evaluate Radiance for glazing calculations as an alternative/complement to Cycles
