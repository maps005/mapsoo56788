"""Survey data import: CSV, Excel, KML/KMZ and GPX.

Imports never discard rows: records without usable coordinates are kept and
reported so the planner can correct them in the data tables.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Iterable

from .geo import LocalProjection, haversine, valid_coord
from .model import NODE_PREFIX, Cable, Design, Duct, Home, Node, Pole, Splitter, Vertex, all_ids, next_id

ALIASES = {
    "id": ["id", "pole id", "pole_id", "poleid", "home id", "home_id", "code", "ref", "name", "label", "tag"],
    "lat": ["lat", "latitude", "y", "northing_dd", "gps lat", "gps_lat"],
    "lon": ["lon", "lng", "long", "longitude", "x", "gps lon", "gps_lon", "gps long"],
    "coords": ["coordinates", "coords", "location", "gps", "lat,lon", "lat/long", "latlong"],
    "type": ["type", "pole type", "pole_type", "material"],
    "height_m": ["height", "height_m", "height (m)", "pole height"],
    "condition": ["condition", "state", "pole condition"],
    "status": ["status", "existing/proposed"],
    "notes": ["notes", "note", "remarks", "comment", "comments", "description"],
    "units": ["units", "unit count", "no. of units", "households", "hp", "hps", "homepasses", "viable hp", "viable hps"],
    "kind": ["kind", "category", "building type", "premise type", "nature of building", "nature of the building",
             "nature"],
    "acquired": ["acquired", "acquisition", "acquired?"],
    "field_type": ["green/brown field", "field", "green field / brown field"],
    "region": ["region"], "zone": ["zone"], "cluster": ["cluster"],
    "address": ["address", "street", "plot"],
    "name": ["name", "building", "building name", "estate", "customer", "bld_name_units", "bld name units",
             "bld_name", "bld name", "building name units", "premise name"],  # "name" only when ID has its own column
    "access_notes": ["access", "access notes", "access_notes", "restrictions"],
    "pole": ["pole", "on pole", "mounted on"],
    "ports": ["ports", "port count", "fat ports", "capacity"],
    "fat": ["fat", "fat id", "serving fat"],
}

NODE_KIND_WORDS = {  # explicit kind text -> node kind
    "POP": "POP", "OLT": "POP", "FAT": "FAT", "JB": "JB", "JUNCTION BOX": "JB", "PON": "PON",
    "SLACK": "SLACK", "SLACK LOOP": "SLACK", "ENCLOSURE": "ENCLOSURE", "SPLICE ENCLOSURE": "ENCLOSURE",
    "CLOSURE": "ENCLOSURE", "SPLICE CLOSURE": "ENCLOSURE", "PR_ENCLOSURE": "PR_ENCLOSURE", "PR ENCLOSURE": "PR_ENCLOSURE",
}
NODE_PREFIXES = [("POP", "POP"), ("FAT", "FAT"), ("JB", "JB"), ("PON", "PON"), ("SLACK", "SLACK"),
                 ("SC", "ENCLOSURE"), ("SE", "ENCLOSURE"), ("ENC", "ENCLOSURE"), ("SPLICE", "ENCLOSURE")]
STATUS_PREFIX = re.compile(r"^(PR|EX|EXISTING|PROPOSED)[\s_-]+", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _num(v) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _int_in(v) -> int | None:
    """Integer from a number or text such as '24HPs' / '24 units'."""
    n = _num(v)
    if n is not None:
        return int(n)
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m else None


def _status(v, default: str) -> str:
    t = _norm(v)
    if t.startswith(("ex", "old")):
        return "existing"
    if t.startswith(("pr", "new", "plan")):
        return "proposed"
    return default


def node_kind(text: str) -> str | None:
    """Node kind from explicit kind text or an ID such as 'FAT-03', 'PR FAT-03', 'SC-01'."""
    u = re.sub(r"\s+", " ", str(text or "").strip().upper())
    if u in NODE_KIND_WORDS:
        return NODE_KIND_WORDS[u]
    rest = STATUS_PREFIX.sub("", u)
    for p, k in NODE_PREFIXES:
        if rest.startswith(p):
            return k
    if re.match(r"^PR\d", u):  # "PR01" = PR enclosure
        return "PR_ENCLOSURE"
    return None


_kind_from_id = node_kind  # backwards-compatible name


def map_columns(headers: Iterable[str]) -> dict[str, str]:
    """Map our field names -> source column, by alias."""
    hs = {_norm(h): h for h in headers if h is not None}
    out = {}
    for field, names in ALIASES.items():
        for n in names:
            if n in hs and hs[n] not in out.values():
                out[field] = hs[n]
                break
    return out


def _has_position_columns(headers) -> bool:
    cols = map_columns(headers)
    return ("lat" in cols and "lon" in cols) or "coords" in cols


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _sheet_rows(rows: list[tuple]) -> list[dict]:
    """Data rows of one worksheet as dicts, keyed by the header row (title lines above it are skipped)."""
    if not rows:
        return []
    texts = [[str(c).strip() if c is not None else "" for c in r] for r in rows]
    # header row: the first of the top rows that names the position columns, else the first row with 2+ cells
    start = next((i for i, r in enumerate(texts[:20]) if _has_position_columns(r)),
                 next((i for i, r in enumerate(rows) if sum(c is not None for c in r) >= 2), 0))
    headers = [h or f"col{i}" for i, h in enumerate(texts[start])]
    return [dict(zip(headers, r)) for r in rows[start + 1:] if any(c is not None and str(c).strip() for c in r)]


def read_workbook(data: bytes) -> list[tuple[str, list[dict]]]:
    """Every worksheet of an Excel workbook: [(sheet name, rows)]."""
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return [(ws.title, _sheet_rows(list(ws.iter_rows(values_only=True)))) for ws in wb.worksheets]
    finally:
        wb.close()


def read_table(filename: str, data: bytes) -> list[dict]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        return next((rows for _, rows in read_workbook(data) if rows), [])
    text = _decode(data)
    lines = text.splitlines()
    # skip title lines above the header row
    start = next((i for i, ln in enumerate(lines[:20])
                  if _has_position_columns(re.split(r"[,;\t]", ln))), 0)
    body = "\n".join(lines[start:])
    try:
        dialect = csv.Sniffer().sniff(body[:4096], delimiters=",;\t") if body.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.DictReader(io.StringIO(body), dialect=dialect)
            if any((v or "").strip() for v in r.values() if isinstance(v, str))]


class Report:
    def __init__(self):
        self.added, self.updated, self.problems = 0, 0, []

    def dict(self):
        return {"added": self.added, "updated": self.updated, "problems": self.problems}


def _split_coords(text: str) -> tuple[float | None, float | None, str | None]:
    s = str(text or "").strip()
    tokens = [t for t in re.split(r"[;\s]+", s) if t]
    if len(tokens) >= 2:  # "-1.3 36.8", "-1,3 36,8", "-1.3; 36.8"
        return _num(tokens[0].rstrip(",")), _num(tokens[1]), None
    if s.count(",") == 1:  # "-1.3,36.8"
        a, b = s.split(",")
        return _num(a), _num(b), None
    if s:
        return None, None, f"coordinates '{s}' are ambiguous (use a space or ';' between latitude and longitude)"
    return None, None, None


def _coords(row: dict, cols: dict) -> tuple[float | None, float | None, str | None]:
    lat = _num(row.get(cols["lat"])) if "lat" in cols else None
    lon = _num(row.get(cols["lon"])) if "lon" in cols else None
    note = None
    if (lat is None or lon is None) and "coords" in cols:
        lat, lon, note = _split_coords(row.get(cols["coords"]))
    if lat is not None and lon is not None and abs(lat) > 90 >= abs(lon):
        lat, lon, note = lon, lat, "latitude/longitude looked swapped and were corrected"
    return lat, lon, note


def import_rows(d: Design, rows: list[dict], target: str, report: Report, default_status: str = "existing") -> None:
    if not rows:
        report.problems.append("No data rows were found in the file")
        return
    cols = map_columns(rows[0].keys())
    if "lat" not in cols and "coords" not in cols:
        report.problems.append(f"No latitude/longitude columns found. Columns: {', '.join(map(str, rows[0].keys()))}")
    ids = all_ids(d)
    coll = {"poles": d.poles, "homes": d.homes, "nodes": d.nodes}[target]
    parsed = [_coords(row, cols) for row in rows]
    # Swapped columns that still look valid (e.g. lat 36.8, lon -1.3): compare with the other points.
    good = [(la, lo) for la, lo, _ in parsed if valid_coord(la, lo)] + \
           [(x.lat, x.lon) for x in d.poles + d.homes + d.nodes if valid_coord(x.lat, x.lon)]

    step = max(1, len(good) // 400)  # a sample of the other points is enough for a majority vote

    def near(la, lo, skip):
        return sum(1 for j in range(0, len(good), step)
                   if j != skip and haversine(la, lo, *good[j]) < 50_000) * step

    if len(good) >= 2:
        k = -1
        for i, (la, lo, note) in enumerate(parsed):
            if not valid_coord(la, lo):
                continue
            k += 1
            swapped = near(lo, la, k) if valid_coord(lo, la) else 0
            # swap only when a clear majority of the other points agree with the swapped position
            if swapped > near(la, lo, k) and swapped > (len(good) - 1) / 2:
                parsed[i] = (lo, la, "latitude/longitude looked swapped and were corrected")
    seen: dict[str, int] = {}
    added_here: set[str] = set()
    matched = _match_rows_to_homes(d, rows, parsed, cols) if target == "homes" else {}
    new_rows: list[str] = []
    before_homes = [h.id for h in d.homes] if matched else []
    for n, (row, (lat, lon, note)) in enumerate(zip(rows, parsed), start=2):
        raw_id = str(row.get(cols.get("id"), "") or "").strip() if "id" in cols else ""
        filled = [str(v).strip().upper() for v in row.values() if v not in (None, "")]
        if lat is None and lon is None and (len(filled) <= 1 or "TOTAL" in filled or
                                            filled[0] in ("BUILDING TYPE", "MDU", "SDU", "BUSINESS UNITS", "COMMERCIAL")):
            continue  # section title, total or summary row of a list
        if note:
            report.problems.append(f"Row {n} ({raw_id or 'no id'}): {note}")
        if not valid_coord(lat, lon):
            given = "" if lat is None and lon is None else f" (given: {lat}, {lon})"
            report.problems.append(f"Row {n} ({raw_id or 'no id'}): missing or invalid coordinates{given} - "
                                   f"imported for correction")
            lat = lon = None
        fields = {k: row.get(c) for k, c in cols.items() if k not in ("id", "lat", "lon", "coords")}
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        status = _status(fields.get("status"), default_status)
        if target == "poles":
            obj = Pole(id=raw_id or next_id(ids, "P"), lat=lat, lon=lon, status=status)
            if "type" in fields: obj.type = str(fields["type"])
            if "height_m" in fields:
                obj.height_m = _num(fields["height_m"])
                if obj.height_m is None:
                    report.problems.append(f"Row {n} ({raw_id or 'no id'}): height '{fields['height_m']}' is not a number")
            if "condition" in fields: obj.condition = str(fields["condition"])
            if "notes" in fields: obj.notes = str(fields["notes"])
        elif target == "homes":
            obj = Home(id=raw_id or next_id(ids, "H"), lat=lat, lon=lon)
            units = _int_in(fields.get("units"))
            if units is not None:
                obj.units = units
            elif "units" in cols:  # a list with a homepass column: blank = not counted
                obj.units = 0
            kind = _norm(fields.get("kind", ""))
            obj.kind = "business" if any(w in kind for w in BUSINESS_WORDS) else \
                "mdu" if ("mdu" in kind or "apartment" in kind or "flat" in kind or obj.units > 1) else "home"
            for k in ("name", "address", "access_notes", "notes"):
                if k in fields: setattr(obj, k, str(fields[k]))
            if "fat" in fields: obj.fat = str(fields["fat"]).strip() or None
            obj.acquired = _norm(fields.get("acquired", "")) in ("acquired", "yes", "y", "true", "1")
            ft = _norm(fields.get("field_type", ""))
            obj.field_type = "green" if "green" in ft else "brown" if "brown" in ft else ""
            for k in ("region", "zone", "cluster"):  # fill empty project details from the list
                if fields.get(k) and not getattr(d.info, k):
                    setattr(d.info, k, str(fields[k]).strip().title())
            match = matched.get(n - 2)
            if match is not None:  # the same building already came from the KMZ: update it
                keep = match.id
                for k in ("units", "kind", "acquired", "field_type"):
                    setattr(match, k, getattr(obj, k))
                match.name = match.name or obj.name or raw_id
                if obj.address: match.address = obj.address
                report.updated += 1
                seen[raw_id] = n
                continue
            if matched:
                new_rows.append(f"row {n} ({obj.name or raw_id or 'no name'})")
        else:
            kind = node_kind(fields.get("kind", "")) or node_kind(raw_id) or "ENCLOSURE"
            obj = Node(id=raw_id or next_id(ids, NODE_PREFIX.get(kind, "N")), kind=kind, lat=lat, lon=lon, status=status)
            if "pole" in fields: obj.pole = str(fields["pole"]).strip()
            if "notes" in fields: obj.notes = str(fields["notes"])
            if "ports" in fields: obj.ports = _int_in(fields["ports"])
        added_here.add(obj.id)
        if raw_id and raw_id in seen:
            report.problems.append(f"Row {n}: ID {raw_id} also appears in row {seen[raw_id]} of this file - both kept, "
                                   f"please give one a new ID")
            coll.append(obj)
            report.added += 1
            continue
        if raw_id:
            seen[raw_id] = n
        existing = next((x for x in coll if x.id == raw_id), None) if raw_id else None
        if existing:
            coll[coll.index(existing)] = obj
            report.updated += 1
        else:
            coll.append(obj)
            ids.add(obj.id)
            report.added += 1

    if new_rows:
        report.problems.insert(0, f"{len(new_rows)} list row(s) had no premise on the map within {HOME_MATCH_M:g} m "
                                  f"and were added as new premises: " + ", ".join(new_rows[:15])
                               + (f" and {len(new_rows) - 15} more" if len(new_rows) > 15 else ""))
    if matched:
        used = {h.id for h in matched.values()}
        missing = [hid for hid in before_homes if hid not in used]
        if missing:
            report.problems.insert(0, f"{len(missing)} premise(s) on the map are not in the list (kept, check them): "
                                      + ", ".join(missing[:15]) + (f" and {len(missing) - 15} more" if len(missing) > 15 else ""))

# ---------------------------------------------------------------------------
# KML / KMZ / GPX
# ---------------------------------------------------------------------------
def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _kml_coords(text: str) -> list[tuple[float, float]]:
    pts = []
    for tok in re.sub(r"\s*,\s*", ",", text or "").split():
        p = tok.split(",")
        if len(p) >= 2:
            lon, lat = _num(p[0]), _num(p[1])
            if lat is not None and lon is not None:
                pts.append((lat, lon))
    return pts


def _clean_desc(html: str) -> str:
    """Plain text of a placemark description; for GIS exports (Layer / Feature ID / Remarks) only the remarks."""
    m = re.search(r"Remarks:\s*(.*?)</p>", html, re.I | re.S)
    if m:
        html = m.group(1)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"KML_STYLE\s*=\s*\S+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _safe_xml(data: bytes) -> ET.Element:
    """Parse KML/GPX, refusing DTDs (entity expansion / external entities)."""
    head = data[:2048].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise ValueError("The file contains a DTD/entity declaration, which is not allowed")
    return ET.fromstring(data)


MAX_KML_BYTES = 60 * 1024 * 1024


def parse_kml(data: bytes) -> list[dict]:
    """Placemarks as dicts: name, path (folder names), folder, desc, ext, geom ('point'|'line'|'polygon'), coords."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            kmls = [i for i in z.infolist() if i.filename.lower().endswith(".kml")]
            if not kmls:
                raise ValueError("The KMZ contains no .kml file")
            info = next((i for i in kmls if i.filename.lower() == "doc.kml"), kmls[0])
            if info.file_size > MAX_KML_BYTES:
                raise ValueError("The KML inside the KMZ is too large")
            with z.open(info) as fh:  # the size header can lie: never decompress more than the limit
                data = fh.read(MAX_KML_BYTES + 1)
            if len(data) > MAX_KML_BYTES:
                raise ValueError("The KML inside the KMZ is too large")
    root = _safe_xml(data)
    _strip_ns(root)
    out = []

    def walk(el, path):
        for ch in el:
            if ch.tag == "Document":
                walk(ch, path)
            elif ch.tag == "Folder":
                walk(ch, path + [(ch.findtext("name") or "").strip()])
            elif ch.tag == "Placemark":
                ext = {x.get("name"): (x.findtext("value") or "") for x in ch.iter("Data")}
                ext.update({x.get("name"): (x.text or "") for x in ch.iter("SimpleData")})
                base = {"name": (ch.findtext("name") or "").strip(), "path": path,
                        "folder": path[-1] if path else "", "desc": _clean_desc(ch.findtext("description") or ""),
                        "ext": ext}
                for geom, tag in (("point", "Point"), ("line", "LineString"), ("polygon", "Polygon")):
                    for g in ch.iter(tag):
                        coords = _kml_coords(g.findtext(".//coordinates") or "")
                        if coords:
                            out.append(base | {"geom": geom, "coords": coords})
    walk(root, [])
    return out


def parse_gpx(data: bytes) -> list[dict]:
    root = _safe_xml(data)
    _strip_ns(root)
    out = []

    def pt(el):
        lat, lon = _num(el.get("lat")), _num(el.get("lon"))
        return (lat, lon) if lat is not None and lon is not None else None

    for w in root.iter("wpt"):
        p = pt(w)
        if p:
            out.append({"name": (w.findtext("name") or "").strip(), "path": [], "folder": "",
                        "desc": (w.findtext("desc") or ""), "ext": {}, "geom": "point", "coords": [p]})
    for tag, ptag in (("trk", "trkpt"), ("rte", "rtept")):
        for t in root.iter(tag):
            pts = [p for p in (pt(e) for e in t.iter(ptag)) if p]
            if len(pts) >= 2:
                out.append({"name": (t.findtext("name") or "").strip(), "path": [], "folder": "", "desc": "",
                            "ext": {}, "geom": "line", "coords": pts})
    return out


# ---------------------------------------------------------------------------
# Folder-aware classification (e.g. POLES/KPW, FATS/FATs/INDOOR FATs, CABLES/PR FOC/12C ADSS FOC)
# ---------------------------------------------------------------------------
def _has(text: str, *words: str) -> bool:
    """Whole-word match in upper-case text."""
    return any(re.search(r"(?<![A-Z])" + re.escape(w) + r"(?![A-Z])", text) for w in words)


def classify(pm: dict) -> dict:
    """What a placemark is, from its ExtendedData, folder path and name: {'what': ...} or {'skip': reason}."""
    segs = [s.upper() for s in (pm.get("path") or ([pm["folder"]] if pm.get("folder") else []))]
    path = " / ".join(segs)
    name = pm["name"].upper()
    text = path + " / " + name
    ext = {str(k).lower(): v for k, v in (pm.get("ext") or {}).items()}
    status = None
    if ext.get("status") in ("existing", "proposed"):
        status = ext["status"]
    elif any(s == "EXISTING" or s.startswith("EXISTING ") or s.startswith("EX ") for s in segs) or \
            re.match(r"^(EX[\s_-]|EXISTING\b)", name):
        status = "existing"
    elif re.match(r"^PR[\s_-]", name) or any(s == "PR" or s.startswith("PR ") for s in segs):
        status = "proposed"

    g = pm["geom"]
    if g == "polygon":
        if _has(text, "BOUNDARY", "PROJECT AREA", "SCOPE"):
            return {"what": "boundary"}
        return {"skip": "area polygon (" + (pm.get("folder") or "no folder") + ")"}
    if g == "line":
        if _has(text, "TRUNKING", "CONDUIT") or ext.get("kind") in ("trunking", "conduit"):
            kind = ext.get("kind") if ext.get("kind") in ("trunking", "conduit") else                 "conduit" if _has(text, "CONDUIT") and not _has(text, "TRUNKING") else "trunking"
            return {"what": "duct", "kind": kind}
        m = re.search(r"(\d+)\s*C\b", name) or re.search(r"(\d+)\s*C\b", path)
        cores = _int_in(ext.get("cores")) or (int(m.group(1)) if m else None)
        if cores or _has(text, "CABLE", "CABLES", "FOC", "FIBRE", "FIBER", "ADSS"):
            cores = cores or 12
            kind = ext.get("kind") if ext.get("kind") in ("main", "spur", "drop") else \
                "drop" if _has(text, "DROP") else "main" if (_has(text, "MAIN", "FEEDER") or cores >= 48) else "spur"
            install = ext.get("install") if ext.get("install") in ("aerial", "underground") else \
                "underground" if _has(text, "UNDERGROUND", "UG") else "aerial"
            return {"what": "cable", "cores": cores, "kind": kind, "status": status, "install": install}
        return {"skip": "line that is not a cable"}

    # points ----------------------------------------------------------------
    ek = str(ext.get("kind", "")).upper()
    if ek in NODE_KIND_WORDS.values():  # exported by this tool
        return {"what": "node", "kind": ek, "status": status or "proposed", "ports": _int_in(ext.get("ports")),
                "notes": ext.get("notes", "")}
    if ek in ("HOME", "MDU", "BUSINESS"):
        return {"what": "home", "kind": ek.lower(), "units": _int_in(ext.get("units")), "fat": ext.get("fat") or None}
    if ext.get("stage") and ext.get("outputs"):
        return {"what": "splitter", "stage": 1 if str(ext["stage"]).strip() == "1" else 2,
                "outputs": _int_in(ext["outputs"]) or 8, "host": ext.get("node")}
    if re.search(r"CAB(LE|EL)\s*END|EXTEND|FUTURE", name):
        return {"what": "extend"}
    if _has(path, "INFO", "NOTE", "NOTES", "LABELS"):
        return {"skip": "information marker"}
    if not segs and len(name.split()) >= 4 and not re.search(r"\d", name.split()[0]):
        return {"what": "note", "text": pm["name"].strip()}  # a sentence at the top level is a note, not a feature
    if _has(path, "SLACK") or name.startswith("SLACK"):
        return {"what": "node", "kind": "SLACK", "status": status or "proposed"}
    # premises: the folder decides (a shop called "JUNCTION BUTCHERY" is not a junction box)
    if _has(path, *PREMISE_FOLDERS) or any(w in seg for seg in segs for w in ("INST", "RELIGIOUS", "LEARNING", "HEALTH")):
        if _has(text, "EMPTY PLOT", "EMPTY PLOTS", "VACANT"):
            return {"skip": "empty plot"}
        units = _units_in(name)
        business = _has(path, "COMMERCIAL", "COMMERC", "BUSINESS", "SHOPS", "GVT") or \
            any(w in seg for seg in segs for w in ("INST", "RELIGIOUS", "LEARNING", "HEALTH"))
        kind = "mdu" if _has(text, "MDU", "MDUS", "APARTMENT", "APARTMENTS") else \
            "business" if business else "mdu" if (units or 0) > 1 else "home"
        return {"what": "home", "kind": kind, "units": units}
    ratio = re.search(r"1\s*[X\*]\s*(\d+)", name)
    jb_folder = any(re.search(r"\bJB\b|JUNCTION BOX", seg) for seg in segs)
    if jb_folder or re.search(r"\bJB\b|JUNCTION BOX|\bBDB", name):  # a JB may carry its PON label: "BDB0025 PON A(1*8)"
        return {"what": "node", "kind": "JB", "status": status or _folder_status(segs) or "proposed",
                "notes": f"PON {_pon_label(name)}" if _pon_label(name) else ""}
    is_splitter = _has(path, "SPLITTER", "SPLITTERS") or (ratio and ("SPL" in name or name.startswith("PON")))
    if is_splitter:
        outputs = int(ratio.group(1)) if ratio else 8
        if _has(text, "PRIMARY", "1ST", "FIRST"):
            stage = 1
        elif _has(text, "SECONDARY", "2ND", "SECOND"):
            stage = 2
        elif name.startswith("PON") or (segs and segs[-1] == "PON"):
            stage = 1  # "PON A (1*8)": the first-stage splitter of PON A
        else:
            stage = 2 if outputs >= 16 or "SPL" in name else 1  # "SPL 1A(1*16)": a FAT splitter in PON A
        return {"what": "splitter", "outputs": outputs, "stage": stage, "host": None, "pon": _pon_label(name)}
    fat_folder = _has(path, "FAT", "FATS") and not _has(path, "POLYGON", "POLYGONS")
    if (_has(name, "FAT") and "SPL" not in name) or fat_folder:
        p = re.search(r"(\d+)\s*P\b", name) or re.search(r"(\d+)\s*P(?:ORTS?)?\b", path)
        note = "Indoor FAT" if _has(text, "INDOOR", "IND") else "Outdoor FAT" if _has(text, "OUTDOOR", "OTD") else ""
        return {"what": "node", "kind": "FAT", "status": status or _folder_status(segs) or "proposed",
                "ports": int(p.group(1)) if p else _int_in(ext.get("ports")), "notes": note}
    if _has(name, "PON") and "SPL" not in name and not ratio:
        return {"what": "node", "kind": "PON", "status": status or "proposed"}
    if _has(text, "CLOSURE", "ENCLOSURE", "ENCLOSURES", "SC", "SE", "ENC", "SPLICE", "JCL"):
        return {"what": "node", "kind": "ENCLOSURE", "status": status or _folder_status(segs) or "proposed"}
    if _has(text, "POP", "OLT"):
        return {"what": "node", "kind": "POP", "status": status or "existing"}
    if _has(text, "PON"):
        return {"what": "node", "kind": "PON", "status": status or "proposed"}
    pole_seg = next((seg for seg in reversed(segs) if re.search(r"\bPOLES?\b|^KP|^STRL|\bPL\b", seg)), None)
    if _has(path, "POLE", "POLES") or pole_seg:
        below = [x for x in (pm.get("path") or []) if x.upper() not in ("POLES", "POLE")]
        return {"what": "pole", "status": status or _folder_status(segs, new_words=NEW_POLE_WORDS) or "existing",
                "type": ext.get("type") or (below[-1] if below else "pole")}
    if _has(text, "EMPTY PLOT", "EMPTY PLOTS", "VACANT"):
        return {"skip": "empty plot"}
    t = _guess_point_target(pm)  # no folder hints: fall back to the name-based guess
    if t == "nodes":
        return {"what": "node", "kind": node_kind(pm["name"]) or "ENCLOSURE", "status": status or "proposed"}
    if t == "homes":
        return {"what": "home", "kind": "home", "units": _units_in(name)}
    return {"what": "pole", "status": status or "existing", "type": segs[-1] if segs else "pole"}


PREMISE_FOLDERS = ("HOME", "HOMES", "MDU", "MDUS", "SDU", "SDUS", "COMMERCIAL", "BUILDING", "BUILDINGS", "CUSTOMER",
                   "CUSTOMERS", "HOUSE", "HOUSES", "PREMISES", "BUSINESS", "SHOPS", "GVT")
NEW_POLE_WORDS = ("PR", "PROP", "PROPOSED", "NEW", "VSQ")  # "VSQ POLES": the client's own new poles


def _folder_status(segs: list[str], new_words=("PR", "PROP", "PROPOSED", "NEW")) -> str | None:
    """'existing' / 'proposed' from folder words such as 'EX ENC', '16P OUTDOOR PR FAT', 'VSQ POLES'."""
    words = {w for seg in segs for w in re.split(r"[\s_/-]+", seg)}
    if words & {"EX", "EXISTING"}:
        return "existing"
    if words & set(new_words):
        return "proposed"
    return None


def _units_in(name: str) -> int | None:
    """Homepasses written in a name: 'MDU 120(12HPs)', 'ASSEGAI APARTMENTS(50 UNITS)', 'FREMO HOSPITAL(1 UNIT)'."""
    u = re.search(r"(\d+)\s*-?\s*(?:HPS?|UNITS?|UNIT)\b", name.upper())
    return int(u.group(1)) if u else None


def _pon_label(name: str) -> str:
    """'A' from 'PON A (1*8)', 'DGS-BDB0029 PONC (1*8)' or 'SPL 1A(1*16)' style names ('' if none)."""
    u = name.upper()
    m = re.search(r"PON\s*([A-Z])\b", u) or re.search(r"\b([A-Z])\s*\(\s*1\s*[X\*]\s*8\s*\)", u)  # "BDB0020 H(1*8)"
    return m.group(1) if m else ""


def _key_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


HOME_MATCH_M = 15.0
BUSINESS_WORDS = ("business", "commercial", "commerc", "shop", "office", "religious", "church", "mosque", "learning",
                  "school", "health", "clinic", "hospital", "gover", "govt", "gvt", "institution")


def _match_rows_to_homes(d: Design, rows: list[dict], parsed: list[tuple], cols: dict) -> dict[int, Home]:
    """One-to-one matching of list rows to premises already on the map (e.g. from the KMZ): nearest pairs first,
    within HOME_MATCH_M; an equal name only breaks ties. Each premise is updated by at most one row, so two
    neighbouring buildings in the list can never overwrite each other."""
    homes = [h for h in d.homes if valid_coord(h.lat, h.lon)]
    if not homes:
        return {}
    cell = 0.00025  # ~28 m grid
    grid: dict[tuple, list[Home]] = defaultdict(list)
    for h in homes:
        grid[(int(h.lat / cell), int(h.lon / cell))].append(h)
    pairs = []
    for i, (row, (lat, lon, _)) in enumerate(zip(rows, parsed)):
        if not valid_coord(lat, lon):
            continue
        label = _key_name(str(row.get(cols.get("name"), "") or row.get(cols.get("id"), "") or ""))
        gx, gy = int(lat / cell), int(lon / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for h in grid.get((gx + dx, gy + dy), ()):
                    dist = haversine(lat, lon, h.lat, h.lon)
                    if dist <= HOME_MATCH_M:
                        same = bool(label) and label in (_key_name(h.id), _key_name(h.name))
                        pairs.append((dist - (HOME_MATCH_M if same else 0), i, h))
    out, taken = {}, set()
    for _, i, h in sorted(pairs, key=lambda t: t[0]):
        if i not in out and h.id not in taken:
            out[i] = h
            taken.add(h.id)
    return out


def _same_home(d: Design, h: Home, skip: set[str] = frozenset()) -> Home | None:
    """An existing home that is the same building: same name, or (without a name match) within 15 m.
    Homes in skip (added earlier from the same file) are separate rows, never the same building."""
    key = _key_name(h.id)
    homes = [x for x in d.homes if x.id not in skip]
    for x in homes:
        if key and key in (_key_name(x.id), _key_name(x.name)):
            return x
    if valid_coord(h.lat, h.lon):
        near = [(haversine(h.lat, h.lon, x.lat, x.lon), x) for x in homes if valid_coord(x.lat, x.lon)]
        near = [t for t in near if t[0] <= 15]
        if near:
            return min(near, key=lambda t: t[0])[1]
    return None


def _guess_point_target(pm: dict) -> str:
    name = pm["name"].upper()
    text = (pm.get("folder", "") + " " + pm["name"]).lower()
    if re.search(r"POLE|(?<![A-Z])PL[\s_-]*\d", name) or re.match(r"^P\d", name):
        return "poles"
    if node_kind(pm["name"]):
        return "nodes"
    if any(w in text for w in ("home", "house", "mdu", "building", "apartment", "customer", "hp")):
        return "homes"
    return "poles"


# preference when several pieces of equipment share one location
SITE_PRIORITY = {"POP": 0, "ENCLOSURE": 1, "PON": 2, "JB": 3, "FAT": 4, "PR_ENCLOSURE": 5, "SLACK": 6}


def nearest_pole(d: Design, lat: float, lon: float, tol_m: float, beside_m: float = 2.5):
    """Nearest pole within tol_m; a proposed pole planted beside an existing one (within beside_m) wins."""
    near = sorted(((haversine(lat, lon, p.lat, p.lon), i, p) for i, p in enumerate(d.poles)
                   if valid_coord(p.lat, p.lon)), key=lambda t: (t[0], t[1]))
    near = [(dist, p) for dist, _, p in near if dist <= tol_m]
    if not near:
        return None
    first = near[0][1]
    if first.status == "existing":
        for _, p in near[1:]:
            if p.status == "proposed" and haversine(first.lat, first.lon, p.lat, p.lon) <= beside_m:
                return p
    return first


def snap(d: Design, lat: float, lon: float, tol_m: float = 3.0, pole_tol_m: float = 5.0,
         slack_tol_m: float = 10.0) -> Vertex:
    """Attach a route point to the equipment and/or pole it was drawn on.

    The drawn coordinates are kept, so measured lengths match the source (e.g. Google Earth).
    """
    v = Vertex(lat=lat, lon=lon)
    cands = []
    for n in d.nodes:
        if not valid_coord(n.lat, n.lon):
            continue
        dist = haversine(lat, lon, n.lat, n.lon)
        if dist <= (slack_tol_m if n.kind == "SLACK" else tol_m):
            rank = SITE_PRIORITY.get(n.kind, 9) + (0.5 if n.status == "existing" and n.kind == "ENCLOSURE" else 0)
            cands.append((rank, dist, n))
    pole = nearest_pole(d, lat, lon, pole_tol_m)
    if pole:
        v.pole = pole.id
    if cands:
        n = min(cands, key=lambda c: (c[0], c[1]))[2]
        v.node = n.id
        if n.pole:
            v.pole = n.pole
    return v


def add_passed_poles(d: Design, path: list[Vertex], tol_m: float = 5.0) -> list[Vertex]:
    """Insert poles that a straight section passes without a drawn route point on them."""
    used = {v.pole for v in path if v.pole}
    out = [path[0]]
    for a, b in zip(path, path[1:]):
        proj = LocalProjection(a.lat, a.lon)
        bx, by = proj.xy(b.lat, b.lon)
        seg2 = bx * bx + by * by
        found = []
        for p in d.poles:
            if p.id in used or not valid_coord(p.lat, p.lon) or seg2 == 0:
                continue
            px, py = proj.xy(p.lat, p.lon)
            t = (px * bx + py * by) / seg2
            if not 0.05 < t < 0.95:
                continue
            off = ((px - t * bx) ** 2 + (py - t * by) ** 2) ** 0.5
            if off <= tol_m and min(haversine(p.lat, p.lon, a.lat, a.lon), haversine(p.lat, p.lon, b.lat, b.lon)) > tol_m:
                found.append((t, p))
        for t, p in sorted(found, key=lambda x: x[0]):
            out.append(Vertex(lat=a.lat + t * (b.lat - a.lat), lon=a.lon + t * (b.lon - a.lon), pole=p.id))
            used.add(p.id)
        out.append(b)
    return out


def _dedupe_path(path: list[Vertex], min_m: float = 0.5) -> list[Vertex]:
    """Drop repeated points (same place, or the same pole/equipment twice in a row)."""
    out: list[Vertex] = []
    for v in path:
        if out:
            p = out[-1]
            same_site = (v.node and v.node == p.node) or (v.pole and v.pole == p.pole and not (v.node or p.node))
            if same_site or haversine(p.lat, p.lon, v.lat, v.lon) < min_m:
                p.node, p.pole = p.node or v.node, p.pole or v.pole
                p.crossing = p.crossing or v.crossing
                continue
        out.append(v)
    return out


def import_placemarks(d: Design, pms: list[dict], target: str, report: Report, default_status: str) -> None:
    if target in ("poles", "homes", "nodes"):  # user forced every point to one type
        rows = [{"id": p["name"], "lat": p["coords"][0][0], "lon": p["coords"][0][1], "notes": p["desc"], **p["ext"]}
                for p in pms if p["geom"] == "point"]
        keys = sorted({k for r in rows for k in r})
        import_rows(d, [{k: r.get(k) for k in keys} for r in rows], target, report, default_status)
        return

    ids = all_ids(d)
    before = set(ids)
    renamed = 0
    counts: dict[str, int] = defaultdict(int)
    skipped: dict[str, int] = defaultdict(int)

    repeated = Counter(pm["name"].strip() for pm in pms if pm["name"].strip())
    seq: dict[str, int] = defaultdict(int)

    def uid(name: str, prefix: str) -> str:
        nonlocal renamed
        name = name.strip()
        if name and name in before:
            renamed += 1
        if name and repeated.get(name, 0) > 1:  # several placemarks share a name ("Slack", "SDU"): number them
            while True:
                seq[name] += 1
                cand = f"{name} {seq[name]:02d}"
                if cand not in ids:
                    break
            ids.add(cand)
            return cand
        i = name if name and name not in ids else next_id(ids, prefix)
        ids.add(i)
        return i

    def ext_of(pm):
        return {str(k).lower(): v for k, v in (pm.get("ext") or {}).items()}

    classified = [(pm, classify(pm)) for pm in pms]
    # cables in a folder without a status take the status of cables with the same naming (DGS-CBL...)
    prefix = lambda n: re.sub(r"[\d\s]+$", "", n.strip().upper())[:12]  # noqa: E731
    named_proposed = {prefix(pm["name"]) for pm, c in classified if c.get("what") == "cable" and c.get("status") == "proposed"}
    named_proposed.discard("")
    for pm, c in classified:
        if c.get("what") == "cable" and c.get("status") is None and prefix(pm["name"]) in named_proposed:
            c["status"] = "proposed"
    seen_poles: dict[str, tuple[float, float]] = {}
    has_existing_cable_folder = any(c.get("what") == "cable" and c.get("status") == "existing" and
                                    any(s.upper().startswith("EXISTING") for s in pm.get("path") or [])
                                    for pm, c in classified)
    # 1) poles and equipment first, so that cables and splitters can attach to them
    for pm, c in classified:
        e = ext_of(pm)
        if c.get("what") == "pole":
            lat, lon = pm["coords"][0]
            key = pm["name"].strip().upper()
            if key in seen_poles and haversine(lat, lon, *seen_poles[key]) <= 2:
                skipped["duplicate pole placemark"] += 1  # the same pole drawn twice
                continue
            seen_poles[key] = (lat, lon)
            d.poles.append(Pole(id=uid(pm["name"], "P"), lat=lat, lon=lon, type=c["type"], status=c["status"],
                                height_m=_num(e.get("height_m")), condition=e.get("condition", ""),
                                notes=(e.get("notes") or pm["desc"])[:200]))
            counts["poles"] += 1
        elif c.get("what") == "node":
            lat, lon = pm["coords"][0]
            d.nodes.append(Node(id=uid(pm["name"], NODE_PREFIX.get(c["kind"], "N")), kind=c["kind"], lat=lat,
                                lon=lon, status=c["status"], ports=c.get("ports"), pole=e.get("pole") or None,
                                notes=" ".join(x for x in (c.get("notes", ""), pm["desc"][:200]) if x)))
            counts[c["kind"]] += 1
    pole_ids = {p.id for p in d.poles}
    for n in d.nodes:  # mount equipment on the pole it stands at
        if n.pole and n.pole not in pole_ids:
            n.pole = None
        if n.pole is None and n.kind != "SLACK" and valid_coord(n.lat, n.lon):
            best = nearest_pole(d, n.lat, n.lon, 3.0)
            if best:
                n.pole = best.id

    for pm, c in classified:
        what = c.get("what")
        e = ext_of(pm)
        if what == "splitter":
            lat, lon = pm["coords"][0]
            host = d.node(c["host"]) if c.get("host") else None
            if host is None and c["stage"] == 1 and c.get("pon"):  # "PON A (1*8)" lives in the JB labelled PON A
                tag = "PON" + c["pon"]
                jbs = [n for n in d.nodes if n.kind in ("JB", "PON") and tag in re.sub(r"\s+", "", (n.notes + " " + n.id).upper())
                       and valid_coord(n.lat, n.lon) and haversine(lat, lon, n.lat, n.lon) <= 60]
                host = min(jbs, key=lambda n: haversine(lat, lon, n.lat, n.lon)) if jbs else None
            if host is None:
                prefer = ("FAT", "ENCLOSURE", "JB", "PON", "POP") if c["stage"] == 2 else \
                    ("ENCLOSURE", "PON", "POP", "JB", "FAT")
                near = [(prefer.index(n.kind), haversine(lat, lon, n.lat, n.lon), n) for n in d.nodes
                        if n.kind in prefer and valid_coord(n.lat, n.lon) and haversine(lat, lon, n.lat, n.lon) <= 15]
                if not near:
                    report.problems.append(f"Splitter '{pm['name']}' is not within 15 m of a closure or FAT - not imported")
                    continue
                host = min(near, key=lambda t: (t[1] > 5, t[0], t[1]))[2]
            parts = [p.strip() for p in re.split(r"\s*&\s*|\s+and\s+", pm["name"]) if p.strip()]
            if len(parts) > 1:  # "1X8 SPL 1A & 2A": two splitters in one placemark
                prefix = re.match(r"(.*?)(\S+)$", parts[0]).group(1)
                names = [parts[0]] + [p if " " in p else prefix + p for p in parts[1:]]
            else:
                names = [pm["name"]]
            for nm in names:
                d.splitters.append(Splitter(id=uid(nm, f"S{c['stage']}-"), node=host.id, stage=c["stage"],
                                            outputs=c["outputs"]))
                counts[f"stage-{c['stage']} splitters"] += 1
        elif what == "home":
            lat, lon = pm["coords"][0]
            units = c["units"]
            if units is None:
                units = 1 if c["kind"] == "home" else 0
                if c["kind"] != "home":
                    report.problems.append(f"'{pm['name']}': homepass count not in the name - counted as 0, "
                                           f"please enter it (or import the home list)")
            d.homes.append(Home(id=uid(pm["name"], "H"), lat=lat, lon=lon, kind=c["kind"], units=units,
                                name=e.get("name") or pm["name"], address=e.get("address", ""),
                                fat=c.get("fat"), notes=pm["desc"][:200]))
            counts["homes"] += 1
        elif what == "note":
            if "INTERCEPT" in c["text"].upper() and not d.info.interception:
                d.info.interception = c["text"][:300]
            report.problems.append(f"Note in the file (not a feature): '{c['text'][:120]}'")
        elif what == "extend":
            d.info.extend_to.append(list(pm["coords"][0]))
            counts["backbone extension points"] += 1
        elif what == "boundary" and not d.info.boundary:
            d.info.boundary = [[lat, lon] for lat, lon in pm["coords"]]
            counts["boundary"] += 1
        elif what == "duct":
            d.ducts.append(Duct(id=uid(pm["name"], "D"), kind=c["kind"],
                                path=[Vertex(lat=lat, lon=lon) for lat, lon in pm["coords"]], notes=pm["desc"][:200]))
            counts[f"{c['kind']} routes"] += 1
        elif what == "cable":
            raw = [snap(d, lat, lon) for lat, lon in pm["coords"]]
            for i in (int(x) for x in re.findall(r"\d+", e.get("crossings", "")) if int(x) < len(raw)):
                raw[i].crossing = True
            path = _dedupe_path(add_passed_poles(d, _dedupe_path(raw)))
            if len(path) < 2:
                report.problems.append(f"Cable '{pm['name']}' has fewer than 2 distinct points - not imported")
                continue
            name = pm["name"].strip()
            own = re.fullmatch(r"(.+?)\s+\d+\s*C", name)  # "C001 48C" as exported by this tool
            if own and e.get("cores"):
                name = own.group(1)
            generic = re.fullmatch(r"\d+\s*C", name, re.I)
            cid = uid("" if generic else name, "C")
            # a file that keeps existing cables in their own folder: every other cable is proposed
            status = c["status"] or ("proposed" if has_existing_cable_folder else default_status)
            d.cables.append(Cable(id=cid, kind=c["kind"], cores=c["cores"], path=path, status=status,
                                  install=c["install"], from_node=path[0].node, to_node=path[-1].node,
                                  notes=f"KML: {pm['name']}" if cid != name else ""))
            counts[f"{status} {c['cores']}C cables"] += 1
        elif "skip" in c:
            skipped[c["skip"]] += 1
    # FATs inside buildings are often drawn a few metres from the cable that serves them
    on_cable = {v.node for c in d.cables for v in c.path if v.node}
    for n in d.nodes:
        if n.kind != "FAT" or n.id in on_cable or not valid_coord(n.lat, n.lon):
            continue
        best = min(((haversine(n.lat, n.lon, v.lat, v.lon), c, i) for c in d.cables if c.status == "proposed"
                    for i, v in enumerate(c.path) if not v.node), default=None, key=lambda t: t[0])
        if best and best[0] <= 10:
            _, c, i = best
            c.path[i].node = n.id
            if i == 0:
                c.from_node = n.id
            elif i == len(c.path) - 1:
                c.to_node = n.id
            report.problems.append(f"{n.id} attached to cable {c.id} ({best[0]:.0f} m from the drawn route)")
    report.added += sum(counts.values())
    report.problems.insert(0, "Imported: " + (", ".join(f"{v} {k}" for k, v in counts.items()) or "nothing"))
    if skipped:
        report.problems.insert(1, "Not imported: " + ", ".join(f"{v} {k}" for k, v in skipped.items()))
    if renamed:
        report.problems.insert(1, f"{renamed} feature name(s) already existed in the project and were imported again "
                                  f"with new IDs - check you did not import the same file twice")


MAX_KMZ_PHOTO_BYTES = 15 * 1024 * 1024


def extract_kmz_photos(data: bytes, limit: int = 200) -> list[tuple[str, str, bytes]]:
    """Photos embedded in a KMZ and the placemark that shows them: [(placemark name, extension, bytes)]."""
    if data[:2] != b"PK":
        return []
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = {i.filename: i for i in z.infolist()}
        kml_info = next((i for i in z.infolist() if i.filename.lower() == "doc.kml"),
                        next((i for i in z.infolist() if i.filename.lower().endswith(".kml")), None))
        if kml_info is None or kml_info.file_size > MAX_KML_BYTES:
            return []
        with z.open(kml_info) as fh:
            kml = fh.read(MAX_KML_BYTES + 1).decode("utf-8", "replace")
        for pm in re.finditer(r"<Placemark\b.*?</Placemark>", kml, re.S):
            block = pm.group()
            nm = re.search(r"<name>(.*?)</name>", block, re.S)
            for ref in re.findall(r"(files/[^\"'<> ]+\.(?:jpe?g|png))", block, re.I):
                info = names.get(ref)
                if info is None or info.file_size > MAX_KMZ_PHOTO_BYTES:
                    continue
                with z.open(info) as fh:
                    blob = fh.read(MAX_KMZ_PHOTO_BYTES + 1)
                if len(blob) <= MAX_KMZ_PHOTO_BYTES:
                    out.append(((nm.group(1).strip() if nm else ""), ref.rsplit(".", 1)[-1].lower(), blob))
                if len(out) >= limit:
                    return out
    return out


# ---------------------------------------------------------------------------
# Workbooks with several sheets: poles, premises, equipment, splitters and cables
# ---------------------------------------------------------------------------
SKIP_SHEETS = ("instruction", "read me", "readme", "how to", "summary", "material", "fibre core", "fiber core",
               "connection", "adjustment", "boq", "bom", "rules")
SHEET_WORDS = [("splitter", "splitters"), ("cable", "cables"), ("route", "cables"), ("pole", "poles"),
               ("equipment", "nodes"), ("node", "nodes"), ("fat", "nodes"), ("closure", "nodes"),
               ("enclosure", "nodes"), ("device", "nodes"), ("home", "homes"), ("premise", "homes"),
               ("building", "homes"), ("mdu", "homes"), ("house", "homes"), ("customer", "homes"), ("hp", "homes")]
CABLE_ALIASES = {
    "id": ["id", "cable", "cable id", "cable_id", "name"],
    "kind": ["kind", "type", "cable type", "function"],
    "cores": ["cores", "core", "fibres", "fibers", "core count", "size"],
    "from": ["from", "from node", "from_node", "start", "a end"],
    "to": ["to", "to node", "to_node", "end", "b end"],
    "install": ["install", "installation", "placement", "aerial/underground"],
    "status": ["status", "existing/proposed"],
    "path": ["path", "route", "via", "poles", "via poles", "route poles", "pole route"],
    "notes": ["notes", "note", "remarks", "comment", "comments"],
    "points": ["path coordinates", "route coordinates", "coordinates", "path points"],
}
SPLITTER_ALIASES = {"id": ["id", "splitter", "splitter id"], "node": ["node", "at", "location", "fat", "pon"],
                    "stage": ["stage", "level"], "outputs": ["outputs", "ratio", "ports", "split"]}


def _cols(headers, aliases: dict[str, list[str]]) -> dict[str, str]:
    hs = {_norm(h): h for h in headers if h is not None}
    return {f: next(hs[n] for n in names if n in hs) for f, names in aliases.items() if any(n in hs for n in names)}


def guess_target(sheet: str, rows: list[dict]) -> str | None:
    """What the rows of a sheet / CSV are: poles, homes, nodes, splitters or cables (None = skip)."""
    name = _norm(sheet)
    if any(w in name for w in SKIP_SHEETS):
        return None
    for word, target in SHEET_WORDS:
        if re.search(rf"\b{word}", name):
            return target
    if not rows:
        return None
    heads = {_norm(h) for h in rows[0]}
    if {"from", "to"} <= heads or heads & {"cores", "via", "path"}:
        return "cables"
    if not _has_position_columns(rows[0].keys()):
        return None
    cols = map_columns(rows[0].keys())
    if "units" in cols or "acquired" in cols or "name" in cols:
        return "homes"
    if "height_m" in cols or "condition" in cols:
        return "poles"
    col = cols.get("kind") or cols.get("id")
    vals = [str(r.get(col) or "") for r in rows[:50]] if col else []
    if vals and sum(node_kind(v) is not None for v in vals) > len(vals) / 2:
        return "nodes"
    return None


def import_cable_rows(d: Design, rows: list[dict], report: Report, default_status: str) -> None:
    """Cables given as rows: ID, kind, cores, from, to, path (pole / equipment IDs in order)."""
    cols = _cols(rows[0].keys(), CABLE_ALIASES)
    if "path" not in cols and not {"from", "to"} <= set(cols):
        report.problems.append("Cables: give a 'path' column (pole / equipment IDs in order) or 'from' and 'to' columns")
        return
    ids = all_ids(d)
    for n, row in enumerate(rows, start=2):
        get = lambda k: str(row.get(cols[k], "") or "").strip() if k in cols else ""  # noqa: E731
        cid = get("id")
        tokens = [t.strip() for t in re.split(r"\s*(?:->|>|,|;|\|)\s*", get("path")) if t.strip()]
        a, b = get("from"), get("to")
        # optional 'lat,lon; lat,lon; ...' column, one pair per path point: gives bends that are not poles
        pts = [p.split(",") for p in get("points").split(";") if p.strip()]
        pts = [(_num(p[0]), _num(p[1])) if len(p) == 2 else (None, None) for p in pts]
        if pts and not tokens:
            tokens = [""] * len(pts)
        elif len(pts) != len(tokens):  # no usable coordinates: the path is IDs, closed by from / to
            pts = []
            if a and (not tokens or tokens[0] != a):
                tokens.insert(0, a)
            if b and (not tokens or tokens[-1] != b):
                tokens.append(b)
        if len(tokens) < 2:
            report.problems.append(f"Cables row {n} ({cid or 'no id'}): needs at least two points (from / to / path)")
            continue
        pts = pts or [(None, None)] * len(tokens)
        exact = any(valid_coord(la, lo) for la, lo in pts)  # one vertex per listed point, at its coordinates
        path, missing = [], []
        for t, (la, lo) in zip(tokens, pts):
            name, _, at = (x.strip() for x in t.partition("@"))  # "FAT-01 @ P003" = equipment on a pole
            node = d.node(name) if name and name != "pt" else None
            pole = d.pole(at or ("" if node else name)) if (at or (name and name != "pt" and not node)) else None
            if (name and name != "pt" and not node and (at or not pole)) or (at and not pole):
                missing.append(t)
                continue
            ref = node or pole
            if ref is None:
                if not valid_coord(la, lo):
                    missing.append(t or "point without coordinates")
                    continue
                path.append(Vertex(lat=la, lon=lo))
                continue
            pole_id = pole.id if pole else node.pole
            if valid_coord(la, lo):
                lat, lon = la, lo
            elif ref.lat is not None and ref.lon is not None:
                lat, lon = ref.lat, ref.lon
            else:
                missing.append(f"{t} (no coordinates)")
                continue
            if not exact and path and pole_id and path[-1].pole == pole_id:
                if node and not path[-1].node:
                    path[-1].node = node.id  # hand-typed list: equipment on the pole just listed
                continue
            path.append(Vertex(lat=lat, lon=lon, node=node.id if node else None, pole=pole_id))
        if missing:
            report.problems.append(f"Cables row {n} ({cid or 'no id'}): unknown point(s) {', '.join(missing)} - "
                                   f"import the poles and equipment first; cable skipped")
            continue
        cores = _int_in(get("cores")) or 12
        kind_t, inst = _norm(get("kind")), _norm(get("install"))
        kind = next((k for k in ("main", "spur", "drop") if k in kind_t), None) or \
            ("main" if "feeder" in kind_t or "backbone" in kind_t or cores >= 48 else "drop" if cores <= 2 else "spur")
        cable = Cable(id=cid or next_id(ids, "CB"), kind=kind, cores=cores, status=_status(get("status"), default_status),
                      install="underground" if ("under" in inst or "duct" in inst) else "aerial",
                      from_node=path[0].node or (a if d.node(a) else None),
                      to_node=path[-1].node or (b if d.node(b) else None), path=path, notes=get("notes"))
        old = d.cable(cable.id) if cid else None
        if old is not None:
            d.cables[d.cables.index(old)] = cable
            report.updated += 1
        else:
            d.cables.append(cable)
            ids.add(cable.id)
            report.added += 1


def import_splitter_rows(d: Design, rows: list[dict], report: Report) -> None:
    cols = _cols(rows[0].keys(), SPLITTER_ALIASES)
    ids = all_ids(d)
    for n, row in enumerate(rows, start=2):
        get = lambda k: str(row.get(cols[k], "") or "").strip() if k in cols else ""  # noqa: E731
        node = d.node(get("node"))
        if node is None:
            report.problems.append(f"Splitters row {n}: equipment '{get('node')}' not found - skipped")
            continue
        out = re.findall(r"\d+", get("outputs"))
        stage = _int_in(get("stage")) or (1 if node.kind == "PON" else 2)
        sp = Splitter(id=get("id") or next_id(ids, "SP"), node=node.id, stage=1 if stage == 1 else 2,
                      outputs=int(out[-1]) if out else (d.rules.default_pon_split if stage == 1 else d.rules.default_fat_split))
        old = d.splitter(sp.id)
        if old is not None:
            d.splitters[d.splitters.index(old)] = sp
            report.updated += 1
        else:
            d.splitters.append(sp)
            ids.add(sp.id)
            report.added += 1


ORDER = ("poles", "nodes", "homes", "splitters", "cables")  # splitters and cables refer to the others


def import_tables(d: Design, sheets: list[tuple[str, list[dict]]], target: str, report: Report, status: str) -> None:
    """Import one or more tables; target 'auto' decides per sheet from its name and columns."""
    jobs = []
    for name, rows in sheets:
        t = target if target in ORDER else guess_target(name, rows)
        if t is None:
            if not any(w in _norm(name) for w in SKIP_SHEETS):
                report.problems.append(f"Sheet '{name}' skipped: could not tell what its rows are. Name the sheet "
                                       f"Poles, Homes, Equipment, Splitters or Cables, or choose 'Rows are'.")
            continue
        jobs.append((ORDER.index(t), name, t, rows))
        if target in ORDER:
            break  # an explicit choice applies to the first sheet with data
    if not jobs:
        raise ValueError("No sheet could be imported. Use the Excel template, or choose what the rows are.")
    notes = []
    for _, name, t, rows in sorted(jobs, key=lambda j: j[0]):
        added, updated = report.added, report.updated
        if t == "cables":
            import_cable_rows(d, rows, report, status)
        elif t == "splitters":
            import_splitter_rows(d, rows, report)
        else:
            import_rows(d, rows, t, report, status)
        notes.append(f"Sheet '{name}' as {t}: {report.added - added} added, {report.updated - updated} updated")
    if len(sheets) > 1:
        report.problems[:0] = notes


def import_file(d: Design, filename: str, data: bytes, target: str = "auto", status: str = "existing") -> dict:
    report = Report()
    low = filename.lower()
    if target == "splitters" and not low.endswith((".xlsx", ".xlsm", ".csv", ".txt")):
        raise ValueError("Splitters can only be imported from Excel or CSV")
    if low.endswith((".kml", ".kmz")):
        import_placemarks(d, parse_kml(data), target, report, status)
    elif low.endswith(".gpx"):
        import_placemarks(d, parse_gpx(data), target, report, status)
    elif low.endswith((".xlsx", ".xlsm")):
        sheets = [(n, r) for n, r in read_workbook(data) if r]
        if not sheets:
            raise ValueError("The workbook has no data rows")
        import_tables(d, sheets, target, report, status)
    elif low.endswith((".csv", ".txt")):
        rows = read_table(filename, data)
        if not rows:
            raise ValueError("No data rows were found in the file")
        t = target if target in ORDER else guess_target(filename.rsplit(".", 1)[0], rows)
        if t is None:
            raise ValueError("Could not tell what the rows are: choose poles, homes, equipment or cables under 'Rows are'")
        import_tables(d, [(filename, rows)], t, report, status)
    else:
        raise ValueError(f"Unsupported file type: {filename}")
    return report.dict()


# ---------------------------------------------------------------------------
# Price lists: update catalogue rates from a supplier / company price list or BOQ template
# ---------------------------------------------------------------------------
def _desc_key(s) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def import_price_list(d: Design, data: bytes) -> dict:
    """Read every sheet; wherever a header row names a description and a price column, take the rows below it.
    Items are matched to the catalogue by description; known company items keep their codes, others are added."""
    from openpyxl import load_workbook
    from .model import DEFAULT_MATERIALS, Material
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    known = {_desc_key(m.description): m for m in d.materials}
    company = {_desc_key(m.description): m for m in DEFAULT_MATERIALS}
    codes = {m.code for m in d.materials}
    seen, out = set(), {"updated": [], "added": [], "unchanged": 0, "problems": []}
    for ws in wb.worksheets:
        cols = None
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip().lower() if c is not None else "" for c in row]
            desc_col = next((k for k, c in enumerate(cells) if "description" in c), None)
            price_col = next((k for k, c in enumerate(cells) if "price" in c or c in ("rate", "unit rate")), None)
            if desc_col is not None and price_col is not None:  # a header row
                cols = {"desc": desc_col, "price": price_col,
                        "unit": next((k for k, c in enumerate(cells) if c in ("uom", "unit", "units")), None),
                        "cat": next((k for k, c in enumerate(cells) if c in ("item", "category", "group")), None)}
                continue
            if cols is None:
                continue
            get = lambda k: row[cols[k]] if cols[k] is not None and cols[k] < len(row) else None  # noqa: E731
            desc, price = get("desc"), _num(get("price"))
            if not desc or not isinstance(desc, str) or price is None:
                continue
            key = _desc_key(desc)
            if key in seen:
                continue
            seen.add(key)
            unit = str(get("unit") or "").strip()
            m = known.get(key)
            if m is not None:
                if m.rate != price or (unit and m.unit != unit and m.unit.upper() == "EA"):
                    out["updated"].append(f"{m.code}: {m.rate:g} -> {price:g}")
                    m.rate = price
                else:
                    out["unchanged"] += 1
                continue
            base = company.get(key)
            code = base.code if base and base.code not in codes else None
            if code is None:
                stem = "".join(ch if ch.isalnum() else "-" for ch in desc.upper()).strip("-")[:18].strip("-") or "ITEM"
                code, k = stem, 1
                while code in codes:
                    k += 1
                    code = f"{stem}-{k}"
            mat = Material(code=code, description=desc.strip(), unit=unit or (base.unit if base else "PCS"), rate=price,
                           category=(base.category if base else str(get("cat") or "General").strip() or "General"))
            d.materials.append(mat)
            codes.add(code)
            known[key] = mat
            out["added"].append(f"{code} ({mat.description}) at {price:g}")
    if not seen:
        out["problems"].append("No price list found: the file needs a header row with a description and a price column")
    return out
