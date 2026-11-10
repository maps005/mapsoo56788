"""CAD drawings as survey data: a DXF (or a DWG converted to DXF) read into placemarks like a KML's.

Points are block inserts, POINT entities, circles and small closed outlines (a pole's circle, a premise's
square, an equipment symbol), named by the block's ID / NAME attribute or the nearest text; lines and
polylines are routes, closed ones areas. The layer is the "folder", so the same rules that read a KMZ's
folders (POLES, FAT, CABLE 48C, BOUNDARY...) read the layers. Coordinates are found from the drawing:
ArchPlanner's own title line, longitude / latitude, or UTM eastings / northings (the zone from the project, else
Kenya's 37); a millimetre drawing is scaled to metres.

DWG is AutoCAD's closed format: it is converted with the ODA File Converter or LibreDWG's dwg2dxf when one is
installed on the server; otherwise the upload asks for a DXF (AutoCAD: Save As > DXF).
"""
from __future__ import annotations

import io
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from .geo import GridProjection, LocalProjection, haversine
from .model import Design

MAX_ENTITIES = 60000
ID_TAGS = ("ID", "NAME", "LABEL", "TAG", "NO", "NUMBER", "REF", "POLE", "POLE_ID", "FAT", "NODE")


# ---------------------------------------------------------------------------------------------------------
# DWG -> DXF
# ---------------------------------------------------------------------------------------------------------
def _converter() -> tuple[str, str] | None:
    """(kind, path) of a DWG converter on this server."""
    env = os.environ.get("DWG_CONVERTER")
    if env and Path(env).exists():
        return ("oda" if "oda" in Path(env).name.lower() else "libredwg", env)
    for name, kind in (("ODAFileConverter", "oda"), ("dwg2dxf", "libredwg")):
        p = shutil.which(name)
        if p:
            return kind, p
    for base in (r"C:\Program Files\ODA", "/usr/bin", "/opt/ODAFileConverter"):
        for p in Path(base).glob("**/ODAFileConverter*") if Path(base).exists() else []:
            if p.is_file():
                return "oda", str(p)
    return None


def dwg_to_dxf(data: bytes) -> bytes:
    if data[:4] != b"AC10":
        raise ValueError("Not a DWG file")
    conv = _converter()
    if conv is None:
        raise ValueError("This server cannot read DWG files yet (AutoCAD's closed format). In AutoCAD use "
                         "Save As > AutoCAD DXF and upload the .dxf, which is read directly.")
    kind, exe = conv
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp, "in"), Path(tmp, "out")
        src.mkdir()
        out.mkdir()
        (src / "drawing.dwg").write_bytes(data)
        cmd = ([exe, str(src), str(out), "ACAD2018", "DXF", "0", "1", "*.DWG"] if kind == "oda"
               else [exe, "-y", "-o", str(out / "drawing.dxf"), str(src / "drawing.dwg")])
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ValueError(f"The DWG could not be converted ({e.__class__.__name__}): upload it as DXF") from e
        dxf = next(out.glob("*.dxf"), None)
        if dxf is None:
            raise ValueError("The DWG could not be converted: upload it as DXF (AutoCAD: Save As > DXF)")
        return dxf.read_bytes()


# ---------------------------------------------------------------------------------------------------------
# coordinates
# ---------------------------------------------------------------------------------------------------------
def _zone_projection(crs: str, zone: int, south: bool) -> GridProjection:
    return GridProjection(crs, -1.0 if south else 1.0, (zone - 1) * 6 - 180 + 3)


def _transform(doc, d: Design, xs: list[float], ys: list[float]):
    """(to_latlon(x, y), note): how the drawing's coordinates become WGS 84 latitude / longitude."""
    texts = " ".join(e.dxf.text for e in doc.modelspace().query("TEXT") if "oordinates" in e.dxf.text)[:2000]
    m = re.search(r"(WGS 84|Arc 1960) / UTM zone (\d+)([NS])", texts)
    if m:
        g = _zone_projection("arc1960" if m.group(1) == "Arc 1960" else "utm", int(m.group(2)), m.group(3) == "S")
        return g.latlon, f"Coordinates: {g.name} (from the drawing's title)"
    m = re.search(r"origin (?:lat )?(-?\d+\.\d+),? (?:lon )?(-?\d+\.\d+)", texts)
    if m:
        lp = LocalProjection(float(m.group(1)), float(m.group(2)))
        return lp.latlon, "Coordinates: ArchPlanner local plane (from the drawing's title)"
    if not xs:
        return None, ""
    xmid, ymid = sorted(xs)[len(xs) // 2], sorted(ys)[len(ys) // 2]
    if abs(xmid) <= 180 and abs(ymid) <= 90:
        return (lambda x, y: (y, x)), "Coordinates: longitude, latitude (WGS 84)"
    if 100000 <= xmid <= 900000 and 0 <= ymid <= 10000000:
        pts = [(x.lat, x.lon) for coll in (d.poles, d.homes, d.nodes) for x in coll if x.lat is not None]
        pts += [tuple(b) for b in d.info.boundary]
        crs = d.info.crs if d.info.crs in ("utm", "arc1960") else "utm"
        if pts:
            c = LocalProjection.for_points(pts)
            g = GridProjection(crs, c.lat0, c.lon0)
            return g.latlon, f"Coordinates: {g.name} (the project's coordinate system)"
        g = _zone_projection(crs, 37, ymid > 5000000)  # Kenya: zone 37, south of the equator above 5 000 km
        return g.latlon, f"Coordinates: assumed {g.name}; set the project's coordinate system if it is not"
    raise ValueError("The drawing's coordinates are not latitude / longitude or UTM: export it in a real "
                     "coordinate system (UTM) to place it on the map")


# ---------------------------------------------------------------------------------------------------------
# DXF -> placemarks
# ---------------------------------------------------------------------------------------------------------
def _read(data: bytes):
    from ezdxf import recover
    try:
        doc, _audit = recover.read(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 - any unreadable drawing
        raise ValueError(f"Not a readable DXF drawing ({e.__class__.__name__})") from e
    return doc


def parse_cad(filename: str, data: bytes, d: Design) -> tuple[list[dict], list[str]]:
    """Placemarks (as importers.parse_kml returns them) and notes on how the drawing was read."""
    if filename.lower().endswith(".dwg"):
        data = dwg_to_dxf(data)
    doc = _read(data)
    msp = doc.modelspace()
    unit = 0.001 if doc.header.get("$INSUNITS", 6) == 4 else 1.0  # millimetres -> metres
    pts, lines, texts = [], [], []
    for n, e in enumerate(msp):
        if n > MAX_ENTITIES:
            break
        t, layer = e.dxftype(), e.dxf.get("layer", "0")
        try:
            if t == "INSERT":
                att = {a.dxf.tag.upper(): a.dxf.text for a in e.attribs} if hasattr(e, "attribs") else {}
                name = next((att[k] for k in ID_TAGS if att.get(k)), "")
                p = e.dxf.insert
                pts.append({"x": p.x, "y": p.y, "layer": layer, "name": name.strip(), "block": e.dxf.name, "ext": att})
            elif t == "POINT":
                p = e.dxf.location
                pts.append({"x": p.x, "y": p.y, "layer": layer, "name": "", "block": "", "ext": {}})
            elif t == "CIRCLE":
                c = e.dxf.center
                pts.append({"x": c.x, "y": c.y, "layer": layer, "name": "", "block": "", "ext": {}, "r": e.dxf.radius})
            elif t in ("TEXT", "MTEXT"):
                p = e.dxf.insert
                txt = e.plain_text() if t == "MTEXT" else e.dxf.text
                if txt.strip():
                    texts.append((p.x, p.y, txt.strip()[:120], layer))
            elif t in ("LWPOLYLINE", "POLYLINE", "LINE"):
                if t == "LINE":
                    xy, closed = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)], False
                elif t == "LWPOLYLINE":
                    xy, closed = [(p[0], p[1]) for p in e.get_points("xy")], e.closed
                else:
                    xy, closed = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices], e.is_closed
                if len(xy) >= 2:
                    lines.append({"xy": xy, "closed": closed, "layer": layer})
        except (AttributeError, ValueError):
            continue
    allx = [p["x"] for p in pts] + [q[0] for ln in lines for q in ln["xy"]]
    ally = [p["y"] for p in pts] + [q[1] for ln in lines for q in ln["xy"]]
    to_ll, note = _transform(doc, d, [v * unit for v in allx], [v * unit for v in ally])
    if to_ll is None:
        raise ValueError("The drawing has no points or lines to import")
    # a small closed outline (12 m or less across, on the ground) is a symbol: a point at its centre (a premise's
    # square, an equipment triangle)
    for ln in list(lines):
        if ln["closed"]:
            xs, ys = [p[0] for p in ln["xy"]], [p[1] for p in ln["xy"]]
            a_, b_ = to_ll(min(xs) * unit, min(ys) * unit), to_ll(max(xs) * unit, max(ys) * unit)
            if haversine(*a_, *b_) <= 17:  # the diagonal of 12 m x 12 m
                pts.append({"x": sum(xs) / len(xs), "y": sum(ys) / len(ys), "layer": ln["layer"], "name": "", "block": "",
                            "ext": {}})
                lines.remove(ln)

    # everything below is measured in metres on the ground, whatever the drawing's units (degrees, m, mm)
    c_ll = to_ll(sorted(allx)[len(allx) // 2] * unit, sorted(ally)[len(ally) // 2] * unit)
    flat = LocalProjection(*c_ll)

    def g(x, y):
        return flat.xy(*to_ll(x * unit, y * unit))
    texts = [(*g(x, y), t, layer) for x, y, t, layer in texts]
    by_layer = defaultdict(list)
    for tx in texts:
        by_layer[tx[3]].append(tx)
    cell = 10.0
    grid = defaultdict(list)
    for tx in texts:
        grid[(int(tx[0] // cell), int(tx[1] // cell))].append(tx)
    generic = re.compile(r"^(0|TEXT|LABELS?|ANNO\w*|NOTES?)$", re.I)  # layers whose text may label anything

    # a nameless point takes the nearest text within 10 m, on its own layer first (a pole's label, not the FAT's on
    # the same pole), then on a general text layer, as a planner reads the drawing
    def label(x, y, layer):
        mx, my = g(x, y)
        gx, gy = int(mx // cell), int(my // cell)
        near = [tx for i in (-1, 0, 1) for j in (-1, 0, 1) for tx in grid.get((gx + i, gy + j), [])
                if math.hypot(tx[0] - mx, tx[1] - my) <= cell]
        own = [tx for tx in near if tx[3] == layer] or [tx for tx in near if generic.match(tx[3])]
        best = min(own, key=lambda tx: math.hypot(tx[0] - mx, tx[1] - my), default=None)
        return best[2] if best else ""

    def seg_dist(q, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / (dx * dx + dy * dy or 1e-12)))
        return math.hypot(q[0] - a[0] - t * dx, q[1] - a[1] - t * dy)

    def line_label(ln):  # a route's own label beside it, an ID-like one first ("C001 48C MAIN 230m", not "ROAD X")
        P = [g(x, y) for x, y in ln["xy"]]
        found = sorted((min(seg_dist(tx, P[k - 1], P[k]) for k in range(1, len(P))), tx[2]) for tx in by_layer[ln["layer"]])
        found = [t for dist, t in found if dist <= cell]
        return next((t for t in found if re.search(r"\d", t.split()[0])), found[0] if found else "")

    def line_ext(text):  # cores and kind written in a route's label
        ext, m = {}, re.search(r"(\d+)\s*C\b", text, re.I)
        if m:
            ext["cores"] = m.group(1)
        k = re.search(r"\b(MAIN|SPUR|DROP)\b", text, re.I)
        if k:
            ext["kind"] = k.group(1).lower()
        return ext

    def split_id(text):  # "FAT02 FAT 1:8" -> ("FAT02", "FAT 1:8"); "KPHT 02" stays whole
        m = re.match(r"^(\S*\d\S*)\s+(.+)$", text)
        return (m.group(1), m.group(2)) if m else (text, "")

    # a short two-point line ending at a text on its layer is a label's leader, not a route
    def leader(ln):
        if len(ln["xy"]) != 2:
            return False
        a, b = g(*ln["xy"][0]), g(*ln["xy"][1])
        if math.hypot(b[0] - a[0], b[1] - a[1]) > 20:
            return False
        return any(math.hypot(tx[0] - e[0], tx[1] - e[1]) <= 4 for tx in by_layer[ln["layer"]] for e in (a, b))
    lines = [ln for ln in lines if not leader(ln)]
    # a symbol drawn twice (a proposed pole's double circle) is one point
    seen, uniq = set(), []
    for p in pts:
        la, lo = to_ll(p["x"] * unit, p["y"] * unit)
        k = (p["layer"], round(la * 2e5), round(lo * 2e5))  # about half a metre on the ground
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    pts = uniq

    def seg(layer):  # layer names as folder words ("CABLE_MAIN" -> "CABLE MAIN"), for the KMZ folder rules
        return re.sub(r"[_\-.]+", " ", layer).strip()
    out, unlabelled = [], 0
    for p in pts:
        name, rest = (p["name"], "") if p["name"] else split_id(label(p["x"], p["y"], p["layer"]))
        if not name and re.search(r"EQUIP|NODE|CLOSURE", p["layer"], re.I):  # a symbol that says nothing of its kind
            unlabelled += 1
            continue
        folder = p["layer"] + (f" / {p['block']}" if p["block"] else "")
        out.append({"name": name, "path": [seg(p["layer"])] + ([seg(p["block"])] if p["block"] else []), "folder": folder,
                    "desc": rest, "ext": p["ext"], "geom": "point", "coords": [to_ll(p["x"] * unit, p["y"] * unit)]})
    for ln in lines:
        text = line_label(ln)
        name, rest = split_id(text)
        out.append({"name": name, "path": [seg(ln["layer"])], "folder": ln["layer"], "desc": rest, "ext": line_ext(text),
                    "geom": "polygon" if ln["closed"] else "line",
                    "coords": [to_ll(x * unit, y * unit) for x, y in ln["xy"]]})
    if unlabelled:
        note += f"; {unlabelled} equipment symbol(s) with no ID / kind label skipped"
    notes = [note, f"Drawing: {len(pts)} points, {len(lines)} lines and areas read from layers "
                   + ", ".join(sorted({p['layer'] for p in pts} | {ln['layer'] for ln in lines})[:12])]
    return out, notes
