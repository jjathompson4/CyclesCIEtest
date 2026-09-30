"""
Shared fixture configuration for Blender Cycles PBR lighting simulation.

All user-facing measurements are in IMPERIAL units (feet/inches).
Internal calculations use SI (meters) since Blender's API requires meters.

Every fixture uses a mesh emitter with realistic physical aperture dimensions.
No point sources — even small downlights have real aperture sizes.

Used by:
    scene_builder.py     (Blender scene construction + mesh emitter shader)
    validate_lux.py      (Blender headless rendering + lux extraction)
    render_perspective.py (Blender perspective view rendering)
    ies_direct_calc.py   (standalone analytical direct illuminance)
"""
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional, Tuple
import os
import re

# ─────────────────────────────────────────────
# UNIT CONVERSIONS
# ─────────────────────────────────────────────

FT_TO_M = 0.3048
IN_TO_M = 0.0254
M_TO_FT = 1.0 / FT_TO_M
LUX_TO_FC = 1.0 / 10.764


def ft(x):
    """Convert feet to meters."""
    return x * FT_TO_M


def inches(x):
    """Convert inches to meters."""
    return x * IN_TO_M


# ─────────────────────────────────────────────
# ROOM GEOMETRY (imperial)
# ─────────────────────────────────────────────

ROOM_WIDTH_FT  = 20.0   # feet
ROOM_DEPTH_FT  = 20.0   # feet
ROOM_HEIGHT_FT = 10.0   # feet

# Derived SI values for Blender
ROOM_WIDTH  = ft(ROOM_WIDTH_FT)    # 6.096 m
ROOM_DEPTH  = ft(ROOM_DEPTH_FT)    # 6.096 m
ROOM_HEIGHT = ft(ROOM_HEIGHT_FT)   # 3.048 m

# ─────────────────────────────────────────────
# MEASUREMENT
# ─────────────────────────────────────────────

WORKPLANE_HEIGHT_FT = 2.5    # feet (standard desk / workplane)
WORKPLANE_HEIGHT = ft(WORKPLANE_HEIGHT_FT)  # 0.762 m

GRID_SPACING_FT = 2.0        # feet
GRID_SPACING = ft(GRID_SPACING_FT)  # 0.6096 m

# ─────────────────────────────────────────────
# MATERIALS
# ─────────────────────────────────────────────

REFLECTANCE_CEILING = 0.80
REFLECTANCE_WALLS   = 0.50
REFLECTANCE_FLOOR   = 0.20

# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────

RENDER_SAMPLES = 1024
LIGHT_LUMENS   = 3000   # fallback if no IES file
MAX_BOUNCES    = None   # None = Cycles default (~12 bounces); 0 = direct-only

# ─────────────────────────────────────────────
# IES FILE PATHS
# ─────────────────────────────────────────────

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# The demo floor plan was built around manufacturer IES files (a USAI 4" downlight,
# BioPro linears, a Selux wall washer) that can't be redistributed. A generic
# Lambertian distribution stands in so the demo runs; point these constants at
# your own IES files to reproduce real luminaires. The CIE 171 tests don't use
# them: they load the synthetic files in cie171/ies directly.
IES_DIR = os.path.join(_BASE_DIR, "cie171", "ies")
_GENERIC_IES = os.path.join(IES_DIR, "cie_diffuse_1000cd.ies")
IES_BIOPRO_DIRECT   = _GENERIC_IES
IES_BIOPRO_INDIRECT = _GENERIC_IES
IES_B4RD            = _GENERIC_IES
IES_SELUX_L36       = _GENERIC_IES


# ─────────────────────────────────────────────
# IES FILE UTILITIES
# ─────────────────────────────────────────────

M_TO_FT_CONST = 1.0 / 0.3048   # used in IES parsing (avoid circular ref)

@lru_cache(maxsize=32)
def parse_ies_module_length(ies_path):
    """Parse IES file luminous opening dimensions, return module length in feet.

    IES LM-63 line 7 (10 tokens after TILT=):
        num_lamps  lumens  multiplier  n_vert  n_horiz  photo_type  units  width  length  height
    units: 1 = feet, 2 = meters

    For linear fixtures, the larger of width/length is the module length.
    Returns 0.0 if the file can't be parsed or has no meaningful opening.
    """
    try:
        with open(ies_path, 'r', errors='ignore') as f:
            text = f.read()
        tilt_match = re.search(r'TILT\s*=\s*\S+', text)
        if not tilt_match:
            return 0.0
        tokens = text[tilt_match.end():].split()
        if len(tokens) < 10:
            return 0.0

        units = int(tokens[6])       # 1=feet, 2=meters
        width = float(tokens[7])     # luminous opening width
        length = float(tokens[8])    # luminous opening length

        module_dim = max(abs(width), abs(length))
        if module_dim < 1e-6:
            return 0.0

        # Convert to feet if in meters
        if units == 2:
            module_dim *= M_TO_FT_CONST

        return module_dim
    except Exception:
        return 0.0


# ─────────────────────────────────────────────
# FIXTURE DEFINITION
# ─────────────────────────────────────────────

@dataclass
class Fixture:
    """Configuration for one luminaire in the scene.

    Every fixture is a mesh emitter with realistic physical aperture dimensions.
    The corrected IES shader (IES_Fac / (4 * A * cos(theta))) ensures
    photometric accuracy independent of mesh area.

    All user-facing dimensions are in imperial (feet/inches).
    Properties provide SI (meter) conversions for Blender.
    """
    ies_path: str                         # absolute path to .ies file
    position_ft: tuple                    # (x, y, z) center position in feet
    rotation: tuple = (0.0, 0.0, 0.0)    # Euler angles (rx, ry, rz) in radians
    # Physical aperture dimensions
    length_ft: float = 0.0               # aperture length along X (feet); 0 = use width_inches
    width_inches: float = 4.0            # aperture width along Y (inches); default 4"
    cos_clamp: float = 0.087             # 1/cos clamp (~85 deg max emission angle)
    lumen_scale: float = 0.0            # 0 = auto from IES module length; >0 = manual override
    # Color (emission tint)
    color_temp_k: float = 0              # CCT in Kelvin; 0 = white (no tint)
    color_rgb: tuple = None              # (r, g, b) 0-1 range; overrides color_temp_k if set
    # Analytical calculation discretization
    subdivisions_x: int = 10
    subdivisions_y: int = 10

    @property
    def position(self):
        """Position in meters for Blender."""
        return tuple(v * FT_TO_M for v in self.position_ft)

    @property
    def mesh_area_m2(self):
        """Compute mesh area in m^2 from physical dimensions."""
        l = self.length_ft * FT_TO_M if self.length_ft > 0 else self.width_inches * IN_TO_M
        w = self.width_inches * IN_TO_M if self.width_inches > 0 else IN_TO_M
        return l * w

    @property
    def mesh_half_dims_m(self):
        """Return (half_x, half_y) in meters for mesh vertex construction."""
        l = self.length_ft * FT_TO_M if self.length_ft > 0 else self.width_inches * IN_TO_M
        w = self.width_inches * IN_TO_M if self.width_inches > 0 else IN_TO_M
        return (l / 2.0, w / 2.0)

    @property
    def mesh_dims_m(self):
        """Return (length_m, width_m) in meters for analytical calcs."""
        l = self.length_ft * FT_TO_M if self.length_ft > 0 else self.width_inches * IN_TO_M
        w = self.width_inches * IN_TO_M if self.width_inches > 0 else IN_TO_M
        return (l, w)

    def get_lumen_scale(self):
        """Compute effective lumen scaling factor for this fixture.

        For linear fixtures whose length exceeds the IES module length,
        auto-computes scale = fixture_length / IES_module_length.
        For round fixtures (length_ft=0) or matching-length linears, returns 1.0.
        Manual override via lumen_scale > 0 takes precedence.
        """
        if self.lumen_scale > 0:
            return self.lumen_scale
        if self.length_ft > 0:
            module_len = parse_ies_module_length(self.ies_path)
            if module_len > 0 and self.length_ft > module_len * 1.01:
                return self.length_ft / module_len
        return 1.0

    def __str__(self):
        name = os.path.basename(self.ies_path)
        x, y, z = self.position_ft
        if self.length_ft > 0:
            dims = f"{self.length_ft:.3f}' x {self.width_inches:.0f}\""
        else:
            dims = f"{self.width_inches:.0f}\" x {self.width_inches:.0f}\""
        return f"MESH at ({x:.1f}, {y:.1f}, {z:.1f}) ft [{dims}] — {name}"


# ─────────────────────────────────────────────
# ROOM DEFINITION (multi-room floor plans)
# ─────────────────────────────────────────────

@dataclass
class Room:
    """A rectangular room in a multi-room floor plan.

    Origin is at the bottom-left corner (min X, min Y) in plan view.
    All dimensions in imperial (feet).
    """
    name: str
    origin_ft: tuple                  # (x, y) bottom-left corner in feet
    width_ft: float                   # X dimension
    depth_ft: float                   # Y dimension
    height_ft: float = 9.0            # ceiling height
    reflectances: dict = field(default_factory=lambda: {
        'ceiling': 0.80, 'walls': 0.50, 'floor': 0.20
    })

    @property
    def center_ft(self):
        """Center point (x, y) in feet."""
        return (self.origin_ft[0] + self.width_ft / 2,
                self.origin_ft[1] + self.depth_ft / 2)


# ─────────────────────────────────────────────
# CALC GRID DEFINITION
# ─────────────────────────────────────────────

@dataclass
class CalcGrid:
    """Configuration for a calculation point grid (illuminance measurement surface).

    ClimateStudio-style calc plane: defines a rectangular measurement area on a
    surface. The system auto-generates a grid of sensor points and measures
    illuminance via Cycles texture baking.

    Sensors are invisible to the simulation (holdout material).
    All dimensions in imperial (feet).
    """
    name: str                                 # display name (e.g., 'Workplane', 'North_Wall')
    surface: str = 'floor'                    # 'floor', 'ceiling', 'wall_north/south/east/west'
    width_ft: float = 0.0                     # measurement area width (0 = auto from room)
    height_ft: float = 0.0                    # measurement area height (0 = auto from room)
    spacing_ft: float = 2.0                   # grid point spacing
    inset_ft: float = 1.0                     # buffer from room edges
    offset_ft: float = 2.5                    # offset from surface (e.g., workplane height above floor)
    bake_resolution: int = 256                # bake texture resolution (pixels per side)
    position_ft: tuple = None                 # explicit (x, y, z) in feet — overrides surface logic
    room_name: str = ''                       # which room this grid belongs to (for reporting)
    boundary_ft: list = None                  # polygon vertices [[x,y], ...] in local feet (relative to position)

    @property
    def position_m(self):
        """Position in meters. Uses explicit position_ft if set, otherwise surface-based."""
        if self.position_ft is not None:
            return tuple(v * FT_TO_M for v in self.position_ft)
        hw = ROOM_WIDTH / 2
        hd = ROOM_DEPTH / 2
        off = self.offset_ft * FT_TO_M
        surface_positions = {
            'floor':      (0, 0, off),
            'ceiling':    (0, 0, ROOM_HEIGHT - off),
            'wall_north': (0, hd - off, ROOM_HEIGHT / 2),
            'wall_south': (0, -hd + off, ROOM_HEIGHT / 2),
            'wall_east':  (hw - off, 0, ROOM_HEIGHT / 2),
            'wall_west':  (-hw + off, 0, ROOM_HEIGHT / 2),
        }
        return surface_positions.get(self.surface, (0, 0, off))

    @property
    def normal(self):
        """Surface normal direction (points into the room)."""
        normals = {
            'floor':      (0, 0, 1),
            'ceiling':    (0, 0, -1),
            'wall_north': (0, -1, 0),
            'wall_south': (0, 1, 0),
            'wall_east':  (-1, 0, 0),
            'wall_west':  (1, 0, 0),
        }
        return normals.get(self.surface, (0, 0, 1))

    @property
    def mesh_dims_m(self):
        """Return (width_m, height_m) for the measurement mesh."""
        inset_m = self.inset_ft * FT_TO_M * 2  # inset from both sides
        if self.surface in ('floor', 'ceiling'):
            w = (self.width_ft * FT_TO_M if self.width_ft > 0 else ROOM_WIDTH) - inset_m
            h = (self.height_ft * FT_TO_M if self.height_ft > 0 else ROOM_DEPTH) - inset_m
        elif self.surface in ('wall_north', 'wall_south'):
            w = (self.width_ft * FT_TO_M if self.width_ft > 0 else ROOM_WIDTH) - inset_m
            h = (self.height_ft * FT_TO_M if self.height_ft > 0 else ROOM_HEIGHT) - inset_m
        elif self.surface in ('wall_east', 'wall_west'):
            w = (self.width_ft * FT_TO_M if self.width_ft > 0 else ROOM_DEPTH) - inset_m
            h = (self.height_ft * FT_TO_M if self.height_ft > 0 else ROOM_HEIGHT) - inset_m
        else:
            w = self.width_ft * FT_TO_M
            h = self.height_ft * FT_TO_M
        return (max(w, 0.1), max(h, 0.1))


# ─────────────────────────────────────────────
# FIXTURE FACTORY
# ─────────────────────────────────────────────

def make_luminaire(ies_path, center_ft, length_ft=0.0, width_inches=4.0, z_ft=None):
    """Create a single mesh emitter fixture with realistic aperture.

    Args:
        ies_path:      path to IES file
        center_ft:     (x, y, z) center position in feet
        length_ft:     aperture length along X in feet (0 = square using width_inches)
        width_inches:  aperture width along Y in inches (default: 4")
        z_ft:          override Z position (default: use center_ft[2])

    Returns:
        list[Fixture] — single-element list for consistency with multi-fixture scenes

    Examples:
        # 4' linear luminaire (BioPro):
        make_luminaire(IES_BIOPRO, (0,0,9.5), length_ft=3.917)

        # 4" round downlight (B4RD):
        make_luminaire(IES_B4RD, (5,5,9.5), width_inches=4.0)
    """
    cx, cy, cz = center_ft
    if z_ft is not None:
        cz = z_ft

    return [Fixture(
        ies_path=ies_path,
        position_ft=(cx, cy, cz),
        length_ft=length_ft,
        width_inches=width_inches,
    )]


# ─────────────────────────────────────────────
# LEGACY: SPOT array (deprecated — use make_luminaire)
# ─────────────────────────────────────────────

import math as _math

def make_spot_array(ies_path, center_ft, length_ft, width_ft=0.0,
                    n_length=10, n_width=1, z_ft=None):
    """LEGACY — Generate SPOT array. Use make_luminaire() for new fixtures.

    Kept for backward compatibility with existing validation scripts.
    """
    cx, cy, cz = center_ft
    if z_ft is not None:
        cz = z_ft

    n_total = n_length * n_width
    fixtures = []

    for ix in range(n_length):
        for iy in range(n_width):
            fx = cx - length_ft / 2 + (ix + 0.5) * length_ft / n_length
            if n_width > 1 and width_ft > 0:
                fy = cy - width_ft / 2 + (iy + 0.5) * width_ft / n_width
            else:
                fy = cy
            fixtures.append(Fixture(
                ies_path=ies_path,
                position_ft=(fx, fy, cz),
                length_ft=0.0,
                width_inches=1.0,  # 1" square for point-like spots
            ))

    return fixtures


# ─────────────────────────────────────────────
# FIXTURE LIST — edit this for your scenario
# ─────────────────────────────────────────────

# ── CalcGrid validation — BioPro centered, direct-only ──
# Known baseline: 227.3 lux / 22.2 fc max (validated to 0.84% vs analytical)
FIXTURES = make_luminaire(
    ies_path=IES_BIOPRO_DIRECT,
    center_ft=(0.0, 0.0, 9.5),
    length_ft=3.917,
    width_inches=4.0,
)

# ── Wall wash array — 3x Selux L36 aimed at the brick wall (north, +Y) ──
# Blender IES phi=0° throws toward local -Y by default.
# Rotate 180° around Z so beam throws toward +Y (north brick wall).
# _WASH_ROT = (0.0, 0.0, _math.pi)
# FIXTURES = [
#     Fixture(
#         ies_path=IES_SELUX_L36,
#         position_ft=(-5.0, 7.0, 9.5),   # left fixture, 3' from north wall
#         rotation=_WASH_ROT,
#         length_ft=4.0,
#         width_inches=0.504,
#     ),
#     Fixture(
#         ies_path=IES_SELUX_L36,
#         position_ft=(0.0, 7.0, 9.5),    # center fixture
#         rotation=_WASH_ROT,
#         length_ft=4.0,
#         width_inches=0.504,
#     ),
#     Fixture(
#         ies_path=IES_SELUX_L36,
#         position_ft=(5.0, 7.0, 9.5),    # right fixture
#         rotation=_WASH_ROT,
#         length_ft=4.0,
#         width_inches=0.504,
#     ),
# ]

# Single asymmetric wall washer (centered, no rotation — for validation):
# FIXTURES = make_luminaire(
#     ies_path=IES_SELUX_L36,
#     center_ft=(0.0, 0.0, 9.5),
#     length_ft=4.0,
#     width_inches=0.504,
# )

# Downlight (B4RD 4" round aperture):
# FIXTURES = make_luminaire(
#     ies_path=IES_B4RD,
#     center_ft=(0.0, 0.0, 9.5),
#     width_inches=4.0,
# )


# ─────────────────────────────────────────────
# ROOM MATERIALS
# ─────────────────────────────────────────────

USE_COLORED_MATERIALS = False  # False = achromatic (gray) mode for photometric validation

ROOM_MATERIALS = {
    'ceiling':    {'color': (0.85, 0.85, 0.80), 'roughness': 0.9},                                  # warm white ceiling
    'floor':      {'color': (0.15, 0.08, 0.04), 'roughness': 0.7},                                  # dark walnut wood
    'wall_north': {'color': (0.55, 0.12, 0.10), 'roughness': 0.85},                                 # red brick
    'wall_south': {'color': (0.08, 0.12, 0.45), 'roughness': 1.0},                                  # blue fabric
    'wall_east':  {'color': (0.06, 0.40, 0.12), 'roughness': 0.15, 'specular': 0.5,
                   'coat_weight': 0.8, 'coat_roughness': 0.05},                                     # green glossy paint
    'wall_west':  {'color': (0.82, 0.78, 0.70), 'roughness': 0.3, 'specular': 0.6},                 # white marble
}


# ─────────────────────────────────────────────
# PERSPECTIVE CAMERA DEFAULTS
# ─────────────────────────────────────────────

PERSP_CAM_POSITION_FT  = (7.0, -6.0, 4.0)     # camera position in feet — viewing brick wall
PERSP_CAM_TARGET_FT    = (0.0, 7.0, 5.0)       # look-at point: center of wall wash on brick wall
PERSP_CAM_FOV          = 90.0                    # degrees
PERSP_RENDER_SAMPLES   = 2048
PERSP_RESOLUTION       = (1920, 1080)
PERSP_VIEW_TRANSFORM   = 'Filmic'               # 'Filmic' for beauty, 'Raw' for analysis
PERSP_OUTPUT_FORMAT     = 'PNG'                  # 'PNG' for beauty, 'OPEN_EXR' for falsecolor
PERSP_ENABLE_DENOISING = True


# ─────────────────────────────────────────────
# CALC GRIDS — illuminance measurement surfaces
# ─────────────────────────────────────────────

CALC_GRIDS = [
    CalcGrid(
        name='Workplane',
        surface='floor',
        spacing_ft=2.0,
        inset_ft=1.0,
        offset_ft=2.5,       # standard workplane height (30")
        bake_resolution=256,
    ),
]


# ─────────────────────────────────────────────
# MULTI-ROOM FLOOR PLAN
# ─────────────────────────────────────────────

USE_FLOOR_PLAN = True   # True = use multi-room layout below; False = single-room mode

FLOOR_PLAN_ROOMS = [
    Room('Corridor',       origin_ft=(0, 14), width_ft=30, depth_ft=6,  height_ft=9),
    Room('Meeting Room',   origin_ft=(0, 0),  width_ft=20, depth_ft=14, height_ft=9),
    Room('Private Office', origin_ft=(20, 0), width_ft=10, depth_ft=14, height_ft=9),
]

FLOOR_PLAN_FIXTURES = [
    # Corridor — 4x B4RD downlights centered at Y=17, 8' spacing
    Fixture(ies_path=IES_B4RD, position_ft=(3,  17, 8.5), width_inches=4.0),
    Fixture(ies_path=IES_B4RD, position_ft=(11, 17, 8.5), width_inches=4.0),
    Fixture(ies_path=IES_B4RD, position_ft=(19, 17, 8.5), width_inches=4.0),
    Fixture(ies_path=IES_B4RD, position_ft=(27, 17, 8.5), width_inches=4.0),
    # Meeting Room — 3x 12' BioPro rows, 6' apart (Y=1, 7, 13 in 14' room)
    Fixture(ies_path=IES_BIOPRO_DIRECT, position_ft=(10, 1,  8.5), length_ft=12.0, width_inches=4.0),
    Fixture(ies_path=IES_BIOPRO_DIRECT, position_ft=(10, 7,  8.5), length_ft=12.0, width_inches=4.0),
    Fixture(ies_path=IES_BIOPRO_DIRECT, position_ft=(10, 13, 8.5), length_ft=12.0, width_inches=4.0),
    # Private Office — 6x B4RD downlights, 2x3 grid
    Fixture(ies_path=IES_B4RD, position_ft=(23, 3.5,  8.5), width_inches=4.0),
    Fixture(ies_path=IES_B4RD, position_ft=(27, 3.5,  8.5), width_inches=4.0),
    Fixture(ies_path=IES_B4RD, position_ft=(23, 7.0,  8.5), width_inches=4.0),
    Fixture(ies_path=IES_B4RD, position_ft=(27, 7.0,  8.5), width_inches=4.0),
    Fixture(ies_path=IES_B4RD, position_ft=(23, 10.5, 8.5), width_inches=4.0),
    Fixture(ies_path=IES_B4RD, position_ft=(27, 10.5, 8.5), width_inches=4.0),
]

FLOOR_PLAN_GRIDS = [
    CalcGrid(name='Corridor_WP',  room_name='Corridor',
             position_ft=(15, 17, 2.5), width_ft=28, height_ft=4,
             spacing_ft=2.0, inset_ft=0, offset_ft=2.5, bake_resolution=256),
    CalcGrid(name='Meeting_WP',   room_name='Meeting Room',
             position_ft=(10, 7, 2.5), width_ft=18, height_ft=12,
             spacing_ft=2.0, inset_ft=0, offset_ft=2.5, bake_resolution=256),
    CalcGrid(name='Office_WP',    room_name='Private Office',
             position_ft=(25, 7, 2.5), width_ft=8, height_ft=12,
             spacing_ft=2.0, inset_ft=0, offset_ft=2.5, bake_resolution=256),
]
