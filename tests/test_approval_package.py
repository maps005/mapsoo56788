"""An apartment block designed to a Nairobi building-plan application: flats that work, stairs and escape that
meet the code, a preliminary structural design, services, planning compliance and the full drawing set."""
import io
import math

from pypdf import PdfReader

from ftth import building as B, calc, compliance, rates, sectors, services, structure, validate
from ftth.exporters import plans
from ftth.exporters.common import stamp
from ftth.model import Design

LAT, LON = -1.29235, 36.78395


def block():
    d = Design()
    sectors.apply(d, "construction")
    d.building = B.generate(B.AutoParams(width=36, depth=18, floors=8, use="apartments", roof="flat", columns=True,
                                         window_width=1.8, window_height=1.5, flat_width=11))
    return d


def placed():
    d = block()
    dl, dn = 45 / 111195.08, 45 / (111195.08 * math.cos(math.radians(LAT)))
    d.info.boundary = [[LAT, LON], [LAT, LON + dn], [LAT + dl, LON + dn], [LAT + dl, LON]]
    d.building.origin = [LAT + 6 / 111195.08, LON + 4.5 / (111195.08 * math.cos(math.radians(LAT)))]
    d.info.site = B.Site(bearing_capacity=250, geotech_report="GI test", max_coverage=35, max_plot_ratio=1000,
                         max_floors=15, setback_front=6, setback_side=3, setback_rear=3, parking_per_unit=0.5)
    return d


def test_every_room_of_a_flat_opens_off_its_hall():
    b = block().building
    flats = {}
    for r in b.rooms:
        if r.unit:
            flats.setdefault(r.unit, []).append(r)
    assert len(flats) == 47
    for unit, rooms in flats.items():
        hall = next(r for r in rooms if r.name.startswith("Hall"))
        for r in rooms:
            if r is hall:
                continue
            # the room's door point lies on the hall's edge: it opens off the hall
            x0, y0, x1, y1 = hall.rect
            assert x0 - 0.01 <= r.door[0] <= x1 + 0.01 and y0 - 0.01 <= r.door[1] <= y1 + 0.01, (unit, r.name)
    names = {r.name for r in b.rooms if r.unit}
    assert {"Living / kitchen", "Bedroom", "Bathroom", "Shower room", "Hall"} <= names


def test_stairs_have_landings_and_every_stair_has_its_own_exit():
    d = block()
    b = d.building
    for s in b.stairs:
        flights, landing = B.stair_flights(b, s)
        assert s.flights == 2 and landing and max(f[3] for f in flights) <= 16
    f = compliance.figures(d)
    assert f["stairs"] == 2 and f["stair_exits"] == 2 and f["firefighting_lift"]
    assert not [i for i in B.check(b) if i["code"] == "bld_stair_flight"]


def test_the_frame_is_designed_and_measured():
    d = placed()
    dz = structure.design(d.building, 250)
    assert dz and dz["slab"] >= 0.15 and dz["beam_y"]["h"] >= dz["beam_y"]["span"] / 12 - 1e-6
    assert max(max(c["sizes"]) for c in dz["columns"]) >= 0.35  # the ground-floor columns of 8 storeys
    assert dz["foundation"]["type"] in ("pads", "raft")
    q = {c: v for c, v, _ in B.quantities(d.building, 250)}
    assert q["CONC-BEAM"] > 100 and q["CONC-COLUMN"] > 50


def test_services_and_planning_figures():
    d = placed()
    L = services.layout(d)
    assert L["sewer_m"] > 0 and L["water"]["underground"] > 0 and L["fire"]["travel"] <= L["fire"]["limit"]
    f = compliance.figures(d)
    assert 30 < f["coverage"] < 35 and 250 < f["plot_ratio"] < 260 and f["setbacks"]["front"] == 6.0
    assert "plan_parking" in {i["code"] for i in compliance.check(d)}  # no parking yet: 24 spaces required
    d.building.landscape.append(B.Landscape(id="P1", kind="parking", points=[[-4.5, 20.5], [35.5, 20.5], [35.5, 25.5], [-4.5, 25.5]]))
    d.building.landscape.append(B.Landscape(id="P2", kind="parking", points=[[-4.5, 31.5], [35.5, 31.5], [35.5, 36.5], [-4.5, 36.5]]))
    assert compliance.figures(d)["parking_provided"] == 32 and "plan_parking" not in {i["code"] for i in compliance.check(d)}


def test_the_priced_package_is_in_the_benchmark_and_complete():
    d = placed()
    d.building.landscape.append(B.Landscape(id="P1", kind="parking", points=[[-4.5, 20.5], [35.5, 20.5], [35.5, 25.5], [-4.5, 25.5]]))
    d.building.landscape.append(B.Landscape(id="P2", kind="parking", points=[[-4.5, 31.5], [35.5, 31.5], [35.5, 36.5], [-4.5, 36.5]]))
    rates.fill(d)
    bom = calc.bom(d)
    assert all(ln.rate for ln in bom if ln.qty)
    # the building (external works and utilities apart, as the benchmark is), with preliminaries, contingency, VAT
    from ftth.exporters.report import EXTERNAL_CODES, project_cost
    building = sum(ln.total or 0 for ln in bom if ln.qty and ln.code not in EXTERNAL_CODES)
    per_m2 = project_cost(building)["whole"] / 5184
    assert 60_000 < per_m2 < 85_000
    assert not [i for i in validate.validate(d) if i["severity"] == "error"]
    pdf = PdfReader(io.BytesIO(plans.build_plans_pdf(d, stamp(d, 1))))
    text = " ".join(p.extract_text() for p in pdf.pages)
    for sheet in ("Site plan", "Foundation plan", "Structural layout", "Roof plan", "Drainage and water plan",
                  "Fire safety plan", "Section A-A", "Section B-B", "South (front) elevation", "Schedules and compliance",
                  "LOCATION PLAN", "PLANNING FIGURES", "COLUMN SCHEDULE", "DOOR AND WINDOW SCHEDULE"):
        assert sheet in text, sheet
