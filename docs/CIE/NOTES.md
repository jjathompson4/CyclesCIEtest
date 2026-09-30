# CIE 171 Validation — Cross-Cutting Notes & Lessons Learned

Findings that apply across multiple test cases. Check here before debugging a new test — the issue may already be solved.

**See also**: `IMPLEMENTATION_AUDIT.md` — comprehensive audit of all deviations between our implementation and the CIE 171:2006 spec for tests 5.9–5.13 (conducted 2026-03-16).

---

## Render Settings

- **Test 5.2 (point source, direct only)**: 4096 samples, 0 bounces, Raw view transform, no denoising, no clamping → 0.99% max error. 512×512 bake resolution with 7×7 kernel averaging sufficient for sub-1% accuracy.
- **Test 5.4 (flux conservation)**: 4096 samples, 0 bounces, Raw, no denoising. 6 calc grids (256² each) on all room surfaces with 2mm offset. → 0.28% error. Wall_west/east grids need swapped width/height dimensions due to Y-rotation in add_calc_grid.
- **Test 5.3 (area source, direct only)**: 4096 samples, 0 bounces, Raw, no denoising. Source discretized into 10×10 sub-emitters (10cm each). Room height +0.01m to avoid ceiling z-fighting. Two calc grids: floor (512²) + wall_south (512²). 7×7 kernel averaging. → 4.94% max error.
- **Test 5.8 (interreflection)**: Tiered settings by reflectance. ρ≤0.30: 2048 samples/16 bounces. ρ≤0.60: 4096/32. ρ≤0.70: 4096/64. ρ=0.80: 4096/256. ρ≥0.90: 8192/1024+. 256×256 bake with full-texture averaging. Results ρ≤0.80 pass (<2% error), ρ=0.90/0.95 fail due to Russian Roulette.

- **Test 5.9 (sky component, roof opening)**: 4096 samples, 0 bounces (ρ=0 means no interreflection), Raw, no denoising. CIE sky HDRI as world environment with -90° Z rotation. External reference grid at (20,20,0) for E_hz. SC = pixel_room / pixel_ref × 100. All 15 sky types passing both openings. Wall point A edge-sensitive (−5.7%, consistent with NVIDIA).

- **Test 5.10 (glazed roof opening)**: Same as 5.9 + glass panel. 4096 samples, **0 bounces** (Transparent BSDF doesn't consume bounces). Glass material: Fresnel (IOR=1.52) → (1-F)² × 0.96 → Transparent BSDF color. Glass plane normal MUST face into room (`flip=True`). Cannot use Glass BSDF / Principled BSDF Transmission (opaque to shadow rays). 15/15 types passing both openings, point A edge-sensitive.

- **Test 5.12 (facade SC + ERC, glazed)**: Same as 5.11 + vertical glass panel at y=-0.001. Glass: Fresnel Transparent BSDF, (1-F)² × 0.96, IOR=1.52, normal +Y (flip=True). 4x3 results: 7.6-10.3% max (wall A edge). 2x1: 15-19% (wall C edge + grazing-angle glass at N/N'). Transparent BSDF doesn't consume bounces. 15/15 types tested both openings.

- **Test 5.14 (facade SC + ERC, vertical mask)**: Same render settings as 5.11. Diffuse mask (ρ=0.30) at y=-6m, semi-infinite in x (±10m), normal +Y. 3m mask: 14/15 types pass (max 5.84%). 6m/9m: CIE reference errata confirmed by NVIDIA (Tables B.25/B.26 overestimate ERC at A-D). Type 12 Table B.26 F=1.02 is a confirmed typo (should be ~6.76).

- **Test 5.13 (facade SC + ERC, horizontal mask)**: Same render settings as 5.11. Two-sided mask at z=3 (top=black, bottom=diffuse ρ=0.30), ±10m x-extent, 50mm depth margin. 0.5m mask: 4/15 pass, 11 marginal at 5-6%. 1.0m mask: CIE Table B.22 errata confirmed by NVIDIA. 2.0m mask: 8-12% at shadow boundary.

- **Test 5.11 (facade SC + ERC)**: 4096 samples, bounces=2 (for emissive ground path), Raw, no denoising. CIE sky HDRI with **+90° Z rotation** (facade-specific, see azimuth alignment note). Emissive ground plane at z=0, L = ρ/π = 0.0955 (ρ=0.30). Wall grid on north wall (wall_north), floor grid, ceiling grid (3 measurement surfaces). 512×512 bake, 3-kernel averaging. CIE Fig. 20 y-axis is FLIPPED from 5.9 — floor/ceiling point y-coords must be reversed. Floor SC: <2% error all types. Ceiling ERC: <3% error all types, sky-type independent (validated). Wall: edge-sensitive at opening boundary (7-17%), same pattern as 5.9/5.10.

## Material Mapping

<!-- Notes on how CIE-specified reflectances map to Cycles material settings -->

## Measurement Point Extraction

- **Mesh emitter near-field bias**: A ~1cm mesh emitter produces a consistent +0.8% positive bias vs true point source, increasing slightly at wider angles. Acceptable for CIE validation (well within 5% tolerance). Reducing emitter size further may help but is unnecessary.
- **Kernel averaging**: Sampling a single pixel is noisy; a 7×7 kernel average around each measurement point reduces noise without significant spatial blurring at 512×512 resolution (kernel covers ~0.05m at 4m grid).

## Known CIE Document Errata

- Table 19 in test 5.7: incorrect reference values (noted by NVIDIA and AGi32)
- Test 5.9, sky type 3: columns A–F are transposed in CIE doc (confirmed by NVIDIA)
- Test 5.9, Tables B.1/B.3 wall values: Under investigation — Blender produces ~70% higher wall SC values for Type 1, 4×4m opening (floor values match perfectly). May indicate a broader errata in the wall-point reference values, or a geometry interpretation issue for the fully-open ceiling case. Floor points (G–N) pass for all sky types tested so far.
- **Test 5.13, Table B.22 (1.0m mask)**: Reference values for overcast/steep-gradation sky types are WRONG. CIE shows E=5.07, F=7.64 (identical to unmasked), but both NVIDIA Iray and Blender Cycles independently compute E≈4.65, F≈5.67. NVIDIA's analysis (p.38): "The CIE report incorrectly used the SC from sky type 15 for positions A-D." The 1.0m mask SHOULD reduce E/F for all sky types, not just uniform/clear ones. This errata affects types 1-4, 6-9, 11 in Table B.22.
- **Test 5.14, Tables B.25/B.26 (6m/9m vertical mask)**: CIE reference values at points A-D are TOO HIGH — overestimate ERC from the mask. Confirmed by NVIDIA Iray (p.42). Both renderers produce consistently lower values at these points.
- **Test 5.14, Table B.26 type 12, point F=1.02**: Confirmed TYPO by NVIDIA — should be ~6.76. All other types have F in range 3.9-7.8 for the 9m mask.
- See Ian Ashdown's errata list for additional corrections

## Blender/Cycles Quirks

- **Emission shader calibration**: Plain Cycles emission shaders (no IES) interact differently with the holdout bake pipeline than IES-based emitters. A systematic +9% overshoot was observed in test 5.6 when using an emission surface as a proxy for a diffuse reflector. The IES-based pipeline (tests 5.2/5.3/5.4/5.8) is well-calibrated. For tests requiring diffuse surface reflection, prefer using actual reflective surfaces + light sources over emission shader shortcuts.
- **World background contamination**: Open-geometry test scenes (no enclosing room) MUST set the world background to pure black (`color=(0,0,0), strength=0`). Blender's default gray world (~0.05 luminance) adds ambient illumination that doesn't cancel in ratio-based measurements. In test 5.6, this caused +15% systematic overshoot because the ambient contributed ~2% to the strong floor signal but ~18% to the weak reflected signal. Previous tests (5.2/5.3/5.4/5.8) were unaffected because their enclosed rooms blocked the world background.
- **Ratio normalization for reflection tests**: For tests measuring form factors or reflectance ratios, use a reference calc grid to measure the baseline illuminance (e.g., E_hz) in the same bake pass. Computing F₁₂ = pixel_reflected / (pixel_reference × ρ) cancels all Cycles calibration factors (π, luminous efficacy, etc.) and gives sub-1% accuracy.
- **Two-pass bake for open geometry**: When direct sun contaminates measurement surfaces (no enclosing room to block it), bake the reference grid first with `use_pass_direct=True`, then bake measurement grids with `use_pass_direct=False, use_pass_indirect=True`. This cleanly separates the reflected-light signal from direct sun contamination. Used successfully in test 5.7 to avoid complex blocker geometry for the floor grid.
- **Sun direction for vertical walls**: When S₂ is a vertical wall (e.g., at y=Y₀ with normal -Y), the sun must travel toward +Y to illuminate the room-facing surface. Rotation around X by +α (positive) gives direction (0, +sinα, -cosα). A common mistake is using the wrong sign, which illuminates S₂'s back face.
- **CIE sky HDRI azimuth alignment**: The equirectangular CIE sky HDRI maps the sun (azimuth=180°) to the image center (u=0.5), which Blender maps to the +X direction by default. A Mapping node Z rotation is required to place the sun in the correct room direction. **Roof-opening tests (5.9, 5.10)**: use **-90° Z** rotation — this places the CIE sun at +Y in Blender. It produces correct results because the inverted viewing geometry through overhead openings naturally flips the effective azimuth. **Facade-opening tests (5.11+)**: use **+90° Z** rotation — this places the CIE sun at -Y (south in our room). Required because rays exit directly through the wall opening with no geometric azimuth inversion. Using the wrong rotation causes 40-70% systematic errors for anisotropic sky types. Parameterized via `load_sky_hdri(azimuth_rotation_deg=...)`.
- **Area source discretization**: Large area emitters (test 5.3, 1m²) must be discretized into a grid of small sub-emitters (10×10 at 10cm works well, <5% error). The IES mesh emitter formula works correctly for each small sub-emitter. This mirrors the analytical approach in `ies_direct_calc.py` and the `subdivisions_x/y` fields on `Fixture`.
- **Ceiling z-fighting**: If an emitter mesh sits at exactly the same Z as the ceiling plane, the ceiling blocks emitted light. Fix: offset room height by 0.01m (test 5.3) or position the emitter slightly below the ceiling surface.
- **Wall grid UV inversion**: For `wall_south` calc grids, the -π/2 rotation around X inverts the V axis. Sample with `v = 1 - z/room_h`, not `v = z/room_h`. Other wall orientations may have similar inversions — check on a per-surface basis.
- **Glass materials and shadow rays (CRITICAL)**: In Cycles, ONLY the Transparent BSDF is transparent to shadow rays. Glass BSDF, Principled BSDF with Transmission, and Glossy BSDF are all OPAQUE to shadow rays (Blender bug #54006). For CIE glass tests (5.10, 5.12), model glass as: Fresnel (IOR=1.52) → compute (1-F)² → use as Transparent BSDF color. The (1-F)² models double-surface Fresnel for a glass pane. Glass plane normal MUST face into the room (toward the calc grids) so the Fresnel node computes correct incidence angles via dot(I, N).
- **Calc grid backface light leakage (CRITICAL)**: The Diffuse BSDF in the holdout material is two-sided — it captures light hitting BOTH faces of the calc grid plane. For wall grids, this causes the back face (outside the room) to capture sky light that should be blocked by the wall. Symptoms: wall readings ~2× the correct value, with the error varying by sky type (worst for overcast skies with bright zenith). Fix: add `Geometry > Backfacing` node to the holdout material so the back face is always transparent. Also increase the wall grid offset from 1mm to 10mm. Applied to `scene_builder.py:add_calc_grid()` on 2026-03-15. This fix affects ALL calc grids but only changes behavior for wall grids (floor grids are already protected by the floor mesh beneath them).
- **Russian Roulette path termination**: Cycles probabilistically terminates paths based on throughput, even when `max_bounces` is set very high (tested up to 4096). At ρ=0.90, each bounce has 90% throughput → after ~10 bounces, accumulated probability ≈ 0.35, and many paths get killed. This causes systematic negative bias for high-reflectance interreflection (test 5.8: −11.65% at ρ=0.90, −32.42% at ρ=0.95). Setting `max_bounces=4096` does NOT fix this — the issue is in the probabilistic termination, not the bounce limit.
- **Practical impact**: ρ ≤ 0.80 covers all realistic interior reflectances (ceiling=0.80 is the highest typical value) and works accurately (<2% error). Only extreme ρ > 0.80 scenarios are affected.
- **CIE sky HDRI azimuth for facade openings (CRITICAL)**: Roof-opening tests (5.9, 5.10) use -90° Z rotation in the Mapping node. This places the CIE sun at +Y in Blender, which *accidentally* produces correct results because the inverted viewing geometry through overhead openings flips the azimuth. Facade-opening tests (5.11+) require **+90° Z rotation** because rays exit directly through the wall opening toward the sky — no geometric inversion occurs. Using the wrong rotation causes 40-70% systematic under-reading for anisotropic sky types (strong circumsolar: c > 0). Symmetric/uniform sky types (c=0: types 1, 3, 5) are barely affected because they have no azimuth-dependent brightening. Parameterized via `load_sky_hdri(azimuth_rotation_deg=...)`.
- **Facade glass normal direction (CRITICAL)**: For vertical glass panels (test 5.12), the default vertex winding order for a quad at y=const gives a -Y normal (outward). This MUST be flipped to +Y (into the room) via `flip=True`. With wrong normal: Fresnel computes negative dot(I,N), returning near-total reflection → glass appears opaque → all floor/ceiling values collapse to ~5% constant. Symptom: flat floor/ceiling values regardless of point position. Fix confirmed by checking that wall values (which approach the glass at near-normal incidence) are approximately correct even with wrong glass normal.
- **Horizontal mask CIE errata (5.13, Table B.22)**: The CIE reference values for the 1.0m mask with overcast sky types are WRONG — confirmed independently by both NVIDIA Iray (p.38 of their validation report) and our Blender Cycles implementation. Both renderers produce E≈4.65, F≈5.67 for type 1, vs CIE reference E=5.07, F=7.64. NVIDIA concluded the CIE accidentally used sky type 15 SC values. Our 0.5m and 2.0m mask results match the reference within 5-9%, consistent with NVIDIA's findings.
- **Emissive ground for facade ERC**: For facade opening tests with a diffuse external ground (ρ=0.30), the room partially blocks sky light from reaching the nearby ground, causing 11-36% negative bias in ceiling ERC values. Fix: use an Emission shader ground with luminance L = ρ/π (calibrated to the CIE HDRI E_hz=1.0 normalization). This makes ERC purely geometric (correct analytical behavior), independent of the room's sky-blocking. Also allows bounces=0 since emission is "direct" light. Applied in test 5.11.
- **CIE 5.11 y-axis convention**: CIE Fig. 20 measures floor/ceiling y from the OPPOSITE wall (north, far from opening) toward the opening (south). This is the REVERSE of the 5.9 convention. Floor/ceiling point coordinates must be flipped: CIE y=0.25 → room y = room_depth - 0.25. Failure to flip causes exact reversal of the SC pattern (computed G ≈ expected N and vice versa). Wall points (on the north wall at fixed y) are unaffected.

## Comparison with Other Implementations

- **Test 5.4 (flux conservation)**: Cycles 0.28%, AGi32 0.31%. NVIDIA did not report 5.4. AGi32: Table 12, p.22.
- **Test 5.3 (area source, diffuse)**: Cycles passes at 4.94% max error using 10×10 sub-emitter discretization. AGi32 also used luminaire subdivision. NVIDIA Iray at ~0% deviation (true area source). NVIDIA: Table 8, p.19 (PDF p.23). AGi32: Table 8, p.20.
- **Test 5.8 (interreflection)**: Cycles passes ρ≤0.80 (max 1.79% error), fails ρ=0.90/0.95 (Russian Roulette). NVIDIA Iray passed all reflectances. AGi32 flagged test 5.8 as "not conducive to the results expected." NVIDIA: Table 15, p.25 (PDF p.29). AGi32: p.26.
- **Test 5.6 (diffuse reflection)**: Cycles passes Scenario 2 at 0.25% max error using Sun lamp + reflective surface + ratio normalization. NVIDIA Iray and AGi32 both show near-perfect matches. Scenarios 1 and 3 pending. NVIDIA: p.22 (PDF p.26). AGi32: Table 15 p.26.
- **Test 5.2 (point source, diffuse)**: All three implementations pass comfortably.
  - Cycles: 0.99% max error (consistent positive bias from mesh emitter area)
  - NVIDIA Iray: ~0.1% max error (true point source, near-perfect)
  - AGi32: ~0.2% max error (radiosity-based, also near-perfect)
  - Radiance: not reported for 5.2
  - Cycles' higher error is expected — mesh emitters have nonzero area vs true point sources.
  - NVIDIA results: Table 7, p.18 of `Validation-of-NVIDIA's-Iray-against-CIE-171_20160217.pdf`
  - AGi32 results: Table 7, p.18 of `Report on AGI 32 validation of CIE 171_Compiled_070620.pdf`

- **Test 5.6 (diffuse reflection) — Radiance comparison**: Radiance mean error 0.137%, Cycles mean error 0.13%. Essentially identical. Both near-perfect for Scenario 2. Source: `RW2008_DGM_AD.pdf` slide 20.

- **Test 5.7 (obstructed reflection) — Radiance comparison**: Radiance reported 21.79% mean error against CIE reference values, but only 0.142% mean error against their own independent analytical calculation of configuration factors. This independently confirms the CIE Table 19 errata. Using corrected values, Radiance and Cycles are both sub-1%. Source: `RW2008_DGM_AD.pdf` slides 21-26.

- **Test 5.8 (interreflection) — Radiance comparison**: Radiance shows the same high-reflectance convergence failure as Cycles. For ρ≤0.80: Radiance mean error 0.318% (Cycles 1.79% max). At ρ=0.90: Radiance 884 vs CIE 937 lx (-5.7%); Cycles -11.65%. At ρ=0.95: Radiance 1472 vs CIE 1979 lx (-25.6%); Cycles -32.42%. Both engines underestimate at high reflectances — Radiance somewhat less than Cycles (likely less aggressive path termination). This is a fundamental limitation of Monte Carlo rendering, not implementation-specific. Source: `RW2008_DGM_AD.pdf` slides 27-29.

- **Test 4.2 (opal circular luminaire) — Radiance comparison**: Radiance FAILED — 33/49 measurement points fell below the measurement band lower limit. The failure was traced to inaccurate modeling of circular light sources. This led Geisler-Moroder & Dür to develop an improved adaptive subdivision algorithm for circular sources (second half of their paper). Worth noting when we implement Section 4 tests. Source: `RW2008_DGM_AD.pdf` slides 10-12.

- **Section 4 (experimental) — Radiance comparison**: Radiance passed 4.1 (CFL point source, all 49 pts) and 4.3 (SSR square luminaire, all 49 pts), but failed 4.2 (circular opal luminaire). This is the only published Radiance validation against CIE 171 Section 4. Source: `RW2008_DGM_AD.pdf` slides 7-15.

### Reference PDF Page Map (for quick lookup on future tests)

| CIE Test | NVIDIA Iray PDF page | AGi32 PDF page | Radiance PDF slide (RW2008_DGM_AD.pdf) |
|----------|---------------------|----------------|----------------------------------------|
| 4.1 | — | — | slides 7-9 (CFL grey wall, mean room illum 88.5 lx, all 49 pts pass) |
| 4.2 | — | — | slides 10-12 (opal luminaire, mean 51.4 lx, 33/49 below MB LL — FAILED circular source) |
| 4.3 | — | — | slides 13-15 (SSR luminaire, mean 234.5 lx, all 49 pts pass) |
| 5.2 | 21-22 (printed p.17-18) | 17-18 | — |
| 5.3 | 23-24 (printed p.19-20) | 19-20 | — |
| 5.5 | 25-26 (printed p.21-22) | — | — |
| 5.6 | 27-28 (printed p.22-23) | 21-22 | slide 20 (mean error 0.137%) |
| 5.7 | 29-30 (printed p.24-25) | 23-24 | slides 21-26 (21.79% vs CIE ref, 0.142% vs own analytical — confirmed CIE Table 19 errata) |
| 5.8 | 31-32 (printed p.25-26) | 25-26 | slides 27-29 (mean error 0.318% for ρ≤0.80; ρ=0.90: 884 vs 937 lx = -5.7%; ρ=0.95: 1472 vs 1979 = -25.6%) |
