"""The workflow gaps: the site survey and client brief (step 1), building model checks (step 2), indicative rates
for every sector (step 4) and the report's site, brief and cost sections (step 6)."""
import pytest
from django.contrib.auth.models import User
from django.test import Client

from ftth import ai_edits, building as B, calc, rates, sectors, validate
from ftth.exporters import report
from ftth.model import Design
from planner.models import Company, Membership, Profile


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def office():
    d = Design()
    sectors.apply(d, "construction")
    d.building = B.generate(B.AutoParams(width=30, depth=12, floors=3, use="office", roof="flat"))
    return d


def codes(d):
    return {i["code"] for i in validate.validate(d)}


def test_the_design_is_checked_against_the_ground_and_the_brief():
    d = office()
    assert "bld_no_ground" in codes(d)
    d.info.site = B.Site(soil="black cotton", bearing_capacity=40, water_table=0.8, slope=14, budget=1000,
                         schedule=[{"name": "Office", "count": 40, "area": 30}, {"name": "Toilets", "count": 1}])
    c = codes(d)
    assert {"bld_soil", "bld_bearing", "bld_water_table", "bld_slope", "bld_brief_rooms", "bld_brief_area"} <= c
    assert "bld_no_ground" not in c and "bld_budget" not in c  # the budget waits for a priced BOQ
    rates.fill(d)
    assert "bld_budget" in codes(d)
    d.info.site = B.Site(soil="murram / gravel", bearing_capacity=250, water_table=6, budget=10 ** 10,
                         schedule=[{"name": "Office", "count": 2}])
    assert not {"bld_soil", "bld_bearing", "bld_water_table", "bld_budget", "bld_brief_rooms"} & codes(d)


def test_a_wall_drawn_twice_is_caught():
    d = office()
    w = d.building.walls[0]
    d.building.walls.append(w.model_copy(update={"id": "W999", "a": w.a, "b": [(w.a[0] + w.b[0]) / 2, w.b[1]]}))
    assert "bld_wall_overlap" in codes(d)
    assert "bld_wall_overlap" not in codes(office())


def test_every_sector_gets_indicative_rates_without_losing_its_own_prices():
    for key, sec in sectors.SECTORS.items():
        if not sec.get("materials"):
            continue
        d = Design()
        sectors.apply(d, key)
        d.materials[0].rate = 123.0  # the company's own price
        d.materials = d.materials[:-1]  # and one item missing from the project
        r = rates.fill(d)
        assert d.materials[0].rate == 123.0 and d.materials[0].code not in r["filled"]
        assert len(r["added"]) == 1 and all(m.rate > 0 for m in d.materials), key
    d = office()
    rates.fill(d)
    bom = calc.bom(d)
    assert all(ln.rate for ln in bom if ln.qty) and calc.boq_total(bom) > 1_000_000
    d.info.currency = "USD"
    with pytest.raises(rates.RateError):
        rates.fill(d)


def test_the_report_has_the_site_the_brief_and_the_cost_per_m2():
    d = office()
    rates.fill(d)
    d.info.site = B.Site(soil="clay", bearing_capacity=150, client_brief="Offices for 120 staff", budget=5e7,
                         schedule=[{"name": "Office", "count": 10, "area": 12}])
    secs = {s.title: s for s in report.sections(d)}
    assert "2. Site and Brief" in secs and "5. Quality Checks and Recommendations" in secs
    text = repr(secs["2. Site and Brief"].__dict__)
    assert "clay" in text and "150 kN/m²" in text and "Offices for 120 staff" in text and "Office" in text
    assert "Cost per m²" in repr(report.sections(d)[0].__dict__)


def test_the_assistant_can_record_the_brief_and_price_the_boq():
    d = office()
    ai_edits.apply(d, [{"op": "set_site", "soil": "sand", "client_brief": "A clinic", "schedule": [{"name": "Office", "count": 3}]},
                       {"op": "fill_rates"}])
    assert d.info.site.soil == "sand" and d.info.site.schedule[0].count == 3 and all(m.rate for m in d.materials)
    with pytest.raises(ai_edits.EditError):
        ai_edits.apply(d, [{"op": "set_site", "soil": "lava"}])


@pytest.mark.django_db
def test_the_fill_rates_button_prices_the_project():
    u = User.objects.create_user("rates-user", password="pw-12345-long")
    co = Company.objects.create(name="Build Co", sector="construction")
    Membership.objects.create(user=u, company=co, role="owner")
    Profile.objects.update_or_create(user=u, defaults={"active_company": co})
    c = Client()
    c.force_login(u)
    pid = c.post("/api/projects", {}, content_type="application/json").json()["id"]
    r = c.post(f"/api/projects/{pid}/indicative-rates")
    assert r.status_code == 200, r.json()
    assert len(r.json()["rates"]["filled"]) >= 40 and all(m["rate"] > 0 for m in r.json()["design"]["materials"])
    assert c.post(f"/api/projects/{pid}/indicative-rates").json()["rates"]["filled"] == []
