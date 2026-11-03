"""Dams sector: an earthfill dam designed from the survey and hydrology, its quantities, checks and deliverables."""
import io
import math

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pypdf import PdfReader

from ftth import calc, dam as D, rates, sectors, validate
from ftth.exporters import damdocs, package
from ftth.exporters.common import stamp
from ftth.model import Design
from planner.models import Company, Membership, Profile


def valley(**kw):
    axis = [[c, 1500 + (abs(c - 140) / 140) ** 1.6 * 22, 1.5 + 2 * (1 - abs(c - 140) / 140)] for c in range(0, 301, 20)]
    res = [[1500 + lv, 260000 * (lv / 20) ** 2.2] for lv in range(0, 23, 2)]
    args = dict(axis=axis, reservoir=res, catchment_km2=18, stream_km=7, stream_slope=1.8, rain_24h=110, rain_annual=750,
                runoff_flood=0.45, runoff_annual=0.08, demand=1500, fsl=1515.0)
    args.update(kw)
    return D.Dam(**args)


def test_capacity_is_the_prismoidal_volume():
    dm = D.Dam(reservoir=[[100, 0], [102, 10000], [104, 40000]])
    cap = D.capacity(dm)
    assert cap[0][2] == 0 and abs(cap[1][2] - 10000 / 3 * 2) < 1  # a cone from 0 to 10,000 m2 over 2 m
    v2 = 2 * (10000 + 40000 + math.sqrt(10000 * 40000)) / 3
    assert abs(cap[2][2] - cap[1][2] - v2) < 1


def test_the_design_follows_the_methods():
    z = D.design(valley())
    hy, sp, fb = z["hydrology"], z["spillway"], z["freeboard"]
    tc = 0.0195 * 7000 ** 0.77 * 0.018 ** -0.385
    assert abs(hy["tc_min"] - tc) < 0.1  # Kirpich
    p = 110 * D.growth(1000, 0.35) / D.growth(100, 0.35)  # a high-hazard dam: the 1 in 1000 year storm by EV1
    i = p / 24 * (24 / (tc / 60)) ** (2 / 3)
    assert abs(hy["intensity"] - i) < 0.1  # the printed intensity is the one used
    assert abs(hy["q100"] - 0.278 * 0.45 * i * 18) < 0.2  # Rational with Mononobe intensity
    assert hy["q_check"] > hy["q100"] and z["flood"]["T_check"] == 10000
    low = D.design(valley(hazard="low"))
    assert low["hydrology"]["q100"] < hy["q100"] and low["flood"]["T_design"] == 100
    assert 0 <= sp["width"] * sp["C"] * sp["h100"] ** 1.5 - hy["q100"] < sp["C"] + 0.1  # the weir carries the flood (B to the metre)
    assert sp["h100"] <= 1.0 + 1e-6 and sp["width"] >= 5
    assert z["crest"] >= max(fb["normal"], fb["flood"], fb["check"]) and z["crest"] - z["mfl"] >= 0.5
    assert z["crest_width"] >= max(4.0, z["height"] / 5 + 3 - 0.01)  # USBR
    assert all(s["ok"] for s in z["stability"]) and len(z["stability"]) == 6
    assert {s["case"] for s in z["stability"]} >= {"Rapid drawdown", "Earthquake, full reservoir (pseudo-static)"}
    assert z["core_top_level"] >= z["fsl"] + sp["h_check"] + 0.2 - 1e-6  # the core holds the check flood
    assert z["mol"] >= z["sediment"]["level"] + 1.0 - 1e-6  # the intake above 50 years of sediment
    assert sp["y2"] > sp["y1"] and abs(sp["basin_len"] - max(6.0, 4.5 * sp["y2"])) < 0.1  # the jump in the basin
    assert z["riprap"]["thickness"] >= 2 * z["riprap"]["d50"] - 1e-6 and z["foundation_height"] > z["height"]
    assert z["volumes"]["total"] > z["volumes"]["core"] + z["volumes"]["shell"] * 0.5
    ends = [s for s in z["sections"] if s["ground"] <= z["crest"] + 1e-6]
    assert abs(ends[0]["ground"] - z["crest"]) < 1e-6 and abs(ends[-1]["ground"] - z["crest"]) < 1e-6  # to the abutments


def test_weak_shells_get_flatter_slopes():
    strong, weak = D.design(valley(shell_phi=32)), D.design(valley(shell_phi=22, shell_c=2))
    assert weak["slope_us"] > strong["slope_us"] or weak["slope_ds"] > strong["slope_ds"]
    assert all(s["ok"] for s in weak["stability"])


def test_checks_catch_a_dam_that_does_not_fit_its_site():
    dm = valley(fsl=1521.5)  # the crest would rise above the surveyed abutments
    codes = {c for _, c, _ in D.check(dm)}
    assert "dam_abutments" in codes
    assert {c for _, c, _ in D.check(valley(demand=20000))} >= {"dam_yield"}
    assert {c for _, c, _ in D.check(D.Dam())} == {"dam_no_survey"}


def test_a_large_dam_is_measured_from_its_foundation():
    def dam(firm):
        return D.Dam(axis=[[c, 1500 + (abs(c - 140) / 140) ** 1.6 * 14, firm] for c in range(0, 301, 20)],
                     reservoir=[[1500 + lv, 200000 * (lv / 12) ** 2] for lv in range(0, 15, 2)], catchment_km2=8, stream_km=4,
                     stream_slope=2, rain_24h=100, rain_annual=700, demand=300, fsl=1508.0)
    shallow, deep = D.design(dam(1.0)), D.design(dam(6.0))
    assert shallow["height"] < 15 and not shallow["large_dam"]
    assert deep["height"] < 15 <= deep["foundation_height"] and deep["large_dam"]  # ICOLD: from the lowest foundation


def test_dam_quantities_reach_the_boq_and_the_deliverables():
    d = Design()
    sectors.apply(d, "dams")
    d.info.name = "Dam test"
    d.dam = valley()
    rates.fill(d)
    bom = calc.bom(d)
    codes = {ln.code for ln in bom}
    assert {"DAM-CORE", "DAM-SHELL", "DAM-FILTER", "DAM-RIPRAP", "CUTOFF-EXC", "SPILL-CONC", "OUTLET-PIPE-300",
            "SEEPAGE-WEIR", "INVESTIGATIONS", "LAND-COMP", "SPILL-FORMWORK"} <= codes
    assert all(ln.rate for ln in bom if ln.qty)
    z = D.design(d.dam)
    core = next(ln for ln in bom if ln.code == "DAM-CORE")
    assert abs(core.qty - (z["volumes"]["core"] + z["volumes"]["cutoff"])) < 1
    assert not [i for i in validate.validate(d) if i["severity"] == "error"]
    assert package.relevant(d) == ["dam_drawings", "dam_report", "bom", "boq", "qa", "project"]
    st = stamp(d, 1)
    draw = PdfReader(io.BytesIO(damdocs.drawings_pdf(d, st)))
    text = "".join(p.extract_text() for p in draw.pages)
    assert len(draw.pages) == 5 and "LONG SECTION ON THE DAM AXIS" in text and "MAXIMUM CROSS-SECTION" in text
    rep = "".join(p.extract_text() for p in PdfReader(io.BytesIO(damdocs.report_pdf(d, st))).pages)
    assert "Rational" in rep and "Bishop" in rep and "Molitor" in rep and "Water Resources Authority" in rep
    assert "Hudson" in rep and "Stilling basin" in rep and "VAT" in rep and "Detailed design still to do" in rep
    from openpyxl import load_workbook
    from ftth.exporters import excel
    ws = load_workbook(io.BytesIO(excel.vsquared_boq_xlsx(d, st))).active
    assert "FTTH" not in " ".join(str(c.value) for row in ws.iter_rows(max_row=12) for c in row if c.value)


@pytest.mark.django_db
def test_dam_projects_through_the_api(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    u = User.objects.create_user("dam-eng", password="x")
    co = Company.objects.create(name="Dam Co", sector="dams")
    Membership.objects.create(user=u, company=co, role="owner")
    Profile.objects.update_or_create(user=u, defaults={"active_company": co})
    c = Client(HTTP_HOST="localhost")
    c.force_login(u)
    st = c.post("/api/projects", {}, content_type="application/json").json()
    assert st["sector"]["dam"] is True and "dam_drawings" in st["outputs"] and "plans" not in st["outputs"]
    d = st["design"]
    d["dam"] = valley().model_dump()
    r = c.put(f"/api/projects/{st['id']}", d, content_type="application/json", HTTP_X_BASE_HASH=st["hash"])
    assert r.status_code == 200, r.content
    z = r.json()["summary"]["dam"]
    assert z["designed"] and z["height"] > 10 and z["profile"] and z["capacity"]
    pdf = c.get(f"/api/projects/{st['id']}/export/dam_drawings.pdf")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
