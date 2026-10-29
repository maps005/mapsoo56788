"""Construction sector: buildings designed automatically, edited, measured, checked and drawn."""
import io
import zipfile

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import ValidationError
from pypdf import PdfReader

from ftth import building as B, calc, sectors, validate
from ftth.exporters import package, plans, report
from ftth.exporters.common import stamp
from ftth.model import Design
from planner.models import Company, Membership, Profile


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def house(**kw):
    d = Design()
    sectors.apply(d, "construction")
    d.building = B.generate(B.AutoParams(**kw))
    return d


def test_auto_design_makes_a_sound_building():
    b = house(width=12, depth=9, floors=2, rooms_x=3, rooms_y=2, roof="hip").building
    assert len(b.levels) == 2 and len(b.stairs) == 1 and b.roofs[0].kind == "hip"
    assert {w.kind for w in b.walls} == {"external", "internal"}
    assert sum(o.kind == "door" for o in b.openings) >= 1 + 2 * 3  # main door and room doors
    assert not [i for i in B.check(b) if i["severity"] == "error"]
    # every opening sits inside its wall, and the stair stays inside the building
    for o in b.openings:
        w = b.wall(o.wall)
        assert o.width / 2 <= o.offset <= B.length(w) - o.width / 2
    st = b.stairs[0]
    n, rise, going = B.stair_steps(b, st)
    assert 0 < st.y and st.y + going < 9 and abs(n * rise - 3.0) < 1e-9


def test_quantities_follow_the_model():
    d = house(width=10, depth=8, floors=1, rooms_x=1, rooms_y=1, roof="gable", pitch=30, overhang=0.5,
              window_spacing=20, external_wall=0.2)
    q = {c: v for c, v, _ in B.quantities(d.building)}
    assert q["CONC-SLAB"] == pytest.approx(10 * 8 * 0.15)
    # four walls on their centrelines, 3 m high, less one window per wall and the main door
    run = 2 * (9.8 + 7.8)
    openings = sum(o.width * o.height for o in d.building.openings)
    assert q["BLOCKWORK-EXT"] == pytest.approx(run * 3 - openings, rel=1e-6)
    assert q["ROOF-SHEETS"] == pytest.approx(11 * 9 / 0.8660254, rel=1e-4)  # plan with overhang / cos 30
    assert q["EXCAVATION"] == pytest.approx(run * 0.6 * 0.9)
    bom = {ln.code: ln for ln in calc.bom(d)}
    assert bom["CONC-SLAB"].description.startswith("Concrete") and bom["DOOR-SINGLE"].qty == 1


def test_checks_catch_bad_openings_stairs_and_setback():
    d = house(width=10, depth=8)
    b = d.building
    b.openings[0].offset = 0.1  # runs off the end of its wall
    b.openings.append(b.openings[1].model_copy(update={"id": "OX"}))  # on top of another
    b.levels[0].height = 2.5
    b.origin = [-1.29, 36.82]
    d.info.boundary = [list(B.to_latlon(b, x, y)) for x, y in ((-1, -1), (11, -1), (11, 9), (-1, 9))]
    codes = {i["code"] for i in validate.validate(d)}
    assert {"bld_opening_outside", "bld_opening_overlap", "bld_headroom", "bld_setback"} <= codes
    d.info.boundary = [list(B.to_latlon(b, x, y)) for x, y in ((2, 2), (5, 2), (5, 5), (2, 5))]
    assert "bld_outside_plot" in {i["code"] for i in validate.validate(d)}
    with pytest.raises(ValidationError):
        B.Wall(id="X", a=[0, 0], b=[1e6, 0])  # further than 10 km


def test_plans_report_and_package_are_the_buildings():
    d = house(width=12, depth=9, floors=2, roof="gable")
    d.info.name = "Test house"
    st = stamp(d, 1)
    pages = PdfReader(io.BytesIO(plans.build_plans_pdf(d, st))).pages
    text = " ".join(p.extract_text() for p in pages)
    assert len(pages) == 3 and "Ground floor plan" in text and "Floor 1 plan" in text and "South (front) elevation" in text
    assert "12.00 m" in text and "Scale 1:" in text
    titles = [s.title for s in report.sections(d)]
    assert titles[2] == "2. The Building" and "FTTH" not in " ".join(titles)
    with zipfile.ZipFile(io.BytesIO(package.build_package(d, st, None))) as z:
        folders = {n.split("/")[0] for n in z.namelist()}
    assert "02_Plans" in folders and not {"01_HLD", "02_LLD", "06_Splicing"} & folders
    assert "plans" not in package.relevant(Design())  # network projects keep their drawings


@pytest.mark.django_db
def test_construction_company_projects_design_buildings_through_the_api():
    u = User.objects.create_user("builder", password="pw-12345-long")
    co = Company.objects.create(name="Build Co", sector="construction")
    Membership.objects.create(user=u, company=co, role="owner")
    Profile.objects.update_or_create(user=u, defaults={"active_company": co})
    c = Client()
    c.force_login(u)
    st = c.post("/api/projects", {}, content_type="application/json").json()
    assert st["sector"]["construction"] is True and st["design"]["info"]["name"] == "New construction / buildings project"
    assert "plans" in st["outputs"] and "lld" not in st["outputs"]
    r = c.post(f"/api/projects/{st['id']}/building/generate", {"width": 14, "depth": 10, "floors": 2, "roof": "hip"},
               content_type="application/json")
    assert r.status_code == 200, r.json()
    st = r.json()
    assert st["result"]["levels"] == 2 and len(st["design"]["building"]["walls"]) > 8
    assert any(ln["code"] == "CONC-SLAB" for ln in c.get(f"/api/projects/{st['id']}/calc").json()["bom"])
    # manual edits save like any other change: move a wall, add a column
    d = st["design"]
    d["building"]["origin"] = [-1.29, 36.82]
    d["building"]["columns"].append({"id": "C900", "level": 0, "x": 2, "y": 2, "size": 0.3})
    st = c.put(f"/api/projects/{st['id']}", d, content_type="application/json", HTTP_X_BASE_HASH=st["hash"]).json()
    assert st["design"]["building"]["columns"][-1]["id"] == "C900" and st["design"]["building"]["origin"] == [-1.29, 36.82]
    # a new design keeps the place on the map
    st = c.post(f"/api/projects/{st['id']}/building/generate", {"floors": 1}, content_type="application/json").json()
    assert st["design"]["building"]["origin"] == [-1.29, 36.82]
    assert c.post(f"/api/projects/{st['id']}/building/generate", {"floors": 0},
                  content_type="application/json").status_code == 400
    assert c.get(f"/api/projects/{st['id']}/export/plans.pdf").status_code == 200


@pytest.mark.django_db
def test_a_construction_company_gets_a_building_planner():
    from ftth import assistant
    u = User.objects.create_user("builder2", password="pw-12345-long")
    co = Company.objects.create(name="Build Co", sector="construction")
    Membership.objects.create(user=u, company=co, role="owner")
    Profile.objects.update_or_create(user=u, defaults={"active_company": co})
    c = Client()
    c.force_login(u)
    # the sample is a building on its plot, not a fibre network
    st = c.post("/api/projects", {"sample": True}, content_type="application/json").json()
    d = st["design"]
    assert st["sector"]["construction"] and d["building"]["walls"] and d["info"]["boundary"] and not d["cables"]
    assert st["summary"]["building"]["floors"] == 2 and st["counts"]["errors"] == 0
    # the review page shows floors and floor area, not homepasses and FATs
    p = Design.model_validate(d)
    p.info.design_status = "in_review"
    st = c.put(f"/api/projects/{st['id']}", p.model_dump(mode="json"), content_type="application/json",
               HTTP_X_BASE_HASH=st["hash"]).json()
    page = c.get("/review/?show=all").content.decode()
    assert "gross floor area" in page and "doors / windows" in page and "homepasses" not in page
    # the assistant is told it is a building and given the building's figures
    p = Design.model_validate(st["design"])
    assert "building design" in assistant._system(p) and "FTTH" not in assistant._system(p)
    ctx = assistant.project_context(p)
    assert '"floors":2' in ctx and "homepasses" not in ctx


def test_bigger_buildings_get_a_corridor_with_rooms_off_it():
    d = house(width=60, depth=18, floors=6, floor_height=4.0, rooms_x=14, use="hospital", roof="flat")
    b = d.building
    names = [r.name for r in b.rooms if r.level == 1]
    assert names.count("Ward") >= 20 and "Corridor" in names and "Lift and lobby" in names and "Nurse station" in names
    assert "Reception" in [r.name for r in b.rooms if r.level == 0]
    # every room on a floor opens onto the corridor: a door in a corridor wall per room
    corr = [w for w in b.walls if w.level == 1 and w.kind == "internal" and abs(w.a[1] - w.b[1]) < 1e-6
            and abs(w.b[0] - w.a[0]) > 50]
    assert len(corr) == 2
    doors = sum(1 for o in b.openings if o.kind == "door" and o.wall in {w.id for w in corr})
    assert doors == len([r for r in b.rooms if r.level == 1 and r.name != "Corridor"])
    assert sum(1 for s in b.stairs if s.level == 0) == 2  # two ways out of a 60 m block
    assert not [i for i in B.check(b) if i["severity"] in ("error", "warning")]
    # small buildings and houses stay a few rooms opening into each other
    small = house(width=12, depth=9, floors=1).building
    assert "Corridor" not in [r.name for r in small.rooms]
    home = house(width=20, depth=10, floors=2, use="house").building
    assert "Corridor" not in [r.name for r in home.rooms] and "Living room" in [r.name for r in home.rooms]
    pdf = PdfReader(io.BytesIO(plans.build_plans_pdf(d, stamp(d, 1))))
    assert "WARD" in pdf.pages[1].extract_text() and "Corridor" in pdf.pages[1].extract_text()
