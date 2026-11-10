"""Design scripts: projects built from lines of commands, all or nothing, within the member's occupation."""
import re
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.test import Client

from ftth import dam as D, occupations, script, sectors
from ftth.model import Design
from planner.models import Company, Membership, Profile

EXAMPLES = Path(__file__).resolve().parents[1] / "planner/static/planner/script.js"


def _example(kind: str) -> str:
    js = EXAMPLES.read_text(encoding="utf-8")
    return re.search(kind + r": `(.*?)`", js, re.S).group(1)


def _design(sector: str) -> Design:
    d = Design()
    sectors.apply(d, sector)
    return d


def test_the_network_example_builds_a_network():
    d = _design("fibre")
    log = script.run(d, _example("network"), occupations.features("fibre", ""))
    assert {p.id for p in d.poles} == {"P001", "P002"} and d.homes[0].units == 4
    fat = d.node("FAT01")
    assert fat.pole == "P002" and fat.ports == 8 and d.node("POP01").kind == "POP"
    c = d.cables[0]
    assert (c.kind, c.cores, c.from_node, [v.pole for v in c.path]) == ("main", 48, "POP01", [None, "P001", "P002"])
    assert d.homes[0].fat == "FAT01" and d.info.cad_scale == 1000 and log[-1] == "11 command(s) run"
    assert re.match(r"Check: 0 errors, [1-9]\d* warnings", log[-2])  # the validator's real counts


def test_the_building_and_dam_examples():
    b = _design("construction")
    script.run(b, _example("building"), occupations.features("construction", ""))
    assert len(b.building.levels) >= 4 and b.building.origin == [-1.2921, 36.8219]
    assert [r.name for r in b.info.site.schedule] == ["Bedroom", "Lounge"] and b.info.site.bearing_capacity == 150
    d = _design("dams")
    script.run(d, _example("dam"), occupations.features("dams", ""))
    assert len(d.dam.axis) == 5 and len(d.dam.reservoir) == 5 and D.design(d.dam)["height"] > 10


def test_errors_name_the_line_and_change_nothing():
    d = _design("fibre")
    with pytest.raises(script.ScriptError, match=r"Line 3: .*no pole, equipment or premise 'P009'"):
        script.run(d, "pole P001 -1.22,36.89\n# a comment\ncable C1 spur 12 P001 > P009", ["network_edit"])
    with pytest.raises(script.ScriptError, match="Line 1: 'building' is for a building project"):
        script.run(d, "building width=10", ["building_design"])
    with pytest.raises(script.ScriptError, match="not part of your occupation"):
        script.run(d, "autodesign", occupations.features("fibre", "splicing_technician"))
    with pytest.raises(script.ScriptError, match="has no wobble"):
        script.run(d, "pole P1 -1.22,36.89 wobble=3", ["network_edit"])


def test_grid_points_and_set():
    d = _design("fibre")
    script.run(d, "pole P001 257110.7,9857710.0\nset rules.cable_extra_pct = 4", occupations.features("fibre", ""))
    p = d.poles[0]
    assert abs(p.lat + 1.2864) < 1e-5 and abs(p.lon - 36.8172) < 1e-5 and d.rules.cable_extra_pct == 4


@pytest.mark.django_db
def test_scripts_through_the_api_are_all_or_nothing(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    co = Company.objects.create(name="Fibre Co", sector="fibre")
    u = User.objects.create_user("scripter", password="x")
    Membership.objects.create(user=u, company=co, role="owner")
    Profile.objects.update_or_create(user=u, defaults={"active_company": co})
    c = Client(HTTP_HOST="localhost")
    c.force_login(u)
    st = c.post("/api/projects", {}, content_type="application/json").json()
    url = f"/api/projects/{st['id']}/script"
    r = c.post(url, {"script": _example("network")}, content_type="application/json")
    assert r.status_code == 200, r.content
    assert len(r.json()["design"]["poles"]) == 2 and r.json()["log"][-1].endswith("command(s) run")
    bad = c.post(url, {"script": "pole P003 -1.22,36.89\nfrobnicate"}, content_type="application/json")
    assert bad.status_code == 400 and bad.json()["line"] == 2
    assert len(c.get(f"/api/projects/{st['id']}").json()["design"]["poles"]) == 2  # P003 was not kept
