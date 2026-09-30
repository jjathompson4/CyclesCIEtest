"""
Perspective View Rendering - Blender 5.0 Headless Cycles
=========================================================
Renders a photorealistic perspective view of the lighting scene.

Uses the same corrected mesh emitter fixtures as validate_lux.py,
producing visually accurate area light apertures with proper IES
angular distribution.

Two output modes:
    'Filmic' + PNG  — beauty render for visual evaluation
    'Raw' + EXR     — linear data for falsecolor analysis

Run with:
    blender --background --python render_perspective.py
"""

import bpy
import math
import os
import sys

# Ensure modules are importable from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_config import *
from scene_builder import (
    clear_scene, build_room, add_fixture,
    add_perspective_camera,
    configure_cycles_base,
)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────
# RENDER CONFIGURATION (perspective-specific)
# ─────────────────────────────────────────────

def configure_render():
    """Configure Cycles for perspective rendering.

    Extends configure_cycles_base() with:
    - View transform (Filmic for beauty, Raw for analysis)
    - Output format (PNG for beauty, EXR for falsecolor)
    - Higher samples for clean visuals
    - Denoising for beauty renders
    - Full bounces (no MAX_BOUNCES override)
    """
    scene = bpy.context.scene
    cycles = scene.cycles

    # Shared base config (engine, GPU, render passes)
    configure_cycles_base(scene)

    # Samples
    cycles.samples = PERSP_RENDER_SAMPLES

    # View transform
    scene.view_settings.view_transform = PERSP_VIEW_TRANSFORM
    if PERSP_VIEW_TRANSFORM == 'Raw':
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
    else:
        # Filmic defaults — let Blender handle tone mapping
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0

    scene.sequencer_colorspace_settings.name = 'Linear Rec.709'
    cycles.film_exposure = 1.0

    # Denoising
    cycles.use_denoising = PERSP_ENABLE_DENOISING
    if PERSP_ENABLE_DENOISING:
        cycles.denoiser = 'OPENIMAGEDENOISE'

    # Clamping — off for accuracy
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0

    # Full bounces (no restriction for perspective renders)
    # Let Cycles use defaults for realistic inter-reflections

    # Output format
    ext = 'exr' if PERSP_OUTPUT_FORMAT == 'OPEN_EXR' else 'png'
    scene.render.image_settings.file_format = PERSP_OUTPUT_FORMAT
    if PERSP_OUTPUT_FORMAT == 'OPEN_EXR':
        scene.render.image_settings.color_depth = '32'
    else:
        scene.render.image_settings.color_depth = '16'
        scene.render.image_settings.color_mode = 'RGBA'

    scene.render.filepath = os.path.join(OUTPUT_DIR, f'perspective_render.{ext}')

    # Render resolution
    res_x, res_y = PERSP_RESOLUTION
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100

    print(f"\nPerspective render config:")
    print(f"  Resolution: {res_x} x {res_y}")
    print(f"  Samples: {PERSP_RENDER_SAMPLES}")
    print(f"  View transform: {PERSP_VIEW_TRANSFORM}")
    print(f"  Output: {PERSP_OUTPUT_FORMAT} ({ext})")
    print(f"  Denoising: {PERSP_ENABLE_DENOISING}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("\n" + "=" * 70)
    print("PERSPECTIVE VIEW RENDER")
    print("=" * 70)
    print(f"\nRoom: {ROOM_WIDTH_FT:.0f}' x {ROOM_DEPTH_FT:.0f}' x {ROOM_HEIGHT_FT:.0f}'")

    print(f"\nFixtures ({len(FIXTURES)}):")
    for i, fix in enumerate(FIXTURES, 1):
        print(f"  {i}. {fix}")
    print()

    clear_scene()
    build_room()

    for i, fixture in enumerate(FIXTURES, 1):
        print(f"Adding fixture {i}/{len(FIXTURES)}:")
        add_fixture(fixture, fixture_id=i)

    configure_render()
    add_perspective_camera()

    print("\nRendering perspective view... (this may take a few minutes)\n")
    bpy.ops.render.render(write_still=True)

    ext = 'exr' if PERSP_OUTPUT_FORMAT == 'OPEN_EXR' else 'png'
    out_path = os.path.join(OUTPUT_DIR, f'perspective_render.{ext}')
    print(f"\nPerspective render saved to: {out_path}")
    print("\nDone.")


if __name__ == '__main__':
    main()
