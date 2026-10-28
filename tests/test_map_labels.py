"""Map labels on the LLD / HLD sheets and in the DXF do not print over each other."""
import io
from unittest.mock import MagicMock

import ezdxf
from reportlab.pdfbase.pdfmetrics import stringWidth

from ftth.exporters import dxf, pdf
from ftth.exporters.common import stamp
from ftth.exporters.labels import LabelPlacer
from ftth.model import Cable, Home, Node, Pole, Vertex
from ftth.sample import sample_design


def crowded_design():
    """The demo plus a knot of equipment, premises and cables around one pole (a closure and a JB share it)."""
    d = sample_design()
    lat, lon = d.poles[2].lat, d.poles[2].lon
    pid = d.poles[2].id
    d.nodes += [Node(id="SC-77", kind="ENCLOSURE", pole=pid, lat=lat, lon=lon),
                Node(id="JB-77", kind="JB", pole=pid, lat=lat, lon=lon)]
    for k in range(8):
        d.nodes.append(Node(id=f"FAT-7{k}", kind="FAT", lat=lat + 0.00004 * (k % 3), lon=lon + 0.00004 * (k // 3)))
        d.homes.append(Home(id=f"Building {k} (long name)", lat=lat - 0.00003 * k, lon=lon + 0.00002 * k, units=4))
        d.poles.append(Pole(id=f"KP-W 9{k}", lat=lat + 0.00002 * k, lon=lon - 0.00003 * k))
    for k in range(4):
        d.cables.append(Cable(id=f"C9{k}", kind="spur", cores=12, path=[
            Vertex(lat=lat, lon=lon), Vertex(lat=lat + 0.0002 * (k + 1), lon=lon + 0.0001)]))
    return d


def overlapping(boxes, tol=0.1):
    out = []
    for i, (a, ta) in enumerate(boxes):
        for b, tb in boxes[i + 1:]:
            ix, iy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
            small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            if ix > 0 and iy > 0 and ix * iy > tol * small:
                out.append((ta, tb))
    return out


def test_placer_moves_labels_off_each_other_and_skips_optional_ones_with_no_room():
    lab = LabelPlacer(cell=10)
    lab.block(0, 0, 2)
    spots = [lab.place(20, 4, 2, [(0, 0)]) for _ in range(12)]  # twelve labels for one point
    boxes = [((x, y, x + 20, y + 4), i) for i, (x, y, _) in enumerate(spots)]
    assert not overlapping(boxes)
    assert not spots[0][2] and any(s[2] for s in spots)  # the first sits by the point; outer rings get leaders
    crowded = LabelPlacer(cell=10)
    for _ in range(16):
        crowded.place(20, 4, 2, [(0, 0)])
    assert crowded.place(20, 4, 2, [(0, 0)], optional=True) is None  # a pole label is left to the schedule


def test_pdf_route_sheet_labels_do_not_overlap():
    d = crowded_design()
    cv = MagicMock()
    font = {}
    texts = []
    cv.setFont.side_effect = lambda name, size: font.update(name=name, size=size)
    cv.drawString.side_effect = lambda x, y, t: texts.append(
        ((x, y - font["size"] * 0.22, x + stringWidth(t, font["name"], font["size"]), y + font["size"] * 0.9), t))
    pdf._draw_map(cv, d, 0, 0, 1100, 760, detail=True, light=True)
    assert len(texts) > 40
    assert not overlapping(texts), overlapping(texts)[:5]
    assert {"SC-77", "JB-77"} <= {t.split(" ")[0] for _, t in texts}  # equipment is always labelled


def test_dxf_labels_do_not_overlap_and_shared_poles_stack_equipment():
    d = crowded_design()
    msp = ezdxf.read(io.StringIO(dxf.build_dxf(d, stamp(d, 1)).decode())).modelspace()
    texts = [((t.dxf.insert[0], t.dxf.insert[1], t.dxf.insert[0] + len(t.dxf.text) * t.dxf.height * 0.62,
               t.dxf.insert[1] + t.dxf.height), t.dxf.text) for t in msp.query("TEXT") if t.dxf.layer != "TITLE"]
    assert not overlapping(texts), overlapping(texts)[:5]
    squares = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "EQUIPMENT" and len(e) == 4]
    centres = {(round(sum(p[0] for p in e.get_points()) / 4, 1), round(sum(p[1] for p in e.get_points()) / 4, 1))
               for e in squares}
    assert len(centres) == len(squares)  # the closure and the JB on one pole are drawn apart
