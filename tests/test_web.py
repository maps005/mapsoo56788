"""Django web layer: authentication, access control, concurrency, approval and exports."""
import pytest
from django.contrib.auth.models import Permission, User
from django.test import Client


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def login(username, perms=()):
    u = User.objects.create_user(username, password="pw-12345-long")
    for p in perms:
        u.user_permissions.add(Permission.objects.get(codename=p))
    c = Client()
    c.force_login(u)
    return c


def put(c, pid, design, base):
    return c.put(f"/api/projects/{pid}", design, content_type="application/json", HTTP_X_BASE_HASH=base)


@pytest.mark.django_db
def test_requires_sign_in():
    c = Client()
    assert c.get("/").status_code == 302
    assert c.get("/api/projects").status_code == 401
    assert c.get("/accounts/login/").status_code == 200


@pytest.mark.django_db
def test_page_and_static():
    c = login("ann")
    r = c.get("/")
    assert r.status_code == 200 and b"planner/app.js" in r.content and "csrftoken" in r.cookies


@pytest.mark.django_db
def test_full_flow_and_staleness():
    c = login("ann")
    st = c.post("/api/projects", {"sample": True}, content_type="application/json").json()
    pid = st["id"]
    st = c.post(f"/api/projects/{pid}/assign-homes").json()
    st = c.post(f"/api/projects/{pid}/allocate").json()
    assert st["result"]["issues"] == []
    assert c.get(f"/api/projects/{pid}/export/boq.xlsx").status_code == 200
    assert c.get(f"/api/projects/{pid}").json()["outputs"]["boq"]["stale"] is False
    d = st["design"]
    d["poles"][0]["lat"] += 0.0001
    st = put(c, pid, d, st["hash"]).json()
    assert st["outputs"]["boq"]["stale"] is True
    assert c.get(f"/api/projects/{pid}/calc").json()["boq_total"] > 0
    assert c.get(f"/api/projects/{pid}/splicing?node=PON01").json()["nodes"][0]["connections"]
    r = c.get(f"/api/projects/{pid}/package.zip")
    assert r.status_code in (200, 409)


@pytest.mark.django_db
def test_projects_are_private_until_shared():
    ann, bob = login("ann"), login("bob")
    pid = ann.post("/api/projects", {"name": "A"}, content_type="application/json").json()["id"]
    assert bob.get(f"/api/projects/{pid}").status_code == 404
    assert bob.get("/api/projects").json() == []
    assert bob.post(f"/api/projects/{pid}/share", {"username": "bob"}, content_type="application/json").status_code == 404
    ann.post(f"/api/projects/{pid}/share", {"username": "bob"}, content_type="application/json")
    assert bob.get(f"/api/projects/{pid}").status_code == 200
    assert bob.delete(f"/api/projects/{pid}").status_code == 403  # members cannot delete


@pytest.mark.django_db
def test_concurrent_edit_is_refused():
    ann, bob = login("ann"), login("bob")
    st = ann.post("/api/projects", {"sample": True}, content_type="application/json").json()
    pid, base = st["id"], st["hash"]
    ann.post(f"/api/projects/{pid}/share", {"username": "bob"}, content_type="application/json")
    d = st["design"]
    d["info"]["area"] = "Ann's edit"
    assert put(ann, pid, d, base).status_code == 200
    d["info"]["area"] = "Bob's edit from a stale copy"
    r = put(bob, pid, d, base)
    assert r.status_code == 409 and r.json()["conflict"] and "ann" in r.json()["detail"]


@pytest.mark.django_db
def test_approval_needs_permission_and_resets_on_change():
    planner = login("pat")
    st = planner.post("/api/projects", {"sample": True}, content_type="application/json").json()
    pid = st["id"]
    planner.post(f"/api/projects/{pid}/assign-homes")
    planner.post(f"/api/projects/{pid}/allocate")
    r = planner.post(f"/api/projects/{pid}/revisions", {"note": "x", "design_status": "approved"},
                     content_type="application/json")
    assert r.status_code == 403

    from planner.models import Project
    approver = login("eve", perms=["approve_design"])
    Project.objects.get(pk=pid).members.add(User.objects.get(username="eve"))
    st = approver.post(f"/api/projects/{pid}/revisions", {"note": "issue", "design_status": "approved"},
                       content_type="application/json").json()
    assert st["design"]["info"]["design_status"] == "approved"
    revs = approver.get(f"/api/projects/{pid}/revisions").json()
    assert revs[0]["author"] == "eve" and revs[0]["status"] == "approved"
    d = st["design"]
    d["homes"][0]["units"] = 3
    st = put(approver, pid, d, st["hash"]).json()
    assert st["design"]["info"]["design_status"] == "draft"


@pytest.mark.django_db
def test_photo_upload_is_private(tmp_path):
    from io import BytesIO
    from PIL import Image
    ann, bob = login("ann"), login("bob")
    pid = ann.post("/api/projects", {"name": "A"}, content_type="application/json").json()["id"]
    fake = BytesIO(b"<html><script>alert(1)</script></html>")
    fake.name = "evil.png"
    assert ann.post(f"/api/projects/{pid}/photos", {"file": fake}).status_code == 400
    png = BytesIO()
    Image.new("RGB", (8, 8), "red").save(png, "PNG")
    png.seek(0)
    png.name = "site.png"
    st = ann.post(f"/api/projects/{pid}/photos", {"file": png, "caption": "Pole P001"}).json()
    name = st["design"]["photos"][0]["file"]
    assert ann.get(f"/api/projects/{pid}/photos/{name}").status_code == 200
    assert bob.get(f"/api/projects/{pid}/photos/{name}").status_code == 404


@pytest.mark.django_db
def test_legacy_import(tmp_path):
    import sqlite3
    from django.core.management import call_command
    from ftth.sample import sample_design
    from planner.models import Project
    db = tmp_path / "ftth.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT, data TEXT, updated TEXT)")
    con.execute("CREATE TABLE revisions (project_id TEXT, version INTEGER, created TEXT, author TEXT, note TEXT, "
                "status TEXT, hash TEXT, data TEXT)")
    d = sample_design()
    con.execute("INSERT INTO projects VALUES ('abc123', ?, ?, '')", (d.info.name, d.model_dump_json()))
    con.execute("INSERT INTO revisions VALUES ('abc123', 1, '', 'x', 'first', 'draft', ?, ?)",
                (d.content_hash(), d.model_dump_json()))
    con.commit()
    con.close()
    User.objects.create_user("ann")
    call_command("import_legacy", db=str(db), owner="ann")
    p = Project.objects.get(pk="abc123")
    assert p.name == d.info.name and p.revisions.count() == 1


@pytest.mark.django_db
def test_auto_design_endpoint():
    c = login("ann")
    st = c.post("/api/projects", {"sample": True}, content_type="application/json").json()
    r = c.post(f"/api/projects/{st['id']}/auto-design", {}, content_type="application/json")
    assert r.status_code == 200
    j = r.json()
    assert j["result"]["allocation_issues"] == [] and j["counts"]["errors"] == 0
    assert c.post(f"/api/projects/{st['id']}/auto-design", {"take_rate": 5}, content_type="application/json").status_code == 400


@pytest.mark.django_db
def test_map_tiles_are_allowed():
    """OpenStreetMap refuses tile requests without a Referer, and the CSP must allow its tile host."""
    r = login("ann").get("/")
    assert r["Referrer-Policy"] == "strict-origin-when-cross-origin"
    csp = r["Content-Security-Policy"]
    assert "https://tile.openstreetmap.org" in csp and "basemaps.cartocdn.com" in csp


@pytest.mark.django_db
def test_long_operation_does_not_overwrite_a_save_made_meanwhile(monkeypatch):
    """Auto-design runs outside the database lock; if the project changed meanwhile, its result is refused."""
    from ftth import autodesign
    from planner.models import Project
    c = login("ann")
    st = c.post("/api/projects", {"sample": True}, content_type="application/json").json()
    pid = st["id"]
    real = autodesign.auto_design

    def slow_design(d, opt=None):
        p = Project.objects.get(pk=pid)  # another user saves while the design is being computed
        other = p.design
        other.info.area = "Saved by Bob meanwhile"
        p.set_design(other)
        p.save()
        return real(d, opt)
    monkeypatch.setattr(autodesign, "auto_design", slow_design)
    r = c.post(f"/api/projects/{pid}/auto-design", {}, content_type="application/json")
    assert r.status_code == 409 and r.json()["conflict"]
    assert Project.objects.get(pk=pid).design.info.area == "Saved by Bob meanwhile"
