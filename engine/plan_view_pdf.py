#!/usr/bin/env python3
"""
Plan View PDF Generator — Lighting Calculation Documentation
=============================================================
Generates AHJ-compliant lighting plan sheets from calc grid results.

Standalone script — no Blender required. Reads calcgrid_results.json.

Usage:
    python3 plan_view_pdf.py calcgrid_results.json lighting_plan.pdf

    # Or with Blender's Python:
    /Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 plan_view_pdf.py ...

Output:
    Multi-page PDF with:
    - Page 1: Combined plan view (all rooms + all grids)
    - Page 2+: Per-room detail sheets with zoomed view
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, FancyBboxPatch
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.patheffects as pe


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

FONT_SIZE_VALUE = 5.5       # fc value text
FONT_SIZE_ROOM_LABEL = 10   # room name
FONT_SIZE_STATS = 7         # stats box
FONT_SIZE_TITLE = 12
FONT_SIZE_SUBTITLE = 8

FIXTURE_COLOR = '#444444'
GRID_VALUE_COLOR = '#1a1a1a'
ROOM_OUTLINE_COLOR = '#000000'
ROOM_FILL_COLOR = '#f5f5f0'
STATS_BOX_COLOR = '#e8e8e8'


# ─────────────────────────────────────────────
# DRAWING HELPERS
# ─────────────────────────────────────────────

def draw_rooms(ax, rooms):
    """Draw room outlines as rectangles with labels."""
    for room in rooms:
        ox, oy = room['origin_ft']
        w, d = room['width_ft'], room['depth_ft']

        rect = Rectangle((ox, oy), w, d,
                          linewidth=1.5, edgecolor=ROOM_OUTLINE_COLOR,
                          facecolor=ROOM_FILL_COLOR, zorder=1)
        ax.add_patch(rect)

        # Room name label (centered)
        cx = ox + w / 2
        cy = oy + d / 2
        ax.text(cx, cy + d * 0.4, room['name'],
                ha='center', va='center', fontsize=FONT_SIZE_ROOM_LABEL,
                fontweight='bold', color='#333333', zorder=10,
                fontstyle='italic')

        # Dimensions
        ax.text(cx, oy - 0.4, f"{w:.0f}' x {d:.0f}'",
                ha='center', va='top', fontsize=6, color='#666666', zorder=10)


def draw_fixtures(ax, fixtures):
    """Draw fixture symbols at their locations."""
    for fix in fixtures:
        x, y, z = fix['position_ft']
        length_ft = fix.get('length_ft', 0)
        width_in = fix.get('width_inches', 4.0)

        if length_ft > 0:
            # Linear fixture — draw as a thick line
            half_l = length_ft / 2
            ax.plot([x - half_l, x + half_l], [y, y],
                    linewidth=3, color=FIXTURE_COLOR, solid_capstyle='round',
                    zorder=5)
            # Small cross at center
            ax.plot(x, y, '+', color=FIXTURE_COLOR, markersize=4,
                    markeredgewidth=0.8, zorder=6)
        else:
            # Round fixture — draw as a circle
            radius = max(width_in / 24, 0.15)  # visual size, min 0.15'
            circle = Circle((x, y), radius,
                            linewidth=1, edgecolor=FIXTURE_COLOR,
                            facecolor='white', zorder=5)
            ax.add_patch(circle)
            ax.plot(x, y, '+', color=FIXTURE_COLOR, markersize=3,
                    markeredgewidth=0.6, zorder=6)


def draw_grid_values(ax, grid):
    """Draw illuminance values at each grid point."""
    x_ft = grid['x_ft']
    y_ft = grid['y_ft']
    values_fc = grid['values_fc']
    pos_ft = grid.get('position_ft')

    # Grid center offset
    if pos_ft:
        cx, cy = pos_ft[0], pos_ft[1]
    else:
        cx, cy = 0, 0

    stats = grid['stats']
    max_fc = stats['max_fc']
    min_fc = stats['min_fc']

    for i, row in enumerate(values_fc):
        # values_fc is stored top-to-bottom (row 0 = highest Y)
        yi = len(y_ft) - 1 - i
        if yi < 0 or yi >= len(y_ft):
            continue
        y_pos = y_ft[yi] + cy

        for j, fc_val in enumerate(row):
            if j >= len(x_ft):
                continue
            x_pos = x_ft[j] + cx

            # Color code: scale from blue (low) through black to red (high)
            if max_fc > min_fc:
                t = (fc_val - min_fc) / (max_fc - min_fc)
            else:
                t = 0.5

            if t < 0.3:
                color = '#1a5276'  # dark blue for low
            elif t > 0.8:
                color = '#922b21'  # dark red for high
            else:
                color = GRID_VALUE_COLOR

            ax.text(x_pos, y_pos, f'{fc_val:.1f}',
                    ha='center', va='center', fontsize=FONT_SIZE_VALUE,
                    fontweight='medium', color=color, zorder=8,
                    path_effects=[pe.withStroke(linewidth=1.5, foreground='white')])


def draw_stats_box(ax, grid, box_x, box_y):
    """Draw a summary statistics box for a calc grid."""
    stats = grid['stats']
    name = grid['name']
    room = grid.get('room_name', '')

    label = f"{room} — {name}" if room else name
    lines = [
        label,
        f"Max: {stats['max_fc']:.1f} fc  ({stats['max_lux']:.0f} lux)",
        f"Min: {stats['min_fc']:.1f} fc  ({stats['min_lux']:.0f} lux)",
        f"Avg: {stats['avg_fc']:.1f} fc  ({stats['avg_lux']:.0f} lux)",
        f"Uniformity (min/avg): {stats['uniformity_avg']:.2f}",
        f"Uniformity (min/max): {stats['uniformity_max']:.2f}",
        f"Points: {stats['n_points']}",
    ]
    text = '\n'.join(lines)

    ax.text(box_x, box_y, text,
            fontsize=FONT_SIZE_STATS, fontfamily='monospace',
            va='top', ha='left', zorder=15,
            bbox=dict(boxstyle='round,pad=0.4', facecolor=STATS_BOX_COLOR,
                      edgecolor='#999999', alpha=0.9))


# ─────────────────────────────────────────────
# PAGE GENERATORS
# ─────────────────────────────────────────────

def render_combined_plan(pdf, data):
    """Render page 1: combined plan view with all rooms and grids."""
    rooms = data['rooms']
    fixtures = data['fixtures']
    grids = data['grids']

    # Compute bounding box
    x_min = min(r['origin_ft'][0] for r in rooms)
    y_min = min(r['origin_ft'][1] for r in rooms)
    x_max = max(r['origin_ft'][0] + r['width_ft'] for r in rooms)
    y_max = max(r['origin_ft'][1] + r['depth_ft'] for r in rooms)

    plan_w = x_max - x_min
    plan_d = y_max - y_min

    # Letter size, landscape
    fig, ax = plt.subplots(1, 1, figsize=(11, 8.5))

    # Title
    fig.text(0.5, 0.97, 'LIGHTING CALCULATION PLAN',
             ha='center', va='top', fontsize=FONT_SIZE_TITLE, fontweight='bold')
    fig.text(0.5, 0.945, f'Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}',
             ha='center', va='top', fontsize=FONT_SIZE_SUBTITLE, color='#666666')

    # Margins for drawing area (inches from figure edge)
    margin = 1.5  # space for stats boxes on right
    ax.set_position([0.06, 0.06, 0.60, 0.85])

    # Set axis limits with padding
    pad = 2.0
    ax.set_xlim(x_min - pad, x_max + pad)
    ax.set_ylim(y_min - pad, y_max + pad)
    ax.set_aspect('equal')
    ax.set_xlabel("X (feet)", fontsize=8)
    ax.set_ylabel("Y (feet)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.15, linewidth=0.5)

    # Draw elements
    draw_rooms(ax, rooms)
    draw_fixtures(ax, fixtures)
    for grid in grids:
        draw_grid_values(ax, grid)

    # Stats boxes on the right side
    stats_x = 0.70
    for i, grid in enumerate(grids):
        stats_y = 0.88 - i * 0.28
        fig.text(stats_x, stats_y,
                 _format_stats_text(grid),
                 fontsize=FONT_SIZE_STATS, fontfamily='monospace',
                 va='top', ha='left', transform=fig.transFigure,
                 bbox=dict(boxstyle='round,pad=0.4', facecolor=STATS_BOX_COLOR,
                           edgecolor='#999999', alpha=0.9))

    # Scale bar
    scale_len = 5  # feet
    sb_x = x_min
    sb_y = y_min - pad + 0.3
    ax.plot([sb_x, sb_x + scale_len], [sb_y, sb_y],
            linewidth=2, color='black', zorder=15)
    ax.plot([sb_x, sb_x], [sb_y - 0.15, sb_y + 0.15],
            linewidth=1.5, color='black', zorder=15)
    ax.plot([sb_x + scale_len, sb_x + scale_len], [sb_y - 0.15, sb_y + 0.15],
            linewidth=1.5, color='black', zorder=15)
    ax.text(sb_x + scale_len / 2, sb_y - 0.3, f"{scale_len}'-0\"",
            ha='center', va='top', fontsize=7, fontweight='bold', zorder=15)

    # Footer
    fig.text(0.5, 0.01, 'Values in footcandles (fc) at 2\'-6\" AFF workplane',
             ha='center', va='bottom', fontsize=6, color='#888888')

    pdf.savefig(fig, dpi=300)
    plt.close(fig)


def render_room_detail(pdf, data, room_name):
    """Render a detail page for a single room."""
    rooms = data['rooms']
    fixtures = data['fixtures']
    grids = data['grids']

    # Find the room
    room = next((r for r in rooms if r['name'] == room_name), None)
    if room is None:
        return

    ox, oy = room['origin_ft']
    rw, rd = room['width_ft'], room['depth_ft']

    # Filter fixtures in this room
    room_fixtures = [f for f in fixtures
                     if ox <= f['position_ft'][0] <= ox + rw
                     and oy <= f['position_ft'][1] <= oy + rd]

    # Filter grids for this room
    room_grids = [g for g in grids if g.get('room_name') == room_name]

    fig, ax = plt.subplots(1, 1, figsize=(11, 8.5))

    fig.text(0.5, 0.97, f'{room_name.upper()} — DETAIL',
             ha='center', va='top', fontsize=FONT_SIZE_TITLE, fontweight='bold')
    fig.text(0.5, 0.945, f"{rw:.0f}' x {rd:.0f}' — {len(room_fixtures)} fixtures",
             ha='center', va='top', fontsize=FONT_SIZE_SUBTITLE, color='#666666')

    ax.set_position([0.08, 0.08, 0.58, 0.82])

    pad = 1.5
    ax.set_xlim(ox - pad, ox + rw + pad)
    ax.set_ylim(oy - pad, oy + rd + pad)
    ax.set_aspect('equal')
    ax.set_xlabel("X (feet)", fontsize=8)
    ax.set_ylabel("Y (feet)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.15, linewidth=0.5)

    # Draw just this room
    draw_rooms(ax, [room])
    draw_fixtures(ax, room_fixtures)
    for grid in room_grids:
        draw_grid_values(ax, grid)

    # Stats boxes
    stats_x = 0.70
    for i, grid in enumerate(room_grids):
        stats_y = 0.88 - i * 0.30
        fig.text(stats_x, stats_y,
                 _format_stats_text(grid),
                 fontsize=FONT_SIZE_STATS + 1, fontfamily='monospace',
                 va='top', ha='left', transform=fig.transFigure,
                 bbox=dict(boxstyle='round,pad=0.4', facecolor=STATS_BOX_COLOR,
                           edgecolor='#999999', alpha=0.9))

    # Fixture schedule for this room
    sched_y = 0.88 - len(room_grids) * 0.30
    sched_lines = [f"FIXTURE SCHEDULE ({room_name})"]
    for i, f in enumerate(room_fixtures, 1):
        ies = f.get('ies_file', 'unknown')
        x, y, z = f['position_ft']
        if f.get('length_ft', 0) > 0:
            dims = f"{f['length_ft']:.1f}' linear"
        else:
            dims = f"{f.get('width_inches', 4):.0f}\" round"
        sched_lines.append(f"  {i}. {ies}  ({dims})  at ({x:.1f}, {y:.1f}, {z:.1f})")

    fig.text(stats_x, sched_y,
             '\n'.join(sched_lines),
             fontsize=6, fontfamily='monospace',
             va='top', ha='left', transform=fig.transFigure,
             bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                       edgecolor='#cccccc', alpha=0.9))

    fig.text(0.5, 0.01, 'Values in footcandles (fc) at 2\'-6\" AFF workplane',
             ha='center', va='bottom', fontsize=6, color='#888888')

    pdf.savefig(fig, dpi=300)
    plt.close(fig)


def _format_stats_text(grid):
    """Format a stats text block for a grid."""
    stats = grid['stats']
    name = grid['name']
    room = grid.get('room_name', '')
    label = f"{room}: {name}" if room else name
    return '\n'.join([
        label,
        f"  Max: {stats['max_fc']:6.1f} fc  ({stats['max_lux']:.0f} lux)",
        f"  Min: {stats['min_fc']:6.1f} fc  ({stats['min_lux']:.0f} lux)",
        f"  Avg: {stats['avg_fc']:6.1f} fc  ({stats['avg_lux']:.0f} lux)",
        f"  Uniformity (min/avg): {stats['uniformity_avg']:.2f}",
        f"  Uniformity (min/max): {stats['uniformity_max']:.2f}",
        f"  Points: {stats['n_points']}",
    ])


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate lighting plan PDF from calc grid results.',
    )
    parser.add_argument('input', help='Input JSON file (calcgrid_results.json)')
    parser.add_argument('output', help='Output PDF file path')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    with open(args.input, 'r') as f:
        data = json.load(f)

    print("=" * 60)
    print("LIGHTING PLAN PDF GENERATOR")
    print("=" * 60)
    print(f"\nInput:  {args.input}")
    print(f"Output: {args.output}")
    print(f"Rooms:    {len(data['rooms'])}")
    print(f"Fixtures: {len(data['fixtures'])}")
    print(f"Grids:    {len(data['grids'])}")

    with PdfPages(args.output) as pdf:
        # Page 1: Combined plan view
        print("\nRendering combined plan view...")
        render_combined_plan(pdf, data)

        # Per-room detail pages
        for room in data['rooms']:
            print(f"Rendering detail: {room['name']}...")
            render_room_detail(pdf, data, room['name'])

    print(f"\nPDF saved to: {args.output}")
    print("Done.")


if __name__ == '__main__':
    main()
