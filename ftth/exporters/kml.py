"""HLD export to KML / KMZ for Google Earth."""
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from .. import calc
from ..geo import valid_coord
from ..model import Design
from .common import KIND_COLOURS, NODE_LABEL, Stamp, clean


def _kml_colour(hex_: str, alpha: str = "ff") -> str:
    h = hex_.lstrip("#")
    return f"{alpha}{h[4:6]}{h[2:4]}{h[0:2]}"  # KML is aabbggrr


def _style(sid: str, hex_: str, icon: str | None = None, width: float = 3) -> str:
    if icon:
        return (f'<Style id="{sid}"><IconStyle><color>{_kml_colour(hex_)}</color><scale>0.8</scale>'
                f'<Icon><href>{icon}</href></Icon></IconStyle><LabelStyle><scale>0.7</scale></LabelStyle></Style>')
    return f'<Style id="{sid}"><LineStyle><color>{_kml_colour(hex_)}</color><width>{width}</width></LineStyle></Style>'


def _ext(fields: dict) -> str:
    rows = "".join(f'<Data name="{escape(clean(k))}"><value>{escape(clean(v))}</value></Data>'
                   for k, v in fields.items() if v not in (None, ""))
    return f"<ExtendedData>{rows}</ExtendedData>"


def _point(name: str, style: str, lat: float, lon: float, fields: dict) -> str:
    return (f"<Placemark><name>{escape(clean(name))}</name><styleUrl>#{style}</styleUrl>{_ext(fields)}"
            f"<Point><coordinates>{lon:.7f},{lat:.7f},0</coordinates></Point></Placemark>")


def build_kml(d: Design, st: Stamp) -> str:
    dot = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
    sq = "http://maps.google.com/mapfiles/kml/shapes/square.png"
    tri = "http://maps.google.com/mapfiles/kml/shapes/triangle.png"
    star = "http://maps.google.com/mapfiles/kml/shapes/star.png"
    home = "http://maps.google.com/mapfiles/kml/shapes/homegardenbusiness.png"
    styles = [_style("pole", KIND_COLOURS["pole"], dot), _style("home", KIND_COLOURS["home"], home),
              _style("main", KIND_COLOURS["main"], width=4), _style("spur", KIND_COLOURS["spur"], width=3),
              _style("drop", KIND_COLOURS["drop"], width=1.5),
              '<Style id="boundary"><LineStyle><color>ffffffff</color><width>2</width></LineStyle>'
              '<PolyStyle><fill>0</fill></PolyStyle></Style>']
    icons = {"POP": star, "ENCLOSURE": sq, "PR_ENCLOSURE": sq, "JB": sq, "PON": star, "FAT": tri, "SLACK": dot}
    styles += [_style(k, KIND_COLOURS[k], icons[k]) for k in icons]

    lengths = {cl.cable: cl for cl in calc.cable_lengths(d)}
    parts = [f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
             f"<name>{escape(clean(d.info.name))} - HLD</name><description>{escape(clean(st.line))}</description>",
             *styles]
    if d.info.boundary:
        ring = " ".join(f"{lon:.7f},{lat:.7f},0" for lat, lon in d.info.boundary + d.info.boundary[:1])
        parts.append(f"<Placemark><name>Project Boundary</name><styleUrl>#boundary</styleUrl><Polygon><outerBoundaryIs>"
                     f"<LinearRing><coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>")

    for kind in ("main", "spur", "drop"):
        cabs = [c for c in d.cables if c.kind == kind and len(c.path) >= 2]
        if not cabs:
            continue
        parts.append(f"<Folder><name>{kind.title()} cables</name>")
        for c in cabs:
            cl = lengths.get(c.id)
            coords = " ".join(f"{v.lon:.7f},{v.lat:.7f},0" for v in c.path)
            parts.append(f"<Placemark><name>{escape(clean(c.id))}</name><styleUrl>#{kind}</styleUrl>"
                         + _ext({"cores": c.cores, "kind": c.kind, "from": c.from_node, "to": c.to_node,
                                 "install": c.install,
                                 "crossings": ",".join(str(i) for i, v in enumerate(c.path) if v.crossing),
                                 "status": c.status, "route_m": round(cl.route_m, 1) if cl else "",
                                 "total_m": round(cl.total_m, 1) if cl else "",
                                 "poles": " > ".join(v.pole or v.node or "" for v in c.path)})
                         + f"<LineString><tessellate>1</tessellate><coordinates>{coords}</coordinates></LineString></Placemark>")
        parts.append("</Folder>")

    ducts = [x for x in d.ducts if len(x.path) >= 2]
    if ducts:
        parts.append(_style("duct", "#3584e4", width=2) + "<Folder><name>Trunking / conduit</name>")
        for x in ducts:
            coords = " ".join(f"{v.lon:.7f},{v.lat:.7f},0" for v in x.path)
            parts.append(f"<Placemark><name>{escape(clean(x.id))}</name><styleUrl>#duct</styleUrl>"
                         + _ext({"kind": x.kind, "notes": x.notes})
                         + f"<LineString><coordinates>{coords}</coordinates></LineString></Placemark>")
        parts.append("</Folder>")
    pos = {n.id: d.node_position(n) for n in d.nodes}
    for kind, label in NODE_LABEL.items():
        nodes = [n for n in d.nodes if n.kind == kind and valid_coord(*pos[n.id])]
        if nodes:
            parts.append(f"<Folder><name>{escape(label)}</name>")
            parts += [_point(n.id, kind, *pos[n.id], {"kind": kind, "pole": n.pole, "status": n.status,
                                                     "ports": n.ports, "notes": n.notes}) for n in nodes]
            parts.append("</Folder>")
    spl = [s for s in d.splitters if s.node in pos and valid_coord(*pos[s.node])]
    if spl:
        parts.append("<Folder><name>Splitters</name>")
        parts += [_point(s.id, "PON" if s.stage == 1 else "FAT", *pos[s.node],
                         {"stage": s.stage, "outputs": s.outputs, "node": s.node, "ratio": s.ratio}) for s in spl]
        parts.append("</Folder>")

    parts.append("<Folder><name>Poles</name>")
    parts += [_point(p.id, "pole", p.lat, p.lon, {"type": p.type, "height_m": p.height_m, "condition": p.condition,
                                                   "status": p.status, "notes": p.notes})
              for p in d.poles if valid_coord(p.lat, p.lon)]
    parts.append("</Folder><Folder><name>Homes / MDUs</name>")
    parts += [_point(h.id, "home", h.lat, h.lon, {"kind": h.kind, "units": h.units, "name": h.name,
                                                   "address": h.address, "fat": h.fat})
              for h in d.homes if valid_coord(h.lat, h.lon)]
    parts.append("</Folder></Document></kml>")
    return "".join(parts)


def build_kmz(d: Design, st: Stamp) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", build_kml(d, st))
    return buf.getvalue()
