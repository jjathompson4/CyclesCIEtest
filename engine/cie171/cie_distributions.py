"""
Generate IES photometric files for CIE 171 analytical distributions.

Lambertian (diffuse): I(θ) = I₀·cos(θ)
  - Symmetric around nadir
  - Vertical angles 0°–90° in 5° steps
  - Single horizontal plane (fully symmetric)

Isotropic: I(θ) = constant in all directions (4π steradians)
  - Full sphere: 0°–180° vertical
  - Used for test 5.8 (interreflection in closed room)
"""

import math
import os


def generate_lambertian_ies(I0, output_path):
    """Generate an IES LM-63-2002 file for a Lambertian (cos θ) distribution.

    Args:
        I0: peak intensity at nadir (candela)
        output_path: where to write the .ies file

    Returns:
        output_path
    """
    # Vertical angles: 0° to 90° in 5° steps (downward hemisphere only)
    vert_angles = list(range(0, 91, 5))  # 19 values
    n_vert = len(vert_angles)

    # Single horizontal plane (axially symmetric)
    horiz_angles = [0]
    n_horiz = 1

    # Candela values: I₀·cos(θ)
    candela = []
    for theta in vert_angles:
        cd = I0 * math.cos(math.radians(theta))
        candela.append(max(cd, 0.0))

    # Compute total flux: Φ = π·I₀ for a perfect Lambertian
    flux = math.pi * I0

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w') as f:
        f.write("IESNA:LM-63-2002\n")
        f.write("[TEST] CIE 171 Lambertian distribution\n")
        f.write(f"[LUMCAT] CIE-DIFFUSE-{I0:.0f}CD\n")
        f.write("TILT=NONE\n")
        # Line 1 of data: 10 values
        # num_lamps  lumens_per_lamp  multiplier  n_vert  n_horiz
        # photometric_type  units_type  width  length  height
        f.write(f"1 {flux:.1f} 1.0 {n_vert} {n_horiz} 1 2 0.0 0.0 0.0\n")
        # Ballast factor, ballast-lamp factor, input watts
        f.write("1.0 1.0 0.0\n")
        # Vertical angles
        f.write(" ".join(f"{a:.1f}" for a in vert_angles) + "\n")
        # Horizontal angles
        f.write(" ".join(f"{a:.1f}" for a in horiz_angles) + "\n")
        # Candela values (one plane)
        f.write(" ".join(f"{cd:.2f}" for cd in candela) + "\n")

    return output_path


def generate_isotropic_ies(flux_lm, output_path):
    """Generate an IES file for an isotropic (uniform) point source.

    I = Φ / (4π) at all angles. Full sphere coverage (0°–180°).

    Args:
        flux_lm: total luminous flux in lumens
        output_path: where to write the .ies file

    Returns:
        output_path
    """
    I_uniform = flux_lm / (4.0 * math.pi)

    # Vertical angles: 0° to 180° in 5° steps (full sphere)
    vert_angles = list(range(0, 181, 5))  # 37 values
    n_vert = len(vert_angles)

    # Single horizontal plane (axially symmetric)
    horiz_angles = [0]
    n_horiz = 1

    # Constant candela at all angles
    candela = [I_uniform] * n_vert

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w') as f:
        f.write("IESNA:LM-63-2002\n")
        f.write("[TEST] CIE 171 Isotropic distribution\n")
        f.write(f"[LUMCAT] CIE-ISOTROPIC-{flux_lm:.0f}LM\n")
        f.write("TILT=NONE\n")
        f.write(f"1 {flux_lm:.1f} 1.0 {n_vert} {n_horiz} 1 2 0.0 0.0 0.0\n")
        f.write("1.0 1.0 0.0\n")
        f.write(" ".join(f"{a:.1f}" for a in vert_angles) + "\n")
        f.write(" ".join(f"{a:.1f}" for a in horiz_angles) + "\n")
        f.write(" ".join(f"{cd:.4f}" for cd in candela) + "\n")

    return output_path
