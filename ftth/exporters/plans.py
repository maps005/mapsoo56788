"""Construction drawings from the building model: a floor plan of each level and the four elevations, on A3 at a
standard scale, with dimensions and a title block."""
from __future__ import annotations

import io
import math

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas as rl_canvas

from .. import building as B
from ..model import Design
from .common import Stamp, clean

W, H = landscape(A3)
M = 28                       # page margin, pt
PT_PER_MM = 72 / 25.4
SCALES = [50, 100, 200, 250, 500, 1000]
GREY, DARK = colors.HexColor("#555555"), colors.HexColor("#1f2933")


def _frame(cv, d: Design, st: Stamp, title: str, page: int, total: int, scale: int | None):
    cv.setStrokeColor(colors.black)
    cv.setLineWidth(1)
    cv.rect(M, M, W - 2 * M, H - 2 * M)
    cv.line(M, M + 46, W - M, M + 46)
    cv.setFont("Helvetica-Bold", 12)
    cv.drawString(M + 8, M + 28, clean(f"{title} - {d.info.name}")[:110])
    cv.setFont("Helvetica", 8)
    cv.drawString(M + 8, M + 12, clean(f"{d.info.company or st.brand.name}   {d.info.area}   {st.line}")[:180])
    cv.drawRightString(W - M - 8, M + 28, f"Sheet {page} of {total}")
    cv.drawRightString(W - M - 8, M + 12, f"Scale 1:{scale} (A3)" if scale else "Not to scale")


def _scale(width_m: float, height_m: float, box_w: float, box_h: float) -> int:
    """The largest standard scale (smallest 1:N) at which the extent fits the box."""
    for n in SCALES:
        k = 1000 / n * PT_PER_MM  # points per metre
        if width_m * k <= box_w and height_m * k <= box_h:
            return n
    return SCALES[-1]


def _wall_quad(w: B.Wall, s0: float, s1: float):
    """Outline of the part of a wall between distances s0 and s1 from its start (plan, metres)."""
    L = B.length(w) or 1
    ux, uy = (w.b[0] - w.a[0]) / L, (w.b[1] - w.a[1]) / L
    nx, ny = -uy * w.thickness / 2, ux * w.thickness / 2
    p0 = (w.a[0] + ux * s0, w.a[1] + uy * s0)
    p1 = (w.a[0] + ux * s1, w.a[1] + uy * s1)
    return [(p0[0] + nx, p0[1] + ny), (p1[0] + nx, p1[1] + ny), (p1[0] - nx, p1[1] - ny), (p0[0] - nx, p0[1] - ny)]


def _poly(cv, pts, fill=False, stroke=True):
    p = cv.beginPath()
    for i, xy in enumerate(pts):
        (p.moveTo if i == 0 else p.lineTo)(*xy)
    p.close()
    cv.drawPath(p, stroke=1 if stroke else 0, fill=1 if fill else 0)


def _dim(cv, a, b, off, text):
    """Dimension line parallel to a-b, off points to its left, with ticks and centred text."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1
    nx, ny = -dy / L * off, dx / L * off
    A, Bp = (a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny)
    cv.setStrokeColor(GREY)
    cv.setLineWidth(0.4)
    cv.line(a[0], a[1], A[0] + nx * 0.2, A[1] + ny * 0.2)
    cv.line(b[0], b[1], Bp[0] + nx * 0.2, Bp[1] + ny * 0.2)
    cv.line(*A, *Bp)
    for x, y in (A, Bp):
        cv.line(x - 3, y - 3, x + 3, y + 3)
    cv.saveState()
    cv.translate((A[0] + Bp[0]) / 2 + nx / abs(off) * 3, (A[1] + Bp[1]) / 2 + ny / abs(off) * 3)
    ang = math.degrees(math.atan2(dy, dx))
    cv.rotate(ang + 180 if ang > 90 or ang <= -90 else ang)
    cv.setFillColor(DARK)
    cv.setFont("Helvetica", 7)
    cv.drawCentredString(0, 0, text)
    cv.restoreState()


def _plan(cv, b: B.Building, lv: int, T, k: float):
    """One floor: walls cut at their openings, doors with their swing, windows, stairs, columns, slab edge."""
    for s in b.slabs:
        if s.level == lv:
            cv.setStrokeColor(colors.HexColor("#999999"))
            cv.setLineWidth(0.4)
            cv.setDash(3, 2)
            _poly(cv, [T(*p) for p in s.outline])
            cv.setDash()
    for w in (w for w in b.walls if w.level == lv):
        L = B.length(w)
        ops = sorted((o for o in b.openings if o.wall == w.id), key=lambda o: o.offset)
        cuts, s = [], 0.0
        for o in ops:
            cuts.append((s, max(s, o.offset - o.width / 2)))
            s = min(L, o.offset + o.width / 2)
        cuts.append((s, L))
        cv.setFillColor(colors.HexColor("#b0b7c0") if w.kind == "external" else colors.HexColor("#d4d9df"))
        cv.setStrokeColor(colors.black)
        cv.setLineWidth(0.8 if w.kind == "external" else 0.5)
        for s0, s1 in cuts:
            if s1 - s0 > 1e-3:
                _poly(cv, [T(*p) for p in _wall_quad(w, s0, s1)], fill=True)
        ux, uy = ((w.b[0] - w.a[0]) / (L or 1), (w.b[1] - w.a[1]) / (L or 1))
        for o in ops:
            c0 = (w.a[0] + ux * (o.offset - o.width / 2), w.a[1] + uy * (o.offset - o.width / 2))
            c1 = (w.a[0] + ux * (o.offset + o.width / 2), w.a[1] + uy * (o.offset + o.width / 2))
            cv.setStrokeColor(DARK)
            cv.setLineWidth(0.5)
            if o.kind == "window":  # glass: two thin lines across the opening
                for f in (-0.15, 0.15):
                    nx, ny = -uy * w.thickness * f, ux * w.thickness * f
                    cv.line(*T(c0[0] + nx, c0[1] + ny), *T(c1[0] + nx, c1[1] + ny))
            else:  # door leaf open to the wall's left side, and its swing (double doors: a leaf from each jamb)
                leaves = [(c0, o.width / 2, 1), (c1, o.width / 2, -1)] if o.style == "double" else [(c0, o.width, 1)]
                for hinge, r, sgn in leaves:
                    hx, hy = T(*hinge)
                    closed = math.degrees(math.atan2(uy * sgn, ux * sgn))  # towards the other jamb
                    cv.line(hx, hy, *T(hinge[0] - uy * r, hinge[1] + ux * r))
                    cv.arc(hx - r * k, hy - r * k, hx + r * k, hy + r * k, startAng=closed, extent=90 * sgn)
    for st in (s for s in b.stairs if s.level == lv):
        n, rise, going = B.stair_steps(b, st)
        a = math.radians(st.angle)
        ux, uy, nx, ny = math.cos(a), math.sin(a), -math.sin(a) * st.width / 2, math.cos(a) * st.width / 2
        run = max(going, st.tread)
        corners = [(st.x + nx, st.y + ny), (st.x + ux * run + nx, st.y + uy * run + ny),
                   (st.x + ux * run - nx, st.y + uy * run - ny), (st.x - nx, st.y - ny)]
        cv.setStrokeColor(DARK)
        cv.setLineWidth(0.5)
        _poly(cv, [T(*p) for p in corners])
        for i in range(1, n - 1):
            t = i * st.tread
            cv.line(*T(st.x + ux * t + nx, st.y + uy * t + ny), *T(st.x + ux * t - nx, st.y + uy * t - ny))
        sx, sy = T(st.x + ux * 0.3, st.y + uy * 0.3)
        ex, ey = T(st.x + ux * run * 0.9, st.y + uy * run * 0.9)
        cv.line(sx, sy, ex, ey)
        cv.setFillColor(DARK)
        cv.setFont("Helvetica-Bold", 6)
        cv.drawString(sx + 3, sy + 3, f"UP {n}R")
    cv.setFillColor(colors.HexColor("#5d6874"))
    for c in (c for c in b.columns if c.level == lv):
        h = c.size / 2
        _poly(cv, [T(c.x - h, c.y - h), T(c.x + h, c.y - h), T(c.x + h, c.y + h), T(c.x - h, c.y + h)], fill=True)
    for r in (r for r in b.rooms if r.level == lv and r.name != "Stair"):  # names and floor areas (stairs show)
        x, y = T(r.x, r.y)
        name = r.name.upper() if r.name != "Corridor" else r.name
        size = max(5.0, min(8.0, 1.6 * k))
        room = (r.w * k - 4) if r.w else 1e9  # shrink, then wrap, a name to fit its room
        while size > 4 and cv.stringWidth(name, "Helvetica-Bold", size) > room:
            size -= 0.5
        lines = [name]
        if cv.stringWidth(name, "Helvetica-Bold", size) > room and " " in name:
            cut = name.rfind(" ", 0, len(name) // 2 + 3)
            lines = [name[:cut], name[cut + 1:]]
        cv.setFillColor(DARK)
        cv.setFont("Helvetica-Bold", size)
        for i, line in enumerate(lines):
            cv.drawCentredString(x, y + 1 + (len(lines) - 1 - i) * (size + 1), line)
        if r.area:
            cv.setFont("Helvetica", size - 1)
            cv.setFillColor(GREY)
            cv.drawCentredString(x, y - size, f"{r.area:g} m²")


LANDSCAPE_STYLE = {  # fill, label
    "flower_bed": ("#f3b6cc", "Flower beds"), "shrub_bed": ("#9cc58f", "Shrub beds"), "lawn": ("#cfe8b8", "Lawn"),
    "paving": ("#dcd8d0", "Paving"), "hedge": ("#2f6b2f", "Hedges"), "tree": ("#3f8f3f", "Trees"),
}


def _landscape_page(cv, d, st, b: B.Building, page: int, total: int):
    """The compound: the ground floor with the landscaping round it, a legend and the planting schedule."""
    pts = [p for w in b.walls if w.level == 0 for p in (w.a, w.b)] + [p for x in b.landscape for p in x.points]
    x0, x1 = min(p[0] for p in pts) - 4, max(p[0] for p in pts) + 4
    y0, y1 = min(p[1] for p in pts) - 4, max(p[1] for p in pts) + 4
    box_w, box_h = W - 2 * M - 220, H - 2 * M - 100
    n = _scale(x1 - x0, y1 - y0, box_w, box_h)
    k = 1000 / n * PT_PER_MM
    ox = M + 30 + (box_w - (x1 - x0) * k) / 2
    oy = M + 70 + (box_h - (y1 - y0) * k) / 2
    T = lambda x, y: (ox + (x - x0) * k, oy + (y - y0) * k)  # noqa: E731
    _frame(cv, d, st, "Landscaping and site layout", page, total, n)
    for x in b.landscape:  # under the building
        fill, _ = LANDSCAPE_STYLE[x.kind]
        cv.setStrokeColor(colors.HexColor("#4d5a3f"))
        cv.setFillColor(colors.HexColor(fill))
        cv.setLineWidth(0.5)
        if x.kind in B.LANDSCAPE_AREAS and len(x.points) >= 3:
            _poly(cv, [T(*q) for q in x.points], fill=True)
        elif x.kind == "hedge":
            cv.setStrokeColor(colors.HexColor(fill))
            cv.setLineWidth(max(2.0, 0.6 * k))
            for a, c in zip(x.points, x.points[1:]):
                cv.line(*T(*a), *T(*c))
        elif x.kind == "tree":
            cx, cy = T(*x.points[0])
            cv.circle(cx, cy, max(4.0, 1.5 * k), stroke=1, fill=1)
            cv.setFillColor(colors.HexColor("#6b4a2f"))
            cv.circle(cx, cy, 1.2, stroke=0, fill=1)
    _plan(cv, b, 0, T, k)
    # legend and schedule on the right
    q = {code: (qty, src) for code, qty, src in B.quantities(b)}
    rows = [(LANDSCAPE_STYLE[kind][0], LANDSCAPE_STYLE[kind][1], txt) for kind, txt in (
        ("flower_bed", f"{sum(B.area(x.points) for x in b.landscape if x.kind == 'flower_bed'):,.1f} m², {q.get('PLANTS-FLOWER', (0,))[0]:,.0f} plants"),
        ("shrub_bed", f"{sum(B.area(x.points) for x in b.landscape if x.kind == 'shrub_bed'):,.1f} m², {q.get('SHRUBS', (0,))[0]:,.0f} shrubs"),
        ("lawn", f"{q.get('GRASS', (0,))[0]:,.1f} m² of turf"),
        ("paving", f"{q.get('PAVING', (0,))[0]:,.1f} m²"),
        ("hedge", f"{q.get('HEDGE', (0,))[0]:,.0f} plants"),
        ("tree", f"{sum(x.kind == 'tree' for x in b.landscape)} trees")) if any(x.kind == kind for x in b.landscape)]
    lx, ly = W - M - 180, H - M - 60
    cv.setFillColor(DARK)
    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(lx, ly, "Landscaping")
    for fill, label, txt in rows:
        ly -= 26
        cv.setFillColor(colors.HexColor(fill))
        cv.setStrokeColor(colors.HexColor("#4d5a3f"))
        cv.rect(lx, ly - 2, 14, 10, stroke=1, fill=1)
        cv.setFillColor(DARK)
        cv.setFont("Helvetica-Bold", 8)
        cv.drawString(lx + 20, ly + 4, label)
        cv.setFont("Helvetica", 7.5)
        cv.drawString(lx + 20, ly - 6, txt)
    ly -= 30
    cv.setFont("Helvetica", 7)
    for line in ("Quantities are typical rates (topsoil 300 mm,", "6 flowers / m², 1.5 shrubs / m²,",
                 "3 hedge plants / m, 1 m³ tree pits).", "A landscape architect confirms species,",
                 "soil and irrigation."):
        cv.drawString(lx, ly, line)
        ly -= 10
    cv.setFont("Helvetica", 9)
    cv.drawRightString(W - M - 10, H - M - 18, "N ↑")


def _elevation(cv, b: B.Building, view: str, box, label: str):
    """A building elevation seen from the south / north / east / west, fitted in box = (x, y, w, h)."""
    right = {"south": (1, 0), "north": (-1, 0), "east": (0, 1), "west": (0, -1)}[view]
    toward = {"south": (0, -1), "north": (0, 1), "east": (1, 0), "west": (-1, 0)}[view]
    pts = [p for w in b.walls for p in (w.a, w.b)]
    for r in b.roofs:
        pts += [[r.x0 - r.overhang, r.y0 - r.overhang], [r.x1 + r.overhang, r.y1 + r.overhang]]
    if not pts:
        return None
    u = lambda p: p[0] * right[0] + p[1] * right[1]  # noqa: E731
    umin, umax = min(map(u, pts)), max(map(u, pts))
    top = max(lv.elevation + lv.height for lv in b.levels) + max((B.roof_geometry(r)["rise"] for r in b.roofs), default=0) + 0.5
    x, y, bw, bh = box
    n = _scale(umax - umin, top + 0.5, bw, bh - 18)
    k = 1000 / n * PT_PER_MM
    ox = x + (bw - (umax - umin) * k) / 2
    oy = y + 14 + 0.5 * k
    T = lambda uu, z: (ox + (uu - umin) * k, oy + z * k)  # noqa: E731
    # each block (the first design, then wings and towers added to it: ids "B2-...") is drawn on its own,
    # farthest first, so a nearer block hides what is behind it
    def block_of(i: str) -> str:
        return i.split("-")[0] if i.startswith("B") and "-" in i else ""
    blocks: dict[str, list] = {}
    for w in b.walls:
        blocks.setdefault(block_of(w.id), []).append(w)
    depth = lambda ws: sum(p[0] * toward[0] + p[1] * toward[1] for w in ws for p in (w.a, w.b)) / (2 * len(ws))  # noqa: E731
    cv.setStrokeColor(colors.black)
    for key, bws in sorted(blocks.items(), key=lambda kv: depth(kv[1])):
        cx = sum(p[0] for w in bws for p in (w.a, w.b)) / (2 * len(bws))
        cy = sum(p[1] for w in bws for p in (w.a, w.b)) / (2 * len(bws))
        roofs = [r for r in b.roofs if (f"B{r.id[1:]}" if r.id[1:].isdigit() and r.id != "R1" else "") == key]
        for lv_i, lv in enumerate(b.levels):  # wall silhouette of each level
            ws = [w for w in bws if w.level == lv_i and w.kind == "external"]
            if not ws:
                continue
            us = [u(p) for w in ws for p in (w.a, w.b)]
            h = max(b.wall_height(w) for w in ws)
            cv.setFillColor(colors.HexColor("#eef1f4"))
            cv.setLineWidth(0.8)
            _poly(cv, [T(min(us), lv.elevation), T(max(us), lv.elevation), T(max(us), lv.elevation + h), T(min(us), lv.elevation + h)], fill=True)
            for w in ws:  # openings of the walls facing the viewer
                L = B.length(w) or 1
                mx, my = (w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2
                nx, ny = -(w.b[1] - w.a[1]) / L, (w.b[0] - w.a[0]) / L
                if nx * (mx - cx) + ny * (my - cy) < 0:
                    nx, ny = -nx, -ny  # outward
                if nx * toward[0] + ny * toward[1] < 0.7:
                    continue
                for o in (o for o in b.openings if o.wall == w.id):
                    c = (w.a[0] + (w.b[0] - w.a[0]) / L * o.offset, w.a[1] + (w.b[1] - w.a[1]) / L * o.offset)
                    half = o.width / 2 * abs((w.b[0] - w.a[0]) / L * right[0] + (w.b[1] - w.a[1]) / L * right[1])
                    z0 = lv.elevation + o.sill
                    cv.setFillColor(colors.HexColor("#cfe3f3") if o.kind == "window" else colors.HexColor("#c8a27a"))
                    cv.setLineWidth(0.5)
                    _poly(cv, [T(u(c) - half, z0), T(u(c) + half, z0), T(u(c) + half, z0 + o.height), T(u(c) - half, z0 + o.height)], fill=True)
        for r in roofs:  # roof profile
            g = B.roof_geometry(r)
            lv = b.levels[min(r.level, len(b.levels) - 1)]
            ze = lv.elevation + lv.height
            corners = [[r.x0 - r.overhang, r.y0 - r.overhang], [r.x1 + r.overhang, r.y1 + r.overhang]]
            u0, u1 = sorted(u(p) for p in corners)
            along_view = (r.ridge == "x") == (right[1] == 0)  # the ridge runs across the drawing
            across = (r.y1 - r.y0 if r.ridge == "x" else r.x1 - r.x0) + 2 * r.overhang
            cv.setFillColor(colors.HexColor("#8a4b38") if r.covering == "tiles" else colors.HexColor("#6b7884"))
            cv.setLineWidth(0.8)
            if r.kind == "flat":  # slab edge, or the parapet wall round the roof
                _poly(cv, [T(u0, ze), T(u1, ze), T(u1, ze + max(0.3, r.parapet)), T(u0, ze + max(0.3, r.parapet))], fill=True)
            elif r.kind == "shed":
                if along_view:
                    _poly(cv, [T(u0, ze), T(u1, ze), T(u1, ze + g["rise"]), T(u0, ze + g["rise"])], fill=True)
                else:
                    _poly(cv, [T(u0, ze), T(u1, ze), T(u1, ze + g["rise"])], fill=True)
            elif along_view:
                inset = across / 2 if r.kind == "hip" else 0
                _poly(cv, [T(u0, ze), T(u1, ze), T(u1 - inset, ze + g["rise"]), T(u0 + inset, ze + g["rise"])], fill=True)
            else:
                _poly(cv, [T(u0, ze), T(u1, ze), T((u0 + u1) / 2, ze + g["rise"])], fill=True)
    cv.setStrokeColor(colors.black)
    cv.setLineWidth(1.2)
    cv.line(*T(umin - 1, 0), *T(umax + 1, 0))  # ground line
    cv.setFillColor(DARK)
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(x, y, f"{label}   1:{n}")
    return n


def build_plans_pdf(d: Design, st: Stamp) -> bytes:
    buf = io.BytesIO()
    cv = rl_canvas.Canvas(buf, pagesize=(W, H))
    b = d.building
    if b is None or not b.walls:
        _frame(cv, d, st, "Plans and elevations", 1, 1, None)
        cv.setFont("Helvetica", 12)
        cv.drawString(M + 20, H / 2, "No building has been designed yet (Building 3D: Auto design, or draw the walls).")
        cv.showPage()
        cv.save()
        return buf.getvalue()
    pts = [p for w in b.walls for p in (w.a, w.b)]
    x0, x1 = min(p[0] for p in pts) - 1.5, max(p[0] for p in pts) + 1.5
    y0, y1 = min(p[1] for p in pts) - 1.5, max(p[1] for p in pts) + 1.5
    box_w, box_h = W - 2 * M - 60, H - 2 * M - 100
    n = _scale(x1 - x0, y1 - y0, box_w, box_h)
    k = 1000 / n * PT_PER_MM
    ox = M + 30 + (box_w - (x1 - x0) * k) / 2
    oy = M + 70 + (box_h - (y1 - y0) * k) / 2
    T = lambda x, y: (ox + (x - x0) * k, oy + (y - y0) * k)  # noqa: E731
    total = len(b.levels) + 1 + (1 if b.landscape else 0)
    for lv_i, lv in enumerate(b.levels):
        _frame(cv, d, st, f"{lv.name} plan", lv_i + 1, total, n)
        _plan(cv, b, lv_i, T, k)
        ext = [w for w in b.walls if w.level == lv_i]
        if ext:  # overall dimensions along the bottom and the left
            ex0, ex1 = min(min(w.a[0], w.b[0]) - w.thickness / 2 for w in ext), max(max(w.a[0], w.b[0]) + w.thickness / 2 for w in ext)
            ey0, ey1 = min(min(w.a[1], w.b[1]) - w.thickness / 2 for w in ext), max(max(w.a[1], w.b[1]) + w.thickness / 2 for w in ext)
            _dim(cv, T(ex1, ey0), T(ex0, ey0), 22, f"{ex1 - ex0:.2f} m")
            _dim(cv, T(ex0, ey0), T(ex0, ey1), 22, f"{ey1 - ey0:.2f} m")
        area = sum(B.area(s.outline) for s in b.slabs if s.level == lv_i)
        cv.setFillColor(DARK)
        cv.setFont("Helvetica", 9)
        cv.drawString(M + 10, H - M - 18, f"Floor level {lv.elevation:+.2f} m   Height {lv.height:.2f} m   Floor area {area:,.1f} m²")
        cv.drawRightString(W - M - 10, H - M - 18, "N ↑")
        cv.showPage()
    if b.landscape:
        _landscape_page(cv, d, st, b, total - 1, total)
        cv.showPage()
    _frame(cv, d, st, "Elevations", total, total, None)
    gw, gh = (W - 2 * M - 30) / 2, (H - 2 * M - 70) / 2
    for i, (view, label) in enumerate((("south", "South (front) elevation"), ("north", "North elevation"),
                                       ("east", "East elevation"), ("west", "West elevation"))):
        bx = M + 10 + (i % 2) * (gw + 10)
        by = M + 56 + (1 - i // 2) * gh
        _elevation(cv, b, view, (bx, by, gw, gh - 10), label)
    cv.showPage()
    cv.save()
    return buf.getvalue()
