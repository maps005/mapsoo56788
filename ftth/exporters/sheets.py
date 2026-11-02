"""The sheets of a building-plan application beyond the floor plans and elevations: the site plan (plot, building
lines, parking, landscaping, planning figures), the foundation and roof plans, two sections and the schedules
(areas and planning compliance, flats, doors and windows, room checks)."""
from __future__ import annotations

import math
from collections import Counter

from reportlab.lib import colors

from .. import building as B, compliance
from ..model import Design
from . import render as R

C = colors.HexColor
INK, GREY, LIGHT = C("#1f2933"), C("#5d6874"), C("#9aa5b1")


def fit(extent, box, scale_fn, pt_per_mm):
    """A transform putting extent (x0, y0, x1, y1, metres) centred in box (x, y, w, h, points), at a standard scale."""
    x0, y0, x1, y1 = extent
    bx, by, bw, bh = box
    n = scale_fn(x1 - x0, y1 - y0, bw, bh)
    k = 1000 / n * pt_per_mm
    ox, oy = bx + (bw - (x1 - x0) * k) / 2, by + (bh - (y1 - y0) * k) / 2
    return (lambda x, y: (ox + (x - x0) * k, oy + (y - y0) * k)), k, n


def _poly(cv, pts, fill=False, stroke=True):
    p = cv.beginPath()
    for i, xy in enumerate(pts):
        (p.moveTo if i == 0 else p.lineTo)(*xy)
    p.close()
    cv.drawPath(p, stroke=1 if stroke else 0, fill=1 if fill else 0)


def _text(cv, x, y, s, size=7, bold=False, color=INK, align="left"):
    cv.setFillColor(color)
    cv.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    (cv.drawString if align == "left" else cv.drawCentredString if align == "centre" else cv.drawRightString)(x, y, s)


def north_arrow(cv, x, y, size=18):
    cv.saveState()
    cv.setFillColor(INK)
    cv.setStrokeColor(INK)
    _poly(cv, [(x, y + size), (x - size * 0.35, y - size * 0.5), (x, y - size * 0.2), (x + size * 0.35, y - size * 0.5)], fill=True)
    _text(cv, x, y + size + 3, "N", 9, True, align="centre")
    cv.restoreState()


def table(cv, x, y, cols, rows, widths, size=7, head_fill=C("#e9eef3"), row_h=11):
    """A ruled table, top-left at (x, y); returns the y below it."""
    cv.saveState()
    cv.setLineWidth(0.4)
    cv.setStrokeColor(LIGHT)
    tw = sum(widths)
    cv.setFillColor(head_fill)
    cv.rect(x, y - row_h, tw, row_h, stroke=1, fill=1)
    xx = x
    for c, w in zip(cols, widths):
        _text(cv, xx + 3, y - row_h + 3, str(c), size, True)
        xx += w
    yy = y - row_h
    for r in rows:
        bad = any(isinstance(v, str) and v.startswith("FAIL") for v in r)
        cv.setFillColor(C("#fdecea") if bad else colors.white)
        cv.rect(x, yy - row_h, tw, row_h, stroke=1, fill=1)
        xx = x
        for v, w in zip(r, widths):
            s = str(v)
            while cv.stringWidth(s, "Helvetica", size) > w - 5 and len(s) > 3:
                s = s[:-2] + "…"
            _text(cv, xx + 3, yy - row_h + 3, s, size, color=C("#b42318") if s.startswith("FAIL") else INK)
            xx += w
        yy -= row_h
    cv.restoreState()
    return yy - 8


# ---------------------------------------------------------------------------------------------------------
# site plan
# ---------------------------------------------------------------------------------------------------------
def site_plan(cv, d: Design, plan_fn, scale_fn, pt_per_mm, box, landscape_style):
    """The plot boundary, the building lines, the building (ground floor), parking with its bays, the
    landscaping, the clear distances to the boundary, a north point and the planning figures."""
    b, st = d.building, d.info.site
    plot = compliance.plot_local(d)
    pts = [p for w in b.walls if w.level == 0 for p in (w.a, w.b)] + [p for x in b.landscape for p in x.points] + plot
    ext = (min(p[0] for p in pts) - 4, min(p[1] for p in pts) - 6, max(p[0] for p in pts) + 4, max(p[1] for p in pts) + 4)
    bx, by, bw, bh = box
    T, k, n = fit(ext, (bx, by, bw - 230, bh), scale_fn, pt_per_mm)
    # the plot: a road strip along the front, the boundary, the building lines inside it
    if plot:
        px0, py0, px1, py1 = B._bbox(plot)
        cv.saveState()
        R._rect(cv, *T(px0 - 4, py0 - 6), *T(px1 + 4, py0 - 0.5), fill=C("#d9d6cf"))
        _text(cv, (T(px0, 0)[0] + T(px1, 0)[0]) / 2, T(0, py0 - 3.6)[1], "ACCESS ROAD", 7, True, GREY, "centre")
        cv.setStrokeColor(C("#c0392b"))
        cv.setLineWidth(1.4)
        cv.setDash([8, 3, 2, 3])
        _poly(cv, [T(*p) for p in plot])
        cv.setDash()
        if st.setback_front or st.setback_side or st.setback_rear:
            cv.setStrokeColor(C("#2e7d32"))
            cv.setLineWidth(0.6)
            cv.setDash(4, 3)
            _poly(cv, [T(px0 + st.setback_side, py0 + st.setback_front), T(px1 - st.setback_side, py0 + st.setback_front),
                       T(px1 - st.setback_side, py1 - st.setback_rear), T(px0 + st.setback_side, py1 - st.setback_rear)])
            cv.setDash()
            _text(cv, T(px0 + st.setback_side, 0)[0] + 3, T(0, py0 + st.setback_front)[1] + 3, "BUILDING LINE", 6, True, C("#2e7d32"))
        cv.restoreState()
    for x in b.landscape:  # landscaping and parking under the building outline
        fill, _ = landscape_style.get(x.kind, ("#dddddd", ""))
        cv.saveState()
        cv.setFillColor(C(fill))
        cv.setStrokeColor(C("#4d5a3f"))
        cv.setLineWidth(0.4)
        if x.kind in B.LANDSCAPE_AREAS and len(x.points) >= 3:
            _poly(cv, [T(*q) for q in x.points], fill=True)
            if x.kind == "parking":
                cv.setStrokeColor(colors.white)
                cv.setLineWidth(0.8)
                bays = B.parking_bays(x)
                total = sum(len(B.parking_bays(z)) for z in b.landscape)
                first = sum(len(B.parking_bays(z)) for z in b.landscape[:b.landscape.index(x)])
                acc_areas = any("accessible" in z.note.lower() for z in b.landscape if z.kind == "parking")
                n_acc, n_ev = (0 if acc_areas else max(1, math.ceil(total * 0.01))), max(1, math.ceil(total * 0.05))
                for i, bay in enumerate(bays):  # numbered; accessible bays (3.6 m) and the last ones with EV charging
                    no = first + i + 1
                    tag = "ACC" if ("accessible" in x.note.lower() or no <= n_acc) else "EV" if no > total - n_ev else str(no)
                    if tag in ("ACC", "EV"):
                        cv.saveState()
                        cv.setFillColor(C("#1565c0") if tag == "ACC" else C("#2e7d32"))
                        _poly(cv, [T(*q) for q in bay], fill=True)
                        cv.restoreState()
                    _poly(cv, [T(*q) for q in bay])
                    cx = sum(q[0] for q in bay) / 4
                    cy = sum(q[1] for q in bay) / 4
                    _text(cv, *T(cx, cy), tag, 5, True, colors.white, "centre")
        elif x.kind == "hedge":
            cv.setStrokeColor(C(fill))
            cv.setLineWidth(max(2.0, 0.6 * k))
            for a, c in zip(x.points, x.points[1:]):
                cv.line(*T(*a), *T(*c))
        elif x.kind == "tree":
            cx, cy = T(*x.points[0])
            cv.circle(cx, cy, max(3.5, 1.5 * k), stroke=1, fill=1)
        cv.restoreState()
    # the building: its ground floor outline, solid
    fp = B.footprint(b)
    cv.saveState()
    cv.setFillColor(C("#e9e4da"))
    cv.setStrokeColor(INK)
    cv.setLineWidth(1.2)
    for s in (s for s in b.slabs if s.level == 0):
        _poly(cv, [T(*q) for q in s.outline], fill=True)
    cv.restoreState()
    if fp:
        x0, y0, x1, y1 = B._bbox(fp)
        _text(cv, *T((x0 + x1) / 2, (y0 + y1) / 2), f"PROPOSED {len(b.levels)}-STOREY BUILDING", 8, True, align="centre")
        _text(cv, T((x0 + x1) / 2, 0)[0], T(0, (y0 + y1) / 2)[1] - 10, f"FFL ±0.00 = {st.ground_level:g} m above datum", 6.5, align="centre")
        f = compliance.figures(d)
        for side, (a, c) in {"front": ((x0 + x1) / 2, y0), "rear": ((x0 + x1) / 2, y1), "west": (x0, (y0 + y1) / 2),
                             "east": (x1, (y0 + y1) / 2)}.items():
            g = f["setbacks"].get(side)
            if g is None:
                continue
            dx, dy = {"front": (0, -g), "rear": (0, g), "west": (-g, 0), "east": (g, 0)}[side]
            cv.saveState()
            cv.setStrokeColor(C("#1565c0"))
            cv.setLineWidth(0.5)
            cv.line(*T(a, c), *T(a + dx, c + dy))
            _text(cv, *(lambda p: (p[0] + 3, p[1] + 2))(T(a + dx / 2, c + dy / 2)), f"{g:.2f} m", 6.5, True, C("#1565c0"))
            cv.restoreState()
    # what the paved areas are (from their notes), and the services in the ground
    for x in b.landscape:
        if x.kind == "paving" and x.note and len(x.points) >= 3:
            ax0, ay0, ax1, ay1 = B._bbox(x.points)
            name = x.note.split(",")[0].split("(")[0].strip()
            if (ax1 - ax0) * (ay1 - ay0) >= 6 and "aisle" not in name.lower():
                vertical = (ay1 - ay0) > (ax1 - ax0) * 2
                cx, cy = T((ax0 + ax1) / 2, (ay0 + ay1) / 2)
                cv.saveState()
                cv.translate(cx, cy)
                if vertical:
                    cv.rotate(90)
                room = abs(T(ax1, 0)[0] - T(ax0, 0)[0]) if not vertical else abs(T(0, ay1)[1] - T(0, ay0)[1])
                lines = [name.upper()[:34]]
                if cv.stringWidth(lines[0], "Helvetica-Bold", 5.5) > room - 4 and " " in lines[0]:
                    cut = lines[0].rfind(" ", 0, len(lines[0]) // 2 + 4)
                    lines = [lines[0][:cut], lines[0][cut + 1:]]
                for j, ln in enumerate(lines):
                    _text(cv, 0, 1 - j * 7 + (len(lines) - 1) * 3, ln, 5, True, C("#4d5a3f"), "centre")
                cv.restoreState()
    from .. import services
    L = services.layout(d)
    if L:
        w_ = L["water"]
        sx_, sy_ = L["soakaway"]
        cv.saveState()
        cv.setStrokeColor(C("#1565c0"))
        cv.setFillColor(C("#bbdefb"))
        cv.circle(*T(sx_, sy_), 1.25 * k, stroke=1, fill=1)
        tx_, ty_ = w_["tank"]
        R._rect(cv, *T(tx_ - 2.0, ty_ - 1.5), *T(tx_ + 2.0, ty_ + 1.5), fill=C("#b2dfdb"), stroke=C("#00897b"), width=0.8)
        cv.restoreState()
        _text(cv, *(lambda q: (q[0], q[1] - 3))(T(sx_, sy_)), "SOAKAWAY" + (" (trafficable)" if w_.get("soak_paved") else ""),
              5.5, True, C("#0d47a1"), "centre")
        _text(cv, *(lambda q: (q[0], q[1] - 3))(T(tx_, ty_)), f"U/G TANK {w_['underground']} m3" +
              (" (trafficable)" if w_.get("tank_paved") else ""), 5.5, True, C("#00695c"), "centre")
    if plot:
        _text(cv, T(px0 - 4, 0)[0] + 4, T(0, py0 - 5.4)[1], f"Ground falls about {st.slope:g} % to the road; FFL +0.15 above the "
              f"highest adjoining ground" if st.slope else "Ground levels to the survey", 5.5, color=GREY)
        drive_ = next((x for x in b.landscape if x.kind == "paving" and "drive" in x.note.lower() and len(x.points) >= 3), None)
        if drive_:
            gx0, _, gx1, _ = B._bbox(drive_.points)
            _text(cv, *T((gx0 + gx1) / 2, py0 - 1.6), "GATE", 6, True, INK, "centre")
    # the fire engine's route: from the road along the driveway to the front of the building
    drive = next((x for x in b.landscape if x.kind == "paving" and "drive" in x.note.lower() and len(x.points) >= 3), None)
    if drive and fp and plot:
        dx0, dy0, dx1, dy1 = B._bbox(drive.points)
        cx = (dx0 + dx1) / 2
        cv.saveState()
        cv.setStrokeColor(C("#c62828"))
        cv.setLineWidth(1.6)
        cv.setDash([6, 3])
        cv.line(*T(cx, B._bbox(plot)[1] - 3), *T(cx, dy1 - 1))
        cv.setDash()
        cv.restoreState()
        _text(cv, T(cx, 0)[0] + 4, T(0, dy0 + 2.5)[1], "FIRE ENGINE ACCESS", 6, True, C("#c62828"))
        _text(cv, T(cx, 0)[0] + 4, T(0, dy0 + 2.5)[1] - 8, f"{dx1 - dx0:g} m clear", 6, color=C("#c62828"))
    # the legend
    lx_, ly_ = bx + 6, by + 8 + 11 * 9
    _text(cv, lx_, ly_ + 4, "LEGEND", 7, True)
    items = [("Plot boundary", None, "#c0392b"), ("Building line", None, "#2e7d32"), ("Building (ground floor)", "#e9e4da", None)]
    seen = []
    for x in b.landscape:
        if x.kind not in seen:
            seen.append(x.kind)
    items += [(k.replace("_", " ").capitalize() + (" (bays numbered)" if k == "parking" else ""),
               landscape_style.get(k, ("#dddddd", ""))[0], None) for k in seen if k not in ("hedge", "tree")]
    items += [("ACC accessible bay 3.6 m", "#1565c0", None), ("EV charging bay", "#2e7d32", None),
              ("Fire engine access", None, "#c62828")]
    for i, (label, fill, line) in enumerate(items):
        yy = ly_ - 6 - i * 9
        if fill:
            R._rect(cv, lx_, yy - 1, lx_ + 14, yy + 6, fill=C(fill), stroke=INK, width=0.3)
        else:
            cv.saveState()
            cv.setStrokeColor(C(line))
            cv.setLineWidth(1.2)
            cv.setDash([4, 2])
            cv.line(lx_, yy + 2.5, lx_ + 14, yy + 2.5)
            cv.restoreState()
        _text(cv, lx_ + 18, yy, label, 6)
    north_arrow(cv, bx + bw - 250, by + bh - 30)
    # the planning figures
    f = compliance.figures(d)
    lx, ly = bx + bw - 220, by + bh - 6
    _text(cv, lx, ly, "PLANNING FIGURES", 9, True)
    ok = lambda got, lim, more=False: ("" if not lim or got is None else ("OK " if (got >= lim if more else got <= lim) else "FAIL "))  # noqa: E731
    rows = [["Plot", st.plot_ref or "-", ""], ["Zone", st.zone or "-", ""],
            ["Plot area", f"{f['plot_area']:,.0f} m²" if f["plot_area"] else "not drawn", ""],
            ["Ground coverage", f"{ok(f['coverage'], st.max_coverage)}{f['coverage']:g} %" if f["coverage"] is not None else "-",
             f"{st.max_coverage:g} %" if st.max_coverage else "-"],
            ["Gross floor area", f"{f['gfa']:,.0f} m²", ""],
            ["Plot ratio", f"{ok(f['plot_ratio'], st.max_plot_ratio)}{f['plot_ratio']:g} %" if f["plot_ratio"] is not None else "-",
             f"{st.max_plot_ratio:g} %" if st.max_plot_ratio else "-"],
            ["Floors / height", f"{ok(f['floors'], st.max_floors)}{f['floors']} / {f['height_roof']:g} m roof, {f['height']:g} m parapet", f"{st.max_floors}" if st.max_floors else "-"],
            ["Flats", str(f["flats"]), ""],
            ["Car parking", f"{ok(f['parking_provided'], f['parking_required'], True)}{f['parking_provided']}",
             f"{f['parking_required']}" if f["parking_required"] else "-"]]
    for side, need in (("front", st.setback_front), ("rear", st.setback_rear), ("west", st.setback_side), ("east", st.setback_side)):
        g = f["setbacks"].get(side)
        if g is not None:
            rows.append([f"Setback {side}", f"{ok(g, need, True)}{g:.2f} m", f"{need:g} m" if need else "-"])
    table(cv, lx, ly - 6, ["Item", "Provided", "Limit"], rows, [78, 80, 52])
    _text(cv, lx, by + 40 + 175, "Limits as entered for the plot; confirm with the county", 6, color=GREY)
    _text(cv, lx, by + 30 + 175, "planning department before submission.", 6, color=GREY)
    location_plan(cv, d, (lx, by + 30, 210, 150))
    return n


# ---------------------------------------------------------------------------------------------------------
# foundation and roof plans
# ---------------------------------------------------------------------------------------------------------
def foundation_plan(cv, b: B.Building, T, k, bearing: float = 0.0):
    """Strip footings under the ground-floor walls and pads under the columns, with the specification."""
    sp = b.spec
    cv.saveState()
    for w in (w for w in b.walls if w.level == 0):
        L = B.length(w) or 1
        ux, uy = (w.b[0] - w.a[0]) / L, (w.b[1] - w.a[1]) / L
        nx, ny = -uy * sp.footing_width / 2, ux * sp.footing_width / 2
        cv.setFillColor(C("#d7dde3"))
        cv.setStrokeColor(GREY)
        cv.setLineWidth(0.4)
        cv.setDash(3, 2)
        _poly(cv, [T(w.a[0] + nx, w.a[1] + ny), T(w.b[0] + nx, w.b[1] + ny), T(w.b[0] - nx, w.b[1] - ny), T(w.a[0] - nx, w.a[1] - ny)], fill=True)
        cv.setDash()
        nx, ny = -uy * w.thickness / 2, ux * w.thickness / 2
        cv.setFillColor(C("#7d858e") if w.kind == "internal" else C("#3b4148"))
        _poly(cv, [T(w.a[0] + nx, w.a[1] + ny), T(w.b[0] + nx, w.b[1] + ny), T(w.b[0] - nx, w.b[1] - ny), T(w.a[0] - nx, w.a[1] - ny)], fill=True, stroke=False)
    from .. import structure
    dz = structure.design(b, bearing) if len(b.levels) > 1 else None
    pads = {p["id"]: p["side"] for p in dz["foundation"].get("pads", [])} if dz else {}
    raft = bool(dz) and dz["foundation"]["type"] == "raft"
    if raft:  # the raft under the whole footprint
        cv.setFillColor(C("#e3e7ea"))
        cv.setStrokeColor(INK)
        _poly(cv, [T(*q) for q in B.footprint(b)], fill=True)
    for cf in (dz["foundation"].get("combined", []) if dz and not raft else []):  # combined footings
        hl, hb = (cf["B"] / 2, cf["L"] / 2) if cf["along"] == "y" else (cf["L"] / 2, cf["B"] / 2)
        cv.setFillColor(C("#c4ccd4"))
        cv.setStrokeColor(INK)
        cv.setLineWidth(0.5)
        _poly(cv, [T(cf["x"] - hl, cf["y"] - hb), T(cf["x"] + hl, cf["y"] - hb), T(cf["x"] + hl, cf["y"] + hb), T(cf["x"] - hl, cf["y"] + hb)], fill=True)
    combined_ids = {i for cf in (dz["foundation"].get("combined", []) if dz and not raft else []) for i in cf["ids"]}
    cores = dz["foundation"].get("cores", []) if dz else []
    for i, cr in enumerate(cores if not raft else []):  # a raft under each RC core
        x0, y0, x1, y1 = cr["rect"]
        cv.setFillColor(C("#b8c2cc"))
        cv.setStrokeColor(INK)
        cv.setLineWidth(0.7)
        _poly(cv, [T(x0, y0), T(x1, y0), T(x1, y1), T(x0, y1)], fill=True)
        _text(cv, *T((x0 + x1) / 2, (y0 + y1) / 2 + 1.2), f"CR{i + 1} core raft {cr['L']:g} x {cr['B']:g} x {cr['t'] * 1000:.0f}",
              6, True, align="centre")
    on_core = lambda c: any(cr["rect"][0] <= c.x <= cr["rect"][2] and cr["rect"][1] <= c.y <= cr["rect"][3] for cr in cores)  # noqa: E731
    pad = 1.2 if len(b.levels) <= 4 else 1.5 if len(b.levels) <= 8 else 1.8
    for c in (c for c in b.columns if c.level == 0 and not raft):
        pad = pads.get(c.id, pad)
        if c.id in combined_ids or (dz and on_core(c)):
            cv.setFillColor(INK)
            h = c.size / 2
            _poly(cv, [T(c.x - h, c.y - h), T(c.x + h, c.y - h), T(c.x + h, c.y + h), T(c.x - h, c.y + h)], fill=True, stroke=False)
            continue
        cv.setFillColor(C("#c4ccd4"))
        cv.setStrokeColor(INK)
        cv.setLineWidth(0.5)
        _poly(cv, [T(c.x - pad / 2, c.y - pad / 2), T(c.x + pad / 2, c.y - pad / 2), T(c.x + pad / 2, c.y + pad / 2), T(c.x - pad / 2, c.y + pad / 2)], fill=True)
        cv.setFillColor(INK)
        h = c.size / 2
        _poly(cv, [T(c.x - h, c.y - h), T(c.x + h, c.y - h), T(c.x + h, c.y + h), T(c.x - h, c.y + h)], fill=True, stroke=False)
    cv.restoreState()
    fc = dz["foundation_concrete"] if dz else "C20/25"
    Df = sp.founding_depth if dz else sp.excavation_depth
    return [(f"Wall footings {sp.footing_width * 1000:.0f} x {sp.footing_thickness * 1000:.0f} mm under the ground-floor walls, "
             f"{fc}" if dz else f"Strip footings {sp.footing_width * 1000:.0f} x {sp.footing_thickness * 1000:.0f} mm, {fc}") +
            f"; pads and rafts founded at -{Df:.2f} m on the bearing stratum ({dz['bearing'] if dz else 0:g} kN/m2)"
            if dz else f"Strip footings {sp.footing_width * 1000:.0f} x {sp.footing_thickness * 1000:.0f} mm, {fc}, "
                       f"founded at -{sp.excavation_depth:.2f} m on firm ground",
            (f"Core rafts CR1-CR{len(cores)} under the RC stair / lift cores, "
             f"{max(c['pressure'] for c in cores)} kN/m2 at the worst edge" if cores and not raft else ""),
            (f"Raft {dz['foundation']['thickness'] * 1000:.0f} mm under the whole building" if raft else
             f"Column pads {min(pads.values()):g}-{max(pads.values()):g} m square ({len(pads)} no.) and "
             f"{len(dz['foundation'].get('combined', []))} combined footings where pads would touch, to the structural schedule"
             if pads else f"Column pads {pad:g} x {pad:g} m under the frame ({sum(c.level == 0 for c in b.columns)} no.)") if b.columns else "",
            f"{sp.hardcore * 1000:.0f} mm compacted hardcore, damp-proof membrane, ground slab C25",
            "Foundations to the structural engineer's design and the geotechnical report"]


def roof_plan(cv, b: B.Building, T, k, roof_m3=None):
    """Each roof seen from above: flat roofs with parapets, falls to outlets; pitched roofs with ridge and hips."""
    notes = []
    cv.saveState()
    for r in b.roofs:
        o = r.overhang
        X0, Y0, X1, Y1 = r.x0 - o, r.y0 - o, r.x1 + o, r.y1 + o
        if r.kind == "flat":
            cv.setFillColor(C("#cfd3d6"))
            cv.setStrokeColor(INK)
            cv.setLineWidth(0.9)
            _poly(cv, [T(X0, Y0), T(X1, Y0), T(X1, Y1), T(X0, Y1)], fill=True)
            if r.parapet:
                t = 0.2
                _poly(cv, [T(X0 + t, Y0 + t), T(X1 - t, Y0 + t), T(X1 - t, Y1 - t), T(X0 + t, Y1 - t)])
            n = max(2, math.ceil((X1 - X0) / 20) * 2)  # outlets along the long sides, one per 20 m or so
            outs = [((X0 + 0.6) + (X1 - X0 - 1.2) * i / (n // 2 - 1 if n // 2 > 1 else 1), Y0 + 0.6) for i in range(n // 2)] + \
                   [((X0 + 0.6) + (X1 - X0 - 1.2) * i / (n // 2 - 1 if n // 2 > 1 else 1), Y1 - 0.6) for i in range(n // 2)]
            cx, cy = (X0 + X1) / 2, (Y0 + Y1) / 2
            for ox, oy in outs:
                cv.setFillColor(C("#1565c0"))
                cv.circle(*T(ox, oy), max(1.8, 0.15 * k), stroke=0, fill=1)
                cv.setStrokeColor(C("#1565c0"))
                cv.setLineWidth(0.4)
                sx, sy = T(cx + (ox - cx) * 0.35, cy + (oy - cy) * 0.35)
                ex, ey = T(ox, oy)
                cv.line(sx, sy, ex, ey)
                a = math.atan2(ey - sy, ex - sx)
                cv.line(ex, ey, ex - 5 * math.cos(a - 0.4), ey - 5 * math.sin(a - 0.4))
                cv.line(ex, ey, ex - 5 * math.cos(a + 0.4), ey - 5 * math.sin(a + 0.4))
            notes.append(f"{r.id}: flat concrete roof, waterproofing membrane on screed laid to falls 1:80, to "
                         f"{len(outs)} outlets and 100 mm downpipes to the stormwater drains"
                         + (f"; {r.parapet:g} m parapet with coping" if r.parapet else ""))
            notes.append("Roof access by a hatch and fixed ladder from each stair core; water storage tanks on the "
                         "roof over the cores, lift overrun and motor room over the lift (services engineer to detail)")
        else:
            cv.setFillColor(C("#b98a74") if r.covering == "tiles" else C("#aab4bd"))
            cv.setStrokeColor(INK)
            cv.setLineWidth(0.9)
            _poly(cv, [T(X0, Y0), T(X1, Y0), T(X1, Y1), T(X0, Y1)], fill=True)
            cv.setLineWidth(0.6)
            if r.kind == "dome":
                pass  # its rings and hips below, no ridge
            elif r.ridge == "x":
                h = (Y1 - Y0) / 2 if r.kind == "hip" else 0
                cv.line(*T(X0 + h, (Y0 + Y1) / 2), *T(X1 - h, (Y0 + Y1) / 2))
                if h:
                    for p, q in ((X0, Y0), (X0, Y1)):
                        cv.line(*T(p, q), *T(X0 + h, (Y0 + Y1) / 2))
                    for p, q in ((X1, Y0), (X1, Y1)):
                        cv.line(*T(p, q), *T(X1 - h, (Y0 + Y1) / 2))
            else:
                h = (X1 - X0) / 2 if r.kind == "hip" else 0
                cv.line(*T((X0 + X1) / 2, Y0 + h), *T((X0 + X1) / 2, Y1 - h))
            if r.kind == "dome":  # seen from above: its sections closing on the cap, and the mast
                rings_ = B.dome_rings(r)
                cv.setDash([2, 2])
                for x0_, x1_, y0_, y1_, _ in rings_[4:-1:4]:
                    _poly(cv, [T(x0_, y0_), T(x1_, y0_), T(x1_, y1_), T(x0_, y1_)])
                cv.setDash()
                x0_, x1_, y0_, y1_, _ = rings_[-1]
                cv.setFillColor(C("#cfd3d6"))
                _poly(cv, [T(x0_, y0_), T(x1_, y0_), T(x1_, y1_), T(x0_, y1_)], fill=True)
                for (p_, q_), (s_, t_) in zip(((X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)), ((x0_, y0_), (x1_, y0_), (x1_, y1_), (x0_, y1_))):
                    cv.line(*T(p_, q_), *T(s_, t_))
                if r.mast:
                    cv.setFillColor(INK)
                    cv.circle(*T((x0_ + x1_) / 2, (y0_ + y1_) / 2), 2.5, stroke=0, fill=1)
                notes.append(f"{r.id}: {r.profile} dome crown, {B.roof_geometry(r)['rise']:.1f} m rise to a "
                             f"{r.cap:g} m flat cap" + (f" and a {r.mast:g} m mast" if r.mast else "") +
                             ", steel trusses with aluminium fins and glazing between them")
            elif r.kind == "arch":  # the vault's springing and the bays of its fins, seen from above
                cv.setDash([2, 2])
                if r.ridge == "y":
                    for q in (X0 + (X1 - X0) * f for f in (0.25, 0.75)):
                        cv.line(*T(q, Y0), *T(q, Y1))
                else:
                    for q in (Y0 + (Y1 - Y0) * f for f in (0.25, 0.75)):
                        cv.line(*T(X0, q), *T(X1, q))
                cv.setDash()
                notes.append(f"{r.id}: pointed vault (arch) crown, {B.roof_geometry(r)['rise']:.1f} m rise, steel trusses "
                             f"with aluminium fins and glazing; ridge along {r.ridge}")
            else:
                notes.append(f"{r.id}: {r.kind} roof at {r.pitch:g}°, {r.covering}, gutters to downpipes at the corners")
    top = len(b.levels) - 1
    flats = len({r.unit for r in b.rooms if r.unit})
    tank_m3 = roof_m3 if roof_m3 is not None else math.ceil(max(4, flats * 4) * 0.15 / 2)  # the services' figure
    stairs_ = [r for r in b.rooms if r.level == top and r.name == "Stair" and r.rect]
    for r in [r for r in b.rooms if r.level == top and "lift" in r.name.lower() and r.rect]:
        x0, y0, x1, y1 = r.rect  # the lift shaft and its overrun / motor room, over the lift
        R._rect(cv, *T(x0 + 0.3, y1 - 2.8), *T(x0 + 2.8, y1 - 0.3), fill=C("#9aa1a8"), stroke=INK, width=0.8)
        _text(cv, *T(x0 + 1.55, y1 - 1.3), "LIFT", 5, True, align="centre")
        _text(cv, *T(x0 + 1.55, y1 - 1.9), "OVERRUN", 5, True, align="centre")
    for i, r in enumerate(stairs_):
        x0, y0, x1, y1 = r.rect  # tanks over the stair cores, and the roof hatch
        R._rect(cv, *T(x0 + 0.3, y0 + 0.4), *T(x1 - 0.3, y0 + 2.6), fill=C("#b2dfdb"), stroke=C("#00897b"), width=0.8)
        _text(cv, *T((x0 + x1) / 2, y0 + 1.4), f"TANK {tank_m3 / max(1, len(stairs_)):g} m3", 5.5, True, C("#00897b"), "centre")
        R._rect(cv, *T(x1 - 1.3, y1 - 1.3), *T(x1 - 0.4, y1 - 0.4), stroke=INK, width=0.8)
        _text(cv, *T(x1 - 0.85, y1 - 1.7), "AOV / HATCH", 5, True, C("#c62828"), "centre")  # smoke vent and access
    cv.restoreState()
    return notes


# ---------------------------------------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------------------------------------
def section(cv, b: B.Building, axis: str, box, label, scale_fn, pt_per_mm, bearing: float = 0.0):
    """A section through the middle of the building: axis "x" cuts along x (looking north), "y" along y (looking
    west). Ground and foundations, slabs, the walls cut, stairs in the cut, the roof, levels and heights."""
    fp = B.footprint(b)
    x0, y0, x1, y1 = B._bbox(fp)
    st0 = next((s for s in b.stairs if s.level == 0), None)  # A-A across the flats, B-B through a stair
    cut = section_line(b) if axis == "x" else (st0.x if st0 else (x0 + x1) / 2)
    lo, hi = (x0, x1) if axis == "x" else (y0, y1)
    sp = b.spec
    from .. import structure
    dz = structure.design(b, bearing) if len(b.levels) > 1 and b.columns else None
    raft = bool(dz) and dz["foundation"]["type"] == "raft"
    Df = sp.founding_depth if dz else sp.excavation_depth  # the founding level
    top = B.top_height(b) + 1
    T, k, n = fit((lo - 4, -Df - 1.5, hi + 4, top), box, scale_fn, pt_per_mm)
    # the ground and the earth below it
    R._rect(cv, *T(lo - 4, -Df - 1.2), *T(hi + 4, 0), fill=C("#e8dccb"))
    cv.saveState()
    cv.setStrokeColor(C("#b9a68c"))
    cv.setLineWidth(0.3)
    xx = T(lo - 4, 0)[0]
    while xx < T(hi + 4, 0)[0]:
        cv.line(xx, T(0, -Df - 1.2)[1], xx + 8, T(0, 0)[1])
        xx += 10
    cv.restoreState()
    if raft:  # the raft under the whole building, at the founding level
        tr = dz["foundation"]["thickness"]
        R._rect(cv, *T(lo, -Df), *T(hi, -Df + tr), fill=C("#9aa1a8"), stroke=INK, width=0.7)
        _text(cv, *(lambda p: (p[0] + 4, p[1] + 3))(T(lo, -Df)), f"RAFT {tr * 1000:.0f} mm, C25/30, founded at -{Df:.2f} m "
              f"({dz['bearing']:g} kN/m2 stratum)", 6, True)
    core_rafts = dz["foundation"].get("cores", []) if dz and not raft else []
    for cr in core_rafts:  # the core rafts the cut passes through
        rx0, ry0, rx1, ry1 = cr["rect"]
        if (ry0 <= cut <= ry1) if axis == "x" else (rx0 <= cut <= rx1):
            a0, a1 = (rx0, rx1) if axis == "x" else (ry0, ry1)
            R._rect(cv, *T(a0, -Df), *T(a1, -Df + cr["t"]), fill=C("#9aa1a8"), stroke=INK, width=0.7)
            _text(cv, *(lambda p: (p[0] + 3, p[1] + 3))(T(a0, -Df)), f"CORE RAFT {cr['t'] * 1000:.0f}", 5.5, True)
    on_raft = lambda q, c_: any((cr["rect"][0] <= c_.x <= cr["rect"][2] and cr["rect"][1] <= c_.y <= cr["rect"][3])  # noqa: E731
                                for cr in core_rafts)
    if dz and not raft:
        _text(cv, *(lambda p: (p[0] + 4, p[1] - 9))(T(lo, -Df)), f"Founding level -{Df:.2f} m ({dz['bearing']:g} kN/m2 stratum)", 6, True)
    found_top = (-Df + dz["foundation"]["thickness"]) if raft else -Df

    def crosses(w):  # walls the cut passes through, and where
        a, c = (w.a[1], w.b[1]) if axis == "x" else (w.a[0], w.b[0])
        if min(a, c) - 1e-6 <= cut <= max(a, c) + 1e-6 and abs(a - c) > 1e-6:
            t = (cut - a) / (c - a)
            return (w.a[0] + (w.b[0] - w.a[0]) * t) if axis == "x" else (w.a[1] + (w.b[1] - w.a[1]) * t)
        return None
    # the frame beyond the cut: the columns on the next grid line behind it, from the foundations up (seen, light)
    cols0 = [c for c in b.columns if c.level == 0]
    if cols0:
        behind = sorted({round(c.y if axis == "x" else c.x, 2) for c in cols0 if (c.y if axis == "x" else c.x) > cut})
        line = behind[0] if behind else None
        for c in b.columns:
            if line is None or abs((c.y if axis == "x" else c.x) - line) > 0.05:
                continue
            lvc = b.levels[min(c.level, len(b.levels) - 1)]
            p = c.x if axis == "x" else c.y
            R._rect(cv, *T(p - c.size / 2, lvc.elevation), *T(p + c.size / 2, lvc.elevation + lvc.height),
                    fill=C("#d5dade"), stroke=C("#9aa5b1"), width=0.3)
            if c.level == 0 and not raft and not on_raft(p, c):
                R._rect(cv, *T(p - 0.7, -Df), *T(p + 0.7, -Df + 0.6), fill=C("#d5dade"), stroke=C("#9aa5b1"), width=0.3)
            if c.level == 0:  # the column down to its foundation
                R._rect(cv, *T(p - c.size / 2, found_top if raft else -Df + 0.6), *T(p + c.size / 2, 0),
                        fill=C("#d5dade"), stroke=C("#9aa5b1"), width=0.3)
    for lv_i, lv in enumerate(b.levels):
        # the slab under the level, where the cut meets it
        for s in (s for s in b.slabs if s.level == lv_i):
            sx0, sy0, sx1, sy1 = B._bbox(s.outline)
            if (sy0 <= cut <= sy1) if axis == "x" else (sx0 <= cut <= sx1):
                a0, a1 = (sx0, sx1) if axis == "x" else (sy0, sy1)
                R._rect(cv, *T(a0, lv.elevation - s.thickness), *T(a1, lv.elevation), fill=C("#9aa1a8"), stroke=INK, width=0.5)
                if dz and lv_i > 0:  # the beams across the cut, under the slab, at each frame line
                    bm = dz["beam_y" if axis == "x" else "beam_x"]
                    for q in sorted({round(c.x if axis == "x" else c.y, 2) for c in b.columns if c.level == 0}):
                        R._rect(cv, *T(q - bm["b"] / 2, lv.elevation - bm["h"]), *T(q + bm["b"] / 2, lv.elevation - s.thickness),
                                fill=C("#9aa1a8"), stroke=INK, width=0.4)
        for w in (w for w in b.walls if w.level == lv_i):
            p = crosses(w)
            if p is None:
                continue
            h = b.wall_height(w) - lv.slab
            R._rect(cv, *T(p - w.thickness / 2, lv.elevation), *T(p + w.thickness / 2, lv.elevation + h),
                    fill=C("#6b5b4e") if w.material == "concrete" else C("#3b4148") if w.kind == "external" else C("#7d858e"))
            xy_ = (p, cut) if axis == "x" else (cut, p)
            on_core_raft = next((cr for cr in core_rafts if cr["rect"][0] <= xy_[0] <= cr["rect"][2]
                                 and cr["rect"][1] <= xy_[1] <= cr["rect"][3]), None)
            if lv_i == 0 and on_core_raft:  # down to its core raft
                R._rect(cv, *T(p - w.thickness / 2, -Df + on_core_raft["t"]), *T(p + w.thickness / 2, 0),
                        fill=C("#6b5b4e") if w.material == "concrete" else C("#5d646b"))
            elif lv_i == 0 and raft:  # down to the raft
                R._rect(cv, *T(p - w.thickness / 2, found_top), *T(p + w.thickness / 2, 0),
                        fill=C("#6b5b4e") if w.material == "concrete" else C("#5d646b"))
            elif lv_i == 0:  # its footing
                R._rect(cv, *T(p - sp.footing_width / 2, -sp.excavation_depth), *T(p + sp.footing_width / 2, -sp.excavation_depth + sp.footing_thickness),
                        fill=C("#9aa1a8"), stroke=INK, width=0.5)
                R._rect(cv, *T(p - w.thickness / 2, -sp.excavation_depth + sp.footing_thickness), *T(p + w.thickness / 2, 0), fill=C("#5d646b"))
        for s in (s for s in b.stairs if s.level == lv_i):  # flights in the cut, each from its first riser up
            nrise, rise, going = B.stair_steps(b, s)
            flights, landing = B.stair_flights(b, s)
            for fx, fy, fang, fn, first in flights:
                a = math.radians(fang)
                ux, uy = math.cos(a), math.sin(a)
                run = fn * s.tread
                if axis == "x":
                    if not (min(fy, fy + uy * run) - s.width <= cut <= max(fy, fy + uy * run) + s.width) and abs(uy) > 0.5:
                        continue
                    p0, p1 = fx - s.width / 2, fx + s.width / 2  # seen across the flight
                    if abs(ux) > 0.5:
                        p0, p1 = fx, fx + ux * run
                else:
                    if not (min(fx, fx + ux * run) - s.width <= cut <= max(fx, fx + ux * run) + s.width) and abs(ux) > 0.5:
                        continue
                    p0, p1 = (fy, fy + uy * run) if abs(uy) > 0.5 else (fy - s.width / 2, fy + s.width / 2)
                cv.saveState()
                cv.setStrokeColor(INK)
                cv.setFillColor(C("#c4ccd4"))
                cv.setLineWidth(0.6)
                pts = [T(p0, lv.elevation + rise * first)]
                for i in range(fn):
                    u = p0 + (p1 - p0) * i / fn
                    u2 = p0 + (p1 - p0) * (i + 1) / fn
                    z = lv.elevation + rise * (first + i + 1)
                    pts += [T(u, z), T(u2, z)]
                pts += [T(p1, lv.elevation + rise * first)]
                _poly(cv, pts, fill=True)
                cv.restoreState()
            if landing:
                lz = lv.elevation + rise * flights[0][3]
                xs, ys = [q[0] for q in landing], [q[1] for q in landing]
                a0, a1 = (min(xs), max(xs)) if axis == "x" else (min(ys), max(ys))
                R._rect(cv, *T(a0, lz - 0.15), *T(a1, lz), fill=C("#9aa1a8"), stroke=INK, width=0.4)
        # the level marker
        mx, my = T(lo - 2.2, lv.elevation)
        cv.saveState()
        cv.setFillColor(INK)
        _poly(cv, [(mx, my), (mx - 4, my + 6), (mx + 4, my + 6)], fill=True)
        cv.restoreState()
        _text(cv, mx - 8, my + 2, f"{lv.name.upper()}  FFL {lv.elevation:+.2f}", 6.5, True, align="right")
    for r in b.roofs:  # roof slab / parapet / pitched roof in the cut
        lv = b.levels[min(r.level, len(b.levels) - 1)]
        ze = lv.elevation + lv.height
        a0, a1 = (r.x0 - r.overhang, r.x1 + r.overhang) if axis == "x" else (r.y0 - r.overhang, r.y1 + r.overhang)
        c0, c1 = (r.y0, r.y1) if axis == "x" else (r.x0, r.x1)
        if not (c0 <= cut <= c1):
            continue
        if r.kind == "flat":
            R._rect(cv, *T(a0, ze - 0.15), *T(a1, ze), fill=C("#9aa1a8"), stroke=INK, width=0.5)
            if r.parapet:
                for e in (a0, a1 - 0.2):
                    R._rect(cv, *T(e, ze), *T(e + 0.2, ze + r.parapet), fill=C("#3b4148"))
                _text(cv, *(lambda p: (p[0] + 4, p[1] - 3))(T(a1, ze + r.parapet)), f"parapet {r.parapet:g} m", 6)
        else:
            g = B.roof_geometry(r)
            mid = (a0 + a1) / 2
            across = (r.ridge == "x") == (axis == "y")
            if r.kind in ("dome", "arch") and across or r.kind == "dome":  # the crown in the cut: its pointed
                # outline, glazed (the floors inside it show through)
                prof_ = B.dome_outline(r, (lambda p: p[0]) if axis == "x" else (lambda p: p[1])) if r.kind == "dome" \
                    else B.arch_profile(a0, a1, g["rise"], 16)
                pts = [T(cc, ze + zz) for cc, zz in prof_]
                cv.saveState()
                cv.setStrokeColor(INK)
                cv.setLineWidth(1.2)
                cv.setFillColor(C("#dbe6ee"))
                cv.setFillAlpha(0.35)
                _poly(cv, pts, fill=True)
                cv.restoreState()
                continue
            elif r.kind == "arch":  # the vault in the cut: its pointed profile, or its height along the ridge
                pts = [T(cc, ze + zz) for cc, zz in B.arch_profile(a0, a1, g["rise"], 16)] if across else \
                    [T(a0, ze), T(a0, ze + g["rise"]), T(a1, ze + g["rise"]), T(a1, ze)]
            else:
                pts = [T(a0, ze), T(mid, ze + g["rise"]), T(a1, ze)] if across else [T(a0, ze), T(a0, ze + g["rise"] * 0.15), T(a1, ze + g["rise"] * 0.15), T(a1, ze)]
            cv.saveState()
            cv.setStrokeColor(INK)
            cv.setLineWidth(1.0)
            cv.setFillColor(C("#c9b8a6"))
            _poly(cv, pts, fill=True)
            cv.restoreState()
    cv.saveState()  # ground line and overall height
    cv.setStrokeColor(INK)
    cv.setLineWidth(1.4)
    cv.line(*T(lo - 4, 0), *T(hi + 4, 0))
    cv.restoreState()
    ht = B.top_height(b)  # to the ridge, apex or parapet
    hx = T(hi + 2, 0)[0]
    cv.saveState()
    cv.setStrokeColor(GREY)
    cv.setLineWidth(0.4)
    cv.line(hx, T(0, 0)[1], hx, T(0, ht)[1])
    for z in (0, ht):
        cv.line(hx - 3, T(0, z)[1], hx + 3, T(0, z)[1])
    cv.restoreState()
    _text(cv, hx + 4, (T(0, 0)[1] + T(0, ht)[1]) / 2, f"{ht:.2f} m overall", 7, True)
    bx, by, bw, bh = box
    _text(cv, bx, by - 12, f"{label}   1:{n}", 9, True)
    return n


def section_line(b: B.Building) -> float:
    """Where section A-A cuts across y: a quarter into the tallest part (the top storey's slabs; a tower over a
    podium or annex), else the footprint."""
    lv_top = max((s.level for s in b.slabs if s.level < len(b.levels)), default=0)  # the highest storey with a floor
    top = [s for s in b.slabs if s.level == lv_top] or [s for s in b.slabs if s.level == 0]
    pts = [q for s in top for q in s.outline] or B.footprint(b)
    _, y0, _, y1 = B._bbox(pts)
    return y0 + (y1 - y0) * 0.27


def cut_marks(cv, b: B.Building, T):
    """Where sections A-A and B-B are cut, marked on the ground floor plan."""
    fp = B.footprint(b)
    x0, y0, x1, y1 = B._bbox(fp)
    cv.saveState()
    cv.setStrokeColor(C("#c0392b"))
    cv.setLineWidth(0.7)
    cv.setDash([10, 3, 2, 3])
    st0 = next((s for s in b.stairs if s.level == 0), None)
    ym, xm = section_line(b), (st0.x if st0 else (x0 + x1) / 2)
    cv.line(*T(x0 - 2, ym), *T(x1 + 2, ym))
    cv.line(*T(xm, y0 - 2), *T(xm, y1 + 2))
    cv.setDash()
    for (px, py), s in ((T(x0 - 3, ym), "A"), (T(x1 + 3, ym), "A"), (T(xm, y0 - 3), "B"), (T(xm, y1 + 3), "B")):
        cv.setFillColor(C("#c0392b"))
        cv.circle(px, py, 6, stroke=0, fill=1)
        _text(cv, px, py - 2.5, s, 7, True, colors.white, "centre")
    cv.restoreState()


# ---------------------------------------------------------------------------------------------------------
# schedules
# ---------------------------------------------------------------------------------------------------------
def schedules(cv, d: Design, box):
    """Areas and planning compliance, the flats, the floor areas, the doors and windows, and the room checks."""
    b, st = d.building, d.info.site
    bx, by, bw, bh = box
    f = compliance.figures(d)
    issues = compliance.check(d)
    col = (bw - 30) / 3
    # column 1: planning and the flats
    x, y = bx, by + bh
    _text(cv, x, y, "AREA SCHEDULE AND PLANNING COMPLIANCE", 9, True)
    lim = lambda v, unit="": f"{v:g}{unit}" if v else "-"  # noqa: E731
    mark = lambda bad: "FAIL " if bad else "OK "  # noqa: E731
    rows = [["Plot area", f"{f['plot_area']:,.0f} m²" if f["plot_area"] else "-", ""],
            ["Footprint", f"{f['footprint']:,.1f} m²", ""],
            ["Ground coverage", (mark(st.max_coverage and f["coverage"] > st.max_coverage) + f"{f['coverage']:g} %") if f["coverage"] is not None else "-", lim(st.max_coverage, " %")],
            ["Gross floor area", f"{f['gfa']:,.1f} m²", ""],
            ["Plot ratio", (mark(st.max_plot_ratio and f["plot_ratio"] > st.max_plot_ratio) + f"{f['plot_ratio']:g} %") if f["plot_ratio"] is not None else "-", lim(st.max_plot_ratio, " %")],
            ["Floors", mark(st.max_floors and f["floors"] > st.max_floors) + str(f["floors"]), lim(st.max_floors)],
            ["Height to roof / parapet", f"{f['height_roof']:g} m / {f['height']:g} m", "30 m sprinklers"],
            ["Car parking", mark(f["parking_provided"] < f["parking_required"]) + str(f["parking_provided"]), str(f["parking_required"] or "-")],
            ["  accessible / EV bays", f"{max(1, math.ceil(f['parking_provided'] * 0.01)) if f['parking_provided'] else 0} / "
                                       f"{max(1, math.ceil(f['parking_provided'] * 0.05)) if f['parking_provided'] else 0}", "1 % / 5 %"],
            ["Escape stairs / lifts", f"{f['stairs']} / {f['lifts']}", "2 over 4 floors"]]
    y = table(cv, x, y - 6, ["Item", "Design", "Limit"], rows, [col * 0.42, col * 0.33, col * 0.25])
    _text(cv, x, y, "FLATS", 9, True)
    rows = [[t, v["count"], f"{v['average']:g} m²", f"{v['smallest']:g} m²"] for t, v in f["flat_types"].items()] or [["-", 0, "-", "-"]]
    rows.append(["Total", f["flats"], "", ""])
    y = table(cv, x, y - 6, ["Type", "No.", "Average", "Smallest"], rows, [col * 0.34, col * 0.16, col * 0.25, col * 0.25])
    _text(cv, x, y, "FLOOR AREAS", 9, True)
    rows = []
    for i, lv in enumerate(b.levels):
        units = len({r.unit for r in b.rooms if r.level == i and r.unit})
        rows.append([lv.name, f"{lv.elevation:+.2f}", f"{sum(B.area(s.outline) for s in b.slabs if s.level == i):,.1f} m²", units])
    table(cv, x, y - 6, ["Level", "FFL", "Gross area", "Flats"], rows[:24], [col * 0.36, col * 0.18, col * 0.28, col * 0.18], row_h=10)
    # column 2: doors and windows
    x, y = bx + col + 15, by + bh
    _text(cv, x, y, "DOOR AND WINDOW SCHEDULE", 9, True)
    kinds = Counter((o.kind, o.style, round(o.width, 2), round(o.height, 2), round(o.sill, 2)) for o in b.openings)
    rows, n = [], {"door": 0, "window": 0}
    for (kind, style, w, h, sill), cnt in sorted(kinds.items(), key=lambda t: (t[0][0], -t[0][2])):
        n[kind] += 1
        rows.append([f"{'D' if kind == 'door' else 'W'}{n[kind]:02d}", f"{style} {kind}", f"{w * 1000:.0f} x {h * 1000:.0f}",
                     f"{sill:g}" if kind == "window" else "-", cnt])
    y = table(cv, x, y - 6, ["Mark", "Type", "W x H (mm)", "Sill (m)", "No."], rows[:34],
              [col * 0.14, col * 0.36, col * 0.24, col * 0.12, col * 0.14], row_h=10)
    _text(cv, x, y, "Doors: hardwood frames, ironmongery to schedule; windows: aluminium, glazed, openable 1/20 of floor.", 6, color=GREY)
    # column 3: the code checks
    x, y = bx + 2 * (col + 15), by + bh
    _text(cv, x, y, "BUILDING CODE CHECKS", 9, True)
    by_code = Counter(i["code"] for i in issues)
    hab = [r for r in b.rooms if r.name in compliance.HABITABLE]
    checks = [["Habitable rooms ≥ 7 m², side ≥ 2.13 m", "by-law 159", f"{len(hab) - by_code['code_room_small'] - by_code['code_room_narrow']}/{len(hab)}"],
              ["One room per flat ≥ 13.9 m²", "by-law 159", f"{f['flats'] - by_code['code_main_room']}/{f['flats']}"],
              ["Kitchens ≥ 5.6 m²", "by-law 156", "FAIL " + str(by_code["code_kitchen"]) if by_code["code_kitchen"] else "OK all"],
              ["Glazing ≥ 1/10 of floor", "by-law 151", f"{len(hab) - by_code['code_light']}/{len(hab)}"],
              ["Clear height ≥ 2.4 m", "Code 2024", "FAIL" if by_code["code_height"] else "OK all levels"],
              ["Clear under beams ≥ 2.25 m", "Code 2024", "FAIL" if by_code.get("code_beam_headroom") else "OK all levels"],
              ["Two escape stairs over 4 floors", "Code 2024", "FAIL" if by_code["code_escape"] else "OK"],
              ["Lift over 4 floors", "Code 2024", "FAIL" if by_code["code_lift"] else "OK"],
              ["Firefighting lift over 6 floors", "para 364", "FAIL" if by_code["code_firefighting_lift"] else "OK" if f["firefighting_lift"] else "n/a"],
              ["Each stair exits directly outside", "means of escape", f"{f['stair_exits']}/{f['stairs']}"],
              ["Sprinklers over 30 m", "para 413", "FAIL needed" if by_code["code_sprinklers"] else "not required"],
              ["Geotechnical report over 4 floors", "para 85", "FAIL missing" if by_code["code_geotech"] else
               (f"OK {st.geotech_report}" if st.geotech_report else "n/a")]]
    y = table(cv, x, y - 6, ["Check", "Rule", "Result"], checks, [col * 0.55, col * 0.2, col * 0.25])
    _text(cv, x, y, "SIGNED", 9, True)
    y -= 14
    for role, name, reg in (("Architect", st.architect, st.architect_reg), ("Structural engineer", st.engineer, st.engineer_reg),
                            ("Developer", d.info.client, "")):
        _text(cv, x, y, f"{role}: {name or '________________'}" + (f"  ({reg})" if reg else ""), 7.5)
        cv.setStrokeColor(GREY)
        cv.line(x, y - 14, x + col * 0.6, y - 14)
        _text(cv, x, y - 21, "Signature and stamp                 Date", 6, color=GREY)
        y -= 34


# ---------------------------------------------------------------------------------------------------------
# structure (preliminary)
# ---------------------------------------------------------------------------------------------------------
def structural_sheet(cv, d: Design, scale_fn, pt_per_mm, box):
    """The frame of a typical floor (columns at their designed size, beams on the frame lines, marked), and the
    column, beam, slab and foundation schedules with the design basis."""
    from .. import structure
    b = d.building
    dz = structure.design(b, d.info.site.bearing_capacity)
    bx, by, bw, bh = box
    fp = B.footprint(b)
    x0_, y0_, x1_, y1_ = B._bbox(fp)
    T, k, n_ = fit((x0_ - 2, y0_ - 2, x1_ + 2, y1_ + 2), (bx, by, bw - 340, bh), scale_fn, pt_per_mm)
    if not dz:
        _text(cv, bx, by + bh - 20, "No frame in the model (no columns): load-bearing walls on strip footings.", 9)
        return
    types = structure.column_types(dz)
    mark = {cid: t["type"] for t in types for cid in t["ids"]}
    cols = dz["columns"]
    cv.saveState()
    cv.setStrokeColor(C("#1565c0"))
    for c in cols:  # beams to the next column along x and along y
        for axis in ("x", "y"):
            same = [o for o in cols if o is not c and abs((o["y"] if axis == "x" else o["x"]) - (c["y"] if axis == "x" else c["x"])) < 0.3
                    and (o["x"] if axis == "x" else o["y"]) > (c["x"] if axis == "x" else c["y"])]
            if not same:
                continue
            nxt = min(same, key=lambda o: (o["x"] if axis == "x" else o["y"]))
            bm = dz["beam_x" if axis == "x" else "beam_y"]
            cv.setLineWidth(max(1.0, bm["b"] * k))
            cv.line(*T(c["x"], c["y"]), *T(nxt["x"], nxt["y"]))
    cv.restoreState()
    for w in (w for w in b.walls if w.level == 1 % len(b.levels) and w.material == "concrete"):  # the RC core walls
        L = B.length(w) or 1
        ux, uy = (w.b[0] - w.a[0]) / L, (w.b[1] - w.a[1]) / L
        nx, ny = -uy * w.thickness / 2, ux * w.thickness / 2
        cv.setFillColor(C("#7a8794"))
        _poly(cv, [T(w.a[0] + nx, w.a[1] + ny), T(w.b[0] + nx, w.b[1] + ny), T(w.b[0] - nx, w.b[1] - ny), T(w.a[0] - nx, w.a[1] - ny)],
              fill=True, stroke=False)
    for i, cr in enumerate(dz["lateral"]["rafts"]):
        _text(cv, *T(cr["x"], cr["y"]), f"CORE {i + 1}", 6, True, C("#37474f"), "centre")
    for c in cols:
        s = c["sizes"][1] if len(c["sizes"]) > 1 else c["sizes"][0]
        R._rect(cv, *T(c["x"] - s / 2, c["y"] - s / 2), *T(c["x"] + s / 2, c["y"] + s / 2), fill=INK)
        _text(cv, T(c["x"], 0)[0] + 4, T(0, c["y"])[1] + 4, mark[c["id"]], 5.5, True, C("#c0392b"))
    x, y = bx + bw - 300, by + bh - 36
    _text(cv, x, y, "COLUMN SCHEDULE", 9, True)
    lv_names = ["G" if i == 0 else str(i) for i in range(len(b.levels))]  # G, 1, 2 ...
    rows = []
    for t in types:
        sizes = t["sizes"]
        runs, start = [], 0
        for i in range(1, len(sizes) + 1):  # levels with the same size, as ranges
            if i == len(sizes) or sizes[i] != sizes[start]:
                runs.append(f"{lv_names[start]}-{lv_names[i - 1]}: {sizes[start] * 1000:.0f}" if i - 1 > start
                            else f"{lv_names[start]}: {sizes[start] * 1000:.0f}")
                start = i
        rows.append([t["type"], t["count"], "; ".join(runs) + " sq"])
    y = table(cv, x, y - 6, ["Type", "No.", "Square size by floor, G = ground (mm)"], rows, [34, 30, 236], size=6.5, row_h=10)
    _text(cv, x, y, "BEAMS AND SLABS", 9, True)
    y = table(cv, x, y - 6, ["Mark", "Span", "b x h (mm)"],
              [["B1 (x)", f"{dz['beam_x']['span']:g} m", f"{dz['beam_x']['b'] * 1000:.0f} x {dz['beam_x']['h'] * 1000:.0f}"],
               ["B2 (y)", f"{dz['beam_y']['span']:g} m", f"{dz['beam_y']['b'] * 1000:.0f} x {dz['beam_y']['h'] * 1000:.0f}"],
               ["Slab", f"{min(dz['spans']):g} x {max(dz['spans']):g} m panels", f"{dz['slab'] * 1000:.0f} thick, {'two-way' if dz['two_way'] else 'one-way'}"]],
              [70, 100, 130], size=6.5, row_h=10)
    _text(cv, x, y, "FOUNDATIONS", 9, True)
    f = dz["foundation"]
    if f["type"] == "raft":
        rows = [["Raft", f"{f['thickness'] * 1000:.0f} mm", f"{f['pressure']} kN/m2 on {dz['bearing']:g}"
                 + (" - PILES NEEDED" if f["piles"] else "")]]
    else:
        groups = {}
        for p in f["pads"]:
            groups[(p["side"], p["depth"])] = groups.get((p["side"], p["depth"]), 0) + 1
        rows = [[f"P{i + 1}", n, f"{s:g} x {s:g} x {dd:g} m"] for i, ((s, dd), n) in enumerate(sorted(groups.items(), reverse=True))]
        cgroups = {}
        for c in f.get("combined", []):
            cgroups[(c["L"], c["B"], c["depth"])] = cgroups.get((c["L"], c["B"], c["depth"]), 0) + 1
        rows += [[f"CF{i + 1}", n, f"{L:g} x {Bw:g} x {dd:g} m combined (2 columns)"]
                 for i, ((L, Bw, dd), n) in enumerate(sorted(cgroups.items(), reverse=True))]
        rows += [[f"CR{i + 1}", 1, f"{c['L']:g} x {c['B']:g} x {c['t']:g} m core raft, {c['pressure']} kN/m2 max"]
                 for i, c in enumerate(f.get("cores", []))]
        worst_p = max([p["pressure"] for p in f["pads"]] + [c["pressure"] for c in f.get("combined", [])] + [0])
        rows.append(["Bearing", "", f"{worst_p} kN/m2 gross at -{f['depth']:g} m (allowed {dz['bearing']:g})"])
    y = table(cv, x, y - 6, ["Type", "No.", "Size"], rows, [50, 40, 210], size=6.5, row_h=10)
    _text(cv, x, y, "DESIGN BASIS", 9, True)
    y -= 12
    for line in (f"Concrete {dz['concrete']}, reinforcement {dz['steel']}; Eurocode 2 load factors 1.35G + 1.5Q",
                 f"Imposed {dz['imposed']:g} kN/m2 (roof 1.5); finishes 1.5, partitions {structure.PARTITIONS:g} kN/m2",
                 f"Design floor load {dz['w_floor']:g} kN/m2, roof {dz['w_roof']:g} kN/m2",
                 f"Heaviest column {dz['worst_N']:,} kN at the ground floor (ultimate)",
                 f"Safe bearing {dz['bearing']:g} kN/m2" + (" ASSUMED - confirm by geotechnical report" if dz["bearing_assumed"] else " (site investigation)"),
                 "Columns: load takedown with beam, facade and own weight; 2 % steel, bending x1.1 / 1.25 / 1.5",
                 f"Slabs span/30 two-way; beams span/12, shallower where needed for {structure.HEADROOM:g} m clear "
                 f"(min {dz['headroom']:g} m)",
                 f"Pads on the net bearing at -{f['depth']:g} m; cores on rafts sized for overturning",
                 "Preliminary sizes for costing and coordination: the registered",
                 "structural engineer's design, drawings and calculations govern."):
        _text(cv, x, y, line, 6.5, color=INK if not line.startswith("Prelim") else C("#b42318"))
        y -= 10
    return n_


# ---------------------------------------------------------------------------------------------------------
# services: drainage and water, fire safety
# ---------------------------------------------------------------------------------------------------------
def _arrow(cv, a, c, color, width=0.8, dash=None):
    cv.saveState()
    cv.setStrokeColor(color)
    cv.setLineWidth(width)
    if dash:
        cv.setDash(dash)
    cv.line(*a, *c)
    cv.setDash()
    ang = math.atan2(c[1] - a[1], c[0] - a[0])
    mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
    cv.line(mx, my, mx - 5 * math.cos(ang - 0.45), my - 5 * math.sin(ang - 0.45))
    cv.line(mx, my, mx - 5 * math.cos(ang + 0.45), my - 5 * math.sin(ang + 0.45))
    cv.restoreState()


def drainage_sheet(cv, d: Design, scale_fn, pt_per_mm, box):
    """Foul drainage from the stacks through inspection chambers to the public sewer; stormwater from the roof
    outlets to a soakaway; the water main, storage and pumps."""
    from .. import services
    b = d.building
    L = services.layout(d)
    plot = compliance.plot_local(d)
    fp = B.footprint(b)
    pts = list(fp) + list(plot) + [list(p) for p in L["chambers"]] + [list(L["soakaway"])]
    ext = (min(p[0] for p in pts) - 4, min(p[1] for p in pts) - 6, max(p[0] for p in pts) + 4, max(p[1] for p in pts) + 4)
    bx, by, bw, bh = box
    T, k, n = fit(ext, (bx, by, bw - 250, bh), scale_fn, pt_per_mm)
    brown, blue, water = C("#8d5524"), C("#1565c0"), C("#00897b")
    if plot:
        cv.saveState()
        cv.setStrokeColor(C("#c0392b"))
        cv.setLineWidth(1.0)
        cv.setDash([8, 3, 2, 3])
        _poly(cv, [T(*p) for p in plot])
        cv.restoreState()
        px0, py0, px1, py1 = B._bbox(plot)
        R._rect(cv, *T(px0 - 4, py0 - 6), *T(px1 + 4, py0 - 0.5), fill=C("#d9d6cf"))
        _text(cv, (T(px0, 0)[0] + T(px1, 0)[0]) / 2, T(0, py0 - 3.6)[1], "ACCESS ROAD - public sewer and water main", 7, True, GREY, "centre")
    cv.saveState()
    cv.setFillColor(C("#ece8df"))
    cv.setStrokeColor(INK)
    cv.setLineWidth(1.0)
    _poly(cv, [T(*q) for q in fp], fill=True)
    cv.restoreState()
    for a, c, kind in L["storm"]:
        _arrow(cv, T(*a), T(*c), blue, 0.8, [4, 2])
    for a, c, kind in L["sewer"]:
        _arrow(cv, T(*a), T(*c), brown, 1.2)
    for i, (x, y) in enumerate(L["chambers"]):
        R._rect(cv, *T(x - 0.4, y - 0.3), *T(x + 0.4, y + 0.3), fill=colors.white, stroke=brown, width=0.8)
        _text(cv, T(x, 0)[0] + 5, T(0, y)[1] + 3, f"IC{i + 1}", 5.5, True, brown)
    for x, y in L["stacks"]:
        cv.saveState()
        cv.setFillColor(brown)
        cv.circle(*T(x, y), max(1.6, 0.12 * k), stroke=0, fill=1)
        cv.restoreState()
    for x, y in L["outlets"]:
        cv.saveState()
        cv.setFillColor(blue)
        cv.circle(*T(x, y), max(1.8, 0.12 * k), stroke=0, fill=1)
        cv.restoreState()
    sx, sy = L["soakaway"]
    cv.saveState()
    cv.setStrokeColor(blue)
    cv.setLineWidth(0.8)
    cv.circle(*T(sx, sy), 1.5 * k, stroke=1, fill=0)
    cv.restoreState()
    _text(cv, *T(sx, sy - 0.2), "SOAKAWAY", 5.5, True, blue, "centre")
    cx, cy = L["connection"]
    _text(cv, T(cx, 0)[0] + 4, T(0, cy)[1] - 10, "TO PUBLIC SEWER", 6, True, brown)
    w = L["water"]
    for a, c in zip(w["main"], w["main"][1:]):
        _arrow(cv, T(*a), T(*c), water, 1.0, [2, 2])
    mx, my = w["meter"]
    R._rect(cv, *T(mx - 0.4, my - 0.3), *T(mx + 0.4, my + 0.3), fill=water)
    _text(cv, T(mx, 0)[0] + 5, T(0, my)[1] + 2, "WATER METER", 5.5, True, water)
    tx, ty = w["tank"]
    R._rect(cv, *T(tx - 1.6, ty - 1.4), *T(tx + 1.6, ty + 1.4), fill=C("#b2dfdb"), stroke=water, width=0.8)
    _text(cv, *T(tx, ty), f"U/G TANK {w['underground']} m3", 5.5, True, water, "centre")
    north_arrow(cv, bx + bw - 270, by + bh - 30)
    lx, y = bx + bw - 240, by + bh - 6
    _text(cv, lx, y, "DRAINAGE AND WATER", 9, True)
    rows = [["Foul drains", f"{L['sewer_m']:g} m", "110 mm uPVC 1:40, 150 mm 1:60"],
            ["Inspection chambers", str(len(L["chambers"])), "600 x 450, at bends and junctions"],
            ["Soil stacks", str(len(L["stacks"])), "100 mm, vented above the roof"],
            ["Stormwater", f"{L['storm_m']:g} m", f"from {len(L['outlets'])} roof outlets, {L['roof_area']} m2"],
            ["Soakaway", "1", "sized by percolation test"],
            ["Water demand", f"{w['demand']:g} m3/day", f"{w['people']} people x 150 l"],
            ["Storage", f"{w['underground'] + w['roof']} m3", f"{w['underground']} underground (incl. {w['fire_reserve']:g} fire) + {w['roof']} roof"],
            ["Booster pumps", "duty / standby", "to the roof tanks"],
            ["Electrical load", f"{L['power']['kva']} kVA", f"{L['power']['flats']} flats x 5 + {L['power']['lifts']} lifts + common"],
            ["Supply", f"{L['power']['meters']} meters", L["power"]["supply"][:40]]]
    table(cv, lx, y - 6, ["Item", "Qty", "Specification"], rows, [70, 50, 110], size=6.3, row_h=10)
    yy = by + 70
    for line in ("Foul and stormwater kept separate; no stormwater to the sewer.",
                 "Connection to the public sewer by Nairobi Water approval.",
                 "Services engineer to size and detail all runs."):
        _text(cv, lx, yy, line, 6.3, color=GREY)
        yy -= 9
    return n


def fire_sheet(cv, d: Design, plan_fn, T, k, box):
    """A typical floor with the means of escape: escape routes from every flat door to the protected stairs, fire
    doors, hose reels, extinguishers, alarm call points; travel distances and the fire-safety provisions."""
    from .. import services
    b = d.building
    lv = 1 if len(b.levels) > 1 else 0
    L = services.layout(d)
    F = L["fire"]
    plan_fn(cv, b, lv, T, k)
    red, green = C("#c62828"), C("#2e7d32")
    halls = [r.door for r in b.rooms if r.level == lv and r.name.startswith("Hall") and r.door]
    ymid = sum(p[1] for p in halls) / len(halls) if halls else None
    for hx, hy in halls:  # escape routes: out of the flat, along the corridor, to the nearest stair
        if not F["stair_doors"] or ymid is None:
            break
        sx, sy = min(F["stair_doors"], key=lambda s: abs(s[0] - hx))
        for a, c in (((hx, hy), (hx, ymid)), ((hx, ymid), (sx, ymid)), ((sx, ymid), (sx, sy))):
            if math.hypot(c[0] - a[0], c[1] - a[1]) > 0.2:
                _arrow(cv, T(*a), T(*c), green, 1.0)
    fx0, _, fx1, _ = B._bbox(B.footprint(b))
    for sx, sy in F["stair_doors"]:
        inward = 1 if sx < (fx0 + fx1) / 2 else -1  # towards the middle of the building, past the lobby door
        yy = ymid if ymid is not None else sy
        hx_, ex_ = sx + 2.4 * inward, sx + 3.2 * inward
        cv.saveState()
        cv.setFillColor(red)
        cv.circle(*T(hx_, yy), max(3, 0.25 * k), stroke=0, fill=1)  # hose reel
        R._rect(cv, *T(ex_ - 0.2, yy - 0.2), *T(ex_ + 0.2, yy + 0.2), fill=red)  # extinguishers
        cv.restoreState()
        _text(cv, *(lambda p: (p[0], p[1] - 10))(T(hx_, yy)), "HR", 5.5, True, red, "centre")
        _text(cv, *(lambda p: (p[0], p[1] - 10))(T(ex_, yy)), "FE", 5.5, True, red, "centre")
        if F["dry_riser"]:  # the dry riser's landing valve in the stair, by the door
            R._rect(cv, *T(sx - 0.25, sy - 1.0), *T(sx + 0.25, sy - 0.5), fill=C("#ef6c00"))
            _text(cv, T(sx + 0.4, 0)[0], T(0, sy - 0.9)[1], "DR", 5.5, True, C("#ef6c00"))
    if F.get("lobby_vents") and ymid is not None:  # the lobby smoke vents: the corridor-end windows, automatic
        for ex in (fx0, fx1):
            _text(cv, *(lambda q: (q[0] + (6 if ex == fx0 else -6), q[1] + 6))(T(ex, ymid)), "AOV", 5.5, True, red,
                  "left" if ex == fx0 else "right")
    bx, by, bw, bh = box
    lx, y = bx + 6, by + bh - 6
    _text(cv, lx, y, "FIRE SAFETY - TYPICAL FLOOR", 9, True)
    ok = F["travel"] <= F["limit"]
    rows = [["Escape stairs", f"{L['stairs']} protected, FD60 self-closing doors"],
            ["Travel to a stair", f"{'OK' if ok else 'FAIL'} {F['travel']:g} m (limit {F['limit']:g} m)"],
            ["Final exits", "each stair direct to outside at ground"],
            ["Hose reels", f"{F['hose_reels']} (one at each stair, every floor)"],
            ["Extinguishers", f"{F['extinguishers']} (two at each stair, every floor)"],
            ["Alarm", f"{F['call_points']} call points, {F['detectors']} smoke detectors"],
            ["Emergency lighting", f"{F['emergency_lights']} fittings, 1 hour"],
            ["Firefighting lift", "yes" if any("firefighting" in r.name.lower() for r in b.rooms) else "not required"],
            ["Dry riser", f"100 mm in each stair, landing valve every floor (top floor {F['top_floor']:g} m)" if F["dry_riser"]
             else f"not required (top floor {F['top_floor']:g} m, 18 m or less)"],
            ["Brigade inlet", f"{F['inlets']} inlet box(es) at the risers' base, on the access road" if F["inlets"] else "-"],
            ["Fire water", f"{F['reserve']:g} m3 reserve in the underground tank" if F["reserve"] else "-"],
            ["Smoke control", f"{F['smoke_vents']} AOVs (1 m2) at the stair heads; {F['lobby_vents']} lobby AOV windows (one per stair a floor)"
             if F["smoke_vents"] else "-"],
            ["Fire engine access", "road, gate and driveway to the building (site plan)"],
            ["Assembly point", "front lawn, by the gate"]]
    table(cv, lx, y - 6, ["Provision", "Design"], rows, [80, 200], size=6.3, row_h=10)
    _text(cv, lx, by + 40, "Green: escape routes. HR hose reel, FE extinguishers, DR dry riser outlet, FD fire doors (rating marked). "
                           "For NCCG Fire Department review.", 6.3, color=GREY)


# ---------------------------------------------------------------------------------------------------------
# location plan, column grid, elevation levels
# ---------------------------------------------------------------------------------------------------------
def location_plan(cv, d: Design, box):
    """The plot on the street map (OpenStreetMap), about 600 m across, with its coordinates; without a map
    (offline) the coordinates alone."""
    bx, by, bw, bh = box
    _text(cv, bx, by + bh + 4, "LOCATION PLAN (not to scale)", 8, True)
    cv.saveState()
    cv.setStrokeColor(LIGHT)
    cv.rect(bx, by, bw, bh, stroke=1, fill=0)
    cv.restoreState()
    if len(d.info.boundary) < 3:
        _text(cv, bx + 6, by + bh / 2, "Draw the plot boundary on the site plan", 7, color=GREY)
        return
    lats, lons = [p[0] for p in d.info.boundary], [p[1] for p in d.info.boundary]
    clat, clon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    dlat = 300 / 111195.08
    dlon = dlat * bw / bh / math.cos(math.radians(clat))
    s, w, n, e = clat - dlat, clon - dlon, clat + dlat, clon + dlon
    img = None
    try:
        from . import basemap
        img = basemap.image("streets", s, w, n, e, int(bw * 3))
    except Exception:  # noqa: BLE001 - offline: coordinates only
        img = None
    if img is not None:
        from io import BytesIO
        from reportlab.lib.utils import ImageReader
        buf = BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        cv.drawImage(ImageReader(buf), bx, by, bw, bh)
        _text(cv, bx + 2, by + 2, "© OpenStreetMap contributors", 5, color=GREY)
    X = lambda lo: bx + (lo - w) / (e - w) * bw  # noqa: E731
    Y = lambda la: by + (la - s) / (n - s) * bh  # noqa: E731
    cv.saveState()
    cv.setStrokeColor(C("#c0392b"))
    cv.setFillColor(C("#c0392b"))
    cv.setFillAlpha(0.35)
    cv.setLineWidth(1.5)
    _poly(cv, [(X(p[1]), Y(p[0])) for p in d.info.boundary], fill=True)
    cv.restoreState()
    _text(cv, X(clon) + 8, Y(clat) + 8, "SITE", 8, True, C("#c0392b"))
    _text(cv, bx, by - 10, f"{abs(clat):.5f}° {'S' if clat < 0 else 'N'}, {clon:.5f}° E   {d.info.area}", 6.5, color=INK)


def column_grid(cv, b: B.Building, T, k):
    """The structural grid: lines through the columns, numbered along x and lettered along y, with the
    distances between them (the dimensioned setting-out of the plans)."""
    cols = [c for c in b.columns if c.level == 0]
    if not cols:
        return
    def lines(vals):
        out = []
        for v in sorted(vals):
            if not out or v - out[-1] > 0.15:
                out.append(v)
        return out
    xs, ys = lines([c.x for c in cols]), lines([c.y for c in cols])
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]
    cv.saveState()
    cv.setStrokeColor(C("#b0b8c0"))
    cv.setLineWidth(0.3)
    cv.setDash([6, 2, 1, 2])
    for x in xs:
        cv.line(*T(x, y0 - 2.5), *T(x, y1 + 2.5))
    for y in ys:
        cv.line(*T(x0 - 2.5, y), *T(x1 + 2.5, y))
    cv.setDash()
    cv.restoreState()
    for i, x in enumerate(xs):
        px, py = T(x, y1 + 3.3)
        cv.saveState()
        cv.setStrokeColor(GREY)
        cv.setFillColor(colors.white)
        cv.circle(px, py, 6, stroke=1, fill=1)
        cv.restoreState()
        _text(cv, px, py - 2.5, str(i + 1), 6, True, align="centre")
        if i:
            a, c = T(xs[i - 1], y1 + 2.0), T(x, y1 + 2.0)
            cv.setStrokeColor(GREY)
            cv.setLineWidth(0.3)
            cv.line(*a, *c)
            _text(cv, (a[0] + c[0]) / 2, a[1] + 2, f"{(x - xs[i - 1]) * 1000:.0f}", 5, align="centre", color=GREY)
    for j, y in enumerate(ys):
        px, py = T(x1 + 3.3, y)
        cv.saveState()
        cv.setStrokeColor(GREY)
        cv.setFillColor(colors.white)
        cv.circle(px, py, 6, stroke=1, fill=1)
        cv.restoreState()
        _text(cv, px, py - 2.5, "ABCDEFGHJKLMNPQRSTUVWXYZ"[j % 24], 6, True, align="centre")
        if j:
            a, c = T(x1 + 2.0, ys[j - 1]), T(x1 + 2.0, y)
            cv.setStrokeColor(GREY)
            cv.setLineWidth(0.3)
            cv.line(*a, *c)
            cv.saveState()
            cv.translate(a[0] + 3, (a[1] + c[1]) / 2)
            cv.rotate(90)
            _text(cv, 0, 0, f"{(y - ys[j - 1]) * 1000:.0f}", 5, align="centre", color=GREY)
            cv.restoreState()


def details_sheet(cv, d: Design, box):
    """Typical structural details (preliminary): slab, beams, column, foundation and stair sections, with the
    scheme reinforcement, and the lateral system."""
    from .. import structure
    b = d.building
    dz = structure.design(b, d.info.site.bearing_capacity)
    if not dz:
        return
    bx, by, bw, bh = box
    k = 85.0  # points per metre (about 1:33): sections that read
    rb = dz["rebar"]

    def section(x, y, w, h, title, lines, bars=(), links=True):
        R._rect(cv, x, y, x + w * k, y + h * k, fill=C("#e5e8eb"), stroke=INK, width=0.8)
        if links:
            cv.saveState()
            cv.setStrokeColor(C("#c62828"))
            cv.setLineWidth(0.6)
            cv.rect(x + 0.04 * k, y + 0.04 * k, (w - 0.08) * k, (h - 0.08) * k, stroke=1, fill=0)
            cv.restoreState()
        cv.saveState()
        cv.setFillColor(C("#c62828"))
        for bx_, by_ in bars:
            cv.circle(x + bx_ * k, y + by_ * k, 2.2, stroke=0, fill=1)
        cv.restoreState()
        _text(cv, x, y + h * k + 10, title, 8, True)
        yy = y - 10
        for line in lines:
            _text(cv, x, yy, line, 6.5)
            yy -= 9
    # slab
    sw, sh = 1.6, dz["slab"]
    section(bx + 10, by + bh - 70, sw, sh, f"SLAB {sh * 1000:.0f} mm ({'two-way' if dz['two_way'] else 'one-way'})",
            [rb["slab"], "20 mm cover, C30/37"], bars=[(0.1 + 0.2 * i, 0.04) for i in range(8)] + [(0.1 + 0.2 * i, sh - 0.04) for i in range(8)], links=False)
    # beams
    for i, key in enumerate(("beam_x", "beam_y")):
        bm = dz[key]
        bars = [(0.05, 0.05), (bm["b"] - 0.05, 0.05), (bm["b"] / 2, 0.05), (0.05, bm["h"] - 0.05), (bm["b"] - 0.05, bm["h"] - 0.05)]
        section(bx + 200 + i * 170, by + bh - 70 - bm["h"] * k, bm["b"], bm["h"],
                f"BEAM B{i + 1} {bm['b'] * 1000:.0f} x {bm['h'] * 1000:.0f}", rb[key].split(", ", 1) + [f"span {bm['span']:g} m"], bars=bars)
    # column
    cs = max(max(c["sizes"]) for c in dz["columns"])
    section(bx + 540, by + bh - 70 - cs * k, cs, cs, f"COLUMN {cs * 1000:.0f} SQ (ground floor)", rb["column"].split(", "),
            bars=[(0.05, 0.05), (cs - 0.05, 0.05), (0.05, cs - 0.05), (cs - 0.05, cs - 0.05), (cs / 2, 0.05), (cs / 2, cs - 0.05),
                  (0.05, cs / 2), (cs - 0.05, cs / 2)])
    # foundation
    f = dz["foundation"]
    if f["type"] == "pads":
        side = max([p["side"] for p in f["pads"]] + [c["B"] for c in f.get("combined", [])])
        dep = max([p["depth"] for p in f["pads"]] + [c["depth"] for c in f.get("combined", [])])
        section(bx + 10, by + bh - 260, side, dep, f"PAD / COMBINED FOOTING up to {side:g} m wide, {dep * 1000:.0f} deep",
                [rb["foundation"], f"{dz['foundation_concrete']} on 50 mm blinding; founded on {dz['bearing']:g} kN/m2 ground",
                 f"{len(f.get('combined', []))} combined footings where pads would touch"]
                + ([f"Core rafts: {rb['core_raft']}"] if rb.get("core_raft") else []),
                bars=[(0.1 + i * 0.25, 0.08) for i in range(int((side - 0.2) / 0.25) + 1)], links=False)
    else:
        section(bx + 10, by + bh - 260, 3.0, f["thickness"], f"RAFT {f['thickness'] * 1000:.0f} mm", [rb["foundation"]], links=False)
    # stair
    st = next((s for s in b.stairs if s.level == 0), None)
    if st:
        n, rise, going = B.stair_steps(b, st)
        fl = B.stair_flights(b, st)[0]
        x0, y0 = bx + 540, by + bh - 330
        pts = [(x0, y0)]
        steps = fl[0][3]
        for i in range(steps):
            pts += [(x0 + i * st.tread * k * 0.6, y0 + (i + 1) * rise * k * 0.6), (x0 + (i + 1) * st.tread * k * 0.6, y0 + (i + 1) * rise * k * 0.6)]
        cv.saveState()
        cv.setStrokeColor(INK)
        cv.setLineWidth(0.8)
        for a2, c2 in zip(pts, pts[1:]):
            cv.line(*a2, *c2)
        cv.line(x0 + 0.15 * k * 0.6, y0 - 0.15 * k * 0.6, pts[-1][0], pts[-1][1] - 0.15 * k * 0.6)
        cv.restoreState()
        _text(cv, x0, y0 + steps * rise * k * 0.6 + 14, "STAIR FLIGHT (dog-leg)", 8, True)
        for j, line in enumerate((f"{n} risers of {rise * 1000:.0f} mm, goings {st.tread * 1000:.0f} mm, {steps} per flight",
                                  f"2R + G = {2 * rise * 1000 + st.tread * 1000:.0f} mm (550-700); width {st.width * 1000:.0f} mm",
                                  "150 mm waist, T12@150 main, T10@250 distribution, C30/37",
                                  "Half landing 150 mm; handrails both sides, 900 mm high")):
            _text(cv, x0, y0 - 18 - j * 9, line, 6.5)
    # lateral system
    lat = dz["lateral"]
    x, y = bx + bw - 330, by + bh
    _text(cv, x, y, "LATERAL SYSTEM - RC CORES", 9, True)
    rows = [["Cores (stairs and lifts)", str(lat["cores"]), ""],
            ["Building weight (G + 0.3Q)", f"{lat['weight']:,} kN", ""],
            ["Earthquake base shear", f"{lat['seismic']:,} kN", f"{lat['coeff']:g} W (ag 0.1 g, EN 1998)"],
            ["Wind along x / y", f"{lat['wind_x']:,} / {lat['wind_y']:,} kN", f"{lat['wind_kpa']:g} kN/m2 peak"],
            ["Solid core walls along x", f"{lat['walls_x']:g} m x {lat['t_x'] * 1000:.0f} mm", f"{(lat['use_x'] or 0):.0%} used ({lat['governs_x']})"],
            ["Solid core walls along y", f"{lat['walls_y']:g} m x {lat['t_y'] * 1000:.0f} mm", f"{(lat['use_y'] or 0):.0%} used ({lat['governs_y']})"],
            ["Overturning per core x / y", f"{lat['M_x']:,} / {lat['M_y']:,} kNm", "flanges in compression and tension"],
            ["Horizontal bars x / y", f"{lat['h_bars_x']} / {lat['h_bars_y']}", "shear, EC2 6.2.3"],
            ["Vertical bars x / y", f"{lat['v_bars_x']} / {lat['v_bars_y']}", f"flange stress {lat.get('stress_x', 0):g} MPa"]]
    y = table(cv, x, y - 6, ["Item", "Value", "Basis"], rows, [120, 90, 120], size=6.5, row_h=10)
    for line in ("Cores and spine walls 300 mm RC, continuous from the foundations to the roof, C30/37,",
                 "bars as tabled (EF = each face). Accidental torsion included (EN 1998-1 4.3.3.2.4);",
                 "the frame carries gravity loads. Second-order effects to be checked by the engineer.",
                 "Preliminary sizes for costing and coordination: the registered structural",
                 "engineer's design, drawings and calculations govern."):
        _text(cv, x, y, line, 6.5, color=C("#b42318") if "Preliminary" in line or "engineer's" in line else INK)
        y -= 9
