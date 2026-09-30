#!/usr/bin/env python3
"""
Falsecolor Map Generator
=========================
Creates color-mapped illuminance or luminance visualizations from EXR renders.

Standalone script — no Blender required.
Requires: numpy, matplotlib (available in Blender's bundled Python).

Usage:
    # Using Blender's Python (recommended):
    /Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 falsecolor.py [options]

    # Or if numpy/matplotlib are installed in system Python:
    python3 falsecolor.py [options]

Examples:
    # Illuminance falsecolor from lux validation render:
    python3 falsecolor.py lux_render.exr fc_illuminance.png --mode illuminance

    # Luminance falsecolor from perspective render:
    python3 falsecolor.py perspective_render.exr fc_luminance.png --mode luminance

    # Custom scale and colormap:
    python3 falsecolor.py lux_render.exr fc.png --max 300 --cmap viridis --contours 10

    # Log scale for high dynamic range:
    python3 falsecolor.py perspective_render.exr fc_log.png --log
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')  # headless backend
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.colorbar import ColorbarBase
from matplotlib import cm


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

LUMINOUS_EFFICACY = 179.0   # lm/W, photopic maximum
LUX_TO_FC = 1.0 / 10.764


# ─────────────────────────────────────────────
# EXR READING
# ─────────────────────────────────────────────

def read_exr(exr_path):
    """Read an EXR file and return (H, W, 3) float32 numpy array (RGB).

    Uses OpenEXR library (pip install openexr).
    Handles both combined RGBA channels and separate R/G/B channels.
    """
    import OpenEXR

    exr_file = OpenEXR.File(exr_path)
    channels = exr_file.channels()

    # Blender typically writes RGBA as a single combined channel
    if 'RGBA' in channels:
        rgba = channels['RGBA'].pixels  # (H, W, 4) float32
        return rgba[:, :, :3].astype(np.float32)

    # Some EXR files have separate R, G, B channels
    r = channels.get('R')
    g = channels.get('G')
    b = channels.get('B')

    if r is not None and g is not None and b is not None:
        return np.stack([r.pixels, g.pixels, b.pixels], axis=-1).astype(np.float32)

    available = list(channels.keys())
    raise ValueError(f"EXR missing expected channels. Available: {available}")


# ─────────────────────────────────────────────
# LUMINANCE / ILLUMINANCE COMPUTATION
# ─────────────────────────────────────────────

def rgb_to_luminance(rgb):
    """Convert linear RGB to luminance using Rec. 709 coefficients."""
    return 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]


def compute_illuminance(rgb):
    """Convert linear RGB (W/m^2 spectral) to illuminance (lux).

    For Cycles renders with luminous efficacy = 179 lm/W.
    """
    luminance = rgb_to_luminance(rgb)
    return luminance * LUMINOUS_EFFICACY


def compute_luminance(rgb):
    """Convert linear RGB to luminance (cd/m^2).

    For Cycles renders, pixel values are in W/m^2/sr when Raw view transform.
    Luminance = luminous efficacy * radiance.
    """
    radiance = rgb_to_luminance(rgb)
    return radiance * LUMINOUS_EFFICACY


# ─────────────────────────────────────────────
# FALSECOLOR RENDERING
# ─────────────────────────────────────────────

def create_falsecolor(values, output_path, mode='illuminance',
                      vmax=None, use_log=False, cmap_name='turbo',
                      contours=0, title=None, room_grid=False,
                      room_dims_ft=None, grid_spacing_ft=None):
    """Generate a falsecolor map from 2D value array.

    Args:
        values:        2D numpy array of illuminance (lux) or luminance (cd/m^2)
        output_path:   path for output PNG
        mode:          'illuminance' or 'luminance'
        vmax:          max value for colorbar (None = auto)
        use_log:       use logarithmic color scale
        cmap_name:     matplotlib colormap name
        contours:      number of contour lines (0 = none)
        title:         custom title (None = auto)
        room_grid:     overlay room coordinate grid
        room_dims_ft:  (width_ft, depth_ft) for grid overlay
        grid_spacing_ft: grid spacing in feet
    """
    h, w = values.shape

    # Statistics
    valid = values[values > 0]
    if len(valid) == 0:
        print("WARNING: All values are zero or negative. Check EXR input.")
        val_min = val_max = val_avg = 0.0
    else:
        val_min = float(np.min(valid))
        val_max = float(np.max(values))
        val_avg = float(np.mean(values))

    if vmax is None:
        vmax = val_max
    vmin = 0.0

    # Units
    if mode == 'illuminance':
        unit = 'lux'
        unit_alt = 'fc'
        alt_factor = LUX_TO_FC
    else:
        unit = 'cd/m\u00b2'
        unit_alt = 'fL'
        alt_factor = 1.0 / 3.426  # cd/m^2 to footlamberts

    # Create figure
    fig_width = 12
    fig_height = fig_width * h / w + 2.0  # extra space for colorbar and stats
    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))

    # Color mapping
    cmap = plt.get_cmap(cmap_name)
    if use_log:
        norm = mcolors.LogNorm(vmin=max(vmin, 0.1), vmax=vmax)
    else:
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

    # Plot falsecolor image (OpenEXR returns top-to-bottom, no flip needed)
    im = ax.imshow(values, cmap=cmap, norm=norm,
                   interpolation='bilinear', aspect='equal')

    # Contour lines
    if contours > 0:
        if use_log:
            levels = np.logspace(np.log10(max(vmin, 0.1)), np.log10(vmax), contours + 2)[1:-1]
        else:
            levels = np.linspace(vmin, vmax, contours + 2)[1:-1]
        ax.contour(values, levels=levels, colors='black',
                   linewidths=0.5, alpha=0.4)

    # Room grid overlay
    if room_grid and room_dims_ft and grid_spacing_ft:
        rw_ft, rd_ft = room_dims_ft
        gs_ft = grid_spacing_ft
        # Convert room coordinates to pixel positions
        x_ticks_ft = []
        x = -rw_ft / 2 + gs_ft
        while x < rw_ft / 2:
            x_ticks_ft.append(x)
            x += gs_ft
        y_ticks_ft = []
        y = -rd_ft / 2 + gs_ft
        while y < rd_ft / 2:
            y_ticks_ft.append(y)
            y += gs_ft

        for xf in x_ticks_ft:
            px = (xf + rw_ft / 2) / rw_ft * w
            ax.axvline(px, color='white', linewidth=0.3, alpha=0.3)
        for yf in y_ticks_ft:
            py = h - (yf + rd_ft / 2) / rd_ft * h  # flip Y
            ax.axhline(py, color='white', linewidth=0.3, alpha=0.3)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, orientation='horizontal', pad=0.08,
                        fraction=0.04, aspect=40)
    cbar.set_label(f'{mode.title()} ({unit})', fontsize=11)

    # Title
    if title is None:
        title = f'{mode.title()} Falsecolor Map'
    ax.set_title(title, fontsize=14, fontweight='bold', pad=12)

    # Remove axes for clean look
    ax.set_xticks([])
    ax.set_yticks([])

    # Statistics text
    stats_text = (
        f'Max: {val_max:.1f} {unit} ({val_max * alt_factor:.1f} {unit_alt})    '
        f'Min: {val_min:.1f} {unit} ({val_min * alt_factor:.1f} {unit_alt})    '
        f'Avg: {val_avg:.1f} {unit} ({val_avg * alt_factor:.1f} {unit_alt})'
    )
    fig.text(0.5, 0.02, stats_text, ha='center', va='bottom', fontsize=10,
             fontfamily='monospace',
             bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.8))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()

    print(f"\nFalsecolor map saved to: {output_path}")
    print(f"  Mode: {mode}")
    print(f"  Max: {val_max:.1f} {unit} ({val_max * alt_factor:.1f} {unit_alt})")
    print(f"  Min: {val_min:.1f} {unit} ({val_min * alt_factor:.1f} {unit_alt})")
    print(f"  Avg: {val_avg:.1f} {unit} ({val_avg * alt_factor:.1f} {unit_alt})")
    if mode == 'illuminance':
        uniformity_avg = val_min / val_avg if val_avg > 0 else 0
        uniformity_max = val_min / val_max if val_max > 0 else 0
        print(f"  Uniformity (min/avg): {uniformity_avg:.2f}")
        print(f"  Uniformity (min/max): {uniformity_max:.2f}")


# ─────────────────────────────────────────────
# MAIN / CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate falsecolor maps from Blender Cycles EXR renders.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 falsecolor.py lux_render.exr fc_illum.png --mode illuminance
  python3 falsecolor.py perspective_render.exr fc_lum.png --mode luminance
  python3 falsecolor.py lux_render.exr fc.png --max 300 --cmap viridis --contours 10
  python3 falsecolor.py lux_render.exr fc_log.png --log
        """
    )
    parser.add_argument('input', help='Input EXR file path')
    parser.add_argument('output', help='Output PNG file path')
    parser.add_argument('--mode', choices=['illuminance', 'luminance'],
                        default='illuminance',
                        help='Analysis mode (default: illuminance)')
    parser.add_argument('--max', type=float, default=None,
                        help='Maximum value for colorbar scale')
    parser.add_argument('--log', action='store_true',
                        help='Use logarithmic color scale')
    parser.add_argument('--cmap', default='turbo',
                        help='Matplotlib colormap (default: turbo)')
    parser.add_argument('--contours', type=int, default=0,
                        help='Number of contour lines (default: 0)')
    parser.add_argument('--title', default=None,
                        help='Custom title for the map')
    parser.add_argument('--room-grid', action='store_true',
                        help='Overlay room coordinate grid')
    parser.add_argument('--room-width', type=float, default=20.0,
                        help='Room width in feet (default: 20)')
    parser.add_argument('--room-depth', type=float, default=20.0,
                        help='Room depth in feet (default: 20)')
    parser.add_argument('--grid-spacing', type=float, default=2.0,
                        help='Grid spacing in feet (default: 2)')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    print("=" * 60)
    print("FALSECOLOR MAP GENERATOR")
    print("=" * 60)
    print(f"\nInput:  {args.input}")
    print(f"Output: {args.output}")
    print(f"Mode:   {args.mode}")

    # Read EXR
    print("\nReading EXR...")
    rgb = read_exr(args.input)

    print(f"  Image size: {rgb.shape[1]} x {rgb.shape[0]}")
    print(f"  Value range: [{rgb.min():.4f}, {rgb.max():.4f}]")

    # Compute values
    if args.mode == 'illuminance':
        values = compute_illuminance(rgb)
    else:
        values = compute_luminance(rgb)

    # Generate falsecolor
    room_dims = (args.room_width, args.room_depth) if args.room_grid else None

    create_falsecolor(
        values,
        args.output,
        mode=args.mode,
        vmax=args.max,
        use_log=args.log,
        cmap_name=args.cmap,
        contours=args.contours,
        title=args.title,
        room_grid=args.room_grid,
        room_dims_ft=room_dims,
        grid_spacing_ft=args.grid_spacing if args.room_grid else None,
    )

    print("\nDone.")


if __name__ == '__main__':
    main()
