"""Draw the four-step explanation of the method used in the README.

    python examples/make_method_figure.py docs/method.png

The trace is synthetic, and the panels are produced by running the real anonymizer
on it, so the figure cannot drift away from what the code does.
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Wedge

import location_anonymizer as la

ORIGIN = (40.0, 20.0)  # invented "home"
RADIUS_KM = 0.5
GRID_M = 100.0
EXTENT_M = 1250

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
RULE = "#d9d8d3"
CELL_FILL, CELL_EDGE = "#e3edfb", "#9ec5f4"
POINT = "#2a78d6"   # the trace
HOME = "#eb6834"    # the protected place, and what can be inferred about it
REMOVED = "#b9b8b2"

M_PER_DEG_LAT = la.KM_PER_DEG_LAT * 1000
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(ORIGIN[0]))

ROUTES = [
    [(0, 0), (180, 60), (260, 420), (700, 520), (1050, 900)],
    [(0, 0), (-150, -40), (-420, 160), (-900, 120), (-1150, 380)],
    [(0, 0), (40, -260), (-200, -520), (-160, -1000)],
    [(0, 0), (180, 60), (520, -180), (980, -260)],
]


def to_latlon(x, y):
    return ORIGIN[0] + y / M_PER_DEG_LAT, ORIGIN[1] + x / M_PER_DEG_LON


def to_xy(lat, lon):
    return (lon - ORIGIN[1]) * M_PER_DEG_LON, (lat - ORIGIN[0]) * M_PER_DEG_LAT


def synthetic_trace(rng):
    points = [(rng.gauss(0, 9), rng.gauss(0, 9)) for _ in range(150)]
    for route in ROUTES:
        for _ in range(3):
            for (x0, y0), (x1, y1) in zip(route, route[1:]):
                steps = max(1, int(math.hypot(x1 - x0, y1 - y0) // 30))
                for i in range(steps):
                    t = i / steps
                    points.append((x0 + t * (x1 - x0) + rng.gauss(0, 7), y0 + t * (y1 - y0) + rng.gauss(0, 7)))
        end_x, end_y = route[-1]
        points += [(end_x + rng.gauss(0, 9), end_y + rng.gauss(0, 9)) for _ in range(40)]
    return points


def run_anonymizer(data):
    """Use a draw whose zone offset is easy to see in a small picture."""
    for seed in range(1000):
        anonymizer = la.LocationAnonymizer("HOME", RADIUS_KM, grid_m=GRID_M, rng=random.Random(seed))
        output = anonymizer.anonymize_data(data)
        cx, cy = to_xy(anonymizer.zones[0].center_lat, anonymizer.zones[0].center_lon)
        if 240 <= math.hypot(cx, cy) <= 290 and cy > 180 and cx < -60:
            return anonymizer, output
    raise SystemExit("no suitable draw found")


def cell_outline(lat_c, lon_c):
    """Corners of the grid cell whose centre is (lat_c, lon_c)."""
    dlat = GRID_M / M_PER_DEG_LAT
    dlon = GRID_M / (M_PER_DEG_LAT * math.cos(math.radians(lat_c)))
    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    return [to_xy(lat_c + sy * dlat / 2, lon_c + sx * dlon / 2) for sx, sy in corners]


def setup(ax, number, title, caption):
    ax.set_facecolor(SURFACE)
    ax.set_xlim(-EXTENT_M, EXTENT_M)
    ax.set_ylim(-EXTENT_M, EXTENT_M)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(RULE)
    ax.text(0, 1.085, f"{number}  {title}", transform=ax.transAxes, fontsize=13.5, fontweight="bold", color=INK)
    ax.text(0, 1.025, caption, transform=ax.transAxes, fontsize=10.5, color=INK_SECONDARY)


def label(ax, text, xy, xytext, ha="left"):
    ax.annotate(
        text, xy=xy, xytext=xytext, fontsize=10, color=INK, ha=ha, va="center",
        arrowprops=dict(arrowstyle="-", color=INK_SECONDARY, linewidth=0.8, shrinkA=3, shrinkB=4),
        bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.5, alpha=0.9),
    )


def scatter(ax, points, colour, size=11, alpha=0.75, zorder=3):
    if points:
        xs, ys = zip(*points)
        ax.scatter(xs, ys, s=size, c=colour, alpha=alpha, linewidths=0, zorder=zorder)


def home_marker(ax):
    ax.scatter([0], [0], s=300, marker="*", c=HOME, edgecolors=SURFACE, linewidths=1.6, zorder=6)


def zone_outline(ax, centre, fill=True):
    radius = RADIUS_KM * 1000
    if fill:
        ax.add_patch(Circle(centre, radius, facecolor="#ecebe7", edgecolor="none", zorder=1))
    ax.add_patch(Circle(centre, radius, facecolor="none", edgecolor=INK, linewidth=1.4, linestyle=(0, (5, 4)), zorder=5))


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "method.png"
    trace = synthetic_trace(random.Random(5))
    data = {
        "locations": [dict(zip(("latitude", "longitude"), to_latlon(x, y))) for x, y in trace],
        "places": [{"primaryActivityId": "HOME", "latitude": ORIGIN[0], "longitude": ORIGIN[1]}],
    }
    anonymizer, output = run_anonymizer(data)
    zone = anonymizer.zones[0]
    centre = to_xy(zone.center_lat, zone.center_lon)
    radius = RADIUS_KM * 1000
    inside = [p for p in trace if zone.contains(*to_latlon(*p))]
    outside = [p for p in trace if not zone.contains(*to_latlon(*p))]
    cells = sorted({(l["latitude"], l["longitude"]) for l in output["locations"]})
    published = [to_xy(*cell) for cell in cells]

    plt.rcParams["font.family"] = "DejaVu Sans"
    fig, axes = plt.subplots(2, 2, figsize=(11, 12.2), facecolor=SURFACE)
    fig.subplots_adjust(left=0.035, right=0.965, top=0.865, bottom=0.025, wspace=0.07, hspace=0.2)
    fig.text(0.035, 0.968, "How the anonymizer protects a home location", fontsize=17, fontweight="bold", color=INK)
    fig.text(
        0.035, 0.944, "Synthetic trace. Zone radius 500 m, grid 100 m (the defaults).", fontsize=11, color=INK_SECONDARY
    )

    ax = axes[0][0]
    setup(ax, 1, "The original trace", "Trips start and end at home, so the points pile up there.")
    scatter(ax, trace, POINT)
    home_marker(ax)
    label(ax, "Home", (0, 0), (330, -330))
    ax.plot([-1120, -620], [-1090, -1090], color=INK, linewidth=2, solid_capstyle="butt")
    ax.text(-870, -1040, "500 m", fontsize=10, color=INK, ha="center")

    ax = axes[0][1]
    setup(ax, 2, "A privacy zone, placed off-centre", "The centre is moved a random 100–300 m from home.")
    zone_outline(ax, centre)
    scatter(ax, trace, POINT)
    ax.plot([0, centre[0]], [0, centre[1]], color=INK, linewidth=1.2, zorder=5)
    ax.scatter([centre[0]], [centre[1]], s=90, marker="+", c=INK, linewidths=1.8, zorder=6)
    home_marker(ax)
    label(ax, "Zone centre", centre, (centre[0] - 330, centre[1] + 560), ha="center")
    label(ax, "Home", (0, 0), (330, -330))
    label(ax, "Privacy zone", (centre[0] - radius * 0.82, centre[1] - radius * 0.57), (-800, -560), ha="center")

    ax = axes[1][0]
    setup(ax, 3, "Remove what is inside, generalise the rest", "Points in the zone are deleted. The others snap to a 100 m grid.")
    for cell in cells:
        ax.add_patch(Polygon(cell_outline(*cell), facecolor=CELL_FILL, edgecolor=CELL_EDGE, linewidth=0.7, zorder=1))
    zone_outline(ax, centre, fill=False)
    scatter(ax, inside, REMOVED, size=9, alpha=0.9, zorder=2)
    scatter(ax, published, POINT, size=14, alpha=1, zorder=4)
    home_marker(ax)
    label(ax, "Removed", (95, -190), (520, -560))
    label(ax, "Kept: one point per\n100 m cell", published[len(published) // 5], (-700, -720), ha="center")

    ax = axes[1][1]
    setup(ax, 4, "What a reader of the output can work out", "The gap shows roughly where the zone is, not where home is.")
    ax.add_patch(
        Wedge(centre, la.MAX_DISPLACEMENT * radius, 0, 360, width=(la.MAX_DISPLACEMENT - la.MIN_DISPLACEMENT) * radius,
              facecolor=HOME, alpha=0.3, edgecolor="none", zorder=1)
    )
    zone_outline(ax, centre, fill=False)
    scatter(ax, published, POINT, size=20, alpha=1, zorder=4)
    label(ax, "Home is somewhere in this ring\n(about 0.25 km²)",
          (centre[0] + 0.4 * radius * 0.71, centre[1] - 0.4 * radius * 0.71), (620, -700), ha="center")
    label(ax, "Edge of the gap", (centre[0] - radius * 0.77, centre[1] + radius * 0.64), (-760, 1010), ha="center")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    print(f"Wrote {out_path}: {len(trace)} points, {len(inside)} removed, {len(published)} grid cells kept")


if __name__ == "__main__":
    main()
