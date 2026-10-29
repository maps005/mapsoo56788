import io
import json
import zipfile

import pytest

from ftth import calc, importers, splicing, validate
from ftth.exporters import package
from ftth.exporters.common import stamp
from ftth.exporters.kml import build_kml
from ftth.model import Connection, Design, End, Pole
from ftth.sample import sample_design


@pytest.fixture
def d():
    d = sample_design()
    calc.assign_homes(d)
    splicing.auto_allocate(d)
    d.info.survey_status = "approved"
    return d


def codes(d):
    return {i["code"] for i in validate.validate(d)}


def test_sample_is_clean(d):
    issues = validate.validate(d)
    assert [i for i in issues if i["severity"] == "error"] == []
    assert all(h.fat for h in d.homes)


def test_allocation_traces_every_fat_to_olt(d):
    for s in d.splitters:
        if s.stage == 2:
            t = splicing.trace_upstream(d, s.id)
            assert t["ok"], t
    # main cable carries one feeder core, each spur one distribution core
    table = {c["cable"]: c for c in splicing.core_table(d)}
    assert table["C001"]["used"] == 1 and table["C004"]["used"] == 1


def test_allocation_is_idempotent(d):
    before = [(c.node, c.a, c.b) for c in d.connections]
    splicing.auto_allocate(d)
    assert [(c.node, c.a, c.b) for c in d.connections] == before


def test_duplicate_core_and_reserved_core_flagged(d):
    used = next(c for c in d.connections if c.a.kind == "olt")
    d.connections.append(Connection(id="M0001", node=used.node, a=End(kind="olt", ref="POP01", n=2), b=used.b))
    assert "core_duplicate" in codes(d)
    d.connections.pop()
    d.cable("C001").reserved = [1]
    assert "core_reserved" in codes(d)


def test_core_out_of_range_and_cable_absent(d):
    d.connections.append(Connection(id="M0002", node="FAT02", a=End(kind="cable", ref="C001", n=99),
                                    b=End(kind="cable", ref="C004", n=5)))
    c = codes(d)
    assert "core_range" in c and "cable_absent" in c


def test_survey_validation(d):
    d.poles.append(Pole(id="P001", lat=-1.3123, lon=36.8211))          # duplicate id
    d.poles.append(Pole(id="P099", lat=None, lon=None))                # missing coords
    d.poles.append(Pole(id="P100", lat=-1.3123000, lon=36.8211001))    # same place as P001
    c = codes(d)
    assert {"id_duplicate", "coord_missing", "location_duplicate"} <= c


def test_fat_capacity(d):
    d.node("FAT01").ports = 1
    assert "fat_capacity" in codes(d)


def test_pole_summary_rules(d):
    rows = {r.pole: r for r in calc.pole_summary(d)}
    assert rows["P001"].jhooks == 1 and rows["P001"].tension == 0      # straight pass
    assert rows["P003"].tension == 3 and rows["P003"].enclosures == 1  # 3 cables terminate at PON01
    d.rules.jhook_per_straight_cable = 2
    assert {r.pole: r for r in calc.pole_summary(d)}["P001"].jhooks == 2


def test_bom_uses_lengths_and_adjustments(d):
    lines = {l.code: l for l in calc.bom(d)}
    cl = {c.cable: c for c in calc.cable_lengths(d)}["C001"]
    assert lines["FOC-48C"].qty >= cl.route_m + 2 * d.rules.slack_per_cable_end_m
    from ftth.model import Adjustment
    d.adjustments.append(Adjustment(code="J-HOOK", qty=5, reason="spares"))
    assert {l.code: l for l in calc.bom(d)}["J-HOOK"].qty == lines["J-HOOK"].qty + 5
    assert calc.boq_total(calc.bom(d)) > 0


def test_csv_import_detects_columns_and_flags_problems():
    d = Design()
    csv = (b"Pole ID,Latitude,Longitude,Condition\nP1,-1.30,36.80,good\nP2,36.81,-1.31,bad\nP3,,,ok\n"
           b"P4,-1.302,36.801,good\nP5,-1.303,36.802,good\n")
    r = importers.import_file(d, "poles.csv", csv, "poles")
    assert r["added"] == 5
    assert d.pole("P2").lat == -1.31  # swapped columns corrected
    assert d.pole("P1").lat == -1.30  # majority left untouched
    assert d.pole("P3").lat is None and any("P3" in p for p in r["problems"])
    assert d.pole("P1").condition == "good"


def test_xlsx_import():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Survey of estate"])
    ws.append(["ID", "Lat", "Lon", "Units", "Building type"])
    ws.append(["H1", -1.31, 36.82, 6, "Apartment"])
    buf = io.BytesIO()
    wb.save(buf)
    d = Design()
    importers.import_file(d, "homes.xlsx", buf.getvalue(), "homes")
    h = d.homes[0]
    assert h.id == "H1" and h.units == 6 and h.kind == "mdu"


def test_kml_roundtrip(d):
    kml = build_kml(d, stamp(d, 1)).encode()
    d2 = Design()
    importers.import_file(d2, "hld.kml", kml, "auto")
    assert {p.id for p in d2.poles} == {p.id for p in d.poles}
    assert {n.id for n in d2.nodes} == {n.id for n in d.nodes}
    assert len(d2.homes) == len(d.homes) and len(d2.cables) == len(d.cables)
    c = d2.cable("C001 48C") or d2.cables[0]
    assert c.cores == 48 and c.from_node == "POP01"


def test_every_deliverable_builds(d):
    st = stamp(d, 3)
    for deliv, fmts in package.DELIVERABLES.items():
        for fmt in fmts:
            assert len(package.build(d, deliv, fmt, st, None)) > 200, (deliv, fmt)
    z = zipfile.ZipFile(io.BytesIO(package.build_package(d, st, None)))
    manifest = json.loads(z.read("MANIFEST.json"))
    assert manifest["data_hash"] == d.content_hash() and len(manifest["files"]) == 25  # LLD: DXF, PDF, DXF + map
