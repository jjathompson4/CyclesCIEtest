# R&D: Wall-Edge Accuracy & Angle-Dependent Glass Absorption

**Date**: 2026-03-19
**Goal**: Resolve the two remaining systematic errors in CIE 171 tests 5.11 and 5.12 before proceeding with further validation work.

---

## Problem 1: Wall-Edge Measurement Accuracy (Tests 5.11, 5.12)

### What's happening

Measurement points near the facade opening boundary show 7–17% error, while floor/ceiling points pass at <3%. The affected points:

- **5.11 (4×3m opening)**: Wall point A (z=2.75m, 0.25m below ceiling/opening top) — 7.5–10.9%
- **5.11 (2×1m opening)**: Wall point C (z=1.75m, near opening top at z=2m) — 5.4–16.9%
- **5.12**: Same wall points plus grazing-angle glass effects at N/N' — 15–19%

The same pattern appears in 5.9/5.10 (roof tests) at wall point A (~5–6%). NVIDIA Iray shows the same edge sensitivity — this is not implementation-specific.

### Root cause analysis

**Current sampling pipeline:**
1. Bake illuminance to 512×512 texture per measurement surface
2. For each CIE measurement point, compute UV → pixel coordinate
3. Average a 7×7 kernel (±3 pixels) around that pixel
4. Convert averaged luminance → lux

**The problem**: At an opening boundary, illuminance changes as a step function. The 7×7 box-filter kernel spans ~55mm in world space (512px over 4m = 7.8mm/px, ×7 = ~55mm). When centered near a sharp boundary, it averages across the discontinuity, pulling the result toward the wrong side.

**Quantitative breakdown (4m wall, 512px):**
- Pixel size: 7.8mm
- Kernel span: ±23mm (7×7)
- Opening edge transition: effectively 0mm (geometric discontinuity)
- Point A distance from opening edge: ~250mm
- Gradient at point A: still steep because solid angle changes rapidly near boundary

**Why smaller openings are worse**: The 2×1m opening creates a steeper angular gradient (smaller solid angle, same room depth), so the illuminance transition zone is narrower and the kernel averaging introduces more bias.

### Approach A: Increase bake resolution (1024×1024 or 2048×2048)

**Concept**: Halve the pixel size → halve the kernel's world-space extent → reduce boundary averaging error.

| Resolution | Pixel size | Kernel span (7×7) | Expected improvement |
|------------|-----------|-------------------|---------------------|
| 512×512 | 7.8mm | 55mm | Current baseline |
| 1024×1024 | 3.9mm | 27mm | ~50% error reduction |
| 2048×2048 | 1.95mm | 14mm | ~75% error reduction |

**Pros**: Simple — change one parameter. Doesn't affect the physics.
**Cons**: 4× memory per doubling, 4× bake time. Diminishing returns — the discontinuity is infinitely sharp, so any finite kernel will still see some averaging bias.

**Implementation**: Change `wall_res = 512` → `wall_res = 1024` in runner_daylight.py measurement extraction. The bake image resolution is set in scene_builder when creating the bake texture.

### Approach B: Adaptive kernel size (edge-aware sampling)

**Concept**: Use a smaller kernel (1×1 or 3×3) for points near the opening boundary where gradients are steep, and keep the 7×7 kernel for interior points where it reduces noise.

**Algorithm**:
1. Compute the gradient magnitude at each measurement point's pixel location
2. If gradient exceeds a threshold → use 1×1 (single pixel) or 3×3 kernel
3. Otherwise → use standard 7×7 kernel

**Pros**: Preserves noise reduction at interior points. Eliminates boundary bias.
**Cons**: Higher Monte Carlo noise at edge points (fewer averaged pixels). Needs gradient threshold tuning.

**Alternative — distance-based**: Instead of gradient detection, compute each point's geometric distance to the nearest opening edge. Points within N pixels of an edge → use smaller kernel.

```python
# Pseudocode
def get_kernel_for_point(point_uv, opening_boundary_uvs, base_kernel=3):
    dist_to_edge_px = compute_distance_to_boundary(point_uv, opening_boundary_uvs, resolution)
    if dist_to_edge_px < 2 * base_kernel:  # within kernel radius of edge
        return 0  # single pixel, no averaging
    return base_kernel
```

### Approach C: Higher resolution + smaller default kernel

**Concept**: Increase to 1024×1024 AND reduce kernel from 7×7 (±3) to 3×3 (±1). At 1024px, a 3×3 kernel spans only ~12mm — sufficient for noise reduction without significant boundary blending.

**This is the recommended first attempt.** It's simple, addresses both issues simultaneously, and doesn't require edge-detection logic.

| Configuration | Pixel size | Kernel span | Edge behavior |
|--------------|-----------|-------------|--------------|
| 512px, ±3 (current) | 7.8mm | 55mm | Severe blending |
| 1024px, ±1 (proposed) | 3.9mm | 12mm | Minimal blending |
| 2048px, ±1 (aggressive) | 1.95mm | 6mm | Negligible blending |

### Approach D: Per-point ray sampling (bypass texture entirely)

**Concept**: Instead of baking to a texture and reading pixels, trace individual rays from each measurement point and accumulate illuminance directly.

**Blender API**: `scene.ray_cast()` only does intersection, not shading. To get illuminance per point, we'd need to either:
- Render a tiny 1×1 image with an orthographic camera aimed at each point
- Use the Cycles API directly (not exposed in bpy)
- Use an external ray tracer

**Pros**: Eliminates all texture quantization artifacts. True point measurement.
**Cons**: Very slow (one render per point), complex to implement, and Blender doesn't expose this cleanly.

**Verdict**: Not practical for the CIE test runner. Reserve for future investigation.

### Recommendation for Problem 1

**Phase 1 — Quick test**: Run 5.11 with `wall_res = 1024` and `kernel = 1` (3×3). Compare wall point A and C errors against current results. If errors drop below 5% → ship it.

**Phase 2 — If needed**: Implement distance-based adaptive kernel. Use geometric knowledge of the opening boundary to reduce kernel at edge points.

**Phase 3 — Nuclear option**: 2048×2048 with ±1 kernel. Only if 1024 isn't sufficient.

**Render time impact**: Bake time scales linearly with pixel count (not quadratically — Cycles traces the same number of samples per pixel). Going from 512² to 1024² = 4× more pixels = ~4× bake time per surface. With 3 surfaces (wall, floor, ceiling) at 4096 samples, this adds ~2-3 minutes per test case. Acceptable for validation.

---

## Problem 2: Angle-Dependent Glass Absorption (Tests 5.10, 5.12)

### What's happening

Our glass model uses a flat ×0.96 correction factor on top of Fresnel `(1-F)²` transmission. This works well at near-normal incidence (tests 5.10, 5.12 4×3m opening) but diverges at grazing angles (5.12 2×1m opening, points N/N' at 70–80° incidence), producing 15–19% error.

### Current model

```
T(θ) = (1 - F(θ))² × 0.96

where F(θ) = R₀ + (1-R₀)(1 - cos θ)⁵   [Schlick/Fresnel]
      R₀ = ((n-1)/(n+1))² = 0.04         [for IOR = 1.52]
```

This gives:
| θ | F(θ) | (1-F)² | ×0.96 | CIE τ_θ | Error |
|---|------|--------|-------|---------|-------|
| 0° | 0.040 | 0.922 | 0.885 | 0.96 | -7.8% |
| 30° | 0.040 | 0.921 | 0.884 | 0.96 | -7.9% |
| 50° | 0.053 | 0.897 | 0.861 | 0.95 | -9.4% |
| 60° | 0.090 | 0.828 | 0.795 | 0.93 | -14.5% |
| 70° | 0.197 | 0.645 | 0.619 | 0.84 | -26.3% |
| 80° | 0.468 | 0.283 | 0.272 | 0.59 | -53.9% |

Wait — the table above shows our model **under-transmits** at all angles compared to CIE. But in practice, tests 5.10 and 5.12 (4×3) pass. The discrepancy is because the bake pipeline measures **integrated illuminance** across the hemisphere, not per-angle transmittance. The 0.96 factor was empirically calibrated to match the CIE's **integrated** sky component values, not per-angle τ_θ.

The problem at grazing angles for 5.12 (2×1m) is that the small opening geometry forces rays to travel through the glass at steeper angles, where our per-ray Fresnel model deviates more from CIE's integrated Tregenza formula.

### CIE reference model: Tregenza/Mitalas & Arseneault

CIE Table 15 (Test 5.5) gives the "true" per-angle transmittance for 6mm clear glass:

| θ | τ_θ (CIE) | Notes |
|---|-----------|-------|
| 0° | 0.96 | Includes both Fresnel + absorption through 6mm |
| 10° | 0.96 | |
| 20° | 0.96 | |
| 30° | 0.96 | |
| 40° | 0.96 | Flat plateau — absorption dominates |
| 50° | 0.95 | Fresnel starts to kick in |
| 60° | 0.93 | |
| 70° | 0.84 | Steep Fresnel rise |
| 80° | 0.59 | |
| 90° | 0.00 | Total reflection |

The key insight: **CIE's τ_θ is much flatter than pure Fresnel** at normal/moderate angles. The real 6mm glass transmits ~96% regardless of angle up to 40°, because the dominant loss mechanism is absorption (constant ~4%), not Fresnel reflection (tiny at low angles). The Fresnel term only dominates above 60°.

### Approach A: Angle-dependent correction factor via lookup table

**Concept**: Replace the flat 0.96 factor with a per-angle correction that maps our `(1-F)²` to the CIE τ_θ curve.

```python
# Correction = CIE_tau / our_fresnel_tau
# At θ=0°:  0.96 / 0.922 = 1.041
# At θ=60°: 0.93 / 0.828 = 1.123
# At θ=70°: 0.84 / 0.645 = 1.302
# At θ=80°: 0.59 / 0.283 = 2.085
```

**Problem**: This correction factor isn't constant — it varies with angle. But in a Cycles shader graph, we can't easily implement an arbitrary lookup table. The Fresnel node only outputs a single `Fac` value.

**Implementation in shader nodes**: We'd need to reconstruct the incidence angle from the Fresnel output, then apply a polynomial correction. This is awkward but possible:

```
# In shader nodes:
F = Fresnel.Fac                           # Schlick reflectance
cos_theta = ((F - R0) / (1 - R0))^(1/5)  # Invert Schlick → recover cos θ  (only approximate)
theta = acos(cos_theta)                   # angle in radians

# CIE transmittance polynomial fit (6mm clear glass):
tau = a + b*cos(theta) + c*cos²(theta) + d*cos³(theta) + ...

# Set Transparent BSDF color = tau
```

This is fragile — the Schlick inversion is only approximate and breaks at edge cases.

### Approach B: Direct CIE transmittance model (bypass Fresnel node)

**Concept**: Don't use Blender's Fresnel node at all. Instead, compute the CIE transmittance directly from the incidence angle using shader nodes.

The incidence angle is `acos(dot(N, I))` where N is the glass normal and I is the incoming ray direction. Blender provides these via the Geometry node.

```
# Shader node graph:
Geometry.Incoming → Dot Product with glass normal → gives cos(θ)
cos(θ) → polynomial evaluation → CIE τ_θ → Transparent BSDF color
```

**CIE τ_θ polynomial fit** (from Table 15 data):

Fitting `τ_θ = f(cos θ)` to the 10 reference points:

| cos θ | τ_θ |
|-------|------|
| 1.000 | 0.96 |
| 0.985 | 0.96 |
| 0.940 | 0.96 |
| 0.866 | 0.96 |
| 0.766 | 0.96 |
| 0.643 | 0.95 |
| 0.500 | 0.93 |
| 0.342 | 0.84 |
| 0.174 | 0.59 |
| 0.000 | 0.00 |

A cubic or quartic polynomial `τ(c) = a₀ + a₁c + a₂c² + a₃c³` should fit this well. Need to compute coefficients.

**Shader node implementation**:
1. `Geometry` node → `Incoming` vector
2. `Vector Math (Dot Product)` with glass normal direction (hardcoded as constant) → cos θ
3. Chain of `Math` nodes (Multiply, Power, Add) to evaluate polynomial
4. Result → `Transparent BSDF` color

**Pros**: Directly matches CIE reference curve. No Fresnel node needed. Physically motivated (matches real 6mm glass behavior including absorption).
**Cons**: More shader nodes. Polynomial coefficients are glass-specific (6mm clear, n=1.52). The `Incoming` vector in Cycles for Transparent BSDF may not behave as expected (need to verify).

### Approach C: Hybrid — Fresnel node + angle-dependent absorption

**Concept**: Keep the Fresnel node for the reflection component but replace the flat 0.96 with an angle-dependent absorption term.

Real glass absorption follows Beer-Lambert: `τ_abs = exp(-α × d / cos θ)` where α is the absorption coefficient and d is glass thickness. At normal incidence the path through the glass is d; at angle θ the path is d/cos θ, so absorption increases at grazing angles.

Combined: `τ(θ) = (1 - F(θ))² × exp(-α × d / cos θ)`

For 6mm clear glass, calibrate α so that τ(0°) = 0.96:
```
0.96 = (1 - 0.04)² × exp(-α × 0.006 / 1.0)
0.96 = 0.922 × exp(-0.006α)
exp(-0.006α) = 1.041
```

This gives a negative α, which is unphysical — meaning `(1-F)²` at normal incidence is already *lower* than CIE's τ_θ. The real 6mm glass transmits more than Schlick predicts because:
1. CIE's τ_θ already includes internal absorption (Table 15 values are measured, not computed from Schlick)
2. The double-surface `(1-F)²` overcounts — real glass has multiple internal reflections that partially compensate

**Verdict**: Beer-Lambert correction alone doesn't fix the fundamental mismatch between Schlick and CIE's empirical transmittance. Approach B (direct polynomial) is cleaner.

### Approach D: NVIDIA's approach — flat transmittance

NVIDIA used a flat τ = 0.91 for all angles (no Fresnel variation at all). This passed all CIE tests.

**Why it works**: The CIE reference values are **integrated** over the sky hemisphere. A flat 0.91 is the hemisphere-averaged transmittance for 6mm clear glass under typical sky distributions. Since we're comparing integrated SC values (not per-angle), the averaging washes out per-angle errors.

**Pros**: Extremely simple — just set Transparent BSDF color to 0.91.
**Cons**: Loses all angle-dependent behavior. Physically wrong for individual rays. May fail Test 5.5 (per-angle transmittance validation).

### Recommendation for Problem 2

**Phase 1 — Quick win**: Try NVIDIA's flat τ = 0.91. Re-run 5.10 and 5.12 for all sky types. If both pass → use this as baseline and note the simplification.

**Phase 2 — Proper fix**: Implement Approach B (direct polynomial model). Steps:
1. Fit a polynomial τ(cos θ) to CIE Table 15 data (numpy polyfit)
2. Implement in shader nodes using `Geometry.Incoming` → `Dot Product` → polynomial chain → `Transparent BSDF`
3. Validate against Test 5.5 (per-angle transmittance) as a bonus
4. Re-run 5.10 and 5.12

**Phase 3 — If shader nodes are problematic**: Use an OSL (Open Shading Language) shader for the polynomial. Cycles supports OSL in CPU mode. More flexible than node math but restricts us to CPU rendering.

**Key risk**: The `Geometry.Incoming` vector behavior with Transparent BSDF needs verification. Transparent BSDF is special in Cycles — it doesn't refract or scatter, so the incoming vector should be the physical ray direction. But we need to confirm that `dot(Incoming, Normal)` gives the correct geometric incidence angle in the Cycles ray context.

---

## Experiment Plan

### Experiment 1: Resolution + kernel sweep (Problem 1)

Run Test 5.11, sky type 1 (CIE Overcast), 4×3m opening only:

| Config | wall_res | kernel | Expected wall A error |
|--------|---------|--------|----------------------|
| A (baseline) | 512 | ±3 | ~8% (current) |
| B | 1024 | ±3 | ~4% |
| C | 1024 | ±1 | ~3% |
| D | 2048 | ±1 | ~2% |
| E | 1024 | 0 (single px) | ~2% (but noisier) |

Then run the winning config on type 1 with the 2×1m opening (wall point C) to confirm improvement.

### Experiment 2: Glass model comparison (Problem 2)

Run Test 5.12, sky type 1, 2×1m opening:

| Config | Glass model | Expected improvement |
|--------|------------|---------------------|
| A (baseline) | Fresnel (1-F)² × 0.96 | 15–19% at N/N' |
| B | Flat τ = 0.91 | ~5% (per NVIDIA) |
| C | Polynomial τ(cos θ) from CIE Table 15 | <5% (matches ref curve) |

### Experiment 3: Combined fix validation

Run the winning configs from Exp 1 + Exp 2 together on:
- 5.11 all 15 sky types, both openings
- 5.12 all 15 sky types, both openings
- 5.10 all 15 sky types, both openings (regression check)
- 5.9 wall points only (regression check for resolution change)

### Success criteria

- **Problem 1**: All wall measurement points < 5% error (CIE per-point tolerance)
- **Problem 2**: All glazed measurement points < 5% error including grazing-angle points N/N'
- **Regression**: No degradation on floor/ceiling points or non-edge wall points

---

## Implementation checklist

- [ ] **Exp 1A**: Modify runner_daylight.py — parameterize `wall_res` and `kernel` per test function
- [ ] **Exp 1B**: Run 5.11 type 1 at each resolution/kernel config, record wall A error
- [ ] **Exp 1C**: Run winning config on 2×1m opening, record wall C error
- [ ] **Exp 2A**: Create flat glass material variant (τ=0.91), run 5.12 type 1 2×1m
- [ ] **Exp 2B**: Fit polynomial to CIE Table 15, implement in shader nodes
- [ ] **Exp 2C**: Verify `Geometry.Incoming` behavior with Transparent BSDF
- [ ] **Exp 2D**: Run 5.12 type 1 2×1m with polynomial glass, compare to baseline
- [ ] **Exp 3**: Full regression sweep with combined fixes
- [ ] Update test documentation (test_5.11.md, test_5.12.md) with new configs
- [ ] Update IMPLEMENTATION_AUDIT.md to reflect resolved deviations
- [ ] Update VALIDATION_STATUS.md

---

## Reference documents

- CIE 171:2006 — Section 5.5 (glass transmittance), Table 15
- CIE 171:2006 — Section 5.11–5.12, Tables B.9–B.20
- NVIDIA Iray validation report — pp. 30–42 (facade tests, glass model)
- `runner_daylight.py` lines 279–310 (measurement extraction), 379–468 (roof glass), 1065–1123 (facade glass)
- `calc_grid_bake.py` lines 158–240 (general extraction pipeline)
- `test_5.5.md` — CIE Table 15 reference data
- `test_5.11.md`, `test_5.12.md` — current results and error analysis
