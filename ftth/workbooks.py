"""Data workbooks: a project's input data as Excel, to fill in offline and upload back.

Network sectors upload survey records (poles, premises, equipment, cables) through ftth.importers. A dam's data is
its axis survey, the reservoir's elevation-area table and its parameters; a building's is the site survey, the
client's brief and the schedule of accommodation. Each workbook is generated from the project's current values,
so downloading, editing and uploading changes only what was edited; values are checked by the design model and a
bad value is reported and left as it was.
"""
from __future__ import annotations

import io

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from pydantic import ValidationError

from .building import BriefRoom, Site
from .dam import Dam
from .model import Design

# key: (description, unit) in the order of the form on screen
DAM_FIELDS = {
    "name": ("Dam name", ""), "river": ("River", ""),
    "catchment_km2": ("Catchment area", "km2"), "stream_km": ("Longest watercourse", "km"),
    "stream_slope": ("Its average slope", "%"), "rain_24h": ("Design storm, 24 h, 1 in 100 years", "mm"),
    "rain_annual": ("Mean annual rainfall", "mm"), "runoff_flood": ("Flood runoff coefficient C", ""),
    "runoff_annual": ("Share of the annual rain that runs off", ""), "evaporation": ("Open-water evaporation", "mm/yr"),
    "demand": ("Draw-off", "m3/day"), "compensation": ("Compensation / reserve flow", "m3/day"),
    "design_flood": ("Design flood (0: by the Rational method)", "m3/s"),
    "rain_cv": ("CV of the annual 24 h maxima", ""), "sediment_yield": ("Sediment yield", "t/km2/yr"),
    "sediment_years": ("Sediment design life", "years"), "hazard": ("Hazard class: high, significant or low", ""),
    "seismic_kh": ("Pseudo-static seismic coefficient kh", ""), "fetch_km": ("Effective fetch (0: estimated)", "km"),
    "fsl": ("Full supply level (0: from the target storage)", "m"), "target_storage": ("Target storage", "m3"),
    "outlet_level": ("Outlet invert / MOL (0: bed + 1.5 m)", "m"),
    "crest_width": ("Crest width (0: USBR H/5 + 3)", "m"), "slope_us": ("Upstream slope", "H:1V"),
    "slope_ds": ("Downstream slope", "H:1V"), "core_top": ("Core top width", "m"), "core_slope": ("Core side slopes", "H:1V"),
    "filter_width": ("Chimney filter width", "m"), "riprap": ("Minimum riprap thickness", "m"),
    "cutoff_width": ("Cut-off trench width", "m"), "wind_kmh": ("Design wind", "km/h"),
    "shell_phi": ("Shell friction angle phi'", "deg"), "shell_c": ("Shell effective cohesion c'", "kPa"),
    "shell_gamma": ("Shell unit weight", "kN/m3"), "core_k": ("Core permeability", "m/s"),
    "spillway_width": ("Spillway width (0: for the design head)", "m"), "spillway_head": ("Spillway design head", "m"),
    "spillway_c": ("Weir coefficient C", ""), "spillway_side": ("Spillway abutment: left or right", ""),
}
SITE_FIELDS = {
    "plot_ref": ("Plot / LR number", ""), "zone": ("Planning zone", ""),
    "soil": ("Soil: rock, murram / gravel, sand, clay, black cotton, made ground / fill", ""),
    "bearing_capacity": ("Safe bearing pressure (0: not tested)", "kN/m2"),
    "water_table": ("Water table depth (0: not found)", "m"), "slope": ("Fall across the plot", "%"),
    "ground_level": ("Ground level at the building", "m"), "geotech_report": ("Geotechnical report reference", ""),
    "survey_notes": ("Site survey notes", ""), "client_brief": ("Client's brief", ""),
    "occupants": ("Occupants", ""), "budget": ("Budget", "currency"),
    "max_coverage": ("Maximum ground coverage", "%"), "max_plot_ratio": ("Maximum plot ratio", "%"),
    "max_floors": ("Maximum floors", ""), "setback_front": ("Building line, front (road)", "m"),
    "setback_side": ("Building line, sides", "m"), "setback_rear": ("Building line, rear", "m"),
    "parking_per_unit": ("Car spaces per flat", ""), "architect": ("Architect", ""),
    "architect_reg": ("Architect's BORAQS registration", ""), "engineer": ("Structural engineer", ""),
    "engineer_reg": ("Engineer's EBK registration", ""),
}
# list sheets: (sheet, model field, columns (heading, width))
DAM_TABLES = [("Axis profile", "axis", [("Chainage (m)", 14), ("Ground level (m)", 16), ("Depth to firm ground (m)", 22)]),
              ("Reservoir", "reservoir", [("Water level (m)", 16), ("Water area (m2)", 16)])]
HEAD_FONT = Font(bold=True, color="FFFFFF")


def _head(ws, cols):
    from .exporters.excel import BOX, HEAD
    for i, (h, w) in enumerate(cols, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.fill, c.font, c.border = HEAD, HEAD_FONT, BOX
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def _params(wb, values: dict, fields: dict, title="Parameters"):
    ws = wb.create_sheet(title)
    _head(ws, [("Key", 18), ("Description", 52), ("Unit", 10), ("Value", 40)])
    for r, (k, (label, unit)) in enumerate(fields.items(), start=2):
        for col, v in enumerate((k, label, unit, values.get(k)), start=1):
            ws.cell(row=r, column=col, value=v)


def _instructions(wb, title, lines):
    ws = wb.active
    ws.title = "Instructions"
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14, color="1F4E79")
    for i, t in enumerate(lines, start=3):
        ws.cell(row=i, column=1, value=t)
    ws.column_dimensions["A"].width = 120


def dam_template(d: Design) -> bytes:
    dm = d.dam or Dam()
    wb = Workbook()
    _instructions(wb, f"Dam data - {d.info.name}", [
        "This workbook holds the dam's input data, filled with the project's current values.",
        "Axis profile: one point a row along the dam axis, chainage from the left abutment (looking downstream).",
        "Reservoir: the elevation-area table from the contour survey, one level a row.",
        "Parameters: change the Value column only; keep the Key column. An empty value keeps the current one.",
        "Upload the whole file in the Dam design tab (Upload Excel). Sheets left out or empty are not changed."])
    for sheet, field, cols in DAM_TABLES:
        ws = wb.create_sheet(sheet)
        _head(ws, cols)
        for r, row in enumerate(getattr(dm, field), start=2):
            for c, v in enumerate(row[:len(cols)], start=1):
                ws.cell(row=r, column=c, value=v)
    _params(wb, dm.model_dump(), DAM_FIELDS)
    return _save(wb)


def building_template(d: Design) -> bytes:
    site = d.info.site
    wb = Workbook()
    _instructions(wb, f"Site survey and brief - {d.info.name}", [
        "This workbook holds the site survey, the client's brief and the planning limits, filled with the current values.",
        "Site & brief: change the Value column only; keep the Key column. An empty value keeps the current one.",
        "Accommodation: the client's schedule of rooms, one kind of room a row (area 0: any size).",
        "Upload the whole file in the Building 3D tab (Upload Excel), then press Design the building."])
    _params(wb, site.model_dump(), SITE_FIELDS, "Site & brief")
    ws = wb.create_sheet("Accommodation")
    _head(ws, [("Room", 30), ("Number", 10), ("Area each (m2)", 16)])
    for r, room in enumerate(site.schedule, start=2):
        for c, v in enumerate((room.name, room.count, room.area), start=1):
            ws.cell(row=r, column=c, value=v)
    return _save(wb)


def _save(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sheet(wb, name):
    """A sheet by name, ignoring case and spaces."""
    want = name.lower().replace(" ", "")
    return next((wb[s] for s in wb.sheetnames if s.lower().replace(" ", "").replace("&", "") == want.replace("&", "")), None)


def _num(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _read_params(ws, fields: dict, report: list[str]) -> dict:
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        key = str(row[0]).strip()
        val = row[3] if len(row) > 3 else None
        if key not in fields:
            report.append(f"Unknown key '{key}' skipped")
            continue
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        out[key] = val.strip() if isinstance(val, str) else val
    return out


def _apply(model, changes: dict, report: list[str], what: str):
    """The model with the changes that pass its checks; each failing value is reported and left as it was."""
    data = model.model_dump()
    for k, v in changes.items():
        trial = {**data, k: v}
        try:
            data = type(model).model_validate(trial).model_dump()
        except ValidationError as e:
            report.append(f"{what}: '{k}' = {v!r} not accepted ({e.errors()[0]['msg']})")
    return type(model).model_validate(data)


def _open(data: bytes):
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - any unreadable upload
        raise ValueError(f"Not an Excel workbook (.xlsx): {e.__class__.__name__}") from e


def import_dam(d: Design, data: bytes) -> list[str]:
    wb = _open(data)
    report: list[str] = []
    dm = d.dam or Dam()
    changes: dict = {}
    for sheet, field, cols in DAM_TABLES:
        ws = _sheet(wb, sheet)
        if ws is None:
            continue
        rows, bad = [], 0
        for r in ws.iter_rows(min_row=2, values_only=True):
            vals = [_num(x) for x in (r or ())[:len(cols)]]
            if all(v is None for v in vals):
                continue
            if any(v is None for v in vals[:2]):
                bad += 1
                continue
            rows.append([v if v is not None else 0.0 for v in vals] + [0.0] * (len(cols) - len(vals)))
        if rows:
            changes[field] = sorted(rows)
            report.append(f"{sheet}: {len(rows)} rows" + (f", {bad} incomplete rows skipped" if bad else ""))
        elif bad:
            report.append(f"{sheet}: {bad} incomplete rows, nothing imported")
    ws = _sheet(wb, "Parameters")
    if ws is not None:
        p = _read_params(ws, DAM_FIELDS, report)
        changes.update(p)
        report.append(f"Parameters: {len(p)} values read")
    if not changes:
        raise ValueError("No dam data found: use the template's sheets Axis profile, Reservoir and Parameters")
    d.dam = _apply(dm, changes, report, "Dam")
    return report


def import_building(d: Design, data: bytes) -> list[str]:
    wb = _open(data)
    report: list[str] = []
    changes: dict = {}
    ws = _sheet(wb, "Site & brief")
    if ws is not None:
        p = _read_params(ws, SITE_FIELDS, report)
        changes.update(p)
        report.append(f"Site & brief: {len(p)} values read")
    ws = _sheet(wb, "Accommodation")
    if ws is not None:
        rooms = []
        for r in ws.iter_rows(min_row=2, values_only=True):
            if not r or not r[0] or not str(r[0]).strip():
                continue
            try:
                rooms.append(BriefRoom(name=str(r[0]).strip()[:60], count=int(_num(r[1]) or 1) if len(r) > 1 else 1,
                                       area=_num(r[2]) or 0.0 if len(r) > 2 else 0.0).model_dump())
            except (ValidationError, ValueError):
                report.append(f"Accommodation: '{r[0]}' not accepted")
        changes["schedule"] = rooms
        report.append(f"Accommodation: {len(rooms)} kinds of room")
    if not changes:
        raise ValueError("No site or brief data found: use the template's sheets Site & brief and Accommodation")
    d.info.site = _apply(d.info.site if isinstance(d.info.site, Site) else Site(), changes, report, "Site")
    return report
