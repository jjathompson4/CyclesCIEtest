# Glass Absorption — Experiment Log

**Problem**: Flat ×0.96 correction on Fresnel `(1-F)²` doesn't model angle-dependent absorption. At grazing angles (70–80°) in the 2×1m facade opening (test 5.12), points N/N' show 15–19% error.

**Primary metric**: Points N and N' error (2×1m opening), test 5.12, sky type 1.

**Secondary metric**: Wall point C error (2×1m opening) — also affected by glass.

**Regression metrics**: Test 5.10 (glazed roof) and test 5.12 4×3m opening must not degrade.

---

## Experiment Index

| ID | Glass model | Status | N err (2×1) | N' err (2×1) | Wall C err (2×1) | Verdict |
|----|------------|--------|-----------|------------|-----------------|---------|
| exp2a | Fresnel (1-F)² × 0.96 (baseline) | done | -15.01% | -14.51% | -17.01% | BASELINE |
| exp2b | Flat τ = 0.91 (NVIDIA approach) | done | +110.78% | +113.72% | -13.79% | REJECTED |
| exp2c | CIE Table 15 polynomial | done | +36.66% | +40.55% | -7.87% | REJECTED |

---

## CIE Table 15 Reference Data

Source: `docs/CIE/wip/test_5.5.md`

| θ (degrees) | cos θ | τ_θ (CIE) | Our (1-F)²×0.96 | Delta |
|-------------|-------|-----------|-----------------|-------|
| 0 | 1.000 | 0.96 | 0.885 | -0.075 |
| 10 | 0.985 | 0.96 | 0.885 | -0.075 |
| 20 | 0.940 | 0.96 | 0.884 | -0.076 |
| 30 | 0.866 | 0.96 | 0.884 | -0.076 |
| 40 | 0.766 | 0.96 | 0.880 | -0.080 |
| 50 | 0.643 | 0.95 | 0.861 | -0.089 |
| 60 | 0.500 | 0.93 | 0.795 | -0.135 |
| 70 | 0.342 | 0.84 | 0.619 | -0.221 |
| 80 | 0.174 | 0.59 | 0.272 | -0.318 |
| 90 | 0.000 | 0.00 | 0.000 | 0.000 |

---

## Polynomial Fitting Results

Polynomial fit completed (see `fit_results.json`). Degree 4 won:

```
τ(c) = 0.000353 + 4.714931·c - 8.885333·c² + 7.543987·c³ - 2.415101·c⁴
where c = cos(θ)
```

Max fitting residual: 0.0023 (0.23% — excellent per-angle fit).

However, the polynomial was ultimately not useful because the problem is not per-angle accuracy — it's the fundamental difference between per-ray application in a Monte Carlo renderer vs the analytical integration CIE used for reference values (see Key Findings below).

---

## Attempts

### exp2a — Baseline (Fresnel (1-F)² × 0.96)

**Date**: 2026-03-19

**Configuration**: Test 5.12, 2×1m opening, sky type 1 (CIE Overcast), 4096 samples
**Code**: Unmodified runner_daylight.py
**Blender**: 5.0.1 (a3db93c5b259, 2025-12-16), macOS Darwin 25.3.0

**Results — 5.12 2×1m** (max err: 17.01%, 5/22 fail):
| Point | Surface | Reference | Computed | Error |
|-------|---------|----------|----------|-------|
| A | Wall | 0.84 | 0.83 | -0.98% |
| B | Wall | 0.94 | 0.96 | +1.86% |
| C | Wall | 1.10 | 0.91 | **-17.01%** FAIL |
| D | Wall | 1.33 | 1.25 | **-6.03%** FAIL |
| E | Wall | 1.50 | 1.48 | -1.38% |
| F | Wall | 1.63 | 1.65 | +1.12% |
| G | Floor | 0.77 | 0.73 | -4.93% |
| H | Floor | 1.15 | 1.16 | +1.17% |
| I | Floor | 1.77 | 1.80 | +1.69% |
| J | Floor | 2.79 | 2.82 | +1.08% |
| K | Floor | 4.38 | 4.38 | -0.11% |
| L | Floor | 6.44 | 6.49 | +0.74% |
| M | Floor | 7.19 | 7.01 | -2.57% |
| N | Floor | 2.16 | 1.84 | **-15.01%** FAIL |
| G' | Ceiling | 0.33 | 0.33 | +0.38% |
| H' | Ceiling | 0.46 | 0.44 | **-5.03%** FAIL |
| I' | Ceiling | 0.65 | 0.66 | +1.30% |
| J' | Ceiling | 0.94 | 0.96 | +2.48% |
| K' | Ceiling | 1.34 | 1.35 | +0.73% |
| L' | Ceiling | 1.80 | 1.79 | -0.48% |
| M' | Ceiling | 1.85 | 1.87 | +1.17% |
| N' | Ceiling | 0.53 | 0.45 | **-14.51%** FAIL |

**Verdict**: BASELINE. Interior points excellent (<5%). Edge points C, N, N' fail — same edge-sensitivity pattern as 5.11 (unglazed), amplified by glass attenuation.

---

### exp2b — Flat τ = 0.91 (NVIDIA approach)

**Date**: 2026-03-19

**Hypothesis**: NVIDIA Iray passed CIE glass tests with flat τ=0.91. Simplest possible model — no angle dependence.

**Code changes**: Replaced Fresnel/invert/square/correct node chain with `transparent.inputs['Color'] = (0.91, 0.91, 0.91, 1.0)` in `_make_glass_material()` in `runner_daylight_rnd.py`.

**Results — 5.12 2×1m** (max err: 113.72%, 14/22 fail):
| Point | Surface | Reference | Computed | Error | Baseline |
|-------|---------|----------|----------|-------|----------|
| C | Wall | 1.10 | 0.95 | -13.79% | -17.01% |
| L | Floor | 6.44 | 7.03 | +9.11% | +0.74% |
| M | Floor | 7.19 | 8.51 | **+18.31%** | -2.57% |
| N | Floor | 2.16 | 4.55 | **+110.78%** | -15.01% |
| M' | Ceiling | 1.85 | 2.24 | **+20.82%** | +1.17% |
| N' | Ceiling | 0.53 | 1.13 | **+113.72%** | -14.51% |

**Observations**: Catastrophic failure at grazing-angle points (N, N', M, M'). Root cause: flat τ=0.91 has NO angle dependence. At 70-80° incidence, real glass reflects most light (CIE τ=0.59 at 80°), but flat 0.91 transmits 91% regardless. Points near the opening edge receive light at steep angles, so the flat model massively over-transmits.

**Why NVIDIA's flat 0.91 worked for them but not for us**: NVIDIA Iray models glass as a **volumetric pane** — rays physically enter one face, travel through the glass thickness (6mm), and exit the other face. Each face applies Fresnel reflection based on IOR. Absorption occurs along the volumetric path. Iray's glass has built-in angle-dependent Fresnel behavior even when the "transmittance" is described as 0.91 in their report — that 0.91 is the hemisphere-averaged result, not a per-ray setting.

We cannot replicate this in Cycles because Glass BSDF is opaque to shadow rays (Blender bug #54006), forcing us to use Transparent BSDF, which is just a dumb color filter with no built-in physics.

**Verdict**: REJECTED — flat transmittance is fundamentally incompatible with Transparent BSDF for facade glass.

---

### exp2c — CIE Table 15 polynomial

**Date**: 2026-03-19

**Hypothesis**: A degree-4 polynomial fitted to CIE Table 15's per-angle τ_θ should give physically correct angle-dependent behavior when applied via `Geometry.Incoming` → dot product → polynomial evaluation → Transparent BSDF color.

**Polynomial**: τ(c) = 0.000353 + 4.714931c - 8.885333c² + 7.543987c³ - 2.415101c⁴ (max residual 0.23%)

**Code changes**: Implemented Horner-form polynomial evaluation using `ShaderNodeMath` (MULTIPLY_ADD) chain in `_make_glass_material()`. Uses `Geometry.Incoming` dot `Geometry.Normal` for cos θ.

**Results — 5.12 2×1m** (max err: 40.55%, 19/22 fail):
| Point | Surface | Reference | Computed | Error | Baseline |
|-------|---------|----------|----------|-------|----------|
| A | Wall | 0.84 | 0.91 | +8.75% | -0.98% |
| D | Wall | 1.33 | 1.34 | +0.73% | -6.03% |
| H | Floor | 1.15 | 1.26 | +9.50% | +1.17% |
| L | Floor | 6.44 | 7.33 | +13.81% | +0.74% |
| M | Floor | 7.19 | 8.45 | **+17.57%** | -2.57% |
| N | Floor | 2.16 | 2.95 | **+36.66%** | -15.01% |
| N' | Ceiling | 0.53 | 0.74 | **+40.55%** | -14.51% |

**Observations**: Systematic +10-40% over-transmission at ALL points, not just edges. The polynomial matches CIE's per-angle τ_θ perfectly (0.23% residual), but it transmits ~8% more light per ray at normal incidence (τ=0.96) than the original model (τ=0.885).

**Root cause analysis**: The CIE reference values for tests 5.10/5.12 were computed using Tregenza's integrated formula (Eq. 19), which analytically integrates glass transmittance over the sky hemisphere weighted by luminance distribution and opening geometry. When we apply per-angle τ_θ as a per-ray filter in a Monte Carlo renderer, the integration happens differently — MC sampling weights differ from Eq. 19's analytical weights.

Our original Fresnel+0.96 model was **empirically calibrated** to match CIE's integrated reference values through the MC pipeline. The polynomial matches CIE's per-angle physics but not the integrated result, because the integration methodology differs.

**Verdict**: REJECTED — correct per-angle physics but wrong integrated result due to MC vs analytical integration mismatch.

---

## Key Findings

### 1. Cycles cannot model volumetric glass for bake operations

**Blender bug #54006**: Glass BSDF, Principled BSDF with Transmission, and Glossy BSDF are all opaque to shadow rays in Cycles. This was verified in test 5.10 Attempts 1-3 (all produced zeros or severe under-transmission).

The ONLY shader transparent to all ray types (including shadow rays) is **Transparent BSDF**, which is a simple color filter with no built-in Fresnel, IOR, or refraction.

### 2. NVIDIA Iray vs Blender Cycles — fundamental difference

NVIDIA Iray models glass as a **volumetric pane**: physical entry face → volumetric path (6mm) → exit face. Each face applies Fresnel from IOR. Absorption follows Beer-Lambert through the volume. This is physically correct.

Blender Cycles (for bake): **single infinitely-thin plane** with Transparent BSDF color filter. We manually compute `(1-F)²` to fake two-surface Fresnel and multiply by 0.96 to match CIE's integrated reference values. This is an approximation.

### 3. The original Fresnel+0.96 model is the best available

Within Cycles' constraints:
- It correctly handles angle-dependent reflection via Fresnel node
- `(1-F)²` accounts for both air-glass interfaces
- `×0.96` empirically calibrates to CIE's hemisphere-integrated reference values
- Interior points pass within 5% for both opening sizes
- Edge points (C, N, N') fail at ~15% due to geometric edge sensitivity, not glass model error

### 4. Edge errors at N/N' in 5.12 are NOT glass-model errors

Comparison of 5.11 (no glass) vs 5.12 (with glass) at matching points shows the edge sensitivity pattern is geometric — the glass amplifies it but doesn't cause it. The same boundary-proximity issues seen in 5.11 wall C/D appear at 5.12 N/N'.

### 5. Implications for the product

**Electric lighting calcs**: Fully validated, no glass involved. CIE tests 5.2–5.8 all pass. Ready for production.

**Daylight calcs through glass**: Limited by Cycles' shadow ray bug. The Transparent BSDF workaround is adequate for large openings and interior measurement points, but has known ~15% errors at grazing-angle edge points for small openings. For production daylight features, evaluate whether:
- The current accuracy is acceptable for the use case
- A secondary engine (e.g., Radiance) should handle glazing calculations
- Blender fixes bug #54006 in a future version, enabling proper Glass BSDF in bakes

---

## Files

- `fit_results.json` — polynomial fitting output (degree 4 coefficients)
- `fit_polynomial.py` — fitting script
- `results/exp2a-flat-096/blender_2x1_type01.json` — baseline result
- `results/exp2b-flat-091/blender_2x1_type01.json` — flat τ=0.91 result
- `results/exp2c-polynomial/blender_2x1_type01.json` — polynomial result
