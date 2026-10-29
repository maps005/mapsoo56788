"""Drafting (markups) saved with the design and drawn in the DXF and PDF sheets; the map under the sheets."""
import io
import zipfile

import ezdxf
import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfReader

from ftth.exporters import basemap, dxf, lld, package
from ftth.exporters.common import stamp
from ftth.model import Design, Markup
from ftth.sample import sample_design


def drafted():
    d = sample_design()
    p = d.poles[0]
    a, b = [p.lat, p.lon], [p.lat + 0.0003, p.lon + 0.0004]
    d.markups = [Markup(id="MK001", kind="dimension", points=[a, b]),
                 Markup(id="MK002", kind="text", points=[a], text="Wayleave pending", colour="#ffd60a"),
                 Markup(id="MK003", kind="polyline", closed=True, points=[a, b, [b[0], a[1]]]),
                 Markup(id="MK004", kind="leader", points=[b, [b[0] + 0.0001, b[1]]], text="Check depth"),
                 Markup(id="MK005", kind="circle", points=[a, [a[0], a[1] + 0.0001]]),
                 Markup(id="MK006", kind="line", points=[a, b])]
    return d


def test_markups_validate_their_points_and_round_trip():
    with pytest.raises(ValidationError):
        Markup(id="X", kind="line", points=[[0.1, 0.1]])  # a line needs two points
    with pytest.raises(ValidationError):
        Markup(id="X", kind="text", points=[[95, 0]], text="off the globe")
    with pytest.raises(ValidationError):
        Markup(id="X", kind="circle", points=[[0, 0], [0, 1]], colour="red")
    d = drafted()
    again = Design.model_validate(d.model_dump(mode="json"))
    assert [m.kind for m in again.markups] == [m.kind for m in d.markups]
    # drafting changes the LLD / HLD outputs only
    before = {k: package.deliverable_hash(d, k) for k in ("lld", "hld", "bom")}
    d.markups.pop()
    after = {k: package.deliverable_hash(d, k) for k in ("lld", "hld", "bom")}
    assert before["lld"] != after["lld"] and before["hld"] != after["hld"] and before["bom"] == after["bom"]


def test_dxf_has_the_drafting_as_cad_entities():
    d = drafted()
    msp = ezdxf.read(io.StringIO(dxf.build_dxf(d, stamp(d, 1)).decode())).modelspace()
    kinds = {e.dxftype() for e in msp.query("*[layer=='MARKUP']")}
    assert {"LINE", "LWPOLYLINE", "CIRCLE", "TEXT", "LEADER", "DIMENSION"} <= kinds
    assert any(t.dxf.text == "Wayleave pending" for t in msp.query("TEXT[layer=='MARKUP']"))


def fake_tiles(monkeypatch):
    calls = []

    def fetch(url):
        calls.append(url)
        buf = io.BytesIO()
        Image.new("RGB", (256, 256), (40, 120, 40)).save(buf, "PNG")
        return buf.getvalue()
    monkeypatch.setattr(basemap, "FETCH", fetch)
    basemap._CACHE.clear()
    return calls


def test_sheets_and_dxf_zip_carry_the_chosen_map(monkeypatch):
    calls = fake_tiles(monkeypatch)
    d = drafted()
    d.info.sheet_map = "satellite"
    pdf_bytes = lld.build_lld_pdf(d, stamp(d, 1))
    assert calls and all("arcgisonline" in u for u in calls)
    pages = PdfReader(io.BytesIO(pdf_bytes)).pages
    text = " ".join(p.extract_text() for p in pages)
    assert "Imagery © Esri" in text and "Wayleave pending" in text
    assert any(p.images for p in pages)  # the map image is on the sheets
    with zipfile.ZipFile(io.BytesIO(dxf.build_dxf_zip(d, stamp(d, 1)))) as z:
        names = z.namelist()
        assert dxf.MAP_FILE in names and "map.jgw" in names
        msp = ezdxf.read(io.StringIO(z.read(next(n for n in names if n.endswith(".dxf"))).decode())).modelspace()
        img = msp.query("IMAGE")[0]
        assert img.image_def.dxf.filename == dxf.MAP_FILE and img.dxf.layer == "BASEMAP"


def test_no_map_by_default_and_no_tiles_fetched(monkeypatch):
    calls = fake_tiles(monkeypatch)
    d = drafted()
    lld.build_lld_pdf(d, stamp(d, 1))
    with zipfile.ZipFile(io.BytesIO(dxf.build_dxf_zip(d, stamp(d, 1)))) as z:
        assert dxf.MAP_FILE not in z.namelist() and "choose Streets or Satellite" in z.read("README.txt").decode()
    assert calls == []


def test_arcs_points_hatches_dimension_types_and_layers_reach_the_dxf_and_pdf():
    from ftth.exporters import drafting
    from ftth.model import CadLayer
    d = sample_design()
    p = d.poles[0]
    a, b, c = [p.lat, p.lon], [p.lat + 0.0002, p.lon + 0.0003], [p.lat, p.lon + 0.0004]
    edge = [p.lat, p.lon + 0.0001]
    with pytest.raises(ValidationError):  # an angular dimension needs arm, vertex, arm
        Markup(id="X", kind="dimension", dim="angular", points=[a, b])
    d.cad_layers = [CadLayer(name="Notes", colour="#ffd60a"), CadLayer(name="Draft", visible=False, locked=True)]
    d.markups = [Markup(id="A1", kind="arc", points=[a, b, c]), Markup(id="P1", kind="point", points=[b]),
                 Markup(id="H1", kind="polyline", closed=True, fill="#3ddc84", points=[a, b, c]),
                 Markup(id="C1", kind="circle", fill="#ff6b6b", points=[a, edge], layer="Notes"),
                 Markup(id="D1", kind="dimension", dim="horizontal", points=[a, b]),
                 Markup(id="D2", kind="dimension", dim="vertical", points=[a, b]),
                 Markup(id="D3", kind="dimension", dim="radius", points=[a, edge]),
                 Markup(id="D4", kind="dimension", dim="angular", points=[b, a, c]),
                 Markup(id="T1", kind="text", points=[c], text="Draft only", layer="Draft")]
    st = stamp(d, 1)
    doc = ezdxf.read(io.StringIO(dxf.build_dxf(d, st).decode()))
    found = {(e.dxftype(), e.dxf.layer) for e in doc.modelspace() if e.dxf.layer.startswith(("MARKUP", "MK_"))}
    assert {("ARC", "MARKUP"), ("POINT", "MARKUP"), ("HATCH", "MARKUP"), ("CIRCLE", "MK_Notes"), ("HATCH", "MK_Notes"),
            ("DIMENSION", "MARKUP"), ("TEXT", "MK_Draft")} <= found
    assert doc.layers.get("MK_Draft").is_off() and doc.layers.get("MK_Draft").is_locked()
    text = " ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(lld.build_lld_pdf(d, st))).pages)
    assert "Draft only" not in text and "°" in text  # hidden layer left out; the angular dimension is there
    # three points on the unit circle give that circle; the dimension values are the angle and the run
    g = drafting.arc3((0, 1), (1, 0), (0, -1))
    assert g and abs(g[2] - 1) < 1e-9 and abs(g[0]) < 1e-9 and abs(g[1]) < 1e-9
    assert abs(drafting.dimension("angular", [(1, 0), (0, 0), (0, 1)], 1)[3] - 90) < 1e-9
    assert abs(drafting.dimension("horizontal", [(0, 0), (3, 4)], 1)[3] - 3) < 1e-9


def test_unreachable_tiles_leave_the_sheet_without_a_map(monkeypatch):
    monkeypatch.setattr(basemap, "FETCH", lambda url: None)
    basemap._CACHE.clear()
    d = drafted()
    d.info.sheet_map = "streets"
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(lld.build_lld_pdf(d, stamp(d, 1)))).pages)
    assert "Map not available" in text
