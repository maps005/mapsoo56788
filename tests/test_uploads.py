"""Uploads in more formats: CAD drawings (DXF; DWG through a converter), CSV / KML / DXF for dams and buildings,
and site photos placed by their GPS position."""
import io

import ezdxf
import pytest
from django.contrib.auth.models import User
from django.test import Client
from PIL import Image

from ftth import importers, sectors, workbooks as W
from ftth.cadimport import dwg_to_dxf
from ftth.dam import Dam
from ftth.exporters import dxf
from ftth.exporters.common import stamp
from ftth.geo import haversine
from ftth.model import Design
from ftth.sample import sample_design


def _dxf_bytes(doc) -> bytes:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def test_our_own_dxf_reads_back_onto_the_map():
    src = sample_design()
    data = dxf.build_dxf(src, stamp(src, 1))
    d = Design()
    rep = importers.import_file(d, "lld.dxf", data, "auto", "existing")
    assert any("WGS 84 / UTM zone" in p for p in rep["problems"])  # the grid from the drawing's own title
    assert len(d.poles) >= len(src.poles) * 0.9 and len(d.cables) >= 1
    p = src.poles[0]
    assert min(haversine(p.lat, p.lon, q.lat, q.lon) for q in d.poles) < 1.0  # back where it was, within a metre


def test_a_surveyors_dxf_in_lon_lat_with_blocks():
    doc = ezdxf.new()
    blk = doc.blocks.new("POLE_SYM")
    blk.add_circle((0, 0), 0.00001)
    blk.add_attdef("ID", (0, 0))
    msp = doc.modelspace()
    for i, (lon, lat) in enumerate([(36.80, -1.30), (36.8005, -1.3002)], start=1):
        ins = msp.add_blockref("POLE_SYM", (lon, lat), dxfattribs={"layer": "POLES"})
        ins.add_attrib("ID", f"KP{i:03d}", (lon, lat))
    msp.add_lwpolyline([(36.80, -1.30), (36.8005, -1.3002)], dxfattribs={"layer": "CABLE_12C"})
    d = Design()
    rep = importers.import_file(d, "survey.dxf", _dxf_bytes(doc), "auto", "existing")
    assert sorted(p.id for p in d.poles) == ["KP001", "KP002"] and abs(d.poles[0].lat + 1.30) < 1e-6
    assert d.cables and d.cables[0].cores == 12
    assert any("longitude, latitude" in p for p in rep["problems"])


def test_dwg_without_a_converter_asks_for_dxf(monkeypatch):
    monkeypatch.setattr("ftth.cadimport._converter", lambda: None)
    with pytest.raises(ValueError, match="DXF"):
        dwg_to_dxf(b"AC1032" + b"\0" * 100)


def test_dam_and_building_data_from_csv_kml_and_dxf():
    d = Design()
    sectors.apply(d, "dams")
    d.dam = Dam()
    W.import_sector_file(d, "axis.csv", b"Chainage,Ground level,Depth to firm\n0,120,2\n50,100,3\n100,119,2\n", dam=True)
    W.import_sector_file(d, "res.csv", b"Level,Area\n100,0\n110,50000\n", dam=True)
    assert len(d.dam.axis) == 3 and d.dam.reservoir[-1] == [110.0, 50000.0]
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline([(36.80, -1.30), (36.801, -1.3005)], dxfattribs={"layer": "DAM_AXIS"})
    doc.modelspace().add_lwpolyline([(36.79, -1.31), (36.81, -1.31), (36.81, -1.29), (36.79, -1.29)], close=True,
                                    dxfattribs={"layer": "SITE"})
    rep = W.import_sector_file(d, "site.dxf", _dxf_bytes(doc), dam=True)
    assert d.dam.axis_start == [-1.30, 36.80] and len(d.info.boundary) == 4 and any("Dam axis" in r for r in rep)

    b = Design()
    sectors.apply(b, "construction")
    kml = b"""<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><name>Plot 12</name>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>36.8,-1.3 36.8004,-1.3 36.8004,-1.2996 36.8,-1.2996 36.8,-1.3
      </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>"""
    W.import_sector_file(b, "plot.kml", kml, dam=False)
    W.import_sector_file(b, "rooms.csv", b"Room,Number,Area\nBedroom,10,12\n", dam=False)
    assert len(b.info.boundary) == 5 and b.info.site.schedule[0].name == "Bedroom"


def _geotagged_jpeg(lat, lon) -> bytes:
    im = Image.new("RGB", (40, 30), "white")
    exif = im.getexif()
    dms = lambda v: (float(int(abs(v))), float(int(abs(v) * 60 % 60)), round(abs(v) * 3600 % 60, 4))  # noqa: E731
    exif[0x8825] = {1: "S" if lat < 0 else "N", 2: dms(lat), 3: "E" if lon > 0 else "W", 4: dms(lon)}
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


@pytest.mark.django_db
def test_a_geotagged_photo_is_linked_to_the_nearest_feature(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    u = User.objects.create_user("photo-user", password="x")
    c = Client(HTTP_HOST="localhost")
    c.force_login(u)
    st = c.post("/api/projects", {"sample": True}, content_type="application/json").json()
    pole = st["design"]["poles"][0]
    f = io.BytesIO(_geotagged_jpeg(pole["lat"], pole["lon"]))
    f.name = "pole check.jpg"
    r = c.post(f"/api/projects/{st['id']}/import", {"file": f})
    assert r.status_code == 200, r.content
    ph = r.json()["design"]["photos"][-1]
    assert ph["caption"] == "pole check" and ph["feature"] is not None
    assert "linked to" in r.json()["import"]["problems"][0]
