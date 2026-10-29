"""Deliverable registry and full design-package builder."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Callable

from .. import calc, splicing, validate
from ..model import Design
from . import dxf, excel, kml, lld, pdf, word
from .common import Stamp

Builder = Callable[[Design, Stamp, Path | None], bytes]

MIME = {"kml": "application/vnd.google-earth.kml+xml", "kmz": "application/vnd.google-earth.kmz",
        "pdf": "application/pdf", "dxf": "image/vnd.dxf", "json": "application/json",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "zip": "application/zip"}


def _splicing_json(d: Design, st: Stamp, _p=None) -> bytes:
    data = {"stamp": st.as_dict(), "splitters": [s.model_dump() for s in d.splitters],
            "connections": [c.model_dump() for c in d.connections],
            "cores": splicing.core_table(d),
            "fat_traces": {s.node: splicing.trace_upstream(d, s.id) for s in d.splitters if s.stage == 2}}
    return json.dumps(data, indent=2).encode()


def _project_json(d: Design, st: Stamp, _p=None) -> bytes:
    return json.dumps({"stamp": st.as_dict(), "design": d.model_dump(mode="json")}, indent=2).encode()


def _csv_zip(d: Design, st: Stamp, _p=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", st.line + "\n")
        for name, text in excel.project_csvs(d).items():
            z.writestr(name, text)
    return buf.getvalue()


# deliverable -> {format: builder}
DELIVERABLES: dict[str, dict[str, Builder]] = {
    "hld": {"kml": lambda d, s, p: kml.build_kml(d, s).encode(), "kmz": lambda d, s, p: kml.build_kmz(d, s),
            "pdf": lambda d, s, p: pdf.map_pdf(d, s, "HLD DESIGN", detail=False)},
    "lld": {"dxf": lambda d, s, p: dxf.build_dxf(d, s), "pdf": lambda d, s, p: lld.build_lld_pdf(d, s),
            "zip": lambda d, s, p: dxf.build_dxf_zip(d, s)},  # DXF + map image
    "pole_summary": {"xlsx": lambda d, s, p: excel.pole_summary_xlsx(d, s), "pdf": lambda d, s, p: pdf.pole_summary_pdf(d, s)},
    "bom": {"xlsx": lambda d, s, p: excel.bom_xlsx(d, s), "pdf": lambda d, s, p: pdf.bom_pdf(d, s)},
    "boq": {"xlsx": lambda d, s, p: excel.vsquared_boq_xlsx(d, s), "pdf": lambda d, s, p: pdf.boq_pdf(d, s)},
    "splicing": {"pdf": lambda d, s, p: pdf.splicing_pdf(d, s), "xlsx": lambda d, s, p: excel.splicing_xlsx(d, s),
                 "json": _splicing_json},
    "report": {"pdf": lambda d, s, p: pdf.report_pdf(d, s, p), "xlsx": lambda d, s, p: excel.report_xlsx(d, s),
               "docx": lambda d, s, p: word.report_docx(d, s, p)},
    "home_list": {"xlsx": lambda d, s, p: excel.home_list_xlsx(d, s), "pdf": lambda d, s, p: pdf.home_list_pdf(d, s)},
    "qa": {"pdf": lambda d, s, p: pdf.qa_pdf(d, s), "xlsx": lambda d, s, p: excel.qa_xlsx(d, s)},
    "project": {"xlsx": lambda d, s, p: excel.project_xlsx(d, s), "json": _project_json, "zip": _csv_zip},
}

TITLES = {"hld": "HLD", "lld": "LLD", "pole_summary": "Pole Summary", "bom": "BOM", "boq": "BOQ",
          "splicing": "Splicing Diagram", "report": "Survey Report", "home_list": "Home List",
          "qa": "QA & Approval Report", "project": "Project Data"}


# design sections each deliverable is generated from (to flag only the outputs a change affects)
_BASE = ["info.name", "info.area", "info.client", "info.prepared_by", "info.design_status"]
_NETWORK = ["poles", "homes", "nodes", "cables", "splitters"]
DEPENDS = {
    "hld": _BASE + _NETWORK + ["info.boundary", "rules", "markups", "info.sheet_map"],
    "lld": _BASE + _NETWORK + ["info.boundary", "rules", "markups", "info.sheet_map"],
    "pole_summary": _BASE + ["poles", "nodes", "cables", "rules"],
    "bom": _BASE + _NETWORK + ["rules", "materials", "adjustments"],
    "boq": _BASE + _NETWORK + ["rules", "materials", "adjustments", "info.currency"],
    "splicing": _BASE + ["nodes", "cables", "splitters", "connections", "homes"],
    "report": _BASE + _NETWORK + ["info", "rules", "materials", "adjustments", "photos"],
    "home_list": ["homes", "info.region", "info.zone", "info.cluster", "info.name", "info.design_status"],
    "qa": ["*"],
    "project": ["*"],
}


def deliverable_hash(d: Design, deliverable: str) -> str:
    import hashlib
    data = d.model_dump(mode="json")
    keys = DEPENDS.get(deliverable, ["*"])
    if "*" in keys:
        part = data
    else:
        part = {}
        for k in keys:
            if "." in k:
                a, b = k.split(".", 1)
                part[k] = data.get(a, {}).get(b)
            else:
                part[k] = data.get(k)
    raw = json.dumps(part, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def filename(d: Design, deliverable: str, fmt: str, revision: int) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in d.info.name).strip("_") or "project"
    suffix = "_csv" if deliverable == "project" and fmt == "zip" else ""
    return f"{safe}_{deliverable.upper()}{suffix}_R{revision}.{fmt}"


def build(d: Design, deliverable: str, fmt: str, st: Stamp, photo_dir: Path | None) -> bytes:
    return DELIVERABLES[deliverable][fmt](d, st, photo_dir)


def build_package(d: Design, st: Stamp, photo_dir: Path | None) -> bytes:
    issues = validate.validate(d)
    buf = io.BytesIO()
    folders = {"hld": "01_HLD", "lld": "02_LLD", "pole_summary": "03_Pole_Summary", "bom": "04_BOM",
               "boq": "05_BOQ", "splicing": "06_Splicing", "report": "07_Survey_Report", "home_list": "08_Home_List",
               "qa": "09_QA_Report", "project": "10_Project_Data"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        files = []
        for deliv, fmts in DELIVERABLES.items():
            for fmt in fmts:
                name = f"{folders[deliv]}/{filename(d, deliv, fmt, st.revision)}"
                z.writestr(name, build(d, deliv, fmt, st, photo_dir))
                files.append(name)
        manifest = {"project": d.info.name, "revision": st.revision, "status": st.status, "data_hash": st.hash,
                    "generated": st.date, "files": files, "summary": calc.summary(d),
                    "validation": validate.counts(issues),
                    "open_issues": [i for i in issues if i["severity"] == "error"],
                    "notes": "All files were generated from the same design data (see data_hash). "
                             "LLD is supplied as DXF; open in AutoCAD and save as DWG if a native DWG is required."}
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
    return buf.getvalue()
