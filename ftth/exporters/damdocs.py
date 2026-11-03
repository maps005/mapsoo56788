"""Dam deliverables: the drawing set (A3: general layout, long section on the axis, the maximum cross-section,
spillway and outlet, the area-capacity curve with the design data) and the design report (A4), from ftth.dam."""
from __future__ import annotations

import io
import math

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import KeepTogether, Paragraph, Spacer

from .. import calc, dam as D
from ..model import Design
from . import plans as P, sheets as SH
from .common import Stamp, markup
from .engineering import H1, H2, NOTE, P8, P8B, _doc, _table

INK, GREY, WATER = colors.HexColor("#22313f"), colors.HexColor("#7b8794"), colors.HexColor("#1565c0")
ZONES = {"shell": "#d9c7a3", "core": "#a1887f", "filter": "#fff3c4", "drain": "#cfd8dc", "riprap": "#90a4ae",
         "ground": "#e8dccb", "cutoff": "#8d6e63"}
PRELIM = ("Preliminary design for costing, approvals and coordination: the registered dam engineer's design, the "
          "geotechnical and hydrological investigations and the Water Resources Authority's dam safety approval govern.")


def _text(cv, x, y, s, size=7, bold=False, color=INK, align="left"):
    cv.setFillColor(color)
    cv.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    (cv.drawString if align == "left" else cv.drawCentredString if align == "centre" else cv.drawRightString)(x, y, s)


def _poly(cv, pts, fill=None, stroke=INK, width=0.6, dash=None):
    cv.saveState()
    if fill:
        cv.setFillColor(colors.HexColor(fill) if isinstance(fill, str) else fill)
    if stroke:
        cv.setStrokeColor(stroke)
    cv.setLineWidth(width)
    if dash:
        cv.setDash(dash)
    p = cv.beginPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    p.close()
    cv.drawPath(p, fill=1 if fill else 0, stroke=1 if stroke else 0)
    cv.restoreState()


def _line(cv, pts, color=INK, width=0.6, dash=None):
    cv.saveState()
    cv.setStrokeColor(color)
    cv.setLineWidth(width)
    if dash:
        cv.setDash(dash)
    for a, b in zip(pts, pts[1:]):
        cv.line(*a, *b)
    cv.restoreState()


def _fit(x0, y0, x1, y1, box, ve=1.0):
    """A transform of (x, y) metres into the box, y exaggerated ve times."""
    bx, by, bw, bh = box
    k = min(bw / max(x1 - x0, 1e-6), bh / max((y1 - y0) * ve, 1e-6))
    ox = bx + (bw - (x1 - x0) * k) / 2
    oy = by + (bh - (y1 - y0) * ve * k) / 2
    return (lambda x, y: (ox + (x - x0) * k, oy + (y - y0) * ve * k)), k


def _level_tag(cv, x, y, label, color=INK):
    cv.saveState()
    cv.setFillColor(color)
    p = cv.beginPath()
    p.moveTo(x, y)
    p.lineTo(x - 3.5, y + 5)
    p.lineTo(x + 3.5, y + 5)
    p.close()
    cv.drawPath(p, fill=1, stroke=0)
    cv.restoreState()
    _text(cv, x + 5, y + 2, label, 6.5, True, color)


def _scale_bar(cv, x, y, k, label="Scale"):
    """A bar of a round length in metres, k points to the metre, at (x, y)."""
    want = 90 / k
    step = next((v for v in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000) if v >= want / 4), 1000)
    n = 4
    for i in range(n):
        cv.setFillColor(INK if i % 2 == 0 else colors.white)
        cv.setStrokeColor(INK)
        cv.setLineWidth(0.4)
        cv.rect(x + i * step * k, y, step * k, 3, fill=1, stroke=1)
    for i in range(n + 1):
        _text(cv, x + i * step * k, y + 5, f"{i * step:g}", 5.5, align="centre")
    _text(cv, x + n * step * k + 6, y, f"m   {label} 1:{round(72 / 2.54 * 100 / k / 100) * 100 if k else 0:,}"
                                       f" at A3", 5.5, color=GREY)


# ---------------------------------------------------------------------------------------------------------
# the drawing set
# ---------------------------------------------------------------------------------------------------------
def _sheet_layout(cv, d, z, box):
    dm = d.dam
    secs = z["sections"]
    W = z["crest_width"]
    su, sd = z["slope_us"], z["slope_ds"]
    ch0, ch1 = secs[0]["ch"], secs[-1]["ch"]
    up = max(W / 2 + su * s["h"] for s in secs) + 30
    dn = max(W / 2 + sd * s["h"] for s in secs) + 70
    bx, by, bw, bh = box
    sw = z["spillway"]["width"]
    c_sp = ch1 + 10 if dm.spillway_side == "right" else ch0 - 10 - sw
    T, k = _fit(min(ch0 - 20, c_sp - 5), -up, max(ch1 + 20, c_sp + sw + 5), dn, (bx, by + 20, bw - 260, bh - 30))
    # the reservoir upstream of the upstream toe, the river downstream
    toe = [T(s["ch"], -(W / 2 + su * s["h"]) - 1) for s in secs]
    _poly(cv, [T(ch0 - 20, -up), T(ch1 + 20, -up), T(ch1 + 20, -W / 2 - 1)] + list(reversed(toe))
          + [T(ch0 - 20, -W / 2 - 1)], fill="#cfe3f7", stroke=None)
    _text(cv, *T((ch0 + ch1) / 2, -up * 0.93), f"RESERVOIR  FSL {z['fsl']:.2f} m  ({z['storage']:,} m3)", 8, True, WATER, "centre")
    bed = min(secs, key=lambda s: s["ground"])
    _line(cv, [T(bed["ch"], dn * 0.4), T(bed["ch"], dn)], WATER, 3)
    _text(cv, *T(bed["ch"] + 3, dn * 0.85), f"{dm.river or 'River'} (downstream)", 6.5, False, WATER)
    # the embankment's footprint: the toes and the crest
    up_toe = [T(s["ch"], -(W / 2 + su * s["h"])) for s in secs if s["h"] > 0]
    dn_toe = [T(s["ch"], W / 2 + sd * s["h"]) for s in secs if s["h"] > 0]
    if up_toe:
        _poly(cv, up_toe + list(reversed(dn_toe)), fill=ZONES["shell"], width=0.8)
        crest = [s for s in secs if s["h"] > 0]
        _poly(cv, [T(crest[0]["ch"], -W / 2), T(crest[-1]["ch"], -W / 2), T(crest[-1]["ch"], W / 2), T(crest[0]["ch"], W / 2)],
              fill="#efe6d2", width=0.8)
    _line(cv, [T(ch0, 0), T(ch1, 0)], colors.HexColor("#c62828"), 0.8, [8, 3, 2, 3])
    for c in range(int(ch0), int(ch1) + 1, 20):  # chainages
        x, y = T(c, 0)
        cv.setStrokeColor(INK)
        cv.line(x, y - 3, x, y + 3)
        _text(cv, x, y - 10, f"{c}", 5.5, align="centre")
    _text(cv, *T(ch0, 4), "AXIS  CH 0", 6.5, True, colors.HexColor("#c62828"))
    _scale_bar(cv, bx + 10, by + 6, k)
    # the spillway: a channel through the chosen abutment, from the reservoir downstream
    _poly(cv, [T(c_sp, -up * 0.45), T(c_sp + sw, -up * 0.45), T(c_sp + sw, dn * 0.9), T(c_sp, dn * 0.9)], fill="#e0e0e0", width=0.8)
    _line(cv, [T(c_sp, 0), T(c_sp + sw, 0)], INK, 2)
    _text(cv, *T(c_sp + sw / 2, dn * 0.5), f"SPILLWAY {sw:g} m", 6.5, True, align="centre")
    # the outlet under the dam at the river bed
    base = W / 2 + max(su, sd) * bed["h"]
    _line(cv, [T(bed["ch"] + 6, -base - 8), T(bed["ch"] + 6, base + 12)], colors.HexColor("#2e7d32"), 1.4)
    _text(cv, *T(bed["ch"] + 9, base + 6), f"OUTLET DN{z['outlet']['dn']}", 6.5, True, colors.HexColor("#2e7d32"))
    SH.north_arrow(cv, bx + bw - 270, by + bh - 30)
    lx, ly = bx + bw - 235, by + bh - 6
    _text(cv, lx, ly, "KEY FIGURES", 9, True)
    rows = [["Dam type", "Zoned earthfill, clay core"], ["Crest level", f"{z['crest']:.2f} m (+{z['camber']:g} m camber)"],
            ["Height", f"{z['height']:g} m (bed), {z['foundation_height']:g} m (foundation)"], ["Crest", f"{z['crest_length']:g} m long, {W:g} m wide"],
            ["Slopes", f"1:{su:g} upstream, 1:{sd:g} downstream"], ["FSL / MFL", f"{z['fsl']:.2f} / {z['mfl']:.2f} m"],
            ["Storage at FSL", f"{z['storage']:,} m3"],
            ["Design flood", f"{z['hydrology']['q100']:g} m3/s (1 in {z['flood']['T_design']:,})"],
            ["Check flood", f"{z['hydrology']['q_check']:g} m3/s (1 in {z['flood']['T_check']:,})"],
            ["Spillway", f"{sw:g} m, {z['spillway']['h100']:g} m head"], ["Embankment", f"{z['volumes']['total']:,} m3"],
            ["Hazard class", z["flood"]["hazard"]],
            ["Class", "Large dam (ICOLD)" if z["large_dam"] else "Small dam"]]
    SH.table(cv, lx, ly - 6, ["Item", "Design"], rows, [80, 145], size=6.5, row_h=10)
    if len(d.info.boundary) >= 3:
        SH.location_plan(cv, d, (lx, by + 30, 225, 150))
    return None


def _sheet_long(cv, d, z, box):
    secs = z["sections"]
    ch0, ch1 = secs[0]["ch"], secs[-1]["ch"]
    lo = min(s["ground"] - s["cut_depth"] for s in secs) - 3
    hi = z["crest"] + 4
    bx, by, bw, bh = box
    ve = max(1.0, min(10.0, round((ch1 - ch0) / max(hi - lo, 1) / 3)))
    T, k = _fit(ch0 - 10, lo, ch1 + 10, hi, (bx + 50, by + 40, bw - 70, bh - 60), ve)
    # ground and the cut-off trench
    g = [T(s["ch"], s["ground"]) for s in secs]
    _poly(cv, [T(ch0 - 10, lo)] + [T(ch0 - 10, secs[0]["ground"])] + g + [T(ch1 + 10, secs[-1]["ground"]), T(ch1 + 10, lo)],
          fill=ZONES["ground"], width=0.4)
    cut = [s for s in secs if s["ground"] <= z["crest"] + 1e-6]  # the embankment, abutment to abutment
    if cut:
        _poly(cv, [T(s["ch"], s["ground"]) for s in cut] + [T(s["ch"], s["ground"] - s["cut_depth"]) for s in reversed(cut)],
              fill=ZONES["cutoff"], width=0.5)
        # the embankment above the ground, to the crest
        _poly(cv, [T(cut[0]["ch"], z["crest"])] + [T(s["ch"], s["ground"]) for s in cut] + [T(cut[-1]["ch"], z["crest"])],
              fill=ZONES["shell"], width=0.7)
    _line(cv, g, INK, 1.0)
    for lvl, name, col, dash in ((z["crest"], f"CREST {z['crest']:.2f}", INK, None), (z["mfl"], f"MFL {z['mfl']:.2f}", WATER, [4, 2]),
                                 (z["fsl"], f"FSL {z['fsl']:.2f}", WATER, None), (z["mol"], f"MOL {z['mol']:.2f}", WATER, [2, 2])):
        _line(cv, [T(ch0 - 10, lvl), T(ch1 + 10, lvl)], col, 0.6, dash)
        _level_tag(cv, *T(ch1 + 10, lvl), name, col)
    # grid: chainages and levels
    for c in range(int(ch0), int(ch1) + 1, 20):
        x = T(c, 0)[0]
        _text(cv, x, by + 26, f"{c}", 5.5, align="centre")
        s = min(secs, key=lambda s: abs(s["ch"] - c))
        _text(cv, x, by + 16, f"{s['ground']:.1f}", 5.5, align="centre", color=GREY)
    _text(cv, bx + 4, by + 26, "Chainage (m)", 6, True)
    _text(cv, bx + 4, by + 16, "Ground (m)", 6, True)
    for lvl in range(int(lo // 5 * 5), int(hi) + 1, 5):
        _text(cv, bx + 44, T(0, lvl)[1] - 2, f"{lvl}", 5.5, align="right", color=GREY)
    _scale_bar(cv, bx + bw - 330, by + 2, k, "Horizontal")
    _text(cv, bx + 50, by + bh - 8, f"LONG SECTION ON THE DAM AXIS (looking downstream), vertical scale x{ve:g}. "
                                    f"Cut-off trench to firm ground + 0.5 m (brown).", 8, True)


def _sheet_section(cv, d, z, box):
    dm = d.dam
    s = max(z["sections"], key=lambda s: s["h"])
    h, W, su, sd = s["h"], z["crest_width"], z["slope_us"], z["slope_ds"]
    g = s["ground"]
    crest = z["crest"]
    hc = z["core_top_level"] - g
    up = W / 2 + su * h
    dn = W / 2 + sd * h
    bx, by, bw, bh = box
    T, k = _fit(-up - 8, g - s["cut_depth"] - 3, dn + 8, crest + 4, (bx + 20, by + 50, bw - 40, bh - 70))
    _poly(cv, [T(-up - 8, g - s["cut_depth"] - 3), T(dn + 8, g - s["cut_depth"] - 3), T(dn + 8, g), T(-up - 8, g)],
          fill=ZONES["ground"], width=0.4)
    # cut-off trench under the core
    cw, cd = dm.cutoff_width, s["cut_depth"]
    _poly(cv, [T(-cw / 2 - cd, g), T(cw / 2 + cd, g), T(cw / 2, g - cd), T(-cw / 2, g - cd)], fill=ZONES["cutoff"], width=0.6)
    # the shells
    _poly(cv, [T(-up, g), T(dn, g), T(W / 2, crest), T(-W / 2, crest)], fill=ZONES["shell"], width=0.9)
    # drainage blanket from the chimney to the toe drain: 0.3 m sand under 0.6 m gravel
    b0 = dm.core_top / 2 + dm.core_slope * hc + dm.filter_width
    b1 = dn - 2.5
    _poly(cv, [T(b0, g), T(b1, g), T(b1, g + 0.3), T(b0, g + 0.3)], fill=ZONES["filter"], width=0.4)
    _poly(cv, [T(b0, g + 0.3), T(b1, g + 0.3), T(b1 - 0.6 * sd, g + 0.9), T(b0, g + 0.9)], fill=ZONES["drain"], width=0.5)
    # the toe drain: a gravel trench with a perforated pipe, at the downstream toe
    _poly(cv, [T(b1, g + 0.9), T(dn + 1.5, g), T(dn + 1.5, g - 1.5), T(b1, g - 1.5)], fill=ZONES["drain"], width=0.6)
    px, py = T(dn - 0.5, g - 0.9)
    cv.setStrokeColor(INK)
    cv.setFillColor(colors.white)
    cv.circle(px, py, max(1.5, 0.15 * k), fill=1, stroke=1)
    _text(cv, *T(dn - 2, g - 2.6), "TOE DRAIN: 150 mm perforated pipe to the seepage weir", 6, align="right")
    # chimney filter downstream of the core
    ct = z["core_top_level"]
    f = dm.filter_width
    _poly(cv, [T(dm.core_top / 2, ct), T(dm.core_top / 2 + f, ct), T(dm.core_top / 2 + f + dm.core_slope * hc, g),
               T(dm.core_top / 2 + dm.core_slope * hc, g)], fill=ZONES["filter"], width=0.5)
    # the core
    _poly(cv, [T(-dm.core_top / 2 - dm.core_slope * hc, g), T(dm.core_top / 2 + dm.core_slope * hc, g),
               T(dm.core_top / 2, ct), T(-dm.core_top / 2, ct)], fill=ZONES["core"], width=0.8)
    # riprap on the upstream face, from the crest to below the MOL
    lo_r = max(g, z["mol"] - 1.5)
    t = z["riprap"]["thickness"] + 0.3
    dx = t * math.sqrt(1 + su * su)
    xa, xb = -W / 2, -(W / 2 + su * (crest - lo_r))
    _poly(cv, [T(xa, crest), T(xb, lo_r), T(xb + dx, lo_r), T(xa + dx * 0.6, crest)], fill=ZONES["riprap"], width=0.5)
    # water and levels
    _poly(cv, [T(-up - 8, g), T(-up, g), T(-(W / 2 + su * (crest - z["fsl"])), z["fsl"]), T(-up - 8, z["fsl"])],
          fill="#cfe3f7", stroke=None)
    for lvl, name, col in ((crest, f"CREST {crest:.2f}", INK), (z["mfl"], f"MFL {z['mfl']:.2f}", WATER),
                           (z["fsl"], f"FSL {z['fsl']:.2f}", WATER), (z["mol"], f"MOL {z['mol']:.2f}", WATER),
                           (g, f"BED {g:.2f}", INK)):
        x = T(-up - 6, lvl)[0]
        _level_tag(cv, x, T(0, lvl)[1], name, col)
    _text(cv, *T(-W / 2 - su * h / 2 - 6, g + h / 2 + 2), f"1:{su:g}", 7, True, align="right")
    _text(cv, *T(W / 2 + sd * h / 2 + 6, g + h / 2 + 2), f"1:{sd:g}", 7, True)
    _text(cv, *(lambda p: (p[0], p[1] + 6))(T(0, crest)), f"CREST {W:g} m, gravel road", 7, True, align="centre")
    # legend
    lx, ly = bx + bw - 190, by + bh - 20
    for i, (name, key) in enumerate((("Shell fill, compacted 300 mm layers", "shell"), ("Clay core, compacted 150 mm layers", "core"),
                                     ("Chimney filter and blanket sand layer, graded sand", "filter"),
                                     ("Drainage blanket and toe drain, graded gravel", "drain"),
                                     (f"Riprap {z['riprap']['thickness']:g} m (D50 {z['riprap']['d50']:g} m) on 0.3 m bedding",
                                      "riprap"), ("Cut-off trench, clay backfill", "cutoff"))):
        _poly(cv, [(lx, ly - i * 12), (lx + 14, ly - i * 12), (lx + 14, ly - i * 12 + 8), (lx, ly - i * 12 + 8)], fill=ZONES[key], width=0.4)
        _text(cv, lx + 18, ly - i * 12 + 1, name, 6.5)
    _text(cv, bx + 20, by + bh - 8, f"MAXIMUM CROSS-SECTION AT CH {s['ch']:g} (natural scale): height {h:.1f} m, base "
                                    f"{s['base']:.0f} m", 8, True)
    # instruments: piezometers in the foundation, the core and the downstream shell; settlement pins on the crest
    for x, y in ((0, g - 1.0), (0, g + hc * 0.4), (b0 + 3, g + 0.2), (dn * 0.6, g + 0.2)):
        cx, cy = T(x, y)
        cv.setFillColor(colors.HexColor("#6a1b9a"))
        cv.circle(cx, cy, 2.2, fill=1, stroke=0)
    _text(cv, *T(dn * 0.6 + 1, g + 1.6), "P: piezometers", 6, color=colors.HexColor("#6a1b9a"))
    _text(cv, bx + 20, by + 40, f"Core top {z['core_top_level']:.2f} m: above the check flood level. Piezometers (P) in the "
                                "foundation, core and downstream shell at three sections; settlement pins on the crest.", 6.5,
          color=GREY)
    _text(cv, bx + 20, by + 30, "Compaction to 95 % standard Proctor (shell), 98 % at OMC to +2 % (core). Filter "
                                "gradations to the no-erosion filter criteria on the tested core and shell materials.", 6.5,
          color=GREY)
    _scale_bar(cv, bx + bw - 330, by + 30, k)


def _sheet_spill(cv, d, z, box):
    sp = z["spillway"]
    bx, by, bw, bh = box
    # spillway long section: approach, broad crest at FSL, chute, stilling basin
    fsl = z["fsl"]
    L, B, drop = sp["chute_len"], sp["basin_len"], sp["drop"]
    x_end = 8 + L + B + 10
    T, k = _fit(-30, fsl - drop - 4, x_end, fsl + 4, (bx + 20, by + bh / 2 + 30, bw / 2 - 40, bh / 2 - 70))
    bot = fsl - drop  # the basin floor at the river bed
    ground = [(-30, fsl - 0.5), (0, fsl - 0.5), (0, fsl), (8, fsl), (8 + L, bot), (8 + L + B, bot), (x_end, bot + 1)]
    _poly(cv, [T(*p) for p in ground] + [T(x_end, bot - 4), T(-30, bot - 4)], fill=ZONES["ground"], width=0.5)
    _poly(cv, [T(0, fsl - 1.5), T(8, fsl - 1.5), T(8, fsl), T(0, fsl)], fill="#bdbdbd", width=0.8)  # the crest sill
    _poly(cv, [T(8, fsl), T(8 + L, bot), T(8 + L, bot - 0.3), T(8, fsl - 0.3)], fill="#bdbdbd", width=0.6)  # chute lining
    _poly(cv, [T(8 + L, bot - 0.5), T(8 + L + B, bot - 0.5), T(8 + L + B, bot + 1.0), T(8 + L + B - 0.6, bot + 1.0),
               T(8 + L + B - 0.6, bot), T(8 + L, bot)], fill="#bdbdbd", width=0.8)  # basin slab and end sill
    _line(cv, [T(-30, fsl + sp["h100"]), T(4, fsl + sp["h100"]), T(8, fsl + sp["h100"] * 2 / 3), T(8 + L, bot + sp["y1"] + 0.05),
               T(8 + L + 1, bot + sp["y1"] + 0.05), T(8 + L + 0.6 * B, bot + sp["y2"]), T(x_end, bot + sp["y2"])], WATER, 1.0)
    _text(cv, *(lambda q: (q[0], q[1] - 10))(T(0, fsl)), f"SILL CREST = FSL {fsl:.2f}", 6.5, True, WATER, "right")
    _level_tag(cv, *T(-12, fsl + sp["h100"]), f"MFL {z['mfl']:.2f} (H {sp['h100']:g} m)", WATER)
    _text(cv, bx + 20, by + bh - 8, f"SPILLWAY ({sp['side']} abutment): broad-crested weir {sp['width']:g} m wide, "
                                    f"Q = C B H^1.5 with C {sp['C']:g}; chute and hydraulic-jump stilling basin", 8, True)
    _text(cv, *T(8 + L / 2 + 4, (fsl + bot) / 2 + 1.5), f"lined chute {L:g} m", 6.5)
    _text(cv, *T(8 + L + B / 2, bot - 2.5), f"stilling basin {B:g} m", 6.5, align="centre")
    _scale_bar(cv, bx + 20, by + bh / 2 + 14, k)
    rows = [[f"Design flood (1:{z['flood']['T_design']:,})", f"{z['hydrology']['q100']:g} m3/s", f"head {sp['h100']:g} m"],
            [f"Check flood (1:{z['flood']['T_check']:,})", f"{z['hydrology']['q_check']:g} m3/s", f"head {sp['h_check']:g} m, no overtopping"],
            ["Velocity at the crest", f"{sp['velocity']:g} m/s", "critical flow"],
            ["Chute toe", f"v1 {sp['v1']:g} m/s, y1 {sp['y1']:g} m", f"Froude {sp['fr1']:g}"],
            ["Stilling basin", f"y2 {sp['y2']:g} m, {B:g} m long", "L = 4.5 y2 (USBR)"],
            ["Walls", f"{sp['wall']:g} m high in the basin", "RC, 1.5 m on the chute"],
            ["Abutment cut", f"{sp['cut']:g} m to the crest", "approach 40 m"]]
    SH.table(cv, bx + 20, by + bh / 2 - 6, ["Spillway", "Value", "Note"], rows, [110, 90, 140], size=6.5, row_h=10)
    # outlet section: intake, pipe through the embankment with collars, valve chamber downstream
    s = max(z["sections"], key=lambda s: s["h"])
    W, su, sd = z["crest_width"], z["slope_us"], z["slope_ds"]
    g, crest = s["ground"], z["crest"]
    up, dn = W / 2 + su * s["h"], W / 2 + sd * s["h"]
    T2, k2 = _fit(-up - 10, g - 3, dn + 15, crest + 2, (bx + bw / 2 + 10, by + 40, bw / 2 - 30, bh - 70))
    _poly(cv, [T2(-up, g), T2(dn, g), T2(W / 2, crest), T2(-W / 2, crest)], fill=ZONES["shell"], width=0.7)
    pipe_y = g + 0.4
    _line(cv, [T2(-up - 6, pipe_y), T2(dn + 8, pipe_y)], colors.HexColor("#2e7d32"), 3)
    # a filter diaphragm round the conduit downstream of the core (collars are not used: they hinder compaction)
    xd = d.dam.core_top / 2 + d.dam.core_slope * (z["core_top_level"] - g) + 2
    _poly(cv, [T2(xd, g), T2(xd + 2, g), T2(xd + 2, g + 3.5), T2(xd, g + 3.5)], fill=ZONES["filter"], width=0.6)
    _text(cv, *T2(xd + 3, g + 3.0), "FILTER DIAPHRAGM", 6, True)
    _poly(cv, [T2(-up - 8, g), T2(-up - 4, g), T2(-up - 4, z["mol"] + 0.5), T2(-up - 8, z["mol"] + 0.5)], fill="#bdbdbd")
    _poly(cv, [T2(dn + 6, g - 0.5), T2(dn + 12, g - 0.5), T2(dn + 12, g + 2.5), T2(dn + 6, g + 2.5)], fill="#bdbdbd")
    _text(cv, *T2(-up - 6, z["mol"] + 1.2), "MULTI-LEVEL INTAKE, SCREENS, GUARD GATE", 6, True, align="centre")
    _scale_bar(cv, bx + bw / 2 + 10, by + 22, k2)
    _text(cv, *T2(dn + 9, g + 3.2), "VALVE CHAMBER", 6, True, align="centre")
    _text(cv, bx + bw / 2 + 10, by + bh - 8, f"OUTLET WORKS: DN{z['outlet']['dn']} steel pipe in concrete surround, "
                                             f"filter diaphragm, upstream guard gate", 8, True)
    _text(cv, bx + bw / 2 + 10, by + bh - 20, f"Drawdown FSL to MOL about {z['outlet']['drawdown_days']:g} days with pipe "
                                              f"friction over {z['outlet']['length']:g} m", 7)


def _sheet_capacity(cv, d, z, box):
    cap = z["capacity"]
    bx, by, bw, bh = box
    gx, gy, gw, gh = bx + 60, by + 60, bw * 0.55, bh - 110
    lv0, lv1 = cap[0][0], cap[-1][0]
    vmax = cap[-1][2] or 1
    amax = max(a for _, a, _ in cap) or 1
    X = lambda v: gx + v / vmax * gw  # noqa: E731
    Y = lambda lv: gy + (lv - lv0) / max(lv1 - lv0, 1e-6) * gh  # noqa: E731
    cv.setStrokeColor(GREY)
    cv.rect(gx, gy, gw, gh)
    for i in range(6):
        _text(cv, gx + gw * i / 5, gy - 12, f"{vmax * i / 5 / 1e6:.2f}", 6, align="centre", color=GREY)
        _text(cv, gx + gw * i / 5, gy + gh + 6, f"{amax * (5 - i) / 5 / 1e4:.1f}", 6, align="centre", color=GREY)
    for lvl in range(int(lv0), int(lv1) + 1, 2):
        _text(cv, gx - 4, Y(lvl) - 2, f"{lvl}", 6, align="right", color=GREY)
    _line(cv, [(X(v), Y(lv)) for lv, _, v in cap], WATER, 1.4)
    _line(cv, [(gx + gw - a / amax * gw, Y(lv)) for lv, a, _ in cap], colors.HexColor("#2e7d32"), 1.2, [4, 2])
    for lvl, name in ((z["fsl"], "FSL"), (z["mol"], "MOL"), (z["mfl"], "MFL"), (z["sediment"]["level"], "SEDIMENT 50 yr")):
        if lv0 <= lvl <= lv1 + 3:
            _line(cv, [(gx, Y(lvl)), (gx + gw, Y(lvl))], INK, 0.4, [2, 2])
            _text(cv, gx + 4, Y(lvl) + 2, f"{name} {lvl:.2f}", 6.5, True)
    _text(cv, gx, gy - 26, "Capacity (Mm3), solid blue", 7, True, WATER)
    _text(cv, gx + gw, gy + gh + 16, "Area (ha), dashed green", 7, True, colors.HexColor("#2e7d32"), "right")
    _text(cv, bx + 20, by + bh - 8, "RESERVOIR ELEVATION-AREA-CAPACITY CURVES AND DESIGN DATA", 8, True)
    lx = gx + gw + 30
    hy = z["hydrology"]
    rows = [["Catchment", f"{hy['catchment']:g} km2"], ["Time of concentration", f"{hy['tc_min']:g} min (Kirpich)"],
            ["Intensity", f"{hy['intensity']:g} mm/h (Mononobe)"],
            [f"Design flood 1:{z['flood']['T_design']:,}", f"{hy['q100']:g} m3/s"],
            [f"Check flood 1:{z['flood']['T_check']:,}", f"{hy['q_check']:g} m3/s"],
            [f"Sediment, {z['sediment']['years']} yr", f"{z['sediment']['volume']:,} m3 to {z['sediment']['level']:.2f} m"],
            ["Storage at FSL", f"{z['storage']:,} m3"], ["Dead storage", f"{z['dead']:,} m3"], ["Live storage", f"{z['live']:,} m3"],
            ["Water area at FSL", f"{z['area_fsl'] / 1e4:.1f} ha"], ["Wave / run-up", f"{z['freeboard']['wave']:g} / {z['freeboard']['runup']:g} m"],
            ["Freeboard over FSL", f"{z['freeboard']['above_fsl']:g} m"], ["Seepage (core)", f"{z['seepage_m3_day']:g} m3/day"]]
    rows += [[f"{s['case']} ({s['face'][0].upper()}/S)", f"F = {s['F']:g} (min {s['need']:g})"] for s in z["stability"]]
    SH.table(cv, lx, by + bh - 24, ["Design data", "Value"], rows, [130, 120], size=6.5, row_h=10)


def drawings_pdf(d: Design, st: Stamp) -> bytes:
    buf = io.BytesIO()
    cv = rl_canvas.Canvas(buf, pagesize=(P.W, P.H))
    z = D.design(d.dam) if d.dam else None
    full = (P.M + 14, P.M + 60, P.W - 2 * P.M - 28, P.H - 2 * P.M - 80)
    pages = [("General layout", _sheet_layout), ("Long section on the dam axis", _sheet_long),
             ("Maximum cross-section and zoning", _sheet_section), ("Spillway and outlet works", _sheet_spill),
             ("Area-capacity curves and design data", _sheet_capacity)]
    if not z:
        P._frame(cv, d, st, "Dam drawings", 1, 1, None)
        _text(cv, P.M + 20, P.H / 2, "No dam survey yet: enter the axis profile and the reservoir table in the Dam tab.", 11)
        cv.showPage()
    else:
        for i, (title, fn) in enumerate(pages, start=1):
            P._frame(cv, d, st, title, i, len(pages), "Scales as shown (A3); vertical exaggeration as noted")
            fn(cv, d, z, full)
            _text(cv, P.M + 14, P.M + 52, PRELIM, 6.5, color=colors.HexColor("#b42318"))
            cv.showPage()
    cv.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------------
# the design report
# ---------------------------------------------------------------------------------------------------------
def report_pdf(d: Design, st: Stamp) -> bytes:
    buf, doc, frame = _doc(d, st, "Dam design report", A4)
    dm = d.dam
    z = D.design(dm) if dm else None
    story = [Paragraph(markup(f"Dam design report (preliminary) - {d.info.name}"), H1),
             Paragraph(markup(f"{d.info.area}. {dm.name if dm else ''} on {dm.river if dm and dm.river else 'the river'}. "
                              f"Prepared by {d.info.prepared_by or '-'}."), P8), Paragraph(PRELIM, NOTE), Spacer(1, 6)]
    if not z:
        story.append(Paragraph("No dam survey yet: enter the axis profile and the reservoir table.", P8))
        doc.build(story, onFirstPage=frame, onLaterPages=frame)
        return buf.getvalue()
    w = A4[0] - 24 * mm

    def sec(title, rows):
        data = [[Paragraph("Item", P8B), Paragraph("Basis / calculation", P8B), Paragraph("Result", P8B)]]
        data += [[Paragraph(markup(a), P8), Paragraph(markup(b), P8), Paragraph(markup(c), P8B)] for a, b, c in rows]
        story.append(KeepTogether([Paragraph(title, H2), _table(data, [w * 0.2, w * 0.55, w * 0.25])]))
    hy, sp, fb, fl = z["hydrology"], z["spillway"], z["freeboard"], z["flood"]
    sec("1. Introduction and site", [
        ("Purpose", d.info.introduction or "Water supply storage", ""),
        ("Site", f"{dm.river or 'River'}; axis surveyed over {z['sections'][-1]['ch'] - z['sections'][0]['ch']:g} m, river bed "
                 f"{z['bed']:.2f} m", "survey"),
        ("Foundations", "depth to firm ground along the axis from the trial pits / boreholes; cut-off trench 0.5 m into it",
         f"{max(s['firm'] for s in z['sections']):g} m deepest"),
        ("Dam type", "zoned earthfill: clay core, free-draining shells, chimney filter and blanket drain, upstream riprap",
         "large dam (ICOLD)" if z["large_dam"] else "small dam"),
    ])
    sec("2. Hydrology", [
        ("Catchment", f"{hy['catchment']:g} km2; watercourse {dm.stream_km:g} km at {dm.stream_slope:g} %", ""),
        ("Time of concentration", f"Kirpich: tc = 0.0195 L^0.77 S^-0.385", f"{hy['tc_min']:g} min"),
        ("Flood standard", f"hazard class '{fl['hazard']}' (by the consequence of a breach): design flood 1 in "
                           f"{fl['T_design']:,} years, safety check flood 1 in {fl['T_check']:,} years", ""),
        ("Design storm", f"P24 (1 in 100) = {dm.rain_24h:g} mm grown to 1 in {fl['T_design']:,} by EV1 with CV {dm.rain_cv:g}; "
                         f"Mononobe: i = P24/24 (24/tc)^(2/3)", f"P24 {fl['p_design']:g} mm, i {hy['intensity']:g} mm/h"),
        ("Design flood", f"Rational: Q = 0.278 C i A, C = {dm.runoff_flood:g}" + (" (given)" if dm.design_flood else ""),
         f"Q{fl['T_design']} = {hy['q100']:g} m3/s"),
        ("Safety check flood", f"P24 {fl['p_check']:g} mm, i {fl['i_check']:g} mm/h, C {fl['c_check']:g} (wetter ground): "
                               "no overtopping", f"{hy['q_check']:g} m3/s"),
        ("Flood confirmation", "the TRRL East African flood model and routing through the reservoir in the detailed design; "
                               "the spillway is sized without routing attenuation (conservative)", ""),
        ("Annual inflow", f"{dm.rain_annual:g} mm x {dm.runoff_annual:g} runoff over the catchment", f"{z['yield']['inflow']:,} m3"),
    ])
    sec("3. Reservoir", [
        ("Full supply level", "the spillway crest" + (" (given)" if dm.fsl else " (from the target storage)" if dm.target_storage else ""),
         f"FSL {z['fsl']:.2f} m"),
        ("Storage", f"elevation-area table, prismoidal volumes; area at FSL {z['area_fsl'] / 1e4:.1f} ha", f"{z['storage']:,} m3"),
        ("Sediment", f"yield {dm.sediment_yield:g} t/km2/yr over {dm.sediment_years} years at 1.3 t/m3; the intake 1 m above it",
         f"{z['sediment']['volume']:,} m3 to {z['sediment']['level']:.2f} m"),
        ("Dead / live storage", f"below / above the outlet (MOL {z['mol']:.2f} m)", f"{z['dead']:,} / {z['live']:,} m3"),
        ("Water balance", f"use {z['yield']['demand']:,} m3/yr ({dm.demand:g} m3/day), evaporation {z['yield']['evaporation']:,} m3/yr; "
                          f"6-month dry season needs {z['yield']['dry_season']:,} m3", "OK" if z["yield"]["ok"] else "SHORT: REVIEW"),
    ])
    sec("4. Spillway", [
        ("Type", f"broad-crested side spillway on the {sp['side']} abutment, crest at FSL, lined chute, stilling basin", ""),
        ("Capacity", f"Q = C B H^1.5, C = {sp['C']:g}, B = {sp['width']:g} m; no routing attenuation (conservative)",
         f"H100 = {sp['h100']:g} m, Hcheck = {sp['h_check']:g} m"),
        ("Velocity", "critical flow over the crest", f"{sp['velocity']:g} m/s"),
        ("Abutment cut", f"from the abutment ground to the crest, 40 m approach channel", f"{sp['cut']:g} m deep"),
        ("Chute", f"lined, about 1 in 4 over the {sp['drop']:g} m drop; v1 = 0.9 (2 g (drop + H))^0.5",
         f"{sp['chute_len']:g} m, v1 {sp['v1']:g} m/s"),
        ("Stilling basin", f"hydraulic jump: y2 = y1/2 ((1 + 8 Fr^2)^0.5 - 1), Fr = {sp['fr1']:g}; L = 4.5 y2; end sill",
         f"y2 {sp['y2']:g} m, {sp['basin_len']:g} m, walls {sp['wall']:g} m"),
    ])
    sec("5. Freeboard and crest", [
        ("Waves", f"fetch {fb['fetch_km']:g} km, wind {dm.wind_kmh:g} km/h; Molitor-Stevenson hw = 0.032 (U F)^0.5 + 0.763 - 0.271 F^0.25",
         f"hw = {fb['wave']:g} m, run-up {fb['runup']:g} m"),
        ("Crest (normal)", "FSL + run-up + 0.5 m", f"{fb['normal']:.2f} m"),
        ("Crest (design flood)", "MFL + half the run-up + 0.5 m", f"{fb['flood']:.2f} m"),
        ("Crest (check flood)", "check flood level + 0.3 m", f"{fb['check']:.2f} m"),
        ("Crest level", f"the highest, rounded up; camber {z['camber']:g} m for settlement", f"{z['crest']:.2f} m"),
    ])
    sec("6. Embankment", [
        ("Height and crest", f"{z['height']:g} m above the river bed, {z['foundation_height']:g} m above the lowest foundation; "
                             f"crest {z['crest_length']:g} m long", f"W = {z['crest_width']:g} m (USBR H/5 + 3)"),
        ("Slopes", "flattened in 0.25 steps until each stability case passes", f"1:{z['slope_us']:g} u/s, 1:{z['slope_ds']:g} d/s"),
        ("Core", f"top {dm.core_top:g} m at {z['core_top_level']:.2f} m (above the check flood), side slopes {dm.core_slope:g}:1; cut-off "
                 f"trench {dm.cutoff_width:g} m wide into firm ground", f"{z['volumes']['core']:,} m3"),
        ("Filters and drains", f"chimney filter {dm.filter_width:g} m; blanket to the toe drain, 0.3 m sand under 0.6 m gravel; "
                               "toe drain with a perforated pipe to the seepage weir; gradations by the no-erosion filter tests",
         f"{z['volumes']['chimney'] + z['volumes']['blanket'] + z['volumes']['blanket_sand']:,} m3"),
        ("Shells", "compacted granular / murram fill", f"{z['volumes']['shell']:,} m3"),
        ("Slope protection", f"Hudson: W50 = gr H^3 / (KD (gr/gw - 1)^3 cot a), KD 2.2, rock 26 kN/m3, H = hw: D50 "
                             f"{z['riprap']['d50']:g} m; two stones thick, at least 0.45 m, on 0.3 m bedding; grass downstream",
         f"{z['riprap']['thickness']:g} m, {z['volumes']['riprap']:,} m3"),
    ])
    sec("7. Seepage and stability", [
        ("Seepage", f"Dupuit through the core, k = {dm.core_k:g} m/s, no tailwater", f"{z['seepage_m3_day']:g} m3/day"),
        ("Materials", f"shell phi' {dm.shell_phi:g} deg, c' {dm.shell_c:g} kPa, {dm.shell_gamma:g} kN/m3; the section is "
                      "analysed as one shell material (the core's own strength in the zoned analysis)", "to be confirmed by tests"),
        ("Method", "simplified Bishop, circles through the face and up to 0.6 H beyond the toe; pore pressures by ru; "
                   f"earthquake by a pseudo-static kh = {dm.seismic_kh:g}; minima from USACE EM 1110-2-1902", ""),
    ] + [(s["case"], f"{s['face']} face at 1:{s['slope']:g}; ru = {s['ru']:g}", f"F = {s['F']:g} (min {s['need']:g}) "
                                                                                                       f"{'OK' if s['ok'] else 'FAIL'}")
         for s in z["stability"]])
    sec("8. Outlet works, instrumentation and safety", [
        ("Outlet", f"DN{z['outlet']['dn']} steel pipe in concrete at MOL: multi-level intake with screens, upstream guard gate, "
                   f"filter diaphragm downstream of the core, valve chamber; (demand + 10 % + {dm.compensation:g} m3/day "
                   "compensation) x 1.5 at 1 m head", f"{z['outlet']['q'] * 1000:.1f} l/s"),
        ("Emergency drawdown", f"orifice with entrance, valve, exit and friction losses (f 0.02) over {z['outlet']['length']:g} m",
         f"FSL-MOL {z['outlet']['drawdown_days']:g} days"),
        ("Instrumentation", "piezometers in the foundation, core and downstream shell at three sections; settlement pins on the "
                            "crest; V-notch seepage weir at the toe drain outfall; reservoir gauges", ""),
        ("Dam safety", "Water Act 2016 and the Water Resources Authority's dam safety rules: registration, design approval, "
                       "supervision by a registered dam engineer, emergency preparedness plan, periodic inspection",
         "large dam: full requirements" if z["large_dam"] else "small dam"),
    ])
    bom = calc.bom(d)
    if bom:
        tot = calc.boq_total(bom)
        data = [[Paragraph("Item", P8B), Paragraph("Quantity", P8B), Paragraph("Amount", P8B)]]
        data += [[Paragraph(markup(ln.description), P8), Paragraph(f"{ln.qty:,.0f} {ln.unit}", P8),
                  Paragraph(f"{ln.total:,.0f}" if ln.total is not None else "-", P8)] for ln in bom if ln.qty]
        prelim, cont = tot * 0.12, tot * 1.12 * 0.15
        vat = (tot + prelim + cont) * 0.16
        for name, amt, bold in (("Measured work", tot, True), ("Preliminaries and general, 12 %", prelim, False),
                                ("Contingency, 15 %", cont, False), ("VAT, 16 %", vat, False),
                                ("Estimated project cost", tot + prelim + cont + vat, True)):
            data.append([Paragraph(name, P8B if bold else P8), Paragraph("", P8), Paragraph(f"{d.info.currency} {amt:,.0f}", P8B)])
        story.append(KeepTogether([Paragraph("9. Quantities and cost", H2), _table(data, [w * 0.55, w * 0.2, w * 0.25])]))
    story.append(KeepTogether([Paragraph("10. Detailed design still to do", H2)] + [
        Paragraph(markup(t), P8) for t in (
            "Investigations: boreholes on the axis and the spillway, permeability (packer) tests, borrow area testing "
            "(grading, Atterberg limits, compaction, triaxial / shear box, dispersivity).",
            "Hydrology: the TRRL East African flood model or a unit hydrograph; flood routing through the reservoir; a monthly "
            "reservoir simulation through a 1 in 20 year drought with the reserve flow.",
            "Embankment: a zoned stability analysis on the tested strengths of each zone; filter gradations by the no-erosion "
            "tests; settlement and camber; foundation seepage, the cut-off and any grout curtain.",
            "Hydraulics: the spillway chute profile and basin by a hydraulic model or the USBR charts; the outlet's hydraulics "
            "and gates; riprap from the quarry's rock.",
            "Safety: hazard classification" + (", a dam-break and inundation study, the emergency preparedness plan"
                                               if dm.hazard != "low" else "") + ", the instrumentation plan and the first filling plan.")]))
    if z["notes"]:
        story += [Paragraph("Notes", H2)] + [Paragraph(markup(n), P8) for n in z["notes"]]
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()
