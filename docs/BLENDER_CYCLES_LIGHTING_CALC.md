# Physics-Based Lighting Calculations in Blender Cycles 5.0

> **Note for this repo:** written during development, before this code was extracted. The demo floor-plan numbers below came from manufacturer IES files (USAI B4RD, BioPro) that aren't redistributed here; the demo now uses a generic Lambertian distribution. The web viewer and the regression baselines this document mentions aren't included. The code lives in `engine/`.

A reference for extracting physically accurate illuminance (lux) values from Blender's Cycles renderer using IES photometric data. Developed and validated against analytical Lambert's cosine law calculations.

Tested with Blender 5.0.1 (Cycles) on macOS.

---

## Table of Contents

1. [The Equation Chain](#1-the-equation-chain)
2. [IES File Handling](#2-ies-file-handling)
3. [Light Setup](#3-light-setup)
4. [Material Setup](#4-material-setup)
5. [Render Settings](#5-render-settings)
6. [Camera Setup](#6-camera-setup)
7. [Lux Extraction from EXR](#7-lux-extraction-from-exr)
8. [Common Pitfalls](#8-common-pitfalls)
9. [Validation Method](#9-validation-method)
10. [Project Files & How to Run](#10-project-files--how-to-run)
11. [Unit Convention](#11-unit-convention)
12. [Multi-Fixture & Area Luminaire Support](#12-multi-fixture--area-luminaire-support)
13. [Decision Log](#13-decision-log)
14. [Known Limitations](#14-known-limitations)
15. [Future Work](#15-future-work)
16. [Verification Protocol](#16-verification-protocol)
17. [Quick Reference](#17-quick-reference)
18. [Corrected Mesh Emitter](#18-corrected-mesh-emitter)
19. [Perspective Rendering](#19-perspective-rendering)
20. [Falsecolor Visualization](#20-falsecolor-visualization)
21. [CalcGrid Bake System](#21-calcgrid-bake-system)
22. [Web Viewer & PDF Export](#22-web-viewer--pdf-export)

---

## 1. The Equation Chain

### Direct Illuminance (Lambert's Cosine Law)

For a point source with luminous intensity I (candela) at angle theta from nadir:

```
E = I(theta) * cos(theta) / d^2
```

Where:
- `E` = illuminance at the measurement point (lux = lm/m^2)
- `I(theta)` = luminous intensity in the direction of the point (candela, from IES data)
- `theta` = angle from the light's vertical axis (0 = straight down)
- `d` = distance from light to measurement point (meters)
- `cos(theta) = h / d` where h = vertical distance from light to measurement plane

### Radiometric vs. Photometric Units

| Photometric (human-weighted) | Radiometric (physical) | Conversion |
|------------------------------|----------------------|------------|
| Luminous intensity (cd = lm/sr) | Radiant intensity (W/sr) | cd = W/sr * K |
| Illuminance (lux = lm/m^2) | Irradiance (W/m^2) | lux = W/m^2 * K |
| Luminous flux (lm) | Radiant flux (W) | lm = W * K |

Where K = luminous efficacy:
- Maximum photopic: **179 lm/W** (used in our lux extraction)
- D65 standard illuminant: **177.83 lm/W** (used internally by Blender/Cycles)
- The 0.7% difference between these is negligible in practice

### How Cycles Converts Candela to Watts

Blender's IES texture node (`ShaderNodeTexIES`) applies this conversion internally:

```
stored_value = candela * multiplier * ballast_factor * (4 * pi / 177.83)
```

Source: `intern/cycles/util/ies.cpp` in the Blender source code.

The constant `4 * pi / 177.83 = 0.07066507...` converts photometric candela to radiometric watts (total power for an isotropic source with that intensity).

### The Critical Pi Correction Factor

Cycles' internal light normalization divides the IES-stored value by an additional pi when evaluating spot light emission. This means the Fac output from the IES node is effectively:

```
Fac = candela * multiplier / (efficacy * pi)
```

To restore correct W/sr, **multiply the Fac output by pi**:

```
Emission Strength = IES_Fac * pi
```

This produces the correct luminous intensity regardless of the IES file's peak candela value. This is the single most important calibration factor.

### Lux from EXR Pixels

For a Lambertian surface with reflectance rho receiving illuminance E:
- Cycles renders the exitance: `pixel = rho * E / efficacy`
- So: `E = pixel * efficacy / rho`

With a rho=1.0 workplane (holdout material):
```
lux = pixel_luminance * 179
```

With a real surface (e.g., floor at rho=0.20):
```
lux = pixel_luminance * 179 / rho
```

---

## 2. IES File Handling

### IESNA LM-63-2002 Format

After the `TILT=NONE` line, the numeric data is structured as:

```
tokens[0]   num_lamps        (integer, usually 1)
tokens[1]   lumens_per_lamp  (float, -1 = absolute photometry)
tokens[2]   multiplier       (float, scales all candela values)
tokens[3]   num_vert         (integer, number of vertical angles)
tokens[4]   num_horiz        (integer, number of horizontal planes)
tokens[5]   photometric_type (1=Type C, 2=Type B, 3=Type A)
tokens[6]   units_type       (1=feet, 2=meters)
tokens[7]   width            (float, luminous opening; negative = circular)
tokens[8]   length           (float, luminous opening)
tokens[9]   height           (float, luminous opening)
tokens[10]  ballast_factor   (float)
tokens[11]  future_use       (float, typically 1)
tokens[12]  input_watts      (float)
tokens[13 ... 13+num_vert-1]               vertical_angles[]
tokens[13+num_vert ... +num_horiz-1]       horizontal_angles[]
tokens[13+num_vert+num_horiz ... end]      candela[horiz][vert]
```

Vertical angles: 0 = nadir (straight down), 90 = horizontal, 180 = straight up.
Horizontal angles: azimuth. Symmetry conventions: 0-90 = quarter, 0-180 = half, 0-360 = full.

### How Blender's IES Node Works Internally

1. Reads all candela values from the IES file
2. Multiplies each by `multiplier * ballast_factor * (4*pi/177.83)`
3. Stores the result as a directional lookup table
4. For each ray, outputs the stored value as the `Factor` output
5. **Does NOT normalize to 0-1** -- the output is already in radiometric units

### Do Not Double-Count the Multiplier

Blender's IES node applies the IES file's multiplier field internally. If you also apply the multiplier in your own code (e.g., when parsing peak candela for scaling), you will get values that are `multiplier` times too high.

Example: A fixture with `multiplier = 1.5` and raw peak candela of 535 cd has an effective peak of 802.5 cd. Blender handles this automatically.

### Correct Node Tree Wiring

```
[Geometry: Incoming] --> [IES Texture: Vector]
[IES Texture: Factor] --> [Math Multiply: Value1]
[pi (3.14159)]        --> [Math Multiply: Value2]
[Math Multiply: Value] --> [Emission: Strength]
```

The pi multiplier is the only scaling needed. No peak candela parsing required.

---

## 3. Light Setup

### Use SPOT, Not POINT

POINT lights in Blender are isotropic -- their node tree cannot apply per-ray directional distribution from IES data. SPOT lights correctly evaluate the IES distribution for each emission direction.

### Spot Light Configuration

```python
bpy.ops.object.light_add(type='SPOT', location=(0, 0, LIGHT_HEIGHT))
light_data = bpy.context.active_object.data

light_data.spot_size  = math.pi    # Full 180-degree hemisphere
light_data.spot_blend = 0.0        # No soft falloff at edge
light_data.use_nodes  = True
light_data.energy     = 1.0        # Node tree is sole energy control
```

### Why energy = 1.0

The default energy for a new SPOT light in Blender is 10W. When `use_nodes = True`, the energy value still acts as a multiplier on the node tree output. Setting it to 1.0 means the node tree has sole control over emission intensity. Forgetting this gives values 10x too high.

---

## 4. Material Setup

### Room Surface Materials

Pure Lambertian diffuse at known reflectance values:

```python
bsdf = nodes.new('ShaderNodeBsdfPrincipled')
bsdf.inputs['Base Color'].default_value = (rho, rho, rho, 1.0)  # achromatic
bsdf.inputs['Roughness'].default_value  = 1.0   # pure diffuse
bsdf.inputs['Metallic'].default_value   = 0.0   # non-metallic
bsdf.inputs['Specular IOR Level'].default_value = 0.0  # no specular
```

Standard architectural reflectance values:
- Ceiling: 80% (0.80)
- Walls: 50% (0.50)
- Floor: 20% (0.20)

### Workplane Holdout Material

The measurement workplane needs to be visible to the camera (for measurement) but invisible to light bounces (so it doesn't affect inter-reflections):

```python
# Light Path node decides visibility per ray type
lp    = nodes.new('ShaderNodeLightPath')
diff  = nodes.new('ShaderNodeBsdfDiffuse')
diff.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)  # perfect white
trans = nodes.new('ShaderNodeBsdfTransparent')
mix   = nodes.new('ShaderNodeMixShader')
out   = nodes.new('ShaderNodeOutputMaterial')

# Camera rays -> white diffuse (rho=1.0); all other rays -> transparent
links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
links.new(trans.outputs['BSDF'],       mix.inputs[1])  # Fac=0: transparent
links.new(diff.outputs['BSDF'],        mix.inputs[2])  # Fac=1: white diffuse
links.new(mix.outputs['Shader'],       out.inputs['Surface'])
```

With rho=1.0, the lux formula simplifies to `lux = pixel_luminance * 179` (no reflectance division).

### Floor Normal Direction

When building room geometry with `mesh.from_pydata()`, the floor's vertex winding order `(-3,-3,0), (3,-3,0), (3,3,0), (-3,3,0)` produces a natural normal of +Z (upward into the room). This is already correct. **Do NOT flip the floor normal** -- all other surfaces (ceiling, walls) need flipping because their natural normals point outward, but the floor's already points inward.

---

## 5. Render Settings

Every one of these settings is critical. Missing any of them will corrupt the linear radiometric values in the EXR output.

```python
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
cycles = scene.cycles

# Sampling
cycles.samples = 1024  # Higher = less noise, slower

# DISABLE ALL TONE MAPPING AND COLOR MANAGEMENT
scene.view_settings.view_transform = 'Raw'       # No filmic/ACES tone mapping
scene.view_settings.exposure       = 0.0          # No exposure compensation
scene.view_settings.gamma          = 1.0          # Linear gamma
scene.sequencer_colorspace_settings.name = 'Linear Rec.709'

# DISABLE ALL POST-PROCESSING
cycles.film_exposure         = 1.0    # No film exposure (default is 1.0)
cycles.use_denoising         = False  # Denoiser corrupts absolute values
cycles.sample_clamp_direct   = 0.0    # No clamping (0 = disabled)
cycles.sample_clamp_indirect = 0.0    # No clamping (0 = disabled)

# Render passes
view_layer = scene.view_layers[0]
view_layer.use_pass_diffuse_color = True
view_layer.use_pass_combined      = True
view_layer.use_pass_emit          = True

# Output format: 32-bit float EXR (no compression artifacts)
scene.render.image_settings.file_format = 'OPEN_EXR'
scene.render.image_settings.color_depth = '32'
scene.render.resolution_x = 512
scene.render.resolution_y = 512
```

### Why Each Setting Matters

| Setting | Wrong Default | Effect if Wrong |
|---------|--------------|-----------------|
| `view_transform` | 'Filmic' | S-curve tone mapping destroys linear values |
| `exposure` | 0.0 | Non-zero shifts all values by 2^exposure |
| `gamma` | 1.0 | Non-1.0 applies power curve |
| `film_exposure` | 1.0 | Multiplier on all pixel values |
| `use_denoising` | True (Blender 4+) | AI denoiser alters absolute values |
| `sample_clamp_direct` | 0.0 | Non-zero clips bright pixels |
| `sample_clamp_indirect` | 0.0 | Non-zero clips bounced light |

---

## 6. Camera Setup

Use an orthographic camera looking straight down to capture the measurement plane as a uniform grid:

```python
bpy.ops.object.camera_add(location=(0, 0, ROOM_HEIGHT - 0.01))
cam = bpy.context.active_object.data

cam.type        = 'ORTHO'
cam.ortho_scale = max(ROOM_WIDTH, ROOM_DEPTH)  # Cover entire room

# Point straight down (default orientation)
bpy.context.active_object.rotation_euler = (0, 0, 0)
bpy.context.scene.camera = bpy.context.active_object
```

The camera sits at z = 2.99m (just below the 3.0m ceiling) looking down. The orthographic projection means every pixel samples the same solid angle, avoiding perspective distortion.

### Pixel-to-Room Coordinate Mapping

```python
# Room coordinates (x, y) to image UV (0-1):
u = (x + ROOM_WIDTH/2)  / ROOM_WIDTH
v = (y + ROOM_DEPTH/2)  / ROOM_DEPTH

# UV to pixel index:
px = int(u * (width - 1))
py = int(v * (height - 1))
idx = (py * width + px) * channels
```

---

## 7. Lux Extraction from EXR

### Loading the EXR

```python
# Clear any cached version first
for cached in list(bpy.data.images):
    if 'lux_render' in cached.name:
        bpy.data.images.remove(cached)

img = bpy.data.images.load(exr_path)
img.colorspace_settings.name = 'Non-Color'  # Preserve raw linear values
pixels = list(img.pixels)
```

The `'Non-Color'` colorspace is essential -- any other setting applies a color transform that corrupts the radiometric values.

### RGB to Luminance

Convert linear RGB to luminance using ITU-R BT.709 coefficients:

```
luminance = 0.2126 * R + 0.7152 * G + 0.0722 * B
```

### Luminance to Lux

With rho=1.0 holdout workplane:
```
lux = luminance * 179.0
```

With a real surface of known reflectance rho:
```
lux = luminance * 179.0 / rho
```

Where 179.0 is the maximum photopic luminous efficacy (lm/W).

### Measurement Grid

Standard photometric measurement uses a 2-foot (0.6096m) grid with the first point offset by half a grid spacing from the wall:

```python
GRID_SPACING = 0.6096  # meters (2 feet)
x = -ROOM_WIDTH/2 + GRID_SPACING/2  # First point
# ... step by GRID_SPACING until reaching +ROOM_WIDTH/2
```

### Unit Conversions

```
Footcandles = Lux / 10.764
Lux = Footcandles * 10.764
```

---

## 8. Common Pitfalls

### 1. Default Light Energy = 10W

New SPOT lights in Blender default to 10W energy. With `use_nodes = True`, this multiplies the entire node tree output by 10. **Always set `light_data.energy = 1.0` after enabling nodes.**

### 2. IES Multiplier Double-Counting

Blender's IES node applies the IES file's multiplier field internally. If you also parse the multiplier from the IES file and use it in your scaling math, values will be `multiplier` times too high. Symptom: values exactly 1.5x (or whatever the multiplier is) too high.

### 3. The Pi Factor

Blender's Cycles renderer has an internal pi normalization in its light evaluation. If you try to scale the IES Fac output by `peak_candela / luminous_efficacy`, it will only work by coincidence when `peak_candela` happens to be close to `pi * 179 = 562`. The universal correction is simply to multiply by pi.

### 4. White Workplane Masking the Floor

A solid white (rho=1.0) workplane at z=0.8m blocks the floor below it from receiving light. Since the white plane reflects 5x more light than the 20% floor, it inflates illuminance values by acting as a secondary light source. Fix: use a Light Path holdout material (transparent to bounces, visible to camera only).

### 5. Floor Normal Flipped Wrong

When flipping all room surface normals "to face inward," the floor's natural normal (+Z) already faces into the room. Flipping it makes it point -Z (downward, wrong). Cycles auto-corrects for rendering via backface detection, but it's technically incorrect.

### 6. Tone Mapping Left Enabled

Blender defaults to 'Filmic' view transform, which applies an S-curve tone map designed for artistic rendering. This destroys the linear relationship between pixel values and physical radiometric quantities. Always set `view_transform = 'Raw'`.

### 7. Denoiser Altering Values

Blender 4+ enables the denoiser by default. While the denoised values are close to correct, the AI denoiser does not preserve exact radiometric values. For accurate lighting analysis, always disable it.

### 8. IES Node `mode` Must Be Set Before `filepath`

In Blender's Python API, the IES texture node defaults to `mode = 'INTERNAL'`. If you set `ies_node.filepath = '/path/to/file.ies'` before setting `ies_node.mode = 'EXTERNAL'`, the filepath gets cleared when the mode changes. Always set the mode first:

```python
ies_node = nodes.new('ShaderNodeTexIES')
ies_node.mode     = 'EXTERNAL'    # FIRST: set mode
ies_node.filepath = IES_FILE_PATH  # THEN: set path
```

### 9. Image Caching on EXR Load

`bpy.data.images.load()` may return a cached version of a previously loaded image with the same filename, even if the file on disk has changed (e.g., after a new render). Always clear cached images before loading:

```python
for cached in list(bpy.data.images):
    if 'lux_render' in cached.name:
        bpy.data.images.remove(cached)
img = bpy.data.images.load(exr_path)
```

Without this, you may read stale pixel data from a previous render.

---

## 9. Validation Method

### Analytical Direct Illuminance Calculator

A standalone Python script (`ies_direct_calc.py`) computes direct illuminance using Lambert's cosine law with no Blender dependency:

```python
# For each grid point (x, y) on the measurement plane:
dx, dy = x, y
horiz_dist = sqrt(dx^2 + dy^2)
d = sqrt(horiz_dist^2 + h^2)        # distance from light to point
cos_theta = h / d                     # Lambert's cosine factor
theta_deg = atan2(horiz_dist, h)      # angle from nadir
phi_deg = atan2(dy, dx) % 360        # azimuth

I = interpolate_candela(theta_deg, phi_deg)  # bilinear from IES data
E = I * cos_theta / (d * d)                  # direct illuminance (lux)
```

This gives the **direct-only** illuminance (no inter-reflections).

### Expected Inter-Reflection Contribution

Blender's full path tracing includes inter-reflections that the analytical calc does not. The expected additional contribution depends on beam width and room reflectances:

| Fixture Type | Direct-Only | With Inter-Reflections | Uplift |
|-------------|-------------|----------------------|--------|
| Single SPOT (BioPro) | 225.4 lux max | 239.9 lux max | +5.4% at peak |
| Single SPOT (B4RD) | 165.0 lux max | ~170 lux max | +3% at peak |
| 10-SPOT array (BioPro) | 227.6 lux max | 239.9 lux max | +5.4% at peak |
| Average across grid | varies | +19-25% avg | inter-reflections fill corners |

### Floor Plan Inter-Reflection Results (80/50/20 reflectances)

| Room | Direct-Only (avg fc) | With Bounces (avg fc) | Uplift | Uniformity Change |
|------|---------------------|----------------------|--------|-------------------|
| Corridor (30x6x9) | 22.3 | 27.2 | +22% | 0.92 → 0.90 |
| Meeting Room (20x14x9) | 64.7 | 80.6 | +25% | 0.49 → 0.57 |
| Private Office (10x14x9) | 55.5 | 63.8 | +15% | 0.64 → 0.69 |

The inter-reflection percentage is higher at grid points far from center (in corners) because direct light is weak but reflected light is relatively uniform. Corners can see >100% uplift vs direct-only.

Corridor sees high uplift despite narrow beam B4RD fixtures because the 6'-wide room puts walls close to the workplane. Office sees less uplift because narrow-beam B4RD downlights direct less light onto ceiling/walls.

### Validated Accuracy

With `max_bounces = 0` (Cycles direct-only mode), all tested configurations match the analytical calculation:

| Configuration | Blender Direct | Analytical | Match |
|--------------|---------------|------------|-------|
| Single SPOT, B4RD | 166.2 lux | 165.0 lux | 99.3% |
| Single SPOT, BioPro | (from prior tests) | (from prior tests) | 99.5-99.9% |
| 10-SPOT array, BioPro | 227.6 lux | 225.4 lux | 99.0% |
| Mixed (10-SPOT + B4RD) | 286.2 lux | 281.9 lux | 98.5% |

Inner zone accuracy (within ±5 ft of center): avg 2.5% error.
Edge/corner accuracy (±7-9 ft from center): avg 4.8% error (dominated by render noise at low fc values).

To run a direct-only test, set `MAX_BOUNCES = 0` in `fixture_config.py`:
```python
MAX_BOUNCES = 0  # direct-only for validation (None = Cycles default)
```

---

## 10. Project Files & How to Run

### File Inventory

```
engine/
  fixture_config.py        # Shared configuration: room, fixtures, units, IES paths, floor plan
  scene_builder.py         # Shared Blender scene construction + mesh emitter shader
  calc_grid_bake.py        # CalcGrid bake pipeline + extraction + JSON output + falsecolor
  plan_view_pdf.py         # Standalone PDF plan view generator (matplotlib)
  validate_lux.py          # Blender headless rendering + lux extraction
  render_perspective.py    # Blender perspective beauty/analysis rendering
  ies_direct_calc.py       # Standalone analytical direct illuminance calculator
  falsecolor.py            # Standalone falsecolor heatmap generator (no Blender)
  test_mesh_emitter.py     # Phase 0 mesh emitter validation reference
  cie171/                  # CIE 171:2006 test cases, runners, sky generator, synthetic IES
docs/
  BLENDER_CYCLES_LIGHTING_CALC.md  # This document
  CIE/                     # Validation status, notes, results JSON, R&D experiments
```

### fixture_config.py (Single Source of Truth)

All room geometry, material properties, render settings, fixture definitions, and camera configuration live here. All scripts import from this file via `from fixture_config import *`.

Key contents:
- **Room dimensions** in imperial: `ROOM_WIDTH_FT = 20.0`, etc.
- **Unit converters**: `ft()`, `inches()`, `FT_TO_M`, `LUX_TO_FC`
- **Fixture dataclass**: mesh-only with physical aperture dimensions
- **`make_luminaire()`**: factory for creating mesh emitter fixtures
- **`FIXTURES` list**: the active fixture configuration
- **`MAX_BOUNCES`**: `None` for full bounces, `0` for direct-only validation
- **Perspective camera config**: position, target, FOV, resolution

### scene_builder.py (Shared Scene Construction)

Extracted from validate_lux.py. Contains all Blender scene construction functions used by both validate_lux.py and render_perspective.py.

Key functions:
- `clear_scene()`, `build_room()`, `make_diffuse_material()`
- `add_fixture(fixture)` -- creates mesh emitter with corrected IES shader (see [§18](#18-corrected-mesh-emitter))
- `add_workplane_mesh()` -- Light Path holdout for lux measurement
- `add_measurement_camera()` -- orthographic top-down
- `add_perspective_camera()` -- perspective with Track To constraint
- `configure_cycles_base(scene)` -- GPU detection, engine, render passes

### validate_lux.py

Blender headless script that builds a test room, adds mesh emitter fixtures (from `FIXTURES` list), renders to EXR, and extracts illuminance values at grid points.

**Run:**
```bash
blender --background --python validate_lux.py
```

**Configuration:** Edit `fixture_config.py` to change room, fixtures, or render settings.

**Outputs:**
- `lux_results.txt` -- formatted grid with summary, fixture list, lux/fc values
- `lux_render.exr` -- 32-bit float EXR for falsecolor analysis

### render_perspective.py

Blender headless script for perspective view rendering. Uses the same room and mesh emitter fixtures but with a perspective camera for visual evaluation.

**Run:**
```bash
blender --background --python render_perspective.py
```

**Outputs:**
- `perspective_render.png` -- beauty render (Filmic tone mapping, denoised)
- `perspective_render.exr` -- analysis render (Raw, for falsecolor input)

Output format controlled by `PERSP_OUTPUT_FORMAT` in fixture_config.py.

### ies_direct_calc.py

Standalone Python script (no Blender dependency) that computes direct-only illuminance using Lambert's cosine law with bilinear IES candela interpolation. All fixtures are treated as area sources, discretized into sub-elements matching the mesh emitter approach.

**Run:**
```bash
python3 ies_direct_calc.py
```

**Outputs:** Printed direct illuminance grid to stdout (no inter-reflections). Values in both lux and footcandles.

### falsecolor.py

Standalone falsecolor heatmap generator. Reads EXR renders and produces color-mapped illuminance or luminance visualizations. No Blender dependency; requires numpy, matplotlib, OpenEXR.

**Run (using Blender's Python):**
```bash
/Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 falsecolor.py \
    lux_render.exr fc_illuminance.png --mode illuminance --contours 5 --room-grid
```

**Options:** `--mode illuminance|luminance`, `--max VALUE`, `--log`, `--cmap turbo|hot|viridis`, `--contours N`, `--room-grid`

---

## 11. Unit Convention

### Imperial User-Facing, SI Internal

All user-facing constants are in **imperial units** (feet/inches), while internal calculations use SI (meters) since Blender's API requires meters.

| Quantity | User-facing unit | Internal unit | Converter |
|----------|-----------------|--------------|-----------|
| Room dimensions | feet | meters | `ft(x)` = `x * 0.3048` |
| Fixture positions | feet | meters | `Fixture.position` property |
| Fixture dimensions | feet | meters | `Fixture.width` / `Fixture.height` properties |
| Small dimensions | inches | meters | `inches(x)` = `x * 0.0254` |
| Illuminance | lux AND footcandles | lux | `fc = lux / 10.764` |
| Luminous intensity | candela | candela | (no conversion needed) |

### Room Geometry

The test room uses clean imperial values: **20' x 20' x 10'** (6.096m x 6.096m x 3.048m).

Standard workplane height: **2.5' AFF** (0.762m) -- typical desk/task height.

Measurement grid: **2' spacing** (0.6096m) -- standard photometric grid per IES recommendations.

### Conversion Constants

```python
FT_TO_M  = 0.3048        # feet to meters
IN_TO_M  = 0.0254        # inches to meters
M_TO_FT  = 1 / 0.3048    # meters to feet
LUX_TO_FC = 1 / 10.764   # lux to footcandles
```

---

## 12. Multi-Fixture & Area Luminaire Support

### Mesh Emitter Architecture

Every fixture is a **mesh emitter** with realistic physical aperture dimensions. No point sources (SPOT/POINT lights) are used in the standard workflow. This ensures:

1. **Photometric accuracy** -- validated to 99.9% against analytical calculations
2. **Visually realistic** -- contiguous glowing area light shapes, not point dots
3. **Consistent methodology** -- one light type for both lux calculations and beauty renders

See [§18 Corrected Mesh Emitter](#18-corrected-mesh-emitter) for the technical formula and shader graph.

### Multiple Fixtures

The system supports any number of fixtures in a single scene. Define them in `fixture_config.py`:

```python
# Single linear luminaire:
FIXTURES = make_luminaire(
    ies_path=IES_BIOPRO_DIRECT,
    center_ft=(0.0, 0.0, 9.5),
    length_ft=3.917,
    width_inches=4.0,
)

# Single round downlight:
FIXTURES = make_luminaire(
    ies_path=IES_B4RD,
    center_ft=(0.0, 0.0, 9.5),
    width_inches=4.0,
)
```

### Mixed Fixture Scenes

Different fixture types can coexist using list concatenation:

```python
FIXTURES = make_luminaire(
    ies_path=IES_BIOPRO_DIRECT,
    center_ft=(0.0, 0.0, 9.5),
    length_ft=3.917,
) + make_luminaire(
    ies_path=IES_B4RD,
    center_ft=(5.0, 5.0, 9.5),
    width_inches=4.0,
)
```

### Fixture Dataclass

```python
@dataclass
class Fixture:
    ies_path: str                         # absolute path to .ies file
    position_ft: tuple                    # (x, y, z) center position in feet
    rotation: tuple = (0.0, 0.0, 0.0)    # Euler angles in radians
    length_ft: float = 0.0               # aperture length along X (feet); 0 = use width_inches
    width_inches: float = 4.0            # aperture width along Y (inches)
    cos_clamp: float = 0.087             # 1/cos clamp (~85 deg max emission angle)
    lumen_scale: float = 0.0             # 0 = auto from IES module length; >0 = manual override
    subdivisions_x: int = 10             # analytical calc discretization
    subdivisions_y: int = 10

    def get_lumen_scale(self):
        """Auto-compute scale = fixture_length / IES_module_length for multi-module linears."""
        if self.lumen_scale > 0: return self.lumen_scale
        if self.length_ft > 0:
            module_len = parse_ies_module_length(self.ies_path)
            if module_len > 0 and self.length_ft > module_len * 1.01:
                return self.length_ft / module_len
        return 1.0
```

Properties: `position` (meters), `mesh_area_m2`, `mesh_half_dims_m`, `mesh_dims_m`.

The `parse_ies_module_length()` utility reads IES line 7 tokens[7,8] (luminous opening width/length) and returns the larger dimension in feet. Cached via `@lru_cache`.

### Mesh Emitter Accuracy

Validated with BioPro 3.917' x 4" mesh emitter vs analytical (max_bounces=0):

| Metric | Blender Direct | Analytical | Match |
|--------|---------------|------------|-------|
| Max | 227.3 lux | 225.4 lux | 99.2% |
| Avg | 65.0 lux | 64.6 lux | 99.4% |

And vs the original 10-SPOT baseline: 227.3 vs 227.6 lux = **99.87% match**.

### Analytical Equivalence

The `compute_area_source_illuminance()` function in `ies_direct_calc.py` discretizes the luminaire rectangle into Nx x Ny sub-elements, matching the mesh emitter approach. Each sub-element acts as a fractional point source using Lambert's cosine law with IES interpolation.

---

## 13. Decision Log

How each key calibration discovery was made, so future developers don't have to re-derive them.

### The Pi Factor: Why `peak_cd / efficacy` Was Wrong

**Initial approach:** Scale the IES Fac output by `peak_cd / luminous_efficacy` (i.e., `peak_cd / 179`). This appeared to work for the B4RD downlight.

**The coincidence:** B4RD has `peak_raw = 535.1 cd` and `multiplier = 1.5`, giving `peak_effective = 802.5 cd`. The scaling factor was `802.5 / 179 = 4.48`. But the correct factor is `pi = 3.14`. For B4RD, `535.1 / 179 = 2.99 ≈ pi`, so the old formula produced nearly correct results (within 5%).

**How it broke:** When testing the BioPro linear fixture (`peak_raw = 1179.9`, `multiplier = 1.0`), Blender gave 314.2 lux vs. the analytical 140.3 lux -- a 2.24x discrepancy. The old scaling factor was `1179.9 / 179 = 6.59 ≈ 2*pi`, making everything 2x too high.

**Diagnostic steps:**
1. Set `max_bounces = 0` to eliminate inter-reflections -- BioPro was still 2.09x too high, proving the error was in calibration, not bounced light
2. "Raw Fac test" -- connected IES Fac directly to Emission Strength (no multiply node). Back-calculated Fac at nadir: BioPro = 2.01 (expected 1.0), B4RD = 1.43 (expected 1.5 due to multiplier)
3. Read Blender source code (`intern/cycles/util/ies.cpp`) -- confirmed the `4*pi/177.83` conversion factor with no peak normalization

**Resolution:** The IES node's Fac output is `cd * multiplier / (efficacy * pi)`. Multiplying by `pi` (not `peak_cd / efficacy`) universally restores correct W/sr for any IES file. Both fixtures then matched analytical calculations to 99.5-99.9%.

### Why SPOT Instead of POINT

POINT lights in Blender are isotropic emitters. Even with an IES node tree connected, the per-ray directional distribution from the IES data is not correctly evaluated because POINT lights don't have the angular evaluation path. SPOT lights do, and setting `spot_size = pi` opens the cone to a full hemisphere.

### Floor Normal Direction

All room surfaces were created with `mesh.from_pydata()` and then had `flip_normals()` applied to make normals face inward. The floor's vertex winding order `(-3,-3,0), (3,-3,0), (3,3,0), (-3,3,0)` produces a natural normal of +Z, which already faces into the room. Flipping it made it point -Z (downward), technically wrong even though Cycles' backface detection masks the error for rendering. The fix was to add a `flip` parameter to `add_plane()` and pass `flip=False` for the floor.

### Why SPOT Arrays, Not AREA Lights

**Goal:** Model area luminaires (like the 3.9-foot BioPro linear fixture) using Blender's AREA light type with IES.

**Blender's AREA light + IES normalization is fundamentally broken for photometry.** The internal `eval_fac = 1 / (area * 4)` scaling is area-dependent and direction-dependent, and there is no single correction factor that restores correct candela values.

**Diagnostic tests performed:**

1. **Raw Fac test** (AREA light, factor=1.0, max_bounces=0): Center pixel gave 281.2 lux vs 225.4 lux analytical (ratio 1.248).

2. **Point-by-point analysis**: The Blender/analytical ratio varied with angle -- 1.255 at center, 1.011 at 5 ft offset, 0.929 at 9 ft. When compensating for emission-angle cosine, the ratio C = ratio/cos(theta) ranged from 1.257 to 1.513 -- NOT a constant.

3. **Community formula** (`IES_Fac / (pi * dot(N, I))`): Result was 92.2 lux vs target 225.4 lux -- only 41% of expected. The pi in the denominator overcorrects.

**Root cause:** AREA lights in Cycles apply a Lambertian emission profile (cosine falloff) that's baked into their light evaluation. IES data already encodes the angular distribution, so applying an additional cosine creates double-counting at certain angles and incorrect ratios at others.

**Original solution (deprecated):** Model area luminaires as arrays of SPOT lights positioned across the fixture dimensions. Each SPOT carries `correction_factor = pi / N` where N is the total number of spots. This was validated but replaced by mesh emitters.

**Current solution:** Use corrected mesh emitters (see §18). Mesh emitters avoid AREA light normalization entirely AND provide visually realistic area light shapes for perspective rendering.

### Why Mesh Emitters, Not SPOT Arrays

**The SPOT array approach worked** -- validated to 99% accuracy for photometric calculations. However, it had fundamental limitations for visual rendering:

1. **No realistic aperture** -- SPOT arrays appear as grids of bright point dots in perspective views, not as contiguous luminaire shapes
2. **Inconsistent methodology** -- using point sources for a system meant to simulate real luminaires is architecturally incoherent
3. **Mesh emitters do both** -- a single mesh plane provides photometric accuracy AND visual realism

**The corrected mesh emitter formula** `Emission Strength = IES_Fac / (4 * A * cos(theta))` was discovered and validated:

| Test | Result |
|------|--------|
| 1" x 1" mesh vs single SPOT (point source) | **99.98% match** |
| 3.917' x 1" mesh vs 10-SPOT array (area source) | **99.9% match** |
| 3.917' x 4" mesh vs analytical | **99.2% match** |

The key insight: `K = 1/(4*A)` makes emission intensity area-independent, so `I(theta) = IES_Fac / 4` regardless of mesh size. This was confirmed both empirically and theoretically.

**Decision:** All fixtures now use mesh emitters exclusively. SPOT/POINT lights are not used in the standard workflow. The `make_spot_array()` function is kept for backward compatibility but marked as legacy.

---

## 14. Known Limitations

These are constraints of the current implementation, not fundamental limits of Cycles:

1. **Lambertian materials only** -- The lux extraction formula `E = pixel * efficacy / rho` assumes perfectly diffuse (Lambertian) surfaces. Specular, glossy, or anisotropic materials break this relationship because their BRDF is not constant.

2. **Monochromatic efficacy** -- A single luminous efficacy value (179 lm/W) is used for the entire spectrum. Real luminaires have spectral power distributions that may differ from the assumed D65 standard illuminant. The error is typically < 1% for white LEDs.

3. **Simple box room** -- The test room is an empty rectangular box. No furniture, partitions, desks, or complex geometry. Inter-reflection calculations are therefore only representative of unfurnished spaces.

4. **Flat measurement plane** -- The workplane is a flat horizontal surface at z = 2.5' AFF (0.762m). No curved or tilted task surfaces.

5. **cos(theta) clamp at grazing angles** -- The mesh emitter's 1/cos correction is clamped at cos(theta) = 0.087 (~85 degrees) to prevent divergence. Light emitted at angles >85 degrees from normal may be slightly underestimated. This affects corners at shallow angles but has negligible impact on workplane illuminance.

6. **Rectangular apertures only** -- Mesh emitters use rectangular planes. Round fixtures (like the B4RD downlight) are modeled as square apertures of equivalent dimension. This is accurate for photometry but slightly affects the visual appearance of round fixtures at close range.

---

## 15. Future Work

### Completed
- ~~Auto-parse luminaire dimensions from IES headers~~ -- Done: `parse_ies_module_length()` in fixture_config.py
- ~~Multi-room layouts~~ -- Done: floor plan mode with Room/CalcGrid dataclasses, calc_grid_bake.py
- ~~Interactive web viewer~~ -- Done: web/viewer.html with pan/zoom, 3 view modes, PDF export
- ~~Inter-reflection validation~~ -- Done: 15-25% uplift validated (Corridor +22%, Meeting +25%, Office +15%)
- ~~Automated regression testing~~ -- Done: test_regression.py + baselines.json (direct-only + bounces baselines)

### Remaining
- **Cross-validate floor plan against iray+** -- Meeting Room 80.6 fc (with bounces); compare room-by-room
- **Indirect fixture testing** -- Validate the uplight IES file (`BPRO2-LED35-SO-NW-SYM-ADC.ies`) where inter-reflections dominate
- **Add Selux L36 wall washer to floor plan** -- Test IES rotation + asymmetric distribution in real layout
- **AGi32 / commercial tool validation** -- Compare results against AGi32 or DIALux
- **Workplane/floor measurement toggle** -- Switch between rho=1.0 holdout and measuring off real floor surface
- **Parametric room geometry** -- Non-rectangular rooms, ceiling heights, wall offsets
- **Round aperture meshes** -- Circular mesh faces for round downlights instead of square approximation
- **Spectral rendering** -- Use Cycles spectral mode for more accurate efficacy weighting
- **Web viewer enhancements** -- Per-room click-to-zoom, fixture legend, light theme, configurable PDF

---

## 16. Verification Protocol

Step-by-step checklist for verifying that code changes haven't broken accuracy.

### After Any Code Change

1. **Set direct-only mode** in `fixture_config.py`:
   ```python
   MAX_BOUNCES = 0
   ```

2. **Run analytical calc**:
   ```bash
   python3 ies_direct_calc.py  # Record max, min, avg
   ```

3. **Run Blender render**:
   ```bash
   blender --background --python validate_lux.py
   ```

4. **Assert direct-only match**: Blender direct-only values should match analytical within 1% at the center point and within 5% across the full grid.

5. **Set full bounces** in `fixture_config.py`:
   ```python
   MAX_BOUNCES = None
   ```

6. **Run Blender with full bounces**:
   ```bash
   blender --background --python validate_lux.py
   ```

7. **Assert inter-reflection uplift**:
   - Peak illuminance: +3-6% above direct-only
   - Average illuminance: +15-25% above direct-only
   - Uniformity should improve (min/avg ratio increases)
   - If uplift is much higher, check workplane holdout material

8. **If values are off by a constant factor**, check these in order:
   - Mesh area calculation -- verify `fixture.mesh_area_m2` matches physical luminaire
   - K = 1/(4*A) -- verify this constant in the shader
   - IES multiplier double-counting -- are you parsing AND letting Blender apply it?
   - IES Texture Vector input -- must connect to `Geometry.Incoming`, not default Normal
   - cos(theta) clamp -- should be 0.087 (too small = 1/cos divergence, too large = clipped beam)
   - Lux formula -- with rho=1.0 workplane, it's just `luminance * 179` (no division by rho)
   - `view_transform` -- must be 'Raw'
   - `use_denoising` -- must be False

### Reference Baselines (20' x 20' x 10' room, 2.5' workplane)

| Configuration | Analytical Max | Blender Direct (bounce=0) | Blender Full |
|--------------|---------------|--------------------------|-------------|
| Mesh emitter, BioPro 3.917'x4" | 225.4 lux / 20.9 fc | 227.3 lux / 21.1 fc (+0.8%) | 239.5 lux / 22.2 fc |
| 1"x1" mesh vs single SPOT | -- | 237.24 vs 237.2 lux | 99.98% match |
| 3.917'x1" mesh vs 10-SPOT array | -- | 227.37 vs 227.6 lux | 99.9% match |

Legacy SPOT baselines (for reference):

| Configuration | Analytical Max | Blender Direct (bounce=0) | Blender Full |
|--------------|---------------|--------------------------|-------------|
| Single SPOT, B4RD | 165.0 lux / 15.3 fc | 166.2 lux / 15.4 fc (+0.7%) | ~170 lux |
| 10-SPOT array, BioPro | 225.4 lux / 20.9 fc | 227.6 lux / 21.1 fc (+1.0%) | 239.9 lux / 22.3 fc |

### Floor Plan Baselines (3 rooms, 13 fixtures, 80/50/20 reflectances)

| Room | Direct-Only (avg fc) | With Bounces (avg fc) | Uplift |
|------|---------------------|----------------------|--------|
| Corridor (30x6x9, 4x B4RD) | 22.3 | 27.2 | +22% |
| Meeting Room (20x14x9, 3x 12' BioPro) | 64.7 | 80.6 | +25% |
| Private Office (10x14x9, 6x B4RD) | 55.5 | 63.8 | +15% |

Regression test: `python3 test_regression.py` validates against `baselines.json`.

---

## 17. Quick Reference

### Minimal Setup Checklist

1. Mesh emitter plane at ceiling, normals facing -Z (into room)
2. Corrected IES shader: `Emission Strength = IES_Fac * K / cos(theta)`
   - `K = 1 / (4 * A)` where A = mesh area in m^2
   - `cos(theta) = dot(Normal, Incoming)`, clamped to 0.087
   - IES Texture Vector input connected to `Geometry.Incoming` (not default Normal)
3. Principled BSDF materials: `Roughness=1, Metallic=0, Specular IOR Level=0`
4. Workplane: Light Path holdout (camera=white diffuse, other=transparent)
5. For lux measurement: `view_transform = 'Raw'`, `use_denoising = False`
6. For beauty renders: `view_transform = 'Filmic'`, `use_denoising = True`
7. Output: 32-bit EXR for analysis, 16-bit PNG for beauty
8. `lux = pixel_luminance * 179` (with rho=1.0 workplane)

### Key Constants

| Constant | Value | Source |
|----------|-------|--------|
| Max photopic luminous efficacy | 179.0 lm/W | CIE standard |
| Mesh emitter calibration K | 1 / (4 * A) | Derived and validated |
| cos(theta) clamp | 0.087 (~85 deg) | Prevents 1/cos divergence |
| D65 luminous efficacy (Blender internal) | 177.83 lm/W | Blender source |
| Candela-to-Watt factor (Blender) | 4*pi/177.83 = 0.07067 | ies.cpp |
| Feet to meters | 0.3048 | Exact |
| Inches to meters | 0.0254 | Exact |
| Lux to footcandles | divide by 10.764 | Exact |
| Standard workplane height | 2.5 ft (0.762 m) | Architectural standard |
| Standard measurement grid | 2 ft (0.6096 m) | Photometric standard |

### Blender Source Code References

- IES parsing and conversion: `intern/cycles/util/ies.cpp`
- Issue tracker for IES normalization: Blender Projects #134752
- Developer discussion: devtalk.blender.org/t/cycles-ies-texture-use-1-watt-for-correct-illumination/16358
- Area light eval_fac issue: Blender Projects #72553

---

## 18. Corrected Mesh Emitter

### The Problem

Blender's built-in light types have limitations for photometric simulation:
- **POINT/SPOT lights** are point sources -- they produce photometrically accurate illuminance but appear as infinitely small dots in perspective views, not realistic luminaire shapes.
- **AREA lights** apply an internal `eval_fac = 1/(area*4)` normalization that makes IES correction impossible (see Decision Log: "Why SPOT Arrays, Not AREA Lights").

**Mesh emitters** solve both problems: they are visible area shapes AND have full shader control with no internal normalization.

### The Formula

```
Emission Strength = IES_Fac * K / cos(theta_emit)
```

Where:
- `IES_Fac` = IES Texture node output (Vector connected to `Geometry.Incoming`)
- `K = lumen_scale / (4 * A)` = calibration constant, A = mesh area in m^2
- `lumen_scale` = fixture_length / IES_module_length (for multi-module linears; 1.0 for single-module or round)
- `cos(theta_emit) = dot(Normal, Incoming)`, clamped to minimum 0.087

This produces area-independent luminous intensity: `I(theta) = IES_Fac * lumen_scale / 4`, matching Blender's SPOT light with pi correction to 99.98% accuracy.

### Module-Length Scaling (lumen_scale)

IES photometric files are tested on a specific luminous module (e.g., the BioPro IES was tested on a 3.917' module). The mesh emitter formula normalizes total intensity to one module's worth of output, regardless of mesh area. When the physical fixture is longer than the IES module:

```
lumen_scale = fixture_length_ft / IES_module_length_ft
```

Example: A 12' BioPro linear fixture → `12.0 / 3.917 = 3.064` → emits 3.064× the candela of one module.

The `parse_ies_module_length()` function in `fixture_config.py` reads the luminous opening dimensions from IES line 7 (tokens 7-8 after TILT=) and returns the larger dimension in feet. For round fixtures (`length_ft = 0`), lumen_scale is always 1.0.

The `Fixture.get_lumen_scale()` method auto-detects this ratio. Manual override is available via `Fixture(lumen_scale=3.0)`.

### Why K = 1/(4A)

Blender mesh emitters at `Strength = 1.0` emit 1 W total (not 1 W/m^2). The Cycles source code for mesh emission does NOT apply any area normalization -- the shader has full control. Meanwhile, Blender's IES node converts candela to watts using `cd * 4*pi / 177.83`. Combining these:

- A mesh at Strength=1.0 radiates like 1W distributed over its area
- The IES Fac output gives `cd_scaled / (177.83 / (4*pi))`
- To make the mesh emit like a calibrated source: multiply Fac by `1/(4*A)`
- The cos correction undoes the Lambertian emission built into flat mesh surfaces

Empirical derivation confirmed: `K_empirical = 387.4` for a 1"x1" mesh (area = 6.4516e-4 m^2), `K_theoretical = 1/(4 * 6.4516e-4) = 387.6`. Match: 99.95%.

### 9-Node Shader Graph

```
[Geometry] ─── Normal ──────────┐
     │                          │
     └── Incoming ──┐     [Dot Product]
                    │           │
              [IES Texture]  [Maximum] (clamp to 0.087)
                    │           │
                    │      [Divide] (1.0 / clamped_cos)
                    │           │
              [Multiply] ←──────┘ (IES_Fac * 1/cos)
                    │
              [Multiply] (× K = 1/(4*A))
                    │
              [Emission Shader]
                    │
              [Material Output]
```

**Critical connection:** The IES Texture node's Vector input MUST be connected to `Geometry.Incoming`, not left at the default (Normal). For flat mesh planes, Normal is constant (-Z), so the IES pattern would be identical at every pixel. Incoming varies per ray direction, giving correct angular distribution.

### Validation Results

| Test | SPOT Baseline | Mesh Emitter | Match |
|------|--------------|-------------|-------|
| 1"x1" mesh (point-like) | 237.2 lux | 237.24 lux | 99.98% |
| 3.917'x1" mesh (linear) | 227.6 lux (10-SPOT) | 227.37 lux | 99.9% |
| 3.917'x4" mesh (realistic) | 225.4 lux (analytical) | 227.3 lux | 99.2% |

All 100 grid points under 3% error vs analytical. Inner zone (within ±5 ft): avg 0.7% error.

---

## 19. Perspective Rendering

### Overview

`render_perspective.py` produces photorealistic perspective views of the lighting scene using the same corrected mesh emitter fixtures as `validate_lux.py`. Mesh luminaires appear as contiguous glowing area shapes -- not point dots.

### Two Output Modes

| Setting | Beauty Render | Analysis Render |
|---------|--------------|----------------|
| View transform | `Filmic` | `Raw` |
| Output format | `PNG` (16-bit) | `OPEN_EXR` (32-bit) |
| Denoising | Enabled (OIDN) | Disabled |
| Use case | Visual evaluation | Falsecolor input |

Configure via `PERSP_VIEW_TRANSFORM` and `PERSP_OUTPUT_FORMAT` in `fixture_config.py`.

### Camera Configuration

```python
PERSP_CAM_POSITION_FT  = (8.0, -8.0, 5.0)     # camera position in feet
PERSP_CAM_TARGET_FT    = (0.0, 0.0, 5.0)       # look-at point in feet
PERSP_CAM_FOV          = 90.0                    # degrees
PERSP_RENDER_SAMPLES   = 2048
PERSP_RESOLUTION       = (1920, 1080)
```

The perspective camera uses a Track To constraint aimed at the target point. No workplane mesh is added (not needed for visual renders).

### Run

```bash
blender --background --python render_perspective.py
```

---

## 20. Falsecolor Visualization

### Overview

`falsecolor.py` is a standalone script that converts EXR renders into color-mapped illuminance or luminance heatmaps. No Blender dependency -- uses numpy, matplotlib, and OpenEXR.

### Modes

- **illuminance** -- Converts RGB to lux via luminous efficacy (179 lm/W). Use with `lux_render.exr` (orthographic, Raw view transform).
- **luminance** -- Converts RGB to cd/m^2. Use with perspective Raw EXR renders.

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--mode` | `illuminance` or `luminance` | `illuminance` |
| `--max` | Maximum value for colorbar | auto |
| `--log` | Logarithmic color scale | off |
| `--cmap` | Matplotlib colormap | `turbo` |
| `--contours N` | Number of contour lines | 0 |
| `--room-grid` | Overlay room coordinate grid | off |
| `--room-width` | Room width in feet | 20 |
| `--room-depth` | Room depth in feet | 20 |
| `--grid-spacing` | Grid spacing in feet | 2 |

### Examples

```bash
# Illuminance from lux validation render:
python3 falsecolor.py lux_render.exr fc_illum.png --mode illuminance --contours 5

# Luminance from perspective render:
python3 falsecolor.py perspective_render.exr fc_lum.png --mode luminance --log

# Custom colormap and scale:
python3 falsecolor.py lux_render.exr fc.png --max 300 --cmap viridis --room-grid
```

### Output

The falsecolor PNG includes:
- Color-mapped image with chosen colormap and scale
- Horizontal colorbar with unit label
- Statistics bar: max, min, avg (in primary and secondary units)
- Optional contour lines and room coordinate grid overlay

---

## 21. CalcGrid Bake System

### Overview

`calc_grid_bake.py` uses Cycles texture baking (instead of rendering) to extract illuminance values at measurement points. Each calc grid is a flat mesh plane with a holdout material. The bake writes luminance values into a texture, which are then sampled at grid point locations.

### Key Discovery

Cycles bake rays **are** camera rays (`Is Camera Ray = True` during `bpy.ops.object.bake()`). This means the holdout material designed for camera-based measurement works identically during baking — no special material needed.

### Data Contract (calcgrid_results.json)

```json
{
  "rooms": [{"name": "Corridor", "origin_ft": [0,14], "width_ft": 30, "depth_ft": 6, "height_ft": 9}],
  "fixtures": [{"ies_file": "B4RD.ies", "position_ft": [3,17,8.5], "length_ft": 0.0, "width_inches": 4.0}],
  "grids": [{
    "name": "Corridor_WP", "room_name": "Corridor",
    "position_ft": [15, 17, 2.5], "spacing_ft": 2.0,
    "x_ft": [-13, -11, ...],  "y_ft": [-1, 1],
    "values_fc": [[row0_highest_Y], [row1], ...],
    "stats": {"max_fc": 24.3, "min_fc": 20.5, "avg_fc": 22.3, ...}
  }]
}
```

**Note:** `values_fc` is stored top-to-bottom (row 0 = highest Y value). Grid coordinates are relative to `position_ft`.

### Run

```bash
blender --background --python calc_grid_bake.py
```

Outputs: `calcgrid_results.json`, `calcgrid_results.txt`, per-grid EXR files, falsecolor renders.

### Validated Accuracy

CalcGrid bake vs orthographic camera render: 0.5% match (228.7 vs 227.3 lux peak, 1-4% across grid).

---

## 22. Web Viewer & PDF Export

### Overview

`web/viewer.html` is a single-file interactive lighting viewer that reads `calcgrid_results.json` and provides three visualization modes. No build step or server required — just open in a browser (or serve via any HTTP server for auto-loading).

### Features

- **Three view modes**: Falsecolor (heatmap only), Numeric (value labels), Hybrid (both)
- **Pan/zoom**: via svg-pan-zoom.js library with smooth interaction
- **Scale-compensated text**: value labels maintain constant screen-space size regardless of zoom level
- **Adjustable illuminance scale**: min/max inputs at bottom bar, live recoloring of all elements
- **Tooltip**: hover any cell to see fc/lux value and grid name
- **Stats panel**: per-grid statistics in sidebar

### PDF Export

Client-side vector PDF generation using jsPDF. The "Export PDF" dropdown offers three modes matching the viewer.

Each PDF contains:
- **Page 1**: Combined plan view (all rooms, fixtures, values/heatmap, stats, illuminance scale)
- **Pages 2+**: Per-room detail sheets with zoomed view, fixture schedule, stats

PDF elements: room outlines, fixture symbols (circles for round, lines for linear), heatmap cells (falsecolor/hybrid), value labels with white halo (numeric/hybrid), turbo colormap scale bar with tick labels, 5'-0" reference scale bar.

### Technical Notes

- **SVG Y-flip**: `transform="scale(1,-1)"` on viewport group converts architectural Y-up to SVG Y-down. Text wrappers use `scale(s, -s)` to un-flip text.
- **Scale-compensated text**: each text wrapper `<g>` stores its position. `updateTextScale(zoom, baseUnitsPerPx)` recomputes transform on every zoom event.
- **Turbo colormap**: 256 sRGB stops in JavaScript array. CSS `rgb()` values are sRGB natively.
- **Recoloring**: `heatmapCells[]` and `valueDots[]` arrays store element references + raw fc values for instant recalculation when scale changes.

### Run

```bash
# Serve from project directory (viewer auto-loads ../calcgrid_results.json)
python3 -m http.server 8765
# Open: http://localhost:8765/web/viewer.html
```

Or drag-drop any `calcgrid_results.json` onto the viewer.
