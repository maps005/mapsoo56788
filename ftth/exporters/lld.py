"""LLD drawing set (A3 landscape), laid out like an approved V Squared LLD:
cover, overview, route sheets (tiled), splicing details and pole summary. Every sheet
carries the MAIN WORK LOAD strip and a title block with the approval names."""
from __future__ import annotations

import io
import math

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from .. import calc, splicing
from ..geo import LocalProjection
from ..model import Design
from . import pdf
from .common import Stamp, clean, logo_size

C = colors.HexColor
W, H = landscape(A3)
M = 10 * mm
STRIP_H = 30 * mm          # bottom band: work load (left) + title block (right)
TB_W = 150 * mm


def _workload(d: Design) -> list[tuple[str, str]]:
    q = {l.code: l.qty for l in calc.bom(d)}
    fats = [n for n in d.nodes if n.kind == "FAT" and n.status == "proposed"]
    rows = calc.pole_summary(d)
    kplc = sum(1 for r in rows if r.cables and r.status == "existing")

    def n(code, unit="pcs"):
        v = q.get(code, 0)
        return f"{v:,.0f}{'m' if unit == 'm' else unit}"
    return [
        ("16P FAT", f"{sum(1 for f in fats if (f.ports or d.rules.default_fat_ports) == 16)}pcs"),
        ("24P FAT", f"{sum(1 for f in fats if (f.ports or d.rules.default_fat_ports) == 24)}pcs"),
        ("1X8 SPLITTERS", n("SPL-1X8")), ("1X16 SPLITTERS", n("SPL-1X16")),
        ("CABLE TIES", n("CABLE-TIES", " pkts")), ("8M PROPOSED POLES", n("POLE-NEW")),
        ("KPLC POLES USED", f"{kplc}pcs"), ("J HOOK", n("J-HOOK")), ("WALL CLAMP", n("WALL-CLAMP")),
        ("JUNCTION BOX", n("JB")), ("SPLICE CLOSURE", n("ENC-SPLICE")),
        ("12C ADSS FOC", n("FOC-12C", "m")), ("24C ADSS FOC", n("FOC-24C", "m")),
        ("48C ADSS FOC", n("FOC-48C", "m")), ("PLASTIC TRUNKING", n("TRUNKING", "m")),
        ("PVC CONDUIT", n("PVC-CONDUIT", "m")), ("UPB", n("UPB")), ("TENSION CLAMPS", n("TENSION-CLAMP")),
    ]


def _frame(cv, d: Design, st: Stamp, title: str, page: int, total: int, work):
    cv.setStrokeColor(colors.black)
    cv.setLineWidth(1)
    cv.rect(M, M, W - 2 * M, H - 2 * M)
    y0 = M
    cv.line(M, y0 + STRIP_H, W - M, y0 + STRIP_H)
    # MAIN WORK LOAD
    wl_w = W - 2 * M - TB_W
    cv.setFont("Helvetica-Bold", 8)
    cv.drawCentredString(M + wl_w / 2, y0 + STRIP_H - 9, "MAIN WORK LOAD")
    per_row = math.ceil(len(work) / 2)
    cw = wl_w / per_row
    cell = (STRIP_H - 12) / 4  # label row, value row, label row, value row
    cv.setLineWidth(0.3)
    for i, (label, value) in enumerate(work):
        r, c = divmod(i, per_row)
        x = M + c * cw
        ylab = y0 + STRIP_H - 12 - (2 * r + 1) * cell
        yval = ylab - cell
        cv.rect(x, ylab, cw, cell)
        cv.rect(x, yval, cw, cell)
        cv.setFont("Helvetica", 4.4)
        cv.drawCentredString(x + cw / 2, ylab + cell / 2 - 1.5, label)
        cv.setFont("Helvetica-Bold", 6.2)
        cv.drawCentredString(x + cw / 2, yval + cell / 2 - 2, value)
    # title block
    tx = W - M - TB_W
    cv.setLineWidth(0.8)
    cv.line(tx, y0, tx, y0 + STRIP_H)
    i = d.info
    company = clean(st.brand.name or i.company or i.client or "")
    cells = [
        ("PROJECT NAME", clean(i.name)), ("DRAWING NAME", clean(title)),
        ("APPROVED BY", clean(i.approved_by)), ("CHECKED BY", clean(i.checked_by)),
        ("LEAD PLANNER", clean(i.lead_planner)), ("PLANNED BY", clean(i.planned_by or i.prepared_by)),
        ("DRAWN BY", clean(i.drawn_by)), ("DATE", st.date),
        ("DRAWING NO", clean(i.drawing_no)), ("PAGE", f"{page} of {total}"),
    ]
    colw, rowh = TB_W / 2, (STRIP_H - 8) / 5
    for k, (label, value) in enumerate(cells):
        r, c = divmod(k, 2)
        x, y = tx + c * colw, y0 + STRIP_H - 8 - (r + 1) * rowh
        cv.setLineWidth(0.3)
        cv.rect(x, y, colw, rowh)
        cv.setFont("Helvetica", 4.6)
        cv.setFillColor(colors.grey)
        cv.drawString(x + 2, y + rowh - 5, label)
        cv.setFillColor(colors.black)
        cv.setFont("Helvetica-Bold", 6.3)
        cv.drawString(x + 2, y + 2, value[:52])
    cv.setFont("Helvetica-Bold", 7.5)
    cv.setFillColor(C("#1f4e79"))
    cv.drawString(tx + 2, y0 + STRIP_H - 6.5, (company or "FTTH LLD")[:60])
    cv.setFont("Helvetica", 5)
    cv.setFillColor(colors.grey)
    cv.drawRightString(W - M - 2, y0 + STRIP_H - 6.5, f"Rev {st.revision} · {st.status.upper()} · data {st.hash}")
    cv.setFillColor(colors.black)
    size = logo_size(st.brand.logo, 48 * mm, 14 * mm)  # issuer logo, top right of the sheet
    if size:
        try:
            cv.drawImage(str(st.brand.logo), W - M - 6 - size[0], H - M - 6 - size[1], size[0], size[1], mask="auto")
        except (OSError, ValueError):
            pass
    # sheet title
    cv.setFont("Helvetica-Bold", 15)
    cv.setFillColor(C("#c01c28"))
    cv.drawString(M + 8, H - M - 20, title.upper())
    cv.setFillColor(colors.black)


def _tiles(d: Design, map_w: float, map_h: float, scale_pt_per_m: float):
    pts = pdf._map_points(d)
    if not pts:
        return None, []
    proj = LocalProjection.for_points(pts)
    xy = [proj.xy(*p) for p in pts]
    minx, maxx = min(p[0] for p in xy), max(p[0] for p in xy)
    miny, maxy = min(p[1] for p in xy), max(p[1] for p in xy)
    tw, th = map_w / scale_pt_per_m, map_h / scale_pt_per_m
    nx, ny = max(1, math.ceil((maxx - minx) / tw)), max(1, math.ceil((maxy - miny) / th))
    ox, oy = (minx + maxx) / 2 - nx * tw / 2, (miny + maxy) / 2 - ny * th / 2
    tiles = []
    for j in range(ny - 1, -1, -1):  # north first
        for i in range(nx):
            box = (ox + i * tw, oy + j * th, ox + (i + 1) * tw, oy + (j + 1) * th)
            inside = [(x, y) for x, y in xy if box[0] <= x < box[2] and box[1] <= y < box[3]]
            if inside:  # centre the sheet on what falls in this cell
                cx = (min(x for x, _ in inside) + max(x for x, _ in inside)) / 2
                cy = (min(y for _, y in inside) + max(y for _, y in inside)) / 2
                tiles.append((proj, cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2))
    return proj, tiles


def build_lld_pdf(d: Design, st: Stamp, scale_denominator: int = 1500) -> bytes:
    buf = io.BytesIO()
    cv = rl_canvas.Canvas(buf, pagesize=(W, H))
    cv.setTitle(f"LLD - {d.info.name}")
    work = _workload(d)
    map_x, map_y = M + 4, M + STRIP_H + 4
    map_w, map_h = W - 2 * M - 8, H - 2 * M - STRIP_H - 34
    scale = 72 / 25.4 * 1000 / scale_denominator  # points per metre at 1:N
    _, tiles = _tiles(d, map_w, map_h, scale)
    rows = calc.pole_summary(d)
    per_page = 48
    pole_pages = max(1, math.ceil(len(rows) / per_page))
    total = 2 + len(tiles) + 1 + pole_pages
    page = 1

    # 1 cover
    _frame(cv, d, st, "Fibre to the Home - LLD", page, total, work)
    cv.setFont("Helvetica-Bold", 34)
    cv.setFillColor(C("#1f4e79"))
    cv.drawCentredString(W / 2, H * 0.68, "FIBER TO THE HOME")
    cv.setFont("Helvetica-Bold", 18)
    cv.setFillColor(colors.black)
    cv.drawCentredString(W / 2, H * 0.60, clean(d.info.name)[:90])
    cv.setFont("Helvetica", 12)
    s = calc.summary(d)
    lines = [clean(d.info.area), f"Homepasses: {s['homepasses']}   FATs: {s['nodes']['FAT']}   "
             f"Splice closures: {s['nodes']['ENCLOSURE']}   Junction boxes: {s['nodes']['JB']}",
             "   ".join(f"{k}: {v:,.0f} m" for k, v in s["cable_m"].items()),
             f"OLT: {clean(d.info.olt_name) or '-'}   Interception: {clean(d.info.interception) or '-'}"]
    for k, t in enumerate(lines):
        cv.drawCentredString(W / 2, H * 0.53 - k * 18, t[:140])
    cv.showPage()
    page += 1

    # 2 overview
    _frame(cv, d, st, "Route overview", page, total, work)
    sc = pdf._draw_map(cv, d, map_x, map_y, map_w, map_h, detail=False, light=True)
    pdf._north_and_scale(cv, map_x + map_w - 180, map_y + 10, sc)
    cv.showPage()
    page += 1

    # route sheets
    for k, win in enumerate(tiles, start=1):
        _frame(cv, d, st, f"Route sheet {k} of {len(tiles)} (1:{scale_denominator})", page, total, work)
        sc = pdf._draw_map(cv, d, map_x, map_y, map_w, map_h, detail=True, window=win, light=True)
        pdf._north_and_scale(cv, map_x + map_w - 180, map_y + 10, sc)
        cv.showPage()
        page += 1

    # splicing details
    _frame(cv, d, st, "Splicing details", page, total, work)
    root = splicing.feed_root(d)
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(M + 8, H - M - 34, f"Feed: {clean(d.info.olt_name) or (root.id if root else '-')}"
                                     f"{' via ' + root.id if root and d.info.olt_name else ''}")
    pdf._schematic(cv, d, M + 8, map_y, W - 2 * M - 16, map_h - 20)
    cv.showPage()
    page += 1

    # pole summary
    heads = ["Name", "Pole Type", "Longitude", "Latitude", "Tension Clamps", "UPB", "J-Hooks", "Extension Arm",
             "Slack", "Equipment", "Notes"]
    widths = [0.11, 0.08, 0.09, 0.09, 0.07, 0.05, 0.06, 0.07, 0.05, 0.13, 0.20]
    slack_at = {}
    for n in d.nodes:
        if n.kind == "SLACK":
            best = min(((pdf.haversine(n.lat, n.lon, p.lat, p.lon), p.id) for p in d.poles
                        if p.lat is not None and n.lat is not None), default=None)
            if best and best[0] <= 10:
                slack_at[best[1]] = slack_at.get(best[1], 0) + 1
    tw = W - 2 * M - 16
    for pg in range(pole_pages):
        _frame(cv, d, st, "Pole summary", page, total, work)
        y = H - M - 40
        x = M + 8
        cv.setFillColor(C("#1f4e79"))
        cv.rect(x, y - 3, tw, 11, stroke=0, fill=1)
        cv.setFillColor(colors.white)
        cv.setFont("Helvetica-Bold", 6.5)
        cx = x
        for h_, w_ in zip(heads, widths):
            cv.drawString(cx + 2, y, h_)
            cx += w_ * tw
        cv.setFillColor(colors.black)
        chunk = rows[pg * per_page:(pg + 1) * per_page]
        for k, r in enumerate(chunk):
            y -= 10
            if k % 2:
                cv.setFillColor(C("#f2f5fa"))
                cv.rect(x, y - 3, tw, 10, stroke=0, fill=1)
                cv.setFillColor(colors.black)
            vals = [r.pole, r.type, f"{r.lon:.8f}" if r.lon is not None else "-",
                    f"{r.lat:.8f}" if r.lat is not None else "-", r.tension, r.upb, r.jhooks, r.ext_arms,
                    slack_at.get(r.pole, 0), ", ".join(e.split(":")[1] for e in r.equipment), "; ".join(r.notes)]
            cv.setFont("Helvetica", 6)
            cx = x
            for v, w_ in zip(vals, widths):
                cv.drawString(cx + 2, y, clean(v)[: int(w_ * tw / 3.1)])
                cx += w_ * tw
        if pg == pole_pages - 1:
            y -= 12
            cv.setFont("Helvetica-Bold", 6.5)
            tot = [sum(getattr(r, a) for r in rows) for a in ("tension", "upb", "jhooks", "ext_arms")]
            cx = x + sum(widths[:4]) * tw
            for v, w_ in zip(tot + [sum(slack_at.values())], widths[4:9]):
                cv.drawString(cx + 2, y, str(v))
                cx += w_ * tw
            cv.drawString(x + 2, y, "TOTAL")
        cv.showPage()
        page += 1
    cv.save()
    return buf.getvalue()
