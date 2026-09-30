# CIE 171:2006 Validation — Status Dashboard

Last updated: 2026-09-29 (5.8 and the full daylight suite rerun with `transparent_max_bounces = 1024`; daylight rows below are from those results)

## Summary

| Test | Description | Status | Best Max Error | Notes |
|------|-------------|--------|----------------|-------|
| **Section 4 — Experimental** | | | | |
| 4.1 | CFL, grey walls | Not started | — | Needs IES from CIE doc |
| 4.2 | Opal luminaire, grey walls | Not started | — | Needs IES from CIE doc |
| 4.3 | Semi-specular reflector, grey walls | Not started | — | Needs IES from CIE doc |
| 4.4 | CFL, black walls | Not started | — | Needs IES from CIE doc |
| 4.5 | Opal luminaire, black walls | Not started | — | Needs IES from CIE doc |
| 4.6 | Semi-specular reflector, black walls | Not started | — | Needs IES from CIE doc |
| **Section 5 — Analytical** | | | | |
| 5.2 | Point light sources | **Passing** | 0.99% | Diffuse distribution; CIE T9 pending |
| 5.3 | Area light sources | **Passing** | 4.94% | Diffuse distribution; CIE T9 pending |
| 5.4 | Luminous flux conservation | **Passing** | 0.28% | Artificial lighting; daylighting scenarios pending |
| 5.5 | Directional transmittance of clear glass | Not started | — | Spec + ref values transcribed in WIP |
| 5.6 | Light reflection over diffuse surfaces | **Passing** | 0.25% | Sun lamp approach; Scenarios 1 & 3 pending |
| 5.7 | Diffuse reflections with internal obstructions | **Passing** | 1.07% | NVIDIA-corrected Table 19 values |
| 5.8 | Internal reflected component (diffuse) | **Passing** | 0.31% | All 12 reflectances; needed `transparent_max_bounces` raised from Blender's default 8 (was −32% at ρ=0.95) |
| 5.9 | Sky component, roof unglazed opening | **Partial pass** | 6.81% (pt A, 1x1 type 2) | 28/30 pass; point A −5.7% (4x4 type 1) and −6.8% (1x1 type 2); Type 3 errata corrected; Type 13 point G CIE errata confirmed by NVIDIA |
| 5.10 | Sky component, roof glazed opening | **Partial pass** | 27.3% (pt A, 1x1) | Point A −18 to −27% on all 1x1 skies, −6 to −8% on 7/15 4x4 skies; other points within 5% (one at −5.4%). Glass model: Fresnel Transparent BSDF |
| 5.11 | SC + ERC, facade unglazed opening | **Partial pass** | 16.9% (2x1) | Wall edge points −7.5 to −10.9% (4x3 pt A) / −6 to −17% (2x1 pt C); ceiling H' −5.2 to −5.5% (2x1); floor within 5% |
| 5.12 | SC + ERC, facade glazed opening | **Partial pass** | 18.7% (2x1) | Wall edge −7.6 to −10.3% (4x3) / −7 to −18% (2x1); grazing-angle N/N' −14 to −19% (2x1), N' ~−6% (4x3) |
| 5.13 | SC + ERC, unglazed + horizontal mask | **Partial pass** | 11.7% (2.0m) | 0.5m: 4/15 pass, pt G −5.1 to −5.9%; 1.0m: pt G −11 to −12% on skies without the B.22 errata (types 5, 10, 12–15); 2.0m: F −7 to −12%, G +8.4 to +8.8% |
| 5.14 | SC + ERC, unglazed + vertical mask | **Partial pass** | 5.84% (3m, excl. errata) | 3m: 14/15 pass (type 1 pt A −5.8%); 6m/9m CIE ref errata confirmed by NVIDIA; Table B.26 type 12 F typo |
| **Section 6 — Additional** | | | | |
| 6.x | Sun patch on floor | Not started | — | Phase C |
| 6.x | Specular surface simulation | Not started | — | Phase C |
| 6.x | Spectral properties of surfaces | Not started | — | Phase C |
| 6.x | Light leak test | Not started | — | Phase C |
| 6.x | Symmetric/asymmetric source processing | Not started | — | Phase C |

## Status Key

- **Not started** — test case defined but no work begun
- **In progress** — actively working on implementation or debugging
- **Passing** — all measurement points within tolerance
- **Partial pass** — majority of points within tolerance; known edge-sensitive points exceed threshold (documented)
- **Failing** — implemented but results outside tolerance
- **Blocked** — waiting on prerequisite (CIE doc data, sky system, etc.)

## Tolerance Criteria

- Section 4 (experimental): ±6.7% measurement error, ±10.5% global
- Section 5 (analytical): 5% measurement error, 10% global (per NVIDIA methodology)
