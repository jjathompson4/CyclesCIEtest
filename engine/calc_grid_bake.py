"""
CalcGrid Bake — Illuminance Measurement via Cycles Texture Baking
================================================================
Single-pass illuminance extraction from holdout calc grid meshes.

Phase 1 — Bake:
  - Each CalcGrid mesh gets baked in one bpy.ops.object.bake() call
  - Holdout material: bake rays are camera rays → white diffuse (rho=1)
  - Same physics as validate_lux.py orthographic camera method
  - Illuminance: E = pixel_luminance * 179 lm/W

Phase 2 — Falsecolor render:
  - Swaps calc grid material to falsecolor emission (camera-only)
  - Renders a perspective view with the falsecolor overlay in the 3D room
  - Stepping stone toward the web interactive viewer

Run with:
    blender --background --python calc_grid_bake.py

Output:
    calcgrid_results.txt          — per-grid illuminance values + stats
    calcgrid_<name>.exr           — raw baked texture per grid
    calcgrid_falsecolor.png       — perspective render with falsecolor overlay
"""

import bpy
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_config import *
from scene_builder import (
    clear_scene, build_room, build_floor_plan, add_fixture, add_calc_grid,
    configure_cycles_base,
)


def point_in_polygon(px, py, polygon):
    """Ray-casting point-in-polygon test.

    Args:
        px, py: point coordinates
        polygon: list of (x, y) tuples forming a closed polygon

    Returns:
        True if point is inside the polygon
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
LUMINOUS_EFFICACY = 179.0  # lm/W


# ─────────────────────────────────────────────
# RENDER CONFIGURATION (bake-specific)
# ─────────────────────────────────────────────

def configure_bake_render():
    """Configure Cycles for physically accurate baking.

    Same settings as validate_lux.py (Raw, no denoising, no clamping)
    but without camera/resolution setup since we're baking to textures.
    """
    scene = bpy.context.scene
    cycles = scene.cycles

    configure_cycles_base(scene)

    cycles.samples = RENDER_SAMPLES

    # Raw linear — no tone mapping
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.sequencer_colorspace_settings.name = 'Linear Rec.709'
    cycles.film_exposure = 1.0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0

    # Bounce control
    if MAX_BOUNCES is not None:
        cycles.max_bounces          = MAX_BOUNCES
        cycles.diffuse_bounces      = MAX_BOUNCES
        cycles.glossy_bounces       = MAX_BOUNCES
        cycles.transmission_bounces = MAX_BOUNCES
        print(f"  max_bounces = {MAX_BOUNCES}")

    # Bake settings
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True


# ─────────────────────────────────────────────
# BAKE EXECUTION
# ─────────────────────────────────────────────

def bake_calc_grids(grid_objects):
    """Bake illuminance onto each calc grid mesh.

    Selects each calc grid object and bakes COMBINED pass to its
    associated image texture. Returns list of (CalcGrid, bake_image) tuples.

    Args:
        grid_objects: list of (CalcGrid, blender_obj, bake_image) tuples

    Returns:
        list of (CalcGrid, bake_image) with baked data
    """
    results = []

    for calc_grid, obj, bake_img in grid_objects:
        print(f"\n  Baking '{calc_grid.name}'...")

        # Deselect all, then select only this grid object
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Ensure the image texture node is active in the material
        mat = obj.data.materials[0]
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                node.select = True
                mat.node_tree.nodes.active = node
                break

        # Bake COMBINED pass (direct + indirect lighting)
        bpy.ops.object.bake(type='COMBINED')

        # Save baked image as EXR
        exr_path = os.path.join(OUTPUT_DIR, f'calcgrid_{calc_grid.name.lower()}.exr')
        bake_img.filepath_raw = exr_path
        bake_img.file_format = 'OPEN_EXR'
        bake_img.save()
        print(f"    Saved: {exr_path}")

        results.append((calc_grid, bake_img))

    return results


# ─────────────────────────────────────────────
# ILLUMINANCE EXTRACTION
# ─────────────────────────────────────────────

def extract_illuminance(calc_grid, bake_img):
    """Extract illuminance grid from baked texture.

    Samples the baked image at grid point locations and converts
    pixel luminance to illuminance: E = L * 179 lm/W.

    For polygonal grids (boundary_ft set), points outside the polygon
    are masked as None and excluded from statistics.

    Returns:
        dict with keys: grid_lux, grid_fc, x_ft, y_ft, stats
    """
    res = calc_grid.bake_resolution
    w_m, h_m = calc_grid.mesh_dims_m
    spacing_m = calc_grid.spacing_ft * FT_TO_M
    has_boundary = calc_grid.boundary_ft is not None and len(calc_grid.boundary_ft) >= 3

    # For polygon grids, the bake mesh bounding box defines w_m/h_m.
    # boundary_ft vertices are in local feet relative to position.
    # Grid sample points are also in local coordinates relative to bounding box center.
    if has_boundary:
        boundary_m = [(v[0] * FT_TO_M, v[1] * FT_TO_M) for v in calc_grid.boundary_ft]
        bx = [v[0] for v in boundary_m]
        by = [v[1] for v in boundary_m]
        bb_min_x, bb_max_x = min(bx), max(bx)
        bb_min_y, bb_max_y = min(by), max(by)
        w_m = max(bb_max_x - bb_min_x, 1e-6)
        h_m = max(bb_max_y - bb_min_y, 1e-6)

    # Read pixels into numpy array
    pixel_count = res * res * 4  # RGBA
    pixels = np.zeros(pixel_count, dtype=np.float32)
    bake_img.pixels.foreach_get(pixels)
    pixels = pixels.reshape((res, res, 4))

    # Build grid sample points in local UV space
    n_x = max(1, round(w_m / spacing_m))
    n_y = max(1, round(h_m / spacing_m))

    # Center the grid within the mesh bounding box
    x_start = (w_m - (n_x - 1) * spacing_m) / 2
    y_start = (h_m - (n_y - 1) * spacing_m) / 2

    grid_lux = []
    x_positions_m = []
    y_positions_m = []

    for iy in range(n_y):
        y_local = y_start + iy * spacing_m
        y_positions_m.append(y_local - h_m / 2)

    for ix in range(n_x):
        x_local = x_start + ix * spacing_m
        x_positions_m.append(x_local - w_m / 2)

    for iy in reversed(range(n_y)):  # top to bottom for display
        row = []
        y_local = y_start + iy * spacing_m
        v = y_local / h_m  # UV 0-1
        py = int(v * (res - 1))
        py = max(0, min(res - 1, py))

        for ix in range(n_x):
            x_local = x_start + ix * spacing_m

            # For polygon grids, check if point is inside the boundary
            if has_boundary:
                # Convert grid sample back to local feet for polygon test
                pt_x_ft = (x_local - w_m / 2 + (bb_min_x + bb_max_x) / 2) * M_TO_FT
                pt_y_ft = (y_local - h_m / 2 + (bb_min_y + bb_max_y) / 2) * M_TO_FT
                if not point_in_polygon(pt_x_ft, pt_y_ft, calc_grid.boundary_ft):
                    row.append(None)
                    continue

            u = x_local / w_m
            px = int(u * (res - 1))
            px = max(0, min(res - 1, px))

            r, g, b = pixels[py, px, 0], pixels[py, px, 1], pixels[py, px, 2]
            luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
            lux = luminance * LUMINOUS_EFFICACY
            row.append(lux)
        grid_lux.append(row)

    # Convert positions to feet
    # For polygon grids, x/y positions are relative to bounding box center,
    # but position_ft is the centroid. Shift so positions are relative to centroid.
    if has_boundary:
        bb_cx = (bb_min_x + bb_max_x) / 2
        bb_cy = (bb_min_y + bb_max_y) / 2
        x_ft = [(x + bb_cx) * M_TO_FT for x in x_positions_m]
        y_ft = [(y + bb_cy) * M_TO_FT for y in y_positions_m]
    else:
        x_ft = [x * M_TO_FT for x in x_positions_m]
        y_ft = [y * M_TO_FT for y in y_positions_m]

    # Stats — exclude None (masked) values
    all_vals = [v for row in grid_lux for v in row if v is not None]
    if len(all_vals) == 0:
        all_vals = [0.0]  # fallback
    lux_max = max(all_vals)
    lux_min = min(all_vals)
    lux_avg = sum(all_vals) / len(all_vals)

    stats = {
        'max_lux': lux_max,
        'min_lux': lux_min,
        'avg_lux': lux_avg,
        'max_fc': lux_max * LUX_TO_FC,
        'min_fc': lux_min * LUX_TO_FC,
        'avg_fc': lux_avg * LUX_TO_FC,
        'uniformity_avgmin': lux_avg / lux_min if lux_min > 0 else 0,
        'uniformity_maxmin': lux_max / lux_min if lux_min > 0 else 0,
        'n_points': len(all_vals),
    }

    return {
        'grid_lux': grid_lux,
        'x_ft': x_ft,
        'y_ft': y_ft,
        'stats': stats,
    }


# ─────────────────────────────────────────────
# RESULTS OUTPUT
# ─────────────────────────────────────────────

def write_results(all_results, rooms=None, fixtures=None):
    """Write all calc grid results to a single text file."""
    out_path = os.path.join(OUTPUT_DIR, 'calcgrid_results.txt')

    fix_list = fixtures if fixtures else FIXTURES

    with open(out_path, 'w') as f:
        f.write("=" * 70 + "\n")
        f.write("CALC GRID BAKE — Illuminance Results\n")
        f.write("=" * 70 + "\n\n")

        if rooms:
            f.write(f"Floor plan: {len(rooms)} rooms\n")
            for r in rooms:
                f.write(f"  {r.name}: {r.width_ft:.0f}' x {r.depth_ft:.0f}' x {r.height_ft:.0f}'  "
                        f"origin=({r.origin_ft[0]:.0f}, {r.origin_ft[1]:.0f})\n")
        else:
            f.write(f"Room:           {ROOM_WIDTH_FT:.0f}' x {ROOM_DEPTH_FT:.0f}' x {ROOM_HEIGHT_FT:.0f}'\n")
        f.write(f"Render samples: {RENDER_SAMPLES}\n")
        if MAX_BOUNCES is not None:
            f.write(f"Max bounces:    {MAX_BOUNCES} (direct-only)\n")
        else:
            f.write(f"Max bounces:    default (full GI)\n")
        f.write(f"Reflectances:   Ceiling {REFLECTANCE_CEILING*100:.0f}%  "
                f"Walls {REFLECTANCE_WALLS*100:.0f}%  "
                f"Floor {REFLECTANCE_FLOOR*100:.0f}%\n\n")

        f.write("FIXTURES:\n")
        for i, fix in enumerate(fix_list, 1):
            f.write(f"  {i}. {fix}\n")
        f.write("\n")

        for calc_grid, result in all_results:
            stats = result['stats']
            x_ft = result['x_ft']
            y_ft = result['y_ft']
            grid_lux = result['grid_lux']

            f.write("-" * 70 + "\n")
            f.write(f"CALC GRID: {calc_grid.name}\n")
            f.write(f"  Surface:  {calc_grid.surface}\n")
            f.write(f"  Offset:   {calc_grid.offset_ft:.1f}' from surface\n")
            f.write(f"  Spacing:  {calc_grid.spacing_ft:.1f}'\n")
            f.write(f"  Inset:    {calc_grid.inset_ft:.1f}' from edges\n")
            w_m, h_m = calc_grid.mesh_dims_m
            f.write(f"  Mesh:     {w_m*M_TO_FT:.1f}' x {h_m*M_TO_FT:.1f}'\n")
            f.write(f"  Points:   {stats['n_points']}\n")
            f.write("-" * 70 + "\n\n")

            f.write("SUMMARY:\n")
            f.write(f"  Maximum:          {stats['max_lux']:8.1f} lux  /  {stats['max_fc']:6.1f} fc\n")
            f.write(f"  Minimum:          {stats['min_lux']:8.1f} lux  /  {stats['min_fc']:6.1f} fc\n")
            f.write(f"  Average:          {stats['avg_lux']:8.1f} lux  /  {stats['avg_fc']:6.1f} fc\n")
            f.write(f"  Avg:Min ratio: {stats['uniformity_avgmin']:.1f}:1\n" if stats['uniformity_avgmin'] > 0 else "  Avg:Min ratio: N/A\n")
            f.write(f"  Max:Min ratio: {stats['uniformity_maxmin']:.1f}:1\n\n" if stats['uniformity_maxmin'] > 0 else "  Max:Min ratio: N/A\n\n")

            f.write("POINT GRID (fc):\n")
            f.write(f"Coordinates in feet from grid center. North at top.\n\n")

            header = "  Y\\X  " + "".join(f" {xf:+6.1f}" for xf in x_ft)
            f.write(header + "\n")

            for i, row in enumerate(grid_lux):
                yf = y_ft[len(y_ft) - 1 - i]
                fc_vals = [v * LUX_TO_FC if v is not None else None for v in row]
                line = f"{yf:+6.1f} " + "".join(f" {v:6.1f}" if v is not None else "   ---" for v in fc_vals)
                f.write(line + "\n")

            f.write(f"\n(Values in footcandles. Multiply by 10.764 for lux.)\n\n")

    print(f"\nResults written to: {out_path}")
    return out_path


def write_results_json(all_results, rooms=None, fixtures=None, output_dir=None, wall_edges=None):
    """Write calc grid results as JSON for downstream tools (PDF, web viewer).

    Args:
        all_results: list of (CalcGrid, result_dict)
        rooms:       list of Room objects (None for single-room mode)
        fixtures:    list of Fixture objects
        output_dir:  output directory (None = module-level OUTPUT_DIR)
        wall_edges:  list of [[x1,y1],[x2,y2]] line segments in feet (from mesh bisect)
    """
    import json

    class NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return super().default(obj)

    data = {
        'rooms': [],
        'fixtures': [],
        'grids': [],
    }

    if rooms is None:
        # Standalone mode (no rooms passed) — use default room from fixture_config
        data['rooms'].append({
            'name': 'Room',
            'origin_ft': [-ROOM_WIDTH_FT / 2, -ROOM_DEPTH_FT / 2],
            'width_ft': ROOM_WIDTH_FT,
            'depth_ft': ROOM_DEPTH_FT,
            'height_ft': ROOM_HEIGHT_FT,
        })
    else:
        # API mode — use provided rooms (may be empty for FBX-only projects)
        for room in rooms:
            data['rooms'].append({
                'name': room.name,
                'origin_ft': list(room.origin_ft),
                'width_ft': room.width_ft,
                'depth_ft': room.depth_ft,
                'height_ft': room.height_ft,
            })

    if fixtures:
        for fix in fixtures:
            data['fixtures'].append({
                'ies_file': os.path.basename(fix.ies_path),
                'position_ft': list(fix.position_ft),
                'length_ft': fix.length_ft,
                'width_inches': fix.width_inches,
                'rotation': list(fix.rotation),
            })

    for calc_grid, result in all_results:
        stats = result['stats']
        grid_fc = [[v * LUX_TO_FC if v is not None else None for v in row] for row in result['grid_lux']]
        grid_entry = {
            'name': calc_grid.name,
            'room_name': calc_grid.room_name,
            'position_ft': list(calc_grid.position_ft) if calc_grid.position_ft else None,
            'width_ft': calc_grid.width_ft if calc_grid.width_ft > 0 else None,
            'height_ft': calc_grid.height_ft if calc_grid.height_ft > 0 else None,
            'spacing_ft': calc_grid.spacing_ft,
            'x_ft': result['x_ft'],
            'y_ft': result['y_ft'],
            'values_fc': grid_fc,
            'stats': {
                'max_fc': round(stats['max_fc'], 1),
                'min_fc': round(stats['min_fc'], 1),
                'avg_fc': round(stats['avg_fc'], 1),
                'max_lux': round(stats['max_lux'], 1),
                'min_lux': round(stats['min_lux'], 1),
                'avg_lux': round(stats['avg_lux'], 1),
                'uniformity_avgmin': round(stats['uniformity_avgmin'], 2),
                'uniformity_maxmin': round(stats['uniformity_maxmin'], 2),
                'n_points': stats['n_points'],
            },
        }
        if calc_grid.boundary_ft is not None:
            grid_entry['boundary_ft'] = calc_grid.boundary_ft
        data['grids'].append(grid_entry)

    # Wall edge segments from imported model mesh bisect
    if wall_edges:
        data['walls'] = wall_edges

    out = output_dir if output_dir else OUTPUT_DIR
    json_path = os.path.join(out, 'calcgrid_results.json')
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2, cls=NumpyEncoder)

    print(f"JSON results written to: {json_path}")
    return json_path


# ─────────────────────────────────────────────
# FALSECOLOR MATERIAL + PERSPECTIVE RENDER
# ─────────────────────────────────────────────

# Turbo colormap key stops (Google AI, Apache 2.0)
TURBO_STOPS = [
    (0.00, (0.190, 0.072, 0.232)),
    (0.10, (0.103, 0.245, 0.633)),
    (0.25, (0.030, 0.528, 0.765)),
    (0.40, (0.174, 0.762, 0.448)),
    (0.55, (0.566, 0.896, 0.165)),
    (0.70, (0.902, 0.807, 0.085)),
    (0.85, (0.972, 0.507, 0.051)),
    (1.00, (0.706, 0.016, 0.150)),
]


def srgb_to_linear(c):
    """Convert sRGB color values to linear. Vectorized for numpy arrays."""
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def turbo_colormap(t):
    """Map scalar t (0-1) to turbo RGB color in LINEAR space.

    Turbo stops are defined in sRGB; converted to linear for Blender's
    float buffer (Standard view transform applies sRGB gamma on output).
    """
    positions = np.array([s[0] for s in TURBO_STOPS])
    colors_srgb = np.array([s[1] for s in TURBO_STOPS])
    colors_linear = srgb_to_linear(colors_srgb)

    t = np.clip(t, 0.0, 1.0)
    rgb = np.zeros((*t.shape, 3), dtype=np.float32)
    for ch in range(3):
        rgb[..., ch] = np.interp(t, positions, colors_linear[:, ch])
    return rgb


def make_falsecolor_image(bake_img, max_lux, res):
    """Generate a falsecolor RGBA image from baked illuminance data.

    Reads the baked texture, converts to illuminance, maps through
    the turbo colormap, and returns a new Blender image with the
    pre-computed falsecolor pixels.

    Args:
        bake_img:  Blender image with baked illuminance data
        max_lux:   maximum illuminance for color scale
        res:       image resolution (pixels per side)

    Returns:
        Blender image with falsecolor RGBA pixels
    """
    # Read baked pixels
    pixel_count = res * res * 4
    raw = np.zeros(pixel_count, dtype=np.float32)
    bake_img.pixels.foreach_get(raw)
    raw = raw.reshape((res, res, 4))

    # Convert to illuminance (luminance weighting, * 179)
    luminance = 0.2126 * raw[:, :, 0] + 0.7152 * raw[:, :, 1] + 0.0722 * raw[:, :, 2]
    lux = luminance * LUMINOUS_EFFICACY

    # Normalize to 0-1 for colormap
    t = lux / max(max_lux, 1.0)

    # Map through turbo colormap
    rgb = turbo_colormap(t)

    # Build RGBA flat array for Blender
    rgba = np.ones((res, res, 4), dtype=np.float32)
    rgba[:, :, :3] = rgb

    # Create new Blender image
    img_name = f'Falsecolor_{bake_img.name}'
    if img_name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[img_name])
    fc_img = bpy.data.images.new(img_name, width=res, height=res,
                                  alpha=False, float_buffer=True)
    fc_img.pixels.foreach_set(rgba.ravel())
    fc_img.update()

    return fc_img


def make_falsecolor_material(name, fc_img):
    """Create an emission material displaying a pre-computed falsecolor image.

    Camera rays see the falsecolor emission; other rays see transparent.
    Simple shader: Image Texture → Emission → MixShader → Output.

    Args:
        name:    material name
        fc_img:  Blender image with pre-computed falsecolor RGBA pixels
    """
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Image Texture — reads pre-computed falsecolor via UV
    img_tex = nodes.new('ShaderNodeTexImage')
    img_tex.image = fc_img
    img_tex.interpolation = 'Linear'

    # Emission — self-lit, moderate strength to avoid Filmic desaturation
    emission = nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 1.0
    links.new(img_tex.outputs['Color'], emission.inputs['Color'])

    # Camera-only: camera rays → falsecolor emission, other rays → transparent
    lp   = nodes.new('ShaderNodeLightPath')
    trans = nodes.new('ShaderNodeBsdfTransparent')
    mix   = nodes.new('ShaderNodeMixShader')
    links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
    links.new(trans.outputs['BSDF'],       mix.inputs[1])
    links.new(emission.outputs['Emission'], mix.inputs[2])

    # Output
    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(mix.outputs['Shader'], output.inputs['Surface'])

    return mat


def render_falsecolor_overlay(grid_objects, all_results, rooms=None):
    """Swap calc grid materials to falsecolor and render a perspective view.

    Args:
        grid_objects: list of (CalcGrid, blender_obj, bake_image)
        all_results:  list of (CalcGrid, result_dict) from extraction
        rooms:        list of Room objects (None for single-room mode)
    """
    print("\n" + "=" * 70)
    print("PHASE 2 — Falsecolor Perspective Render")
    print("=" * 70)

    # Build lookup for max_lux per grid
    max_lux_map = {}
    for calc_grid, result in all_results:
        max_lux_map[calc_grid.name] = result['stats']['max_lux']

    # Generate falsecolor images and swap materials on each calc grid
    for calc_grid, obj, bake_img in grid_objects:
        max_lux = max_lux_map.get(calc_grid.name, 250.0)
        res = calc_grid.bake_resolution

        # Pre-compute falsecolor pixels (numpy) — no shader complexity
        fc_img = make_falsecolor_image(bake_img, max_lux, res)
        print(f"  Generated falsecolor image for '{calc_grid.name}' (scale: 0-{max_lux:.0f} lux)")

        # Create and apply falsecolor material
        mat_name = f'Falsecolor_{calc_grid.name}'
        fc_mat = make_falsecolor_material(mat_name, fc_img)
        obj.data.materials.clear()
        obj.data.materials.append(fc_mat)

    # ── Common render settings ──
    scene = bpy.context.scene
    cycles = scene.cycles

    # Use Standard view transform — preserves falsecolor saturation (no Filmic rolloff)
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.exposure = 1.0
    scene.view_settings.gamma = 1.0
    cycles.samples = 512
    cycles.use_denoising = True

    # Full GI for the perspective render
    cycles.max_bounces = 12
    cycles.diffuse_bounces = 4
    cycles.glossy_bounces = 4
    cycles.transmission_bounces = 4

    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_depth = '8'

    # Compute bounding box for camera placement
    if rooms:
        x_min = min(r.origin_ft[0] for r in rooms)
        y_min = min(r.origin_ft[1] for r in rooms)
        x_max = max(r.origin_ft[0] + r.width_ft for r in rooms)
        y_max = max(r.origin_ft[1] + r.depth_ft for r in rooms)
        max_height = max(r.height_ft for r in rooms)
        cx = (x_min + x_max) / 2 * FT_TO_M
        cy = (y_min + y_max) / 2 * FT_TO_M
        bb_w = (x_max - x_min) * FT_TO_M
        bb_d = (y_max - y_min) * FT_TO_M
        cam_z = max_height * FT_TO_M - 0.01
    else:
        cx, cy = 0, 0
        bb_w = ROOM_WIDTH
        bb_d = ROOM_DEPTH
        cam_z = ROOM_HEIGHT - 0.01

    # ── Render 1: Top-down plan view (orthographic, ceiling hidden) ──
    print("\n  --- Render 1: Plan view (orthographic, top-down) ---")

    # Hide ceilings so they don't block the top-down view
    for obj in bpy.data.objects:
        if 'Ceiling' in obj.name:
            obj.hide_render = True

    # Also hide fixtures so we see just the room outline + calc grid
    for obj in bpy.data.objects:
        if obj.name.startswith('Fixture_'):
            obj.hide_render = True

    bpy.ops.object.camera_add(location=(cx, cy, cam_z))
    plan_cam = bpy.context.active_object
    plan_cam.name = 'PlanCamera'
    plan_cam.data.type = 'ORTHO'
    plan_cam.data.ortho_scale = max(bb_w, bb_d) * 1.1
    plan_cam.rotation_euler = (0, 0, 0)

    bpy.context.scene.camera = plan_cam

    # Resolution proportional to floor plan aspect ratio
    plan_res_base = 1200
    aspect = bb_w / bb_d if bb_d > 0 else 1.0
    if aspect >= 1.0:
        scene.render.resolution_x = plan_res_base
        scene.render.resolution_y = int(plan_res_base / aspect)
    else:
        scene.render.resolution_x = int(plan_res_base * aspect)
        scene.render.resolution_y = plan_res_base

    plan_path = os.path.join(OUTPUT_DIR, 'calcgrid_falsecolor_plan.png')
    scene.render.filepath = plan_path

    print(f"  Resolution: 1024x1024, orthographic")
    bpy.ops.render.render(write_still=True)
    print(f"  Saved: {plan_path}")

    # Unhide ceilings and fixtures for perspective render
    for obj in bpy.data.objects:
        if 'Ceiling' in obj.name or obj.name.startswith('Fixture_'):
            obj.hide_render = False

    # ── Render 2: Perspective view (inside room) ──
    print("\n  --- Render 2: Perspective view ---")

    if rooms:
        # Position camera to see the whole floor plan from a corner
        cam_pos_ft = (x_max + 5, y_min - 8, max_height - 1)
        cam_target_ft = (cx / FT_TO_M, cy / FT_TO_M, 2.5)
    else:
        cam_pos_ft = (8.0, -7.0, 8.0)
        cam_target_ft = (0.0, 0.0, 2.5)
    cam_pos = tuple(v * FT_TO_M for v in cam_pos_ft)
    cam_target = tuple(v * FT_TO_M for v in cam_target_ft)

    bpy.ops.object.camera_add(location=cam_pos)
    cam_obj = bpy.context.active_object
    cam_obj.data.type = 'PERSP'
    cam_obj.data.lens_unit = 'FOV'
    cam_obj.data.angle = math.radians(70.0)

    bpy.ops.object.empty_add(location=cam_target)
    target_obj = bpy.context.active_object
    target_obj.name = 'FC_CameraTarget'

    constraint = cam_obj.constraints.new(type='TRACK_TO')
    constraint.target = target_obj
    constraint.track_axis = 'TRACK_NEGATIVE_Z'
    constraint.up_axis = 'UP_Y'

    bpy.context.scene.camera = cam_obj
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080

    persp_path = os.path.join(OUTPUT_DIR, 'calcgrid_falsecolor.png')
    scene.render.filepath = persp_path

    print(f"  Camera: ({cam_pos_ft[0]}, {cam_pos_ft[1]}, {cam_pos_ft[2]}) ft")
    print(f"  Resolution: 1920x1080, 512 samples")
    bpy.ops.render.render(write_still=True)
    print(f"  Saved: {persp_path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("\n" + "=" * 70)
    print("CALC GRID BAKE — Illuminance via Texture Baking")
    print("=" * 70)

    # Determine mode: multi-room floor plan or single room
    try:
        from fixture_config import USE_FLOOR_PLAN, FLOOR_PLAN_ROOMS, FLOOR_PLAN_FIXTURES, FLOOR_PLAN_GRIDS
        use_floor_plan = USE_FLOOR_PLAN
    except ImportError:
        use_floor_plan = False

    if use_floor_plan:
        rooms = FLOOR_PLAN_ROOMS
        fixtures = FLOOR_PLAN_FIXTURES
        calc_grids = FLOOR_PLAN_GRIDS
        print(f"\nFloor plan mode: {len(rooms)} rooms, {len(fixtures)} fixtures, {len(calc_grids)} grids")
        for r in rooms:
            print(f"  {r.name}: {r.width_ft:.0f}' x {r.depth_ft:.0f}' x {r.height_ft:.0f}'")
    else:
        rooms = None
        fixtures = FIXTURES
        calc_grids = CALC_GRIDS
        print(f"\nSingle room: {ROOM_WIDTH_FT:.0f}' x {ROOM_DEPTH_FT:.0f}' x {ROOM_HEIGHT_FT:.0f}'")
        print(f"Fixtures: {len(fixtures)}")
        print(f"Calc grids: {len(calc_grids)}")
    print()

    # Build scene
    clear_scene()
    if use_floor_plan:
        print("Building floor plan:")
        build_floor_plan(rooms)
    else:
        build_room()

    print("\nAdding fixtures:")
    for i, fixture in enumerate(fixtures, 1):
        add_fixture(fixture, fixture_id=i)

    # Add calc grid meshes
    print("\nAdding calc grids:")
    grid_objects = []
    for cg in calc_grids:
        obj, bake_img = add_calc_grid(cg)
        grid_objects.append((cg, obj, bake_img))

    # Configure renderer
    configure_bake_render()

    # Bake all grids
    print("\nBaking calc grids...")
    baked = bake_calc_grids(grid_objects)

    # Extract illuminance from baked textures
    print("\nExtracting illuminance values...")
    all_results = []
    for calc_grid, bake_img in baked:
        result = extract_illuminance(calc_grid, bake_img)
        all_results.append((calc_grid, result))

        stats = result['stats']
        print(f"\n  {calc_grid.name}:")
        print(f"    Max: {stats['max_lux']:.1f} lux / {stats['max_fc']:.1f} fc")
        print(f"    Min: {stats['min_lux']:.1f} lux / {stats['min_fc']:.1f} fc")
        print(f"    Avg: {stats['avg_lux']:.1f} lux / {stats['avg_fc']:.1f} fc")
        print(f"    Uniformity (min/avg): {stats['uniformity_avg']:.2f}")

    # Write results
    write_results(all_results, rooms=rooms, fixtures=fixtures)
    write_results_json(all_results, rooms=rooms, fixtures=fixtures)

    # Phase 2: Falsecolor perspective render
    render_falsecolor_overlay(grid_objects, all_results, rooms=rooms)

    print("\nDone.")


if __name__ == '__main__':
    main()
