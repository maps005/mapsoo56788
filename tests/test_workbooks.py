"""Data workbooks: a dam's and a building's input data downloaded as Excel, edited, and uploaded back."""
import io

import pytest
from django.contrib.auth.models import User
from django.test import Client
from openpyxl import load_workbook

from ftth import sectors, workbooks as W
from ftth.dam import Dam
from ftth.model import Design
from planner.models import Company, Membership, Profile


def _edit(data: bytes, fn) -> bytes:
    wb = load_workbook(io.BytesIO(data))
    fn(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _set(ws, key, value):
    row = next(r for r in ws.iter_rows(min_row=2) if r[0].value == key)
    row[3].value = value


def test_a_dam_round_trips_through_excel():
    d = Design()
    sectors.apply(d, "dams")
    d.dam = Dam(axis=[[0, 120, 2], [100, 100, 3]], reservoir=[[100, 0], [110, 5e4]], catchment_km2=12)
    data = W.dam_template(d)

    def edit(wb):
        ax = wb["Axis profile"]
        ax.append([200, 118, 1.5])
        _set(wb["Parameters"], "rain_24h", 105)
        _set(wb["Parameters"], "hazard", "significant")
        _set(wb["Parameters"], "slope_us", 99)  # beyond the model's limit: reported, kept as it was
    report = W.import_dam(d, _edit(data, edit))
    assert d.dam.axis[-1] == [200.0, 118.0, 1.5] and len(d.dam.axis) == 3
    assert d.dam.rain_24h == 105 and d.dam.hazard == "significant" and d.dam.catchment_km2 == 12
    assert d.dam.slope_us == 3.0 and any("slope_us" in r for r in report)
    with pytest.raises(ValueError):
        W.import_dam(d, b"not a workbook")


def test_a_building_brief_round_trips_through_excel():
    d = Design()
    sectors.apply(d, "construction")
    d.info.site.soil = "clay"

    def edit(wb):
        _set(wb["Site & brief"], "bearing_capacity", 150)
        _set(wb["Site & brief"], "architect", "Arch. Test")
        wb["Accommodation"].append(["Bedroom", 24, 12])
        wb["Accommodation"].append(["Lounge", 8, 0])
    W.import_building(d, _edit(W.building_template(d), edit))
    s = d.info.site
    assert s.bearing_capacity == 150 and s.architect == "Arch. Test" and s.soil == "clay"
    assert [(r.name, r.count, r.area) for r in s.schedule] == [("Bedroom", 24, 12.0), ("Lounge", 8, 0.0)]


@pytest.mark.django_db
def test_data_workbooks_through_the_api(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    co = Company.objects.create(name="Dam Co", sector="dams")
    users = {}
    for name, occ in (("lead", ""), ("qs", "quantity_surveyor")):
        u = User.objects.create_user(name, password="x")
        Membership.objects.create(user=u, company=co, role="owner" if not occ else "planner", occupation=occ)
        Profile.objects.update_or_create(user=u, defaults={"active_company": co})
        users[name] = c = Client(HTTP_HOST="localhost")
        c.force_login(u)
    lead = users["lead"]
    st = lead.post("/api/projects", {}, content_type="application/json").json()
    r = lead.get(f"/api/projects/{st['id']}/data-template.xlsx")
    assert r.status_code == 200 and "dam data" in r["Content-Disposition"] and ":" not in r["Content-Disposition"].split("filename=")[1]
    filled = _edit(r.content, lambda wb: (wb["Axis profile"].append([0, 1500, 2]), wb["Axis profile"].append([300, 1520, 2]),
                                          wb["Reservoir"].append([1500, 0]), wb["Reservoir"].append([1520, 4e5])))
    up = lead.post(f"/api/projects/{st['id']}/import", {"file": io.BytesIO(filled)})
    assert up.status_code == 400  # a file object without a name is not an .xlsx upload
    f = io.BytesIO(filled)
    f.name = "dam.xlsx"
    up = lead.post(f"/api/projects/{st['id']}/import", {"file": f})
    assert up.status_code == 200, up.content
    assert len(up.json()["design"]["dam"]["axis"]) == 2 and up.json()["import"]["problems"]
    f.seek(0)
    assert users["qs"].post(f"/api/projects/{st['id']}/import", {"file": f}).status_code == 403  # not a QS's data
