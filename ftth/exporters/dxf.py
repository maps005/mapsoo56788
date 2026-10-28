"""LLD export to DXF (opens in AutoCAD, BricsCAD, QCAD, LibreCAD).

Native DWG is not written: open the DXF in AutoCAD and save as DWG. Coordinates are
metres in a local plane centred on the project (origin recorded in the title block).
"""
from __future__ import annotations

import io

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .. import calc, sectors
from ..geo import LocalProjection, valid_coord
from ..model import Design
from .common import KIND_COLOURS, Stamp, hex_rgb
from .labels import LabelPlacer, route_anchors, stacked

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
    # geometry first, then the labels where they cover no symbol or other label (most important first)
    lab = LabelPlacer(cell=12.0, free=0.05)

    def place(x, y, text, layer, h, r, anchors=None, optional=False):
        at = lab.place(len(text) * h * 0.62, h, r, anchors or [(x, y)], optional)
        if at is None:  # a pole / premise / drop label with no free room: the schedules list it
            return
        left, bottom, leader = at
        if leader:
            msp.add_line(leader[:2], leader[2:], dxfattribs={"layer": layer})
        label(left, bottom, text, layer, h)

    lengths = {cl.cable: cl for cl in calc.cable_lengths(d)}
    routes = []
    for c in d.cables:
        if len(c.path) < 2:
            continue
        layer = f"CABLE_{c.kind.upper()}"
        xy = [proj.xy(v.lat, v.lon) for v in c.path]
        msp.add_lwpolyline(xy, dxfattribs={"layer": layer, "const_width": 0.6 if c.kind == "main" else 0.3})
        lab.block_line(xy, 2.0)
        routes.append((c, layer, xy))

    poles = []
    for p in d.poles:
        if valid_coord(p.lat, p.lon):
            x, y = proj.xy(p.lat, p.lon)
            msp.add_circle((x, y), 1.2, dxfattribs={"layer": "POLES"})
            if p.status == "proposed":
                msp.add_circle((x, y), 2.0, dxfattribs={"layer": "POLES"})
            lab.block(x, y, 2.0)
            poles.append((p, x, y))

    equipment, placed = [], []
    for n in d.nodes:
        lat, lon = n.lat, n.lon
        if not valid_coord(lat, lon) and n.pole and d.pole(n.pole):
            lat, lon = d.pole(n.pole).lat, d.pole(n.pole).lon
        if not valid_coord(lat, lon):
            continue
        x0, y0 = proj.xy(lat, lon)
        s = 2.5
        x, y = stacked(placed, x0, y0, 2 * s, 2.4 * s)  # a closure and a JB on one pole: one below the other
        if (x, y) != (x0, y0):
            msp.add_line((x0, y0), (x, y), dxfattribs={"layer": "EQUIPMENT"})
        if n.kind == "FAT":
            msp.add_lwpolyline([(x, y + s), (x - s, y - s), (x + s, y - s)], close=True, dxfattribs={"layer": "EQUIPMENT"})
        else:
            msp.add_lwpolyline([(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)], close=True,
                               dxfattribs={"layer": "EQUIPMENT"})
        lab.block(x, y, s)
        equipment.append((n, x, y))

    nodes = {n.id: n for n in d.nodes}
    homes = []
    for h in d.homes:
        if valid_coord(h.lat, h.lon):
            x, y = proj.xy(h.lat, h.lon)
            msp.add_lwpolyline([(x - 2, y - 2), (x + 2, y - 2), (x + 2, y + 2), (x - 2, y + 2)], close=True,
                               dxfattribs={"layer": "HOMES"})
            lab.block(x, y, 2.0)
            homes.append((h, x, y))
            f = nodes.get(h.fat or "")
            if f and valid_coord(f.lat, f.lon):
                msp.add_line((x, y), proj.xy(f.lat, f.lon), dxfattribs={"layer": "DROPS", "linetype": "DASHED"})

    for n, x, y in equipment:
        sp = [s_ for s_ in d.splitters if s_.node == n.id]
        extra = " " + ",".join(s_.ratio for s_ in sp) if sp else ""
        place(x, y, f"{n.id} {sectors.kind_label(d, n.kind)}{extra}", "EQUIPMENT", 1.8, 2.5)
    for c, layer, xy in routes:
        cl = lengths.get(c.id)
        place(*xy[0], f"{c.id} {c.cores}C {c.kind.upper()} {cl.total_m:.0f}m" if cl else c.id, layer, th, 0.5,
              route_anchors(xy), optional=c.kind == "drop")
        for v, (x, y) in zip(c.path, xy):
            if v.crossing:
                place(x, y, "ROAD X", layer, 1.5, 1.0)
    for h, x, y in homes:
        place(x, y, f"{h.id}" + (f" ({h.units}u)" if h.units > 1 else ""), "HOMES", 1.3, 2.0, optional=True)
    for p, x, y in poles:
        place(x, y, p.id, "POLES", 1.5, 2.0, optional=True)

    # title block below the drawing extents
    if pts:
        xs = [proj.xy(*p)[0] for p in pts]
        ys = [proj.xy(*p)[1] for p in pts]
        x0, y0, w = min(xs), min(ys) - 40, max(60.0, max(xs) - min(xs))
        msp.add_lwpolyline([(x0, y0), (x0 + w, y0), (x0 + w, y0 + 30), (x0, y0 + 30)], close=True,
                           dxfattribs={"layer": "TITLE"})
        for i, t in enumerate([f"{'FTTH LLD' if d.info.sector == 'fibre' else 'DETAILED DESIGN'} - {d.info.name}", f"{d.info.area}",
                               f"Rev {st.revision}  Status {st.status.upper()}  Data {st.hash}  Date {st.date}",
                               f"Units: metres, local plane origin lat {proj.lat0:.6f} lon {proj.lon0:.6f} (WGS84)"]):
            label(x0 + 2, y0 + 24 - i * 6, t, "TITLE", 3 if i == 0 else 2)

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")
