#!/usr/bin/env python3
"""Fit polynomial to CIE Table 15 glass transmittance data.

Run this BEFORE implementing the polynomial shader nodes (exp2c).
Records the best-fit coefficients and residuals.

Usage:
    python fit_polynomial.py

Output:
    Prints polynomial coefficients, residuals, and a comparison table.
    Also generates fit_results.json with coefficients for use in shader code.
"""

import json
import os
import numpy as np

# CIE 171:2006, Table 15 — 6mm clear glass (n=1.52)
# (incidence_angle_degrees, transmittance)
CIE_TABLE_15 = [
    (0,  0.96),
    (10, 0.96),
    (20, 0.96),
    (30, 0.96),
    (40, 0.96),
    (50, 0.95),
    (60, 0.93),
    (70, 0.84),
    (80, 0.59),
    (90, 0.00),
]

# Convert to cos(theta) domain — polynomial will be τ(cos θ)
angles_deg = np.array([d[0] for d in CIE_TABLE_15])
angles_rad = np.deg2rad(angles_deg)
cos_theta = np.cos(angles_rad)
tau_ref = np.array([d[1] for d in CIE_TABLE_15])

print("=" * 70)
print("CIE Table 15 — Glass Transmittance Polynomial Fit")
print("=" * 70)
print()
print("Reference data (cos θ → τ):")
print(f"  {'cos θ':>8s}  {'τ_ref':>6s}")
for c, t in zip(cos_theta, tau_ref):
    print(f"  {c:8.4f}  {t:6.4f}")
print()

# Fit polynomials of degree 3, 4, 5, 6
# We need τ(0) = 0 and τ(1) ≈ 0.96
best_deg = None
best_coeffs = None
best_max_residual = 1.0

results = {}

for deg in [3, 4, 5, 6]:
    coeffs = np.polyfit(cos_theta, tau_ref, deg)
    fitted = np.polyval(coeffs, cos_theta)
    residuals = fitted - tau_ref
    max_residual = np.max(np.abs(residuals))
    rms_residual = np.sqrt(np.mean(residuals**2))

    # Check boundary conditions
    tau_at_0 = np.polyval(coeffs, 0.0)   # should be ≈ 0
    tau_at_1 = np.polyval(coeffs, 1.0)   # should be ≈ 0.96

    # Check monotonicity in [0, 1]
    test_c = np.linspace(0, 1, 1000)
    test_tau = np.polyval(coeffs, test_c)
    is_monotonic = np.all(np.diff(test_tau) >= -0.001)  # allow tiny numerical noise
    has_negative = np.any(test_tau < -0.01)
    exceeds_one = np.any(test_tau > 1.01)

    print(f"Degree {deg}:")
    print(f"  Coefficients (highest power first): {coeffs}")
    print(f"  Max residual:  {max_residual:.6f}")
    print(f"  RMS residual:  {rms_residual:.6f}")
    print(f"  τ(cos θ=0):    {tau_at_0:.4f}  (target: 0.00)")
    print(f"  τ(cos θ=1):    {tau_at_1:.4f}  (target: 0.96)")
    print(f"  Monotonic:     {'Yes' if is_monotonic else 'NO — has local extrema'}")
    print(f"  In [0,1] range: {'Yes' if not has_negative and not exceeds_one else 'NO'}")
    print(f"  Per-point fit:")
    for c, t_ref, t_fit, r in zip(cos_theta, tau_ref, fitted, residuals):
        status = "OK" if abs(r) < 0.005 else "WARN" if abs(r) < 0.01 else "BAD"
        print(f"    cos θ={c:.3f}  ref={t_ref:.4f}  fit={t_fit:.4f}  Δ={r:+.4f}  [{status}]")
    print()

    results[deg] = {
        "coefficients": coeffs.tolist(),
        "max_residual": float(max_residual),
        "rms_residual": float(rms_residual),
        "tau_at_0": float(tau_at_0),
        "tau_at_1": float(tau_at_1),
        "is_monotonic": bool(is_monotonic),
        "in_range": bool(not has_negative and not exceeds_one),
    }

    # Pick best: must be monotonic, in range, and lowest max residual
    if is_monotonic and not has_negative and not exceeds_one:
        if max_residual < best_max_residual:
            best_max_residual = max_residual
            best_deg = deg
            best_coeffs = coeffs

print("=" * 70)
if best_deg is not None:
    print(f"WINNER: Degree {best_deg}")
    print(f"  Max residual: {best_max_residual:.6f}")
    print(f"  Coefficients: {best_coeffs}")
    print()

    # Print in Horner form for shader node implementation
    # τ = a₀ + c(a₁ + c(a₂ + c·a₃))  for degree 3
    # numpy polyfit returns [aₙ, aₙ₋₁, ..., a₁, a₀] (highest power first)
    horner_coeffs = best_coeffs  # already highest-power-first
    print("Horner form (for shader node chain):")
    print(f"  Start with: {horner_coeffs[0]:.6f}")
    for i in range(1, len(horner_coeffs)):
        print(f"  × cos θ + {horner_coeffs[i]:.6f}")
    print()

    # Print as explicit polynomial for documentation
    terms = []
    for i, c in enumerate(reversed(best_coeffs.tolist())):
        if i == 0:
            terms.append(f"{c:.6f}")
        elif i == 1:
            terms.append(f"{c:+.6f}·c")
        else:
            terms.append(f"{c:+.6f}·c^{i}")
    print(f"  τ(c) = {' '.join(terms)}")
    print(f"  where c = cos(θ)")
else:
    print("WARNING: No polynomial met all criteria (monotonic, in [0,1] range)")
    print("Manual selection required. Check results above.")

# Save results
output = {
    "description": "Polynomial fit of CIE Table 15 glass transmittance (6mm clear, n=1.52)",
    "domain": "cos(theta) in [0, 1]",
    "range": "transmittance in [0, 0.96]",
    "reference": "CIE 171:2006, Table 15, p.26",
    "fits": results,
}

if best_deg is not None:
    output["recommended"] = {
        "degree": best_deg,
        "coefficients_highest_first": best_coeffs.tolist(),
        "coefficients_lowest_first": list(reversed(best_coeffs.tolist())),
        "max_residual": float(best_max_residual),
    }

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fit_results.json")
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"\nResults saved to: {out_path}")
