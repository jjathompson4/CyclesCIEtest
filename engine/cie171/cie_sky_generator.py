"""
CIE Standard General Sky — HDR Environment Map Generator

Implements the 15 CIE General Sky luminance distributions from
ISO 15469:2004 / CIE S 011/E:2003. Generates equirectangular HDR
images suitable for use as Blender Cycles environment textures.

Formulas:
    Relative luminance at sky point (θ_z, γ) relative to zenith:

        L/L_z = [f(χ) × φ(θ_z)] / [f(θ_s) × φ(0)]

    where:
        φ(θ) = 1 + a × exp(b / cos(θ))       — gradation function
        f(χ) = 1 + c × [exp(d×χ) - exp(d×π/2)] + e × cos²(χ)  — indicatrix
        θ_z = zenith angle of sky point
        θ_s = zenith angle of sun
        χ = angular distance between sky point and sun

    The 15 sky types are defined by coefficients (a, b, c, d, e).

Reference: ISO 15469:2004, CIE S 011/E:2003
Coefficients from: andrewwillmott/sun-sky (validated against CIE standard)

Usage:
    python cie_sky_generator.py                    # generate all 15 types
    python cie_sky_generator.py --type 1           # generate single type
    python cie_sky_generator.py --type 1 --verify  # generate + verify E_hz
"""

import math
import os
import sys
import struct
import array
import argparse

# ─────────────────────────────────────────────
# CIE GENERAL SKY TYPE DEFINITIONS
# ─────────────────────────────────────────────

# (a, b, c, d, e) coefficients for gradation φ and indicatrix f
# Source: ISO 15469:2004, Table 1
CIE_SKY_TYPES = {
    1:  {'a':  4.0, 'b': -0.70, 'c':  0, 'd': -1.0, 'e': 0.00,
         'name': 'CIE Standard Overcast Sky, steep luminance gradation'},
    2:  {'a':  4.0, 'b': -0.70, 'c':  2, 'd': -1.5, 'e': 0.15,
         'name': 'Overcast, steep gradation + slight brightening toward sun'},
    3:  {'a':  1.1, 'b': -0.80, 'c':  0, 'd': -1.0, 'e': 0.00,
         'name': 'Overcast, moderately graded luminance distribution'},
    4:  {'a':  1.1, 'b': -0.80, 'c':  2, 'd': -1.5, 'e': 0.15,
         'name': 'Overcast, moderate gradation + slight brightening toward sun'},
    5:  {'a':  0.0, 'b': -1.00, 'c':  0, 'd': -1.0, 'e': 0.00,
         'name': 'Uniform luminance sky'},
    6:  {'a':  0.0, 'b': -1.00, 'c':  2, 'd': -1.5, 'e': 0.15,
         'name': 'Partly cloudy, no zenith gradation + slight brightening'},
    7:  {'a':  0.0, 'b': -1.00, 'c':  5, 'd': -2.5, 'e': 0.30,
         'name': 'Partly cloudy, brighter circumsolar region'},
    8:  {'a':  0.0, 'b': -1.00, 'c': 10, 'd': -3.0, 'e': 0.45,
         'name': 'Partly cloudy, distinct solar corona'},
    9:  {'a': -1.0, 'b': -0.55, 'c':  2, 'd': -1.5, 'e': 0.15,
         'name': 'Partly cloudy, obscured sun'},
    10: {'a': -1.0, 'b': -0.55, 'c':  5, 'd': -2.5, 'e': 0.30,
         'name': 'Partly cloudy, brighter circumsolar region'},
    11: {'a': -1.0, 'b': -0.55, 'c': 10, 'd': -3.0, 'e': 0.45,
         'name': 'White-blue sky with distinct solar corona'},
    12: {'a': -1.0, 'b': -0.32, 'c': 10, 'd': -3.0, 'e': 0.45,
         'name': 'CIE Standard Clear Sky, low luminance turbidity'},
    13: {'a': -1.0, 'b': -0.32, 'c': 16, 'd': -3.0, 'e': 0.30,
         'name': 'CIE Standard Clear Sky, polluted atmosphere'},
    14: {'a': -1.0, 'b': -0.15, 'c': 16, 'd': -3.0, 'e': 0.30,
         'name': 'Cloudless turbid sky with broad solar corona'},
    15: {'a': -1.0, 'b': -0.15, 'c': 24, 'd': -2.8, 'e': 0.15,
         'name': 'White-blue turbid sky with broad solar corona'},
}

# Type 16 is sometimes used as an alias for CIE Overcast (same as Type 1
# but with the classic L = Lz(1+2cosθ)/3 formulation). For CIE 171
# purposes, the doc references "16 types" meaning Types 1-15 + "overcast".
# Since Type 1 IS the CIE Standard Overcast, we treat Type 16 = Type 1.


# ─────────────────────────────────────────────
# SKY LUMINANCE COMPUTATION
# ─────────────────────────────────────────────

def _gradation(theta_z, a, b):
    """Gradation function φ(θ_z) = 1 + a × exp(b / cos(θ_z))."""
    cos_z = max(math.cos(theta_z), 0.004)  # clamp near horizon
    return 1.0 + a * math.exp(b / cos_z)


def _indicatrix(chi, c, d, e):
    """Indicatrix function f(χ) = 1 + c × [exp(d×χ) - exp(d×π/2)] + e × cos²(χ).

    The term exp(d×π/2) normalizes the exponential so f(π/2)
    contribution from the exp term is zero (90° from sun).
    """
    return 1.0 + c * (math.exp(d * chi) - math.exp(d * math.pi / 2)) + e * math.cos(chi) ** 2


def angular_distance(theta1, phi1, theta2, phi2):
    """Angular distance between two points on the sphere.

    Args:
        theta1, theta2: zenith angles (0=zenith, π/2=horizon)
        phi1, phi2: azimuth angles

    Returns:
        Angular distance in radians.
    """
    cos_chi = (math.sin(theta1) * math.sin(theta2) *
               math.cos(phi1 - phi2) +
               math.cos(theta1) * math.cos(theta2))
    return math.acos(max(-1.0, min(1.0, cos_chi)))


def sky_luminance_ratio(theta_z, azimuth, sun_theta_z, sun_azimuth, sky_type):
    """Compute relative sky luminance L/L_z at a given sky point.

    Args:
        theta_z: zenith angle of sky point (radians)
        azimuth: azimuth of sky point (radians)
        sun_theta_z: sun zenith angle (radians)
        sun_azimuth: sun azimuth (radians)
        sky_type: dict with keys 'a', 'b', 'c', 'd', 'e'

    Returns:
        L/L_z (relative luminance, dimensionless). Zenith always = 1.0.
    """
    a, b = sky_type['a'], sky_type['b']
    c, d, e = sky_type['c'], sky_type['d'], sky_type['e']

    # Angular distance from sun
    chi = angular_distance(theta_z, azimuth, sun_theta_z, sun_azimuth)

    # Numerator: f(χ) × φ(θ_z)
    f_chi = _indicatrix(chi, c, d, e)
    phi_z = _gradation(theta_z, a, b)

    # Denominator: f(θ_s) × φ(0)
    # θ_s = angular distance from zenith to sun = sun_theta_z
    f_sun = _indicatrix(sun_theta_z, c, d, e)
    phi_0 = _gradation(0.0, a, b)  # gradation at zenith

    denom = f_sun * phi_0
    if abs(denom) < 1e-10:
        return 1.0

    ratio = (f_chi * phi_z) / denom
    return max(ratio, 0.0)


# ─────────────────────────────────────────────
# HDR IMAGE GENERATION
# ─────────────────────────────────────────────

def generate_sky_hdri(sky_type_id, sun_elevation_deg=60.0, sun_azimuth_deg=180.0,
                      width=2048, height=1024, normalize_ehz=True):
    """Generate an equirectangular HDR sky image for a CIE sky type.

    The image uses equirectangular projection:
        - Horizontal axis: azimuth (0° to 360°)
        - Vertical axis: elevation (-90° to +90°), top=zenith, bottom=nadir

    Args:
        sky_type_id: integer 1-15
        sun_elevation_deg: sun elevation above horizon in degrees
        sun_azimuth_deg: sun azimuth in degrees (180° = south)
        width, height: image resolution
        normalize_ehz: if True, scale luminance so E_hz = 1.0
                       (makes SC values directly comparable to reference)

    Returns:
        list of pixel values (R, G, B, A) as flat float array,
        plus metadata dict
    """
    sky = CIE_SKY_TYPES[sky_type_id]
    sun_theta_z = math.radians(90.0 - sun_elevation_deg)
    sun_az = math.radians(sun_azimuth_deg)

    pixels = [0.0] * (width * height * 4)

    for row in range(height):
        # Map row to elevation: top=+90° (zenith), bottom=-90° (nadir)
        elevation = math.pi / 2 - (row + 0.5) / height * math.pi
        theta_z = math.pi / 2 - elevation  # zenith angle

        if theta_z > math.pi / 2:
            # Below horizon — black
            for col in range(width):
                idx = (row * width + col) * 4
                pixels[idx] = 0.0
                pixels[idx + 1] = 0.0
                pixels[idx + 2] = 0.0
                pixels[idx + 3] = 1.0
            continue

        for col in range(width):
            azimuth = (col + 0.5) / width * 2 * math.pi

            ratio = sky_luminance_ratio(theta_z, azimuth,
                                        sun_theta_z, sun_az, sky)

            idx = (row * width + col) * 4
            pixels[idx] = ratio       # R
            pixels[idx + 1] = ratio   # G
            pixels[idx + 2] = ratio   # B
            pixels[idx + 3] = 1.0     # A

    # Normalize so that diffuse horizontal illuminance E_hz = 1.0
    # E_hz = integral over upper hemisphere of L(θ,φ) × cos(θ) × sin(θ) dθ dφ
    if normalize_ehz:
        ehz = _compute_ehz(pixels, width, height)
        if ehz > 1e-10:
            scale = 1.0 / ehz
            for row in range(height):
                for col in range(width):
                    idx = (row * width + col) * 4
                    pixels[idx] *= scale
                    pixels[idx + 1] *= scale
                    pixels[idx + 2] *= scale

    meta = {
        'sky_type_id': sky_type_id,
        'sky_name': sky['name'],
        'sun_elevation_deg': sun_elevation_deg,
        'sun_azimuth_deg': sun_azimuth_deg,
        'width': width,
        'height': height,
        'normalized': normalize_ehz,
    }

    return pixels, meta


def _compute_ehz(pixels, width, height):
    """Compute diffuse horizontal illuminance from equirectangular sky image.

    E_hz = integral over upper hemisphere of L × cos(θ_z) × sin(θ_z) dθ dφ

    For equirectangular: each pixel covers dθ × dφ = (π/H) × (2π/W).
    Solid angle element: sin(θ_z) × dθ × dφ.
    """
    d_theta = math.pi / height
    d_phi = 2 * math.pi / width

    ehz = 0.0
    for row in range(height):
        elevation = math.pi / 2 - (row + 0.5) / height * math.pi
        theta_z = math.pi / 2 - elevation

        if theta_z > math.pi / 2:
            continue  # below horizon

        cos_z = math.cos(theta_z)
        sin_z = math.sin(theta_z)

        for col in range(width):
            idx = (row * width + col) * 4
            L = pixels[idx]  # grayscale, R=G=B
            ehz += L * cos_z * sin_z * d_theta * d_phi

    return ehz


def save_hdr(pixels, width, height, filepath):
    """Save pixel data as Radiance HDR (.hdr) file.

    Simple RGBE encoding — compatible with Blender's environment texture.
    """
    def float_to_rgbe(r, g, b):
        v = max(r, g, b)
        if v < 1e-32:
            return 0, 0, 0, 0
        mantissa, exponent = math.frexp(v)
        v = mantissa * 256.0 / v
        return (max(0, min(255, int(r * v))),
                max(0, min(255, int(g * v))),
                max(0, min(255, int(b * v))),
                max(0, min(255, exponent + 128)))

    with open(filepath, 'wb') as f:
        # Header
        f.write(b'#?RADIANCE\n')
        f.write(b'FORMAT=32-bit_rle_rgbe\n')
        f.write(b'\n')
        f.write(f'-Y {height} +X {width}\n'.encode())

        # Pixel data (uncompressed RGBE)
        for row in range(height):
            for col in range(width):
                idx = (row * width + col) * 4
                r, g, b, e = float_to_rgbe(pixels[idx], pixels[idx+1], pixels[idx+2])
                f.write(bytes([r, g, b, e]))


# ─────────────────────────────────────────────
# MAIN — GENERATE ALL 15 SKY TYPES
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate CIE Standard General Sky HDRIs')
    parser.add_argument('--type', type=int, default=0,
                        help='Sky type (1-15), or 0 for all')
    parser.add_argument('--sun-elevation', type=float, default=60.0,
                        help='Sun elevation in degrees (default: 60)')
    parser.add_argument('--sun-azimuth', type=float, default=180.0,
                        help='Sun azimuth in degrees (default: 180 = south)')
    parser.add_argument('--resolution', type=int, default=512,
                        help='Image width (height = width/2, default: 512)')
    parser.add_argument('--verify', action='store_true',
                        help='Verify E_hz integration after generation')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='Output directory (default: sky_hdri/)')
    args = parser.parse_args()

    out_dir = args.output_dir or os.path.join(os.path.dirname(__file__), 'sky_hdri')
    os.makedirs(out_dir, exist_ok=True)

    types_to_generate = [args.type] if args.type > 0 else list(range(1, 16))
    w = args.resolution
    h = w // 2

    for sky_id in types_to_generate:
        sky = CIE_SKY_TYPES[sky_id]
        print(f"\nGenerating CIE Sky Type {sky_id}: {sky['name']}")
        print(f"  Sun: elevation={args.sun_elevation}°, azimuth={args.sun_azimuth}°")
        print(f"  Resolution: {w}×{h}")

        pixels, meta = generate_sky_hdri(
            sky_id,
            sun_elevation_deg=args.sun_elevation,
            sun_azimuth_deg=args.sun_azimuth,
            width=w, height=h,
            normalize_ehz=True,
        )

        filename = f'cie_sky_type_{sky_id:02d}.hdr'
        filepath = os.path.join(out_dir, filename)
        save_hdr(pixels, w, h, filepath)
        print(f"  Saved: {filepath}")

        if args.verify:
            ehz = _compute_ehz(pixels, w, h)
            print(f"  E_hz verification: {ehz:.6f} (should be ~1.0)")

    print(f"\nDone. {len(types_to_generate)} sky HDRIs saved to {out_dir}")


if __name__ == '__main__':
    main()
