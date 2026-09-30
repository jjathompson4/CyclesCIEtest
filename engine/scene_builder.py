"""
Shared Blender scene construction for PBR lighting simulation.

Provides functions for building rooms, fixtures, cameras, and workplanes.
Every fixture uses a corrected mesh emitter with IES angular distribution.

The corrected IES mesh emitter formula:
    Emission Strength = IES_Fac / (4 * A * cos(theta))

    where:
        IES_Fac  = IES Texture node output (Vector = Geometry.Incoming)
        A        = mesh area in m^2
        cos(theta) = dot(Normal, Incoming), clamped to fixture.cos_clamp
        K        = 1 / (4 * A)  (calibration constant)

This produces area-independent intensity: I(theta) = IES_Fac / 4,
matching Blender's SPOT light with pi correction to 99.9% accuracy.

Used by:
    validate_lux.py       (orthographic lux measurement)
    render_perspective.py  (perspective visual rendering)
"""

import bpy
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_config import *


# ─────────────────────────────────────────────
# SCENE SETUP
# ─────────────────────────────────────────────

def clear_scene():
    """Remove all objects and materials from the scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for material in bpy.data.materials:
        bpy.data.materials.remove(material)


def make_diffuse_material(name, reflectance):
    """Create a physically accurate diffuse material at exact reflectance value."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()

    # Principled BSDF with roughness=1 and metallic=0 = pure diffuse
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (reflectance, reflectance, reflectance, 1.0)
    bsdf.inputs['Roughness'].default_value  = 1.0
    bsdf.inputs['Metallic'].default_value   = 0.0
    bsdf.inputs['Specular IOR Level'].default_value = 0.0  # no specular

    output = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat


def make_colored_material(name, color, roughness=1.0, metallic=0.0,
                          specular=0.0, coat_weight=0.0, coat_roughness=0.1):
    """Create a colored Principled BSDF material.

    Args:
        name:           material name
        color:          (R, G, B) tuple, 0.0-1.0 linear
        roughness:      surface roughness (0=mirror, 1=matte)
        metallic:       metallic weight (0=dielectric, 1=metal)
        specular:       Specular IOR Level
        coat_weight:    clearcoat weight (0=none, 1=full)
        coat_roughness: clearcoat roughness
    """
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (color[0], color[1], color[2], 1.0)
    bsdf.inputs['Roughness'].default_value  = roughness
    bsdf.inputs['Metallic'].default_value   = metallic
    bsdf.inputs['Specular IOR Level'].default_value = specular
    bsdf.inputs['Coat Weight'].default_value = coat_weight
    bsdf.inputs['Coat Roughness'].default_value = coat_roughness

    output = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat


def make_pbr_material(name, override):
    """Build a full PBR Principled BSDF material from a MaterialOverride dict.

    Supports texture maps (albedo, roughness, gloss, normal, opacity, emissive),
    glass (transmission + IOR + tint), metallic presets, and per-type defaults.

    Args:
        name:     Material name
        override: Dict with keys: reflectance, roughness, metallic, base_color,
                  albedo_map, roughness_map, gloss_map, normal_map, opacity_map,
                  emissive_map, transmission, ior, tint, specular, coat_weight,
                  sheen_weight, etc.
    """
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 300)
    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (400, 300)
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

    tex_x = -600  # X position for texture nodes

    # --- Base Color / Albedo ---
    albedo_map = override.get('albedo_map') or override.get('albedoMap')

    # Helper: determine base color for the shader.
    # For lighting analysis, reflectance is the authoritative value.
    # baseColor is only used as a tint when an albedo texture is present.
    def _base_color_linear():
        r = override.get('reflectance', 0.5)
        return (r, r, r, 1.0)

    def _base_color_for_texture():
        """Get baseColor as a tint multiplier for albedo textures (0-1 range)."""
        bc = override.get('base_color') or override.get('baseColor')
        if bc and len(bc) >= 3:
            if any(c > 1.0 for c in bc[:3]):
                return (bc[0] / 255.0, bc[1] / 255.0, bc[2] / 255.0, 1.0)
            return (bc[0], bc[1], bc[2], 1.0)
        return None

    # Helper: create a Box Mapping + Texture Coordinate node group for
    # world-space tiling at 1 tile per meter (used for library textures).
    is_library = override.get('_library', False)
    if is_library:
        print(f"  [make_pbr_material] Library material: {name}, using box projection")

    def _add_box_mapping(tex_node):
        """Wire a TexCoord(Generated) → tex_node for world-space UVs via Box projection.

        Uses 'Generated' coordinates instead of 'Object' so that the projection
        is stable regardless of the object's origin or local axis orientation.
        Box projection with blend avoids seams on thin/planar geometry like partitions.
        """
        if not is_library:
            return
        coord = nodes.new('ShaderNodeTexCoord')
        coord.location = (tex_x - 400, tex_node.location[1])
        links.new(coord.outputs['Object'], tex_node.inputs['Vector'])
        tex_node.projection = 'BOX'
        tex_node.projection_blend = 0.5

    if albedo_map and os.path.isfile(albedo_map):
        tex = nodes.new('ShaderNodeTexImage')
        tex.location = (tex_x, 400)
        try:
            tex.image = bpy.data.images.load(albedo_map)
            _add_box_mapping(tex)
            links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        except Exception as e:
            print(f"  Warning: Failed to load albedo map {albedo_map}: {e}")
            bsdf.inputs['Base Color'].default_value = _base_color_linear()
    else:
        bsdf.inputs['Base Color'].default_value = _base_color_linear()

    # --- Roughness (or invert Gloss) ---
    rough_map = override.get('roughness_map') or override.get('roughnessMap')
    gloss_map = override.get('gloss_map') or override.get('glossMap')

    if rough_map and os.path.isfile(rough_map):
        tex = nodes.new('ShaderNodeTexImage')
        tex.location = (tex_x, 100)
        try:
            tex.image = bpy.data.images.load(rough_map)
            tex.image.colorspace_settings.name = 'Non-Color'
            _add_box_mapping(tex)
            links.new(tex.outputs['Color'], bsdf.inputs['Roughness'])
        except Exception as e:
            print(f"  Warning: Failed to load roughness map {rough_map}: {e}")
            bsdf.inputs['Roughness'].default_value = override.get('roughness', 0.5)
    elif gloss_map and os.path.isfile(gloss_map):
        # Invert gloss to roughness: roughness = 1 - glossiness
        tex = nodes.new('ShaderNodeTexImage')
        tex.location = (tex_x, 100)
        try:
            tex.image = bpy.data.images.load(gloss_map)
            tex.image.colorspace_settings.name = 'Non-Color'
            _add_box_mapping(tex)
            invert = nodes.new('ShaderNodeInvert')
            invert.location = (tex_x + 300, 100)
            links.new(tex.outputs['Color'], invert.inputs['Color'])
            links.new(invert.outputs['Color'], bsdf.inputs['Roughness'])
        except Exception as e:
            print(f"  Warning: Failed to load gloss map {gloss_map}: {e}")
            bsdf.inputs['Roughness'].default_value = override.get('roughness', 0.5)
    else:
        bsdf.inputs['Roughness'].default_value = override.get('roughness', 0.5)

    # --- Metallic ---
    bsdf.inputs['Metallic'].default_value = override.get('metallic', 0.0)

    # --- Specular ---
    specular = override.get('specular')
    if specular is not None:
        bsdf.inputs['Specular IOR Level'].default_value = specular

    # --- Normal Map ---
    normal_map = override.get('normal_map') or override.get('normalMap')
    if normal_map and os.path.isfile(normal_map):
        tex = nodes.new('ShaderNodeTexImage')
        tex.location = (tex_x, -200)
        try:
            tex.image = bpy.data.images.load(normal_map)
            tex.image.colorspace_settings.name = 'Non-Color'
            _add_box_mapping(tex)
            nmap = nodes.new('ShaderNodeNormalMap')
            nmap.location = (tex_x + 300, -200)
            links.new(tex.outputs['Color'], nmap.inputs['Color'])
            links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
        except Exception as e:
            print(f"  Warning: Failed to load normal map {normal_map}: {e}")

    # --- Glass (Transmission + IOR + Tint) ---
    transmission = override.get('transmission')
    if transmission is not None and transmission > 0:
        bsdf.inputs['Transmission Weight'].default_value = transmission
        # Use IOR=1.0 for architectural thin glass to avoid volumetric
        # refraction distortion ("funhouse mirror" effect). The visual
        # difference from IOR 1.52 is negligible for window panes, and
        # IOR=1.0 prevents ray bending through the glass volume.
        bsdf.inputs['IOR'].default_value = 1.0
        # Apply tint via base color (override if tint specified)
        tint = override.get('tint')
        if tint and len(tint) >= 3:
            bsdf.inputs['Base Color'].default_value = (tint[0]/255.0, tint[1]/255.0, tint[2]/255.0, 1.0)

    # --- Opacity Map ---
    opacity_map = override.get('opacity_map') or override.get('opacityMap')
    if opacity_map and os.path.isfile(opacity_map):
        mat.blend_method = 'HASHED'  # For EEVEE preview compat
        tex = nodes.new('ShaderNodeTexImage')
        tex.location = (tex_x, -500)
        try:
            tex.image = bpy.data.images.load(opacity_map)
            tex.image.colorspace_settings.name = 'Non-Color'
            # Mix BSDF with Transparent based on opacity
            transparent = nodes.new('ShaderNodeBsdfTransparent')
            transparent.location = (0, 0)
            mix = nodes.new('ShaderNodeMixShader')
            mix.location = (200, 300)
            links.new(tex.outputs['Color'], mix.inputs['Fac'])
            links.new(transparent.outputs['BSDF'], mix.inputs[1])
            links.new(bsdf.outputs['BSDF'], mix.inputs[2])
            # Rewire output
            links.new(mix.outputs['Shader'], output.inputs['Surface'])
        except Exception as e:
            print(f"  Warning: Failed to load opacity map {opacity_map}: {e}")

    # --- Emissive Map ---
    emissive_map = override.get('emissive_map') or override.get('emissiveMap')
    if emissive_map and os.path.isfile(emissive_map):
        tex = nodes.new('ShaderNodeTexImage')
        tex.location = (tex_x, -800)
        try:
            tex.image = bpy.data.images.load(emissive_map)
            links.new(tex.outputs['Color'], bsdf.inputs['Emission Color'])
            bsdf.inputs['Emission Strength'].default_value = 1.0
        except Exception as e:
            print(f"  Warning: Failed to load emissive map {emissive_map}: {e}")

    # --- Coat (clearcoat for ceramic etc.) ---
    coat_weight = override.get('coat_weight') or override.get('coatWeight')
    if coat_weight:
        bsdf.inputs['Coat Weight'].default_value = coat_weight

    # --- Sheen (for fabric) ---
    sheen_weight = override.get('sheen_weight') or override.get('sheenWeight')
    if sheen_weight:
        bsdf.inputs['Sheen Weight'].default_value = sheen_weight

    return mat


def _make_surface_material(name, mat_spec):
    """Create a material from a specification dict or use achromatic reflectance.

    If mat_spec is a dict with 'color' key: creates colored material.
    If mat_spec is a float: creates achromatic diffuse at that reflectance.
    """
    if isinstance(mat_spec, dict):
        return make_colored_material(
            name,
            color=mat_spec.get('color', (0.5, 0.5, 0.5)),
            roughness=mat_spec.get('roughness', 1.0),
            metallic=mat_spec.get('metallic', 0.0),
            specular=mat_spec.get('specular', 0.0),
            coat_weight=mat_spec.get('coat_weight', 0.0),
            coat_roughness=mat_spec.get('coat_roughness', 0.1),
        )
    else:
        return make_diffuse_material(name, float(mat_spec))


def _add_plane(name, verts, mat, flip=True):
    """Create a single quad plane with the given vertices and material.

    Args:
        name:  object name
        verts: 4 vertices [(x,y,z), ...]
        mat:   Blender material
        flip:  flip normals (True for ceiling/walls facing inward)
    """
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


def build_room(materials=None):
    """Create a box room with separate faces for ceiling, walls, floor.

    Args:
        materials: optional dict mapping surface names to material specs.
            Keys: 'ceiling', 'floor', 'wall_north', 'wall_south',
                  'wall_east', 'wall_west'
            Values: either a float (achromatic reflectance) or a dict with
                    'color', 'roughness', 'metallic', 'specular', etc.
            If None: uses USE_COLORED_MATERIALS flag from fixture_config.
    """
    hw = ROOM_WIDTH  / 2
    hd = ROOM_DEPTH  / 2
    h  = ROOM_HEIGHT

    # Resolve material specs
    if materials is None:
        try:
            from fixture_config import USE_COLORED_MATERIALS, ROOM_MATERIALS
            if USE_COLORED_MATERIALS:
                materials = ROOM_MATERIALS
        except ImportError:
            pass

    if materials and isinstance(materials, dict):
        mat_ceiling    = _make_surface_material('Ceiling',    materials.get('ceiling', REFLECTANCE_CEILING))
        mat_floor      = _make_surface_material('Floor',      materials.get('floor', REFLECTANCE_FLOOR))
        mat_wall_south = _make_surface_material('Wall_South', materials.get('wall_south', materials.get('walls', REFLECTANCE_WALLS)))
        mat_wall_north = _make_surface_material('Wall_North', materials.get('wall_north', materials.get('walls', REFLECTANCE_WALLS)))
        mat_wall_west  = _make_surface_material('Wall_West',  materials.get('wall_west',  materials.get('walls', REFLECTANCE_WALLS)))
        mat_wall_east  = _make_surface_material('Wall_East',  materials.get('wall_east',  materials.get('walls', REFLECTANCE_WALLS)))
    else:
        mat_ceiling    = make_diffuse_material('Ceiling', REFLECTANCE_CEILING)
        mat_floor      = make_diffuse_material('Floor',   REFLECTANCE_FLOOR)
        mat_wall_south = make_diffuse_material('Walls',   REFLECTANCE_WALLS)
        mat_wall_north = mat_wall_south
        mat_wall_west  = mat_wall_south
        mat_wall_east  = mat_wall_south

    # Floor — natural normal is +Z (up into room)
    _add_plane('Floor', [
        (-hw, -hd, 0), (hw, -hd, 0), (hw, hd, 0), (-hw, hd, 0)
    ], mat_floor, flip=False)

    # Ceiling
    _add_plane('Ceiling', [
        (-hw, -hd, h), (hw, -hd, h), (hw, hd, h), (-hw, hd, h)
    ], mat_ceiling)

    # Walls — each can have its own material
    _add_plane('Wall_South', [
        (-hw, -hd, 0), (hw, -hd, 0), (hw, -hd, h), (-hw, -hd, h)
    ], mat_wall_south)
    _add_plane('Wall_North', [
        (-hw,  hd, 0), (hw,  hd, 0), (hw,  hd, h), (-hw,  hd, h)
    ], mat_wall_north)
    _add_plane('Wall_West', [
        (-hw, -hd, 0), (-hw,  hd, 0), (-hw,  hd, h), (-hw, -hd, h)
    ], mat_wall_west)
    _add_plane('Wall_East', [
        ( hw, -hd, 0), ( hw,  hd, 0), ( hw,  hd, h), ( hw, -hd, h)
    ], mat_wall_east)


def build_floor_plan(rooms):
    """Create a multi-room floor plan from a list of Room objects.

    Each room gets its own floor, ceiling, and 4 walls. Shared/overlapping
    walls are acceptable for lighting calculations (no double-counting issue
    since holdout grids only measure incoming light).

    Args:
        rooms: list of Room objects from fixture_config.py
    """
    for room in rooms:
        ox = room.origin_ft[0] * FT_TO_M
        oy = room.origin_ft[1] * FT_TO_M
        w  = room.width_ft * FT_TO_M
        d  = room.depth_ft * FT_TO_M
        h  = room.height_ft * FT_TO_M

        # Room corners in world space
        x0, x1 = ox, ox + w
        y0, y1 = oy, oy + d

        prefix = room.name.replace(' ', '_')
        refl = room.reflectances

        mat_ceiling = make_diffuse_material(f'{prefix}_Ceiling', refl.get('ceiling', 0.80))
        mat_floor   = make_diffuse_material(f'{prefix}_Floor',   refl.get('floor', 0.20))
        mat_walls   = make_diffuse_material(f'{prefix}_Walls',   refl.get('walls', 0.50))

        # Floor (normal +Z, no flip)
        _add_plane(f'{prefix}_Floor', [
            (x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)
        ], mat_floor, flip=False)

        # Ceiling (flip to face down)
        _add_plane(f'{prefix}_Ceiling', [
            (x0, y0, h), (x1, y0, h), (x1, y1, h), (x0, y1, h)
        ], mat_ceiling, flip=True)

        # South wall (Y = y0)
        _add_plane(f'{prefix}_Wall_South', [
            (x0, y0, 0), (x1, y0, 0), (x1, y0, h), (x0, y0, h)
        ], mat_walls, flip=True)

        # North wall (Y = y1)
        _add_plane(f'{prefix}_Wall_North', [
            (x0, y1, 0), (x1, y1, 0), (x1, y1, h), (x0, y1, h)
        ], mat_walls, flip=True)

        # West wall (X = x0)
        _add_plane(f'{prefix}_Wall_West', [
            (x0, y0, 0), (x0, y1, 0), (x0, y1, h), (x0, y0, h)
        ], mat_walls, flip=True)

        # East wall (X = x1)
        _add_plane(f'{prefix}_Wall_East', [
            (x1, y0, 0), (x1, y1, 0), (x1, y1, h), (x1, y0, h)
        ], mat_walls, flip=True)

        print(f"  Room '{room.name}': {room.width_ft:.0f}' x {room.depth_ft:.0f}' x {room.height_ft:.0f}'  "
              f"origin=({room.origin_ft[0]:.0f}, {room.origin_ft[1]:.0f})")


# ─────────────────────────────────────────────
# MESH EMITTER FIXTURE
# ─────────────────────────────────────────────

def add_fixture(fixture, fixture_id=1):
    """Add a mesh emitter fixture with corrected IES shader to the scene.

    Creates a rectangular mesh plane at the fixture position with downward-facing
    normals, and applies the corrected IES emission shader:

        Emission Strength = IES_Fac * K / cos(theta_emit)

    where K = 1/(4*A), A = mesh area in m^2, cos(theta) clamped to fixture.cos_clamp.

    This produces photometrically accurate illuminance validated to 99.9% against
    both SPOT lights (point source) and SPOT arrays (area source).

    Args:
        fixture: Fixture object from fixture_config.py
        fixture_id: numeric ID for unique naming (default: 1)

    Returns:
        The Blender mesh object.
    """
    pos = fixture.position  # meters
    half_x, half_y = fixture.mesh_half_dims_m
    mesh_area = fixture.mesh_area_m2
    lumen_scale = fixture.get_lumen_scale()
    K = lumen_scale / (4.0 * mesh_area)

    # Create mesh plane centered at LOCAL origin — this ensures rotation_euler
    # rotates around the fixture's own center, not the world origin.
    name = f'Fixture_{fixture_id}'
    mesh = bpy.data.meshes.new(name)
    obj  = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    mesh.from_pydata([
        (-half_x, -half_y, 0),
        (+half_x, -half_y, 0),
        (+half_x, +half_y, 0),
        (-half_x, +half_y, 0),
    ], [], [(0, 1, 2, 3)])
    mesh.update()

    # Flip normals to face downward (-Z into the room)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.flip_normals()
    bpy.ops.object.mode_set(mode='OBJECT')

    # Set position and rotation — rotation happens around local origin (fixture center)
    obj.location = pos
    obj.rotation_euler = fixture.rotation

    # ── Build corrected IES emission shader ──
    mat = bpy.data.materials.new(name=f'{name}_IES')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 1. Geometry node for Normal and Incoming vectors
    geo = nodes.new('ShaderNodeNewGeometry')

    # 2. IES Texture — CRITICAL: connect Incoming to Vector, not default Normal
    ies_path = fixture.ies_path
    ies = nodes.new('ShaderNodeTexIES')
    ies.mode = 'EXTERNAL'
    ies.filepath = ies_path

    # If fixture has rotation, rotate Incoming into the fixture's local space
    # so the IES angular distribution aims with the fixture.
    # Inverse of Euler XYZ (rx, ry, rz) = Rz(-rz) then Ry(-ry) then Rx(-rx).
    rx, ry, rz = fixture.rotation
    _has_rot = abs(rx) > 1e-6 or abs(ry) > 1e-6 or abs(rz) > 1e-6

    if _has_rot:
        ies_vec = geo.outputs['Incoming']
        for axis, angle in [('Z_AXIS', -rz), ('Y_AXIS', -ry), ('X_AXIS', -rx)]:
            if abs(angle) > 1e-6:
                rot_node = nodes.new('ShaderNodeVectorRotate')
                rot_node.rotation_type = axis
                rot_node.inputs['Angle'].default_value = angle
                links.new(ies_vec, rot_node.inputs['Vector'])
                ies_vec = rot_node.outputs['Vector']
        links.new(ies_vec, ies.inputs['Vector'])
    else:
        links.new(geo.outputs['Incoming'], ies.inputs['Vector'])

    # 3. Compute cos(theta) = dot(Normal, Incoming)
    dot = nodes.new('ShaderNodeVectorMath')
    dot.operation = 'DOT_PRODUCT'
    links.new(geo.outputs['Normal'],   dot.inputs[0])
    links.new(geo.outputs['Incoming'], dot.inputs[1])

    # 4. Clamp cos(theta) to prevent 1/cos divergence at grazing angles
    clamp = nodes.new('ShaderNodeMath')
    clamp.operation = 'MAXIMUM'
    clamp.inputs[1].default_value = fixture.cos_clamp
    links.new(dot.outputs['Value'], clamp.inputs[0])

    # 5. Compute 1/cos(theta) — the Lambertian correction factor
    inv_cos = nodes.new('ShaderNodeMath')
    inv_cos.operation = 'DIVIDE'
    inv_cos.inputs[0].default_value = 1.0
    links.new(clamp.outputs['Value'], inv_cos.inputs[1])

    # 6. Multiply IES_Fac by 1/cos(theta)
    fac_corrected = nodes.new('ShaderNodeMath')
    fac_corrected.operation = 'MULTIPLY'
    links.new(ies.outputs['Factor'],    fac_corrected.inputs[0])
    links.new(inv_cos.outputs['Value'], fac_corrected.inputs[1])

    # 7. Multiply by calibration constant K = 1/(4*A)
    cal = nodes.new('ShaderNodeMath')
    cal.operation = 'MULTIPLY'
    cal.inputs[1].default_value = K
    links.new(fac_corrected.outputs['Value'], cal.inputs[0])

    # 8. Emission shader
    emission = nodes.new('ShaderNodeEmission')
    links.new(cal.outputs['Value'], emission.inputs['Strength'])

    # 8b. Emission color — Blackbody (CCT) or RGB override
    if fixture.color_rgb is not None:
        rgb_node = nodes.new('ShaderNodeRGB')
        rgb_node.outputs['Color'].default_value = (
            fixture.color_rgb[0], fixture.color_rgb[1], fixture.color_rgb[2], 1.0
        )
        links.new(rgb_node.outputs['Color'], emission.inputs['Color'])
    elif fixture.color_temp_k > 0:
        bb_node = nodes.new('ShaderNodeBlackbody')
        bb_node.inputs['Temperature'].default_value = fixture.color_temp_k
        links.new(bb_node.outputs['Color'], emission.inputs['Color'])

    # 9. Material output
    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(emission.outputs['Emission'], output.inputs['Surface'])

    mesh.materials.append(mat)

    print(f"  Fixture {fixture_id}: {fixture}")
    print(f"    Mesh area: {mesh_area*1e4:.1f} cm^2 ({mesh_area:.6f} m^2)")
    print(f"    K = {K:.4f}, lumen_scale = {lumen_scale:.3f}, cos_clamp = {fixture.cos_clamp}")
    print(f"    IES: {os.path.basename(ies_path)}")

    return obj


# ─────────────────────────────────────────────
# WORKPLANE & CAMERAS
# ─────────────────────────────────────────────

def add_calc_grid(calc_grid):
    """Add a CalcGrid measurement surface for Cycles texture baking.

    Creates an invisible holdout mesh that:
    - Bake rays (camera rays) see a white diffuse surface (rho=1)
    - All other rays see transparent (no effect on inter-reflections)
    - Has UV mapping for bake target texture
    - Has a bake target image assigned for Cycles baking

    Same holdout principle as the orthographic workplane, but positioned
    and oriented according to the CalcGrid config, with UV + bake image
    for texture baking instead of camera rendering.

    Args:
        calc_grid: CalcGrid object from fixture_config.py

    Returns:
        tuple: (blender_object, bake_image)
    """
    import bmesh
    from mathutils import Vector, Euler
    import math as _m

    pos = calc_grid.position_m
    normal = calc_grid.normal
    w_m, h_m = calc_grid.mesh_dims_m
    res = calc_grid.bake_resolution
    has_boundary = calc_grid.boundary_ft is not None and len(calc_grid.boundary_ft) >= 3

    # Create mesh at local origin
    name = f'CalcGrid_{calc_grid.name}'
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    if has_boundary:
        # Polygon boundary — convert from local feet to local meters
        boundary_m = [(v[0] * FT_TO_M, v[1] * FT_TO_M) for v in calc_grid.boundary_ft]

        # Compute bounding box for UV mapping
        bx = [v[0] for v in boundary_m]
        by = [v[1] for v in boundary_m]
        bb_min_x, bb_max_x = min(bx), max(bx)
        bb_min_y, bb_max_y = min(by), max(by)
        bb_w = max(bb_max_x - bb_min_x, 1e-6)
        bb_h = max(bb_max_y - bb_min_y, 1e-6)

        # Create polygon mesh using bmesh for proper triangulation
        bm = bmesh.new()
        verts = [bm.verts.new((v[0], v[1], 0)) for v in boundary_m]
        bm.verts.ensure_lookup_table()
        face = bm.faces.new(verts)

        # UV layer — map to bounding box [0,1]
        uv_layer_bm = bm.loops.layers.uv.new('CalcGridUV')
        for loop in face.loops:
            co = loop.vert.co
            loop[uv_layer_bm].uv = (
                (co.x - bb_min_x) / bb_w,
                (co.y - bb_min_y) / bb_h,
            )

        # Triangulate for Blender bake
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        # Override w_m, h_m to bounding box for bake texture sizing
        w_m = bb_w
        h_m = bb_h
        print(f"    Polygon boundary: {len(calc_grid.boundary_ft)} vertices")
    else:
        # Original rectangular path
        hw = w_m / 2
        hh = h_m / 2
        mesh.from_pydata([
            (-hw, -hh, 0),
            (+hw, -hh, 0),
            (+hw, +hh, 0),
            (-hw, +hh, 0),
        ], [], [(0, 1, 2, 3)])
        mesh.update()

        # UV unwrap — planar projection normalized to 0-1
        uv_layer = mesh.uv_layers.new(name='CalcGridUV')
        uv_coords = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for i, loop in enumerate(mesh.loops):
            uv_layer.data[i].uv = uv_coords[i]

    # Orient the plane to match the target surface normal
    # Default plane normal is +Z; rotate to match requested normal
    nx, ny, nz = normal
    if abs(nz - 1.0) < 1e-6:
        # Floor: normal is +Z, no rotation needed
        pass
    elif abs(nz + 1.0) < 1e-6:
        # Ceiling: flip 180° around X
        obj.rotation_euler = (_m.pi, 0, 0)
    elif abs(ny - 1.0) < 1e-6:
        # Wall south (normal +Y): rotate -90° around X
        obj.rotation_euler = (-_m.pi / 2, 0, 0)
    elif abs(ny + 1.0) < 1e-6:
        # Wall north (normal -Y): rotate +90° around X
        obj.rotation_euler = (_m.pi / 2, 0, 0)
    elif abs(nx - 1.0) < 1e-6:
        # Wall west (normal +X): rotate +90° around Y
        obj.rotation_euler = (0, _m.pi / 2, 0)
    elif abs(nx + 1.0) < 1e-6:
        # Wall east (normal -X): rotate -90° around Y
        obj.rotation_euler = (0, -_m.pi / 2, 0)

    obj.location = pos

    # Create bake target image
    img_name = f'BakeTarget_{calc_grid.name}'
    # Remove existing image if present
    if img_name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[img_name])
    bake_img = bpy.data.images.new(img_name, width=res, height=res,
                                    alpha=False, float_buffer=True)
    bake_img.colorspace_settings.name = 'Non-Color'

    # Holdout material: camera rays → white diffuse (front face only), other rays → transparent
    # Same as workplane holdout, but with an Image Texture node for bake target.
    # Backface culling: the back face of the calc grid must be transparent so that
    # wall grids don't capture sky light leaking through from outside the room.
    # Without this, the two-sided Diffuse BSDF picks up illumination on both faces.
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    lp    = nodes.new('ShaderNodeLightPath')
    geom  = nodes.new('ShaderNodeNewGeometry')
    diff  = nodes.new('ShaderNodeBsdfDiffuse')
    diff.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
    trans = nodes.new('ShaderNodeBsdfTransparent')

    # Mix 1: camera ray → white diffuse, non-camera ray → transparent
    mix_cam = nodes.new('ShaderNodeMixShader')
    mix_cam.name = 'CameraRayMix'
    links.new(lp.outputs['Is Camera Ray'], mix_cam.inputs['Fac'])
    links.new(trans.outputs['BSDF'],       mix_cam.inputs[1])
    links.new(diff.outputs['BSDF'],        mix_cam.inputs[2])

    # Mix 2: front face → camera ray result, back face → always transparent
    # This prevents the calc grid from capturing light on its back side,
    # which would corrupt wall measurements (light leaking from outside the room).
    trans2 = nodes.new('ShaderNodeBsdfTransparent')
    mix_bf = nodes.new('ShaderNodeMixShader')
    mix_bf.name = 'BackfaceCull'
    links.new(geom.outputs['Backfacing'],    mix_bf.inputs['Fac'])
    links.new(mix_cam.outputs['Shader'],     mix_bf.inputs[1])  # front face
    links.new(trans2.outputs['BSDF'],        mix_bf.inputs[2])  # back face → transparent

    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(mix_bf.outputs['Shader'], out.inputs['Surface'])

    # Image Texture node — required for Cycles to know WHERE to bake.
    # Must be selected (active) at bake time. Not connected to anything.
    img_tex = nodes.new('ShaderNodeTexImage')
    img_tex.image = bake_img
    img_tex.select = True
    nodes.active = img_tex

    mesh.materials.append(mat)

    print(f"  CalcGrid '{calc_grid.name}': {calc_grid.surface}")
    print(f"    Position: ({pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}) m")
    print(f"    Mesh: {w_m:.3f} x {h_m:.3f} m")
    print(f"    Bake resolution: {res}x{res}")
    print(f"    Grid spacing: {calc_grid.spacing_ft:.1f}' ({calc_grid.spacing_ft * FT_TO_M:.3f} m)")

    return obj, bake_img


def add_workplane_mesh():
    """Add a measurement plane at workplane height.

    Camera rays see a white Lambertian surface (rho=1) so illuminance is
    recoverable as E = L * pi. All other rays (bounces, shadows) see
    transparent, so the plane does not participate in room inter-reflection
    and does not mask the floor or inflate lux readings.
    """
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

    # Fac=0 (non-camera ray) -> transparent; Fac=1 (camera ray) -> white diffuse
    links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
    links.new(trans.outputs['BSDF'],       mix.inputs[1])
    links.new(diff.outputs['BSDF'],        mix.inputs[2])
    links.new(mix.outputs['Shader'],       out.inputs['Surface'])

    mesh.materials.append(mat)


def add_measurement_camera():
    """Add orthographic top-down camera just below ceiling, looking down at workplane."""
    bpy.ops.object.camera_add(location=(0, 0, ROOM_HEIGHT - 0.01))
    cam_obj  = bpy.context.active_object
    cam_data = cam_obj.data

    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = max(ROOM_WIDTH, ROOM_DEPTH)

    # Point straight down
    cam_obj.rotation_euler = (0, 0, 0)

    bpy.context.scene.camera = cam_obj
    return cam_obj


def add_perspective_camera():
    """Add perspective camera at configured position, aimed at target.

    Uses Track To constraint for accurate aiming. Camera position, target,
    and FOV are configured in fixture_config.py.
    """
    pos = tuple(v * FT_TO_M for v in PERSP_CAM_POSITION_FT)
    target = tuple(v * FT_TO_M for v in PERSP_CAM_TARGET_FT)

    bpy.ops.object.camera_add(location=pos)
    cam_obj  = bpy.context.active_object
    cam_data = cam_obj.data

    cam_data.type = 'PERSP'
    cam_data.lens_unit = 'FOV'
    cam_data.angle = math.radians(PERSP_CAM_FOV)

    # Create an empty at the target for Track To
    bpy.ops.object.empty_add(location=target)
    target_obj = bpy.context.active_object
    target_obj.name = 'CameraTarget'

    # Add Track To constraint
    constraint = cam_obj.constraints.new(type='TRACK_TO')
    constraint.target = target_obj
    constraint.track_axis = 'TRACK_NEGATIVE_Z'
    constraint.up_axis = 'UP_Y'

    bpy.context.scene.camera = cam_obj
    return cam_obj


# ─────────────────────────────────────────────
# RENDER CONFIGURATION (shared base)
# ─────────────────────────────────────────────

def configure_cycles_base(scene):
    """Configure Cycles engine basics: GPU detection, render passes.

    Does NOT set view_transform, output format, samples, or bounces.
    Those are caller-specific (validate_lux vs render_perspective).
    """
    scene.render.engine = 'CYCLES'
    cycles = scene.cycles

    # GPU if available
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
        print("CPU rendering (no GPU detected)")

    # Calc grids are Transparent BSDF planes, and every pass through one
    # counts against transparent_max_bounces (Blender default 8). At that
    # default, paths bouncing between a gridded floor and the room are cut
    # short: CIE 5.8 read 12% low at rho 0.90 and 32% low at rho 0.95.
    cycles.transparent_max_bounces = 1024

    # Enable render passes
    view_layer = scene.view_layers[0]
    view_layer.use_pass_diffuse_color    = True
    view_layer.use_pass_combined         = True
    view_layer.use_pass_emit             = True
    view_layer.use_pass_diffuse_direct   = True   # DiffDir — for analysis irradiance
    view_layer.use_pass_diffuse_indirect = True   # DiffInd — for analysis irradiance


def parse_ies_peak_candela(ies_path):
    """Parse an IES file and return the raw peak candela (diagnostic only).

    NOTE: Not used for emission scaling — the K = 1/(4*A) formula handles
    calibration universally. Kept for diagnostic comparison.

    Returns peak candela (cd) without multiplier, or None if parsing fails.
    """
    try:
        with open(ies_path, 'r', errors='ignore') as f:
            text = f.read()

        tilt_match = re.search(r'TILT\s*=\s*\S+', text)
        if not tilt_match:
            return None
        token_text = text[tilt_match.end():]
        tokens = token_text.split()

        multiplier  = float(tokens[2])
        num_vert    = int(tokens[3])
        num_horiz   = int(tokens[4])

        cd_start = 10 + 3 + num_vert + num_horiz
        cd_count = num_vert * num_horiz
        candelas = [float(tokens[cd_start + i]) for i in range(cd_count)]
        peak_cd_raw = max(candelas)
        return peak_cd_raw
    except Exception as e:
        print(f"  IES parse warning: {e}")
        return None
