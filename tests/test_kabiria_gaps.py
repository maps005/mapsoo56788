"""Kabiria-style projects: same-pole equipment, folder-driven import, coverage FATs, several interceptions."""
import pytest

from ftth import autodesign, splicing, validate
from ftth.importers import Report, classify, import_rows
from ftth.model import Cable, Design, Home, Node, Pole, Splitter, Vertex

from test_agent_findings import client, street


def pt(path, name):
    return classify({"path": path, "name": name, "geom": "point", "ext": {}})


def test_equipment_on_one_pole_is_one_site_and_shares_the_closure_splitter():
    d = street(n=3)
    d.nodes += [Node(id="SC 1", kind="ENCLOSURE", lat=-1.29, lon=36.82 + 40 / 111_320, pole="P01"),
                Node(id="FAT 1A", kind="FAT", lat=-1.29, lon=36.82 + 40 / 111_320, pole="P01", ports=16)]
    d.splitters.append(Splitter(id="SPL 1A", node="SC 1", stage=2, outputs=16))
    site = splicing.site_groups(d)
    assert site("SC 1") == site("FAT 1A") != site("EX SC")
    assert [s.id for s in splicing.site_splitters(d, "FAT 1A", site)] == ["SPL 1A"]


@pytest.mark.parametrize("path,name,want", [
    (["FATS", "16P OUTDOOR PR FAT"], "FAT 1A", {"what": "node", "kind": "FAT", "ports": 16, "status": "proposed"}),
    (["COMMERCIAL"], "JUNCTION BUTCHERY", {"what": "home", "kind": "business"}),
    (["SPLITTERS"], "SPL 1A(1*16)", {"what": "splitter", "stage": 2, "outputs": 16}),
    (["SPLITTERS"], "PON A (1*8)", {"what": "splitter", "stage": 1, "outputs": 8, "pon": "A"}),
    (["VSQ POLES"], "VSQ 12", {"what": "pole", "status": "proposed"}),
    (["JB"], "BDB0025 PON A(1*8)", {"what": "node", "kind": "JB", "notes": "PON A"}),
    (["POLES", "KPTX"], "KP 33", {"what": "pole", "status": "existing", "type": "KPTX"}),
    (["MDUS"], "SIWAMA 24HP", {"what": "home", "kind": "mdu", "units": 24}),
])
def test_kabiria_folders_are_read_correctly(path, name, want):
    got = pt(path, name)
    assert {k: got.get(k) for k in want} == want


def test_home_list_rows_match_one_premise_each():
    d = Design()
    d.homes += [Home(id="H1", name="ROSE APTS", lat=-1.29, lon=36.82),
                Home(id="H2", name="LILY APTS", lat=-1.29, lon=36.82 + 8 / 111_320)]
    rows = [{"Name": "LILY APTS", "Latitude": -1.29, "Longitude": 36.82 + 1 / 111_320, "HP": 12},  # nearer H1
            {"Name": "ROSE APTS", "Latitude": -1.29, "Longitude": 36.82 + 6 / 111_320, "HP": 20},
            {"Name": "FAR AWAY", "Latitude": -1.30, "Longitude": 36.83, "HP": 4}]
    rep = Report()
    import_rows(d, rows, "homes", rep)
    h = {x.id: x for x in d.homes}
    assert (h["H1"].units, h["H2"].units) == (20, 12)  # the name decides between two close premises
    assert len(d.homes) == 3 and any("FAR AWAY" in p for p in rep.problems)


def coverage_street(n=10):
    d = street(n=n, step=40.0)
    for k in range(n):
        d.homes.append(Home(id=f"B{k}", lat=-1.2902, lon=36.82 + k * 40 / 111_320, units=60, kind="mdu"))
    return d


def test_coverage_design_uses_16_port_fats_24c_and_take_rate():
    d = coverage_street()
    res = autodesign.auto_design(d, autodesign.Options(**autodesign.PRESETS["coverage"]))
    fats = [n for n in d.nodes if n.kind == "FAT"]
    assert fats and all(n.pole for n in fats)
    assert len(fats) < len(d.homes)  # one FAT covers several buildings at the take rate
    assert {s.outputs for s in d.splitters if s.stage == 2} == {16}
    assert {c.cores for c in d.cables if c.kind == "spur"} == {24}
    assert d.rules.fat_load_take_rate == pytest.approx(0.036)
    assert not res["allocation_issues"]
    assert not [i for i in validate.validate(d) if i["code"] == "fat_capacity"]


def test_several_interceptions_each_feed_the_nearest_pons():
    d = coverage_street(30)  # 1.2 km street: several PONs, one interception at each end
    end = d.poles[-1]
    d.nodes.append(Node(id="EX SC 2", kind="ENCLOSURE", lat=end.lat, lon=end.lon, pole=end.id, status="existing"))
    d.cables.append(Cable(id="EX 48C", kind="main", cores=48, status="existing",
                          path=[Vertex(lat=p.lat, lon=p.lon, pole=p.id) for p in d.poles]))
    d.info.interception_nodes = ["EX SC 2"]
    opt = autodesign.Options(**{**autodesign.PRESETS["coverage"], "coverage_take_rate": 0.2})
    res = autodesign.auto_design(d, opt)
    assert not res["allocation_issues"]
    sources = {c.a.ref for c in d.connections if c.a.kind == "olt"}
    assert {"EX SC", "EX SC 2"} <= sources


@pytest.mark.django_db
def test_auto_design_api_takes_a_style_and_remembers_it(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    c = client()
    st = c.post("/api/projects", {"sample": True}, content_type="application/json").json()
    url = f"/api/projects/{st['id']}/auto-design"
    assert c.post(url, {"preset": "fancy"}, content_type="application/json").status_code == 400
    assert c.post(url, {"fat_split": 10}, content_type="application/json").status_code == 400
    assert c.post(url, {"spur_cores": 24.5}, content_type="application/json").status_code == 400
    r = c.post(url, {"preset": "coverage", "coverage_take_rate": 0.1}, content_type="application/json")
    assert r.status_code == 200
    design = r.json()["design"]
    assert design["info"]["design_style"] == "coverage"
    assert design["rules"]["fat_load_take_rate"] == pytest.approx(0.1)


def jb_line():
    """EX SC -> JB (1x8 PON + 1x16) -> FAT A -> closure -> FAT B along one 24C."""
    d = street(n=5)
    lon = lambda k: 36.82 + k * 40 / 111_320  # noqa: E731
    d.nodes += [Node(id="JB 1", kind="JB", lat=-1.29, lon=lon(1), pole="P01"),
                Node(id="FAT A", kind="FAT", lat=-1.29, lon=lon(2), pole="P02", ports=16),
                Node(id="SC X", kind="ENCLOSURE", lat=-1.29, lon=lon(3), pole="P03"),
                Node(id="FAT B", kind="FAT", lat=-1.29, lon=lon(4), pole="P04", ports=16)]
    d.splitters += [Splitter(id="PON A", node="JB 1", stage=1, outputs=8),
                    Splitter(id="SPL 1A", node="JB 1", stage=2, outputs=16)]
    d.cables += [Cable(id="48C", kind="main", cores=48, path=[Vertex(lat=p.lat, lon=p.lon, pole=p.id) for p in d.poles[:2]]),
                 Cable(id="24C", kind="spur", cores=24, path=[Vertex(lat=p.lat, lon=p.lon, pole=p.id) for p in d.poles[1:]])]
    d.info.interception_node = "EX SC"
    return d


def test_a_1x16_held_in_a_jb_is_fed_and_serves_the_fats_beyond_it():
    d = jb_line()
    r = splicing.auto_allocate(d)
    assert not r["issues"] and r["splitters"] == 0  # no splitter invented for FAT A / FAT B
    assert any(c.b.kind == "splitter_in" and c.b.ref == "SPL 1A" for c in d.connections)
    assert sum("shared splitter" in n for n in r["notes"]) == 2
    assert not [i for i in validate.validate(d) if i["severity"] == "error"]


def test_fats_share_a_fat_splitter_only_when_the_rules_allow():
    d = jb_line()
    d.splitters = [s for s in d.splitters if s.id != "SPL 1A"] + [Splitter(id="SPL A", node="FAT A", stage=2, outputs=16)]
    r = splicing.auto_allocate(d)
    assert r["splitters"] == 1  # FAT B gets its own
    d = jb_line()
    d.splitters = [s for s in d.splitters if s.id != "SPL 1A"] + [Splitter(id="SPL A", node="FAT A", stage=2, outputs=16)]
    d.rules.share_fat_splitters = True
    r = splicing.auto_allocate(d)
    assert r["splitters"] == 0 and any("FAT B takes fibres from SPL A" in n for n in r["notes"])
    assert not [i for i in validate.validate(d) if i["severity"] == "error"]


def test_coverage_puts_one_fat_per_pole_closures_where_the_cable_passes_and_24p_where_dense():
    d = coverage_street(12)
    for k in range(12):  # dense row of buildings: more demand than one box takes
        d.homes.append(Home(id=f"D{k}", lat=-1.2901, lon=36.82 + k * 40 / 111_320, units=200, kind="mdu"))
    autodesign.auto_design(d, autodesign.Options(**autodesign.PRESETS["coverage"]))
    fats = [n for n in d.nodes if n.kind == "FAT"]
    poles = [f.pole for f in fats]
    assert len(poles) == len(set(poles))  # no stacking
    assert 24 in {f.ports for f in fats}
    closure_poles = {n.pole for n in d.nodes if n.kind == "ENCLOSURE" and "FAT closure" in n.notes}
    assert closure_poles and closure_poles <= set(poles)
    spl = {f.id: sum(s.node == f.id for s in d.splitters) for f in fats}
    assert set(spl.values()) == {1}


@pytest.mark.django_db
def test_company_standard_seeds_new_projects_and_can_be_reapplied():
    from django.contrib.auth.models import User
    from django.test import Client

    from planner.models import Company, Membership, Profile
    u = User.objects.create_user("std", password="pw-12345-long")
    co = Company.objects.create(name="V Squared", design_standard="vsquared_coverage")
    Membership.objects.create(user=u, company=co, role="owner")
    Profile.objects.update_or_create(user=u, defaults={"active_company": co})
    c = Client()
    c.force_login(u)
    st = c.post("/api/projects", {"name": "Kabiria"}, content_type="application/json").json()
    d = st["design"]
    assert d["info"]["design_style"] == "coverage"
    assert d["rules"]["cable_extra_pct"] == 0 and d["rules"]["share_fat_splitters"] is True
    assert c.get("/api/defaults").json()["rules"]["default_fat_split"] == 16
    r = c.post(f"/api/projects/{st['id']}/apply-standard", {"standard": "system"}, content_type="application/json")
    assert r.status_code == 200 and r.json()["design"]["rules"]["cable_extra_pct"] == 10
    assert c.post(f"/api/projects/{st['id']}/apply-standard", {"standard": "nope"},
                  content_type="application/json").status_code == 400
