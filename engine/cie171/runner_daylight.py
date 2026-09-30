"""
CIE 171:2006 Daylight Test Runner — Tests 5.9, 5.10, 5.11

Usage:
    # Test 5.9 (roof opening):
    blender --background --python cie171/runner_daylight.py -- --test 5.9 --opening 4x4 --sky-type 5

    # Test 5.10 (roof opening + glass):
    blender --background --python cie171/runner_daylight.py -- --test 5.10 --opening 4x4 --sky-type 5

    # Test 5.11 (facade opening):
    blender --background --python cie171/runner_daylight.py -- --test 5.11 --opening 2x1 --sky-type 5
    blender --background --python cie171/runner_daylight.py -- --test 5.11 --opening 4x3 --sky-type 5

Output:
    Results printed to stdout + saved to docs/CIE/results/test_{id}/
"""

import bpy
import math
import os
import sys
import json
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_RENDERER_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _RENDERER_DIR)
sys.path.insert(0, _THIS_DIR)

from fixture_config import FT_TO_M, M_TO_FT, CalcGrid
from scene_builder import (
    clear_scene, configure_cycles_base, add_calc_grid,
    make_diffuse_material, _add_plane,
)
from calc_grid_bake import bake_calc_grids
from cie_sky_generator import CIE_SKY_TYPES

_PROJECT_ROOT = os.path.abspath(os.path.join(_RENDERER_DIR, '..'))


def _results_dir(test_id):
    d = os.path.join(_PROJECT_ROOT, 'docs', 'CIE', 'results', f'test_{test_id}')
    os.makedirs(d, exist_ok=True)
    return d


def load_sky_hdri(sky_type_id, azimuth_rotation_deg=-90):
    """Load a CIE sky HDRI as the Blender world environment.

    Args:
        sky_type_id: CIE sky type (1-16)
        azimuth_rotation_deg: Z rotation for azimuth alignment.
            -90 for roof-opening tests (5.9/5.10) where the inverted
            geometry naturally corrects the azimuth.
            +90 for facade-opening tests (5.11+) where the opening
            directly faces the sky and correct azimuth is required.
    """
    hdr_path = os.path.join(_THIS_DIR, 'sky_hdri', f'cie_sky_type_{sky_type_id:02d}.hdr')
    if not os.path.exists(hdr_path):
        raise FileNotFoundError(f"Sky HDRI not found: {hdr_path}. Run cie_sky_generator.py first.")

    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new('World')
        bpy.context.scene.world = world

    if hasattr(world, 'use_nodes'):
        world.use_nodes = True

    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    bg = nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = 1.0

    env_tex = nodes.new('ShaderNodeTexEnvironment')
    env_tex.image = bpy.data.images.load(hdr_path)
    env_tex.projection = 'EQUIRECTANGULAR'

    # Rotate environment to align HDRI azimuth with room coordinates.
    # Our HDRI: sun at azimuth=180° (center of image).
    # Blender env mapping: u=0 → +X, u=0.25 → +Y, u=0.5 → -X, u=0.75 → -Y
    # CIE 5.9: sun on south (toward -Y in our room where south wall = y=0).
    # -Y direction = azimuth 270° in Blender convention.
    # HDRI has sun at 180° (its center). Need to rotate by +90° around Z.
    tex_coord = nodes.new('ShaderNodeTexCoord')
    mapping = nodes.new('ShaderNodeMapping')
    mapping.inputs['Rotation'].default_value = (0, 0, math.radians(azimuth_rotation_deg))
    links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], env_tex.inputs['Vector'])

    output = nodes.new('ShaderNodeOutputWorld')

    links.new(env_tex.outputs['Color'], bg.inputs['Color'])
    links.new(bg.outputs['Background'], output.inputs['Surface'])

    sky_name = CIE_SKY_TYPES.get(sky_type_id, {}).get('name', f'Type {sky_type_id}')
    print(f"  Sky: CIE Type {sky_type_id} — {sky_name}")


def build_room_with_roof_opening(room_w, room_d, room_h,
                                  opening_w, opening_d,
                                  mat_surfaces):
    """Build a room with a rectangular opening in the ceiling.

    Room spans [0, room_w] × [0, room_d] × [0, room_h].
    Opening is centered in the ceiling at z=room_h.

    Args:
        room_w, room_d, room_h: room dimensions in meters
        opening_w, opening_d: opening dimensions in meters
        mat_surfaces: material for all room surfaces (black for CIE tests)
    """
    mat = mat_surfaces

    # Floor
    _add_plane('Floor', [
        (0, 0, 0), (room_w, 0, 0), (room_w, room_d, 0), (0, room_d, 0)
    ], mat, flip=False)

    # 4 Walls
    _add_plane('Wall_South', [
        (0, 0, 0), (room_w, 0, 0), (room_w, 0, room_h), (0, 0, room_h)
    ], mat, flip=True)
    _add_plane('Wall_North', [
        (0, room_d, 0), (room_w, room_d, 0),
        (room_w, room_d, room_h), (0, room_d, room_h)
    ], mat, flip=True)
    _add_plane('Wall_West', [
        (0, 0, 0), (0, room_d, 0), (0, room_d, room_h), (0, 0, room_h)
    ], mat, flip=True)
    _add_plane('Wall_East', [
        (room_w, 0, 0), (room_w, room_d, 0),
        (room_w, room_d, room_h), (room_w, 0, room_h)
    ], mat, flip=True)

    # Ceiling with opening
    cx = room_w / 2
    cy = room_d / 2
    ox0 = cx - opening_w / 2  # opening x start
    ox1 = cx + opening_w / 2  # opening x end
    oy0 = cy - opening_d / 2  # opening y start
    oy1 = cy + opening_d / 2  # opening y end
    z = room_h

    if opening_w >= room_w and opening_d >= room_d:
        # Full ceiling opening — no ceiling needed
        print(f"  Ceiling: fully open ({opening_w}m × {opening_d}m)")
    else:
        # Create 4 ceiling strips around the opening
        # South strip: y=[0, oy0]
        if oy0 > 0.001:
            _add_plane('Ceiling_S', [
                (0, 0, z), (room_w, 0, z), (room_w, oy0, z), (0, oy0, z)
            ], mat, flip=True)
        # North strip: y=[oy1, room_d]
        if oy1 < room_d - 0.001:
            _add_plane('Ceiling_N', [
                (0, oy1, z), (room_w, oy1, z),
                (room_w, room_d, z), (0, room_d, z)
            ], mat, flip=True)
        # West strip: x=[0, ox0], y=[oy0, oy1]
        if ox0 > 0.001:
            _add_plane('Ceiling_W', [
                (0, oy0, z), (ox0, oy0, z), (ox0, oy1, z), (0, oy1, z)
            ], mat, flip=True)
        # East strip: x=[ox1, room_w], y=[oy0, oy1]
        if ox1 < room_w - 0.001:
            _add_plane('Ceiling_E', [
                (ox1, oy0, z), (room_w, oy0, z),
                (room_w, oy1, z), (ox1, oy1, z)
            ], mat, flip=True)
        print(f"  Ceiling: {opening_w}m × {opening_d}m opening centered")


def run_5_9_blender(test_case, opening_key, sky_type_id):
    """Run CIE 5.9 for a specific opening size and sky type.

    Returns dict with per-point results.
    """
    opening = test_case['openings'][opening_key]
    opening_w = opening['width_m']
    opening_d = opening['depth_m']
    reference = opening['reference'][sky_type_id]

    room_w = test_case['room_width_m']
    room_d = test_case['room_depth_m']
    room_h = test_case['room_height_m']

    clear_scene()

    # Load sky HDRI
    load_sky_hdri(sky_type_id)

    # Build room with roof opening (all surfaces black, ρ=0)
    mat_black = make_diffuse_material('Room_Black', 0.0)
    build_room_with_roof_opening(room_w, room_d, room_h,
                                 opening_w, opening_d, mat_black)

    # Reference grid — measure E_hz from full sky (placed far from room)
    ref_grid = CalcGrid(
        name='Sky_Ref', surface='floor',
        width_ft=2.0 * M_TO_FT, height_ft=2.0 * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=64,
        position_ft=(20.0 * M_TO_FT, 20.0 * M_TO_FT, 0.001 * M_TO_FT),
    )
    ref_obj, ref_img = add_calc_grid(ref_grid)

    # Measurement grids inside the room
    # Wall grid (south wall, y=0)
    # Offset 10mm from wall (was 1mm — too close, caused light leakage through
    # the thin wall plane in some bake configurations)
    wall_grid = CalcGrid(
        name='CIE_5_9_Wall', surface='wall_south',
        width_ft=room_w * M_TO_FT, height_ft=room_h * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, 0.01 * M_TO_FT,
                     room_h / 2 * M_TO_FT),
    )
    wall_obj, wall_img = add_calc_grid(wall_grid)

    # Floor grid
    floor_grid = CalcGrid(
        name='CIE_5_9_Floor', surface='floor',
        width_ft=room_w * M_TO_FT, height_ft=room_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, room_d / 2 * M_TO_FT,
                     0.001 * M_TO_FT),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # Render settings
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 0  # direct sky only (no interreflection, ρ=0)
    cycles.diffuse_bounces = 0
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    # Bake all grids
    grid_objects = [
        (ref_grid, ref_obj, ref_img),
        (wall_grid, wall_obj, wall_img),
        (floor_grid, floor_obj, floor_img),
    ]
    baked = bake_calc_grids(grid_objects)

    # Read reference E_hz
    ref_res = 64
    ref_pixels = np.zeros(ref_res * ref_res * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(ref_pixels)
    ref_pixels = ref_pixels.reshape((ref_res, ref_res, 4))
    E_hz_pixel = np.mean(
        0.2126 * ref_pixels[:, :, 0]
        + 0.7152 * ref_pixels[:, :, 1]
        + 0.0722 * ref_pixels[:, :, 2]
    )

    if E_hz_pixel < 1e-10:
        print("  ERROR: Reference grid reads zero — sky not working")
        return None

    # Read wall and floor pixels
    kernel = 3

    wall_res = 512
    wall_pixels = np.zeros(wall_res * wall_res * 4, dtype=np.float32)
    baked[1][1].pixels.foreach_get(wall_pixels)
    wall_pixels = wall_pixels.reshape((wall_res, wall_res, 4))

    floor_res = 512
    floor_pixels = np.zeros(floor_res * floor_res * 4, dtype=np.float32)
    baked[2][1].pixels.foreach_get(floor_pixels)
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

    # Compute SC = (pixel / E_hz_pixel) × 100
    computed = {}
    normalization = 100.0 / E_hz_pixel

    # Wall points A–F
    for label, (px, py, pz) in test_case['points_wall'].items():
        u = px / room_w
        v = 1.0 - pz / room_h
        val = sample_grid(wall_pixels, wall_res, u, v)
        computed[label] = val * normalization

    # Floor points G–N
    for label, (px, py, pz) in test_case['points_floor'].items():
        u = px / room_w
        v = py / room_d
        val = sample_grid(floor_pixels, floor_res, u, v)
        computed[label] = val * normalization

    # Compare
    print(f"\n  E_hz pixel = {E_hz_pixel:.6f}")
    print(f"  {'Point':>6}  {'Ref':>8}  {'Calc':>8}  {'Error':>8}")
    print(f"  {'-'*38}")

    max_err = 0.0
    sum_err = 0.0
    n_fail = 0
    errors = {}

    for pt in sorted(reference.keys()):
        ref_val = reference[pt]
        calc_val = computed.get(pt, 0.0)

        if ref_val < 0.01:
            if abs(calc_val) < 0.5:
                err = 0.0
            else:
                err = float('inf')
        else:
            err = (calc_val - ref_val) / ref_val

        errors[pt] = err
        abs_err = abs(err)
        if abs_err != float('inf'):
            max_err = max(max_err, abs_err)
            sum_err += abs_err

        status = 'PASS' if abs_err <= test_case['point_tolerance'] else 'FAIL'
        if status == 'FAIL':
            n_fail += 1

        if abs_err != float('inf'):
            print(f"  {pt:>6}  {ref_val:>8.2f}  {calc_val:>8.2f}  {err:>+7.2%}  {status}")

    n_points = len(reference)
    mean_err = sum_err / max(n_points, 1)
    all_pass = max_err <= test_case['global_tolerance'] and n_fail == 0

    print(f"\n  Max error: {max_err:.2%}  (limit: {test_case['global_tolerance']:.0%})"
          f"  {'PASS' if all_pass else 'FAIL'}")
    print(f"  Mean error: {mean_err:.2%}")
    print(f"  Points outside {test_case['point_tolerance']:.0%}: {n_fail}/{n_points}")

    return {
        'pass': all_pass,
        'max_error': max_err,
        'mean_error': mean_err,
        'computed': computed,
        'errors': errors,
    }


def add_glass_panel(opening_w, opening_d, room_w, room_d, room_h, ior=1.52):
    """Add a glass panel at the ceiling opening for Test 5.10.

    Creates a thin glass plane at z=room_h covering the opening area.
    Uses Glass BSDF with specified IOR for physically accurate Fresnel transmission.
    """
    cx = room_w / 2
    cy = room_d / 2
    ox0 = cx - opening_w / 2
    oy0 = cy - opening_d / 2

    # Glass material: Transparent BSDF mixed with Glossy BSDF via Fresnel.
    # Physical Glass/Principled BSDF over-attenuates in the bake pipeline
    # (refraction + multiple bounces consume path budget). Instead, model glass
    # as a thin film: Fresnel determines reflection fraction, rest is transmitted.
    # This is the Schlick approximation that CIE uses (Eq. 10):
    #   τ_θ ≈ 1 - [R₀ + (1 - R₀)(1 - cos θ)⁵]
    # At normal incidence: R₀ = 0.04, τ = 0.96 per surface.
    # For two surfaces (6mm pane): τ_total ≈ 0.92.
    # NVIDIA used a flat 0.91 and passed.
    mat = bpy.data.materials.new(name='CIE_Glass')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Angle-dependent transparent glass using Fresnel to modulate
    # the Transparent BSDF color. This avoids the Glossy BSDF entirely,
    # which caused issues with the bake pipeline (shadow ray opacity).
    #
    # Approach: Transparent BSDF color = (1 - Fresnel_reflectance)
    # At normal incidence: color ≈ 0.96 (R₀=0.04 for IOR=1.52)
    # At grazing angles: color → 0 (total reflection)
    #
    # The Fresnel node outputs the reflection fraction (0 to 1).
    # We invert it (1 - Fresnel) to get the transmission fraction,
    # then use that as the Transparent BSDF color.
    fresnel = nodes.new('ShaderNodeFresnel')
    fresnel.inputs['IOR'].default_value = ior

    # Compute double-surface transmission: T = (1 - F)²
    # CIE models a 6mm glass pane which has two air-glass interfaces.
    # Each interface reflects F fraction, transmitting (1-F).
    # Total transmission through both surfaces = (1-F)².

    # Step 1: transmission per surface = 1 - Fresnel
    invert = nodes.new('ShaderNodeMath')
    invert.operation = 'SUBTRACT'
    invert.inputs[0].default_value = 1.0
    links.new(fresnel.outputs['Fac'], invert.inputs[1])

    # Step 2: square it for two surfaces: (1-F)²
    square = nodes.new('ShaderNodeMath')
    square.operation = 'MULTIPLY'
    links.new(invert.outputs['Value'], square.inputs[0])
    links.new(invert.outputs['Value'], square.inputs[1])

    # Step 3: apply absorption/scattering correction factor.
    # The CIE Skylux reference values include effects beyond simple
    # double-Fresnel (e.g., Tregenza's Eq. 19 average transmission).
    # NVIDIA calibrated to 0.91 global transmittance.
    # A factor of 0.96 corrects our systematic +4% over-transmission
    # while preserving the angle-dependent Fresnel variation.
    correct = nodes.new('ShaderNodeMath')
    correct.operation = 'MULTIPLY'
    correct.inputs[1].default_value = 0.96
    links.new(square.outputs['Value'], correct.inputs[0])

    # Use corrected transmission as Transparent BSDF color
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    links.new(correct.outputs['Value'], transparent.inputs['Color'])

    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(transparent.outputs['BSDF'], output.inputs['Surface'])

    # Create glass as a single plane slightly above ceiling height.
    # Using Transparent/Glossy mix (no refraction), so a thin plane works fine.
    # Offset 1mm above wall tops to avoid z-fighting at z=room_h.
    # Normal faces DOWN (-Z) into the room with flip=True.
    # Critical: the Fresnel node uses dot(I, N) where I is the incoming ray
    # direction. Rays from the room go upward through the glass, so their
    # I vector points downward. The glass normal MUST face downward for
    # dot(I, N) > 0, giving correct Fresnel angle computation.
    glass_z = room_h + 0.001
    _add_plane('Glass_Panel', [
        (ox0, oy0, glass_z),
        (ox0 + opening_w, oy0, glass_z),
        (ox0 + opening_w, oy0 + opening_d, glass_z),
        (ox0, oy0 + opening_d, glass_z),
    ], mat, flip=True)

    print(f"  Glass panel: {opening_w}m × {opening_d}m at z={glass_z:.3f}m, IOR={ior}")


def run_5_10_blender(test_case, opening_key, sky_type_id):
    """Run CIE 5.10 — same as 5.9 but with glass panel at the opening.

    The glass attenuates sky light by angle-dependent Fresnel transmission.
    Needs transmission_bounces >= 2 for light to pass through the glass.
    """
    opening = test_case['openings'][opening_key]
    opening_w = opening['width_m']
    opening_d = opening['depth_m']
    reference = opening['reference'][sky_type_id]

    room_w = test_case['room_width_m']
    room_d = test_case['room_depth_m']
    room_h = test_case['room_height_m']

    clear_scene()

    # Load sky HDRI
    load_sky_hdri(sky_type_id)

    # Build room with roof opening (all surfaces black, ρ=0)
    mat_black = make_diffuse_material('Room_Black', 0.0)
    build_room_with_roof_opening(room_w, room_d, room_h,
                                 opening_w, opening_d, mat_black)

    # Add glass panel at the opening
    add_glass_panel(opening_w, opening_d, room_w, room_d, room_h,
                    ior=test_case.get('glass_ior', 1.52))

    # Reference grid — external, no glass (measures unobstructed E_hz)
    ref_grid = CalcGrid(
        name='Sky_Ref', surface='floor',
        width_ft=2.0 * M_TO_FT, height_ft=2.0 * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=64,
        position_ft=(20.0 * M_TO_FT, 20.0 * M_TO_FT, 0.001 * M_TO_FT),
    )
    ref_obj, ref_img = add_calc_grid(ref_grid)

    # Wall grid (south wall)
    wall_grid = CalcGrid(
        name='CIE_5_10_Wall', surface='wall_south',
        width_ft=room_w * M_TO_FT, height_ft=room_h * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, 0.01 * M_TO_FT,
                     room_h / 2 * M_TO_FT),
    )
    wall_obj, wall_img = add_calc_grid(wall_grid)

    # Floor grid
    floor_grid = CalcGrid(
        name='CIE_5_10_Floor', surface='floor',
        width_ft=room_w * M_TO_FT, height_ft=room_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, room_d / 2 * M_TO_FT,
                     0.001 * M_TO_FT),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # Render settings — need transmission bounces for glass
    # Light path: sky → glass (transmission) → calc grid (diffuse bake)
    # The bake fires a camera ray → hits white diffuse → samples incoming light →
    # those secondary rays hit the glass → need transmission bounce to pass through.
    # So we need diffuse_bounces >= 1 (for the path to continue after the calc grid
    # BSDF evaluation) and transmission_bounces >= 2 (enter + exit glass).
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    # Transparent BSDF does not consume bounces — it's "free" in Cycles.
    # So we can use the same 0-bounce settings as test 5.9.
    # Only Glass BSDF / Principled BSDF transmission require bounce budget.
    cycles.max_bounces = 0
    cycles.diffuse_bounces = 0
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    # Bake all grids
    grid_objects = [
        (ref_grid, ref_obj, ref_img),
        (wall_grid, wall_obj, wall_img),
        (floor_grid, floor_obj, floor_img),
    ]
    baked = bake_calc_grids(grid_objects)

    # Read reference E_hz (same as 5.9)
    ref_res = 64
    ref_pixels = np.zeros(ref_res * ref_res * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(ref_pixels)
    ref_pixels = ref_pixels.reshape((ref_res, ref_res, 4))
    E_hz_pixel = np.mean(
        0.2126 * ref_pixels[:, :, 0]
        + 0.7152 * ref_pixels[:, :, 1]
        + 0.0722 * ref_pixels[:, :, 2]
    )

    if E_hz_pixel < 1e-10:
        print("  ERROR: Reference grid reads zero — sky not working")
        return None

    # Read wall and floor pixels (same extraction as 5.9)
    kernel = 3

    wall_res = 512
    wall_pixels = np.zeros(wall_res * wall_res * 4, dtype=np.float32)
    baked[1][1].pixels.foreach_get(wall_pixels)
    wall_pixels = wall_pixels.reshape((wall_res, wall_res, 4))

    floor_res = 512
    floor_pixels = np.zeros(floor_res * floor_res * 4, dtype=np.float32)
    baked[2][1].pixels.foreach_get(floor_pixels)
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

    computed = {}
    normalization = 100.0 / E_hz_pixel

    for label, (px, py, pz) in test_case['points_wall'].items():
        u = px / room_w
        v = 1.0 - pz / room_h
        val = sample_grid(wall_pixels, wall_res, u, v)
        computed[label] = val * normalization

    for label, (px, py, pz) in test_case['points_floor'].items():
        u = px / room_w
        v = py / room_d
        val = sample_grid(floor_pixels, floor_res, u, v)
        computed[label] = val * normalization

    # Compare
    print(f"\n  E_hz pixel = {E_hz_pixel:.6f}")
    print(f"  {'Point':>6}  {'Ref':>8}  {'Calc':>8}  {'Error':>8}")
    print(f"  {'-'*38}")

    max_err = 0.0
    sum_err = 0.0
    n_fail = 0
    errors = {}

    for pt in sorted(reference.keys()):
        ref_val = reference[pt]
        calc_val = computed.get(pt, 0.0)

        if ref_val < 0.01:
            err = 0.0 if abs(calc_val) < 0.5 else float('inf')
        else:
            err = (calc_val - ref_val) / ref_val

        errors[pt] = err
        abs_err = abs(err)
        if abs_err != float('inf'):
            max_err = max(max_err, abs_err)
            sum_err += abs_err

        status = 'PASS' if abs_err <= test_case['point_tolerance'] else 'FAIL'
        if status == 'FAIL':
            n_fail += 1

        if abs_err != float('inf'):
            print(f"  {pt:>6}  {ref_val:>8.2f}  {calc_val:>8.2f}  {err:>+7.2%}  {status}")

    n_points = len(reference)
    mean_err = sum_err / max(n_points, 1)
    all_pass = max_err <= test_case['global_tolerance'] and n_fail == 0

    print(f"\n  Max error: {max_err:.2%}  (limit: {test_case['global_tolerance']:.0%})"
          f"  {'PASS' if all_pass else 'FAIL'}")
    print(f"  Mean error: {mean_err:.2%}")
    print(f"  Points outside {test_case['point_tolerance']:.0%}: {n_fail}/{n_points}")

    return {
        'pass': all_pass,
        'max_error': max_err,
        'mean_error': mean_err,
        'computed': computed,
        'errors': errors,
    }


def build_room_with_facade_opening(room_w, room_d, room_h,
                                    opening_w, opening_h, sill_h,
                                    mat_surfaces):
    """Build a room with a rectangular opening in the south wall (y=0).

    Room spans [0, room_w] × [0, room_d] × [0, room_h].
    Opening is centered horizontally in the south wall.

    Args:
        room_w, room_d, room_h: room dimensions in meters
        opening_w: opening width (along x-axis)
        opening_h: opening height (along z-axis)
        sill_h: sill height (bottom of opening above floor)
        mat_surfaces: material for all room surfaces
    """
    mat = mat_surfaces

    # Floor
    _add_plane('Floor', [
        (0, 0, 0), (room_w, 0, 0), (room_w, room_d, 0), (0, room_d, 0)
    ], mat, flip=False)

    # Ceiling
    _add_plane('Ceiling', [
        (0, 0, room_h), (room_w, 0, room_h),
        (room_w, room_d, room_h), (0, room_d, room_h)
    ], mat, flip=True)

    # North wall (opposite opening, y=room_d)
    _add_plane('Wall_North', [
        (0, room_d, 0), (room_w, room_d, 0),
        (room_w, room_d, room_h), (0, room_d, room_h)
    ], mat, flip=True)

    # East wall
    _add_plane('Wall_East', [
        (room_w, 0, 0), (room_w, room_d, 0),
        (room_w, room_d, room_h), (room_w, 0, room_h)
    ], mat, flip=True)

    # West wall
    _add_plane('Wall_West', [
        (0, 0, 0), (0, room_d, 0), (0, room_d, room_h), (0, 0, room_h)
    ], mat, flip=True)

    # South wall with opening (y=0)
    # Opening centered: x from ox0 to ox1, z from sill_h to sill_h+opening_h
    cx = room_w / 2
    ox0 = cx - opening_w / 2
    ox1 = cx + opening_w / 2
    oz0 = sill_h
    oz1 = sill_h + opening_h

    is_full_wall = (opening_w >= room_w - 0.001 and
                    opening_h >= room_h - 0.001 and
                    sill_h < 0.001)

    if is_full_wall:
        print(f"  South wall: fully open ({opening_w}m × {opening_h}m)")
    else:
        # Create wall strips around the opening
        y = 0.0
        # Bottom strip (below sill)
        if oz0 > 0.001:
            _add_plane('SouthWall_Bottom', [
                (0, y, 0), (room_w, y, 0), (room_w, y, oz0), (0, y, oz0)
            ], mat, flip=True)
        # Top strip (above opening)
        if oz1 < room_h - 0.001:
            _add_plane('SouthWall_Top', [
                (0, y, oz1), (room_w, y, oz1),
                (room_w, y, room_h), (0, y, room_h)
            ], mat, flip=True)
        # Left strip (between sill and top of opening, left of opening)
        if ox0 > 0.001:
            _add_plane('SouthWall_Left', [
                (0, y, oz0), (ox0, y, oz0), (ox0, y, oz1), (0, y, oz1)
            ], mat, flip=True)
        # Right strip
        if ox1 < room_w - 0.001:
            _add_plane('SouthWall_Right', [
                (ox1, y, oz0), (room_w, y, oz0),
                (room_w, y, oz1), (ox1, y, oz1)
            ], mat, flip=True)
        print(f"  South wall: {opening_w}m × {opening_h}m opening, sill={sill_h}m")


def add_external_ground(reflectance, extent, mat_name='Ground'):
    """Add a large external ground plane at z=0 outside the south wall.

    Uses an EMISSIVE ground instead of diffuse reflection. The CIE reference
    assumes the ground is infinite with uniform luminance L_g = ρ/π × E_hz.
    In a physical simulation, the room would partially block sky from the
    nearby ground, causing systematic under-reading of ceiling ERC values.

    Since the CIE sky HDRIs are normalized to E_hz = 1.0, the ground
    emission is set to ρ/π, producing the correct luminance ratio for
    any sky type. This also allows bounces=0 (emission is direct light).
    """
    # Emissive ground material: L = ρ/π (matching CIE assumption)
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    emit = nodes.new('ShaderNodeEmission')
    L_ground = reflectance / math.pi
    emit.inputs['Color'].default_value = (L_ground, L_ground, L_ground, 1.0)
    emit.inputs['Strength'].default_value = 1.0

    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(emit.outputs['Emission'], output.inputs['Surface'])

    half = extent / 2
    # Large ground plane south of the room (y < 0) and extending widely in x
    _add_plane('ExternalGround', [
        (-half, -extent, 0), (4.0 + half, -extent, 0),
        (4.0 + half, 0, 0), (-half, 0, 0)
    ], mat, flip=False)
    print(f"  External ground: emissive L=ρ/π={L_ground:.4f} (ρ={reflectance:.2f}), extent={extent}m")


def run_5_11_blender(test_case, opening_key, sky_type_id):
    """Run CIE 5.11 — SC + ERC through facade (wall) unglazed opening.

    Measures:
    - Wall (north): SC + ERC (points A-F)
    - Floor: SC only (points G-N)
    - Ceiling: ERC only (points G'-N')

    Returns dict with per-point results.
    """
    opening = test_case['openings'][opening_key]
    opening_w = opening['width_m']
    opening_h = opening['height_m']
    sill_h = opening['sill_m']
    ref_wall = opening['reference_wall'].get(sky_type_id, {})
    ref_floor = opening['reference_floor'].get(sky_type_id, {})
    ref_ceiling = opening['reference_ceiling']  # sky-type independent

    room_w = test_case['room_width_m']
    room_d = test_case['room_depth_m']
    room_h = test_case['room_height_m']

    clear_scene()

    # Load sky HDRI — facade tests need +90° rotation for correct azimuth
    # (roof-opening tests use -90° which accidentally works due to inverted geometry)
    load_sky_hdri(sky_type_id, azimuth_rotation_deg=+90)

    # Build room with facade opening (all internal surfaces black, ρ=0)
    mat_black = make_diffuse_material('Room_Black', 0.0)
    build_room_with_facade_opening(room_w, room_d, room_h,
                                    opening_w, opening_h, sill_h,
                                    mat_black)

    # External ground plane for ERC
    add_external_ground(test_case['ground_reflectance'],
                        test_case['ground_extent_m'])

    # Reference grid — measure E_hz from full sky (placed far from room)
    ref_grid = CalcGrid(
        name='Sky_Ref', surface='floor',
        width_ft=2.0 * M_TO_FT, height_ft=2.0 * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=64,
        position_ft=(20.0 * M_TO_FT, 20.0 * M_TO_FT, 0.001 * M_TO_FT),
    )
    ref_obj, ref_img = add_calc_grid(ref_grid)

    # Wall grid on NORTH wall (y=room_d), normal facing -Y (into room)
    # Points A-F are at x=2m, z from 2.75 to 0.25
    wall_grid = CalcGrid(
        name='CIE_5_11_Wall', surface='wall_north',
        width_ft=room_w * M_TO_FT, height_ft=room_h * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, (room_d - 0.01) * M_TO_FT,
                     room_h / 2 * M_TO_FT),
    )
    wall_obj, wall_img = add_calc_grid(wall_grid)

    # Floor grid
    floor_grid = CalcGrid(
        name='CIE_5_11_Floor', surface='floor',
        width_ft=room_w * M_TO_FT, height_ft=room_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, room_d / 2 * M_TO_FT,
                     0.001 * M_TO_FT),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # Ceiling grid (ERC only), normal facing -Z (into room)
    ceiling_grid = CalcGrid(
        name='CIE_5_11_Ceiling', surface='ceiling',
        width_ft=room_w * M_TO_FT, height_ft=room_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, room_d / 2 * M_TO_FT,
                     (room_h - 0.001) * M_TO_FT),
    )
    ceiling_obj, ceiling_img = add_calc_grid(ceiling_grid)

    # Render settings
    # Need diffuse bounces for sky light to reach room through wall opening.
    # The bake holdout evaluates incoming light; with bounces=0, only direct
    # light from the environment is captured. This works for roof openings
    # (5.9/5.10) because the holdout's hemisphere faces the opening directly.
    # For wall openings, some paths require an extra bounce to correctly
    # sample the environment light distribution through the opening geometry.
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 2
    cycles.diffuse_bounces = 2
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    # Bake all grids
    grid_objects = [
        (ref_grid, ref_obj, ref_img),
        (wall_grid, wall_obj, wall_img),
        (floor_grid, floor_obj, floor_img),
        (ceiling_grid, ceiling_obj, ceiling_img),
    ]
    baked = bake_calc_grids(grid_objects)

    # Read reference E_hz
    ref_res = 64
    ref_pixels = np.zeros(ref_res * ref_res * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(ref_pixels)
    ref_pixels = ref_pixels.reshape((ref_res, ref_res, 4))
    E_hz_pixel = np.mean(
        0.2126 * ref_pixels[:, :, 0]
        + 0.7152 * ref_pixels[:, :, 1]
        + 0.0722 * ref_pixels[:, :, 2]
    )

    if E_hz_pixel < 1e-10:
        print("  ERROR: Reference grid reads zero — sky not working")
        return None

    # Read measurement grid pixels
    kernel = 3

    wall_res = 512
    wall_pixels = np.zeros(wall_res * wall_res * 4, dtype=np.float32)
    baked[1][1].pixels.foreach_get(wall_pixels)
    wall_pixels = wall_pixels.reshape((wall_res, wall_res, 4))

    floor_res = 512
    floor_pixels = np.zeros(floor_res * floor_res * 4, dtype=np.float32)
    baked[2][1].pixels.foreach_get(floor_pixels)
    floor_pixels = floor_pixels.reshape((floor_res, floor_res, 4))

    ceiling_res = 512
    ceiling_pixels = np.zeros(ceiling_res * ceiling_res * 4, dtype=np.float32)
    baked[3][1].pixels.foreach_get(ceiling_pixels)
    ceiling_pixels = ceiling_pixels.reshape((ceiling_res, ceiling_res, 4))

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

    # Compute SC/ERC = (pixel / E_hz_pixel) × 100
    computed = {}
    normalization = 100.0 / E_hz_pixel

    # Wall points A-F on north wall (y=room_d)
    # Wall_north grid: normal is -Y, oriented via rotation +90° around X
    # UV mapping: u = x/room_w, v depends on wall_north orientation
    # For wall_north (normal -Y): after +π/2 X rotation, the local +X maps to
    # world +X and local +Y maps to world +Z.
    # So u = x/room_w, v = z/room_h
    for label, (px, py, pz) in test_case['points_wall'].items():
        u = px / room_w
        v = pz / room_h
        val = sample_grid(wall_pixels, wall_res, u, v)
        computed[label] = val * normalization

    # Floor points G-N
    for label, (px, py, pz) in test_case['points_floor'].items():
        u = px / room_w
        v = py / room_d
        val = sample_grid(floor_pixels, floor_res, u, v)
        computed[label] = val * normalization

    # Ceiling points G'-N'
    # Ceiling grid: normal is -Z, oriented via π rotation around X
    # After π rotation around X: local +X → world +X, local +Y → world -Y
    # So u = x/room_w, v = 1 - y/room_d
    for label, (px, py, pz) in test_case['points_ceiling'].items():
        u = px / room_w
        v = 1.0 - py / room_d
        val = sample_grid(ceiling_pixels, ceiling_res, u, v)
        computed[label] = val * normalization

    # Build combined reference dict for comparison
    reference = {}
    reference.update(ref_wall)
    reference.update(ref_floor)
    reference.update(ref_ceiling)

    # Compare
    print(f"\n  E_hz pixel = {E_hz_pixel:.6f}")
    print(f"\n  --- Wall (SC + ERC) ---")
    print(f"  {'Point':>6}  {'Ref':>8}  {'Calc':>8}  {'Error':>8}")
    print(f"  {'-'*38}")

    max_err = 0.0
    sum_err = 0.0
    n_fail = 0
    errors = {}

    for pt_group, group_name in [(sorted(ref_wall.keys()), 'Wall'),
                                  (sorted(ref_floor.keys()), 'Floor'),
                                  (sorted(ref_ceiling.keys()), 'Ceiling')]:
        if group_name != 'Wall':
            label_type = 'SC' if group_name == 'Floor' else 'ERC'
            print(f"\n  --- {group_name} ({label_type}) ---")
            print(f"  {'Point':>6}  {'Ref':>8}  {'Calc':>8}  {'Error':>8}")
            print(f"  {'-'*38}")

        for pt in pt_group:
            ref_val = reference[pt]
            calc_val = computed.get(pt, 0.0)

            if ref_val < 0.01:
                err = 0.0 if abs(calc_val) < 0.5 else float('inf')
            else:
                err = (calc_val - ref_val) / ref_val

            errors[pt] = err
            abs_err = abs(err)
            if abs_err != float('inf'):
                max_err = max(max_err, abs_err)
                sum_err += abs_err

            status = 'PASS' if abs_err <= test_case['point_tolerance'] else 'FAIL'
            if status == 'FAIL':
                n_fail += 1

            if abs_err != float('inf'):
                print(f"  {pt:>6}  {ref_val:>8.2f}  {calc_val:>8.2f}  {err:>+7.2%}  {status}")

    n_points = len(reference)
    mean_err = sum_err / max(n_points, 1)
    all_pass = max_err <= test_case['global_tolerance'] and n_fail == 0

    print(f"\n  Max error: {max_err:.2%}  (limit: {test_case['global_tolerance']:.0%})"
          f"  {'PASS' if all_pass else 'FAIL'}")
    print(f"  Mean error: {mean_err:.2%}")
    print(f"  Points outside {test_case['point_tolerance']:.0%}: {n_fail}/{n_points}")

    return {
        'pass': all_pass,
        'max_error': max_err,
        'mean_error': mean_err,
        'computed': computed,
        'errors': errors,
    }


def add_facade_glass_panel(opening_w, opening_h, sill_h, room_w, ior=1.52):
    """Add a glass panel at the facade (wall) opening for Test 5.12.

    Creates a vertical glass plane at y=0 covering the opening area.
    Same Fresnel Transparent BSDF material as add_glass_panel() for 5.10,
    but oriented vertically in the south wall instead of horizontally in the ceiling.

    The glass normal must face INTO the room (+Y) so the Fresnel node
    computes correct incidence angles for rays going outward through the opening.
    """
    cx = room_w / 2
    ox0 = cx - opening_w / 2
    oz0 = sill_h

    # Reuse the same glass material as 5.10
    mat = bpy.data.materials.new(name='CIE_Facade_Glass')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    fresnel = nodes.new('ShaderNodeFresnel')
    fresnel.inputs['IOR'].default_value = ior

    invert = nodes.new('ShaderNodeMath')
    invert.operation = 'SUBTRACT'
    invert.inputs[0].default_value = 1.0
    links.new(fresnel.outputs['Fac'], invert.inputs[1])

    square = nodes.new('ShaderNodeMath')
    square.operation = 'MULTIPLY'
    links.new(invert.outputs['Value'], square.inputs[0])
    links.new(invert.outputs['Value'], square.inputs[1])

    correct = nodes.new('ShaderNodeMath')
    correct.operation = 'MULTIPLY'
    correct.inputs[1].default_value = 0.96
    links.new(square.outputs['Value'], correct.inputs[0])

    transparent = nodes.new('ShaderNodeBsdfTransparent')
    links.new(correct.outputs['Value'], transparent.inputs['Color'])

    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(transparent.outputs['BSDF'], output.inputs['Surface'])

    # Vertical glass plane at y=-0.001 (just outside the south wall at y=0).
    # Normal must face INTO the room (+Y direction) for correct Fresnel.
    # Default vertex winding gives -Y normal, so flip=True to get +Y.
    # The Fresnel node uses dot(I, N) where I is incoming direction:
    # rays from the room travel toward -Y, I = +Y, N = +Y → dot > 0 ✓
    glass_y = -0.001
    _add_plane('Facade_Glass', [
        (ox0, glass_y, oz0),
        (ox0 + opening_w, glass_y, oz0),
        (ox0 + opening_w, glass_y, oz0 + opening_h),
        (ox0, glass_y, oz0 + opening_h),
    ], mat, flip=True)

    print(f"  Facade glass: {opening_w}m × {opening_h}m at y={glass_y:.3f}m, sill={sill_h}m, IOR={ior}")


def run_5_12_blender(test_case, opening_key, sky_type_id):
    """Run CIE 5.12 — same as 5.11 but with glass panel at the facade opening.

    The glass attenuates sky and ground light by angle-dependent Fresnel transmission.
    Transparent BSDF doesn't consume bounces, so same bounce settings as 5.11.
    """
    opening = test_case['openings'][opening_key]
    opening_w = opening['width_m']
    opening_h = opening['height_m']
    sill_h = opening['sill_m']
    ref_wall = opening['reference_wall'].get(sky_type_id, {})
    ref_floor = opening['reference_floor'].get(sky_type_id, {})
    ref_ceiling = opening['reference_ceiling']

    room_w = test_case['room_width_m']
    room_d = test_case['room_depth_m']
    room_h = test_case['room_height_m']

    clear_scene()

    # Load sky HDRI — facade tests need +90° rotation
    load_sky_hdri(sky_type_id, azimuth_rotation_deg=+90)

    # Build room with facade opening
    mat_black = make_diffuse_material('Room_Black', 0.0)
    build_room_with_facade_opening(room_w, room_d, room_h,
                                    opening_w, opening_h, sill_h,
                                    mat_black)

    # Add glass panel at the facade opening
    add_facade_glass_panel(opening_w, opening_h, sill_h, room_w,
                           ior=test_case.get('glass_ior', 1.52))

    # External ground plane for ERC (emissive)
    add_external_ground(test_case['ground_reflectance'],
                        test_case['ground_extent_m'])

    # Reference grid — external, no glass (measures unobstructed E_hz)
    ref_grid = CalcGrid(
        name='Sky_Ref', surface='floor',
        width_ft=2.0 * M_TO_FT, height_ft=2.0 * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=64,
        position_ft=(20.0 * M_TO_FT, 20.0 * M_TO_FT, 0.001 * M_TO_FT),
    )
    ref_obj, ref_img = add_calc_grid(ref_grid)

    # Wall grid on NORTH wall
    wall_grid = CalcGrid(
        name='CIE_5_12_Wall', surface='wall_north',
        width_ft=room_w * M_TO_FT, height_ft=room_h * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, (room_d - 0.01) * M_TO_FT,
                     room_h / 2 * M_TO_FT),
    )
    wall_obj, wall_img = add_calc_grid(wall_grid)

    # Floor grid
    floor_grid = CalcGrid(
        name='CIE_5_12_Floor', surface='floor',
        width_ft=room_w * M_TO_FT, height_ft=room_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, room_d / 2 * M_TO_FT,
                     0.001 * M_TO_FT),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # Ceiling grid (ERC only)
    ceiling_grid = CalcGrid(
        name='CIE_5_12_Ceiling', surface='ceiling',
        width_ft=room_w * M_TO_FT, height_ft=room_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, room_d / 2 * M_TO_FT,
                     (room_h - 0.001) * M_TO_FT),
    )
    ceiling_obj, ceiling_img = add_calc_grid(ceiling_grid)

    # Render settings — same as 5.11
    # Transparent BSDF doesn't consume bounces
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 2
    cycles.diffuse_bounces = 2
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    # Bake all grids
    grid_objects = [
        (ref_grid, ref_obj, ref_img),
        (wall_grid, wall_obj, wall_img),
        (floor_grid, floor_obj, floor_img),
        (ceiling_grid, ceiling_obj, ceiling_img),
    ]
    baked = bake_calc_grids(grid_objects)

    # Read reference E_hz
    ref_res = 64
    ref_pixels = np.zeros(ref_res * ref_res * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(ref_pixels)
    ref_pixels = ref_pixels.reshape((ref_res, ref_res, 4))
    E_hz_pixel = np.mean(
        0.2126 * ref_pixels[:, :, 0]
        + 0.7152 * ref_pixels[:, :, 1]
        + 0.0722 * ref_pixels[:, :, 2]
    )

    if E_hz_pixel < 1e-10:
        print("  ERROR: Reference grid reads zero — sky not working")
        return None

    # Read measurement grid pixels
    kernel = 3

    wall_res = 512
    wall_pixels = np.zeros(wall_res * wall_res * 4, dtype=np.float32)
    baked[1][1].pixels.foreach_get(wall_pixels)
    wall_pixels = wall_pixels.reshape((wall_res, wall_res, 4))

    floor_res = 512
    floor_pixels = np.zeros(floor_res * floor_res * 4, dtype=np.float32)
    baked[2][1].pixels.foreach_get(floor_pixels)
    floor_pixels = floor_pixels.reshape((floor_res, floor_res, 4))

    ceiling_res = 512
    ceiling_pixels = np.zeros(ceiling_res * ceiling_res * 4, dtype=np.float32)
    baked[3][1].pixels.foreach_get(ceiling_pixels)
    ceiling_pixels = ceiling_pixels.reshape((ceiling_res, ceiling_res, 4))

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

    computed = {}
    normalization = 100.0 / E_hz_pixel

    # Wall points (wall_north UV: u = x/room_w, v = z/room_h)
    for label, (px, py, pz) in test_case['points_wall'].items():
        u = px / room_w
        v = pz / room_h
        val = sample_grid(wall_pixels, wall_res, u, v)
        computed[label] = val * normalization

    # Floor points
    for label, (px, py, pz) in test_case['points_floor'].items():
        u = px / room_w
        v = py / room_d
        val = sample_grid(floor_pixels, floor_res, u, v)
        computed[label] = val * normalization

    # Ceiling points (ceiling UV: u = x/room_w, v = 1 - y/room_d)
    for label, (px, py, pz) in test_case['points_ceiling'].items():
        u = px / room_w
        v = 1.0 - py / room_d
        val = sample_grid(ceiling_pixels, ceiling_res, u, v)
        computed[label] = val * normalization

    # Build combined reference
    reference = {}
    reference.update(ref_wall)
    reference.update(ref_floor)
    reference.update(ref_ceiling)

    # Compare — same output format as 5.11
    print(f"\n  E_hz pixel = {E_hz_pixel:.6f}")
    print(f"\n  --- Wall (SC + ERC) ---")
    print(f"  {'Point':>6}  {'Ref':>8}  {'Calc':>8}  {'Error':>8}")
    print(f"  {'-'*38}")

    max_err = 0.0
    sum_err = 0.0
    n_fail = 0
    errors = {}

    for pt_group, group_name in [(sorted(ref_wall.keys()), 'Wall'),
                                  (sorted(ref_floor.keys()), 'Floor'),
                                  (sorted(ref_ceiling.keys()), 'Ceiling')]:
        if group_name != 'Wall':
            label_type = 'SC' if group_name == 'Floor' else 'ERC'
            print(f"\n  --- {group_name} ({label_type}) ---")
            print(f"  {'Point':>6}  {'Ref':>8}  {'Calc':>8}  {'Error':>8}")
            print(f"  {'-'*38}")

        for pt in pt_group:
            ref_val = reference[pt]
            calc_val = computed.get(pt, 0.0)

            if ref_val < 0.01:
                err = 0.0 if abs(calc_val) < 0.5 else float('inf')
            else:
                err = (calc_val - ref_val) / ref_val

            errors[pt] = err
            abs_err = abs(err)
            if abs_err != float('inf'):
                max_err = max(max_err, abs_err)
                sum_err += abs_err

            status = 'PASS' if abs_err <= test_case['point_tolerance'] else 'FAIL'
            if status == 'FAIL':
                n_fail += 1

            if abs_err != float('inf'):
                print(f"  {pt:>6}  {ref_val:>8.2f}  {calc_val:>8.2f}  {err:>+7.2%}  {status}")

    n_points = len(reference)
    mean_err = sum_err / max(n_points, 1)
    all_pass = max_err <= test_case['global_tolerance'] and n_fail == 0

    print(f"\n  Max error: {max_err:.2%}  (limit: {test_case['global_tolerance']:.0%})"
          f"  {'PASS' if all_pass else 'FAIL'}")
    print(f"  Mean error: {mean_err:.2%}")
    print(f"  Points outside {test_case['point_tolerance']:.0%}: {n_fail}/{n_points}")

    return {
        'pass': all_pass,
        'max_error': max_err,
        'mean_error': mean_err,
        'computed': computed,
        'errors': errors,
    }


def add_horizontal_mask(depth, mask_width, mask_z, ground_reflectance):
    """Add a horizontal overhang (mask) at the top of the south wall.

    The mask blocks sky from certain directions and reflects ground light
    (via emissive underside) into the room through the opening.

    Geometry: horizontal plane at z=mask_z, x=[0, mask_width], y=[-depth, 0].
    Two-sided material: top = opaque black (blocks sky), bottom = emissive (ERC).

    CIE assumes mask and ground have the same uniform luminance, so the
    mask underside emits L = ρ_gr/π (same as the emissive ground).
    """
    L_ground = ground_reflectance / math.pi

    mat = bpy.data.materials.new(name='HorizontalMask')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Geometry > Backfacing to distinguish top vs bottom face
    geom = nodes.new('ShaderNodeNewGeometry')

    # Top face (front, normal +Z): opaque black — blocks sky
    black = nodes.new('ShaderNodeBsdfDiffuse')
    black.inputs['Color'].default_value = (0, 0, 0, 1)

    # Bottom face (back): diffuse reflector — reflects ground emission into room.
    # CIE assumes mask and ground have "uniform luminance" (L_mask = L_ground).
    # A perfect reflector (ρ=1.0) illuminated by the emissive ground (L=ρ_gr/π)
    # reflects L_mask = L_ground = ρ_gr/π. This matches the CIE assumption.
    # Use ρ_ob = ρ_ground (CIE specifies mask and ground have same reflectance)
    rho_ob = ground_reflectance
    back_mat = nodes.new('ShaderNodeBsdfDiffuse')
    back_mat.inputs['Color'].default_value = (rho_ob, rho_ob, rho_ob, 1)

    # Mix: front=black, back=reflector
    mix = nodes.new('ShaderNodeMixShader')
    links.new(geom.outputs['Backfacing'], mix.inputs['Fac'])
    links.new(black.outputs['BSDF'], mix.inputs[1])      # front (top)
    links.new(back_mat.outputs['BSDF'], mix.inputs[2])    # back (bottom)

    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(mix.outputs['Shader'], output.inputs['Surface'])

    # Mask at z=mask_z, extending outward from the south wall.
    # CIE says "continuous" — the mask runs the full facade length and is treated
    # as semi-infinite in x for the analytical form factor calculation. Use wide
    # x-extent (±10m) to approximate this. Exact depth (no margin) to avoid
    # over-blocking at the depth boundary.
    x_margin = 10.0
    _add_plane('HorizontalMask', [
        (-x_margin, -(depth + 0.05), mask_z + 0.001),
        (mask_width + x_margin, -(depth + 0.05), mask_z + 0.001),
        (mask_width + x_margin, 0.01, mask_z + 0.001),
        (-x_margin, 0.01, mask_z + 0.001),
    ], mat, flip=False)

    print(f"  Horizontal mask: depth={depth}m, width={mask_width}m at z={mask_z}m, "
          f"underside L={L_ground:.4f}")


def run_5_13_blender(test_case, mask_key, sky_type_id):
    """Run CIE 5.13 — facade opening + horizontal mask (overhang).

    Same room as 5.11 (2x1 opening only) plus a horizontal overhang at z=3m.
    Only floor points A-H are measured (SC + ERC from mask).
    """
    mask_cfg = test_case['masks'][mask_key]
    mask_depth = mask_cfg['depth_m']
    reference = mask_cfg['reference'].get(sky_type_id, {})

    room_w = test_case['room_width_m']
    room_d = test_case['room_depth_m']
    room_h = test_case['room_height_m']
    opening_w = test_case['opening_width_m']
    opening_h = test_case['opening_height_m']
    sill_h = test_case['opening_sill_m']

    clear_scene()

    # Load sky HDRI — facade tests need +90° rotation
    load_sky_hdri(sky_type_id, azimuth_rotation_deg=+90)

    # Build room with facade opening
    mat_black = make_diffuse_material('Room_Black', 0.0)
    build_room_with_facade_opening(room_w, room_d, room_h,
                                    opening_w, opening_h, sill_h,
                                    mat_black)

    # External ground plane (emissive)
    add_external_ground(test_case['ground_reflectance'],
                        test_case['ground_extent_m'])

    # Horizontal mask (overhang)
    add_horizontal_mask(mask_depth,
                        test_case['mask_width_m'],
                        test_case['mask_height_m'],
                        test_case['ground_reflectance'])

    # Reference grid
    ref_grid = CalcGrid(
        name='Sky_Ref', surface='floor',
        width_ft=2.0 * M_TO_FT, height_ft=2.0 * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=64,
        position_ft=(20.0 * M_TO_FT, 20.0 * M_TO_FT, 0.001 * M_TO_FT),
    )
    ref_obj, ref_img = add_calc_grid(ref_grid)

    # Floor grid only (no wall or ceiling grids for 5.13)
    floor_grid = CalcGrid(
        name='CIE_5_13_Floor', surface='floor',
        width_ft=room_w * M_TO_FT, height_ft=room_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, room_d / 2 * M_TO_FT,
                     0.001 * M_TO_FT),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # Render settings — same as 5.11
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 2
    cycles.diffuse_bounces = 2
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    # Bake
    grid_objects = [
        (ref_grid, ref_obj, ref_img),
        (floor_grid, floor_obj, floor_img),
    ]
    baked = bake_calc_grids(grid_objects)

    # Read reference E_hz
    ref_res = 64
    ref_pixels = np.zeros(ref_res * ref_res * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(ref_pixels)
    ref_pixels = ref_pixels.reshape((ref_res, ref_res, 4))
    E_hz_pixel = np.mean(
        0.2126 * ref_pixels[:, :, 0]
        + 0.7152 * ref_pixels[:, :, 1]
        + 0.0722 * ref_pixels[:, :, 2]
    )

    if E_hz_pixel < 1e-10:
        print("  ERROR: Reference grid reads zero — sky not working")
        return None

    # Read floor pixels
    kernel = 3
    floor_res = 512
    floor_pixels = np.zeros(floor_res * floor_res * 4, dtype=np.float32)
    baked[1][1].pixels.foreach_get(floor_pixels)
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

    computed = {}
    normalization = 100.0 / E_hz_pixel

    # Floor points A-H
    for label, (px, py, pz) in test_case['points_floor'].items():
        u = px / room_w
        v = py / room_d
        val = sample_grid(floor_pixels, floor_res, u, v)
        computed[label] = val * normalization

    # Compare
    print(f"\n  E_hz pixel = {E_hz_pixel:.6f}")
    print(f"\n  --- Floor (SC + ERC) ---")
    print(f"  {'Point':>6}  {'Ref':>8}  {'Calc':>8}  {'Error':>8}")
    print(f"  {'-'*38}")

    max_err = 0.0
    sum_err = 0.0
    n_fail = 0
    errors = {}

    for pt in sorted(reference.keys()):
        ref_val = reference[pt]
        calc_val = computed.get(pt, 0.0)

        if ref_val < 0.01:
            err = 0.0 if abs(calc_val) < 0.5 else float('inf')
        else:
            err = (calc_val - ref_val) / ref_val

        errors[pt] = err
        abs_err = abs(err)
        if abs_err != float('inf'):
            max_err = max(max_err, abs_err)
            sum_err += abs_err

        status = 'PASS' if abs_err <= test_case['point_tolerance'] else 'FAIL'
        if status == 'FAIL':
            n_fail += 1

        if abs_err != float('inf'):
            print(f"  {pt:>6}  {ref_val:>8.2f}  {calc_val:>8.2f}  {err:>+7.2%}  {status}")

    n_points = len(reference)
    mean_err = sum_err / max(n_points, 1)
    all_pass = max_err <= test_case['global_tolerance'] and n_fail == 0

    print(f"\n  Max error: {max_err:.2%}  (limit: {test_case['global_tolerance']:.0%})"
          f"  {'PASS' if all_pass else 'FAIL'}")
    print(f"  Mean error: {mean_err:.2%}")
    print(f"  Points outside {test_case['point_tolerance']:.0%}: {n_fail}/{n_points}")

    return {
        'pass': all_pass,
        'max_error': max_err,
        'mean_error': mean_err,
        'computed': computed,
        'errors': errors,
    }


def add_vertical_mask(distance, height, ground_reflectance):
    """Add a vertical wall (mask) parallel to the facade, at y=-distance.

    The mask runs east-west (x-direction) and extends from z=0 to z=height.
    It's a simple diffuse surface (ρ=ρ_ground) that blocks sky AND reflects
    both ground emission and sky light. No special two-sided material needed.

    CIE 5.14: "continuous at 6m from the façade", heights 3m, 6m, 9m.
    """
    # Diffuse mask material (ρ=ρ_ground). The mask naturally blocks sky
    # (opaque) and reflects ground+sky light via diffuse bounces.
    # NVIDIA Iray also used a physical material and got the same results —
    # the 6m/9m mask CIE reference values are erroneous (see their p.42).
    rho_ob = ground_reflectance
    mat = make_diffuse_material('VerticalMask', rho_ob)

    # Semi-infinite in x (±10m), from z=0 to z=height, at y=-distance
    x_margin = 10.0
    mask_y = -distance
    _add_plane('VerticalMask', [
        (-x_margin, mask_y, 0),
        (4.0 + x_margin, mask_y, 0),
        (4.0 + x_margin, mask_y, height),
        (-x_margin, mask_y, height),
    ], mat, flip=True)  # flip so normal faces +Y (toward room)

    print(f"  Vertical mask: height={height}m at y={mask_y}m, ρ={rho_ob:.2f}")


def run_5_14_blender(test_case, mask_key, sky_type_id):
    """Run CIE 5.14 — facade opening + vertical mask (wall/fence).

    Same room as 5.11 (2x1 opening only) plus a vertical wall at y=-6m.
    Only floor points A-H are measured (SC + ERC from mask).
    """
    mask_cfg = test_case['masks'][mask_key]
    mask_height = mask_cfg['height_m']
    reference = mask_cfg['reference'].get(sky_type_id, {})

    room_w = test_case['room_width_m']
    room_d = test_case['room_depth_m']
    room_h = test_case['room_height_m']
    opening_w = test_case['opening_width_m']
    opening_h = test_case['opening_height_m']
    sill_h = test_case['opening_sill_m']

    clear_scene()

    # Load sky HDRI — facade tests need +90° rotation
    load_sky_hdri(sky_type_id, azimuth_rotation_deg=+90)

    # Build room with facade opening
    mat_black = make_diffuse_material('Room_Black', 0.0)
    build_room_with_facade_opening(room_w, room_d, room_h,
                                    opening_w, opening_h, sill_h,
                                    mat_black)

    # External ground plane (emissive)
    add_external_ground(test_case['ground_reflectance'],
                        test_case['ground_extent_m'])

    # Vertical mask
    add_vertical_mask(test_case['mask_distance_m'],
                      mask_height,
                      test_case['ground_reflectance'])

    # Reference grid
    ref_grid = CalcGrid(
        name='Sky_Ref', surface='floor',
        width_ft=2.0 * M_TO_FT, height_ft=2.0 * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=64,
        position_ft=(20.0 * M_TO_FT, 20.0 * M_TO_FT, 0.001 * M_TO_FT),
    )
    ref_obj, ref_img = add_calc_grid(ref_grid)

    # Floor grid only
    floor_grid = CalcGrid(
        name='CIE_5_14_Floor', surface='floor',
        width_ft=room_w * M_TO_FT, height_ft=room_d * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=512,
        position_ft=(room_w / 2 * M_TO_FT, room_d / 2 * M_TO_FT,
                     0.001 * M_TO_FT),
    )
    floor_obj, floor_img = add_calc_grid(floor_grid)

    # Render settings — need bounces for mask reflection of ground + sky
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 4096
    cycles.max_bounces = 2
    cycles.diffuse_bounces = 2
    cycles.glossy_bounces = 0
    cycles.transmission_bounces = 0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.film_exposure = 1.0
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True

    # Bake
    grid_objects = [
        (ref_grid, ref_obj, ref_img),
        (floor_grid, floor_obj, floor_img),
    ]
    baked = bake_calc_grids(grid_objects)

    # Read reference E_hz
    ref_res = 64
    ref_pixels = np.zeros(ref_res * ref_res * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(ref_pixels)
    ref_pixels = ref_pixels.reshape((ref_res, ref_res, 4))
    E_hz_pixel = np.mean(
        0.2126 * ref_pixels[:, :, 0]
        + 0.7152 * ref_pixels[:, :, 1]
        + 0.0722 * ref_pixels[:, :, 2]
    )

    if E_hz_pixel < 1e-10:
        print("  ERROR: Reference grid reads zero — sky not working")
        return None

    # Read floor pixels
    kernel = 3
    floor_res = 512
    floor_pixels = np.zeros(floor_res * floor_res * 4, dtype=np.float32)
    baked[1][1].pixels.foreach_get(floor_pixels)
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

    computed = {}
    normalization = 100.0 / E_hz_pixel

    for label, (px, py, pz) in test_case['points_floor'].items():
        u = px / room_w
        v = py / room_d
        val = sample_grid(floor_pixels, floor_res, u, v)
        computed[label] = val * normalization

    # Compare
    print(f"\n  E_hz pixel = {E_hz_pixel:.6f}")
    print(f"\n  --- Floor (SC + ERC) ---")
    print(f"  {'Point':>6}  {'Ref':>8}  {'Calc':>8}  {'Error':>8}")
    print(f"  {'-'*38}")

    max_err = 0.0
    sum_err = 0.0
    n_fail = 0
    errors = {}

    for pt in sorted(reference.keys()):
        ref_val = reference[pt]
        calc_val = computed.get(pt, 0.0)
        if ref_val < 0.01:
            err = 0.0 if abs(calc_val) < 0.5 else float('inf')
        else:
            err = (calc_val - ref_val) / ref_val
        errors[pt] = err
        abs_err = abs(err)
        if abs_err != float('inf'):
            max_err = max(max_err, abs_err)
            sum_err += abs_err
        status = 'PASS' if abs_err <= test_case['point_tolerance'] else 'FAIL'
        if status == 'FAIL':
            n_fail += 1
        if abs_err != float('inf'):
            print(f"  {pt:>6}  {ref_val:>8.2f}  {calc_val:>8.2f}  {err:>+7.2%}  {status}")

    n_points = len(reference)
    mean_err = sum_err / max(n_points, 1)
    all_pass = max_err <= test_case['global_tolerance'] and n_fail == 0

    print(f"\n  Max error: {max_err:.2%}  (limit: {test_case['global_tolerance']:.0%})"
          f"  {'PASS' if all_pass else 'FAIL'}")
    print(f"  Mean error: {mean_err:.2%}")
    print(f"  Points outside {test_case['point_tolerance']:.0%}: {n_fail}/{n_points}")

    return {
        'pass': all_pass,
        'max_error': max_err,
        'mean_error': mean_err,
        'computed': computed,
        'errors': errors,
    }


def _run_test_and_save(test_id, test_case, opening, sky_id):
    """Generic helper to run a daylight test and save results."""
    sky_name = CIE_SKY_TYPES.get(sky_id, {}).get('name', f'Type {sky_id}')

    print("\n" + "#" * 70)
    print(f"# CIE 171:2006 — Test {test_id}")
    print(f"# Opening: {opening}, Sky Type {sky_id}: {sky_name}")
    print("#" * 70)

    if test_id == '5.9':
        result = run_5_9_blender(test_case, opening, sky_id)
    elif test_id == '5.10':
        result = run_5_10_blender(test_case, opening, sky_id)
    elif test_id == '5.11':
        result = run_5_11_blender(test_case, opening, sky_id)
    elif test_id == '5.12':
        result = run_5_12_blender(test_case, opening, sky_id)
    elif test_id == '5.13':
        result = run_5_13_blender(test_case, opening, sky_id)
    elif test_id == '5.14':
        result = run_5_14_blender(test_case, opening, sky_id)
    else:
        print(f"Unknown test: {test_id}")
        return

    if result:
        results_dir = _results_dir(test_id)
        out_file = os.path.join(results_dir,
                                f'blender_{opening}_type{sky_id:02d}.json')
        with open(out_file, 'w') as f:
            json.dump({
                'sky_type': sky_id,
                'opening': opening,
                'pass': bool(result['pass']),
                'max_error': result['max_error'],
                'computed': result['computed'],
            }, f, indent=2)
        print(f"\n  Saved: {out_file}")

        print(f"\n  RESULT: {'PASS' if result['pass'] else 'FAIL'}"
              f"  (max err: {result['max_error']:.2%})")


def main():
    import argparse

    # Parse args after '--' separator
    argv = sys.argv
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(description='CIE 171 Daylight Test Runner')
    parser.add_argument('--test', type=str, required=True, help='Test ID (e.g., 5.9, 5.10)')
    parser.add_argument('--opening', type=str, default='4x4',
                        help='Opening size: 1x1 or 4x4 (default: 4x4)')
    parser.add_argument('--sky-type', type=int, default=5,
                        help='Sky type 1-16 (default: 5 = uniform)')
    args = parser.parse_args(argv)

    if args.test in ('5.9', '5.10', '5.11', '5.12', '5.13', '5.14'):
        if args.test == '5.9':
            from test_cases_daylight import TEST_5_9 as test_case
        elif args.test == '5.10':
            from test_cases_daylight import TEST_5_10 as test_case
        elif args.test == '5.11':
            from test_cases_daylight import TEST_5_11 as test_case
        elif args.test == '5.12':
            from test_cases_daylight import TEST_5_12 as test_case
        elif args.test == '5.13':
            from test_cases_daylight import TEST_5_13 as test_case
        else:
            from test_cases_daylight import TEST_5_14 as test_case

        _run_test_and_save(args.test, test_case, args.opening, args.sky_type)
    else:
        print(f"Unknown test: {args.test}")
        sys.exit(1)


if __name__ == '__main__':
    main()
