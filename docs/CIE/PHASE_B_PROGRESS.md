# CIE 171 Phase B — Daylight Tests Progress

## Overview

Phase B implements CIE 171 tests 5.9–5.14, which validate sky component (SC) and external reflected component (ERC) calculations under 15 CIE standard sky types. This is ~3,000 reference data points across 6 tests.

## Step 1: CIE Sky HDR Generator — COMPLETE

**File**: `engine/cie171/cie_sky_generator.py`

Implements the 15 CIE General Sky luminance distributions from ISO 15469:2004:

```
L/L_z = [f(χ) × φ(θ_z)] / [f(θ_s) × φ(0)]

where:
    φ(θ) = 1 + a × exp(b / cos(θ))                          — gradation
    f(χ) = 1 + c × [exp(d×χ) - exp(d×π/2)] + e × cos²(χ)   — indicatrix
```

### Sky Type Parameters (ISO 15469:2004)

| Type | a | b | c | d | e | Description |
|------|---|---|---|---|---|-------------|
| 1 | 4.0 | -0.70 | 0 | -1.0 | 0.00 | CIE Standard Overcast, steep gradation |
| 2 | 4.0 | -0.70 | 2 | -1.5 | 0.15 | Overcast, steep + slight sun brightening |
| 3 | 1.1 | -0.80 | 0 | -1.0 | 0.00 | Overcast, moderate gradation |
| 4 | 1.1 | -0.80 | 2 | -1.5 | 0.15 | Overcast, moderate + slight sun brightening |
| 5 | 0.0 | -1.00 | 0 | -1.0 | 0.00 | Uniform luminance sky |
| 6 | 0.0 | -1.00 | 2 | -1.5 | 0.15 | Partly cloudy, no zenith gradation |
| 7 | 0.0 | -1.00 | 5 | -2.5 | 0.30 | Partly cloudy, brighter circumsolar |
| 8 | 0.0 | -1.00 | 10 | -3.0 | 0.45 | Partly cloudy, distinct solar corona |
| 9 | -1.0 | -0.55 | 2 | -1.5 | 0.15 | Partly cloudy, obscured sun |
| 10 | -1.0 | -0.55 | 5 | -2.5 | 0.30 | Partly cloudy, circumsolar region |
| 11 | -1.0 | -0.55 | 10 | -3.0 | 0.45 | White-blue sky, distinct solar corona |
| 12 | -1.0 | -0.32 | 10 | -3.0 | 0.45 | CIE Standard Clear, low turbidity |
| 13 | -1.0 | -0.32 | 16 | -3.0 | 0.30 | CIE Standard Clear, polluted |
| 14 | -1.0 | -0.15 | 16 | -3.0 | 0.30 | Cloudless turbid, broad corona |
| 15 | -1.0 | -0.15 | 24 | -2.8 | 0.15 | White-blue turbid, broad corona |

### Validation

- All 15 sky types generate successfully
- E_hz normalization verified: each HDRI produces exactly E_hz = 1.0 after integration
- Physical behavior confirmed:
  - Type 1 (overcast): Bright zenith (1.0), dim horizon (0.335), no sun preference
  - Type 5 (uniform): Constant 1.0 everywhere
  - Type 12 (clear): Brightest near sun (3.47), gradient across sky dome
- **Blender integration tested**: Uniform sky HDRI loaded as environment texture, baked onto holdout surface → measured pixel = 0.9940 × expected (99.4% accuracy, 0.4% std dev)

### Generated Files

- `engine/cie171/sky_hdri/cie_sky_type_01.hdr` through `_15.hdr`
- Format: Radiance HDR (RGBE), equirectangular projection
- Resolution: 1024×512 (production), 256×128 also available
- Sun position: 60° elevation, 180° azimuth (south) — matching CIE 171 test specs

### Blender Nishita Benchmarking (Future)

After Phase B validation passes with CIE HDRIs, we plan to benchmark Blender's built-in Nishita sky model against these same CIE standards. Key points:

- **Nishita** is physics-based (Rayleigh + Mie scattering, parameterized by turbidity)
- **CIE sky types** are empirical (parameterized by gradation + indicatrix coefficients)
- No clean 1:1 mapping exists between the two systems
- We'll sweep Nishita turbidity (1.0–10.0) to find best-fit per CIE type
- Output: mapping table showing accuracy tradeoff for users who want quick daylight studies vs code-compliance work

## Step 2: Reference Value Transcription — COMPLETE (2026-03-15)

All reference values from CIE Appendix B (Tables B.1–B.26) have been transcribed into the WIP files:

| Test | Tables | WIP File | Data Points |
|------|--------|----------|-------------|
| 5.9 | B.1–B.4 | `wip/test_5.9.md` + `test_cases_daylight.py` | 448 |
| 5.10 | B.5–B.8 | `wip/test_5.10.md` | 448 |
| 5.11 | B.9–B.14 | `wip/test_5.11.md` | ~560 |
| 5.12 | B.15–B.20 | `wip/test_5.12.md` | ~560 |
| 5.13 | B.21–B.23 | `wip/test_5.13.md` | 384 |
| 5.14 | B.24–B.26 | `wip/test_5.14.md` | 384 |

Also transcribed: Test 5.5 reference (Table 15) into `wip/test_5.5.md`.

## Step 3: Scene Builder Extensions — PARTIAL

### Implemented:
- [x] `build_room_with_roof_opening()` — in `runner_daylight.py`, used by Tests 5.9 and 5.10
- [x] `add_glass_panel()` — in `runner_daylight.py`, used by Test 5.10. Uses Fresnel (IOR=1.52) → (1-F)² → Transparent BSDF color. Glass plane normal must face INTO the room (`flip=True`). Cannot use Glass BSDF or Principled BSDF Transmission (opaque to shadow rays, Blender bug #54006).

### Needed for remaining tests:

**Test 5.11 (facade unglazed)**: **VALIDATED (2026-03-16)** — Partial pass
- [x] `build_room_with_facade_opening()` — opening in south wall with wall strips around it
- [x] `add_external_ground(reflectance=0.30, extent=50)` — emissive ground (L=ρ/π), not diffuse (avoids sky-blocking bias)
- [x] `run_5_11_blender()` — 3 measurement surfaces (wall_north, floor, ceiling)
- [x] Reference values (Tables B.9–B.14) in `test_cases_daylight.py`
- [x] CLI wired up: `--test 5.11 --opening 2x1|4x3`
- [x] **All 15 sky types validated for both openings** (30 render runs)
- [x] Key fixes: y-axis flip for facade points, +90° HDRI rotation for facade tests, emissive ground for ERC
- Floor SC <3.5%, ceiling ERC <5.5% (sky-independent), wall edge-sensitive 7-17% (same as 5.9/5.10)

**Test 5.12 (facade glazed)**: **VALIDATED (2026-03-16)** — Partial pass
- [x] `add_facade_glass_panel()` — vertical glass at y=-0.001, normal +Y (flip=True), Fresnel Transparent BSDF
- [x] `run_5_12_blender()` — combines 5.11 facade + glass panel
- [x] Reference values (Tables B.15–B.20) in `test_cases_daylight.py`
- [x] **All 15 sky types validated for both openings** (30 render runs)
- 4x3: 7.6-10.3% max error (wall A edge). 2x1: 15-19% (wall C + grazing-angle glass N/N')

**Test 5.13 (horizontal mask)**: **VALIDATED (2026-03-16)** — Passing (excl. CIE errata)
- [x] `add_horizontal_mask()` — two-sided material (top=black, bottom=diffuse ρ_ob=0.30)
- [x] `run_5_13_blender()` — floor-only measurement, 3 mask depths
- [x] Reference values (Tables B.21–B.23) in `test_cases_daylight.py`
- [x] CIE Fig. 24 geometry confirmed: mask at z=3, semi-infinite in x (±10m), 50mm depth margin
- [x] All 15 sky types × 3 mask depths = 45 configs tested
- [x] CIE Table B.22 errata confirmed by NVIDIA Iray (1.0m mask overcast values wrong)
- 0.5m mask: 4.9% best. 1.0m: 4.6% (excl. errata). 2.0m: 8.5%

**Test 5.14 (vertical mask)**: Add vertical fin
- `add_vertical_mask(distance=6m, height, width, reflectance)` — vertical plane perpendicular to facade
- 3 mask heights: 3m, 6m, 9m (all at 6m from facade)
- Same 8 floor points as 5.13

### Implementation order recommendation:
1. ~~**5.10** — simplest: just add glass to existing 5.9 setup~~ **DONE**
2. ~~**5.11** — new geometry (facade opening + ground plane), but no glass~~ **DONE — Partial pass**
3. ~~**5.12** — combine 5.10 glass + 5.11 facade~~ **DONE — Partial pass**
4. **5.13** — add mask to 5.11
5. ~~**5.14** — add different mask to 5.11~~ **DONE — 45 configs tested. 3m passes (1.79%); 6m/9m CIE errata (confirmed by NVIDIA)**

## Step 4: Daylight Test Runner — PARTIAL

- [x] `runner_daylight.py` — implements Test 5.9 with CLI for opening size + sky type
- [x] `run_5_10_blender()` + `add_glass_panel()` — glass panel on 5.9 scene, 15/15 types passing both openings
- [x] Extend with `run_5_11_blender()` — facade opening + ground + ceiling measurement points
- [x] Extend with `run_5_12_blender()` + `add_facade_glass_panel()` — facade + vertical glass
- [x] Extend with `run_5_13_blender()` — facade + horizontal mask + 8-point floor layout (geometry fix pending)
- [x] Extend with `run_5_14_blender()` + `add_vertical_mask()` — facade + vertical mask. 3m passes; 6m/9m CIE errata (confirmed by NVIDIA)

Each function should follow the pattern of `run_5_9_blender()` in `runner_daylight.py`.

## Step 5: Nishita Benchmarking — NOT STARTED

Sweep Nishita turbidity vs CIE sky types, produce mapping table.
