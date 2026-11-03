"""Deliverables for the structural and architectural engineers of a construction project, from the one building
model and its preliminary structural design (ftth/structure.py):

- bar bending schedule (BS 8666:2020 shape codes, bar marks, cut lengths, weights by diameter), Excel and PDF;
- structural calculations: calculation sheets (Ref | Calculations | Output) for the loads, slabs, beams, columns,
  foundations and the lateral system, PDF;
- the building as an IFC4 model (storeys, walls with their openings, doors, windows, slabs, columns, spaces,
  materials, georeferenced site) for Revit, ArchiCAD, Tekla, ETABS and other BIM tools;
- architectural schedules: doors, windows, room data and finishes, areas by floor, Excel.

Everything is preliminary, for costing and coordination; the registered engineer's and architect's own
documents govern, and every output says so."""
from __future__ import annotations

import io
import math
import re
import uuid
from collections import Counter, defaultdict
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .. import building as B, structure
from ..model import Design
from .common import Stamp, clean, markup

PRELIM = ("Preliminary, for costing and coordination: the registered engineer's and architect's own drawings, "
          "schedules and calculations govern.")
UNIT_MASS = lambda d: d * d / 162.0  # noqa: E731  kg/m of a bar of diameter d mm (BS 8666)
COVER = {"slab": 25, "beam": 30, "column": 35, "wall": 30, "foundation": 75}  # mm, XC1 / XC2 (EN 1992-1-1 4.4)
LAP = 40  # laps and anchorages, bar diameters
MARK_PREFIX = {"Columns": "C", "Beams": "B", "Slab": "S", "Stairs": "ST", "Footings": "WF", "Foundations": "F",
               "Raft": "R", "Walls": "W", "Lintels": "L"}  # bar marks: C01, B01, ...


# ---------------------------------------------------------------------------------------------------------
# shared: the design and the bars it calls for
# ---------------------------------------------------------------------------------------------------------
def covers(b: B.Building) -> dict:
    """Nominal covers, mm: durability (XC1 / XC2) and the axis distances the fire period needs (EN 1992-1-2),
    whichever is more, for the bars the scheme uses (10 mm links, 20 mm column and beam bars, 10 mm slab bars)."""
    need = structure.FIRE_MIN[structure.fire_period(b)]
    return {"slab": max(COVER["slab"], need["slab"][1] - 5), "beam": max(COVER["beam"], need["beam"][1] - 20),
            "column": max(COVER["column"], math.ceil((need["column"][1] - 20) / 5) * 5),
            "wall": max(COVER["wall"], need["wall"][1] - 6), "foundation": COVER["foundation"]}


def _design(d: Design):
    b = d.building
    if not b or len(b.levels) < 2 or not b.columns:
        return None
    return structure.design(b, d.info.site.bearing_capacity)


def _spacing(text: str) -> tuple[int, int] | None:
    m = re.search(r"T(\d+)@(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _count(text: str) -> tuple[int, int] | None:
    m = re.search(r"(\d+)T(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _frame_lines(b: B.Building, lv: int):
    """The beam runs of the frame over storey lv's columns: (axis, fixed coordinate, (column positions along it))."""
    cols = [{"x": c.x, "y": c.y} for c in b.columns if c.level == lv]
    out = []
    for axis in ("x", "y"):
        lines = defaultdict(list)
        for c in cols:
            lines[round(c["y"] if axis == "x" else c["x"], 1)].append(c["x"] if axis == "x" else c["y"])
        for k, pos in sorted(lines.items()):
            pos = sorted(set(round(p, 3) for p in pos))
            if len(pos) >= 2:
                out.append((axis, k, tuple(pos)))
    return out


def _shape_length(code: str, a: float, b: float = 0.0, c: float = 0.0, dia: int = 12) -> float:
    """Cut length (mm) of a BS 8666 shape from its dimensions (mm)."""
    if code == "00":
        return a
    if code == "11":
        return a + b - 0.5 * (4 * dia) - dia
    if code == "21":
        return a + b + c - (4 * dia) - 2 * dia
    if code == "51":
        return 2 * (a + b) + 20 * dia
    return a + b + c


def bbs_rows(d: Design) -> list[dict]:
    """The bar bending schedule: one row per bar mark."""
    return bbs_rows_for(d.building, d.info.site.bearing_capacity) if d.building else []


def bbs_rows_for(b: B.Building, bearing: float = 0.0) -> list[dict]:
    """The bar bending schedule of a framed building (its preliminary design), one row per bar mark; the BOQ's
    reinforcement is its total, so the two always agree."""
    if not b or len(b.levels) < 2 or not b.columns:
        return []
    dz = structure.design(b, bearing)
    if not dz:
        return []
    rb = dz["rebar"]
    COVER = covers(b)  # noqa: N806  durability and fire
    rows: list[dict] = []
    marks = Counter()

    def add(member, n_members, n_each, dia, code, a, b_=0.0, c=0.0, note=""):
        if n_members <= 0 or n_each <= 0 or a <= 0:
            return
        pre = MARK_PREFIX.get(member.split()[0], member[:2].upper())
        marks[pre] += 1
        L = max(0.0, _shape_length(code, a, b_, c, dia))
        L = math.ceil(L / 25) * 25  # cut lengths to 25 mm
        total = n_members * n_each
        rows.append({"member": member, "mark": f"{pre}{marks[pre]:02d}",
                     "type": f"H{dia}", "dia": dia, "members": n_members, "each": n_each, "total": total,
                     "length": int(L), "shape": code, "A": int(a), "B": int(b_), "C": int(c),
                     "metres": round(total * L / 1000, 1), "kg": round(total * L / 1000 * UNIT_MASS(dia), 1),
                     "note": note})
    heights = [lv.height for lv in b.levels]
    # columns: main bars spliced at each floor (lap 40d), links at the spacing called for
    types = structure.column_types(dz)
    main = _count(rb["column"]) or (8, 20)
    link = _spacing(rb["column"]) or (10, 200)
    for t in types:
        for lv, side in enumerate(t["sizes"]):
            if lv >= len(heights):
                break
            s = side * 1000
            n = max(4, math.ceil(structure.STEEL * s * s / (math.pi * main[1] ** 2 / 4) / 2) * 2)
            add(f"Columns {t['type']} {b.levels[lv].name}", t["count"], n, main[1], "00", heights[lv] * 1000 + LAP * main[1],
                note=f"{s:.0f} sq, lap {LAP}d above the floor")
            inner = s - 2 * COVER["column"] - link[0]
            add(f"Columns {t['type']} {b.levels[lv].name} links", t["count"], math.floor(heights[lv] * 1000 / link[1]) + 1,
                link[0], "51", inner, inner, note=f"at {link[1]} mm")
    # beams: bottom and top bars along each frame line of each floor (the columns below it), laps at the
    # supports; links. The same line on several floors is one bar mark for all of them.
    runs_by = Counter()
    for lv in range(1, len(b.levels)):
        for run in _frame_lines(b, lv - 1):
            runs_by[run] += 1
    for key, axis in (("beam_x", "x"), ("beam_y", "y")):
        bm = dz[key]
        bot = _count(rb[key]) or (2, 16)
        lk = _spacing(rb[key].split("links")[-1]) or (10, 200)
        for (ax_, k, pos), floors in sorted(runs_by.items(), key=lambda t: (t[0][1], -len(t[0][2]))):
            if ax_ != axis:
                continue
            length = (pos[-1] - pos[0]) * 1000 + 2 * LAP * bot[1]
            n_bars = bot[0] * max(1, math.ceil(length / 12000))  # 12 m stock bars, lapped
            add(f"Beams B{1 if axis == 'x' else 2} line {axis}={k:g}", floors, n_bars, bot[1], "00",
                min(12000, length), note="bottom, lapped at supports")
            add(f"Beams B{1 if axis == 'x' else 2} line {axis}={k:g} top", floors, n_bars, bot[1], "00", min(12000, length),
                note="top over supports")
            w_, h_ = bm["b"] * 1000 - 2 * COVER["beam"], bm["h"] * 1000 - 2 * COVER["beam"]
            add(f"Beams B{1 if axis == 'x' else 2} line {axis}={k:g} links", floors,
                math.floor((pos[-1] - pos[0]) * 1000 / lk[1]) + len(pos), lk[0], "51", w_, h_, note=f"at {lk[1]} mm")
    # slabs: bottom mesh both ways over each floor, top bars over the beams
    bottom = _spacing(rb["slab"]) or (10, 150)
    top = _spacing(rb["slab"].split(",")[-1]) or bottom
    for lv in range(1, len(b.levels) + 1):
        slabs = [s for s in b.slabs if s.level == lv]
        if not slabs:
            continue
        for s in slabs:
            x0, y0, x1, y1 = B._bbox(s.outline)
            area = B.area(s.outline)
            fill = area / max(1e-6, (x1 - x0) * (y1 - y0))  # the share of the box the slab covers
            name = b.levels[lv].name if lv < len(b.levels) else "Roof"
            for direction, L_, W_ in (("x", x1 - x0, y1 - y0), ("y", y1 - y0, x1 - x0)):
                n = math.ceil(math.ceil(W_ * 1000 / bottom[1]) * fill)
                bars = max(1, math.ceil(L_ * 1000 / 12000))
                add(f"Slab {name} bottom {direction}", 1, n * bars, bottom[0], "00",
                    min(12000, L_ * 1000 - 2 * COVER["slab"] + (bars - 1) * LAP * bottom[0] / bars),
                    note=f"{bottom[0]} @ {bottom[1]}")
            for axis, k, pos in _frame_lines(b, lv - 1):  # top bars across each beam, 0.3 x span each side
                span = max(dz["spans"]) * 1000
                n = math.ceil((pos[-1] - pos[0]) * 1000 / top[1])
                add(f"Slab {name} top over {axis}={k:g}", 1, n, top[0], "00", 0.6 * span + 2 * LAP * top[0] / 2,
                    note=f"{top[0]} @ {top[1]} over the beam")
    # foundations
    f = dz["foundation"]
    fb = _spacing(rb["foundation"]) or (16, 150)
    if f["type"] == "pads":
        sizes = Counter((p["side"], p["depth"]) for p in f["pads"])
        for (side, dep), n in sorted(sizes.items(), reverse=True):
            a = side * 1000 - 2 * COVER["foundation"]
            each = 2 * (math.floor(a / fb[1]) + 1)
            add(f"Foundations pad {side:g} m", n, each, fb[0], "21", (dep * 1000 - 2 * COVER["foundation"]) * 0.5, a,
                (dep * 1000 - 2 * COVER["foundation"]) * 0.5, note="bottom both ways, ends turned up")
        for cf in f.get("combined", []):
            for L_, W_ in ((cf["L"], cf["B"]), (cf["B"], cf["L"])):
                a = L_ * 1000 - 2 * COVER["foundation"]
                add(f"Foundations combined {cf['L']:g}x{cf['B']:g}", 1, math.floor((W_ * 1000 - 2 * COVER["foundation"]) / fb[1]) + 1,
                    fb[0], "21", (cf["depth"] * 1000 - 2 * COVER["foundation"]) * 0.5, a,
                    (cf["depth"] * 1000 - 2 * COVER["foundation"]) * 0.5, note="bottom both ways")
    rafts = [(r_["L"], r_["B"], r_["t"], rb.get("core_raft") or rb["foundation"]) for r_ in f.get("cores", [])]
    if f["type"] == "raft":
        x0, y0, x1, y1 = B._bbox(B.footprint(b))
        rafts.append((x1 - x0, y1 - y0, f["thickness"], rb["foundation"]))
    for i, (L_, W_, t_, text) in enumerate(rafts):
        rr = _spacing(text) or (20, 150)
        for face in ("bottom", "top"):
            for dl, dw in ((L_, W_), (W_, L_)):
                bars = max(1, math.ceil(dl * 1000 / 12000))
                add(f"Raft R{i + 1} {face}", 1, (math.floor((dw * 1000 - 2 * COVER['foundation']) / rr[1]) + 1) * bars, rr[0], "00",
                    min(12000, dl * 1000 - 2 * COVER["foundation"]), note=f"{face}, {rr[0]} @ {rr[1]}, lapped")
    # stairs: waist slab main bars along each flight (lapped into the landings), distribution across, the half
    # landing both ways (structural details sheet: T12@150 main, T10@250 distribution)
    sd = dz.get("stair") or {}
    sm = _spacing(sd.get("main", "")) or (12, 150)
    sdist = _spacing(sd.get("dist", "")) or (10, 250)
    flights_by = Counter()
    for st_ in b.stairs:
        n, rise, going = B.stair_steps(b, st_)
        fl = max(1, st_.flights)
        per = math.ceil(n / fl)
        slope = math.hypot(per * st_.tread, per * rise) * 1000
        flights_by[(round(slope), round(st_.width, 2), fl)] += fl
    for (slope, width, fl), count in sorted(flights_by.items()):
        w_mm = width * 1000
        add(f"Stairs flight {slope / 1000:.1f} m", count, math.floor((w_mm - 2 * COVER["slab"]) / sm[1]) + 1, sm[0], "00",
            slope + 2 * LAP * sm[0], note=f"waist {sd.get('waist', 0.15) * 1000:.0f} mm, main T{sm[0]}@{sm[1]}, lapped into landings")
        add(f"Stairs flight {slope / 1000:.1f} m distribution", count, math.floor(slope / sdist[1]) + 1, sdist[0], "00",
            w_mm - 2 * COVER["slab"], note=f"T{sdist[0]}@{sdist[1]}")
        if fl == 2:
            land = 2 * w_mm + B.GAP * 1000
            add("Stairs half landing", count // 2, 2 * (math.floor(w_mm / sm[1]) + 1), sm[0], "00", land - 2 * COVER["slab"],
                note=f"T{sm[0]}@{sm[1]} both ways")
    # wall footings under the ground-floor walls: transverse bars and longitudinal bars, lapped
    sp = b.spec
    run0 = sum(B.length(w) for w in b.walls if w.level == 0 and w.material != "concrete")
    if run0:
        add("Footings wall strips transverse", 1, math.floor(run0 * 1000 / 200) + 1, 12, "00",
            sp.footing_width * 1000 - 2 * COVER["foundation"], note=f"T12@200 across the {sp.footing_width * 1000:.0f} mm strips")
        add("Footings wall strips longitudinal", 1, 3 * max(1, math.ceil(run0 * 1000 / 12000)), 12, "00",
            min(12000, run0 * 1000) + LAP * 12, note="3T12 along, lapped")
    # lintels over every opening: 2T12 bottom, 2T10 top, links R8 at 200
    by_w = Counter(round(o.width + 0.3, 1) for o in b.openings)
    for L_, n in sorted(by_w.items()):
        add(f"Lintels {L_ * 1000:.0f} mm", n, 2, 12, "00", L_ * 1000 - 2 * COVER["beam"], note="bottom")
        add(f"Lintels {L_ * 1000:.0f} mm top", n, 2, 10, "00", L_ * 1000 - 2 * COVER["beam"], note="top")
        add(f"Lintels {L_ * 1000:.0f} mm links", n, math.floor(L_ * 1000 / 200) + 1, 8, "51", 140, 140, note="R8@200, 200x200 lintel")
    # RC core and spine walls: vertical and horizontal bars, each face
    lat = dz["lateral"]
    hv = _spacing(lat.get("v_bars_x", "")) or (12, 200)
    hh = _spacing(lat.get("h_bars_x", "")) or (10, 200)
    by_level = defaultdict(float)
    for w in b.walls:
        if w.material == "concrete":
            by_level[w.level] += B.length(w)
    for lv, run in sorted(by_level.items()):
        h = b.wall_height(next(w for w in b.walls if w.level == lv and w.material == "concrete")) * 1000
        add(f"Walls {b.levels[lv].name} vertical", 1, 2 * (math.floor(run * 1000 / hv[1]) + 1), hv[0], "00", h + LAP * hv[0],
            note="each face, lap above the floor")
        add(f"Walls {b.levels[lv].name} horizontal", 1, 2 * (math.floor(h / hh[1]) + 1) * max(1, math.ceil(run / 12)), hh[0], "00",
            min(12000, run * 1000), note="each face, lapped at corners")
    return rows


def bbs_summary(rows: list[dict]) -> list[tuple[str, float]]:
    by = Counter()
    for r in rows:
        by[r["type"]] += r["kg"]
    return sorted(((k, round(v, 1)) for k, v in by.items()), key=lambda t: int(t[0][1:]))


BBS_COLS = [("Member", 34), ("Bar mark", 9), ("Type & size", 9), ("No. of mbrs", 9), ("No. in each", 9),
            ("Total no.", 9), ("Length (mm)", 11), ("Shape code", 9), ("A (mm)", 9), ("B (mm)", 9), ("C (mm)", 9),
            ("Total length (m)", 12), ("Weight (kg)", 11), ("Notes", 34)]


def _row_values(r: dict) -> list:
    return [r["member"], r["mark"], r["type"], r["members"], r["each"], r["total"], r["length"], r["shape"],
            r["A"] or "", r["B"] or "", r["C"] or "", r["metres"], r["kg"], r["note"]]


# ---------------------------------------------------------------------------------------------------------
# Excel helpers
# ---------------------------------------------------------------------------------------------------------
THIN = Side(style="thin", color="B0B7BF")
HEAD = PatternFill("solid", fgColor="1F3A5F")


def _sheet(wb, title, d: Design, st: Stamp, heading: str, cols: list[tuple[str, int]], rows: list[list], first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]
    ws["A1"] = heading.upper()
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = clean(f"{d.info.name} - {d.info.area}")
    ws["A3"] = clean(st.line)
    ws["A3"].font = Font(size=8, color="666666")
    for j, (name, width) in enumerate(cols, start=1):
        c = ws.cell(row=5, column=j, value=name)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), HEAD
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
        ws.column_dimensions[get_column_letter(j)].width = width
    for i, row in enumerate(rows, start=6):
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=i, column=j, value=v)
            c.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
    ws.freeze_panes = "A6"
    ws.cell(row=len(rows) + 7, column=1, value=PRELIM).font = Font(italic=True, size=8, color="B42318")
    return ws


def bbs_xlsx(d: Design, st: Stamp) -> bytes:
    rows = bbs_rows(d)
    wb = Workbook()
    ws = _sheet(wb, "Bar bending schedule", d, st, "Bar bending schedule (BS 8666:2020)", BBS_COLS,
                [_row_values(r) for r in rows], first=True)
    summ = bbs_summary(rows)
    _sheet(wb, "Summary by diameter", d, st, "Reinforcement summary", [("Bar", 10), ("Weight (kg)", 14), ("Weight (t)", 12)],
           [[k, v, round(v / 1000, 2)] for k, v in summ] + [["Total", round(sum(v for _, v in summ), 1),
                                                              round(sum(v for _, v in summ) / 1000, 2)]])
    _sheet(wb, "Shape codes", d, st, "BS 8666 shape codes used", [("Code", 8), ("Shape", 40), ("Cut length", 40)],
           [["00", "Straight", "A"], ["11", "L-bar", "A + B - 0.5r - d"], ["21", "U-bar", "A + B + C - r - 2d"],
            ["51", "Closed link", "2(A + B) + 20d"]])
    ws.auto_filter.ref = f"A5:{get_column_letter(len(BBS_COLS))}{5 + len(rows)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------------------------------------
_SS = getSampleStyleSheet()
P8 = ParagraphStyle("p8", parent=_SS["Normal"], fontSize=7.5, leading=9.5)
P8B = ParagraphStyle("p8b", parent=P8, fontName="Helvetica-Bold")
H1 = ParagraphStyle("h1", parent=_SS["Heading1"], fontSize=15, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_SS["Heading2"], fontSize=11.5, spaceBefore=8, spaceAfter=4)
NOTE = ParagraphStyle("note", parent=P8, textColor=colors.HexColor("#b42318"))


def _doc(d: Design, st: Stamp, title: str, pagesize):
    buf = io.BytesIO()

    def frame(cv, doc):
        cv.saveState()
        cv.setFont("Helvetica", 7)
        cv.setFillColor(colors.HexColor("#555555"))
        w, h = pagesize
        cv.drawString(12 * mm, 8 * mm, clean(f"{title} | {st.line}")[:180])
        cv.drawRightString(w - 12 * mm, 8 * mm, f"Page {doc.page}")
        cv.restoreState()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=title, author=clean(d.info.prepared_by or "ArchPlanner"))
    return buf, doc, frame


def _table(data, widths, head=True, size=7.5):
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", size), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b0b7bf")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if head:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", size)]
    t.setStyle(TableStyle(style))
    return t


def bbs_pdf(d: Design, st: Stamp) -> bytes:
    rows = bbs_rows(d)
    buf, doc, frame = _doc(d, st, "Bar bending schedule", landscape(A4))
    story = [Paragraph(markup(f"Bar bending schedule (BS 8666:2020) - {d.info.name}"), H1),
             Paragraph(markup(f"{d.info.area}. Bars H = high-yield B500. Cut lengths to 25 mm; laps and anchorages {LAP}d; "
                             f"covers: slabs {COVER['slab']}, beams {COVER['beam']}, columns {COVER['column']}, "
                             f"foundations {COVER['foundation']} mm."), P8), Spacer(1, 4)]
    if not rows:
        story.append(Paragraph("No framed structure in the model (no columns): nothing to schedule.", P8))
    else:
        head = ["Member", "Mark", "Bar", "No. mbrs", "No. each", "Total no.", "Length mm", "Shape", "A mm", "B mm", "C mm",
                "Total m", "kg", "Notes"]
        widths = [112, 34, 30, 32, 32, 34, 40, 30, 36, 36, 36, 44, 44, 0]
        widths[-1] = landscape(A4)[0] - 24 * mm - sum(widths[:-1])
        data = [[Paragraph(h, P8B) for h in head]] + [[Paragraph(markup(str(v)), P8) for v in _row_values(r)] for r in rows]
        story.append(_table(data, widths))
        summ = bbs_summary(rows)
        story += [Spacer(1, 8), Paragraph("Summary by diameter", H2),
                  _table([["Bar", "Weight (kg)", "Weight (t)"]] + [[k, f"{v:,.1f}", f"{v / 1000:,.2f}"] for k, v in summ]
                         + [["Total", f"{sum(v for _, v in summ):,.1f}", f"{sum(v for _, v in summ) / 1000:,.2f}"]],
                         [60, 80, 80])]
    story += [Spacer(1, 6), Paragraph(PRELIM, NOTE)]
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------------
# structural calculations
# ---------------------------------------------------------------------------------------------------------
def calc_sections(d: Design) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """The calculation sheets: (title, [(reference, calculation, output)])."""
    dz = _design(d)
    if not dz:
        return []
    b = d.building
    fyd, fcd = 0.87 * structure.FYK, 0.567 * structure.FCK
    COVER = covers(b)  # noqa: N806  durability and fire
    g_slab = structure.GAMMA_C * dz["slab"]
    g = g_slab + structure.FINISHES + structure.PARTITIONS
    q = dz["imposed"]
    wq = structure.wind_peak(dz["lateral"]["height"])
    out = []
    out.append(("1. Design basis", [
        ("EN 1990", "Ultimate limit state 1.35 Gk + 1.5 Qk; serviceability Gk + Qk", "STR / SLS"),
        ("EN 1992-1-1", f"Concrete {dz['concrete']} (fck {structure.FCK:g} MPa), foundations {dz['foundation_concrete']}; "
                        f"reinforcement {dz['steel']} (fyk {structure.FYK:g} MPa)", f"fcd {fcd:.1f} MPa, fyd {fyd:.0f} MPa"),
        ("EN 1991-1-1", f"Imposed {q:g} kN/m2 floors, {structure.ROOF_IMPOSED:g} roof; finishes {structure.FINISHES:g}, "
                        f"partitions {structure.PARTITIONS:g} kN/m2; concrete {structure.GAMMA_C:g} kN/m3", ""),
        ("EN 1991-1-4", f"vb = {structure.VB:g} m/s, terrain III (z0 {structure.Z0:g} m); at z = {wq['z']:.1f} m: "
                        f"cr = {wq['cr']:.3f}, vm = {wq['vm']:.1f} m/s, Iv = {wq['iv']:.3f}; qp = (1 + 7 Iv) 0.5 rho vm2",
         f"qp = {wq['qp']:.2f} kN/m2; x cf {structure.CF:g} = {dz['lateral']['wind_kpa']:g}"),
        ("EN 1998-1", f"Base shear {structure.SEISMIC_COEFF:g} W (ag about 0.1 g, DCM walls); accidental torsion", ""),
        ("EN 1992-1-1 4.4", f"Nominal covers (exposure XC1 / XC2, and the R{structure.fire_period(b)} axis distances): "
                            f"slabs {COVER['slab']}, beams {COVER['beam']}, columns {COVER['column']}, walls {COVER['wall']}, "
                            f"foundations {COVER['foundation']} mm", "cnom"),
        ("Site", f"Safe bearing {dz['bearing']:g} kN/m2 at {dz['foundation']['depth']:g} m"
                 + (" (ASSUMED: geotechnical report needed)" if dz["bearing_assumed"] else " (site investigation)"), ""),
    ]))
    # slab
    short, long_ = min(dz["spans"]), max(dz["spans"])
    d_eff = dz["slab"] - 0.03
    m = dz["w_floor"] * short ** 2 / 10
    K = m * 1e6 / (1000 * (d_eff * 1000) ** 2 * structure.FCK)
    z = min(0.95, 0.5 + math.sqrt(max(0.0, 0.25 - K / 1.134))) * d_eff * 1000
    As = max(m * 1e6 / (fyd * z), 0.0013 * 1e6 * dz["slab"])
    dfl = structure.slab_deflection(dz["slab"], short, q)  # the design's own check (EC2 7.16, K 1.3)
    ld, ld_lim, rho, rho0, Kd = dfl["ld"], dfl["limit"], dfl["rho"], dfl["rho0"], dfl["K"]
    out.append(("2. Slabs", [
        ("Loads", f"gk = {structure.GAMMA_C:g} x {dz['slab']:g} + {structure.FINISHES:g} + {structure.PARTITIONS:g} = {g:.2f} kN/m2; "
                  f"qk = {q:g}", f"n = 1.35 x {g:.2f} + 1.5 x {q:g} = {dz['w_floor']:.2f} kN/m2"),
        ("Span", f"{short:g} x {long_:g} m panels, {'two-way' if dz['two_way'] else 'one-way'} ({long_ / short:.2f})",
         f"h = {dz['slab'] * 1000:.0f} mm, d = {d_eff * 1000:.0f} mm"),
        ("Bending", f"M = n L2 / 10 = {dz['w_floor']:.2f} x {short:g}2 / 10 = {m:.1f} kNm/m; K = {K:.3f} (< 0.167, no "
                    f"compression steel); z = {z:.0f} mm", f"As,req = {As:.0f} mm2/m"),
        ("Provide", dz["rebar"]["slab"], f"As,prov >= {dz['rebar']['slab_As']} mm2/m"),
        ("EC2 7.4.2", f"Span / effective depth {ld:.1f} against the limit of expression 7.16 with K = {Kd:g} and "
                      f"rho = {rho * 100:.2f} % (rho0 {rho0 * 100:.2f} %): {ld_lim:.1f}",
         "OK" if ld <= ld_lim else "CHECK DEFLECTION"),
    ]))
    # beams
    rows = []
    for key, mark in (("beam_x", "B1"), ("beam_y", "B2")):
        bm = dz[key]
        L = bm["span"]
        trib = bm.get("trib", short if key == "beam_y" else short / 2)
        wl = dz["w_floor"] * trib + 1.35 * structure.GAMMA_C * bm["b"] * (bm["h"] - dz["slab"])
        M = wl * L ** 2 / 10
        V = 0.6 * wl * L
        dd = (bm["h"] - 0.05)
        Kb = M * 1e6 / (bm["b"] * 1000 * (dd * 1000) ** 2 * structure.FCK)
        zb = min(0.95, 0.5 + math.sqrt(max(0.0, 0.25 - Kb / 1.134))) * dd * 1000
        Asb = M * 1e6 / (fyd * zb)
        vEd = V * 1e3 / (bm["b"] * 1000 * 0.9 * dd * 1000)
        vmax = 0.36 * structure.FCK * (1 - structure.FCK / 250) / 1.5 * 0.69  # cot 2.5
        lk = _spacing(dz["rebar"][key].split("links")[-1]) or (10, 200)
        asw = 2 * math.pi * lk[0] ** 2 / 4
        vrs = asw / lk[1] * 0.9 * dd * 1000 * fyd * 2.5 / 1e3
        rows += [
            (f"{mark} load", f"span {L:g} m; slab {trib:g} m x {dz['w_floor']:.2f} + own weight", f"w = {wl:.1f} kN/m"),
            (f"{mark} bending", f"M = wL2/10 = {M:.0f} kNm; b x h = {bm['b'] * 1000:.0f} x {bm['h'] * 1000:.0f}, d = "
                                f"{dd * 1000:.0f}; K = {Kb:.3f} (K' 0.167); z = {zb:.0f} mm",
             f"As,req = {Asb:.0f} mm2" if Kb <= 0.167 else "K > K': DEEPEN OR ADD COMPRESSION STEEL"),
            (f"{mark} shear", f"V = 0.6 wL = {V:.0f} kN; vEd = {vEd:.2f} MPa (< vRd,max {vmax:.2f}); links "
                              f"T{lk[0]}@{lk[1]}: VRd,s = {vrs:.0f} kN (cot 2.5)", "OK" if vrs >= V and vEd < vmax else "INCREASE LINKS"),
            (f"{mark} provide", dz["rebar"][key], f"headroom {dz['headroom']:g} m"),
            (f"{mark} EC2 7.4.2", f"L / d = {L / dd:.1f} against expression 7.16 (K 1.3, rho = {Asb / (bm['b'] * dd * 1e6) * 100:.2f} %): "
                                  f"{structure.span_depth_limit(Asb / (bm['b'] * dd * 1e6)):.1f}",
             "OK" if L / dd <= structure.span_depth_limit(Asb / (bm["b"] * dd * 1e6)) else "DEEPEN BEAM"),
        ]
    out.append(("3. Beams", rows))
    # stairs: the waist slab spanning between the floor and the half landing, simply supported
    sd = dz.get("stair")
    if sd:
        t = sd["waist"]
        sm = _spacing(sd["main"]) or (12, 150)
        prov = math.pi * sm[0] ** 2 / 4 * 1000 / sm[1]
        out.append(("4. Stairs", [
            ("Geometry", f"{sd['risers']} risers of {sd['rise'] * 1000:.0f} mm, goings {sd['going'] * 1000:.0f} mm, "
                         f"{sd['flights']} flight(s); effective span {sd['span']:.2f} m (plan), simply supported",
             f"2R + G = {2 * sd['rise'] * 1000 + sd['going'] * 1000:.0f} mm"),
            ("Loads", f"gk = 25 x ({t:g} / {sd['cos']:.2f} + {sd['rise']:.3f} / 2) + 1.5 = {sd['gk']:.2f}; qk = "
                      f"{structure.STAIR_IMPOSED:g} kN/m2 (escape stair)", f"n = {sd['w']:.2f} kN/m2"),
            ("Bending", f"waist {t * 1000:.0f} mm, d = {sd['d']:.0f} mm; M = n L2 / 8 = {sd['M']:.1f} kNm/m; K = {sd['K']:.3f}",
             f"As,req = {sd['As']:.0f} mm2/m"),
            ("Provide", f"{sd['main']} main ({prov:.0f} mm2/m), {sd['dist']} distribution",
             "OK" if prov >= sd["As"] and sd["K"] <= 0.167 else "REDESIGN"),
            ("EC2 7.4.2", f"L / d = {sd['ld']:.1f} against {sd['limit']:.1f} (simply supported, expression 7.16)",
             "OK" if sd["ld"] <= sd["limit"] else "THICKEN WAIST"),
        ]))
    # columns
    rows = []
    sigma = 0.4 * structure.FCK + 0.67 * structure.FYK * structure.STEEL
    for t in structure.column_types(dz):
        c = next(c for c in dz["columns"] if c["id"] == t["ids"][0])
        s = t["sizes"][0]
        l0 = 0.85 * b.levels[0].height
        lam = l0 / (s / math.sqrt(12))
        cap = sigma * (s * 1000) ** 2 / 1e3
        rows.append((f"{t['type']} ({t['count']} no.)",
                     f"{c['trib']:g} m2 tributary, {c['edge']} edge(s); N,Ed ground = {c['N_uls']:,} kN; {s * 1000:.0f} sq: "
                     f"N,Rd = (0.4 fck + 0.67 fyk x 2 %) Ac = {cap:,.0f} kN; l0 = 0.85 x {b.levels[0].height:g} = {l0:.2f} m, "
                     f"slenderness {lam:.0f} (braced, < 25: short)",
                     f"{'OK' if cap * 1.0 >= c['N_uls'] else 'CHECK'}; sizes {', '.join(f'{v * 1000:.0f}' for v in t['sizes'][:4])}..."))
    rows.append(("Provide", dz["rebar"]["column"], "2 % steel"))
    out.append(("5. Columns", rows))
    # foundations
    f = dz["foundation"]
    rows = []
    if f["type"] == "raft":
        rows.append(("Raft", f"{f['thickness'] * 1000:.0f} mm under the whole building; average {f.get('average', 0)} kN/m2, edge "
                             f"{f['pressure']} kN/m2 with the overturning (no tension)", "OK" if not f["piles"] else "PILES"))
    else:
        for p in sorted({(p["side"], p["depth"], p["pressure"]) for p in f["pads"]}, reverse=True)[:6]:
            rows.append((f"Pad {p[0]:g} m", f"{p[0]:g} x {p[0]:g} x {p[1]:g} m; gross pressure {p[2]} kN/m2 at "
                                            f"-{f['depth']:g} m against {dz['bearing']:g}", "OK" if p[2] <= dz["bearing"] else "ENLARGE"))
        if f["pads"]:  # the heaviest pad: bending at the column face and punching (EC2 6.4)
            p = max(f["pads"], key=lambda p: p["N_sls"])
            col = next(c for c in dz["columns"] if c["id"] == p["id"])
            a, h, c_ = p["side"], p["depth"], col["sizes"][0]
            dp = (h - 0.075 - 0.016) * 1000
            N = col["N_uls"]
            qn = N / (a * a)
            Mf = qn * (a - c_) ** 2 / 8
            fb = _spacing(dz["rebar"]["foundation"]) or (16, 175)
            Asp = math.pi * fb[0] ** 2 / 4 * 1000 / fb[1]
            Asr = Mf * 1e6 / (fyd * 0.9 * dp)
            fck = 25.0
            k = min(2.0, 1 + math.sqrt(200 / dp))
            rho = min(0.02, Asp / (1000 * dp))
            vrdc = max(0.12 * k * (100 * rho * fck) ** (1 / 3), 0.035 * k ** 1.5 * math.sqrt(fck))
            c_mm = c_ * 1000
            u1 = 4 * c_mm + 2 * math.pi * 2 * dp
            A1 = (c_mm ** 2 + 4 * c_mm * 2 * dp + math.pi * (2 * dp) ** 2) / 1e6
            Vred = max(0.0, N - qn * min(A1, a * a))
            ved = Vred * 1e3 / (u1 * dp)
            ved0 = N * 1e3 / (4 * c_mm * dp)
            vmax = 0.5 * 0.6 * (1 - fck / 250) * fck / 1.5
            rows += [
                (f"Pad {a:g} m bending", f"N,Ed = {N:,} kN on {a:g} x {a:g} m: qnet = {qn:.0f} kN/m2; M at the column face = "
                                         f"q (a - c)2 / 8 = {Mf:.0f} kNm/m; d = {dp:.0f} mm",
                 f"As,req {Asr:.0f} / prov {Asp:.0f} mm2/m {'OK' if Asp >= Asr else 'MORE STEEL'}"),
                (f"Pad {a:g} m punching", f"at the column face vEd = {ved0:.2f} MPa (vRd,max {vmax:.2f}); at 2d: u1 = {u1:.0f} mm, "
                                          f"V,red = {Vred:,.0f} kN, vEd = {ved:.2f} MPa against vRd,c = {vrdc:.2f} MPa (k {k:.2f}, rho {rho * 100:.2f} %)",
                 "OK" if ved <= vrdc and ved0 <= vmax else "DEEPEN PAD"),
            ]
        for cf in f.get("combined", [])[:6]:
            rows.append(("Combined", f"{cf['L']:g} x {cf['B']:g} x {cf['depth']:g} m for {len(cf['ids'])} columns; "
                                     f"{cf['pressure']} kN/m2", "OK" if cf["pressure"] <= dz["bearing"] else "ENLARGE"))
        for i, cr in enumerate(f.get("cores", [])):
            rows.append((f"Core raft CR{i + 1}", f"{cr['L']:g} x {cr['B']:g} x {cr['t']:g} m; edge pressure with the "
                                                 f"overturning {cr['pressure']} kN/m2, no uplift (e < L/6)",
                         "OK" if cr["ok"] else "ENLARGE"))
    rows.append(("Provide", dz["rebar"]["foundation"] + (f"; core rafts {dz['rebar']['core_raft']}" if dz["rebar"].get("core_raft") else ""), ""))
    out.append(("6. Foundations", rows))
    lat = dz["lateral"]
    out.append(("7. Lateral stability", [
        ("Weight", f"floors (G + 0.3Q), frame, cores and facades: W = {lat['weight']:,} kN", ""),
        ("EN 1998-1", f"Base shear {lat['coeff']:g} W = {lat['seismic']:,} kN; wind {lat['wind_x']:,} / {lat['wind_y']:,} kN",
         f"governs: {lat['governs_x']}"),
        ("Cores", f"{lat['cores']} RC cores; solid walls {lat['walls_x']:g} m along x, {lat['walls_y']:g} m along y, "
                  f"{lat['t_x'] * 1000:.0f} mm", ""),
        ("Shear x / y", f"horizontal bars {lat.get('h_bars_x', '')} / {lat.get('h_bars_y', '')} (EC2 6.2.3, cot 1)",
         f"{(lat['use_x'] or 0):.0%} / {(lat['use_y'] or 0):.0%} used"),
        ("Overturning", f"M = {lat.get('M_x', 0):,} / {lat.get('M_y', 0):,} kNm a core; flange stress "
                        f"{lat.get('stress_x', 0):g} MPa; vertical bars {lat.get('v_bars_x', '')}",
         "OK" if max(lat["use_x"] or 0, lat["use_y"] or 0) <= 1 else "ADD WALLS"),
    ]))
    # fire resistance: EN 1992-1-2 tabulated data
    per = structure.fire_period(b)
    fm = structure.FIRE_MIN[per]
    mainc = _count(dz["rebar"]["column"]) or (8, 20)
    linkc = _spacing(dz["rebar"]["column"]) or (10, 200)
    mainb = _count(dz["rebar"]["beam_y"]) or (3, 20)
    slab_bar = _spacing(dz["rebar"]["slab"]) or (10, 150)
    a_col = COVER["column"] + linkc[0] + mainc[1] / 2
    a_beam = COVER["beam"] + 10 + mainb[1] / 2
    a_slab = COVER["slab"] + slab_bar[0] / 2
    a_wall = COVER["wall"] + 6
    small_col = min(min(c["sizes"]) for c in dz["columns"]) * 1000
    t_wall = max(dz["lateral"]["t_x"], dz["lateral"]["t_y"]) * 1000
    beam_b = min(dz["beam_x"]["b"], dz["beam_y"]["b"]) * 1000
    def chk(size, a, need, cover):
        if size < need[0]:
            return "INCREASE SIZE"
        return "OK" if a >= need[1] else f"COVER TO {math.ceil((need[1] - a + cover) / 5) * 5:.0f} mm"
    out.append(("8. Fire resistance", [
        ("Period", f"top floor at {max(lv.elevation for lv in b.levels):g} m: R{per} for the structure (R60 to 18 m, "
                   f"R90 to 30 m, R120 above)", f"R{per}"),
        ("EN 1992-1-2 5.3", f"columns: smallest {small_col:.0f} mm, axis distance {a_col:.0f} mm against "
                            f"{fm['column'][0]} / {fm['column'][1]} (table 5.2a, mu 0.7)", chk(small_col, a_col, fm["column"], COVER["column"])),
        ("EN 1992-1-2 5.6", f"continuous beams: width {beam_b:.0f} mm, axis distance {a_beam:.0f} mm against "
                            f"{fm['beam'][0]} / {fm['beam'][1]} (table 5.6)", chk(beam_b, a_beam, fm["beam"], COVER["beam"])),
        ("EN 1992-1-2 5.7", f"two-way slabs: {dz['slab'] * 1000:.0f} mm, axis distance {a_slab:.0f} mm against "
                            f"{fm['slab'][0]} / {fm['slab'][1]} (table 5.8)", chk(dz["slab"] * 1000, a_slab, fm["slab"], COVER["slab"])),
        ("EN 1992-1-2 5.4", f"core walls: {t_wall:.0f} mm, axis distance {a_wall:.0f} mm against {fm['wall'][0]} / "
                            f"{fm['wall'][1]} (table 5.4, one face exposed)", chk(t_wall, a_wall, fm["wall"], COVER["wall"])),
    ]))
    return out


def calcs_pdf(d: Design, st: Stamp) -> bytes:
    buf, doc, frame = _doc(d, st, "Structural calculations", A4)
    story = [Paragraph(markup(f"Structural calculations (preliminary) - {d.info.name}"), H1),
             Paragraph(markup(f"{d.info.area}. Engineer: {d.info.site.engineer or '-'} {d.info.site.engineer_reg or ''}. "
                             f"Date {date.today().isoformat()}."), P8),
             Paragraph(PRELIM, NOTE), Spacer(1, 6)]
    secs = calc_sections(d)
    if not secs:
        story.append(Paragraph("No framed structure in the model (no columns): load-bearing walls on strip footings; "
                               "see the quantities and the drawings.", P8))
    w = A4[0] - 24 * mm
    for title, rows in secs:
        data = [[Paragraph("Ref", P8B), Paragraph("Calculations", P8B), Paragraph("Output", P8B)]]
        data += [[Paragraph(markup(a), P8), Paragraph(markup(c), P8), Paragraph(markup(o), P8B)] for a, c, o in rows]
        story.append(KeepTogether([Paragraph(title, H2), _table(data, [w * 0.15, w * 0.6, w * 0.25])]))
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------------
# architectural schedules
# ---------------------------------------------------------------------------------------------------------
FINISHES = {  # room -> (floor, walls, ceiling, skirting)
    "Bathroom": ("Anti-slip ceramic tiles on screed", "Ceramic tiles to 2.1 m, emulsion over", "Moisture-resistant emulsion", "Tile"),
    "Shower room": ("Anti-slip ceramic tiles on screed", "Ceramic tiles full height in the shower", "Moisture-resistant emulsion", "Tile"),
    "Toilets": ("Anti-slip ceramic tiles on screed", "Ceramic tiles to 2.1 m", "Moisture-resistant emulsion", "Tile"),
    "Kitchen": ("Porcelain tiles on screed", "Tiled splashback, emulsion", "Emulsion on skim", "Tile"),
    "Living / kitchen": ("Porcelain tiles on screed", "Emulsion on plaster, tiled splashback", "Emulsion on skim", "Timber"),
    "Bedroom": ("Laminate / porcelain tiles on screed", "Emulsion on plaster", "Emulsion on skim", "Timber"),
    "Hall": ("Porcelain tiles on screed", "Emulsion on plaster", "Emulsion on skim", "Timber"),
    "Corridor": ("Terrazzo / granite tiles", "Washable emulsion", "Suspended ceiling, services above", "Terrazzo"),
    "Stair": ("Terrazzo, non-slip nosings", "Washable emulsion", "Emulsion on skim", "Terrazzo"),
    "Office": ("Raised floor, carpet tiles", "Emulsion on plaster", "Suspended mineral-fibre ceiling", "PVC"),
    "Banking hall": ("Polished granite", "Stone cladding / emulsion", "Suspended plasterboard, feature lighting", "Granite"),
    "Parking and plant": ("Power-floated concrete, sealed", "Fair-faced blockwork, painted", "Exposed soffit, painted", "-"),
    "Ward": ("Sheet vinyl, coved", "Washable emulsion", "Suspended hygienic ceiling", "Coved vinyl"),
    "Classroom": ("Vinyl tiles", "Emulsion on plaster", "Suspended mineral-fibre ceiling", "PVC"),
}


def _finish(name: str):
    for k, v in FINISHES.items():
        if name.startswith(k) or k in name:
            return v
    if "lift" in name.lower() or "lobby" in name.lower():
        return ("Terrazzo / granite tiles", "Washable emulsion", "Suspended ceiling", "Terrazzo")
    return ("Ceramic tiles on screed", "Emulsion on plaster", "Emulsion on skim", "Tile")


def schedules_xlsx(d: Design, st: Stamp) -> bytes:
    b = d.building
    wb = Workbook()
    if not b or not b.walls:
        _sheet(wb, "Schedules", d, st, "Architectural schedules", [("Note", 60)], [["No building in the model"]], first=True)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    walls = {w.id: w for w in b.walls}
    # doors and windows: one type per kind, style and size, counted by floor
    for kind, title in (("door", "Door schedule"), ("window", "Window schedule")):
        types = defaultdict(Counter)
        for o in b.openings:
            if o.kind != kind or o.wall not in walls:
                continue
            key = (o.style, round(o.width, 2), round(o.height, 2), round(o.sill, 2), o.rating,
                   walls[o.wall].kind)
            types[key][walls[o.wall].level] += 1
        rows = []
        for i, (key, by) in enumerate(sorted(types.items(), key=lambda t: (-t[0][1], t[0][0])), start=1):
            style, w_, h_, sill, rating, wk = key
            mark = f"{'D' if kind == 'door' else 'W'}{i:02d}"
            desc = (f"{'Fire door FD' + str(rating) + ', self-closing, ' if rating else ''}{style} {kind}, "
                    f"{'external' if wk == 'external' else 'internal'}")
            rows.append([mark, desc, int(w_ * 1000), int(h_ * 1000)] + ([] if kind == "door" else [int(sill * 1000), round(w_ * h_, 2)])
                        + [f"FD{rating}" if rating else "-" if kind == "door" else "Aluminium, clear glazing",
                           ", ".join(f"{b.levels[lv].name}: {n}" for lv, n in sorted(by.items()))[:200], sum(by.values())])
        cols = ([("Mark", 7), ("Description", 44), ("Width (mm)", 11), ("Height (mm)", 11)] +
                ([] if kind == "door" else [("Sill (mm)", 10), ("Area (m2)", 10)]) +
                [("Rating / finish", 22), ("Where", 60), ("Total no.", 9)])
        _sheet(wb, title, d, st, title, cols, rows, first=kind == "door")
    # room data and finishes
    rows = []
    for r in sorted(b.rooms, key=lambda r: (r.level, r.name)):
        fl, wa, ce, sk = _finish(r.name)
        lv = b.levels[min(r.level, len(b.levels) - 1)]
        rows.append([lv.name, r.id, r.unit or "-", r.name, r.area, round(lv.height - lv.slab, 2), fl, wa, ce, sk])
    _sheet(wb, "Room finishes", d, st, "Room data and finishes schedule",
           [("Level", 14), ("Room", 9), ("Unit", 8), ("Name", 26), ("Area (m2)", 10), ("Clear height (m)", 10),
            ("Floor", 30), ("Walls", 32), ("Ceiling", 30), ("Skirting", 10)], rows)
    # areas by floor
    rows = []
    tot = [0.0, 0.0, 0, 0]
    for i, lv in enumerate(b.levels):
        gfa = sum(B.area(s.outline) for s in b.slabs if s.level == i)
        net = sum(r.area for r in b.rooms if r.level == i and r.name not in ("Corridor", "Stair") and "lift" not in r.name.lower())
        circ = sum(r.area for r in b.rooms if r.level == i and (r.name in ("Corridor", "Stair") or "lift" in r.name.lower()))
        units = len({r.unit for r in b.rooms if r.level == i and r.unit})
        rooms = sum(1 for r in b.rooms if r.level == i)
        rows.append([lv.name, round(lv.elevation, 2), round(lv.height, 2), round(gfa, 1), round(net, 1), round(circ, 1),
                     f"{net / gfa:.0%}" if gfa else "-", rooms, units])
        tot = [tot[0] + gfa, tot[1] + net, tot[2] + rooms, tot[3] + units]
    rows.append(["Total", "", "", round(tot[0], 1), round(tot[1], 1), "", f"{tot[1] / tot[0]:.0%}" if tot[0] else "-", tot[2], tot[3]])
    _sheet(wb, "Area schedule", d, st, "Area schedule (gross and net by floor)",
           [("Level", 14), ("FFL (m)", 9), ("Storey (m)", 9), ("Gross floor area (m2)", 14), ("Net room area (m2)", 14),
            ("Circulation (m2)", 12), ("Net / gross", 10), ("Rooms", 8), ("Units", 8)], rows)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------------
# IFC4 (ISO 10303-21) export
# ---------------------------------------------------------------------------------------------------------
_B64 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


_GUID_NS = [""]  # the project the GUIDs belong to (set by ifc_model)


def ifc_guid(seed: str) -> str:
    """A stable 22-character IFC GlobalId (IFC base-64: 2 bits, then 21 x 6 bits) for a model element: the same
    project and element give the same GUID on every export, so a BIM tool can update its copy."""
    n = uuid.uuid5(uuid.NAMESPACE_URL, f"archplanner:{_GUID_NS[0]}:{seed}").int
    return _B64[(n >> 126) & 3] + "".join(_B64[(n >> (6 * i)) & 63] for i in range(20, -1, -1))


def _s(text: str) -> str:
    return "'" + clean(str(text)).encode("ascii", "replace").decode().replace("\\", "\\\\").replace("'", "''") + "'"


def _f(v: float) -> str:
    return f"{float(v):.4f}"


class _Ifc:
    def __init__(self):
        self.lines: list[str] = []

    def add(self, text: str) -> str:
        self.lines.append(f"#{len(self.lines) + 1}={text};")
        return f"#{len(self.lines)}"

    def pt(self, *c) -> str:
        return self.add(f"IFCCARTESIANPOINT(({','.join(_f(v) for v in c)}))")

    def dir(self, *c) -> str:
        return self.add(f"IFCDIRECTION(({','.join(_f(v) for v in c)}))")


def _latlon(v: float) -> str:
    sign = -1 if v < 0 else 1
    v = abs(v)
    deg = int(v)
    mins = int((v - deg) * 60)
    secs = (v - deg - mins / 60) * 3600
    whole = int(secs)
    micro = int(round((secs - whole) * 1e6))
    return f"({sign * deg},{sign * mins},{sign * whole},{sign * micro})"


def ifc_model(d: Design, st: Stamp) -> bytes:
    b = d.building
    _GUID_NS[0] = d.info.name + "|" + (str(b.origin) if b else "")
    f = _Ifc()
    o = f.pt(0, 0, 0)
    z, x = f.dir(0, 0, 1), f.dir(1, 0, 0)
    world = f.add(f"IFCAXIS2PLACEMENT3D({o},{z},{x})")
    ctx = f.add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,{world},$)")
    body = f.add(f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,{ctx},$,.MODEL_VIEW.,$)")
    units = [f.add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)"), f.add("IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)"),
             f.add("IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)"), f.add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)")]
    ua = f.add(f"IFCUNITASSIGNMENT(({','.join(units)}))")
    project = f.add(f"IFCPROJECT('{ifc_guid('project:' + d.info.name)}',$,{_s(d.info.name)},{_s('ArchPlanner model')},$,$,$,({ctx}),{ua})")
    site_pl = f.add(f"IFCLOCALPLACEMENT($,{world})")
    lat, lon = (b.origin or [None, None]) if b else (None, None)
    site = f.add(f"IFCSITE('{ifc_guid('site')}',$,{_s(d.info.area or 'Site')},$,$,{site_pl},$,$,.ELEMENT.,"
                 f"{_latlon(lat) if lat is not None else '$'},{_latlon(lon) if lon is not None else '$'},"
                 f"{_f(d.info.site.ground_level)},$,$)")
    bld_pl = f.add(f"IFCLOCALPLACEMENT({site_pl},{f.add(f'IFCAXIS2PLACEMENT3D({o},{z},{f.dir(math.cos(math.radians(b.rotation if b else 0)), math.sin(math.radians(b.rotation if b else 0)), 0)})')})")
    bld = f.add(f"IFCBUILDING('{ifc_guid('building')}',$,{_s(d.info.name)},$,$,{bld_pl},$,$,.ELEMENT.,$,$,$)")
    f.add(f"IFCRELAGGREGATES('{ifc_guid('agg:project')}',$,$,$,{project},({site}))")
    f.add(f"IFCRELAGGREGATES('{ifc_guid('agg:site')}',$,$,$,{site},({bld}))")
    if not b:
        return _ifc_text(f, d, st)
    dz = structure.design(b, d.info.site.bearing_capacity) if b.columns and len(b.levels) > 1 else None
    col_size = {}
    if dz:
        for c in dz["columns"]:
            col_size[(round(c["x"], 2), round(c["y"], 2))] = c["sizes"]
    storeys, st_pl, contents, spaces = [], [], defaultdict(list), defaultdict(list)
    for i, lv in enumerate(b.levels):
        pl = f.add(f"IFCLOCALPLACEMENT({bld_pl},{f.add(f'IFCAXIS2PLACEMENT3D({f.pt(0, 0, lv.elevation)},$,$)')})")
        storeys.append(f.add(f"IFCBUILDINGSTOREY('{ifc_guid(f'storey:{i}')}',$,{_s(lv.name)},$,$,{pl},$,$,.ELEMENT.,{_f(lv.elevation)})"))
        st_pl.append(pl)
    f.add(f"IFCRELAGGREGATES('{ifc_guid('agg:building')}',$,$,$,{bld},({','.join(storeys)}))")
    by_mat = defaultdict(list)
    items = {"wall": [], "slab": [], "column": [], "door": [], "window": []}  # for the property sets and quantities
    rating = structure.fire_period(b) if dz else 0

    def shape(solid: str) -> str:
        rep = f.add(f"IFCSHAPEREPRESENTATION({body},'Body','SweptSolid',({solid}))")
        return f.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({rep}))")

    def box(px, py, pz, dx_dir, w, depth, h, centre=True, parent=None):
        """A box w (along dx_dir) x depth x h, its local origin at (px, py, pz) in the parent placement."""
        ax = f.add(f"IFCAXIS2PLACEMENT3D({f.pt(px, py, pz)},{z},{f.dir(dx_dir[0], dx_dir[1], 0)})")
        lp = f.add(f"IFCLOCALPLACEMENT({parent},{ax})")
        p2 = f.add(f"IFCAXIS2PLACEMENT2D({f.pt(w / 2 if not centre else 0, 0)},$)")
        prof = f.add(f"IFCRECTANGLEPROFILEDEF(.AREA.,$,{p2},{_f(w)},{_f(depth)})")
        solid = f.add(f"IFCEXTRUDEDAREASOLID({prof},{f.add(f'IFCAXIS2PLACEMENT3D({o},$,$)')},{z},{_f(h)})")
        return lp, shape(solid)

    walls = {}
    for w in b.walls:
        L = B.length(w)
        if L < 1e-3:
            continue
        lvi = min(w.level, len(b.levels) - 1)
        ux, uy = (w.b[0] - w.a[0]) / L, (w.b[1] - w.a[1]) / L
        h = b.wall_height(w)
        lp, pds = box(w.a[0], w.a[1], 0, (ux, uy), L, w.thickness, h, centre=False, parent=st_pl[lvi])
        wid = f.add(f"IFCWALL('{ifc_guid('wall:' + w.id)}',$,{_s(w.id)},{_s(f'{w.kind} {w.material} wall')},$,{lp},{pds},{_s(w.id)},.STANDARD.)")
        walls[w.id] = (wid, lp, w)
        net = L * h - sum(o.width * o.height for o in b.openings if o.wall == w.id)
        items["wall"].append((wid, w, L, h, net))
        contents[lvi].append(wid)
        by_mat["Concrete C30/37" if w.material == "concrete" else f"{w.material.capitalize()} walling"].append(wid)
    for op in b.openings:
        if op.wall not in walls:
            continue
        wid, wlp, w = walls[op.wall]
        lvi = min(w.level, len(b.levels) - 1)
        x0 = op.offset - op.width / 2
        lp, pds = box(x0, 0, op.sill, (1, 0), op.width, w.thickness + 0.2, op.height, centre=False, parent=wlp)
        oid = f.add(f"IFCOPENINGELEMENT('{ifc_guid('open:' + op.id)}',$,{_s(op.id)},$,$,{lp},{pds},$,.OPENING.)")
        f.add(f"IFCRELVOIDSELEMENT('{ifc_guid('void:' + op.id)}',$,$,$,{wid},{oid})")
        lp2, pds2 = box(x0, 0, op.sill, (1, 0), op.width, 0.06, op.height, centre=False, parent=wlp)
        if op.kind == "door":
            el = f.add(f"IFCDOOR('{ifc_guid('door:' + op.id)}',$,{_s(op.id)},{_s(f'{op.style} door' + (f' FD{op.rating}' if op.rating else ''))},"
                       f"$,{lp2},{pds2},{_s(op.id)},{_f(op.height)},{_f(op.width)},.DOOR.,"
                       f"{'.DOUBLE_DOOR_SINGLE_SWING.' if op.style == 'double' else '.SINGLE_SWING_LEFT.'},$)")
        else:
            el = f.add(f"IFCWINDOW('{ifc_guid('window:' + op.id)}',$,{_s(op.id)},{_s(f'{op.style} window')},$,{lp2},{pds2},"
                       f"{_s(op.id)},{_f(op.height)},{_f(op.width)},.WINDOW.,.SINGLE_PANEL.,$)")
        f.add(f"IFCRELFILLSELEMENT('{ifc_guid('fill:' + op.id)}',$,$,$,{oid},{el})")
        items[op.kind].append((el, op, w.kind == "external"))
        contents[lvi].append(el)
    for s in b.slabs:
        lvi = min(s.level, len(b.levels) - 1)
        top = s.level >= len(b.levels)
        thick = dz["slab"] if dz and s.level > 0 else s.thickness  # suspended slabs as designed
        z0 = (b.levels[-1].height if top else 0.0) - thick
        pts = [f.pt(px, py) for px, py in s.outline] + [f.pt(*s.outline[0])]
        poly = f.add(f"IFCPOLYLINE(({','.join(pts)}))")
        prof = f.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{poly})")
        solid = f.add(f"IFCEXTRUDEDAREASOLID({prof},{f.add(f'IFCAXIS2PLACEMENT3D({f.pt(0, 0, z0)},$,$)')},{z},{_f(thick)})")
        lp = f.add(f"IFCLOCALPLACEMENT({st_pl[lvi]},{f.add(f'IFCAXIS2PLACEMENT3D({o},$,$)')})")
        sid = f.add(f"IFCSLAB('{ifc_guid('slab:' + s.id)}',$,{_s(s.id)},$,$,{lp},{shape(solid)},{_s(s.id)},"
                    f"{'.ROOF.' if top else '.BASESLAB.' if s.level == 0 else '.FLOOR.'})")
        contents[lvi].append(sid)
        by_mat["Concrete C30/37"].append(sid)
        items["slab"].append((sid, s, thick))
    for c in b.columns:
        lvi = min(c.level, len(b.levels) - 1)
        base = next((v for k, v in col_size.items() if abs(k[0] - c.x) < 0.3 and abs(k[1] - c.y) < 0.3), None)
        size = base[lvi] if base and lvi < len(base) else c.size
        lp, pds = box(c.x, c.y, 0, (1, 0), size, size, b.levels[lvi].height - b.levels[lvi].slab, parent=st_pl[lvi])
        cid = f.add(f"IFCCOLUMN('{ifc_guid('column:' + c.id)}',$,{_s(c.id)},{_s(f'{size * 1000:.0f} sq RC column')},$,{lp},{pds},{_s(c.id)},.COLUMN.)")
        contents[lvi].append(cid)
        by_mat["Concrete C30/37"].append(cid)
        items["column"].append((cid, size, b.levels[lvi].height - b.levels[lvi].slab))
    for s in b.stairs:
        lvi = min(s.level, len(b.levels) - 1)
        lp = f.add(f"IFCLOCALPLACEMENT({st_pl[lvi]},{f.add(f'IFCAXIS2PLACEMENT3D({f.pt(s.x, s.y, 0)},$,$)')})")
        sid = f.add(f"IFCSTAIR('{ifc_guid('stair:' + s.id)}',$,{_s(s.id)},{_s(f'{s.flights}-flight stair, {s.width:g} m')},$,{lp},$,$,"
                    f"{'.HALF_TURN_STAIR.' if s.flights == 2 else '.STRAIGHT_RUN_STAIR.'})")
        contents[lvi].append(sid)
    for r in b.roofs:
        lvi = min(r.level, len(b.levels) - 1)
        lp = f.add(f"IFCLOCALPLACEMENT({st_pl[lvi]},{f.add(f'IFCAXIS2PLACEMENT3D({o},$,$)')})")
        kind = {"flat": ".FLAT_ROOF.", "gable": ".GABLE_ROOF.", "hip": ".HIP_ROOF.", "shed": ".SHED_ROOF.",
                "arch": ".BARREL_ROOF.", "dome": ".DOME_ROOF."}.get(r.kind, ".NOTDEFINED.")
        rid = f.add(f"IFCROOF('{ifc_guid('roof:' + r.id)}',$,{_s(r.id)},{_s(f'{r.kind} roof, {r.covering}')},$,{lp},$,$,{kind})")
        contents[lvi].append(rid)
    for r in b.rooms:
        if not r.rect:
            continue
        lvi = min(r.level, len(b.levels) - 1)
        x0, y0, x1, y1 = r.rect
        lp, pds = box((x0 + x1) / 2, (y0 + y1) / 2, 0, (1, 0), x1 - x0, y1 - y0, b.levels[lvi].height - b.levels[lvi].slab,
                      parent=st_pl[lvi])
        sp = f.add(f"IFCSPACE('{ifc_guid('space:' + r.id)}',$,{_s(r.id)},{_s(r.name)},$,{lp},{pds},{_s(r.name)},.ELEMENT.,.INTERNAL.,$)")
        spaces[lvi].append(sp)
    for i, s_ in enumerate(storeys):
        if contents[i]:
            f.add(f"IFCRELCONTAINEDINSPATIALSTRUCTURE('{ifc_guid(f'contain:{i}')}',$,$,$,({','.join(contents[i])}),{s_})")
        if spaces[i]:
            f.add(f"IFCRELAGGREGATES('{ifc_guid(f'spaces:{i}')}',$,$,$,{s_},({','.join(spaces[i])}))")
    # property sets, shared by the elements that have the same values
    def prop(name, value):
        return f.add(f"IFCPROPERTYSINGLEVALUE({_s(name)},$,{value},$)")

    def pset(key, name, props, objs):
        ps = f.add(f"IFCPROPERTYSET('{ifc_guid('pset:' + key)}',$,{_s(name)},$,({','.join(prop(n, v) for n, v in props)}))")
        f.add(f"IFCRELDEFINESBYPROPERTIES('{ifc_guid('defpset:' + key)}',$,$,$,({','.join(objs)}),{ps})")
    yes = lambda v: ".T." if v else ".F."  # noqa: E731
    groups = defaultdict(list)
    for wid, w, *_ in items["wall"]:
        lb = w.material == "concrete"
        groups[("wall", w.kind == "external", lb)].append(wid)
    for (_, ext, lb), objs in groups.items():
        props = [("IsExternal", f"IFCBOOLEAN({yes(ext)})"), ("LoadBearing", f"IFCBOOLEAN({yes(lb)})")]
        if lb and rating:
            props.append(("FireRating", f"IFCLABEL('REI{rating}')"))
        pset(f"wall:{ext}:{lb}", "Pset_WallCommon", props, objs)
    for kind, pname in (("door", "Pset_DoorCommon"), ("window", "Pset_WindowCommon")):
        g2 = defaultdict(list)
        for el, op, ext in items[kind]:
            g2[(ext, op.rating)].append(el)
        for (ext, rt), objs in g2.items():
            props = [("IsExternal", f"IFCBOOLEAN({yes(ext)})")] + ([("FireRating", f"IFCLABEL('FD{rt}')")] if rt else [])
            pset(f"{kind}:{ext}:{rt}", pname, props, objs)
    if items["column"]:
        pset("column", "Pset_ColumnCommon", [("LoadBearing", "IFCBOOLEAN(.T.)")]
             + ([("FireRating", f"IFCLABEL('R{rating}')")] if rating else []), [c[0] for c in items["column"]])
    if items["slab"]:
        pset("slab", "Pset_SlabCommon", [("LoadBearing", "IFCBOOLEAN(.T.)")]
             + ([("FireRating", f"IFCLABEL('REI{rating}')")] if rating else []), [x[0] for x in items["slab"]])
    # base quantities, element by element
    def qto(eid, key, name, qs):
        made = []
        for qn, kind_, v in qs:
            ent = {"L": "IFCQUANTITYLENGTH", "A": "IFCQUANTITYAREA", "V": "IFCQUANTITYVOLUME"}[kind_]
            made.append(f.add(f"{ent}({_s(qn)},$,$,{_f(v)},$)"))
        q = f.add(f"IFCELEMENTQUANTITY('{ifc_guid('qto:' + key)}',$,{_s(name)},$,$,({','.join(made)}))")
        f.add(f"IFCRELDEFINESBYPROPERTIES('{ifc_guid('defqto:' + key)}',$,$,$,({eid}),{q})")
    for wid, w, L, h, net in items["wall"]:
        qto(wid, "wall:" + w.id, "Qto_WallBaseQuantities", [("Length", "L", L), ("Height", "L", h), ("Width", "L", w.thickness),
                                                            ("NetSideArea", "A", max(0.0, net)), ("NetVolume", "V", max(0.0, net) * w.thickness)])
    for sid, sl, thick in items["slab"]:
        a = B.area(sl.outline)
        qto(sid, "slab:" + sl.id, "Qto_SlabBaseQuantities", [("Depth", "L", thick), ("NetArea", "A", a), ("NetVolume", "V", a * thick)])
    for i, (cid, size, h) in enumerate(items["column"]):
        qto(cid, f"column:{i}", "Qto_ColumnBaseQuantities", [("Length", "L", h), ("CrossSectionArea", "A", size * size),
                                                             ("NetVolume", "V", size * size * h)])
    for name, els in by_mat.items():
        mat = f.add(f"IFCMATERIAL({_s(name)},$,$)")
        f.add(f"IFCRELASSOCIATESMATERIAL('{ifc_guid('mat:' + name)}',$,$,$,({','.join(els)}),{mat})")
    return _ifc_text(f, d, st)


def _ifc_text(f: _Ifc, d: Design, st: Stamp) -> bytes:
    stamp = date.today().isoformat() + "T00:00:00"
    head = ["ISO-10303-21;", "HEADER;",
            "FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');",
            f"FILE_NAME({_s(clean(d.info.name)[:60] + '.ifc')},'{stamp}',({_s(d.info.prepared_by or 'ArchPlanner')}),"
            f"({_s(d.info.company or 'ArchPlanner')}),'ArchPlanner','ArchPlanner',{_s(st.line[:200])});",
            "FILE_SCHEMA(('IFC4'));", "ENDSEC;", "DATA;"]
    return ("\n".join(head + f.lines + ["ENDSEC;", "END-ISO-10303-21;"]) + "\n").encode("ascii", "replace")
