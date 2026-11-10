"""Occupations: each company member sees and changes only their own trade's tools and deliverables."""
import copy

import pytest
from django.contrib.auth.models import User
from django.test import Client

from ftth import occupations as O
from ftth.exporters import package
from ftth.model import Design
from planner.models import Company, Membership, Profile


def test_features_follow_the_sector_then_the_occupation():
    assert "splicing" in O.features("fibre", "") and "splicing" not in O.features("water", "")
    assert set(O.features("construction", "architect")) == {"map", "building_design", "building_view", "report"}
    assert set(O.features("construction", "structural_engineer")) == {"building_view", "structure"}
    assert set(O.features("fibre", "splicing_technician")) == {"map", "splicing", "cad"}
    # an occupation of another sector (a fibre project in a construction company) keeps the sector's tools
    assert O.features("fibre", "architect") == O.features("fibre", "")
    assert [k for k, _ in O.for_sector("construction")] == ["all", "architect", "structural_engineer", "quantity_surveyor"]


def test_deliverables_and_changes_by_occupation():
    rel = package.relevant(Design(info={"sector": "construction"}))
    arch = O.deliverables(rel, O.features("construction", "architect"))
    struct = O.deliverables(rel, O.features("construction", "structural_engineer"))
    qs = O.deliverables(rel, O.features("construction", "quantity_surveyor"))
    assert {"plans", "schedules", "ifc", "report"} <= set(arch) and not {"calcs", "bbs", "boq"} & set(arch)
    assert {"calcs", "bbs", "plans", "ifc"} <= set(struct) and not {"boq", "report"} & set(struct)
    assert {"bom", "boq", "bbs"} <= set(qs) and "calcs" not in qs
    assert {"qa", "project"} <= set(arch) & set(struct) & set(qs)  # everyone's
    old, new = {"materials": [1], "building": {"a": 1}}, {"materials": [2], "building": {"a": 2}}
    assert O.forbidden_changes(old, new, O.features("construction", "architect")) == ["materials"]
    assert O.forbidden_changes(old, new, O.features("construction", "quantity_surveyor")) == ["building"]


def _member(company, name, occupation, role="planner"):
    u = User.objects.create_user(name, password="x")
    Membership.objects.create(user=u, company=company, role=role, occupation=occupation)
    Profile.objects.update_or_create(user=u, defaults={"active_company": company})
    c = Client(HTTP_HOST="localhost")
    c.force_login(u)
    return c


def _put(c, st, change):
    d = copy.deepcopy(st["design"])
    change(d)
    return c.put(f"/api/projects/{st['id']}", d, content_type="application/json", HTTP_X_BASE_HASH=st["hash"])


@pytest.mark.django_db
def test_construction_members_only_get_their_trade(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    co = Company.objects.create(name="Build Co", sector="construction")
    lead = _member(co, "lead", "", role="owner")
    st = lead.post("/api/projects", {"sample": True}, content_type="application/json").json()
    assert st["occupation"]["key"] == "all" and "calcs" in st["outputs"] and "boq" in st["outputs"]
    pid = st["id"]

    arch = _member(co, "arch", "architect")
    sa = arch.get(f"/api/projects/{pid}").json()
    assert sa["occupation"]["label"] == "Architect" and "building_design" in sa["features"]
    assert "plans" in sa["outputs"] and "calcs" not in sa["outputs"] and "boq" not in sa["outputs"]
    assert arch.get(f"/api/projects/{pid}/export/calcs.pdf").status_code == 403
    assert arch.get(f"/api/projects/{pid}/export/plans.pdf").status_code == 200
    r = _put(arch, sa, lambda d: d["materials"][0].update(rate=d["materials"][0]["rate"] + 1))
    assert r.status_code == 403 and "materials" in r.json()["detail"]
    r = _put(arch, sa, lambda d: d["building"].update(rotation=d["building"]["rotation"] + 5))
    assert r.status_code == 200, r.content

    eng = _member(co, "eng", "structural_engineer")
    se = eng.get(f"/api/projects/{pid}").json()
    assert set(se["features"]) == {"building_view", "structure"} and "calcs" in se["outputs"]
    assert eng.get(f"/api/projects/{pid}/export/bbs.xlsx").status_code == 200
    assert _put(eng, se, lambda d: d["building"].update(rotation=d["building"]["rotation"] + 10)).status_code == 403
    assert eng.post(f"/api/projects/{pid}/building/generate", {}, content_type="application/json").status_code == 403
    # the title block and project text are everyone's
    assert _put(eng, se, lambda d: d["info"].update(prepared_by="Eng. Test")).status_code == 200
    # a fibre deliverable does not exist on a building project
    assert lead.get(f"/api/projects/{pid}/export/splicing.pdf").status_code == 404


@pytest.mark.django_db
def test_a_splicing_technician_splices_but_does_not_redesign(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    co = Company.objects.create(name="Fibre Co", sector="fibre")
    lead = _member(co, "fibre-lead", "", role="owner")
    pid = lead.post("/api/projects", {"sample": True}, content_type="application/json").json()["id"]
    tech = _member(co, "splicer", "splicing_technician")
    st = tech.get(f"/api/projects/{pid}").json()
    assert set(st["outputs"]) == {"hld", "lld", "splicing", "qa", "project"}
    assert tech.post(f"/api/projects/{pid}/auto-design", {}, content_type="application/json").status_code == 403
    assert tech.post(f"/api/projects/{pid}/allocate", {}, content_type="application/json").status_code == 200
    assert _put(tech, tech.get(f"/api/projects/{pid}").json(),
                lambda d: d["poles"][0].update(lat=d["poles"][0]["lat"] + 1e-5)).status_code == 403
    assert tech.get(f"/api/projects/{pid}/export/boq.xlsx").status_code == 403
