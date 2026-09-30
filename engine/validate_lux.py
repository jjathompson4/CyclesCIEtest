"""
Lux Validation Test - Blender 5.0 Headless Cycles
===================================================
Tests whether Cycles can produce physically accurate illuminance readings
using corrected mesh emitter fixtures with IES angular distribution.

Room setup:
- 20ft x 20ft x 10ft box (configurable in fixture_config.py)
- One or more mesh emitter fixtures with IES files
- Known material reflectances

Run with:
    blender --background --python validate_lux.py

Output:
    lux_results.txt  - grid of lux/fc values at workplane height
    lux_render.exr   - raw linear render for inspection
"""

import bpy
import os
import sys

# Ensure modules are importable from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_config import *
from scene_builder import (
    clear_scene, build_room, add_fixture,
    add_workplane_mesh, add_measurement_camera,
    configure_cycles_base,
)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────
# RENDER CONFIGURATION (lux-specific)
# ─────────────────────────────────────────────

def configure_render():
    """Configure Cycles for physically accurate lux measurement.

    Extends configure_cycles_base() with:
    - Raw view transform (no tone mapping)
    - 32-bit EXR output
    - No denoising or clamping
    - MAX_BOUNCES control for direct-only validation
    """
    scene = bpy.context.scene
    cycles = scene.cycles

    # Shared base config (engine, GPU, render passes)
    configure_cycles_base(scene)

    # Samples
    cycles.samples = RENDER_SAMPLES

    # CRITICAL: Disable ALL tone mapping, exposure, and color management
    # Raw linear values required for accurate lux extraction
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.sequencer_colorspace_settings.name = 'Linear Rec.709'
    cycles.film_exposure = 1.0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0

    # Bounce control for validation
    if MAX_BOUNCES is not None:
        cycles.max_bounces          = MAX_BOUNCES
        cycles.diffuse_bounces      = MAX_BOUNCES
        cycles.glossy_bounces       = MAX_BOUNCES
        cycles.transmission_bounces = MAX_BOUNCES
        print(f"  max_bounces = {MAX_BOUNCES} (direct-only mode)")

    # Output as EXR (full float, no compression artifacts)
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_depth = '32'
    scene.render.filepath = os.path.join(OUTPUT_DIR, 'lux_render.exr')

    # Render resolution
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512


# ─────────────────────────────────────────────
# LUX EXTRACTION
# ─────────────────────────────────────────────

def extract_lux_grid():
    """
    After rendering, sample the EXR at grid points and convert to lux.

    Cycles irradiance render pass is in W/m^2.
    Lux (lm/m^2) = W/m^2 * luminous efficacy of the illuminant.

    For a standard white LED (correlated color temperature ~4000K):
    luminous efficacy ~ 179 lm/W (photopic spectral efficiency maximum)
    """
    LUMINOUS_EFFICACY = 179.0  # lm/W, maximum photopic value

    # Load rendered EXR
    exr_path = os.path.join(OUTPUT_DIR, 'lux_render.exr')
    if not os.path.exists(exr_path):
        print("ERROR: Render output not found. Render may have failed.")
        return

    for cached in list(bpy.data.images):
        if cached.filepath == exr_path or 'lux_render' in cached.name:
            bpy.data.images.remove(cached)
    img = bpy.data.images.load(exr_path)
    img.colorspace_settings.name = 'Non-Color'
    pixels = list(img.pixels)
    width  = img.size[0]
    height = img.size[1]
    channels = img.channels  # typically 4 (RGBA)

    def sample_pixel(u, v):
        """Sample pixel at normalized UV coordinates (0-1). Returns (R,G,B)."""
        px = int(u * (width  - 1))
        py = int(v * (height - 1))
        idx = (py * width + px) * channels
        return pixels[idx], pixels[idx+1], pixels[idx+2]

    def rgb_to_luminance(r, g, b):
        """Convert linear RGB to luminance using standard coefficients."""
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    # Build measurement grid
    hw = ROOM_WIDTH  / 2
    hd = ROOM_DEPTH  / 2

    x_points = []
    x = -hw + GRID_SPACING / 2
    while x < hw:
        x_points.append(x)
        x += GRID_SPACING

    y_points = []
    y = -hd + GRID_SPACING / 2
    while y < hd:
        y_points.append(y)
        y += GRID_SPACING

    grid = []
    for y in reversed(y_points):  # top to bottom for readable output
        row = []
        for x in x_points:
            # Convert room coordinates to UV (0-1)
            u = (x + hw) / ROOM_WIDTH
            v = (y + hd) / ROOM_DEPTH
            r, g, b = sample_pixel(u, v)
            luminance_Wm2 = rgb_to_luminance(r, g, b)
            # Workplane has rho=1.0 holdout material (white for camera, transparent for bounces)
            # so reflectance divisor is 1.0 -- pixel directly represents irradiance * efficacy
            lux = luminance_Wm2 * LUMINOUS_EFFICACY
            row.append(lux)
        grid.append(row)

    return grid, x_points, y_points


def write_results(grid, x_points, y_points):
    """Write lux grid to text file with imperial coordinates and dual units."""
    if not grid:
        return

    all_values = [v for row in grid for v in row]
    lux_min  = min(all_values)
    lux_max  = max(all_values)
    lux_avg  = sum(all_values) / len(all_values)
    fc_min   = lux_min * LUX_TO_FC
    fc_max   = lux_max * LUX_TO_FC
    fc_avg   = lux_avg * LUX_TO_FC
    uniformity_avg = lux_min / lux_avg  if lux_avg  > 0 else 0
    uniformity_max = lux_min / lux_max  if lux_max  > 0 else 0

    # Convert grid coordinates to feet for display
    x_ft = [x * M_TO_FT for x in x_points]
    y_ft = [y * M_TO_FT for y in y_points]

    out_path = os.path.join(OUTPUT_DIR, 'lux_results.txt')
    with open(out_path, 'w') as f:
        f.write("=" * 70 + "\n")
        f.write("LUX VALIDATION TEST - Blender 5.0 / Cycles\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"Room:           {ROOM_WIDTH_FT:.0f}' x {ROOM_DEPTH_FT:.0f}' x {ROOM_HEIGHT_FT:.0f}'\n")
        f.write(f"Workplane:      {WORKPLANE_HEIGHT_FT:.1f}' AFF\n")
        f.write(f"Grid spacing:   {GRID_SPACING_FT:.0f}'\n")
        f.write(f"Render samples: {RENDER_SAMPLES}\n")
        f.write(f"Reflectances:   Ceiling {REFLECTANCE_CEILING*100:.0f}%  "
                f"Walls {REFLECTANCE_WALLS*100:.0f}%  "
                f"Floor {REFLECTANCE_FLOOR*100:.0f}%\n\n")

        f.write("FIXTURES:\n")
        for i, fix in enumerate(FIXTURES, 1):
            f.write(f"  {i}. {fix}\n")
        f.write("\n")

        f.write("-" * 70 + "\n")
        f.write("SUMMARY\n")
        f.write("-" * 70 + "\n")
        f.write(f"  Maximum:          {lux_max:8.1f} lux  /  {fc_max:6.1f} fc\n")
        f.write(f"  Minimum:          {lux_min:8.1f} lux  /  {fc_min:6.1f} fc\n")
        f.write(f"  Average:          {lux_avg:8.1f} lux  /  {fc_avg:6.1f} fc\n")
        f.write(f"  Uniformity (min/avg): {uniformity_avg:.2f}\n")
        f.write(f"  Uniformity (min/max): {uniformity_max:.2f}\n\n")

        f.write("-" * 70 + "\n")
        f.write("POINT CALCULATION GRID (fc)\n")
        f.write("Coordinates in feet from room center. North at top.\n")
        f.write("-" * 70 + "\n\n")

        # Column headers in feet
        header = "  Y\\X  " + "".join(f" {xf:+6.1f}" for xf in x_ft)
        f.write(header + "\n")

        for i, row in enumerate(grid):
            yf = y_ft[len(y_ft) - 1 - i]  # reversed order
            fc_vals = [v * LUX_TO_FC for v in row]
            line = f"{yf:+6.1f} " + "".join(f" {v:6.1f}" for v in fc_vals)
            f.write(line + "\n")

        f.write(f"\n(Values in footcandles. Multiply by 10.764 for lux.)\n")

    # Console output
    print(f"\nResults written to: {out_path}")
    print(f"\nSUMMARY:")
    print(f"  Max: {lux_max:.1f} lux / {fc_max:.1f} fc")
    print(f"  Min: {lux_min:.1f} lux / {fc_min:.1f} fc")
    print(f"  Avg: {lux_avg:.1f} lux / {fc_avg:.1f} fc")
    print(f"  Uniformity (min/avg): {uniformity_avg:.2f}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("\n" + "="*70)
    print("LUX VALIDATION TEST")
    print("="*70)
    print(f"\nRoom: {ROOM_WIDTH_FT:.0f}' x {ROOM_DEPTH_FT:.0f}' x {ROOM_HEIGHT_FT:.0f}'")
    print(f"Workplane: {WORKPLANE_HEIGHT_FT:.1f}' AFF")
    print(f"Grid: {GRID_SPACING_FT:.0f}' spacing\n")

    print(f"Fixtures ({len(FIXTURES)}):")
    for i, fix in enumerate(FIXTURES, 1):
        print(f"  {i}. {fix}")
    print()

    clear_scene()
    build_room()

    for i, fixture in enumerate(FIXTURES, 1):
        print(f"Adding fixture {i}/{len(FIXTURES)}:")
        add_fixture(fixture, fixture_id=i)

    configure_render()
    add_workplane_mesh()
    add_measurement_camera()

    print("\nRendering... (this may take a minute)\n")
    bpy.ops.render.render(write_still=True)

    print("\nExtracting lux values from render...\n")
    result = extract_lux_grid()
    if result:
        grid, x_points, y_points = result
        write_results(grid, x_points, y_points)
    else:
        print("ERROR: Lux extraction failed.")

    print("\nDone.")


if __name__ == '__main__':
    main()
