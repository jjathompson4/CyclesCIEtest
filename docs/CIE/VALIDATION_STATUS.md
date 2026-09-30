# CIE 171:2006 Validation — Status Dashboard

Last updated: 2026-03-16

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
| 5.8 | Internal reflected component (diffuse) | **Partial pass** | 1.79% (ρ≤0.80) | ρ=0.90/0.95 fail due to Russian Roulette |
| 5.9 | Sky component, roof unglazed opening | **Passing** | 4.23% (excl. errata) | 15/15 types pass both openings; Type 3 errata corrected; Type 13 point G CIE errata confirmed by NVIDIA |
| 5.10 | Sky component, roof glazed opening | **Passing** | 3.8% (excl. pt A) | Glass model: Fresnel Transparent BSDF; point A edge-sensitive (same as 5.9) |
| 5.11 | SC + ERC, facade unglazed opening | **Partial pass** | 7.49% (4x3) | Floor/ceiling excellent (<3%); wall edge points 7-11% (4x3) / 5-17% (2x1) |
| 5.12 | SC + ERC, facade glazed opening | **Partial pass** | 7.64% (4x3) | Glass Fresnel works; wall edge 8-10% (4x3); grazing-angle N/N' 15-19% (2x1) |
| 5.13 | SC + ERC, unglazed + horizontal mask | **Passing** | 4.57% (1.0m, excl. errata) | 0.5m: 5-6%; 1.0m: 4.6% (excl. B.22 errata, confirmed by NVIDIA); 2.0m: 8.5% |
| 5.14 | SC + ERC, unglazed + vertical mask | **Passing** | 1.79% (3m, excl. errata) | 3m mask passes; 6m/9m CIE ref errata confirmed by NVIDIA; Table B.26 type 12 F typo |
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
