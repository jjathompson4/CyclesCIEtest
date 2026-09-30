# Analysis Pass Math — Illuminance & Luminance from Cycles Render Passes

Reference for how the analysis/simulate render extracts per-pixel illuminance (lux)
and luminance (cd/m^2) from Blender Cycles render passes.

---

## Passes Extracted

The analysis render uses Cycles' compositor to extract 4 passes from a single render:

| Pass | Compositor Output | Contents |
|------|------------------|----------|
| Combined | `Image` | Total outgoing radiance toward camera (all BSDFs) |
| DiffDir | `Diffuse Direct` | Direct diffuse light component (albedo-free) |
| DiffInd | `Diffuse Indirect` | Indirect diffuse light component (albedo-free) |
| DiffCol | `Diffuse Color` | Surface albedo (rho) |

## Blender Cycles Pass Decomposition

Cycles uses a **multiplicative decomposition** for diffuse passes:

```
Diffuse contribution to Combined = DiffCol x (DiffDir + DiffInd)
```

This means DiffDir and DiffInd are the **light-only** values — they do NOT include
surface albedo. They represent `E / pi` (irradiance divided by pi) for Lambertian
surfaces.

## Illuminance (lux)

### Proven formula (calc grid bake)

The calc grid uses a white holdout material (rho = 1) and bakes the COMBINED pass:

```
pixel_value = (rho / pi) x E = (1 / pi) x E    [since rho = 1]
illuminance = Rec709_luminance(pixel) x 179 lm/W
```

This is validated against real-world measurements to 99.9% accuracy.

### Analysis render formula (matches calc grid)

Since `DiffDir + DiffInd = E / pi` (light component, albedo-free), we use the
same formula:

```
illuminance = Rec709_luminance(DiffDir + DiffInd) x 179 lm/W
```

Where `Rec709_luminance(rgb) = 0.2126 * R + 0.7152 * G + 0.0722 * B`.

### Previous bug (fixed 2026-03-01)

The original code divided by DiffCol before multiplying by 179:

```python
# WRONG — DiffDir/DiffInd are already albedo-free
irradiance_rgb = (diff_dir + diff_ind) / diff_col
illuminance = dot(irradiance_rgb, lum_weights) * 179
```

This divided by albedo a second time, inflating values by `1 / rho`. For a floor
with rho = 0.20, this made illuminance ~5x too high. The fix: drop the division
by DiffCol entirely.

## Luminance (cd/m^2)

The Combined pass gives outgoing radiance toward the camera (all surface types):

```
luminance = Rec709_luminance(Combined) x 179 lm/W
```

No pi factor, no albedo correction. This is straightforward because Combined
already represents the physically correct outgoing radiance `L` in W/sr/m^2,
and `L x 179` converts to cd/m^2.

## The 179 Constant

The factor 179 lm/W is the luminous efficacy of Blender's internal radiance
representation. It converts Cycles' linear radiometric pixel values to photometric
units (lux for illuminance, cd/m^2 for luminance). This is a standard constant
in Radiance/HDRI lighting analysis (CIE standard illuminant weighting).

More precisely: `179 = 683 lm/W x (weighted average of V(lambda) over D65)`.
The 683 lm/W is the maximum luminous efficacy at 555nm, and the V(lambda)
weighting over D65 daylight gives the ~0.262 factor, yielding 179.

## DiffCol Pass — When It's Useful

DiffCol is the surface albedo texture. While not used in the current illuminance
calculation, it's still extracted because:

1. It enables future features like reflectance visualization
2. It can validate that surfaces have expected rho values
3. If needed, surface exitance M can be computed: `M = rho x E`

## Files

- `engine/calc_grid_bake.py` — `extract_illuminance()` (proven reference)
- `engine/scene_builder.py` — `configure_cycles_base()` (enables passes)
