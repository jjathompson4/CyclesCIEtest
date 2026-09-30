# Glass Absorption — Experiment Analysis

## Comparison Table

| Config | Glass model | N err (2×1) | N' err (2×1) | Wall C err (2×1) | Interior avg err | Verdict |
|--------|------------|-----------|------------|-----------------|-----------------|---------|
| exp2a (baseline) | Fresnel (1-F)² × 0.96 | -15.01% | -14.51% | -17.01% | ~2% | BEST AVAILABLE |
| exp2b | Flat τ = 0.91 | +110.78% | +113.72% | -13.79% | ~6% | REJECTED |
| exp2c | Polynomial τ(cos θ) | +36.66% | +40.55% | -7.87% | ~10% | REJECTED |

## Winner

**exp2a (baseline)** — The original Fresnel (1-F)² × 0.96 model remains the best available glass model within Cycles' constraints. No alternative improves on it.

## Why Neither Alternative Worked

### Flat τ = 0.91 (exp2b)
- Transparent BSDF is a dumb color filter — no built-in Fresnel
- At grazing angles, flat 0.91 transmits 91% while real glass reflects most light
- Points near opening edges receive steep-angle light → catastrophic over-transmission
- NVIDIA passed with "flat 0.91" because Iray's Glass BSDF has built-in Fresnel even with a flat setting — the 0.91 was a hemisphere-averaged result, not a per-ray color

### Polynomial (exp2c)
- Matches CIE Table 15 per-angle τ_θ perfectly (0.23% residual)
- But transmits ~8% more per ray at normal incidence (0.96 vs 0.885)
- CIE reference values for 5.10/5.12 were computed via Tregenza's analytical integration (Eq. 19), which weights angles differently than Monte Carlo sampling
- Original model's (1-F)² × 0.96 was empirically calibrated to match the MC-integrated result against CIE references — the polynomial doesn't have this calibration

## Root Cause: Cycles Limitation

**Blender bug #54006**: Glass BSDF is opaque to shadow rays in Cycles bake operations. This forces us to use Transparent BSDF, which has no built-in glass physics. We manually add Fresnel via shader math nodes and empirically calibrate to CIE references.

This is a **fundamental architectural limitation** of Cycles for glass-based daylighting calculations. It cannot be solved by better shader math — it requires Blender to fix the shadow ray handling for Glass BSDF.

## Recommended Integration

**No changes to the production glass model.** The original Fresnel (1-F)² × 0.96 is the best available.

## Impact on Product Strategy

| Feature | Cycles Readiness | Notes |
|---------|-----------------|-------|
| Electric lighting | **Ready** | CIE 5.2–5.8 validated, no glass needed |
| Daylight (unglazed) | **Ready** | CIE 5.9, 5.11, 5.13, 5.14 validated |
| Daylight (glazed, large openings) | **Adequate** | CIE 5.10, 5.12 4×3m pass |
| Daylight (glazed, small openings, edge points) | **Limited** | ~15% edge errors, documented limitation |

For production daylight features requiring accurate glazing calculations, consider:
1. Accepting current accuracy for typical window sizes (large openings pass)
2. Evaluating Radiance as a secondary engine for glazing-specific calculations
3. Monitoring Blender bug #54006 for a fix in future versions
