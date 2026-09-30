"""
Quick integration test: Load a CIE sky HDRI into Blender and verify
that the baked illuminance on a horizontal surface matches expectations.

Test: Type 5 (uniform sky) should produce uniform illuminance on a
horizontal surface. The normalized HDRI has E_hz = 1.0, so the baked
pixel values should be consistent (pixel = E / π).

Run with:
    blender --background --python cie171/test_sky_integration.py
"""

import bpy
import math
import os
import sys
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_RENDERER_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _RENDERER_DIR)
sys.path.insert(0, _THIS_DIR)

from fixture_config import FT_TO_M, M_TO_FT, CalcGrid
from scene_builder import (
    clear_scene, configure_cycles_base, add_calc_grid,
)
from calc_grid_bake import bake_calc_grids


def load_sky_hdri(hdr_path, strength=1.0):
    """Load an HDR image as the world environment texture."""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new('World')
        bpy.context.scene.world = world

    if hasattr(world, 'use_nodes'):
        world.use_nodes = True

    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    # Background node
    bg = nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = strength

    # Environment texture
    env_tex = nodes.new('ShaderNodeTexEnvironment')
    env_tex.image = bpy.data.images.load(hdr_path)
    # Equirectangular projection (default)
    env_tex.projection = 'EQUIRECTANGULAR'

    # Output
    output = nodes.new('ShaderNodeOutputWorld')

    links.new(env_tex.outputs['Color'], bg.inputs['Color'])
    links.new(bg.outputs['Background'], output.inputs['Surface'])

    print(f"  Loaded sky HDRI: {os.path.basename(hdr_path)}")
    print(f"  Strength: {strength}")


def main():
    print("\n" + "=" * 70)
    print("CIE SKY HDRI INTEGRATION TEST")
    print("=" * 70)

    clear_scene()

    # Load Type 5 (uniform sky) — should produce uniform illuminance
    hdr_path = os.path.join(_THIS_DIR, 'sky_hdri', 'cie_sky_type_05.hdr')
    if not os.path.exists(hdr_path):
        print(f"ERROR: {hdr_path} not found. Run cie_sky_generator.py first.")
        return

    # The HDRI is normalized so E_hz = 1.0 (radiometric W/m²).
    # Blender interprets the pixel values as radiance.
    # For a uniform sky with L = const, E_hz = π × L.
    # Our HDRI has normalized values where the integral gives E_hz = 1.0.
    # So the radiance values in the HDRI are already correct.
    # Strength=1.0 means E_hz = 1.0 W/m² from the sky.
    load_sky_hdri(hdr_path, strength=1.0)

    # Place a horizontal calc grid at z=0
    grid = CalcGrid(
        name='Sky_Test_Floor', surface='floor',
        width_ft=4.0 * M_TO_FT, height_ft=4.0 * M_TO_FT,
        spacing_ft=0.5, inset_ft=0.0, offset_ft=0.0,
        bake_resolution=128,
        position_ft=(0, 0, 0),
    )
    obj, img = add_calc_grid(grid)

    # Configure render
    scene = bpy.context.scene
    cycles = scene.cycles
    configure_cycles_base(scene)
    cycles.samples = 1024
    cycles.max_bounces = 0  # direct sky only, no bounces
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

    print(f"\n  Render: 1024 samples, 0 bounces (direct sky only)")

    # Bake
    baked = bake_calc_grids([(grid, obj, img)])

    # Read pixels
    res = 128
    pixels = np.zeros(res * res * 4, dtype=np.float32)
    baked[0][1].pixels.foreach_get(pixels)
    pixels = pixels.reshape((res, res, 4))

    # Analyze: average luminance across the grid
    lum = 0.2126 * pixels[:, :, 0] + 0.7152 * pixels[:, :, 1] + 0.0722 * pixels[:, :, 2]
    avg_pixel = np.mean(lum)
    std_pixel = np.std(lum)
    min_pixel = np.min(lum)
    max_pixel = np.max(lum)

    # For a uniform sky with E_hz = 1.0 W/m²:
    # The holdout surface (white diffuse, ρ=1) reflects L = E/π
    # So pixel = E_hz / π = 1.0 / π ≈ 0.3183
    expected = 1.0 / math.pi

    print(f"\n  Results:")
    print(f"    Average pixel:  {avg_pixel:.6f}")
    print(f"    Expected (1/π): {expected:.6f}")
    print(f"    Ratio:          {avg_pixel / expected:.4f}")
    print(f"    Std dev:        {std_pixel:.6f} ({std_pixel/avg_pixel*100:.1f}% of mean)")
    print(f"    Min/Max:        {min_pixel:.6f} / {max_pixel:.6f}")

    ratio = avg_pixel / expected
    if 0.90 < ratio < 1.10:
        print(f"\n  PASS — Sky HDRI integration working (ratio {ratio:.3f}, within 10%)")
    else:
        print(f"\n  FAIL — Unexpected ratio {ratio:.3f} (expected ~1.0)")
        print(f"    This may indicate a calibration issue with the HDRI loader")


if __name__ == '__main__':
    main()
