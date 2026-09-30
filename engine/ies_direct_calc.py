"""
Direct illuminance calculation using Lambert's cosine law: E = I*cos(theta)/d^2
No Blender — pure IES parsing + photometric math.

Supports multiple fixtures from fixture_config.py.
All fixtures are treated as area sources (discretized into sub-elements),
matching the mesh emitter approach used in Blender rendering.

Run:
    python3 ies_direct_calc.py
"""
import math
import os
import re
import sys

# Ensure fixture_config.py is importable from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_config import *


# ─────────────────────────────────────────────
# IES PARSING
# ─────────────────────────────────────────────

class IESData:
    """Parsed IES photometric data for one fixture."""
    def __init__(self, vert_angles, horiz_angles, candela, multiplier, peak_cd):
        self.vert_angles = vert_angles
        self.horiz_angles = horiz_angles
        self.candela = candela          # candela[horiz][vert], already scaled by multiplier
        self.multiplier = multiplier
        self.peak_cd = peak_cd


def parse_ies(ies_path):
    """Parse IES file, return IESData object."""
    with open(ies_path, 'r', errors='ignore') as f:
        text = f.read()

    tilt_match = re.search(r'TILT\s*=\s*\S+', text)
    token_text = text[tilt_match.end():]
    tokens = token_text.split()

    num_lamps   = int(tokens[0])
    lumens      = float(tokens[1])
    multiplier  = float(tokens[2])
    num_vert    = int(tokens[3])
    num_horiz   = int(tokens[4])

    name = os.path.basename(ies_path)
    print(f"IES [{name}]: {num_lamps} lamp(s), {lumens} lm/lamp, multiplier={multiplier}")
    print(f"     {num_vert} vert angles, {num_horiz} horiz angles")

    # Skip ballast factor, future use, input watts (3 values after the 10 param block)
    offset = 13  # 10 params + 3 extras
    vert_angles = [float(tokens[offset + i]) for i in range(num_vert)]
    offset += num_vert
    horiz_angles = [float(tokens[offset + i]) for i in range(num_horiz)]
    offset += num_horiz

    # Candela values: num_horiz planes x num_vert values each
    candela = []
    for h in range(num_horiz):
        plane = []
        for v in range(num_vert):
            cd = float(tokens[offset]) * multiplier
            plane.append(cd)
            offset += 1
        candela.append(plane)

    print(f"     Vert range: {vert_angles[0]} - {vert_angles[-1]} deg")
    print(f"     Horiz range: {horiz_angles[0]} - {horiz_angles[-1]} deg")
    peak = max(cd for plane in candela for cd in plane)
    print(f"     Peak candela: {peak:.1f} cd (with multiplier)")

    return IESData(vert_angles, horiz_angles, candela, multiplier, peak)


# ─────────────────────────────────────────────
# CANDELA INTERPOLATION
# ─────────────────────────────────────────────

def interpolate_candela(ies, theta_deg, phi_deg):
    """Interpolate candela value at (theta, phi) from IES data.
    theta = vertical angle from nadir (0 deg = straight down)
    phi = horizontal angle (azimuth)
    """
    vert_angles = ies.vert_angles
    horiz_angles = ies.horiz_angles
    candela = ies.candela

    # Clamp phi to IES range (most fixtures are symmetric)
    phi_deg = phi_deg % 360
    if horiz_angles[-1] <= 90:
        # Quarter symmetry
        if phi_deg > 270:
            phi_deg = 360 - phi_deg
        elif phi_deg > 180:
            phi_deg = phi_deg - 180
        elif phi_deg > 90:
            phi_deg = 180 - phi_deg
    elif horiz_angles[-1] <= 180:
        # Half symmetry
        if phi_deg > 180:
            phi_deg = 360 - phi_deg

    # Find vertical interpolation
    if theta_deg <= vert_angles[0]:
        vi = 0
        vt = 0.0
    elif theta_deg >= vert_angles[-1]:
        vi = len(vert_angles) - 2
        vt = 1.0
    else:
        vi, vt = 0, 0.0
        for i in range(len(vert_angles) - 1):
            if vert_angles[i] <= theta_deg <= vert_angles[i + 1]:
                vi = i
                span = vert_angles[i + 1] - vert_angles[i]
                vt = (theta_deg - vert_angles[i]) / span if span > 0 else 0
                break

    # Find horizontal interpolation
    if len(horiz_angles) == 1:
        hi = 0
        ht = 0.0
    elif phi_deg <= horiz_angles[0]:
        hi = 0
        ht = 0.0
    elif phi_deg >= horiz_angles[-1]:
        hi = len(horiz_angles) - 2
        ht = 1.0
    else:
        hi, ht = 0, 0.0
        for i in range(len(horiz_angles) - 1):
            if horiz_angles[i] <= phi_deg <= horiz_angles[i + 1]:
                hi = i
                span = horiz_angles[i + 1] - horiz_angles[i]
                ht = (phi_deg - horiz_angles[i]) / span if span > 0 else 0
                break

    # Bilinear interpolation
    if len(horiz_angles) == 1:
        c00 = candela[0][vi]
        c01 = candela[0][min(vi + 1, len(vert_angles) - 1)]
        return c00 * (1 - vt) + c01 * vt

    hi2 = min(hi + 1, len(horiz_angles) - 1)
    vi2 = min(vi + 1, len(vert_angles) - 1)
    c00 = candela[hi][vi]
    c01 = candela[hi][vi2]
    c10 = candela[hi2][vi]
    c11 = candela[hi2][vi2]
    c0 = c00 * (1 - vt) + c01 * vt
    c1 = c10 * (1 - vt) + c11 * vt
    return c0 * (1 - ht) + c1 * ht


# ─────────────────────────────────────────────
# ILLUMINANCE CALCULATIONS
# ─────────────────────────────────────────────

def compute_area_source_illuminance(fixture, ies, x, y, floor_z):
    """Direct illuminance from a mesh/area source at measurement point (x, y, floor_z).

    Discretizes the luminaire rectangle into Nx x Ny sub-elements.
    Each sub-element acts as a fractional point source.
    Uses fixture.mesh_dims_m for luminaire dimensions.

    Scales candela by fixture.get_lumen_scale() to account for linear fixtures
    whose length exceeds the IES-tested module length (e.g., 12' run of 3.917' modules).
    """
    lx, ly, lz = fixture.position  # meters
    length_m, width_m = fixture.mesh_dims_m
    nx = fixture.subdivisions_x
    ny = fixture.subdivisions_y
    lumen_scale = fixture.get_lumen_scale()

    E_total = 0.0
    for ix in range(nx):
        for iy in range(ny):
            # Sub-element center position (meters)
            sx = lx + (ix + 0.5) * length_m / nx - length_m / 2
            sy = ly + (iy + 0.5) * width_m / ny - width_m / 2
            sz = lz

            dx = x - sx
            dy = y - sy
            h = sz - floor_z

            horiz_dist = math.sqrt(dx * dx + dy * dy)
            d = math.sqrt(horiz_dist * horiz_dist + h * h)
            if d < 1e-10:
                continue
            cos_theta = h / d
            theta_deg = math.degrees(math.atan2(horiz_dist, h))
            phi_deg = math.degrees(math.atan2(dy, dx)) % 360

            I = interpolate_candela(ies, theta_deg, phi_deg)
            E_total += I * lumen_scale * cos_theta / (d * d * nx * ny)

    return E_total


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 70)
    print("DIRECT ILLUMINANCE CALCULATOR (analytical, no Blender)")
    print("=" * 70)
    print(f"\nRoom: {ROOM_WIDTH_FT:.0f}' x {ROOM_DEPTH_FT:.0f}' x {ROOM_HEIGHT_FT:.0f}'")
    print(f"Workplane: {WORKPLANE_HEIGHT_FT:.1f}' AFF")
    print(f"Grid: {GRID_SPACING_FT:.0f}' spacing\n")

    # Parse IES data for each fixture
    fixture_ies = []
    for i, fix in enumerate(FIXTURES, 1):
        print(f"Fixture {i}: {fix}")
        length_m, width_m = fix.mesh_dims_m
        print(f"  Aperture: {length_m*100:.1f} cm x {width_m*100:.1f} cm ({fix.mesh_area_m2:.6f} m^2)")
        print(f"  Discretization: {fix.subdivisions_x} x {fix.subdivisions_y}")
        ies = parse_ies(fix.ies_path)
        fixture_ies.append((fix, ies))
        print()

    floor_z = WORKPLANE_HEIGHT  # meters

    # Build grid (meters internally)
    hw = ROOM_WIDTH / 2
    hd = ROOM_DEPTH / 2

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

    # Compute illuminance at each grid point
    grid = []
    for y in reversed(y_points):
        row = []
        for x in x_points:
            E_total = 0.0
            for fix, ies in fixture_ies:
                E = compute_area_source_illuminance(fix, ies, x, y, floor_z)
                E_total += E
            row.append(E_total)
        grid.append(row)

    # Print results
    all_vals = [v for r in grid for v in r]
    lux_max = max(all_vals)
    lux_min = min(all_vals)
    lux_avg = sum(all_vals) / len(all_vals)
    fc_max  = lux_max * LUX_TO_FC
    fc_min  = lux_min * LUX_TO_FC
    fc_avg  = lux_avg * LUX_TO_FC

    print(f"DIRECT ILLUMINANCE (no inter-reflections)")
    print(f"  Max: {lux_max:.1f} lux / {fc_max:.1f} fc")
    print(f"  Min: {lux_min:.1f} lux / {fc_min:.1f} fc")
    print(f"  Avg: {lux_avg:.1f} lux / {fc_avg:.1f} fc")
    print()

    # Grid in feet and footcandles
    x_ft = [xm * M_TO_FT for xm in x_points]
    y_ft = [ym * M_TO_FT for ym in y_points]

    header = "  Y\\X  " + "".join(f" {xf:+6.1f}" for xf in x_ft)
    print(header)
    for i, row in enumerate(grid):
        yf = y_ft[len(y_ft) - 1 - i]  # reversed order
        fc_vals = [v * LUX_TO_FC for v in row]
        line = f"{yf:+6.1f} " + "".join(f" {v:6.1f}" for v in fc_vals)
        print(line)

    print(f"\n(Values in footcandles. Multiply by 10.764 for lux.)")


if __name__ == '__main__':
    main()
