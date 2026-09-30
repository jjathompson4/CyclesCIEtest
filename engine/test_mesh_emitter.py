"""
Mesh Emitter Validation Test - Corrected IES on Mesh Light
==========================================================
Tests whether a mesh emitter with IES Texture + 1/cos(theta) correction
can reproduce the same illuminance as a validated SPOT light.

The hypothesis: AREA lights failed because Blender applies internal
eval_fac = 1/(area*4) normalization. Mesh emitters have NO such internal
normalization, so the community formula IES_Fac / (pi * cos(theta)) should
work correctly.

Shader graph:
    Geometry.Incoming --> IES Texture (Vector) --> Fac
    Geometry.Normal dot Geometry.Incoming --> max(0.087) --> 1/x --> cos_correction
    Fac * cos_correction * calibration_K --> Emission Strength

Run with:
    blender --background --python test_mesh_emitter.py

Output:
    mesh_emitter_results.txt  - comparison grid
    mesh_render.exr           - raw linear render
"""

import bpy
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_config import *

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Test parameters ──
MESH_SIZE_INCHES = 1.0          # default square side (overridden for rect tests)
MESH_LENGTH_FT = 3.917          # luminaire length (X) in feet — BioPro length
MESH_WIDTH_INCHES = 1.0         # luminaire width (Y) in inches (narrow line source)
MESH_POSITION_FT = (0.0, 0.0, 9.5)  # same as SPOT baseline
COS_CLAMP = 0.087               # ~85 degrees max emission angle
IES_PATH = IES_BIOPRO_DIRECT


# ─────────────────────────────────────────────
# SCENE SETUP (reused from validate_lux.py)
# ─────────────────────────────────────────────

def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for material in bpy.data.materials:
        bpy.data.materials.remove(material)


def make_diffuse_material(name, reflectance):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (reflectance, reflectance, reflectance, 1.0)
    bsdf.inputs['Roughness'].default_value  = 1.0
    bsdf.inputs['Metallic'].default_value   = 0.0
    bsdf.inputs['Specular IOR Level'].default_value = 0.0
    output = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat


def build_room():
    hw = ROOM_WIDTH  / 2
    hd = ROOM_DEPTH  / 2
    h  = ROOM_HEIGHT

    mat_ceiling = make_diffuse_material('Ceiling', REFLECTANCE_CEILING)
    mat_walls   = make_diffuse_material('Walls',   REFLECTANCE_WALLS)
    mat_floor   = make_diffuse_material('Floor',   REFLECTANCE_FLOOR)

    def add_plane(name, verts, mat, flip=True):
        mesh = bpy.data.meshes.new(name)
        obj  = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        mesh.from_pydata(verts, [], [(0,1,2,3)])
        mesh.update()
        mesh.materials.append(mat)
        if flip:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.flip_normals()
            bpy.ops.object.mode_set(mode='OBJECT')

    add_plane('Floor', [
        (-hw, -hd, 0), (hw, -hd, 0), (hw, hd, 0), (-hw, hd, 0)
    ], mat_floor, flip=False)
    add_plane('Ceiling', [
        (-hw, -hd, h), (hw, -hd, h), (hw, hd, h), (-hw, hd, h)
    ], mat_ceiling)
    add_plane('Wall_South', [
        (-hw, -hd, 0), (hw, -hd, 0), (hw, -hd, h), (-hw, -hd, h)
    ], mat_walls)
    add_plane('Wall_North', [
        (-hw,  hd, 0), (hw,  hd, 0), (hw,  hd, h), (-hw,  hd, h)
    ], mat_walls)
    add_plane('Wall_West', [
        (-hw, -hd, 0), (-hw,  hd, 0), (-hw,  hd, h), (-hw, -hd, h)
    ], mat_walls)
    add_plane('Wall_East', [
        ( hw, -hd, 0), ( hw,  hd, 0), ( hw,  hd, h), ( hw, -hd, h)
    ], mat_walls)


def add_workplane_mesh():
    hw = ROOM_WIDTH / 2
    hd = ROOM_DEPTH / 2
    mesh = bpy.data.meshes.new('Workplane')
    obj  = bpy.data.objects.new('Workplane', mesh)
    bpy.context.collection.objects.link(obj)
    mesh.from_pydata([
        (-hw, -hd, WORKPLANE_HEIGHT), ( hw, -hd, WORKPLANE_HEIGHT),
        ( hw,  hd, WORKPLANE_HEIGHT), (-hw,  hd, WORKPLANE_HEIGHT),
    ], [], [(0, 1, 2, 3)])
    mesh.update()

    mat   = bpy.data.materials.new(name='Workplane')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    lp    = nodes.new('ShaderNodeLightPath')
    diff  = nodes.new('ShaderNodeBsdfDiffuse')
    diff.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
    trans = nodes.new('ShaderNodeBsdfTransparent')
    mix   = nodes.new('ShaderNodeMixShader')
    out   = nodes.new('ShaderNodeOutputMaterial')
    links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
    links.new(trans.outputs['BSDF'],       mix.inputs[1])
    links.new(diff.outputs['BSDF'],        mix.inputs[2])
    links.new(mix.outputs['Shader'],       out.inputs['Surface'])
    mesh.materials.append(mat)


def add_measurement_camera():
    bpy.ops.object.camera_add(location=(0, 0, ROOM_HEIGHT - 0.01))
    cam_obj  = bpy.context.active_object
    cam_data = cam_obj.data
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = max(ROOM_WIDTH, ROOM_DEPTH)
    cam_obj.rotation_euler = (0, 0, 0)
    bpy.context.scene.camera = cam_obj
    return cam_obj


# ─────────────────────────────────────────────
# MESH EMITTER WITH CORRECTED IES SHADER
# ─────────────────────────────────────────────

def add_mesh_emitter(ies_path, position_ft, calibration_K,
                     length_ft=0.0, width_inches=0.0, size_inches=1.0):
    """Create a mesh plane with IES + 1/cos(theta) corrected emission.

    Shader graph:
        Geometry.Incoming --> IES Texture --> Fac
        dot(Normal, Incoming) --> max(COS_CLAMP) --> 1/x --> cos_correction
        Fac * calibration_K / cos_theta --> Emission Strength

    Args:
        ies_path: path to IES file
        position_ft: (x, y, z) in feet
        calibration_K: emission scaling constant (1/(4*area_m2))
        length_ft: fixture length along X in feet (0 = use size_inches for square)
        width_inches: fixture width along Y in inches (0 = use size_inches)
        size_inches: fallback square size in inches (used if length_ft=0)
    """
    pos = tuple(v * FT_TO_M for v in position_ft)

    # Compute mesh dimensions
    if length_ft > 0:
        half_x = (length_ft * FT_TO_M) / 2.0
        half_y = (width_inches * IN_TO_M) / 2.0 if width_inches > 0 else (size_inches * IN_TO_M) / 2.0
        mesh_area = (length_ft * FT_TO_M) * (2 * half_y)
    else:
        half_x = (size_inches * IN_TO_M) / 2.0
        half_y = half_x
        mesh_area = (size_inches * IN_TO_M) ** 2

    # Create mesh plane facing downward
    mesh = bpy.data.meshes.new('MeshEmitter')
    obj  = bpy.data.objects.new('MeshEmitter', mesh)
    bpy.context.collection.objects.link(obj)

    z = pos[2]
    cx, cy = pos[0], pos[1]
    mesh.from_pydata([
        (cx - half_x, cy - half_y, z),
        (cx + half_x, cy - half_y, z),
        (cx + half_x, cy + half_y, z),
        (cx - half_x, cy + half_y, z),
    ], [], [(0, 1, 2, 3)])
    mesh.update()

    # Flip normals to face downward (-Z)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.flip_normals()
    bpy.ops.object.mode_set(mode='OBJECT')

    # ── Build corrected IES emission shader ──
    mat = bpy.data.materials.new(name='MeshEmitter_IES')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 1. Geometry node for Normal and Incoming vectors
    geo = nodes.new('ShaderNodeNewGeometry')

    # 2. IES Texture with Incoming vector (critical: NOT default Normal)
    ies = nodes.new('ShaderNodeTexIES')
    ies.mode = 'EXTERNAL'
    ies.filepath = ies_path
    links.new(geo.outputs['Incoming'], ies.inputs['Vector'])

    # 3. Compute cos(theta) = dot(Normal, Incoming)
    dot = nodes.new('ShaderNodeVectorMath')
    dot.operation = 'DOT_PRODUCT'
    links.new(geo.outputs['Normal'],   dot.inputs[0])
    links.new(geo.outputs['Incoming'], dot.inputs[1])

    # 4. Clamp cos(theta) to prevent division by zero at grazing angles
    clamp = nodes.new('ShaderNodeMath')
    clamp.operation = 'MAXIMUM'
    clamp.inputs[1].default_value = COS_CLAMP
    links.new(dot.outputs['Value'], clamp.inputs[0])

    # 5. Compute 1/cos(theta) - the correction factor
    inv_cos = nodes.new('ShaderNodeMath')
    inv_cos.operation = 'DIVIDE'
    inv_cos.inputs[0].default_value = 1.0
    links.new(clamp.outputs['Value'], inv_cos.inputs[1])

    # 6. Multiply IES Fac by 1/cos(theta)
    fac_corrected = nodes.new('ShaderNodeMath')
    fac_corrected.operation = 'MULTIPLY'
    links.new(ies.outputs['Factor'],    fac_corrected.inputs[0])
    links.new(inv_cos.outputs['Value'], fac_corrected.inputs[1])

    # 7. Multiply by calibration constant K
    cal = nodes.new('ShaderNodeMath')
    cal.operation = 'MULTIPLY'
    cal.inputs[1].default_value = calibration_K
    links.new(fac_corrected.outputs['Value'], cal.inputs[0])

    # 8. Emission shader
    emission = nodes.new('ShaderNodeEmission')
    links.new(cal.outputs['Value'], emission.inputs['Strength'])

    # 9. Output
    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(emission.outputs['Emission'], output.inputs['Surface'])

    mesh.materials.append(mat)

    dims = f"{length_ft*12:.0f}\" x {width_inches:.0f}\"" if length_ft > 0 else f"{size_inches}\" x {size_inches}\""
    print(f"  Mesh emitter created: {dims} = {mesh_area*1e4:.2f} cm^2 ({mesh_area:.6f} m^2)")
    print(f"  Position: ({position_ft[0]:.1f}, {position_ft[1]:.1f}, {position_ft[2]:.1f}) ft")
    print(f"  Calibration K = {calibration_K:.6f}")
    print(f"  cos(theta) clamp = {COS_CLAMP}")
    print(f"  IES: {os.path.basename(ies_path)}")

    return obj


# ─────────────────────────────────────────────
# RENDER CONFIGURATION
# ─────────────────────────────────────────────

def configure_render(output_name='mesh_render.exr'):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    cycles = scene.cycles

    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.refresh_devices()
    has_gpu = False
    for device in prefs.devices:
        if device.type in ('CUDA', 'OPTIX', 'METAL', 'HIP'):
            device.use = True
            has_gpu = True
    if has_gpu:
        cycles.device = 'GPU'
        print("GPU rendering enabled")
    else:
        cycles.device = 'CPU'

    cycles.samples = RENDER_SAMPLES
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.sequencer_colorspace_settings.name = 'Linear Rec.709'
    cycles.film_exposure = 1.0
    cycles.use_denoising = False
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 0.0

    # Direct-only (MAX_BOUNCES=0 from fixture_config)
    cycles.max_bounces          = 0
    cycles.diffuse_bounces      = 0
    cycles.glossy_bounces       = 0
    cycles.transmission_bounces = 0
    print("  max_bounces = 0 (direct-only mode)")

    view_layer = scene.view_layers[0]
    view_layer.use_pass_diffuse_color  = True
    view_layer.use_pass_combined       = True
    view_layer.use_pass_emit           = True

    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_depth = '32'
    scene.render.filepath = os.path.join(OUTPUT_DIR, output_name)
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512


# ─────────────────────────────────────────────
# LUX EXTRACTION
# ─────────────────────────────────────────────

def extract_lux_grid(exr_name='mesh_render.exr'):
    LUMINOUS_EFFICACY = 179.0

    exr_path = os.path.join(OUTPUT_DIR, exr_name)
    if not os.path.exists(exr_path):
        print(f"ERROR: {exr_path} not found.")
        return None

    for cached in list(bpy.data.images):
        if cached.filepath == exr_path or exr_name.replace('.exr','') in cached.name:
            bpy.data.images.remove(cached)
    img = bpy.data.images.load(exr_path)
    img.colorspace_settings.name = 'Non-Color'
    pixels = list(img.pixels)
    width  = img.size[0]
    height = img.size[1]
    channels = img.channels

    def sample_pixel(u, v):
        px = int(u * (width  - 1))
        py = int(v * (height - 1))
        idx = (py * width + px) * channels
        return pixels[idx], pixels[idx+1], pixels[idx+2]

    def rgb_to_luminance(r, g, b):
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

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
    for y_val in reversed(y_points):
        row = []
        for x_val in x_points:
            u = (x_val + hw) / ROOM_WIDTH
            v = (y_val + hd) / ROOM_DEPTH
            r, g, b = sample_pixel(u, v)
            luminance_Wm2 = rgb_to_luminance(r, g, b)
            lux = luminance_Wm2 * LUMINOUS_EFFICACY
            row.append(lux)
        grid.append(row)

    return grid, x_points, y_points


# ─────────────────────────────────────────────
# MULTI-K SWEEP: Test several calibration values
# ─────────────────────────────────────────────

def main():
    print("\n" + "="*70)
    print("MESH EMITTER VALIDATION TEST")
    print("="*70)

    # Compute mesh area based on configured dimensions
    if MESH_LENGTH_FT > 0:
        w_m = MESH_WIDTH_INCHES * IN_TO_M if MESH_WIDTH_INCHES > 0 else MESH_SIZE_INCHES * IN_TO_M
        mesh_area_m2 = MESH_LENGTH_FT * FT_TO_M * w_m
        dims_str = f"{MESH_LENGTH_FT*12:.0f}\" x {MESH_WIDTH_INCHES:.0f}\""
    else:
        mesh_area_m2 = (MESH_SIZE_INCHES * IN_TO_M) ** 2
        dims_str = f"{MESH_SIZE_INCHES}\" x {MESH_SIZE_INCHES}\""

    # Derived from probe: K = 1 / (4 * mesh_area_m2)
    # This makes intensity area-independent: I(theta) = IES_Fac * K * A = IES_Fac / 4
    K_test = 1.0 / (4.0 * mesh_area_m2)

    print(f"\nMesh: {dims_str} ({mesh_area_m2:.6f} m^2)")
    print(f"Position: {MESH_POSITION_FT}")
    print(f"IES: {os.path.basename(IES_PATH)}")
    print(f"Testing K = {K_test}")
    print()

    clear_scene()
    build_room()
    add_mesh_emitter(IES_PATH, MESH_POSITION_FT, K_test,
                     length_ft=MESH_LENGTH_FT, width_inches=MESH_WIDTH_INCHES,
                     size_inches=MESH_SIZE_INCHES)
    configure_render('mesh_render.exr')
    add_workplane_mesh()
    add_measurement_camera()

    print("\nRendering mesh emitter (K={:.4f})...\n".format(K_test))
    bpy.ops.render.render(write_still=True)

    print("\nExtracting lux values...\n")
    result = extract_lux_grid('mesh_render.exr')
    if not result:
        print("ERROR: Lux extraction failed.")
        return

    grid, x_points, y_points = result
    all_values = [v for row in grid for v in row]
    lux_max = max(all_values)
    lux_min = min(all_values)
    lux_avg = sum(all_values) / len(all_values)

    # Get center value (grid center point)
    mid_row = len(grid) // 2
    mid_col = len(grid[0]) // 2
    lux_center = grid[mid_row][mid_col]

    print("="*70)
    print(f"MESH EMITTER RESULTS (K = {K_test})")
    print("="*70)
    print(f"  Center:  {lux_center:.2f} lux  /  {lux_center * LUX_TO_FC:.2f} fc")
    print(f"  Max:     {lux_max:.2f} lux  /  {lux_max * LUX_TO_FC:.2f} fc")
    print(f"  Min:     {lux_min:.2f} lux  /  {lux_min * LUX_TO_FC:.2f} fc")
    print(f"  Avg:     {lux_avg:.2f} lux  /  {lux_avg * LUX_TO_FC:.2f} fc")
    print()

    # Compare against known SPOT baseline
    # From previous validation: single BioPro SPOT at (0,0,9.5ft), MAX_BOUNCES=0
    # Baseline values will be read from lux_results.txt if available
    spot_baseline_path = os.path.join(OUTPUT_DIR, 'lux_results.txt')
    spot_center = None
    if os.path.exists(spot_baseline_path):
        # Parse max lux from baseline
        with open(spot_baseline_path, 'r') as f:
            for line in f:
                if 'Maximum:' in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == 'lux':
                            spot_center = float(parts[i-1])
                            break
                    break

    if spot_center:
        ratio = spot_center / lux_max if lux_max > 0 else float('inf')
        print(f"  SPOT baseline max: {spot_center:.2f} lux")
        print(f"  Ratio (SPOT/Mesh): {ratio:.4f}")
        print(f"  => Corrected K = {K_test * ratio:.6f}")
        print()
        print(f"  To match SPOT baseline, use K = {K_test * ratio:.6f}")
    else:
        print("  No SPOT baseline found in lux_results.txt")
        print("  Run validate_lux.py with single SPOT first to establish baseline.")

    # Write detailed results
    out_path = os.path.join(OUTPUT_DIR, 'mesh_emitter_results.txt')
    x_ft = [x * M_TO_FT for x in x_points]
    y_ft = [y * M_TO_FT for y in y_points]

    with open(out_path, 'w') as f:
        f.write("="*70 + "\n")
        f.write("MESH EMITTER VALIDATION TEST\n")
        f.write("="*70 + "\n\n")
        f.write(f"Mesh:        {MESH_SIZE_INCHES}\" x {MESH_SIZE_INCHES}\" "
                f"({mesh_area_m2:.6f} m^2)\n")
        f.write(f"Position:    ({MESH_POSITION_FT[0]:.1f}, {MESH_POSITION_FT[1]:.1f}, "
                f"{MESH_POSITION_FT[2]:.1f}) ft\n")
        f.write(f"IES:         {os.path.basename(IES_PATH)}\n")
        f.write(f"K:           {K_test}\n")
        f.write(f"cos clamp:   {COS_CLAMP}\n")
        f.write(f"Bounces:     0 (direct-only)\n")
        f.write(f"Samples:     {RENDER_SAMPLES}\n\n")

        f.write("-"*70 + "\n")
        f.write("SUMMARY\n")
        f.write("-"*70 + "\n")
        f.write(f"  Center:    {lux_center:8.2f} lux  /  {lux_center*LUX_TO_FC:6.2f} fc\n")
        f.write(f"  Maximum:   {lux_max:8.2f} lux  /  {lux_max*LUX_TO_FC:6.2f} fc\n")
        f.write(f"  Minimum:   {lux_min:8.2f} lux  /  {lux_min*LUX_TO_FC:6.2f} fc\n")
        f.write(f"  Average:   {lux_avg:8.2f} lux  /  {lux_avg*LUX_TO_FC:6.2f} fc\n\n")

        if spot_center:
            ratio = spot_center / lux_max if lux_max > 0 else float('inf')
            f.write(f"  SPOT baseline max: {spot_center:.2f} lux\n")
            f.write(f"  Ratio (SPOT/Mesh): {ratio:.6f}\n")
            f.write(f"  Corrected K:       {K_test * ratio:.6f}\n\n")

        f.write("-"*70 + "\n")
        f.write("POINT GRID (fc)\n")
        f.write("-"*70 + "\n\n")

        header = "  Y\\X  " + "".join(f" {xf:+6.1f}" for xf in x_ft)
        f.write(header + "\n")
        for i, row in enumerate(grid):
            yf = y_ft[len(y_ft) - 1 - i]
            fc_vals = [v * LUX_TO_FC for v in row]
            line = f"{yf:+6.1f} " + "".join(f" {v:6.2f}" for v in fc_vals)
            f.write(line + "\n")

    print(f"\nResults written to: {out_path}")
    print("\nDone.")


if __name__ == '__main__':
    main()
