#!/usr/bin/env python3
"""Draw the Gaza and Ukraine reference maps used on pranksternews.com.

Data: Natural Earth 1:10m (public domain, naturalearthdata.com):
  ne_10m_admin_0_countries, ne_10m_admin_1_states_provinces, ne_10m_ocean.
Needs: matplotlib, shapely, pyshp.  Usage:
  python3 tools/make_maps.py /path/to/natural-earth-dir /path/to/output-dir
The Natural Earth zips must be unzipped into <dir>/<layer-name>/<layer-name>.shp
Outputs gaza-map.svg and ukraine-map.svg (vector).
"""
import math, sys, os
import shapefile
from shapely.geometry import shape, box
from shapely.ops import unary_union
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch, Patch
from matplotlib.path import Path
import matplotlib.patheffects as pe

NE = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = sys.argv[2] if len(sys.argv) > 2 else "."

SEA = "#d6e6f2"
LAND = "#f1ede4"
BORDER = "#9a9486"
INK = "#2b2b2b"
ACCENT = "#c0504d"
GREEN = "#3f7f63"


def layer(name):
    r = shapefile.Reader(f"{NE}/{name}/{name}.shp")
    out = []
    for sr in r.shapeRecords():
        out.append((sr.record.as_dict(), shape(sr.shape.__geo_interface__)))
    return out


def patch_for(geom, **kw):
    polys = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    verts, codes = [], []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            xy = list(ring.coords)
            verts += xy
            codes += [Path.MOVETO] + [Path.LINETO] * (len(xy) - 2) + [Path.CLOSEPOLY]
    return PathPatch(Path(verts, codes), **kw)


def draw(ax, geom, tol=0.004, **kw):
    """Simplify and clip to the visible window so the SVG stays small."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    pad = 0.5
    geom = geom.simplify(tol, preserve_topology=True).intersection(box(x0 - pad, y0 - pad, x1 + pad, y1 + pad))
    if geom.is_empty:
        return
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        polys = [g for g in getattr(geom, "geoms", []) if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return
        geom = unary_union(polys)
    ax.add_patch(patch_for(geom, **kw))


def setup(width_px, height_px, lon0, lon1, lat0, lat1):
    fig = plt.figure(figsize=(width_px / 100, height_px / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    mid = math.radians((lat0 + lat1) / 2)
    ax.set_aspect(1 / math.cos(mid), adjustable="datalim")
    ax.axis("off")
    ax.add_patch(plt.Rectangle((lon0, lat0), lon1 - lon0, lat1 - lat0, color=SEA, zorder=0))
    return fig, ax


def label(ax, x, y, s, size=11, color=INK, weight="normal", style="normal", ha="center", va="center", z=10):
    t = ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, fontstyle=style, ha=ha, va=va, zorder=z)
    t.set_path_effects([pe.withStroke(linewidth=2.6, foreground="white", alpha=0.85)])
    return t


def city(ax, x, y, s, dx=0.0, dy=0.0, ha="left", size=10.5, dot=4.5):
    ax.plot([x], [y], "o", ms=dot, mfc=INK, mec="white", mew=1, zorder=11)
    label(ax, x + dx, y + dy, s, size=size, ha=ha)


def save_svg(fig, path, w, h, title):
    import re
    fig.savefig(path, format="svg", facecolor=SEA, metadata={"Date": None, "Creator": "Prankster News tools/make_maps.py"})
    t = open(path, encoding="utf-8").read()
    def fix_tag(m):
        tag = re.sub(r'\swidth="[^"]+"', f' width="{w}"', m.group(0), count=1)
        return re.sub(r'\sheight="[^"]+"', f' height="{h}"', tag, count=1)
    t = re.sub(r'<svg [^>]*>', fix_tag, t, count=1)
    t = re.sub(r'(<svg [^>]*>)', r'\1<title>' + title + '</title>', t, count=1)
    open(path, "w", encoding="utf-8").write(t)


def credit(fig, text):
    fig.text(0.012, 0.012, text, fontsize=8.5, color="#555", ha="left", va="bottom", zorder=20)


def scalebar(ax, lon, lat, km):
    deg = km / (111.32 * math.cos(math.radians(lat)))
    ax.plot([lon, lon + deg], [lat, lat], color=INK, lw=2.2, solid_capstyle="butt", zorder=12)
    for x in (lon, lon + deg):
        ax.plot([x, x], [lat - 0.004, lat + 0.004], color=INK, lw=2.2, zorder=12)
    label(ax, lon + deg / 2, lat + 0.02, f"{km} km", size=9.5)


countries = layer("ne_10m_admin_0_countries")
by_name = {d["NAME"]: g for d, g in countries}


# ---------------------------------------------------------------- Gaza
def gaza():
    W, H = 1200, 880
    lon0, lon1, lat0, lat1 = 33.98, 35.02, 31.04, 31.72
    fig, ax = setup(W, H, lon0, lon1, lat0, lat1)
    for name, g in by_name.items():
        draw(ax, g, tol=0.003, fc=LAND, ec=BORDER, lw=0.9, zorder=1)
    pal = by_name["Palestine"]
    gaza_poly = [p for p in pal.geoms if p.bounds[0] < 34.4][0]
    wb = [p for p in pal.geoms if p.bounds[0] > 34.4]
    for p in wb:
        draw(ax, p, fc="#e4efe6", ec=BORDER, lw=0.9, zorder=2)
    draw(ax, gaza_poly, fc="#bfdcc9", ec=GREEN, lw=2.2, zorder=3)

    label(ax, 34.17, 31.43, "GAZA STRIP", size=14, weight="bold", color="#245a42")
    label(ax, 34.87, 31.565, "ISRAEL", size=14, weight="bold", color="#555")
    label(ax, 34.12, 31.10, "EGYPT", size=14, weight="bold", color="#555", va="center")
    label(ax, 34.12, 31.62, "Mediterranean\nSea", size=12, style="italic", color="#4a6f8a")
    label(ax, 35.00, 31.68, "West Bank →", size=10, color="#4f7a5d", ha="right", style="italic")

    city(ax, 34.4668, 31.5017, "Gaza City", dx=0.025, dy=0.0)
    city(ax, 34.3515, 31.4183, "Deir al-Balah", dx=0.025, dy=-0.005)
    city(ax, 34.3063, 31.3462, "Khan Younis", dx=0.025, dy=-0.005)
    city(ax, 34.2435, 31.2969, "Rafah", dx=0.025, dy=-0.005)
    city(ax, 34.571, 31.669, "Ashkelon", dx=0.02, dy=0.0)

    scalebar(ax, 34.45, 31.09, 10)
    # locator inset (top-right sea area is occupied; use bottom-left of the Mediterranean)
    ins = fig.add_axes([0.735, 0.075, 0.24, 0.30])
    ilon0, ilon1, ilat0, ilat1 = 25.0, 40.0, 26.0, 38.0
    ins.set_xlim(ilon0, ilon1); ins.set_ylim(ilat0, ilat1)
    ins.set_aspect(1 / math.cos(math.radians(32)))
    ins.set_xticks([]); ins.set_yticks([])
    for s in ins.spines.values():
        s.set_color("#777"); s.set_linewidth(1)
    ins.add_patch(plt.Rectangle((ilon0, ilat0), ilon1 - ilon0, ilat1 - ilat0, color=SEA, zorder=0))
    for name, g in by_name.items():
        draw(ins, g, tol=0.03, fc=LAND, ec=BORDER, lw=0.4, zorder=1)
    draw(ins, pal, tol=0.01, fc="#a9d1b8", ec=GREEN, lw=0.6, zorder=2)
    ins.add_patch(plt.Rectangle((lon0, lat0), lon1 - lon0, lat1 - lat0, fill=False, ec=ACCENT, lw=1.6, zorder=3))
    for x, y, s in [(27.5, 28.0, "EGYPT"), (35.8, 35.0, "SYRIA"), (37.5, 31.0, "SAUDI\nARABIA"), (36.8, 32.7, "JORDAN"), (34.2, 32.6, "ISRAEL")]:
        pass
    ins.text(28.5, 28.0, "Egypt", fontsize=8, color="#555", ha="center")
    ins.text(36.9, 30.2, "Saudi\nArabia", fontsize=7, color="#555", ha="center")
    ins.text(29.5, 35.0, "Mediterranean Sea", fontsize=7, color="#4a6f8a", ha="center", style="italic")
    fig.text(0.735 + 0.12, 0.075 + 0.30 + 0.008, "Location of the Gaza Strip", fontsize=8.5, ha="center", color="#444")
    credit(fig, "Map: Prankster News. Data: Natural Earth (public domain). Boundaries are generalized, for orientation only.")
    save_svg(fig, f"{OUT}/gaza-map.svg", W, H, "Map of the Gaza Strip and surrounding area with major cities")
    plt.close(fig)


# ------------------------------------------------------------- Ukraine
def ukraine():
    W, H = 1280, 880
    lon0, lon1, lat0, lat1 = 21.2, 41.6, 43.3, 52.9
    fig, ax = setup(W, H, lon0, lon1, lat0, lat1)
    provinces = layer("ne_10m_admin_1_states_provinces")
    ukr_regions = {}
    for d, g in provinces:
        if d["admin"] == "Ukraine":
            ukr_regions[d["name"]] = g
        elif d["admin"] == "Russia" and d["name"] in ("Crimea", "Sevastopol"):
            ukr_regions[d["name"]] = g
    for name, g in by_name.items():
        if name != "Ukraine":
            draw(ax, g, tol=0.01, fc="#e7e3da", ec=BORDER, lw=0.9, zorder=1)
    ukr_all = unary_union(list(ukr_regions.values()))
    draw(ax, ukr_all, tol=0.01, fc=LAND, ec="none", zorder=2)
    # oblast borders
    for n, g in ukr_regions.items():
        draw(ax, g, tol=0.01, fc="none", ec="#bcb6a8", lw=0.6, zorder=3)
    held = ["Crimea", "Sevastopol", "Luhans'k", "Donets'k", "Zaporizhzhya", "Kherson"]
    for n in held:
        draw(ax, ukr_regions[n], tol=0.01, fc="#e7b3ad", ec="#bcb6a8", lw=0.6, zorder=4)
    draw(ax, ukr_all, tol=0.01, fc="none", ec="#3a3a3a", lw=1.9, zorder=6)

    label(ax, 31.2, 49.15, "UKRAINE", size=21, weight="bold", color="#3a3a3a")
    label(ax, 39.5, 52.3, "RUSSIA", size=15, weight="bold", color="#777")
    label(ax, 28.0, 53.0 - 0.45, "BELARUS", size=13, weight="bold", color="#777")
    label(ax, 22.8, 51.5, "POLAND", size=12, weight="bold", color="#777")
    label(ax, 21.9, 47.5, "HUNGARY", size=10.5, weight="bold", color="#777", ha="left")
    label(ax, 25.3, 46.4, "ROMANIA", size=12, weight="bold", color="#777")
    label(ax, 28.55, 47.15, "MOLDOVA", size=9, weight="bold", color="#777")
    label(ax, 32.0, 44.2, "Black Sea", size=14, style="italic", color="#4a6f8a")
    label(ax, 36.9, 46.15, "Sea of\nAzov", size=10.5, style="italic", color="#4a6f8a")

    pts = [
        ("Kyiv", 30.5234, 50.4501, 0.2, 0.0, "left"),
        ("Lviv", 24.0297, 49.8397, 0.2, 0.0, "left"),
        ("Kharkiv", 36.2304, 49.9935, 0.2, 0.0, "left"),
        ("Dnipro", 35.0462, 48.4647, 0.2, 0.0, "left"),
        ("Odesa", 30.7233, 46.4825, -0.2, 0.05, "right"),
        ("Zaporizhzhia", 35.139, 47.8388, -0.2, -0.2, "right"),
        ("Donetsk", 37.8028, 48.0159, 0.2, 0.0, "left"),
        ("Luhansk", 39.3078, 48.574, -0.2, 0.25, "right"),
        ("Mariupol", 37.5433, 47.0971, 0.0, -0.3, "center"),
        ("Kherson", 32.6178, 46.6354, 0.2, 0.28, "left"),
        ("Simferopol", 34.1, 44.9521, -0.2, -0.33, "center"),
    ]
    for n, x, y, dx, dy, ha in pts:
        city(ax, x, y, n, dx=dx, dy=dy, ha=ha, size=10.5, dot=5)
    # capital marker star
    ax.plot([30.5234], [50.4501], "*", ms=13, mfc="#222", mec="white", mew=1, zorder=12)

    # legend
    handles = [
        Patch(fc="#e7b3ad", ec="#bcb6a8", label="Regions Russia holds in whole or in part"),
        Patch(fc=LAND, ec="#3a3a3a", label="Ukraine's internationally recognized borders"),
    ]
    leg = ax.legend(handles=handles, loc="lower left", fontsize=10, frameon=True, framealpha=0.95, edgecolor="#999", bbox_to_anchor=(0.012, 0.045))
    leg.set_zorder(30)
    fig.text(0.5, 0.045 - 0.0, "", fontsize=1)
    scalebar_lat = 43.62
    deg = 200 / (111.32 * math.cos(math.radians(scalebar_lat)))
    x0 = 38.2
    ax.plot([x0, x0 + deg], [scalebar_lat, scalebar_lat], color=INK, lw=2.2, solid_capstyle="butt", zorder=12)
    for x in (x0, x0 + deg):
        ax.plot([x, x], [scalebar_lat - 0.06, scalebar_lat + 0.06], color=INK, lw=2.2, zorder=12)
    label(ax, x0 + deg / 2, scalebar_lat + 0.25, "200 km", size=9.5)
    credit(fig, "Map: Prankster News. Data: Natural Earth (public domain). The front line is not shown; it changes often. Russia also holds small areas elsewhere.")
    save_svg(fig, f"{OUT}/ukraine-map.svg", W, H, "Map of Ukraine showing the regions Russia holds in whole or in part")
    plt.close(fig)


if __name__ == "__main__":
    ocean = None
    gaza()
    ukraine()
