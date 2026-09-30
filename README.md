# CyclesCIEtest

Can Blender's Cycles path tracer produce illuminance values good enough for lighting calculations? This repo tests it against CIE 171:2006, the standard set of test cases for checking the accuracy of lighting simulation software.

**Status:** personal research prototype, built on my own time. It isn't a product, isn't maintained, and isn't affiliated with HDR or any employer. Don't use it for design decisions or code compliance.

## Results

These are the CIE 171 analytical test cases (Section 5). The tolerance is 5% per measurement point and 10% globally, the criteria NVIDIA used in its Iray validation. A case passes only if every measurement point is within tolerance; reference values that NVIDIA's validation also identified as CIE errata are excluded.

| Test | What it checks | Result | Max error |
|---|---|---|---|
| 5.2 | Point light sources | Pass | 0.99% |
| 5.3 | Area light sources | Pass | 4.94% |
| 5.4 | Luminous flux conservation | Pass | 0.28% |
| 5.5 | Directional transmittance of clear glass | Not run | — |
| 5.6 | Light reflection over diffuse surfaces | Pass | 0.25% |
| 5.7 | Diffuse reflections with internal obstructions | Pass | 1.07% |
| 5.8 | Internal reflected component | Pass | 0.31%, ρ = 0.05 to 0.95 |
| 5.9 | Sky component, unglazed roof opening | Partial | 28 of 30 sky/opening runs pass; edge point A at −5.7% and −6.8% in the other two (type 13 point G errata excluded) |
| 5.10 | Sky component, glazed roof opening | Partial | Edge point A: −18 to −27% (1×1 opening), −6 to −8% (4×4, 7 of 15 skies); other points within 5% |
| 5.11 | Sky + externally reflected component, unglazed facade opening | Partial | Wall points at the opening edge −6 to −17%; ceiling point H′ −5.2 to −5.5% (2×1); floor points within 5% |
| 5.12 | Same, glazed facade opening | Partial | Wall points at the opening edge −6 to −18%; grazing-angle points N and N′ −14 to −19% (2×1) |
| 5.13 | Unglazed opening with a horizontal mask | Partial | 0.5 m: 4 of 15 skies pass, point G −5 to −6% on the rest; 1.0 m: point G −11 to −12% on skies without the Table B.22 errata; 2.0 m: points F and G 7–12% |
| 5.14 | Unglazed opening with a vertical mask | Partial | 3 m: 14 of 15 skies pass, one point at −5.8%; the 6 m and 9 m reference values are errata |

All six electric-light cases that were run pass, and the six daylight cases pass partially: the misses are at points on opening edges, at grazing angles, and at mask shadow boundaries. Test 5.5 wasn't run. The experimental cases (Section 4) and the additional tests (Section 6) weren't run either. Details are in [docs/CIE/VALIDATION_STATUS.md](docs/CIE/VALIDATION_STATUS.md), and the raw results are in [docs/CIE/results](docs/CIE/results).

## What I learned

These findings are useful to anyone doing lighting calculations in Cycles. There's more in [docs/CIE/NOTES.md](docs/CIE/NOTES.md).

- **Raise the transparent-bounce limit.** Calc grids are Transparent BSDF planes, and every pass through one counts against `transparent_max_bounces`, which defaults to 8. At that default, test 5.8 read −11.65% at ρ = 0.90 and −32.42% at ρ = 0.95, because paths bouncing between the floor and the room were cut short. With the limit at 1024, every reflectance is within 0.31%. I first blamed Russian roulette; that was wrong, since roulette reweights the paths it keeps and adds noise, not bias.
- **Glass has to be a Transparent BSDF.** It's the only shader that shadow rays pass through. The glass is modeled as a Transparent BSDF tinted by double-surface Fresnel: (1 − F)² × 0.96, IOR 1.52.
- **Points at the edge of an opening are sensitive.** They depend on bake resolution and the averaging kernel. The experiments are in [docs/CIE/rnd](docs/CIE/rnd).
- **Sky orientation differs between roof and facade openings.** They need different HDRI azimuth rotations, and the wrong one gives 40–70% errors for skies with circumsolar brightening.
- **Open test scenes need a black world background.** Blender's default grey world adds ambient light that skewed test 5.6 by 15%.
- **Some CIE reference values are wrong.** The 1.0 m mask values in Table B.22 (test 5.13) for overcast skies appear to use the wrong sky type. Cycles computes the same corrected values that NVIDIA's Iray validation reported.

## How it works

- Luminaires are mesh emitters with real aperture sizes and an IES-driven emission shader.
- Illuminance is read from calc grids: measurement surfaces baked in Cycles and sampled at each CIE measurement point with a small averaging kernel.
- Renders mostly use 4,096 samples (2,048–8,192 in the interreflection test), the Raw view transform, and no denoising or clamping.
- Daylight tests light the scene with CIE standard sky HDRIs, normalized to unit horizontal illuminance.

The math and the Blender specifics are in [docs/BLENDER_CYCLES_LIGHTING_CALC.md](docs/BLENDER_CYCLES_LIGHTING_CALC.md) and [docs/analysis-pass-math.md](docs/analysis-pass-math.md).

## Web app demo

I also built a proof-of-concept web app on this engine. It imports a model, places IES luminaires, runs the calculation from the browser, and shows false-color results in a Three.js viewer. The app isn't in this repo; here's a [demo video](https://www.youtube.com/watch?v=kkUZkLPS4n0).

## Running it

You need Blender 5 (developed on 5.0, checked on 5.1). The Blender scripts use Blender's bundled Python. The standalone scripts need Python 3 with numpy and matplotlib.

```bash
cd engine

# Reference values only (no Blender)
python3 cie171/runner.py --test 5.2 --analytical-only

# Electric-light tests (5.2–5.8), rendered in Cycles
blender --background --python cie171/runner.py -- --test 5.2

# Daylight tests (5.9–5.14): generate the sky HDRIs once, then run
python3 cie171/cie_sky_generator.py --resolution 1024
blender --background --python cie171/runner_daylight.py -- --test 5.9 --opening 4x4 --sky-type 5
```

Results are written to `docs/CIE/results/test_<id>/`.

`calc_grid_bake.py` runs a small demo floor plan: a corridor, a meeting room and an office. It uses a generic Lambertian distribution in place of the manufacturer IES files it was built with, which can't be redistributed. Point the constants in `engine/fixture_config.py` at your own IES files to use real luminaires.

## Layout

```
engine/          Calculation engine (runs inside Blender via bpy)
  cie171/        CIE 171 test cases, runners, sky generator, synthetic IES files
docs/
  CIE/           Validation status, notes, results JSON, R&D experiments
```

## References

- CIE 171:2006, *Test Cases to Assess the Accuracy of Lighting Computer Programs*. Available from the CIE; not included here.
- NVIDIA's 2016 validation of Iray against CIE 171, and the AGi32 CIE 171 validation report. I used them for tolerance criteria and to cross-check errata; neither is included.

## License

GPL-3.0; see [LICENSE](LICENSE). The engine runs inside Blender through its Python API, and Blender is GPL.

Jeff Thompson · [thompsonjeff.com](https://thompsonjeff.com)
