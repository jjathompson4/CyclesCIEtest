"""
CIE 171:2006 Test Case Definitions — Geometry, Reference Values, Tolerances.

Each test case is a dict with:
  - source parameters (position, distribution, I0)
  - measurement points {label: (x, y)}
  - reference values {label: E_lux}
  - tolerances (per-point, global)
"""

import math

# ─────────────────────────────────────────────
# Test 5.2 — Point Light Sources (Diffuse)
# ─────────────────────────────────────────────

TEST_5_2_DIFFUSE = {
    'name': 'CIE 5.2 — Point source, diffuse (Lambertian)',
    'source_height_m': 3.0,         # point source at (0, 0, 3)
    'surface_size_m': 4.0,          # 4m × 4m measurement surface at z=0
    'I0_cd': 1000.0,                # peak intensity at nadir
    'flux_lm': math.pi * 1000.0,    # Φ = π·I₀ for Lambertian

    # Measurement points — offsets from surface center (meters)
    'points': {
        'A': (0.0, 0.0),
        'B': (0.5, 0.0),
        'C': (1.0, 0.0),
        'D': (1.5, 0.0),
        'E': (0.5, 0.5),
        'F': (1.0, 0.5),
        'G': (1.5, 0.5),
        'H': (1.0, 1.0),
        'I': (1.5, 1.0),
        'J': (1.5, 1.5),
    },

    # Reference values from CIE 171:2006, Table 11
    'reference_I_cd': {
        'A': 1000.0,  'B': 986.4,  'C': 948.7,  'D': 894.4,
        'E': 973.3,   'F': 937.0,  'G': 884.7,  'H': 904.5,
        'I': 857.2,   'J': 816.5,
    },
    'reference_E_lux': {
        'A': 111.11, 'B': 105.21, 'C': 90.02,  'D': 71.11,
        'E': 99.73,  'F': 85.64,  'G': 68.06,  'H': 74.36,
        'I': 59.98,  'J': 49.39,
    },

    # Tolerances
    'point_tolerance': 0.05,   # 5% per point
    'global_tolerance': 0.10,  # 10% global (max error)
}


def compute_analytical_5_2(test_case):
    """Compute illuminance at all measurement points using E = I(θ)·cos(θ)/d².

    For a Lambertian source: I(θ) = I₀·cos(θ), so E = I₀·cos²(θ)/d².
    Equivalently: E = I₀·h²/d⁴ where h = source height, d = slant distance.

    Returns:
        dict {label: {'d_m': float, 'theta_deg': float, 'I_cd': float, 'E_lux': float}}
    """
    h = test_case['source_height_m']
    I0 = test_case['I0_cd']
    results = {}

    for label, (x, y) in test_case['points'].items():
        horiz = math.sqrt(x * x + y * y)
        d = math.sqrt(horiz * horiz + h * h)
        cos_theta = h / d
        theta_deg = math.degrees(math.acos(cos_theta))

        # Lambertian: I(θ) = I₀·cos(θ)
        I_theta = I0 * cos_theta

        # E = I(θ)·cos(θ)/d²
        E = I_theta * cos_theta / (d * d)

        results[label] = {
            'd_m': d,
            'theta_deg': theta_deg,
            'I_cd': I_theta,
            'E_lux': E,
        }

    return results


# ─────────────────────────────────────────────
# Test 5.3 — Area Light Sources (Diffuse)
# ─────────────────────────────────────────────

TEST_5_3_DIFFUSE = {
    'name': 'CIE 5.3 — Area light source, diffuse (Lambertian)',
    'room_width_m': 4.0,
    'room_depth_m': 4.0,
    'room_height_m': 3.0,
    'source_width_m': 1.0,
    'source_depth_m': 1.0,
    'I0_cd': 1000.0,
    'flux_lm': math.pi * 1000.0,

    # Wall points A–F: on south wall (y=0), x=2m (room center), z varies
    # Floor points G–N: on floor (z=0), x=2m, y varies
    'points_wall': {
        'A': (2.0, 0.0, 2.75),
        'B': (2.0, 0.0, 2.25),
        'C': (2.0, 0.0, 1.75),
        'D': (2.0, 0.0, 1.25),
        'E': (2.0, 0.0, 0.75),
        'F': (2.0, 0.0, 0.25),
    },
    'points_floor': {
        'G': (2.0, 0.25, 0.0),
        'H': (2.0, 0.75, 0.0),
        'I': (2.0, 1.25, 0.0),
        'J': (2.0, 1.75, 0.0),
        'K': (2.0, 2.25, 0.0),
        'L': (2.0, 2.75, 0.0),
        'M': (2.0, 3.25, 0.0),
        'N': (2.0, 3.75, 0.0),
    },

    # CIE 171:2006, Table 12
    'reference_E_lux': {
        'A': 32.68, 'B': 75.09, 'C': 81.38, 'D': 69.12, 'E': 53.41, 'F': 39.90,
        'G': 61.27, 'H': 79.18, 'I': 95.52, 'J': 105.89, 'K': 105.89, 'L': 95.52,
        'M': 79.18, 'N': 61.27,
    },

    'point_tolerance': 0.05,
    'global_tolerance': 0.10,
}


def compute_analytical_5_3(test_case):
    """Illuminance from a Lambertian area source via numerical integration.

    Discretizes the 1m×1m source (centered at ceiling) into N×N sub-elements.
    Each sub-element contributes: dE = (I₀/N²) · cos(θ_s) · cos(θ_r) / d²

    Source center: (2, 2, 3). Source normal: -Z (downward).
    """
    I0 = test_case['I0_cd']
    src_cx, src_cy = 2.0, 2.0
    src_w = test_case['source_width_m']
    src_d = test_case['source_depth_m']
    src_z = test_case['room_height_m']

    N = 200  # fine grid
    I_sub = I0 / (N * N)

    results = {}
    all_points = {}
    all_points.update(test_case['points_wall'])
    all_points.update(test_case['points_floor'])

    for label, (px, py, pz) in all_points.items():
        if label in test_case['points_wall']:
            n_rx, n_ry, n_rz = 0.0, 1.0, 0.0  # wall normal into room
        else:
            n_rx, n_ry, n_rz = 0.0, 0.0, 1.0  # floor normal up

        E = 0.0
        for ix in range(N):
            sx = src_cx - src_w/2 + (ix + 0.5) * src_w / N
            for iy in range(N):
                sy = src_cy - src_d/2 + (iy + 0.5) * src_d / N

                dx = px - sx
                dy = py - sy
                dz = pz - src_z

                d2 = dx*dx + dy*dy + dz*dz
                if d2 < 1e-20:
                    continue
                d = math.sqrt(d2)

                # Source normal -Z: cos(θ_s) = -dz/d
                cos_s = -dz / d
                if cos_s <= 0:
                    continue

                # Receiver: angle of incidence = dot(normal, direction_to_source)
                cos_r = (n_rx*(-dx) + n_ry*(-dy) + n_rz*(-dz)) / d
                if cos_r <= 0:
                    continue

                E += I_sub * cos_s * cos_r / d2

        results[label] = {'E_lux': E}

    return results


# ─────────────────────────────────────────────
# Test 5.6 — Light Reflection over Diffuse Surfaces
# ─────────────────────────────────────────────

# Scenario 2: S₂ = 4m × 4m floor, ρ=30%
# S₁-v: vertical wall, 4m × 2.5m, positioned 50cm above ground, 2m from S₂ center
# S₁-hz: horizontal ceiling, 4m × 4m, 3m above ground
# Reference values: E/(E_hz·ρ) as percentages (= form factor × 100)
# Points A–F on S₁-v (vertical), G–N on S₁-hz (horizontal)
# From CIE Fig. 11: same point layout as test 5.3

TEST_5_6_SCENARIO2 = {
    'name': 'CIE 5.6 — Diffuse reflection, Scenario 2 (S₂ = 4m×4m)',

    # S₂ (reflective ground surface)
    's2_width_m': 4.0,
    's2_depth_m': 4.0,
    's2_reflectance': 0.30,

    # S₁-v (vertical measurement wall)
    # 4m wide × 2.5m high, bottom edge at z=0.5m, at y=0 (2m from S₂ center)
    's1v_width_m': 4.0,
    's1v_height_m': 2.5,
    's1v_z_bottom_m': 0.5,

    # S₁-hz (horizontal measurement ceiling)
    # 4m × 4m at z=3m
    's1hz_width_m': 4.0,
    's1hz_depth_m': 4.0,
    's1hz_z_m': 3.0,

    # Measurement points — from CIE Fig. 11
    # S₁-v points: on wall at x=2m, spaced 0.5m starting 0.25m from floor
    # In CIE Fig. 11, labels A–F go from BOTTOM (A near floor) to TOP (F near ceiling)
    # A = z=0.25 (but would be below S₁-v bottom at z=0.5, hence undefined for Scenario 2)
    # B = z=0.75, C = z=1.25, D = z=1.75, E = z=2.25, F = z=2.75
    'points_wall': {
        'B': (2.0, 0.0, 0.75),
        'C': (2.0, 0.0, 1.25),
        'D': (2.0, 0.0, 1.75),
        'E': (2.0, 0.0, 2.25),
        'F': (2.0, 0.0, 2.75),
    },
    # Note: Point A is undefined ("-") in Table 17 for Scenario 2

    # S₁-hz points (G–N): on ceiling at x=2m, y varies
    'points_ceiling': {
        'G': (2.0, 0.25, 3.0),
        'H': (2.0, 0.75, 3.0),
        'I': (2.0, 1.25, 3.0),
        'J': (2.0, 1.75, 3.0),
        'K': (2.0, 2.25, 3.0),
        'L': (2.0, 2.75, 3.0),
        'M': (2.0, 3.25, 3.0),
        'N': (2.0, 3.75, 3.0),
    },

    # Reference: E/(E_hz·ρ) as percentages (Table 17)
    # These are configuration factors (form factors) × 100
    'reference_form_factor_pct': {
        'B': 35.901, 'C': 27.992, 'D': 21.639, 'E': 16.716, 'F': 12.967,
        'G': 26.80, 'H': 30.94, 'I': 33.98, 'J': 35.57,
        'K': 35.57, 'L': 33.98, 'M': 30.94, 'N': 26.80,
    },

    'point_tolerance': 0.05,
    'global_tolerance': 0.10,
}


def compute_analytical_5_6(test_case):
    """Compute form factors from S₂ to each measurement point analytically.

    For a uniform Lambertian reflector S₂, the illuminance at point P on S₁ is:
        E_P = M₂ × F₁₂ = (E_hz × ρ) × F₁₂

    So E/(E_hz·ρ) = F₁₂ = configuration factor.

    F₁₂ = ∫∫ cos(θ₁)·cos(θ₂) / (π·d²) dA₂

    where θ₁ = angle at receiver, θ₂ = angle at S₂, d = distance.
    We numerically integrate over S₂.
    """
    s2_w = test_case['s2_width_m']
    s2_d = test_case['s2_depth_m']
    # S₂ is on the floor from (0,0,0) to (4,4,0)
    # S₂ center at (2, 2, 0)

    N = 200  # integration grid
    dA = (s2_w / N) * (s2_d / N)

    results = {}
    all_points = {}
    all_points.update(test_case['points_wall'])
    all_points.update(test_case['points_ceiling'])

    for label, (px, py, pz) in all_points.items():
        # Determine receiver normal
        if label in test_case['points_wall']:
            n_rx, n_ry, n_rz = 0.0, 1.0, 0.0  # wall facing +Y (into room)
        else:
            n_rx, n_ry, n_rz = 0.0, 0.0, -1.0  # ceiling facing down

        F12 = 0.0
        for ix in range(N):
            sx = (ix + 0.5) * s2_w / N  # S₂ spans [0, 4] in x
            for iy in range(N):
                sy = (iy + 0.5) * s2_d / N  # S₂ spans [0, 4] in y
                sz = 0.0  # floor

                dx = px - sx
                dy = py - sy
                dz = pz - sz

                d2 = dx*dx + dy*dy + dz*dz
                if d2 < 1e-20:
                    continue
                d = math.sqrt(d2)

                # S₂ normal is +Z (floor facing up)
                cos_s = dz / d  # cos angle at S₂
                if cos_s <= 0:
                    continue

                # Receiver angle: dot(receiver_normal, direction_to_S₂)
                # Direction from point to S₂ element = (-dx, -dy, -dz)/d
                cos_r = (n_rx * (-dx) + n_ry * (-dy) + n_rz * (-dz)) / d
                if cos_r <= 0:
                    continue

                # Form factor element: cos(θ₁)·cos(θ₂) / (π·d²) · dA
                F12 += cos_s * cos_r / (math.pi * d2) * dA

        results[label] = F12 * 100  # convert to percentage

    return results


# ─────────────────────────────────────────────
# Test 5.4 — Luminous Flux Conservation
# ─────────────────────────────────────────────

TEST_5_4 = {
    'name': 'CIE 5.4 — Luminous flux conservation (artificial lighting)',
    'room_size_m': 4.0,             # 4m × 4m × 3m room
    'room_height_m': 3.0,
    'flux_lm': 10000.0,             # isotropic point source, 10,000 lm

    # For an isotropic source in a closed room with black surfaces (ρ=0),
    # all emitted flux must reach the room surfaces.
    # Total surface area: 2×(4×4) + 4×(4×3) = 32 + 48 = 80 m²
    'total_surface_m2': 80.0,

    # Reference: Φ_surfaces / Φ_emitted = 1.0 (perfect conservation)
    'reference_ratio': 1.0,

    # Tolerances — using same 5%/10% as other Section 5 tests
    'point_tolerance': 0.05,
    'global_tolerance': 0.10,
}


# ─────────────────────────────────────────────
# Test 5.8 — Internal Reflected Component (Diffuse)
# ─────────────────────────────────────────────

TEST_5_8 = {
    'name': 'CIE 5.8 — Internal reflected component for diffuse surfaces',
    'room_size_m': 4.0,             # 4m × 4m × 4m cube
    'total_surface_m2': 96.0,       # S_T = 6 × 4² = 96 m²
    'flux_lm': 10000.0,             # isotropic point source at room center

    # Reflectances to test
    'reflectances': [0.00, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95],

    # Reference indirect illuminance from CIE 171:2006, Table 20
    # E_avg = (1/S_T) × ρΦ/(1-ρ)
    'reference_E_indirect': {
        0.00: 0.00,
        0.05: 5.48,
        0.10: 11.6,
        0.20: 26.0,
        0.30: 44.6,
        0.40: 69.4,
        0.50: 104.0,
        0.60: 156.0,
        0.70: 243.0,
        0.80: 417.0,
        0.90: 937.0,
        0.95: 1979.0,
    },

    # Direct illuminance for an isotropic source in a 4m cube:
    # E_direct = Φ / S_T = 10000 / 96 ≈ 104.17 lx (uniform on all surfaces)
    # NVIDIA Iray measured 105.24 lx (slightly higher due to near-field)
    'reference_E_direct': 104.17,

    # Tolerances
    'point_tolerance': 0.05,   # 5% per measurement
    'global_tolerance': 0.10,  # 10% global
}


# ─────────────────────────────────────────────
# Test 5.7 — Diffuse Reflections with Internal Obstructions
# ─────────────────────────────────────────────

# Geometry (CIE Fig. 12):
#   S₂: vertical wall 4m×3m at y=4, ρ=60%, receives E_v from 60° sun
#   S₁-v: vertical measurement wall 4m×3m at y=0, ρ=0%
#   S₁-hz: horizontal measurement floor 4m×2.5m, ρ=0%
#   Obstruction: 4m×1m×0.2m box at y=[2.5,2.7], z=[0,1]
# Reference: E/(E_v·ρ) as percentages
# NOTE: CIE Table 19 values are INCORRECT — using NVIDIA-corrected values

TEST_5_7 = {
    'name': 'CIE 5.7 — Diffuse reflections with internal obstructions',

    # S₂ (reflective vertical wall)
    's2_width_m': 4.0,
    's2_height_m': 3.0,
    's2_reflectance': 0.60,
    's2_y_m': 4.0,

    # S₁-v (vertical measurement wall)
    's1v_width_m': 4.0,
    's1v_height_m': 3.0,

    # S₁-hz (horizontal measurement floor)
    's1hz_width_m': 4.0,
    's1hz_depth_m': 2.5,

    # Obstruction (black box)
    'obs_width_m': 4.0,
    'obs_height_m': 1.0,
    'obs_thickness_m': 0.20,
    'obs_y_near_m': 2.5,   # face toward S₁
    'obs_y_far_m': 2.7,    # face toward S₂
    'obs_z_top_m': 1.0,

    # Measurement points (CIE Fig. 13)
    # S₁-v: A at top, F at bottom, x=2m center
    'points_wall': {
        'A': (2.0, 0.0, 2.75),
        'B': (2.0, 0.0, 2.25),
        'C': (2.0, 0.0, 1.75),
        'D': (2.0, 0.0, 1.25),
        'E': (2.0, 0.0, 0.75),
        'F': (2.0, 0.0, 0.25),
    },
    # S₁-hz: G nearest S₁-v, K nearest obstruction
    'points_floor': {
        'G': (2.0, 0.25, 0.0),
        'H': (2.0, 0.75, 0.0),
        'I': (2.0, 1.25, 0.0),
        'J': (2.0, 1.75, 0.0),
        'K': (2.0, 2.25, 0.0),
    },

    # NVIDIA-corrected reference: E/(E_v·ρ) as percentages
    # Source: Table 14 (corrected Table 19), p.24 of NVIDIA Iray report
    'reference_form_factor_pct': {
        'A': 16.07, 'B': 16.33, 'C': 15.40, 'D': 13.32, 'E': 10.32, 'F': 7.08,
        'G': 3.38, 'H': 3.63, 'I': 3.01, 'J': 0.00, 'K': 0.00,
    },

    'point_tolerance': 0.05,
    'global_tolerance': 0.10,
}


def _ray_hits_box(px, py, pz, sx, sy, sz,
                  bx0, bx1, by0, by1, bz0, bz1):
    """AABB slab intersection test for ray from P to S (t in [0,1])."""
    dx, dy, dz = sx - px, sy - py, sz - pz
    t_min, t_max = 0.0, 1.0

    for p0, d0, lo, hi in [(px, dx, bx0, bx1),
                            (py, dy, by0, by1),
                            (pz, dz, bz0, bz1)]:
        if abs(d0) < 1e-12:
            if p0 < lo or p0 > hi:
                return False
        else:
            t1 = (lo - p0) / d0
            t2 = (hi - p0) / d0
            if t1 > t2:
                t1, t2 = t2, t1
            t_min = max(t_min, t1)
            t_max = min(t_max, t2)
            if t_min > t_max:
                return False
    return True


def compute_analytical_5_7(test_case):
    """Form factors from S₂ to measurement points, with obstruction occlusion.

    Same integrand as test 5.6 but S₂ is a vertical wall (normal -Y)
    and rays are tested against the obstruction AABB.
    """
    s2_w = test_case['s2_width_m']
    s2_h = test_case['s2_height_m']
    s2_y = test_case['s2_y_m']

    # Obstruction AABB
    bx0, bx1 = 0.0, test_case['obs_width_m']
    by0, by1 = test_case['obs_y_near_m'], test_case['obs_y_far_m']
    bz0, bz1 = 0.0, test_case['obs_z_top_m']

    N = 200
    dA = (s2_w / N) * (s2_h / N)

    results = {}
    all_points = {}
    all_points.update(test_case['points_wall'])
    all_points.update(test_case['points_floor'])

    for label, (px, py, pz) in all_points.items():
        if label in test_case['points_wall']:
            n_rx, n_ry, n_rz = 0.0, 1.0, 0.0   # wall facing +Y
        else:
            n_rx, n_ry, n_rz = 0.0, 0.0, 1.0   # floor facing +Z

        F12 = 0.0
        for ix in range(N):
            sx = (ix + 0.5) * s2_w / N
            for iy in range(N):
                sz = (iy + 0.5) * s2_h / N   # S₂ is vertical: z varies
                sy = s2_y                      # S₂ at y=4.0

                dx = px - sx
                dy = py - sy
                dz = pz - sz

                d2 = dx * dx + dy * dy + dz * dz
                if d2 < 1e-20:
                    continue
                d = math.sqrt(d2)

                # S₂ normal is -Y
                cos_s = -dy / d
                if cos_s <= 0:
                    continue

                cos_r = (n_rx * (-dx) + n_ry * (-dy) + n_rz * (-dz)) / d
                if cos_r <= 0:
                    continue

                # Occlusion test
                if _ray_hits_box(px, py, pz, sx, sy, sz,
                                 bx0, bx1, by0, by1, bz0, bz1):
                    continue

                F12 += cos_s * cos_r / (math.pi * d2) * dA

        results[label] = F12 * 100

    return results


def compute_analytical_5_8(test_case):
    """Compute expected indirect illuminance for each reflectance.

    E_indirect = (1/S_T) × ρΦ/(1-ρ)  (CIE Equation 16)

    Also computes total = direct + indirect for comparison with Blender
    (which measures total illuminance, not indirect separately).

    Returns:
        dict {rho: {'E_indirect': float, 'E_direct': float, 'E_total': float}}
    """
    S_T = test_case['total_surface_m2']
    phi = test_case['flux_lm']
    E_direct = phi / S_T  # isotropic: uniform on all surfaces

    results = {}
    for rho in test_case['reflectances']:
        if rho < 1e-6:
            E_indirect = 0.0
        else:
            E_indirect = (1.0 / S_T) * (rho * phi) / (1.0 - rho)
        results[rho] = {
            'E_indirect': E_indirect,
            'E_direct': E_direct,
            'E_total': E_direct + E_indirect,
        }
    return results
