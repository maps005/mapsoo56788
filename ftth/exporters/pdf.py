"""PDF deliverables: HLD/LLD map sheets, schedules, splicing diagram and survey report."""
from __future__ import annotations

import io
import math
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, HRFlowable, Image, KeepTogether,
                                ListFlowable, ListItem, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

from .. import calc, sectors, splicing
from ..geo import LocalProjection, haversine, valid_coord
from ..model import Design
from . import report
from .common import KIND_COLOURS, NODE_LABEL, Stamp, logo_size, markup, photo_path
from . import basemap
from .labels import LabelPlacer, route_anchors, stacked

C = lambda h: colors.HexColor(h)  # noqa: E731
STYLES = getSampleStyleSheet()
NAVY, GOLD, LIGHT = "#0b2545", "#d4a437", "#eef3fa"
CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.4, leading=9)
CELL_R = ParagraphStyle("cellr", parent=CELL, alignment=TA_RIGHT)
CELL_H = ParagraphStyle("cellh", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")
CELL_BR = ParagraphStyle("cellbr", parent=CELL_B, alignment=TA_RIGHT)
_NUM = re.compile(r"^[A-Z]{0,3}\s?-?[\d,]+(\.\d+)?\s?(m|%|pcs)?$")


# ---------------------------------------------------------------------------
# Map sheets
# ---------------------------------------------------------------------------
def _map_points(d: Design) -> list[tuple[float, float]]:
    """Points that define the drawing area: the proposed network, equipment, premises, boundary and ducts.
    Existing cables and poles are drawn but do not stretch the sheet (they can run far beyond the project)."""
    pts = [(p.lat, p.lon) for coll in (d.homes, d.nodes) for p in coll if valid_coord(p.lat, p.lon)]
    pts += [(v.lat, v.lon) for c in d.cables if c.status == "proposed" for v in c.path]
    pts += [tuple(b) for b in d.info.boundary] + [(v.lat, v.lon) for x in d.ducts for v in x.path]
    pts += [(p.lat, p.lon) for p in d.poles if p.status == "proposed" and valid_coord(p.lat, p.lon)]
    if not pts:  # nothing proposed yet: use everything
        pts = [(p.lat, p.lon) for p in d.poles if valid_coord(p.lat, p.lon)]
        pts += [(v.lat, v.lon) for c in d.cables for v in c.path]
    return pts


class _Labels(LabelPlacer):
    """Map labels on a PDF sheet: placed by LabelPlacer in points, drawn with reportlab."""

    def __init__(self, x0, y0, w, h):
        super().__init__(24.0, (x0, y0, x0 + w, y0 + h))

    def place_text(self, cv, text, x, y, font, size, r, fill, anchors=None, optional=False):
        """Draw text near (x, y) (or at the first free of several anchor points, e.g. along a cable)."""
        # the box is the whole line: descender to the top of capitals and accents (about 1.15 x the font size)
        at = self.place(stringWidth(text, font, size), size * 1.15, r, anchors or [(x, y)], optional)
        if at is None:
            return
        left, bottom, leader = at
        cv.setFillColor(fill)
        if leader:  # the label sits away from its point
            cv.setStrokeColor(fill)
            cv.setLineWidth(0.3)
            cv.line(*leader)
        cv.setFont(font, size)
        cv.drawString(left, bottom + size * 0.22, text)  # baseline above the descender


def _sheet_basemap(cv, style, proj, x0, y0, w, h, cx, cy, scale, light):
    """Map tiles filling the sheet's map frame, faded so the drawing stays readable, with their attribution."""
    south, west = proj.latlon(cx - w / 2 / scale, cy - h / 2 / scale)
    north, east = proj.latlon(cx + w / 2 / scale, cy + h / 2 / scale)
    img = basemap.image(style, south, west, north, east, min(2400, max(64, round(w / 72 * 120))))
    if img is None:
        cv.setFillColor(colors.grey)
        cv.setFont("Helvetica", 6)
        cv.drawString(x0 + 4, y0 + 4, "Map not available (tiles could not be fetched)")
        return
    img = basemap.faded(img, 0.35 if light else 0.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    buf.seek(0)
    cv.drawImage(ImageReader(buf), x0, y0, w, h)
    if not light:  # dark sheets: darken instead, so light lines and labels stand out
        cv.setFillColor(colors.black)
        cv.setFillAlpha(0.45)
        cv.rect(x0, y0, w, h, stroke=0, fill=1)
        cv.setFillAlpha(1)
    cv.setFillColor(colors.HexColor("#333333") if light else colors.white)
    cv.setFont("Helvetica", 5)
    cv.drawString(x0 + 3, y0 + 3, basemap.attribution(style))


def _draw_markups(cv, d: Design, T, scale, labels):
    """The drafting layer: lines, shapes, notes, leaders and dimensions, in their own colours."""
    for m in d.markups:
        P = [T(la, lo) for la, lo in m.points]
        cv.setStrokeColor(C(m.colour))
        cv.setFillColor(C(m.colour))
        cv.setLineWidth(0.9)
        size = max(4.0, min(m.size * scale, 24.0))
        if m.kind in ("line", "polyline", "leader"):
            pp = cv.beginPath()
            for i, xy in enumerate(P):
                (pp.moveTo if i == 0 else pp.lineTo)(*xy)
            if m.kind == "polyline" and m.closed:
                pp.close()
            cv.drawPath(pp, stroke=1, fill=0)
            if m.kind == "leader" and len(P) >= 2:  # arrowhead at the first point
                (ax, ay), (bx, by) = P[0], P[1]
                a = math.atan2(by - ay, bx - ax)
                for s in (0.4, -0.4):
                    cv.line(ax, ay, ax + 6 * math.cos(a + s), ay + 6 * math.sin(a + s))
        elif m.kind == "circle":
            (ax, ay), (bx, by) = P
            cv.circle(ax, ay, math.hypot(bx - ax, by - ay), stroke=1, fill=0)
        elif m.kind == "dimension":
            (ax, ay), (bx, by) = P
            a, off = math.atan2(by - ay, bx - ax), 6.0
            nx, ny = -math.sin(a) * off, math.cos(a) * off  # dimension line parallel to the measured points
            cv.line(ax, ay, ax + nx * 1.3, ay + ny * 1.3)
            cv.line(bx, by, bx + nx * 1.3, by + ny * 1.3)
            cv.line(ax + nx, ay + ny, bx + nx, by + ny)
            tx, ty = 2.5 * math.cos(a + 0.8), 2.5 * math.sin(a + 0.8)  # architectural ticks at both ends
            for px, py in ((ax + nx, ay + ny), (bx + nx, by + ny)):
                cv.line(px - tx, py - ty, px + tx, py + ty)
            length = haversine(*m.points[0], *m.points[1])
            text = m.text or f"{length:.1f} m"
            cv.saveState()
            cv.translate((ax + bx) / 2 + nx * 1.6, (ay + by) / 2 + ny * 1.6)
            cv.rotate(math.degrees(a if -math.pi / 2 < a <= math.pi / 2 else a + math.pi))
            cv.setFont("Helvetica", size)
            cv.drawCentredString(0, 0, text)
            cv.restoreState()
            continue
        if m.text and m.kind in ("text", "leader"):
            x, y = P[-1]
            cv.setFont("Helvetica", size)
            cv.drawString(x + (2 if m.kind == "leader" else 0), y, m.text)
            labels.block(x + stringWidth(m.text, "Helvetica", size) / 2, y + size / 2, max(size, stringWidth(m.text, "Helvetica", size) / 2))


def _draw_map(cv, d: Design, x0, y0, w, h, detail: bool, window=None, light: bool = False):
    """Draw the design into a box. window = (proj, minx, miny, maxx, maxy) in local metres shows one sheet tile."""
    pts = _map_points(d)
    if not pts:
        cv.drawString(x0 + 10, y0 + h / 2, "No mapped features")
        return None
    if window:
        proj, minx, miny, maxx, maxy = window
    else:
        proj = LocalProjection.for_points(pts)
        xy = [proj.xy(*p) for p in pts]
        minx, maxx = min(p[0] for p in xy), max(p[0] for p in xy)
        miny, maxy = min(p[1] for p in xy), max(p[1] for p in xy)
    span = max(maxx - minx, maxy - miny, 50.0)
    scale = min(w / max(maxx - minx, span * 0.2), h / max(maxy - miny, span * 0.2)) * (1.0 if window else 0.9)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2

    def T(lat, lon):
        X, Y = proj.xy(lat, lon)
        return x0 + w / 2 + (X - cx) * scale, y0 + h / 2 + (Y - cy) * scale

    cv.saveState()
    p = cv.beginPath()
    p.rect(x0, y0, w, h)
    cv.clipPath(p, stroke=1, fill=0)
    cv.setFillColor(colors.white if light else C("#10161d"))
    cv.rect(x0, y0, w, h, stroke=0, fill=1)
    label = colors.black if light else colors.white
    if d.info.sheet_map != "off":  # the project's map under the sheet (Settings: map on PDF / DXF)
        _sheet_basemap(cv, d.info.sheet_map, proj, x0, y0, w, h, cx, cy, scale, light)

    for x in d.ducts:  # trunking / conduit
        if len(x.path) >= 2:
            cv.setStrokeColor(C("#3584e4"))
            cv.setLineWidth(1.2)
            cv.setDash(1, 2)
            dp = cv.beginPath()
            for i, v in enumerate(x.path):
                (dp.moveTo if i == 0 else dp.lineTo)(*T(v.lat, v.lon))
            cv.drawPath(dp, stroke=1, fill=0)
            cv.setDash()

    if d.info.boundary:
        cv.setStrokeColor(label)
        cv.setDash(4, 3)
        cv.setLineWidth(1)
        bp = cv.beginPath()
        for i, (la, lo) in enumerate(d.info.boundary + d.info.boundary[:1]):
            (bp.moveTo if i == 0 else bp.lineTo)(*T(la, lo))
        cv.drawPath(bp, stroke=1, fill=0)
        cv.setDash()

    nodes = {n.id: n for n in d.nodes}
    cv.setStrokeColor(C("#5e5c64"))
    cv.setLineWidth(0.4)
    cv.setDash(2, 2)
    for hm in d.homes:
        for fid in hm.fats:
            f = nodes.get(fid)
            if f and valid_coord(hm.lat, hm.lon) and valid_coord(f.lat, f.lon):
                cv.line(*T(hm.lat, hm.lon), *T(f.lat, f.lon))
    cv.setDash()

    lengths = {cl.cable: cl for cl in calc.cable_lengths(d)}
    lines = []  # (cable, page points) for the cable tags
    for c in d.cables:
        if len(c.path) < 2:
            continue
        cv.setStrokeColor(C(KIND_COLOURS[c.kind]))
        cv.setLineWidth(2.4 if c.kind == "main" else 1.6 if c.kind == "spur" else 0.8)
        pp = cv.beginPath()
        pts_ = [T(v.lat, v.lon) for v in c.path]
        for i, xy in enumerate(pts_):
            (pp.moveTo if i == 0 else pp.lineTo)(*xy)
        cv.drawPath(pp, stroke=1, fill=0)
        lines.append((c, pts_))

    # symbols first, so no label is drawn over a symbol; labels after, most important first
    labels = _Labels(x0, y0, w, h)
    for _, pts_ in lines:
        labels.block_line(pts_, 4)
    _draw_markups(cv, d, T, scale, labels)
    home_xy, pole_xy, node_xy = [], [], []
    for hm in d.homes:
        if valid_coord(hm.lat, hm.lon):
            X, Y = T(hm.lat, hm.lon)
            cv.setFillColor(C(KIND_COLOURS["home"]))
            s = 3.2 if hm.kind == "mdu" else 2.4
            cv.rect(X - s, Y - s, 2 * s, 2 * s, stroke=0, fill=1)
            labels.block(X, Y, s)
            home_xy.append((hm, X, Y, s))

    for pl in d.poles:
        if valid_coord(pl.lat, pl.lon):
            X, Y = T(pl.lat, pl.lon)
            cv.setFillColor(C(KIND_COLOURS["pole"]))
            cv.setStrokeColor(label)
            cv.setLineWidth(0.5)
            cv.circle(X, Y, 2.6, stroke=1 if pl.status == "proposed" else 0, fill=1)
            labels.block(X, Y, 2.6)
            pole_xy.append((pl, X, Y))

    placed: list[tuple[float, float]] = []  # equipment symbols drawn so far
    for n in d.nodes:
        lat, lon = d.node_position(n)
        if not valid_coord(lat, lon):
            continue
        X0, Y0 = T(lat, lon)
        X, Y = stacked(placed, X0, Y0, 8, 9.5)
        if (X, Y) != (X0, Y0):
            cv.setStrokeColor(label)
            cv.setLineWidth(0.3)
            cv.line(X0, Y0, X, Y)
        cv.setFillColor(C(KIND_COLOURS[n.kind]))
        cv.setStrokeColor(label)
        cv.setLineWidth(0.6)
        if n.kind == "FAT":
            tp = cv.beginPath()
            tp.moveTo(X, Y + 5); tp.lineTo(X - 4.5, Y - 3.5); tp.lineTo(X + 4.5, Y - 3.5); tp.close()
            cv.drawPath(tp, stroke=1, fill=1)
        else:
            cv.rect(X - 4, Y - 4, 8, 8, stroke=1, fill=1)
        labels.block(X, Y, 4.5)
        node_xy.append((n, X, Y))

    for n, X, Y in node_xy:
        labels.place_text(cv, n.id + (" " + ",".join(s.ratio for s in d.splitters if s.node == n.id)
                                      if detail and any(s.node == n.id for s in d.splitters) else ""),
                          X, Y, "Helvetica-Bold", 6, 4.5, label, optional=not detail)  # overview: where room
    if detail:
        for c, pts_ in lines:  # tag at the free-most segment midpoint, starting from the middle of the route
            cl = lengths.get(c.id)
            labels.place_text(cv, f"{c.id} {c.cores}C {cl.total_m:.0f}m" if cl else c.id, *pts_[0], "Helvetica-Bold",
                              6, 1.5, C(KIND_COLOURS[c.kind]), anchors=route_anchors(pts_), optional=c.kind == "drop")
        for hm, X, Y, s in home_xy:
            labels.place_text(cv, hm.id + (f" ({hm.units})" if hm.units > 1 else ""), X, Y, "Helvetica", 4.5, s, label,
                              optional=True)
        for pl, X, Y in pole_xy:
            labels.place_text(cv, pl.id, X, Y, "Helvetica", 5, 2.6, C("#1a5fb4") if light else C("#99c1f1"),
                              optional=True)
    cv.restoreState()
    return scale


def _north_and_scale(cv, x, y, scale):
    cv.setFillColor(colors.black)
    cv.setFont("Helvetica-Bold", 10)
    p = cv.beginPath()
    p.moveTo(x, y + 22); p.lineTo(x - 6, y + 4); p.lineTo(x, y + 9); p.lineTo(x + 6, y + 4); p.close()
    cv.drawPath(p, stroke=0, fill=1)
    cv.drawCentredString(x, y + 25, "N")
    if not scale:
        return
    target = 120 / scale  # metres in ~120 pt
    nice = 10 ** math.floor(math.log10(target))
    for m in (5, 2, 1):
        if nice * m <= target:
            nice *= m
            break
    L = nice * scale
    sx, sy = x + 25, y + 6
    cv.setLineWidth(1)
    cv.setStrokeColor(colors.black)
    cv.line(sx, sy, sx + L, sy)
    for t in (0, 0.5, 1):
        cv.line(sx + L * t, sy - 3, sx + L * t, sy + 3)
    cv.setFont("Helvetica", 7)
    cv.drawString(sx, sy + 6, "0")
    cv.drawRightString(sx + L, sy + 6, f"{nice:g} m")


def _legend(cv, x, y):
    items = [("line", KIND_COLOURS["main"], "Main cable"), ("line", KIND_COLOURS["spur"], "Spur cable"),
             ("line", KIND_COLOURS["drop"], "Drop cable"), ("dot", KIND_COLOURS["pole"], "Pole"),
             ("sq", KIND_COLOURS["home"], "Home / MDU")] + \
            [("tri" if k == "FAT" else "sq", KIND_COLOURS[k], v) for k, v in NODE_LABEL.items()]
    cv.setFont("Helvetica-Bold", 9)
    cv.setFillColor(colors.black)
    cv.drawString(x, y, "LEGEND")
    cv.setFont("Helvetica", 7.5)
    for i, (kind, col, label) in enumerate(items):
        yy = y - 13 - i * 11
        cv.setFillColor(C(col))
        cv.setStrokeColor(C(col))
        if kind == "line":
            cv.setLineWidth(2)
            cv.line(x, yy + 3, x + 16, yy + 3)
        elif kind == "dot":
            cv.circle(x + 8, yy + 3, 3, stroke=0, fill=1)
        elif kind == "tri":
            p = cv.beginPath(); p.moveTo(x + 8, yy + 7); p.lineTo(x + 4, yy); p.lineTo(x + 12, yy); p.close()
            cv.drawPath(p, stroke=0, fill=1)
        else:
            cv.rect(x + 4, yy, 8, 7, stroke=0, fill=1)
        cv.setFillColor(colors.black)
        cv.drawString(x + 22, yy + 1, label)
    return y - 13 - len(items) * 11


def map_pdf(d: Design, st: Stamp, title: str, detail: bool) -> bytes:
    buf = io.BytesIO()
    W, H = landscape(A3)
    cv = rl_canvas.Canvas(buf, pagesize=(W, H))
    cv.setTitle(f"{title} - {d.info.name}")
    m = 12 * mm
    side = 70 * mm
    cv.setLineWidth(1.2)
    cv.rect(m, m, W - 2 * m, H - 2 * m)
    scale = _draw_map(cv, d, m + 4, m + 4, W - 2 * m - side - 8, H - 2 * m - 8, detail)
    sx = W - m - side
    cv.line(sx, m, sx, H - m)
    top = H - m - 8
    size = logo_size(st.brand.logo, side - 16, 18 * mm)
    if size:
        try:
            cv.drawImage(str(st.brand.logo), sx + 8, top - size[1], size[0], size[1], mask="auto")
            top -= size[1] + 6
        except (OSError, ValueError):
            pass
    cv.setFont("Helvetica-Bold", 8)
    cv.setFillColor(colors.black)
    cv.drawString(sx + 8, top - 6, st.brand.name[:44])
    cv.setFont("Helvetica-Bold", 16)
    cv.setFillColor(C("#1f4e79"))
    cv.drawString(sx + 8, top - 26, title)
    cv.setFont("Helvetica", 9)
    cv.setFillColor(colors.black)
    yy = top - 44
    for t in (d.info.name, d.info.area, f"Client: {d.info.client}" if d.info.client else ""):
        if t:
            cv.drawString(sx + 8, yy, t[:48])
            yy -= 12
    yy = _legend(cv, sx + 8, yy - 14)
    s = calc.summary(d)
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(sx + 8, yy - 14, "SUMMARY")
    cv.setFont("Helvetica", 7.5)
    lines = [f"Poles: {s['poles']} ({s['poles_new']} new)", f"Premises: {s['homes']} / HPs {s['homepasses']}"] + \
            [f"{k}: {v:,.0f} m" for k, v in s["cable_m"].items()] + \
            [f"{NODE_LABEL[k]}: {v}" for k, v in s["nodes"].items() if v]
    for i, t in enumerate(lines):
        cv.drawString(sx + 8, yy - 27 - i * 10, t)
    _north_and_scale(cv, sx + 20, m + 70, scale)
    cv.setFont("Helvetica", 7)
    tb = [f"Revision: {st.revision}", f"Status: {st.status.upper()}", f"Data hash: {st.hash}", f"Date: {st.date}",
          f"Prepared by: {d.info.prepared_by}"]
    for i, t in enumerate(tb):
        cv.drawString(sx + 8, m + 50 - i * 9, t)
    cv.showPage()
    cv.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Table documents
# ---------------------------------------------------------------------------
def _brand_header(cv, st: Stamp, x0: float, x1: float, top: float):
    """Issuer logo on the left, its name and details on the right, a rule underneath."""
    b = st.brand
    size = logo_size(b.logo, 42 * mm, 11 * mm)
    if size:
        try:
            cv.drawImage(str(b.logo), x0, top - size[1], size[0], size[1], mask="auto")
        except (OSError, ValueError):
            pass
    cv.setFont("Helvetica-Bold", 9)
    cv.setFillColor(C("#1f4e79"))
    cv.drawRightString(x1, top - 4 * mm, b.name[:80])
    if b.details:
        cv.setFont("Helvetica", 6.5)
        cv.setFillColor(colors.grey)
        cv.drawRightString(x1, top - 8 * mm, b.details[:140])
    cv.setStrokeColor(C("#d4a437"))
    cv.setLineWidth(0.8)
    cv.line(x0, top - 12.5 * mm, x1, top - 12.5 * mm)
    cv.setStrokeColor(colors.black)


def _footer(st: Stamp):
    def draw(cv, doc):
        cv.saveState()
        _brand_header(cv, st, doc.leftMargin, doc.pagesize[0] - doc.rightMargin, doc.pagesize[1] - 8 * mm)
        cv.setFont("Helvetica", 7)
        cv.setFillColor(colors.grey)
        cv.drawString(doc.leftMargin, 8 * mm, st.line)
        cv.drawRightString(doc.pagesize[0] - doc.rightMargin, 8 * mm, f"Page {doc.page}")
        cv.restoreState()
    return draw


def _widths(headers, rows, avail: float) -> list[float]:
    """Column widths: every column fits its longest word (no broken words such as 'Uni t'), and the rest of the
    width goes to the columns with the most text. Short tables stay compact."""
    sample = rows[:300]
    longest = [max([len(str(h))] + [len(str(r[j])) for r in sample if j < len(r)]) for j, h in enumerate(headers)]
    word = [max(len(w) for c in [h] + [r[j] for r in sample if j < len(r)] for w in (str(c).split() or [""]))
            for j, h in enumerate(headers)]
    floor = [max(w, 3) * 4.4 + 9 for w in word]  # points: the longest word at 7.4 pt plus padding
    want = [min(max(n, 4), 48) for n in longest]
    total = min(avail, max(avail * 0.5, sum(want) * 6.2 + 12 * len(want), sum(floor)))
    extra = max(total - sum(floor), 0)
    grow = [max(w * 6.2 + 12 - f, 0) for w, f in zip(want, floor)]
    g = sum(grow) or 1
    out = [f + extra * x / g for f, x in zip(floor, grow)]
    k = total / sum(out)
    return [w * k for w in out]


def _table(headers, rows, widths=None, total_row=False, avail: float = 186 * mm):
    """A schedule table: header row, zebra rows, wrapped cell text, numbers right-aligned."""
    rows = [["" if c is None else str(c) for c in r] for r in rows]
    numeric = [bool(rows) and any(j < len(r) and r[j].strip() for r in rows)
               and all(_NUM.match(r[j].strip()) or not r[j].strip() for r in rows if j < len(r))
               for j in range(len(headers))]
    body = []
    for n, r in enumerate(rows):
        last = total_row and n == len(rows) - 1
        body.append([Paragraph(markup(c), (CELL_BR if numeric[j] else CELL_B) if last else
                               (CELL_R if numeric[j] else CELL)) for j, c in enumerate(r)])
    head = [Paragraph(markup(h), CELL_H) for h in headers]
    t = Table([head] + body, colWidths=widths or _widths(headers, rows, avail), repeatRows=1, hAlign="LEFT")
    style = [("BACKGROUND", (0, 0), (-1, 0), C("#1f4e79")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
             ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C("#f2f5fa")])]
    if total_row:
        style += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8), ("BACKGROUND", (0, -1), (-1, -1), C("#d9e2f3"))]
    t.setStyle(TableStyle(style))
    return t


def _doc(story, st: Stamp, title: str, pagesize=A4) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=24 * mm, bottomMargin=16 * mm, title=title, author=st.brand.name)
    doc.build(story, onFirstPage=_footer(st), onLaterPages=_footer(st))
    return buf.getvalue()


def _head(title: str, d: Design):
    return [Paragraph(title, STYLES["Title"]), Paragraph(markup(f"{d.info.name} - {d.info.area}"), STYLES["Normal"]),
            Spacer(1, 6)]


def _sector_schedule_pdf(d: Design, st: Stamp) -> bytes:
    """Other sectors: support schedule with the sector's hardware and equipment columns and recorded details."""
    sec, rows = sectors.get(d.info.sector), calc.pole_summary(d)
    cols = sectors.schedule_columns(d.info.sector)
    fields = sec["details"].get("pole", [])

    def det(pid):
        x = d.pole(pid).details if d.pole(pid) else {}
        return "; ".join(f"{f['label']}: {x[f['key']]}{' ' + f['unit'] if f['unit'] else ''}" for f in fields if f["key"] in x)
    data = [[p.pole, f"{p.lat:.5f}, {p.lon:.5f}" if p.lat is not None and p.lon is not None else "-", len(p.cables)] +
            [getattr(p, k) for k, _ in cols] +
            [Paragraph(markup("; ".join(x for x in (det(p.pole), "; ".join(p.notes)) if x)), STYLES["BodyText"])]
            for p in rows]
    tot = ["Total", "", sum(len(p.cables) for p in rows)] + [sum(getattr(p, k) for p in rows) for k, _ in cols] + [""]
    title = f"{sec['support']} Schedule"
    widths = [24 * mm, 32 * mm, 14 * mm] + [20 * mm] * len(cols)
    widths.append(max(267 * mm - sum(widths), 50 * mm))
    story = _head(title, d) + [_table([f"{sec['support']} ID", "Location (Lat, Long)", f"{sec['line']}s"] +
                                      [h for _, h in cols] + ["Details and notes"], data + [tot], widths, total_row=True)]
    return _doc(story, st, title, landscape(A4))


def pole_summary_pdf(d: Design, st: Stamp) -> bytes:
    if not sectors.fibre_tools(d):
        return _sector_schedule_pdf(d, st)
    rows = calc.pole_summary(d)
    data = [[p.pole, f"{p.lat:.5f}, {p.lon:.5f}" if p.lat is not None and p.lon is not None else "-", len(p.cables),
             p.tension, p.upb, p.jhooks, p.ext_arms, p.jb, p.enclosures, p.fats,
             Paragraph(markup("; ".join(p.notes)), STYLES["BodyText"])]
            for p in rows]
    tot = ["Total", "", sum(len(p.cables) for p in rows)] + \
        [sum(getattr(p, k) for p in rows) for k in ("tension", "upb", "jhooks", "ext_arms", "jb", "enclosures", "fats")] + [""]
    story = _head("Pole Summary", d) + [_table(
        ["Pole ID", "Location (Lat, Long)", "Cables", "Tension Clamps", "UPB", "J-Hooks", "Ext. Arm", "JB",
         "Enclosure", "FAT", "Notes"],
        data + [tot], [22 * mm, 32 * mm, 13 * mm, 17 * mm, 11 * mm, 14 * mm, 14 * mm, 9 * mm, 15 * mm, 10 * mm, 70 * mm],
        total_row=True)]
    return _doc(story, st, "Pole Summary", landscape(A4))


def bom_pdf(d: Design, st: Stamp) -> bytes:
    lines = calc.bom(d)
    data = [[i, l.code, l.description, l.unit, f"{l.qty:,.0f}", l.source] for i, l in enumerate(lines, 1)]
    story = _head("Bill of Materials (BOM)", d) + [_table(["Item", "Code", "Description", "Unit", "Quantity", "Basis"], data,
                                                          [10 * mm, 28 * mm, 66 * mm, 14 * mm, 20 * mm, 48 * mm])]
    if d.adjustments:
        story += [Spacer(1, 10), Paragraph("Authorised manual adjustments", STYLES["Heading3"]),
                  _table(["Code", "Change", "Reason", "By"], [[a.code, a.qty, a.reason, a.by] for a in d.adjustments])]
    return _doc(story, st, "BOM")


def boq_pdf(d: Design, st: Stamp) -> bytes:
    lines = calc.bom(d)
    cur = d.info.currency
    data = [[l.description, l.unit, f"{l.qty:,.0f}", f"{l.rate:,.2f}" if l.rate is not None else "n/a",
             f"{l.total:,.2f}" if l.total is not None else "n/a"] for l in lines]
    data.append(["Total", "", "", "", f"{calc.boq_total(lines):,.2f}"])
    story = _head("Bill of Quantities (BOQ)", d) + [_table(
        ["Description", "Unit", "Quantity", f"Unit Rate ({cur})", f"Total ({cur})"], data,
        [70 * mm, 15 * mm, 25 * mm, 32 * mm, 34 * mm], total_row=True)]
    return _doc(story, st, "BOQ")


# ---------------------------------------------------------------------------
# Splicing
# ---------------------------------------------------------------------------
def _schematic(cv, d: Design, x, y, w, h):
    """POP -> PON (1st stage) -> FAT (2nd stage) tree drawn from the connection records."""
    pops = [n for n in d.nodes if n.kind == "POP"]
    s1 = [s for s in d.splitters if s.stage == 1]
    s2 = [s for s in d.splitters if s.stage == 2]
    feeds, labels = {}, {}
    for s in s1 + s2:
        t = splicing.trace_upstream(d, s.id)
        up = next((st_["to"].split(" OUT")[0] for st_ in t["steps"] if " OUT " in st_["to"]), None)
        feeds[s.id] = (up, t["ok"])
        cores = [st_["to"] for st_ in t["steps"] if " core " in st_["to"]]
        port = next((st_["to"].split(" OUT ")[1] for st_ in t["steps"] if " OUT " in st_["to"]), None)
        labels[s.id] = ((f"OUT {port} > " if port else "") + (cores[0] if cores else "")) if t["ok"] else ""

    cols = [x + 10, x + w * 0.38, x + w * 0.72]
    step2 = min(44, (h - 60) / max(len(s2), 1))  # one row per 2nd-stage splitter
    bh = min(18.0, max(step2 - 2, 4.0))          # boxes and text shrink so neighbouring rows never touch
    fs = min(6.5, max(bh * 0.6, 3.0))

    def link_label(bx, by, text):
        """The fibre feeding a box, on the box's own row just before it: lines fanning out of one splitter meet
        in the middle, so labels there would print over each other."""
        if text:
            cv.setFillColor(colors.black)
            cv.setFont("Helvetica", fs)
            cv.drawRightString(bx - 4, by + 1.5, text)
    cv.setFont("Helvetica-Bold", 9)
    for cx_, label in zip(cols, ("POP / OLT", "1st stage (PON)", "2nd stage (FAT)")):
        cv.drawString(cx_, y + h - 12, label)

    def box(bx, by, text, col, height=18.0):
        cv.setFillColor(C(col)); cv.setStrokeColor(colors.black)
        cv.roundRect(bx, by - height / 2, 110, height, min(3, height / 4), stroke=1, fill=1)
        cv.setFillColor(colors.white); cv.setFont("Helvetica-Bold", min(7.5, height * 0.45))
        cv.drawString(bx + 5, by - height * 0.17, text)

    pos = {}
    for i, p in enumerate(pops):
        yy = y + h - 40 - i * 30
        box(cols[0], yy, p.id, KIND_COLOURS["POP"])
        pos[p.id] = (cols[0] + 110, yy)
    for i, s in enumerate(s1):
        yy = y + h - 40 - i * max(44, step2 * 4)
        box(cols[1], yy, f"{s.node} {s.ratio}", KIND_COLOURS["PON"])
        pos[s.id] = (cols[1], yy)
        if feeds[s.id][1] and pops:
            cv.setStrokeColor(C(KIND_COLOURS["main"])); cv.setLineWidth(1.4)
            cv.line(*pos[pops[0].id], cols[1], yy)
            link_label(cols[1], yy, labels[s.id])
    load = calc.fat_load(d)
    for i, s in enumerate(s2):
        yy = y + h - 40 - i * step2
        up, ok = feeds[s.id]
        box(cols[2], yy, f"{s.node} {s.ratio}", KIND_COLOURS["FAT"] if ok else "#77767b", bh)
        if up and up in pos:
            cv.setStrokeColor(C(KIND_COLOURS["spur"])); cv.setLineWidth(1.2)
            cv.line(pos[up][0] + 110, pos[up][1], cols[2], yy)
            link_label(cols[2], yy, labels[s.id])
        cv.setFillColor(colors.black); cv.setFont("Helvetica", fs)
        node = d.node(s.node)
        hp = load.get(s.node, 0)
        ports = (node.ports if node and node.ports else d.rules.default_fat_ports)
        cv.drawString(cols[2] + 114, yy - fs * 0.4, f"> {hp} HPs on FAT ({ports} ports)" if ok else "")
        if not ok:
            cv.setFillColor(colors.red); cv.setFont("Helvetica", min(7, fs + 0.5))
            cv.drawString(cols[2] + 114, yy - fs * 0.4, "NOT FED")


def splicing_pdf(d: Design, st: Stamp) -> bytes:
    buf = io.BytesIO()
    W, H = landscape(A4)
    cv = rl_canvas.Canvas(buf, pagesize=(W, H))
    cv.setTitle(f"Fibre Splicing Diagram - {d.info.name}")
    m = 12 * mm
    cv.setFont("Helvetica-Bold", 15); cv.setFillColor(C("#1f4e79"))
    cv.drawString(m, H - m - 10, f"Fibre Splicing Diagram - {d.info.name}")
    _schematic(cv, d, m, m + 20, W - 2 * m, H - 2 * m - 40)
    cv.setFont("Helvetica", 7); cv.setFillColor(colors.grey)
    cv.drawString(m, 8 * mm, st.line)
    # colour key
    cv.setFont("Helvetica", 7)
    for i, (name, hx) in enumerate(splicing.COLOURS):
        cv.setFillColor(C(hx)); cv.setStrokeColor(colors.black)
        cv.circle(m + 6 + i * 52, m + 10, 4, stroke=1, fill=1)
        cv.setFillColor(colors.black)
        cv.drawString(m + 12 + i * 52, m + 8, f"{i + 1} {name}")
    cv.showPage()
    cv.save()
    first = buf.getvalue()

    story = [Paragraph("Splice records by node", STYLES["Heading2"])]
    for n in d.nodes:
        info = splicing.node_splicing(d, n.id)
        if not info["connections"] and not info["splitters"]:
            continue
        story.append(Paragraph(markup(f"{n.id} - {NODE_LABEL[n.kind]}" + (f" (pole {n.pole})" if n.pole else "")),
                               STYLES["Heading3"]))
        if info["splitters"]:
            story.append(Paragraph(markup("Splitters: " + ", ".join(f"{s['id']} stage {s['stage']} {s['ratio']}"
                                                              for s in info["splitters"])), STYLES["BodyText"]))
        rows, swatches = [], []
        for r, c in enumerate(info["connections"], start=1):
            rows.append([c["id"], c["a_label"], "", c["b_label"], "", "auto" if c["auto"] else "manual"])
            for col, hx in ((2, c["a_hex"]), (4, c["b_hex"])):
                if hx:
                    swatches.append(("BACKGROUND", (col, r), (col, r), C(hx)))
        t = _table(["ID", "Incoming", "", "Outgoing", "", "Source"], rows,
                   [16 * mm, 75 * mm, 6 * mm, 75 * mm, 6 * mm, 16 * mm])
        t.setStyle(TableStyle(swatches))
        story += [t, Spacer(1, 8)]
    story.append(Paragraph("Core usage by cable", STYLES["Heading2"]))
    story.append(_table(["Cable", "Type", "Cores", "Used", "Reserved", "Spare"],
                        [[c["cable"], c["kind"], c["cores"], c["used"], c["reserved"], c["spare"]]
                         for c in splicing.core_table(d)], avail=273 * mm))
    second = _doc(story, st, "Splicing records", landscape(A4))
    return _merge([first, second])


def _merge(pdfs: list[bytes]) -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for p in pdfs:
        for page in PdfReader(io.BytesIO(p)).pages:
            w.add_page(page)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Survey report
# ---------------------------------------------------------------------------
RPT = {
    "h1": ParagraphStyle("rh1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=C(NAVY), spaceBefore=4,
                         spaceAfter=2),
    "h2": ParagraphStyle("rh2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=C("#1557b0"),
                         spaceBefore=9, spaceAfter=4),
    "body": ParagraphStyle("rbody", fontName="Helvetica", fontSize=9.3, leading=13.4, alignment=TA_JUSTIFY, spaceAfter=6),
    "missing": ParagraphStyle("rmiss", fontName="Helvetica-Oblique", fontSize=9, leading=12, textColor=C("#9a3b3b"),
                              spaceAfter=6),
    "caption": ParagraphStyle("rcap", fontName="Helvetica", fontSize=7.6, leading=9.6, textColor=C("#4a5b73")),
    "toc": ParagraphStyle("rtoc", fontName="Helvetica", fontSize=10, leading=18),
}


class _ReportDoc(BaseDocTemplate):
    """A4 report: a cover page without the running header, contents with page numbers, branded pages after."""

    def __init__(self, buf, st: Stamp, title: str, title_text: str = "FTTH Survey and Design Report"):
        self.title_text = title_text
        super().__init__(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=26 * mm,
                         bottomMargin=18 * mm, title=title, author=st.brand.name)
        self.st = st
        body = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        cover = Frame(self.leftMargin, 20 * mm, self.width, A4[1] - 38 * mm, id="cover")
        self.addPageTemplates([PageTemplate("cover", [cover], onPage=self._cover_page),
                               PageTemplate("body", [body], onPage=self._body_page)])

    def _cover_page(self, cv, doc):
        cv.saveState()
        cv.setFillColor(C(NAVY))
        cv.rect(0, 0, A4[0], 13 * mm, stroke=0, fill=1)
        cv.setFillColor(C(GOLD))
        cv.rect(0, 13 * mm, A4[0], 1.3 * mm, stroke=0, fill=1)
        cv.setFillColor(colors.white)
        cv.setFont("Helvetica", 7.5)
        cv.drawString(18 * mm, 5 * mm, self.st.brand.name[:60])
        cv.drawRightString(A4[0] - 18 * mm, 5 * mm, f"Rev {self.st.revision} | {self.st.date}")
        cv.restoreState()

    def _body_page(self, cv, doc):
        cv.saveState()
        _brand_header(cv, self.st, self.leftMargin, A4[0] - self.rightMargin, A4[1] - 9 * mm)
        cv.setStrokeColor(C("#d9dee5"))
        cv.setLineWidth(0.5)
        cv.line(self.leftMargin, 13 * mm, A4[0] - self.rightMargin, 13 * mm)
        cv.setFont("Helvetica", 7)
        cv.setFillColor(colors.grey)
        cv.drawString(self.leftMargin, 9 * mm, f"{self.st.project[:70]}  |  {self.title_text}  |  "
                                              f"Rev {self.st.revision} ({self.st.status.replace('_', ' ')})")
        cv.drawRightString(A4[0] - self.rightMargin, 9 * mm, f"Page {doc.page}")
        cv.restoreState()

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name == "rh1":
            self.notify("TOCEntry", (0, f.getPlainText(), self.page))


def _cards(items, width: float):
    style = ParagraphStyle("card", fontName="Helvetica", fontSize=15, leading=18)
    cells = [[Paragraph(f'<font size="15" color="{NAVY}"><b>{markup(v)}</b></font><br/>'
                        f'<font size="7.3" color="#4a5b73">{markup(k).upper()}</font>', style) for k, v in items[i:i + 3]]
             for i in range(0, len(items), 3)]
    for row in cells:
        row += [""] * (3 - len(row))
    t = Table(cells, colWidths=[width / 3] * 3)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C(LIGHT)), ("LINEBEFORE", (0, 0), (-1, -1), 3, C(GOLD)),
                           ("LINEBELOW", (0, 0), (-1, -2), 4, colors.white), ("TOPPADDING", (0, 0), (-1, -1), 9),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _kv(rows, width: float):
    t = Table([[Paragraph(markup(k), CELL_B), Paragraph(markup(v), CELL)] for k, v in rows],
              colWidths=[width * 0.32, width * 0.68])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), C(LIGHT)), ("GRID", (0, 0), (-1, -1), 0.3, C("#c9d3e0")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _cover(d: Design, st: Stamp, width: float) -> list:
    i = d.info
    out = []
    size = logo_size(st.brand.logo, 62 * mm, 26 * mm)
    if size:
        out.append(Image(str(st.brand.logo), size[0], size[1], hAlign="LEFT"))
    out += [Spacer(1, 22 * mm),
            Paragraph(f'<font color="#b8862b"><b>{markup(sectors.get(i.sector)["report_title"].upper())}</b></font>',
                      ParagraphStyle("ck", fontName="Helvetica", fontSize=10, leading=14, spaceAfter=8)),
            Paragraph(markup(i.name or "Project"),
                      ParagraphStyle("ct", fontName="Helvetica-Bold", fontSize=24, leading=29, textColor=C(NAVY))),
            Spacer(1, 6),
            Paragraph(markup(" | ".join(x for x in (i.area, i.client, i.cluster) if x)),
                      ParagraphStyle("cs", fontName="Helvetica", fontSize=12, leading=16, textColor=C("#4a5b73"))),
            Spacer(1, 8), HRFlowable(width="30%", thickness=2.2, color=C(GOLD), hAlign="LEFT"), Spacer(1, 18 * mm),
            Paragraph("Document control", RPT["h2"]), _kv(report.document_control(d, st), width), Spacer(1, 8),
            Paragraph("Sign-off", RPT["h2"])]
    sign = Table([[Paragraph(h, CELL_H) for h in ("Role", "Name", "Signature", "Date")]] +
                 [[Paragraph(markup(k), CELL_B), Paragraph(markup(v or ""), CELL), "", ""] for k, v in report.signoff(d)],
                 colWidths=[width * 0.28, width * 0.32, width * 0.24, width * 0.16], rowHeights=[None] + [10 * mm] * 4)
    sign.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), C(NAVY)), ("GRID", (0, 0), (-1, -1), 0.3, C("#c9d3e0")),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return out + [sign]


def _h1(text: str) -> list:
    return [Paragraph(markup(text), RPT["h1"]),
            HRFlowable(width="100%", thickness=1.2, color=C(GOLD), spaceBefore=2, spaceAfter=8)]


def report_pdf(d: Design, st: Stamp, photo_dir: Path | None) -> bytes:
    buf = io.BytesIO()
    doc = _ReportDoc(buf, st, f"{sectors.get(d.info.sector)['report_title']} - {d.info.name}",
                     sectors.get(d.info.sector)["report_title"])
    width = doc.width
    toc = TableOfContents()
    toc.levelStyles = [RPT["toc"]]
    story = _cover(d, st, width) + [NextPageTemplate("body"), PageBreak(), Paragraph("Contents", RPT["h2"]), toc,
                                    PageBreak()]
    for n, sec in enumerate(report.sections(d)):
        if n:
            story.append(CondPageBreak(70 * mm))  # a section heading never sits alone at the foot of a page
        story += _h1(sec.title)
        for b in sec.blocks:
            kind = b[0]
            if kind == "p":
                story.append(Paragraph(markup(b[1]), RPT["body"]))
            elif kind == "missing":
                story.append(Paragraph(markup(b[1]) + " <font size='7.5' color='#7a8aa0'>(to be completed in the "
                                       "project details)</font>", RPT["missing"]))
            elif kind == "h":
                story += [CondPageBreak(35 * mm), Paragraph(markup(b[1]), RPT["h2"])]
            elif kind == "kv":
                story += [_kv(b[1], width), Spacer(1, 8)]
            elif kind == "table":
                story += [_table(b[1], b[2], total_row=b[3], avail=width), Spacer(1, 8)]
            elif kind == "cards":
                story += [_cards(b[1], width), Spacer(1, 10)]
            elif kind == "bullets":
                story.append(ListFlowable([ListItem(Paragraph(markup(x), RPT["body"]), leftIndent=12) for x in b[1]],
                                          bulletType="bullet", leftIndent=12))
        story.append(Spacer(1, 8))

    photos = [(p, photo_path(photo_dir, p.file)) for p in d.photos]
    cells = []
    cellw = (width - 6 * mm) / 2
    for ph, path in photos:
        if not path:
            continue
        try:
            img = Image(str(path))
        except OSError:
            continue
        ratio = img.imageHeight / img.imageWidth
        img.drawWidth, img.drawHeight = cellw, cellw * ratio
        if img.drawHeight > 70 * mm:
            img.drawHeight, img.drawWidth = 70 * mm, 70 * mm / ratio
        cap = f"<b>{markup(ph.caption or ph.file)}</b>" + (f" ({markup(ph.feature)})" if ph.feature else "")
        a = ph.analysis or {}
        if a.get("objects") or a.get("summary"):
            cap += "<br/><font color='#1557b0'>Photo AI:</font> " + \
                markup(a.get("summary") or ", ".join(o.get("label", "") for o in a.get("objects", [])[:6]))
            if a.get("pole_labels"):
                cap += " Labels: " + markup(", ".join(a["pole_labels"]))
            if a.get("issues"):
                cap += " <font color='#9a3b3b'>Issues: " + markup(", ".join(a["issues"])) + "</font>"
        cells.append([img, Spacer(1, 3), Paragraph(cap, RPT["caption"])])
    if cells:
        story += [PageBreak()] + _h1("Appendix A. Survey Photographs")
        grid = Table([[cells[k], cells[k + 1] if k + 1 < len(cells) else ""] for k in range(0, len(cells), 2)],
                     colWidths=[cellw + 3 * mm] * 2)
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
        story.append(grid)
    doc.multiBuild(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Home list and QA reports
# ---------------------------------------------------------------------------
def home_list_pdf(d: Design, st: Stamp) -> bytes:
    i = d.info
    story = _head("Home List", d)
    story.append(Paragraph(markup(f"Region: {i.region or '-'}   Zone: {i.zone or '-'}   Cluster: {i.cluster or '-'}"),
                           STYLES["Normal"]))
    totals = []
    for title, kind in (("Multi Dwelling Units (MDUs)", "mdu"), ("Single Dwelling Units (SDUs)", "home"),
                        ("Commercial Units", "business")):
        homes = [h for h in d.homes if h.kind == kind]
        hp = sum(h.units for h in homes)
        totals.append((title, len(homes), hp))
        if not homes:
            continue
        rows = [[Paragraph(markup(h.name or h.id), STYLES["BodyText"]), h.units or "",
                 {"green": "Green", "brown": "Brown"}.get(h.field_type, ""),
                 f"{h.lat:.6f}" if h.lat is not None else "", f"{h.lon:.6f}" if h.lon is not None else "",
                 "yes" if h.acquired else "", ", ".join(h.fats)] for h in homes]
        rows.append(["Total", hp, "", "", "", "", ""])
        story += [Spacer(1, 6), Paragraph(title, STYLES["Heading3"]),
                  _table(["Name", "Viable HP", "Field", "Latitude", "Longitude", "Acquired", "Serving FAT"], rows,
                         [62 * mm, 18 * mm, 14 * mm, 22 * mm, 22 * mm, 16 * mm, 32 * mm], total_row=True)]
    story += [Spacer(1, 10), Paragraph("Summary", STYLES["Heading3"]),
              _table(["Building type", "Buildings", "Homepasses"],
                     [[t, n, hp] for t, n, hp in totals] + [["Total", sum(t[1] for t in totals), sum(t[2] for t in totals)]],
                     [70 * mm, 30 * mm, 30 * mm], total_row=True)]
    return _doc(story, st, "Home List")


def qa_pdf(d: Design, st: Stamp) -> bytes:
    from .excel import qa_rows
    rows, issues = qa_rows(d, st)
    story = _head("QA and Approval Report", d) + [
        _table(["Item", "Detail"], [[a, str(b)] for a, b in rows], [55 * mm, 120 * mm]), Spacer(1, 10),
        Paragraph("Validation issues", STYLES["Heading2"])]
    if issues:
        t = _table(["Severity", "Check", "Feature", "Issue"],
                   [[x["severity"], x["code"], x.get("ref") or "", Paragraph(markup(x["message"]), STYLES["BodyText"])]
                    for x in issues], [18 * mm, 32 * mm, 26 * mm, 110 * mm])
        t.setStyle(TableStyle([("TEXTCOLOR", (0, r), (0, r), C("#c00000")) for r, x in enumerate(issues, 1)
                               if x["severity"] == "error"]))
        story.append(t)
    else:
        story.append(Paragraph("No validation issues.", STYLES["BodyText"]))
    return _doc(story, st, "QA Report")
