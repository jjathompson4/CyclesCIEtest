"""
CIE 171:2006 Test Runner — Analytical + Blender Render Verification.

Usage:
    # Analytical-only check (no Blender needed):
    python cie171/runner.py --test 5.2 --analytical-only
    python cie171/runner.py --test 5.8 --analytical-only

    # Full test (inside Blender):
    blender --background --python cie171/runner.py -- --test 5.2
    blender --background --python cie171/runner.py -- --test 5.8

Output:
    Results printed to stdout + saved to docs/CIE/results/test_X.X/
"""

import math
import os
import sys
import json

# Ensure parent directory is on path for imports
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_RENDERER_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _RENDERER_DIR)
sys.path.insert(0, _THIS_DIR)

from test_cases import (
    TEST_5_2_DIFFUSE, compute_analytical_5_2,
    TEST_5_3_DIFFUSE, compute_analytical_5_3,
    TEST_5_4,
    TEST_5_6_SCENARIO2, compute_analytical_5_6,
    TEST_5_7, compute_analytical_5_7,
    TEST_5_8, compute_analytical_5_8,
)
from cie_distributions import generate_lambertian_ies, generate_isotropic_ies


# ─────────────────────────────────────────────
# RESULTS OUTPUT
# ─────────────────────────────────────────────

_PROJECT_ROOT = os.path.abspath(os.path.join(_RENDERER_DIR, '..'))


def _results_dir(test_id):
    d = os.path.join(_PROJECT_ROOT, 'docs', 'CIE', 'results', f'test_{test_id}')
    os.makedirs(d, exist_ok=True)
    return d


def compare_results(computed, reference, test_case, label=''):
    """Compare computed illuminance against CIE reference values.

    Args:
        computed: dict {key: value} where value is float or dict with 'E_lux'
        reference: dict {key: float} (reference lux)
        test_case: test case dict (for tolerances)
        label: description string for output

    Returns:
        dict with pass/fail, per-point errors, global stats
    """
    point_tol = test_case['point_tolerance']
    global_tol = test_case['global_tolerance']

    print(f"\n{'='*70}")
    print(f"{test_case['name']} — {label}")
    print(f"{'='*70}")

    errors = {}
    all_pass = True
    skipped = 0

    for pt in sorted(reference.keys(), key=lambda x: (isinstance(x, str), x)):
        ref = reference[pt]
        if isinstance(computed[pt], dict):
            calc = computed[pt].get('E_lux', computed[pt].get('E_total', 0))
        else:
            calc = computed[pt]

        if ref == 0:
            # For zero reference: use absolute tolerance.
            # If calc is near zero (< 0.5 absolute), treat as pass.
            if abs(calc) < 0.5:
                errors[pt] = 0.0
                skipped += 1
                continue
            else:
                errors[pt] = float('inf')
                all_pass = False
                print(f"  {str(pt):>6}  ref={ref:>10.2f}  calc={calc:>10.2f}  "
                      f"err=   inf%  FAIL (ref=0, calc≠0)")
                continue

        err = (calc - ref) / ref
        errors[pt] = err
        status = 'PASS' if abs(err) <= point_tol else 'FAIL'
        if status == 'FAIL':
            all_pass = False
        print(f"  {str(pt):>6}  ref={ref:>10.2f}  calc={calc:>10.2f}  err={err:>+7.2%}  {status}")

    finite_errors = [abs(e) for e in errors.values() if abs(e) != float('inf')]
    if not finite_errors:
        finite_errors = [0.0]
    max_err = max(finite_errors)
    mean_err = sum(finite_errors) / len(finite_errors)
    global_pass = max_err <= global_tol

    print(f"\n  Max error:  {max_err:.2%}  (limit: {global_tol:.0%}) {'PASS' if global_pass else 'FAIL'}")
    print(f"  Mean error: {mean_err:.2%}")
    n_fail = sum(1 for e in finite_errors if e > point_tol)
    print(f"  Points outside {point_tol:.0%}: {n_fail}/{len(finite_errors)}")
    if skipped:
        print(f"  Skipped (both zero): {skipped}")
    print(f"  Overall: {'PASS' if (all_pass and global_pass) else 'FAIL'}")

    return {
        'pass': all_pass and global_pass,
        'max_error': max_err,
        'mean_error': mean_err,
        'errors': errors,
        'n_failing': n_fail,
    }


# ═══════════════════════════════════════════════
# TEST 5.2 — Point Light Sources (Diffuse)
# ═══════════════════════════════════════════════

def run_5_2_analytical(test_case):
    """Pure math check: E = I₀·cos²(θ)/d² vs Table 11 reference values."""
    print("\n" + "=" * 70)
    print("PHASE A — Analytical Verification (pure math)")
    print("=" * 70)

    computed = compute_analytical_5_2(test_case)

    print(f"\nSource: I₀ = {test_case['I0_cd']:.0f} cd, height = {test_case['source_height_m']:.1f} m")
    print(f"Distribution: Lambertian (I(θ) = I₀·cos(θ))")
    print(f"\n{'Point':>5}  {'x(m)':>5}  {'y(m)':>5}  {'d(m)':>6}  {'θ(°)':>6}  {'I(cd)':>8}  {'E(lx)':>8}")
    print(f"{'-'*5:>5}  {'-'*5:>5}  {'-'*5:>5}  {'-'*6:>6}  {'-'*6:>6}  {'-'*8:>8}  {'-'*8:>8}")

    for pt in sorted(computed.keys()):
        r = computed[pt]
        x, y = test_case['points'][pt]
        print(f"{pt:>5}  {x:>5.1f}  {y:>5.1f}  {r['d_m']:>6.3f}  {r['theta_deg']:>6.2f}  {r['I_cd']:>8.1f}  {r['E_lux']:>8.2f}")

    result = compare_results(computed, test_case['reference_E_lux'], test_case,
                             label='Analytical vs Table 11')

    print(f"\n  Intensity check (I(θ) vs Table 11):")
    for pt in sorted(test_case['reference_I_cd'].keys()):
        ref_I = test_case['reference_I_cd'][pt]
        calc_I = computed[pt]['I_cd']
        err = (calc_I - ref_I) / ref_I
        print(f"    {pt}: ref={ref_I:.1f}, calc={calc_I:.1f}, err={err:+.3%}")

    results_dir = _results_dir('5.2')
    out = {}
    for pt in sorted(computed.keys()):
        r = computed[pt]
        out[pt] = {
            'x_m': test_case['points'][pt][0],
            'y_m': test_case['points'][pt][1],
            'd_m': r['d_m'],
            'theta_deg': r['theta_deg'],
            'I_cd': r['I_cd'],
            'E_lux_calc': r['E_lux'],
            'E_lux_ref': test_case['reference_E_lux'][pt],
            'error_pct': result['errors'][pt] * 100,
        }
    json_path = os.path.join(results_dir, 'analytical_results.json')
    with open(json_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n  Saved: {json_path}")

    return result


def run_5_2_blender(test_case):
    """Build CIE 5.2 scene in Blender and bake illuminance."""
    import bpy

    from fixture_config import FT_TO_M, M_TO_FT, Fixture, CalcGrid, Room
    from scene_builder import (
        clear_scene, build_floor_plan, add_fixture, add_calc_grid,
        configure_cycles_base,
    )
    from calc_grid_bake import bake_calc_grids

    print("\n" + "=" * 70)
    print("PHASE B — Blender Cycles Render")
    print("=" * 70)

    ies_path = os.path.join(_THIS_DIR, 'ies', 'cie_diffuse_1000cd.ies')
    generate_lambertian_ies(test_case['I0_cd'], ies_path)
    print(f"\n  Generated IES: {ies_path}")

    room_w_m, room_d_m, room_h_m = 6.0, 6.0, 5.0
    room_w_ft = room_w_m * M_TO_FT
    room_d_ft = room_d_m * M_TO_FT
    room_h_ft = room_h_m * M_TO_FT

    clear_scene()
    room = Room(name='CIE_5_2', origin_ft=(0, 0),
                width_ft=room_w_ft, depth_ft=room_d_ft, height_ft=room_h_ft,
                reflectances={'ceiling': 0.0, 'walls': 0.0, 'floor': 0.0})
    build_floor_plan([room])

    cx_ft = room_w_ft / 2
    cy_ft = room_d_ft / 2
    src_z_ft = test_case['source_height_m'] * M_TO_FT

    fixture = Fixture(ies_path=ies_path,
                      position_ft=(cx_ft, cy_ft, src_z_ft),
                      width_inches=0.4, cos_clamp=0.01)
    add_fixture(fixture, fixture_id=1)

    grid_w_ft = test_case['surface_size_m'] * M_TO_FT
    calc_grid = CalcGrid(name='CIE_5_2_Floor', surface='floor',
                         width_ft=grid_w_ft, height_ft=grid_w_ft,
                         spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
                         bake_resolution=512,
                         position_ft=(cx_ft, cy_ft, 0.0))
    obj, bake_img = add_calc_grid(calc_grid)

    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 0
    cycles.diffuse_bounces = 0
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    print(f"\n  Render: 4096 samples, 0 bounces (direct only)")

    grid_objects = [(calc_grid, obj, bake_img)]
    baked = bake_calc_grids(grid_objects)

    import numpy as np
    LUMINOUS_EFFICACY = 179.0
    bake_img_data = baked[0][1]
    res = calc_grid.bake_resolution
    pixels = np.zeros(res * res * 4, dtype=np.float32)
    bake_img_data.pixels.foreach_get(pixels)
    pixels = pixels.reshape((res, res, 4))

    half_size = test_case['surface_size_m'] / 2.0
    computed = {}
    for pt, (x, y) in test_case['points'].items():
        u = (x + half_size) / test_case['surface_size_m']
        v = (y + half_size) / test_case['surface_size_m']
        px = int(u * (res - 1))
        py = int(v * (res - 1))
        px = max(0, min(res - 1, px))
        py = max(0, min(res - 1, py))

        kernel = 3
        r_sum, g_sum, b_sum, count = 0, 0, 0, 0
        for dy in range(-kernel, kernel + 1):
            for dx in range(-kernel, kernel + 1):
                sx = max(0, min(res - 1, px + dx))
                sy = max(0, min(res - 1, py + dy))
                r_sum += pixels[sy, sx, 0]
                g_sum += pixels[sy, sx, 1]
                b_sum += pixels[sy, sx, 2]
                count += 1

        luminance = 0.2126 * (r_sum/count) + 0.7152 * (g_sum/count) + 0.0722 * (b_sum/count)
        computed[pt] = luminance * LUMINOUS_EFFICACY

    results_dir = _results_dir('5.2')
    exr_path = os.path.join(results_dir, 'cie_5_2_baked.exr')
    bake_img_data.filepath_raw = exr_path
    bake_img_data.file_format = 'OPEN_EXR'
    bake_img_data.save()

    result = compare_results(computed, test_case['reference_E_lux'], test_case,
                             label='Blender Cycles vs Table 11')

    out = {}
    for pt in sorted(computed.keys()):
        out[pt] = {
            'E_lux_blender': computed[pt],
            'E_lux_ref': test_case['reference_E_lux'][pt],
            'error_pct': result['errors'][pt] * 100,
        }
    json_path = os.path.join(results_dir, 'blender_results.json')
    with open(json_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"  Saved: {json_path}")

    return result


# ═══════════════════════════════════════════════
# TEST 5.6 — Light Reflection over Diffuse Surfaces
# ═══════════════════════════════════════════════

def run_5_6_analytical(test_case):
    """Analytical form factor check for diffuse reflection."""
    print("\n" + "=" * 70)
    print("PHASE A — Analytical Verification (form factor integration)")
    print("=" * 70)

    computed = compute_analytical_5_6(test_case)

    print(f"\nS₂: {test_case['s2_width_m']}m × {test_case['s2_depth_m']}m floor, ρ={test_case['s2_reflectance']}")
    print(f"Reference: E/(E_hz·ρ) = form factor F₁₂ × 100 (%)")

    ref = test_case['reference_form_factor_pct']
    result = compare_results(computed, ref, test_case, label='Analytical F₁₂ vs Table 17')

    results_dir = _results_dir('5.6')
    out = {pt: {'F12_calc_pct': computed[pt], 'F12_ref_pct': ref[pt]}
           for pt in computed}
    with open(os.path.join(results_dir, 'analytical_results.json'), 'w') as f:
        json.dump(out, f, indent=2)

    return result


def run_5_6_blender(test_case):
    """CIE 5.6 Scenario 2 — Sun lamp + reflective S₂ (Approach A).

    Implements the CIE specification as written:
    1. Sun lamp at 35° incidence uniformly illuminates S₂ (diffuse floor, ρ=0.30)
    2. Opaque black overhang blocks direct sun from reaching S₁-v
    3. S₁-hz (ceiling) naturally doesn't see the sun (back-face, bake captures
       only light arriving from the normal side = below)
    4. Floor calc grid measures E_hz directly from the sun
    5. F₁₂ = pixel_reflected / (pixel_floor × ρ) — all calibration factors cancel

    The ratio approach is robust: any Cycles-specific scaling in the bake
    pipeline (π factors, luminous efficacy) cancels identically in numerator
    and denominator, so the result depends only on the physics.
    """
    import bpy
    import numpy as np

    from fixture_config import FT_TO_M, M_TO_FT, CalcGrid
    from scene_builder import (
        clear_scene, configure_cycles_base, add_calc_grid,
        make_diffuse_material, _add_plane,
    )
    from calc_grid_bake import bake_calc_grids

    print("\n" + "=" * 70)
    print("PHASE B — Blender Cycles Render (Sun lamp + reflective S₂)")
    print("=" * 70)

    s2_w = test_case['s2_width_m']   # 4.0
    s2_d = test_case['s2_depth_m']   # 4.0
    rho = test_case['s2_reflectance']  # 0.30

    clear_scene()

    # ── Set world background to pure black (no ambient light) ──
    # Without an enclosing room, the default gray world contributes
    # ambient illumination that doesn't cancel in the ratio.
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new('World')
        bpy.context.scene.world = world
    if hasattr(world, 'use_nodes'):
        world.use_nodes = True
    nodes_w = world.node_tree.nodes
    bg = nodes_w.get('Background')
    if bg:
        bg.inputs['Color'].default_value = (0, 0, 0, 1)
        bg.inputs['Strength'].default_value = 0.0
    print("  World background set to black")

    # ── S₂: Diffuse reflecting floor surface (ρ=0.30) ──
    mat_s2 = make_diffuse_material('S2_Floor', rho)
    _add_plane('S2_Floor', [
        (0, 0, 0), (s2_w, 0, 0), (s2_w, s2_d, 0), (0, s2_d, 0)
    ], mat_s2, flip=False)  # Normal +Z (up)
    print(f"\n  S₂ floor: {s2_w}m × {s2_d}m, ρ={rho}")

    # ── Overhang blocker: prevents direct sun from reaching S₁-v ──
    # Sun direction: (0, -sin35°, -cos35°) = (0, -0.574, -0.819)
    # Shadow analysis: ray to wall bottom (z=0.5) passes z=3.0 at y=1.75
    # Overhang at z=3.002, y=-0.5 to y=1.9 blocks all sun from S₁-v.
    # Shadow of overhang edge on S₂: y = 1.9 - 0.574×3.002/0.819 = -0.20
    # → shadow falls at y=-0.20, outside S₂ (y≥0), so S₂ is fully lit. ✓
    # Reflected light from S₂ to S₁-v travels from z=0 to z≤3.0,
    # never crossing z=3.002, so the overhang doesn't block it. ✓
    mat_black = make_diffuse_material('Blocker_Black', 0.0)
    blocker_z = 3.002
    _add_plane('Sun_Blocker', [
        (-0.5, -0.5, blocker_z), (s2_w + 0.5, -0.5, blocker_z),
        (s2_w + 0.5, 1.9, blocker_z), (-0.5, 1.9, blocker_z)
    ], mat_black, flip=True)  # Normal facing down
    print(f"  Sun blocker: overhang at z={blocker_z}, y=-0.5 to 1.9")

    # ── Sun lamp at 35° incidence ──
    # Default Sun direction is -Z. Rotate -35° around X to tilt toward -Y.
    # Result direction: (0, -sin35°, -cos35°) = (0, -0.574, -0.819)
    # E_hz on horizontal S₂ = energy × cos(35°)
    bpy.ops.object.light_add(type='SUN', location=(2, 2, 10))
    sun = bpy.context.active_object
    sun.data.energy = 10.0  # W/m² — strong signal for clean ratio
    sun.rotation_euler = (math.radians(-35), 0, 0)
    print(f"  Sun lamp: energy={sun.data.energy} W/m², 35° incidence from +Y")

    # ── Floor calc grid: measures E_hz (direct sun on S₂) ──
    floor_grid = CalcGrid(
        name='CIE_5_6_floor', surface='floor',
        width_ft=s2_w * M_TO_FT, height_ft=s2_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=256,
        position_ft=(s2_w / 2 * M_TO_FT, s2_d / 2 * M_TO_FT,
                     0.001 * M_TO_FT),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # ── S₁-v calc grid (wall): measures reflected illuminance ──
    s1v_w_ft = test_case['s1v_width_m'] * M_TO_FT
    s1v_h_ft = test_case['s1v_height_m'] * M_TO_FT
    s1v_z_center = test_case['s1v_z_bottom_m'] + test_case['s1v_height_m'] / 2

    wall_grid = CalcGrid(
        name='CIE_5_6_S1v', surface='wall_south',
        width_ft=s1v_w_ft, height_ft=s1v_h_ft,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(s2_w / 2 * M_TO_FT, 0.001 * M_TO_FT,
                     s1v_z_center * M_TO_FT),
    )
    wall_obj, wall_img = add_calc_grid(wall_grid)

    # ── S₁-hz calc grid (ceiling): measures reflected illuminance ──
    ceil_w_ft = test_case['s1hz_width_m'] * M_TO_FT
    ceil_d_ft = test_case['s1hz_depth_m'] * M_TO_FT

    ceil_grid = CalcGrid(
        name='CIE_5_6_S1hz', surface='ceiling',
        width_ft=ceil_w_ft, height_ft=ceil_d_ft,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(s2_w / 2 * M_TO_FT, s2_d / 2 * M_TO_FT,
                     (test_case['s1hz_z_m'] - 0.001) * M_TO_FT),
    )
    ceil_obj, ceil_img = add_calc_grid(ceil_grid)

    # ── Render settings ──
    # 1 bounce: sun → S₂ (direct), S₂ → S₁ (1st diffuse bounce)
    # S₁ has ρ=0 so no secondary reflections; higher bounces won't change results
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 1
    cycles.diffuse_bounces = 1
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    print(f"  Render: 4096 samples, 1 bounce")

    # ── Bake all three grids ──
    grid_objects = [
        (floor_grid, floor_obj, floor_img),
        (wall_grid, wall_obj, wall_img),
        (ceil_grid, ceil_obj, ceil_img),
    ]
    baked = bake_calc_grids(grid_objects)

    # ── Read bake results ──
    kernel = 3

    # Floor grid (256×256) — measure E_hz
    floor_res = 256
    floor_pixels = np.zeros(floor_res * floor_res * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(floor_pixels)
    floor_pixels = floor_pixels.reshape((floor_res, floor_res, 4))

    # Average E_hz from center region (skip edges for clean measurement)
    margin = floor_res // 8
    center = floor_pixels[margin:-margin, margin:-margin, :3]
    E_hz_pixel = np.mean(
        0.2126 * center[:, :, 0]
        + 0.7152 * center[:, :, 1]
        + 0.0722 * center[:, :, 2]
    )
    print(f"\n  E_hz measurement: center avg pixel = {E_hz_pixel:.6f}")

    if E_hz_pixel < 1e-10:
        print("  ERROR: Floor grid reads zero — sun not reaching S₂")
        return None

    # Wall pixels (512×512)
    wall_res = 512
    wall_pixels = np.zeros(wall_res * wall_res * 4, dtype=np.float32)
    baked[1][1].pixels.foreach_get(wall_pixels)
    wall_pixels = wall_pixels.reshape((wall_res, wall_res, 4))

    # Ceiling pixels (512×512)
    ceil_res = 512
    ceil_pixels = np.zeros(ceil_res * ceil_res * 4, dtype=np.float32)
    baked[2][1].pixels.foreach_get(ceil_pixels)
    ceil_pixels = ceil_pixels.reshape((ceil_res, ceil_res, 4))

    def sample_grid(pixels, res, u, v):
        px = int(u * (res - 1))
        py = int(v * (res - 1))
        px = max(0, min(res - 1, px))
        py = max(0, min(res - 1, py))
        r_s, g_s, b_s, cnt = 0, 0, 0, 0
        for dy in range(-kernel, kernel + 1):
            for dx in range(-kernel, kernel + 1):
                sx = max(0, min(res - 1, px + dx))
                sy = max(0, min(res - 1, py + dy))
                r_s += pixels[sy, sx, 0]
                g_s += pixels[sy, sx, 1]
                b_s += pixels[sy, sx, 2]
                cnt += 1
        lum = 0.2126 * (r_s / cnt) + 0.7152 * (g_s / cnt) + 0.0722 * (b_s / cnt)
        return lum

    # ── Compute F₁₂ = pixel_reflected / (E_hz_pixel × ρ) × 100 ──
    # All π and luminous efficacy factors cancel in the ratio.
    computed = {}
    normalization = 100.0 / (E_hz_pixel * rho)

    # Wall points B–F
    s1v_z_bot = test_case['s1v_z_bottom_m']
    s1v_h = test_case['s1v_height_m']
    for label, (px, py, pz) in test_case['points_wall'].items():
        u = px / s2_w
        v = 1.0 - (pz - s1v_z_bot) / s1v_h
        val = sample_grid(wall_pixels, wall_res, u, v)
        computed[label] = val * normalization

    # Ceiling points G–N
    # UV mapping for ceiling (π rotation around X): v = 1 - world_y / depth
    for label, (px, py, pz) in test_case['points_ceiling'].items():
        u = px / test_case['s1hz_width_m']
        v = 1.0 - py / test_case['s1hz_depth_m']
        val = sample_grid(ceil_pixels, ceil_res, u, v)
        computed[label] = val * normalization

    print(f"\n  Sampled {len(computed)} measurement points")
    print(f"  E_hz pixel = {E_hz_pixel:.6f}, ρ = {rho}")
    print(f"  Normalization = 100 / (E_hz × ρ) = {normalization:.4f}")

    ref = test_case['reference_form_factor_pct']
    result = compare_results(computed, ref, test_case,
                             label='Blender F₁₂ vs Table 17 (Sun lamp)')

    results_dir = _results_dir('5.6')
    out = {pt: {'F12_blender_pct': computed[pt], 'F12_ref_pct': ref[pt],
                'error_pct': result['errors'].get(pt, 0) * 100}
           for pt in computed}
    with open(os.path.join(results_dir, 'blender_results.json'), 'w') as f:
        json.dump(out, f, indent=2)
    print(f"  Saved results to {results_dir}")

    return result


# ═══════════════════════════════════════════════
# TEST 5.7 — Diffuse Reflections with Internal Obstructions
# ═══════════════════════════════════════════════

def run_5_7_analytical(test_case):
    """Analytical form factor check with obstruction occlusion."""
    print("\n" + "=" * 70)
    print("PHASE A — Analytical Verification (form factor + occlusion)")
    print("=" * 70)

    computed = compute_analytical_5_7(test_case)

    print(f"\nS₂: {test_case['s2_width_m']}m × {test_case['s2_height_m']}m wall, "
          f"ρ={test_case['s2_reflectance']}")
    print(f"Obstruction: {test_case['obs_width_m']}m × {test_case['obs_height_m']}m × "
          f"{test_case['obs_thickness_m']}m at y=[{test_case['obs_y_near_m']}, "
          f"{test_case['obs_y_far_m']}]")
    print(f"Reference: E/(E_v·ρ) = form factor F₁₂ × 100 (%)")
    print(f"NOTE: Using NVIDIA-corrected Table 19 values (CIE original has errata)")

    ref = test_case['reference_form_factor_pct']
    result = compare_results(computed, ref, test_case,
                             label='Analytical F₁₂ vs corrected Table 19')

    results_dir = _results_dir('5.7')
    out = {pt: {'F12_calc_pct': computed[pt], 'F12_ref_pct': ref[pt]}
           for pt in computed}
    with open(os.path.join(results_dir, 'analytical_results.json'), 'w') as f:
        json.dump(out, f, indent=2)

    return result


def run_5_7_blender(test_case):
    """CIE 5.7 — Sun lamp + reflective S₂ wall + obstruction.

    Same ratio approach as 5.6 but with:
    - S₂ is a vertical wall (4m×3m, ρ=0.60) at y=4
    - Sun at 60° incidence on S₂ (rotation around X by -30°)
    - Black obstruction box at y=[2.5, 2.7], z=[0, 1]
    - Reference grid on S₂ to measure E_v
    - F₁₂ = pixel_reflected / (pixel_ref × ρ)
    """
    import bpy
    import numpy as np

    from fixture_config import FT_TO_M, M_TO_FT, CalcGrid
    from scene_builder import (
        clear_scene, configure_cycles_base, add_calc_grid,
        make_diffuse_material, _add_plane,
    )
    from calc_grid_bake import bake_calc_grids

    print("\n" + "=" * 70)
    print("PHASE B — Blender Cycles Render (Sun lamp + obstruction)")
    print("=" * 70)

    s2_w = test_case['s2_width_m']   # 4.0
    s2_h = test_case['s2_height_m']  # 3.0
    s2_y = test_case['s2_y_m']       # 4.0
    rho = test_case['s2_reflectance']  # 0.60

    clear_scene()

    # ── Black world background ──
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new('World')
        bpy.context.scene.world = world
    if hasattr(world, 'use_nodes'):
        world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    if bg:
        bg.inputs['Color'].default_value = (0, 0, 0, 1)
        bg.inputs['Strength'].default_value = 0.0
    print("  World background set to black")

    # ── S₂: Diffuse reflecting vertical wall (ρ=0.60) at y=4 ──
    mat_s2 = make_diffuse_material('S2_Wall', rho)
    _add_plane('S2_Wall', [
        (0, s2_y, 0), (s2_w, s2_y, 0),
        (s2_w, s2_y, s2_h), (0, s2_y, s2_h)
    ], mat_s2, flip=True)  # Normal -Y (facing toward S₁)
    print(f"\n  S₂ wall: {s2_w}m × {s2_h}m at y={s2_y}, ρ={rho}")

    # ── Obstruction: black box between S₁ and S₂ ──
    mat_black = make_diffuse_material('Obstruction_Black', 0.0)
    obs_y0 = test_case['obs_y_near_m']   # 2.5
    obs_y1 = test_case['obs_y_far_m']    # 2.7
    obs_z1 = test_case['obs_z_top_m']    # 1.0

    # Front face (toward S₁, normal -Y)
    _add_plane('Obs_Front', [
        (0, obs_y0, 0), (s2_w, obs_y0, 0),
        (s2_w, obs_y0, obs_z1), (0, obs_y0, obs_z1)
    ], mat_black, flip=True)
    # Back face (toward S₂, normal +Y)
    _add_plane('Obs_Back', [
        (0, obs_y1, 0), (s2_w, obs_y1, 0),
        (s2_w, obs_y1, obs_z1), (0, obs_y1, obs_z1)
    ], mat_black, flip=False)
    # Top face (normal +Z)
    _add_plane('Obs_Top', [
        (0, obs_y0, obs_z1), (s2_w, obs_y0, obs_z1),
        (s2_w, obs_y1, obs_z1), (0, obs_y1, obs_z1)
    ], mat_black, flip=False)
    print(f"  Obstruction: {s2_w}m × {obs_z1}m × "
          f"{test_case['obs_thickness_m']}m at y=[{obs_y0}, {obs_y1}]")

    # ── Sun lamp at 60° incidence on S₂ ──
    # S₂ at y=4, normal -Y (room-facing). Sun must illuminate this face.
    # Sun direction must go TOWARD +Y to hit S₂'s -Y face.
    # direction = (0, +sin30°, -cos30°) = (0, +0.5, -0.866)
    # → dir_to_light = (0, -0.5, +0.866). dot with S₂ normal (0,-1,0) = +0.5 > 0 ✓
    # Rotation: Rx(+30°) on default -Z gives (0, sin30°, -cos30°) = (0, +0.5, -0.866)
    bpy.ops.object.light_add(type='SUN', location=(2, -2, 6))
    sun = bpy.context.active_object
    sun.data.energy = 10.0
    sun.rotation_euler = (math.radians(30), 0, 0)
    print(f"  Sun lamp: energy={sun.data.energy} W/m², 60° incidence on S₂")
    # Note: No geometric blocker needed — S₁ grids use indirect-only bake pass
    # to exclude direct sun. This avoids complex blocker geometry that could
    # interfere with reflected light paths through the obstruction gap.

    # ── Reference grid on S₂ to measure E_v ──
    # S₂ normal -Y. Sun direction (0, +0.5, -0.866) illuminates the -Y face.
    # Reference grid at y=3.999 (just in front of S₂), surface='wall_north'
    # (normal -Y), captures the same illuminance the front face of S₂ receives.
    ref_w_ft = s2_w * M_TO_FT
    ref_h_ft = s2_h * M_TO_FT
    ref_grid = CalcGrid(
        name='CIE_5_7_ref', surface='wall_north',
        width_ft=ref_w_ft, height_ft=ref_h_ft,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=256,
        position_ft=(s2_w / 2 * M_TO_FT,
                     (s2_y - 0.001) * M_TO_FT,
                     s2_h / 2 * M_TO_FT),
    )
    ref_obj, ref_img = add_calc_grid(ref_grid)

    # ── S₁-v calc grid (wall at y=0, facing +Y) ──
    s1v_w_ft = test_case['s1v_width_m'] * M_TO_FT
    s1v_h_ft = test_case['s1v_height_m'] * M_TO_FT
    wall_grid = CalcGrid(
        name='CIE_5_7_S1v', surface='wall_south',
        width_ft=s1v_w_ft, height_ft=s1v_h_ft,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(s2_w / 2 * M_TO_FT,
                     0.001 * M_TO_FT,
                     s2_h / 2 * M_TO_FT),
    )
    wall_obj, wall_img = add_calc_grid(wall_grid)

    # ── S₁-hz calc grid (floor at z=0, facing +Z) ──
    s1hz_w_ft = test_case['s1hz_width_m'] * M_TO_FT
    s1hz_d_ft = test_case['s1hz_depth_m'] * M_TO_FT
    floor_grid = CalcGrid(
        name='CIE_5_7_S1hz', surface='floor',
        width_ft=s1hz_w_ft, height_ft=s1hz_d_ft,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(s2_w / 2 * M_TO_FT,
                     test_case['s1hz_depth_m'] / 2 * M_TO_FT,
                     0.001 * M_TO_FT),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # ── Render settings ──
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 1
    cycles.diffuse_bounces = 1
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True
    print(f"  Render: 4096 samples, 1 bounce")

    # ── Bake in two passes ──
    # Pass 1: Reference grid with direct+indirect (captures E_v from sun)
    baked_ref = bake_calc_grids([(ref_grid, ref_obj, ref_img)])

    # Pass 2: Measurement grids with INDIRECT ONLY
    # This filters out direct sun hitting S₁-hz floor, capturing only
    # reflected light from S₂. S₁-v already doesn't see direct sun
    # (back-face), but indirect-only is cleaner for both.
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = True
    baked_meas = bake_calc_grids([
        (wall_grid, wall_obj, wall_img),
        (floor_grid, floor_obj, floor_img),
    ])

    # ── Read bake results ──
    kernel = 3

    # Reference grid (256²) — measure E_v
    ref_res = 256
    ref_pixels = np.zeros(ref_res * ref_res * 4, dtype=np.float32)
    baked_ref[0][1].pixels.foreach_get(ref_pixels)
    ref_pixels = ref_pixels.reshape((ref_res, ref_res, 4))
    margin = ref_res // 8
    center = ref_pixels[margin:-margin, margin:-margin, :3]
    E_v_pixel = np.mean(
        0.2126 * center[:, :, 0]
        + 0.7152 * center[:, :, 1]
        + 0.0722 * center[:, :, 2]
    )
    print(f"\n  E_v measurement: center avg pixel = {E_v_pixel:.6f}")

    if E_v_pixel < 1e-10:
        print("  ERROR: Reference grid reads zero — sun not reaching S₂")
        return None

    # Wall pixels (512²) — from measurement pass
    wall_res = 512
    wall_pixels = np.zeros(wall_res * wall_res * 4, dtype=np.float32)
    baked_meas[0][1].pixels.foreach_get(wall_pixels)
    wall_pixels = wall_pixels.reshape((wall_res, wall_res, 4))

    # Floor pixels (512²) — from measurement pass
    floor_res = 512
    floor_pixels = np.zeros(floor_res * floor_res * 4, dtype=np.float32)
    baked_meas[1][1].pixels.foreach_get(floor_pixels)
    floor_pixels = floor_pixels.reshape((floor_res, floor_res, 4))

    def sample_grid(pixels, res, u, v):
        px = int(u * (res - 1))
        py = int(v * (res - 1))
        px = max(0, min(res - 1, px))
        py = max(0, min(res - 1, py))
        r_s, g_s, b_s, cnt = 0, 0, 0, 0
        for dy in range(-kernel, kernel + 1):
            for dx in range(-kernel, kernel + 1):
                sx = max(0, min(res - 1, px + dx))
                sy = max(0, min(res - 1, py + dy))
                r_s += pixels[sy, sx, 0]
                g_s += pixels[sy, sx, 1]
                b_s += pixels[sy, sx, 2]
                cnt += 1
        lum = 0.2126 * (r_s / cnt) + 0.7152 * (g_s / cnt) + 0.0722 * (b_s / cnt)
        return lum

    # ── Compute F₁₂ = pixel_reflected / (E_v_pixel × ρ) × 100 ──
    computed = {}
    normalization = 100.0 / (E_v_pixel * rho)

    # Wall points A–F (S₁-v at y=0, 4m wide × 3m high)
    # wall_south UV: u = x/width, v = 1 - z/height
    s1v_h = test_case['s1v_height_m']
    for label, (px, py, pz) in test_case['points_wall'].items():
        u = px / test_case['s1v_width_m']
        v = 1.0 - pz / s1v_h
        val = sample_grid(wall_pixels, wall_res, u, v)
        computed[label] = val * normalization

    # Floor points G–K (S₁-hz at z=0, 4m wide × 2.5m deep)
    for label, (px, py, pz) in test_case['points_floor'].items():
        u = px / test_case['s1hz_width_m']
        v = py / test_case['s1hz_depth_m']
        val = sample_grid(floor_pixels, floor_res, u, v)
        computed[label] = val * normalization

    print(f"\n  Sampled {len(computed)} measurement points")
    print(f"  E_v pixel = {E_v_pixel:.6f}, ρ = {rho}")
    print(f"  Normalization = 100 / (E_v × ρ) = {normalization:.4f}")

    ref = test_case['reference_form_factor_pct']
    result = compare_results(computed, ref, test_case,
                             label='Blender F₁₂ vs corrected Table 19 (Sun lamp)')

    results_dir = _results_dir('5.7')
    out = {pt: {'F12_blender_pct': computed[pt], 'F12_ref_pct': ref[pt],
                'error_pct': result['errors'].get(pt, 0) * 100}
           for pt in computed}
    with open(os.path.join(results_dir, 'blender_results.json'), 'w') as f:
        json.dump(out, f, indent=2)
    print(f"  Saved results to {results_dir}")

    return result


# ═══════════════════════════════════════════════
# TEST 5.4 — Luminous Flux Conservation
# ═══════════════════════════════════════════════

def run_5_4_blender(test_case):
    """Measure total flux on all 6 room surfaces, compare to emitted flux.

    Scene: 4m×4m×3m room, black surfaces (ρ=0), isotropic source at center.
    Places calc grids on floor, ceiling, and all 4 walls.
    Extracts average illuminance from each baked texture, computes flux = E_avg × area.
    """
    import bpy
    import numpy as np

    from fixture_config import FT_TO_M, M_TO_FT, Fixture, CalcGrid, Room
    from scene_builder import (
        clear_scene, build_floor_plan, add_fixture, add_calc_grid,
        configure_cycles_base,
    )
    from calc_grid_bake import bake_calc_grids

    print("\n" + "=" * 70)
    print("Blender Flux Conservation Test")
    print("=" * 70)

    # Generate isotropic IES
    ies_path = os.path.join(_THIS_DIR, 'ies', 'cie_isotropic_10000lm.ies')
    generate_isotropic_ies(test_case['flux_lm'], ies_path)

    room_w = test_case['room_size_m']   # 4m
    room_d = test_case['room_size_m']   # 4m
    room_h = test_case['room_height_m'] # 3m
    room_w_ft = room_w * M_TO_FT
    room_d_ft = room_d * M_TO_FT
    room_h_ft = room_h * M_TO_FT
    cx_ft = room_w_ft / 2
    cy_ft = room_d_ft / 2
    cz_ft = room_h_ft / 2

    clear_scene()

    room = Room(name='CIE_5_4', origin_ft=(0, 0),
                width_ft=room_w_ft, depth_ft=room_d_ft, height_ft=room_h_ft,
                reflectances={'ceiling': 0.0, 'walls': 0.0, 'floor': 0.0})
    build_floor_plan([room])

    # Isotropic source at room center
    fixture = Fixture(
        ies_path=ies_path,
        position_ft=(cx_ft, cy_ft, cz_ft),
        width_inches=0.4,
        cos_clamp=0.01,
    )
    add_fixture(fixture, fixture_id=1)

    # Calc grids on all 6 surfaces — small offset to avoid z-fighting
    off = 0.002  # 2mm offset from surface
    res = 256

    surface_defs = [
        ('Floor',      'floor',      (cx_ft, cy_ft, off * M_TO_FT),
         room_w_ft, room_d_ft, room_w * room_d),
        ('Ceiling',    'ceiling',    (cx_ft, cy_ft, (room_h - off) * M_TO_FT),
         room_w_ft, room_d_ft, room_w * room_d),
        ('Wall_South', 'wall_south', (cx_ft, off * M_TO_FT, cz_ft),
         room_w_ft, room_h_ft, room_w * room_h),
        ('Wall_North', 'wall_north', (cx_ft, (room_d - off) * M_TO_FT, cz_ft),
         room_w_ft, room_h_ft, room_w * room_h),
        ('Wall_West',  'wall_west',  (off * M_TO_FT, cy_ft, cz_ft),
         room_h_ft, room_d_ft, room_d * room_h),
        ('Wall_East',  'wall_east',  ((room_w - off) * M_TO_FT, cy_ft, cz_ft),
         room_h_ft, room_d_ft, room_d * room_h),
    ]

    grid_objects = []
    surface_areas = {}
    for name, surface, pos_ft, w_ft, h_ft, area_m2 in surface_defs:
        cg = CalcGrid(
            name=f'CIE_5_4_{name}',
            surface=surface,
            width_ft=w_ft, height_ft=h_ft,
            spacing_ft=1.0, inset_ft=0.0, offset_ft=0.0,
            bake_resolution=res,
            position_ft=pos_ft,
        )
        obj, img = add_calc_grid(cg)
        grid_objects.append((cg, obj, img))
        surface_areas[name] = area_m2

    # Render — direct only, isotropic source
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 0
    cycles.diffuse_bounces = 0
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    print(f"\n  Render: 4096 samples, 0 bounces (direct only)")

    baked = bake_calc_grids(grid_objects)

    # Extract average illuminance from each surface
    LUMINOUS_EFFICACY = 179.0
    total_flux = 0.0
    surface_results = []

    print(f"\n  {'Surface':<12}  {'Area (m²)':>9}  {'Avg E (lx)':>10}  {'Flux (lm)':>9}")
    print(f"  {'-'*12:<12}  {'-'*9:>9}  {'-'*10:>10}  {'-'*9:>9}")

    for i, (cg, bake_img) in enumerate(baked):
        pixels = np.zeros(res * res * 4, dtype=np.float32)
        bake_img.pixels.foreach_get(pixels)
        pixels = pixels.reshape((res, res, 4))

        luminance = 0.2126 * pixels[:, :, 0] + 0.7152 * pixels[:, :, 1] + 0.0722 * pixels[:, :, 2]
        avg_lux = float(np.mean(luminance)) * LUMINOUS_EFFICACY

        name = surface_defs[i][0]
        area = surface_areas[name]
        flux = avg_lux * area
        total_flux += flux

        print(f"  {name:<12}  {area:>9.1f}  {avg_lux:>10.2f}  {flux:>9.1f}")
        surface_results.append({
            'name': name,
            'area_m2': area,
            'avg_lux': avg_lux,
            'flux_lm': flux,
        })

    emitted = test_case['flux_lm']
    ratio = total_flux / emitted
    error_pct = (ratio - 1.0) * 100

    print(f"\n  {'Total flux on surfaces:':<30} {total_flux:>10.1f} lm")
    print(f"  {'Emitted flux:':<30} {emitted:>10.1f} lm")
    print(f"  {'R_S = Φ_i / Φ_0:':<30} {ratio:>10.4f}")
    print(f"  {'Error:':<30} {error_pct:>+9.2f}%")
    print(f"  {'Status:':<30} {'PASS' if abs(error_pct) <= test_case['global_tolerance'] * 100 else 'FAIL'}")

    passed = abs(error_pct / 100) <= test_case['global_tolerance']

    # Save results
    results_dir = _results_dir('5.4')
    out = {
        'emitted_flux_lm': emitted,
        'total_surface_flux_lm': total_flux,
        'ratio': ratio,
        'error_pct': error_pct,
        'pass': passed,
        'surfaces': surface_results,
    }
    json_path = os.path.join(results_dir, 'blender_results.json')
    with open(json_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n  Saved: {json_path}")

    return {
        'pass': passed,
        'max_error': abs(error_pct / 100),
        'mean_error': abs(error_pct / 100),
        'errors': {'flux_ratio': error_pct / 100},
        'n_failing': 0 if passed else 1,
    }


# ═══════════════════════════════════════════════
# TEST 5.8 — Internal Reflected Component
# ═══════════════════════════════════════════════

def run_5_8_analytical(test_case):
    """Analytical check: E_avg = (1/S_T) × ρΦ/(1-ρ) vs Table 20."""
    print("\n" + "=" * 70)
    print("PHASE A — Analytical Verification (pure math)")
    print("=" * 70)

    computed = compute_analytical_5_8(test_case)
    S_T = test_case['total_surface_m2']
    phi = test_case['flux_lm']

    print(f"\nRoom: {test_case['room_size_m']:.0f}m cube, S_T = {S_T:.0f} m²")
    print(f"Source: isotropic, Φ = {phi:.0f} lm")
    print(f"Formula: E_indirect = (1/S_T) × ρΦ/(1-ρ)")
    print(f"\n{'ρ':>6}  {'E_dir':>8}  {'E_ind(ref)':>10}  {'E_ind(calc)':>11}  {'E_total':>8}")
    print(f"{'-'*6:>6}  {'-'*8:>8}  {'-'*10:>10}  {'-'*11:>11}  {'-'*8:>8}")

    for rho in test_case['reflectances']:
        r = computed[rho]
        ref = test_case['reference_E_indirect'][rho]
        print(f"{rho:>6.2f}  {r['E_direct']:>8.2f}  {ref:>10.2f}  {r['E_indirect']:>11.2f}  {r['E_total']:>8.2f}")

    # Compare indirect illuminance against reference
    computed_indirect = {rho: computed[rho]['E_indirect'] for rho in test_case['reflectances']}
    result = compare_results(computed_indirect, test_case['reference_E_indirect'],
                             test_case, label='Analytical E_indirect vs Table 20')

    results_dir = _results_dir('5.8')
    out = {}
    for rho in test_case['reflectances']:
        r = computed[rho]
        out[str(rho)] = {
            'reflectance': rho,
            'E_direct': r['E_direct'],
            'E_indirect_calc': r['E_indirect'],
            'E_indirect_ref': test_case['reference_E_indirect'][rho],
            'E_total': r['E_total'],
        }
    json_path = os.path.join(results_dir, 'analytical_results.json')
    with open(json_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n  Saved: {json_path}")

    return result


def run_5_8_blender(test_case):
    """Build CIE 5.8 scene in Blender — run multiple reflectances.

    For each reflectance:
      1. Build 4m cube room with uniform reflectance
      2. Add isotropic point source at center (10,000 lm)
      3. Add calc grid on floor
      4. Bake with full bounces, extract average illuminance
      5. Compute indirect = total - direct(ρ=0)

    The ρ=0 run gives the direct component baseline.
    """
    import bpy
    import numpy as np

    from fixture_config import FT_TO_M, M_TO_FT, Fixture, CalcGrid, Room
    from scene_builder import (
        clear_scene, build_floor_plan, add_fixture, add_calc_grid,
        configure_cycles_base,
    )
    from calc_grid_bake import bake_calc_grids

    print("\n" + "=" * 70)
    print("PHASE B — Blender Cycles Render")
    print("=" * 70)

    # Generate isotropic IES
    ies_path = os.path.join(_THIS_DIR, 'ies', 'cie_isotropic_10000lm.ies')
    generate_isotropic_ies(test_case['flux_lm'], ies_path)
    print(f"\n  Generated IES: {ies_path}")

    room_m = test_case['room_size_m']  # 4m
    room_ft = room_m * M_TO_FT
    cx_ft = room_ft / 2
    cy_ft = room_ft / 2
    cz_ft = (room_m / 2) * M_TO_FT  # center height = 2m

    LUMINOUS_EFFICACY = 179.0

    # Render settings per reflectance tier
    def get_samples_and_bounces(rho):
        if rho <= 0.0:
            return 1024, 0      # direct only
        elif rho <= 0.30:
            return 2048, 16
        elif rho <= 0.60:
            return 4096, 32
        elif rho <= 0.70:
            return 4096, 64
        elif rho <= 0.80:
            return 4096, 256
        elif rho <= 0.90:
            return 8192, 1024   # ρ=0.90: mean 10 bounces, need ~100+ for convergence
        else:
            return 8192, 4096   # ρ=0.95: mean 20 bounces, need ~400+ for convergence

    results_by_rho = {}
    direct_baseline = None

    for rho in test_case['reflectances']:
        samples, bounces = get_samples_and_bounces(rho)

        print(f"\n{'─'*70}")
        print(f"  ρ = {rho:.2f}  |  samples={samples}, bounces={bounces}")
        print(f"{'─'*70}")

        clear_scene()

        room = Room(
            name=f'CIE_5_8_rho{int(rho*100):03d}',
            origin_ft=(0, 0),
            width_ft=room_ft,
            depth_ft=room_ft,
            height_ft=room_ft,
            reflectances={'ceiling': rho, 'walls': rho, 'floor': rho},
        )
        build_floor_plan([room])

        fixture = Fixture(
            ies_path=ies_path,
            position_ft=(cx_ft, cy_ft, cz_ft),
            width_inches=0.4,
            cos_clamp=0.01,
        )
        add_fixture(fixture, fixture_id=1)

        # Calc grid on floor, covering the full 4m × 4m
        calc_grid = CalcGrid(
            name=f'Floor_rho{int(rho*100):03d}',
            surface='floor',
            width_ft=room_ft,
            height_ft=room_ft,
            spacing_ft=1.0,
            inset_ft=0.0,
            offset_ft=0.001,  # tiny offset above floor to avoid z-fighting
            bake_resolution=256,
            position_ft=(cx_ft, cy_ft, 0.001),
        )
        obj, bake_img = add_calc_grid(calc_grid)

        # Configure render
        scene = bpy.context.scene
        cycles = scene.cycles
        configure_cycles_base(scene)

        cycles.samples = samples
        cycles.max_bounces = bounces
        cycles.diffuse_bounces = bounces
        cycles.glossy_bounces = 0
        cycles.transmission_bounces = 0
        cycles.use_denoising = False
        cycles.sample_clamp_direct = 0.0
        cycles.sample_clamp_indirect = 0.0
        cycles.film_exposure = 1.0

        scene.view_settings.view_transform = 'Raw'
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
        scene.render.bake.use_pass_direct = True
        scene.render.bake.use_pass_indirect = True

        # Bake
        grid_objects = [(calc_grid, obj, bake_img)]
        baked = bake_calc_grids(grid_objects)

        # Extract average illuminance from baked texture
        bake_img_data = baked[0][1]
        res = calc_grid.bake_resolution
        pixels = np.zeros(res * res * 4, dtype=np.float32)
        bake_img_data.pixels.foreach_get(pixels)
        pixels = pixels.reshape((res, res, 4))

        # Average over all pixels (uniform illuminance expected)
        luminance = 0.2126 * pixels[:, :, 0] + 0.7152 * pixels[:, :, 1] + 0.0722 * pixels[:, :, 2]
        avg_lux = float(np.mean(luminance)) * LUMINOUS_EFFICACY

        if rho == 0.0:
            direct_baseline = avg_lux
            E_indirect = 0.0
        else:
            E_indirect = avg_lux - direct_baseline

        print(f"    E_total = {avg_lux:.2f} lx")
        print(f"    E_direct(baseline) = {direct_baseline:.2f} lx")
        print(f"    E_indirect = {E_indirect:.2f} lx")
        print(f"    E_indirect(ref) = {test_case['reference_E_indirect'][rho]:.2f} lx")

        results_by_rho[rho] = {
            'E_total': avg_lux,
            'E_direct': direct_baseline,
            'E_indirect': E_indirect,
        }

    # Compare indirect values
    computed_indirect = {rho: results_by_rho[rho]['E_indirect'] for rho in test_case['reflectances']}
    result = compare_results(computed_indirect, test_case['reference_E_indirect'],
                             test_case, label='Blender E_indirect vs Table 20')

    # Save results
    results_dir = _results_dir('5.8')
    out = {}
    for rho in test_case['reflectances']:
        r = results_by_rho[rho]
        ref = test_case['reference_E_indirect'][rho]
        out[str(rho)] = {
            'reflectance': rho,
            'E_total_blender': r['E_total'],
            'E_direct_blender': r['E_direct'],
            'E_indirect_blender': r['E_indirect'],
            'E_indirect_ref': ref,
            'error_pct': result['errors'].get(rho, 0) * 100,
        }
    json_path = os.path.join(results_dir, 'blender_results.json')
    with open(json_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n  Saved: {json_path}")

    return result


# ═══════════════════════════════════════════════
# TEST 5.3 — Area Light Sources (Diffuse)
# ═══════════════════════════════════════════════

def run_5_3_analytical(test_case):
    """Analytical check for area source illuminance."""
    print("\n" + "=" * 70)
    print("PHASE A — Analytical Verification (numerical integration)")
    print("=" * 70)

    computed = compute_analytical_5_3(test_case)

    print(f"\nSource: 1m×1m at ceiling center, I₀={test_case['I0_cd']:.0f} cd, Lambertian")
    print(f"Room: {test_case['room_width_m']:.0f}×{test_case['room_depth_m']:.0f}×{test_case['room_height_m']:.0f}m")

    # Flatten for comparison
    computed_flat = {k: v['E_lux'] for k, v in computed.items()}
    result = compare_results(computed_flat, test_case['reference_E_lux'],
                             test_case, label='Analytical vs Table 12')

    results_dir = _results_dir('5.3')
    out = {pt: {'E_lux_calc': computed[pt]['E_lux'],
                'E_lux_ref': test_case['reference_E_lux'][pt]}
           for pt in computed}
    with open(os.path.join(results_dir, 'analytical_results.json'), 'w') as f:
        json.dump(out, f, indent=2)

    return result


def run_5_3_blender(test_case):
    """Build CIE 5.3 scene in Blender — area source with wall + floor grids."""
    import bpy
    import numpy as np

    from fixture_config import FT_TO_M, M_TO_FT, Fixture, CalcGrid, Room
    from scene_builder import (
        clear_scene, build_floor_plan, add_fixture, add_calc_grid,
        configure_cycles_base,
    )
    from calc_grid_bake import bake_calc_grids

    print("\n" + "=" * 70)
    print("PHASE B — Blender Cycles Render")
    print("=" * 70)

    # Generate Lambertian IES
    ies_path = os.path.join(_THIS_DIR, 'ies', 'cie_diffuse_1000cd.ies')
    generate_lambertian_ies(test_case['I0_cd'], ies_path)

    room_w = test_case['room_width_m']
    room_d = test_case['room_depth_m']
    room_h = test_case['room_height_m']
    room_w_ft = room_w * M_TO_FT
    room_d_ft = room_d * M_TO_FT
    room_h_ft = room_h * M_TO_FT

    clear_scene()

    # Room slightly taller than 3m so the ceiling doesn't coincide with the emitter
    # (z-fighting would block emitted light). Emitter goes at exactly z=3.0m.
    room_h_actual = room_h + 0.01  # 3.01m ceiling
    room_h_actual_ft = room_h_actual * M_TO_FT
    room = Room(name='CIE_5_3', origin_ft=(0, 0),
                width_ft=room_w_ft, depth_ft=room_d_ft, height_ft=room_h_actual_ft,
                reflectances={'ceiling': 0.0, 'walls': 0.0, 'floor': 0.0})
    build_floor_plan([room])

    # 1m × 1m area emitter at ceiling center — discretized into N×N sub-emitters.
    # Each sub-emitter is a small point-like source where the IES formula works.
    # This mirrors the analytical discretization in ies_direct_calc.py.
    ies_path = os.path.join(_THIS_DIR, 'ies', 'cie_diffuse_1000cd.ies')
    generate_lambertian_ies(test_case['I0_cd'], ies_path)

    src_w = test_case['source_width_m']
    src_d = test_case['source_depth_m']
    N = 10  # 10×10 = 100 sub-emitters
    sub_w = src_w / N  # 0.1m per sub-element
    sub_d = src_d / N
    sub_w_in = sub_w * M_TO_FT * 12  # ~1.6 inches

    src_cx = room_w / 2  # source center in meters
    src_cy = room_d / 2

    fid = 1
    for ix in range(N):
        for iy in range(N):
            sx = src_cx - src_w/2 + (ix + 0.5) * sub_w
            sy = src_cy - src_d/2 + (iy + 0.5) * sub_d
            sz = room_h  # ceiling

            fixture = Fixture(
                ies_path=ies_path,
                position_ft=(sx * M_TO_FT, sy * M_TO_FT, sz * M_TO_FT),
                width_inches=sub_w_in,
                cos_clamp=0.01,
                lumen_scale=1.0 / (N * N),  # each sub-emitter gets 1/N² of the flux
            )
            add_fixture(fixture, fixture_id=fid)
            fid += 1

    print(f"\n  Area source: {src_w}m × {src_d}m, discretized {N}×{N} = {N*N} sub-emitters")
    print(f"  Sub-emitter size: {sub_w*100:.1f}cm × {sub_d*100:.1f}cm")
    print(f"  I₀ = {test_case['I0_cd']:.0f} cd, Φ = {test_case['flux_lm']:.0f} lm")

    cx_ft = room_w_ft / 2
    cy_ft = room_d_ft / 2

    # Floor calc grid: full 4m × 4m floor
    floor_grid = CalcGrid(
        name='CIE_5_3_Floor', surface='floor',
        width_ft=room_w_ft, height_ft=room_d_ft,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.001,
        bake_resolution=512,
        position_ft=(cx_ft, cy_ft, 0.001),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # Wall calc grid: south wall (y=0), 4m wide × 3m high
    wall_grid = CalcGrid(
        name='CIE_5_3_Wall', surface='wall_south',
        width_ft=room_w_ft, height_ft=room_h_ft,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.001,
        bake_resolution=512,
        position_ft=(cx_ft, 0.001 * M_TO_FT, room_h_ft / 2),
    )
    wall_obj, wall_img = add_calc_grid(wall_grid)

    # Render
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 0
    cycles.diffuse_bounces = 0
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    print(f"\n  Render: 4096 samples, 1 bounce (emitter → surface)")

    # Bake both grids
    grid_objects = [
        (floor_grid, floor_obj, floor_img),
        (wall_grid, wall_obj, wall_img),
    ]
    baked = bake_calc_grids(grid_objects)

    LUMINOUS_EFFICACY = 179.0

    # Read floor pixels
    floor_pixels = np.zeros(512 * 512 * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(floor_pixels)
    floor_pixels = floor_pixels.reshape((512, 512, 4))

    # Read wall pixels
    wall_pixels = np.zeros(512 * 512 * 4, dtype=np.float32)
    baked[1][1].pixels.foreach_get(wall_pixels)
    wall_pixels = wall_pixels.reshape((512, 512, 4))

    computed = {}
    kernel = 3

    def sample_grid(pixels, res, u, v):
        px = int(u * (res - 1))
        py = int(v * (res - 1))
        px = max(0, min(res - 1, px))
        py = max(0, min(res - 1, py))
        r_s, g_s, b_s, cnt = 0, 0, 0, 0
        for dy in range(-kernel, kernel + 1):
            for dx in range(-kernel, kernel + 1):
                sx = max(0, min(res - 1, px + dx))
                sy = max(0, min(res - 1, py + dy))
                r_s += pixels[sy, sx, 0]
                g_s += pixels[sy, sx, 1]
                b_s += pixels[sy, sx, 2]
                cnt += 1
        lum = 0.2126 * (r_s/cnt) + 0.7152 * (g_s/cnt) + 0.0722 * (b_s/cnt)
        return lum * LUMINOUS_EFFICACY

    # Floor points G–N: y varies from 0.25 to 3.75, x=2.0
    # UV: u = x/room_w, v = y/room_d
    for label, (px, py, pz) in test_case['points_floor'].items():
        u = px / room_w
        v = py / room_d
        computed[label] = sample_grid(floor_pixels, 512, u, v)

    # Wall points A–F: z varies from 2.75 to 0.25, x=2.0
    # Wall_south grid: after -π/2 rotation around X, UV v is inverted relative to world Z.
    # v=0 → ceiling (z=room_h), v=1 → floor (z=0). So v = 1 - z/room_h_actual.
    for label, (px, py, pz) in test_case['points_wall'].items():
        u = px / room_w
        v = 1.0 - pz / room_h_actual
        computed[label] = sample_grid(wall_pixels, 512, u, v)

    print(f"\n  Sampled {len(computed)} measurement points")

    result = compare_results(computed, test_case['reference_E_lux'],
                             test_case, label='Blender Cycles vs Table 12')

    # Save
    results_dir = _results_dir('5.3')
    out = {pt: {'E_lux_blender': computed[pt],
                'E_lux_ref': test_case['reference_E_lux'][pt],
                'error_pct': result['errors'].get(pt, 0) * 100}
           for pt in computed}
    with open(os.path.join(results_dir, 'blender_results.json'), 'w') as f:
        json.dump(out, f, indent=2)
    print(f"  Saved results to {results_dir}")

    return result


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = sys.argv
    if '--' in args:
        args = args[args.index('--') + 1:]

    analytical_only = '--analytical-only' in args

    # Determine test
    test_id = '5.2'  # default
    for i, arg in enumerate(args):
        if arg == '--test' and i + 1 < len(args):
            test_id = args[i + 1]

    if test_id == '5.2':
        test_case = TEST_5_2_DIFFUSE
        print("\n" + "#" * 70)
        print(f"# CIE 171:2006 — Test 5.2: Point Light Sources (Diffuse)")
        print("#" * 70)

        analytical_result = run_5_2_analytical(test_case)

        if analytical_only:
            print("\n  (--analytical-only: skipping Blender render)")
            sys.exit(0 if analytical_result['pass'] else 1)

        blender_result = run_5_2_blender(test_case)

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Analytical: {'PASS' if analytical_result['pass'] else 'FAIL'}"
              f"  (max err: {analytical_result['max_error']:.2%})")
        print(f"  Blender:    {'PASS' if blender_result['pass'] else 'FAIL'}"
              f"  (max err: {blender_result['max_error']:.2%})")

    elif test_id == '5.3':
        test_case = TEST_5_3_DIFFUSE
        print("\n" + "#" * 70)
        print(f"# CIE 171:2006 — Test 5.3: Area Light Sources (Diffuse)")
        print("#" * 70)

        analytical_result = run_5_3_analytical(test_case)

        if analytical_only:
            print("\n  (--analytical-only: skipping Blender render)")
            sys.exit(0 if analytical_result['pass'] else 1)

        blender_result = run_5_3_blender(test_case)

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Analytical: {'PASS' if analytical_result['pass'] else 'FAIL'}"
              f"  (max err: {analytical_result['max_error']:.2%})")
        print(f"  Blender:    {'PASS' if blender_result['pass'] else 'FAIL'}"
              f"  (max err: {blender_result['max_error']:.2%})")

    elif test_id == '5.6':
        test_case = TEST_5_6_SCENARIO2
        print("\n" + "#" * 70)
        print(f"# CIE 171:2006 — Test 5.6: Light Reflection over Diffuse Surfaces")
        print("#" * 70)

        analytical_result = run_5_6_analytical(test_case)

        if analytical_only:
            print("\n  (--analytical-only: skipping Blender render)")
            sys.exit(0 if analytical_result['pass'] else 1)

        blender_result = run_5_6_blender(test_case)

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Analytical: {'PASS' if analytical_result['pass'] else 'FAIL'}"
              f"  (max err: {analytical_result['max_error']:.2%})")
        print(f"  Blender:    {'PASS' if blender_result['pass'] else 'FAIL'}"
              f"  (max err: {blender_result['max_error']:.2%})")

    elif test_id == '5.7':
        test_case = TEST_5_7
        print("\n" + "#" * 70)
        print(f"# CIE 171:2006 — Test 5.7: Diffuse Reflections with Internal Obstructions")
        print("#" * 70)

        analytical_result = run_5_7_analytical(test_case)

        if analytical_only:
            print("\n  (--analytical-only: skipping Blender render)")
            sys.exit(0 if analytical_result['pass'] else 1)

        blender_result = run_5_7_blender(test_case)

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Analytical: {'PASS' if analytical_result['pass'] else 'FAIL'}"
              f"  (max err: {analytical_result['max_error']:.2%})")
        print(f"  Blender:    {'PASS' if blender_result['pass'] else 'FAIL'}"
              f"  (max err: {blender_result['max_error']:.2%})")

    elif test_id == '5.4':
        test_case = TEST_5_4
        print("\n" + "#" * 70)
        print(f"# CIE 171:2006 — Test 5.4: Luminous Flux Conservation")
        print("#" * 70)

        if analytical_only:
            print("\n  Test 5.4 is trivially analytical (Φ_i/Φ_0 = 1.0 by definition).")
            print("  Run without --analytical-only for Blender verification.")
            sys.exit(0)

        blender_result = run_5_4_blender(test_case)

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Blender: {'PASS' if blender_result['pass'] else 'FAIL'}"
              f"  (error: {blender_result['max_error']:.2%})")

    elif test_id == '5.8':
        test_case = TEST_5_8
        print("\n" + "#" * 70)
        print(f"# CIE 171:2006 — Test 5.8: Internal Reflected Component (Diffuse)")
        print("#" * 70)

        analytical_result = run_5_8_analytical(test_case)

        if analytical_only:
            print("\n  (--analytical-only: skipping Blender render)")
            sys.exit(0 if analytical_result['pass'] else 1)

        blender_result = run_5_8_blender(test_case)

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Analytical: {'PASS' if analytical_result['pass'] else 'FAIL'}"
              f"  (max err: {analytical_result['max_error']:.2%})")
        print(f"  Blender:    {'PASS' if blender_result['pass'] else 'FAIL'}"
              f"  (max err: {blender_result['max_error']:.2%})")

    else:
        print(f"Unknown test: {test_id}")
        print("Available: 5.2, 5.3, 5.4, 5.6, 5.8")
        sys.exit(1)


if __name__ == '__main__':
    main()
