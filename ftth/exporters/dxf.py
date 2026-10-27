"""LLD export to DXF (opens in AutoCAD, BricsCAD, QCAD, LibreCAD).

Native DWG is not written: open the DXF in AutoCAD and save as DWG. Coordinates are
metres in a local plane centred on the project (origin recorded in the title block).
"""
from __future__ import annotations

import io

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .. import calc
from ..geo import LocalProjection, valid_coord
from ..model import Design
from .common import KIND_COLOURS, NODE_LABEL, Stamp, hex_rgb

LAYERS = {"DUCTS": "#3584e4", "BOUNDARY": "#888888", "POLES": KIND_COLOURS["pole"], "HOMES": KIND_COLOURS["home"],
          "CABLE_MAIN": KIND_COLOURS["main"], "CABLE_SPUR": KIND_COLOURS["spur"], "CABLE_DROP": KIND_COLOURS["drop"],
          "EQUIPMENT": KIND_COLOURS["ENCLOSURE"], "LABELS": "#ffffff", "DROPS": "#77767b", "TITLE": "#ffffff"}


def _points(d: Design) -> list[tuple[float, float]]:
    pts = [(x.lat, x.lon) for coll in (d.poles, d.homes, d.nodes) for x in coll if valid_coord(x.lat, x.lon)]
    pts += [(v.lat, v.lon) for c in d.cables for v in c.path]
    return pts


def build_dxf(d: Design, st: Stamp) -> bytes:
    pts = _points(d)
    proj = LocalProjection.for_points(pts)
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.M
    for name, colour in LAYERS.items():
        layer = doc.layers.add(name)
        layer.rgb = hex_rgb(colour)
    msp = doc.modelspace()
    th = 2.0  # text height (m)

    def label(x, y, text, layer="LABELS", h=th):
        msp.add_text(text, height=h, dxfattribs={"layer": layer}).set_placement((x, y), align=TextEntityAlignment.LEFT)

    if d.info.boundary:
        msp.add_lwpolyline([proj.xy(la, lo) for la, lo in d.info.boundary], close=True, dxfattribs={"layer": "BOUNDARY"})

    for x in d.ducts:
        if len(x.path) >= 2:
            msp.add_lwpolyline([proj.xy(v.lat, v.lon) for v in x.path], dxfattribs={"layer": "DUCTS"})
            a = x.path[0]
            label(*proj.xy(a.lat, a.lon), f"{x.id} {x.kind.upper()}", "DUCTS", 1.5)
    lengths = {cl.cable: cl for cl in calc.cable_lengths(d)}
    for c in d.cables:
        if len(c.path) < 2:
            continue
        layer = f"CABLE_{c.kind.upper()}"
        xy = [proj.xy(v.lat, v.lon) for v in c.path]
        msp.add_lwpolyline(xy, dxfattribs={"layer": layer, "const_width": 0.6 if c.kind == "main" else 0.3})
        mid = len(xy) // 2
        (x1, y1), (x2, y2) = xy[mid - 1], xy[mid]
        cl = lengths.get(c.id)
        label((x1 + x2) / 2, (y1 + y2) / 2 + 1.5,
              f"{c.id} {c.cores}C {c.kind.upper()} {cl.total_m:.0f}m" if cl else c.id, layer)
        for v, (x, y) in zip(c.path, xy):
            if v.crossing:
                label(x + 1, y - 3, "ROAD X", layer, 1.5)

    for p in d.poles:
        if valid_coord(p.lat, p.lon):
            x, y = proj.xy(p.lat, p.lon)
            msp.add_circle((x, y), 1.2, dxfattribs={"layer": "POLES"})
            if p.status == "proposed":
                msp.add_circle((x, y), 2.0, dxfattribs={"layer": "POLES"})
            label(x + 2, y + 1, p.id, "POLES", 1.5)

    for n in d.nodes:
        lat, lon = n.lat, n.lon
        if not valid_coord(lat, lon) and n.pole and d.pole(n.pole):
            lat, lon = d.pole(n.pole).lat, d.pole(n.pole).lon
        if not valid_coord(lat, lon):
            continue
        x, y = proj.xy(lat, lon)
        s = 2.5
        if n.kind == "FAT":
            msp.add_lwpolyline([(x, y + s), (x - s, y - s), (x + s, y - s)], close=True, dxfattribs={"layer": "EQUIPMENT"})
        else:
            msp.add_lwpolyline([(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)], close=True,
                               dxfattribs={"layer": "EQUIPMENT"})
        extra = ""
        sp = [s_ for s_ in d.splitters if s_.node == n.id]
        if sp:
            extra = " " + ",".join(s_.ratio for s_ in sp)
        label(x + 3.5, y - 1, f"{n.id} {NODE_LABEL[n.kind]}{extra}", "EQUIPMENT", 1.8)

    nodes = {n.id: n for n in d.nodes}
    for h in d.homes:
        if valid_coord(h.lat, h.lon):
            x, y = proj.xy(h.lat, h.lon)
            msp.add_lwpolyline([(x - 2, y - 2), (x + 2, y - 2), (x + 2, y + 2), (x - 2, y + 2)], close=True,
                               dxfattribs={"layer": "HOMES"})
            label(x + 2.5, y - 2.5, f"{h.id}" + (f" ({h.units}u)" if h.units > 1 else ""), "HOMES", 1.3)
            f = nodes.get(h.fat or "")
            if f and valid_coord(f.lat, f.lon):
                msp.add_line((x, y), proj.xy(f.lat, f.lon), dxfattribs={"layer": "DROPS", "linetype": "DASHED"})

    # title block below the drawing extents
    if pts:
        xs = [proj.xy(*p)[0] for p in pts]
        ys = [proj.xy(*p)[1] for p in pts]
        x0, y0, w = min(xs), min(ys) - 40, max(60.0, max(xs) - min(xs))
        msp.add_lwpolyline([(x0, y0), (x0 + w, y0), (x0 + w, y0 + 30), (x0, y0 + 30)], close=True,
                           dxfattribs={"layer": "TITLE"})
        for i, t in enumerate([f"FTTH LLD - {d.info.name}", f"{d.info.area}",
                               f"Rev {st.revision}  Status {st.status.upper()}  Data {st.hash}  Date {st.date}",
                               f"Units: metres, local plane origin lat {proj.lat0:.6f} lon {proj.lon0:.6f} (WGS84)"]):
            label(x0 + 2, y0 + 24 - i * 6, t, "TITLE", 3 if i == 0 else 2)

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")
