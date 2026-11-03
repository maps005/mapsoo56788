"""Deliverables for the structural and architectural engineers: bar bending schedule, structural calculations,
architectural schedules and the IFC model."""
import io
import re

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from ftth import building as B, calc, sectors, structure
from ftth.exporters import engineering as E, package
from ftth.exporters.common import stamp
from ftth.model import Design


@pytest.fixture(scope="module")
def block():
    d = Design()
    sectors.apply(d, "construction")
    d.info.name = "Engineering test block"
    d.info.site.bearing_capacity = 250
    d.building = B.generate(B.AutoParams(width=40, depth=18, floors=6, use="apartments", flat_width=12, roof="flat",
                                         columns=True, floor_height=3.0))
    d.building.origin = [-1.29, 36.78]
    return d


def test_the_bar_bending_schedule_is_bs8666_and_is_the_boqs_steel(block):
    rows = E.bbs_rows(block)
    assert len(rows) > 50
    assert {r["shape"] for r in rows} <= {"00", "11", "21", "51"} and {"00", "51"} <= {r["shape"] for r in rows}
    assert len({r["mark"] for r in rows}) == len(rows)  # every bar mark once
    for r in rows:  # weight = number x length x d2/162
        assert abs(r["kg"] - r["total"] * r["length"] / 1000 * r["dia"] ** 2 / 162) < 0.2
        assert r["length"] % 25 == 0 and r["length"] <= 12000 + 40 * 25
    members = {r["member"].split()[0] for r in rows}
    assert {"Columns", "Beams", "Slab", "Walls"} <= members and ({"Foundations", "Raft"} & members)
    rebar = next(ln for ln in calc.bom(block) if ln.code == "REBAR")
    assert abs(rebar.qty - sum(r["kg"] for r in rows)) < 1  # one figure: the BOQ prices the schedule
    xl = load_workbook(io.BytesIO(E.bbs_xlsx(block, stamp(block, 1))))
    assert xl.sheetnames[:2] == ["Bar bending schedule", "Summary by diameter"]
    assert len(PdfReader(io.BytesIO(E.bbs_pdf(block, stamp(block, 1)))).pages) >= 2


def test_structural_calculations_check_every_element(block):
    secs = E.calc_sections(block)
    assert [t.split(". ")[1] for t, _ in secs] == ["Design basis", "Slabs", "Beams", "Stairs", "Columns", "Foundations",
                                                    "Lateral stability", "Fire resistance"]
    outputs = [o for _, rows in secs for _, _, o in rows]
    flags = ("CHECK", "INCREASE", "ENLARGE", "PILES", "ADD", "DEEPEN", "MORE STEEL", "COVER TO", "THICKEN", "REDESIGN", "K > K'")
    assert not [o for o in outputs if any(w in o for w in flags)]
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(E.calcs_pdf(block, stamp(block, 1)))).pages)
    assert "EC2 7.4.2" in text and "VRd,s" in text and "Preliminary" in text
    assert "punching" in text and "EN 1991-1-4" in text and "EN 1992-1-2" in text


def test_wind_follows_en1991_1_4():
    w = structure.wind_peak(24.0)  # terrain III, vb 28 m/s
    assert abs(w["qp"] - 1.13) < 0.02 and abs(w["cr"] - 0.944) < 0.005
    assert structure.wind_peak(2.0)["z"] == structure.ZMIN  # below zmin the pressure at zmin
    assert structure.wind_peak(90)["qp"] > structure.wind_peak(24)["qp"]


def test_fire_resistance_sets_minimum_sizes_and_covers():
    from ftth.exporters.engineering import covers
    low = B.generate(B.AutoParams(width=20, depth=12, floors=3, columns=True, roof="flat"))
    high = B.generate(B.AutoParams(width=30, depth=16, floors=12, columns=True, roof="flat", use="office"))
    assert structure.fire_period(low) == 60 and structure.fire_period(high) == 120
    dz = structure.design(high, 300)
    assert min(min(c["sizes"]) for c in dz["columns"]) >= structure.FIRE_MIN[120]["column"][0] / 1000
    assert min(dz["beam_x"]["b"], dz["beam_y"]["b"]) >= structure.FIRE_MIN[120]["beam"][0] / 1000
    assert covers(high)["column"] + 20 >= structure.FIRE_MIN[120]["column"][1]


def test_the_stair_waist_is_designed_and_used(block):
    dz = structure.design(block.building, 250)
    sd = dz["stair"]
    assert sd["K"] <= 0.167 and sd["ld"] <= sd["limit"] and sd["waist"] >= 0.15
    rows = [r for r in E.bbs_rows(block) if r["member"].startswith("Stairs")]
    assert rows and any(f"waist {sd['waist'] * 1000:.0f} mm" in r["note"] for r in rows)
    lintels = [r for r in E.bbs_rows(block) if r["member"].startswith("Lintels")]
    footings = [r for r in E.bbs_rows(block) if r["member"].startswith("Footings")]
    assert lintels and footings


def test_slabs_are_thick_enough_for_ec2_deflection():
    for span in (4.0, 5.5, 7.0):
        h = 0.15
        while not structure.slab_deflection(h, span, 2.5)["ok"]:
            h += 0.025
        assert structure.slab_deflection(h, span, 2.5)["ld"] <= structure.slab_deflection(h, span, 2.5)["limit"]
    assert not structure.slab_deflection(0.15, 7.0, 2.5)["ok"]  # 150 mm over 7 m: too slender


def test_architectural_schedules(block):
    wb = load_workbook(io.BytesIO(E.schedules_xlsx(block, stamp(block, 1))))
    assert wb.sheetnames == ["Door schedule", "Window schedule", "Room finishes", "Area schedule"]
    doors = [[c.value for c in r] for r in wb["Door schedule"].iter_rows(min_row=6) if r[0].value and str(r[0].value).startswith("D")]
    assert sum(r[-1] for r in doors) == sum(1 for o in block.building.openings if o.kind == "door")
    assert any("FD60" in str(r[1]) for r in doors) and any("FD30" in str(r[1]) for r in doors)
    rooms = [r for r in wb["Room finishes"].iter_rows(min_row=6, values_only=True) if r[0] and r[1]]
    assert len(rooms) == len(block.building.rooms)
    assert any(r[3] == "Bathroom" and "tiles" in r[6].lower() for r in rooms)
    total = [r for r in wb["Area schedule"].iter_rows(min_row=6, values_only=True) if r[0] == "Total"][0]
    assert abs(total[3] - sum(B.area(s.outline) for s in block.building.slabs if s.level < len(block.building.levels))) < 1


def test_the_ifc_model_is_complete_and_consistent(block):
    text = E.ifc_model(block, stamp(block, 1)).decode()
    assert text.startswith("ISO-10303-21;") and "FILE_SCHEMA(('IFC4'));" in text and text.rstrip().endswith("END-ISO-10303-21;")
    defined = set(re.findall(r"^#(\d+)=", text, re.M))
    used = set(re.findall(r"#(\d+)", re.sub(r"^#\d+=", "", text, flags=re.M)))
    assert used <= defined  # every reference resolves
    guids = re.findall(r"\('([0-9A-Za-z_$]{22})'", text)
    assert len(guids) == len(set(guids)) and all(g[0] in "0123" for g in guids)
    count = lambda e: len(re.findall(rf"^#\d+={e}\(", text, re.M))  # noqa: E731
    b = block.building
    assert count("IFCBUILDINGSTOREY") == len(b.levels)
    assert count("IFCWALL") == len(b.walls) and count("IFCCOLUMN") == len(b.columns)
    assert count("IFCDOOR") + count("IFCWINDOW") == len(b.openings) == count("IFCOPENINGELEMENT")
    assert count("IFCSLAB") == len(b.slabs) and count("IFCSPACE") == sum(1 for r in b.rooms if r.rect)
    assert "IFCSITE(" in text and "(-1,-17,-24," in text  # georeferenced: -1.29 deg = -1 deg 17 min 24 s
    assert E.ifc_model(block, stamp(block, 1)) == E.ifc_model(block, stamp(block, 1))  # stable GUIDs
    assert "'Pset_WallCommon'" in text and "IFCLABEL('REI60')" in text or "IFCLABEL('REI90')" in text
    assert count("IFCELEMENTQUANTITY") == len(b.walls) + len(b.slabs) + len(b.columns)
    dz = structure.design(b, 250)
    assert f"IFCQUANTITYLENGTH('Depth',$,$,{dz['slab']:.4f},$)" in text  # suspended slabs as designed


def test_engineering_deliverables_belong_to_construction_only(block):
    keys = package.relevant(block)
    assert {"plans", "bbs", "calcs", "schedules", "ifc"} <= set(keys)
    other = Design()
    sectors.apply(other, "fibre")
    assert not ({"plans", "bbs", "calcs", "schedules", "ifc"} & set(package.relevant(other)))
    assert package.MIME["ifc"] == "application/x-step"
