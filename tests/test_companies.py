"""Companies, roles, review comments, the projects / review / company / profile pages and the themed admin."""
from io import BytesIO

import pytest
from django.contrib.auth.models import User
from django.test import Client
from PIL import Image

from planner.models import Comment, Company, Membership, Profile, Project


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def user(name, **kw):
    u = User.objects.create_user(name, password="pw-12345-long", **kw)
    c = Client()
    c.force_login(u)
    return u, c


def png():
    b = BytesIO()
    Image.new("RGB", (40, 20), "navy").save(b, "PNG")
    b.seek(0)
    b.name = "logo.png"
    return b


def company_with(roles: dict) -> Company:
    co = Company.objects.create(name="V Squared")
    for u, role in roles.items():
        Membership.objects.create(user=u, company=co, role=role)
    return co


def put(c, pid, design, base):
    return c.put(f"/api/projects/{pid}", design, content_type="application/json", HTTP_X_BASE_HASH=base)


@pytest.mark.django_db
def test_create_company_page_makes_owner_and_new_projects_join_it():
    u, c = user("ann")
    r = c.post("/company/", {"action": "create", "name": "V Squared", "currency": "KES", "phone": "0111 015 500",
                             "logo": png()})
    assert r.status_code == 302
    co = Company.objects.get(name="V Squared")
    assert Membership.objects.get(user=u, company=co).role == "owner" and co.logo
    assert Profile.objects.get(user=u).active_company == co
    st = c.post("/api/projects", {"name": "Kabiria"}, content_type="application/json").json()
    assert Project.objects.get(pk=st["id"]).company == co and st["design"]["info"]["company"] == "V Squared"
    assert st["company"]["name"] == "V Squared" and st["company"]["logo"] == f"/company/{co.id}/logo"
    assert c.get(f"/company/{co.id}/logo").status_code == 200
    assert Client().get(f"/company/{co.id}/logo").status_code == 401


@pytest.mark.django_db
def test_company_roles_control_view_edit_comment_and_approve():
    owner, oc = user("owner")
    viewer, vc = user("vic")
    planner, pc = user("pat")
    approver, ac = user("ali")
    outsider, xc = user("xen")
    co = company_with({owner: "owner", viewer: "viewer", planner: "planner", approver: "approver"})
    st = oc.post("/api/projects", {"sample": True}, content_type="application/json").json()
    pid = st["id"]
    assert Project.objects.get(pk=pid).company == co
    assert xc.get(f"/api/projects/{pid}").status_code == 404           # not a member
    v = vc.get(f"/api/projects/{pid}").json()
    assert v["can_edit"] is False and v["can_approve"] is False
    assert put(vc, pid, v["design"], v["hash"]).status_code == 403      # viewers only read ...
    assert vc.post(f"/api/projects/{pid}/comments", {"text": "Check FAT01 load", "ref": "FAT01"},
                   content_type="application/json").status_code == 200  # ... and comment
    p = pc.get(f"/api/projects/{pid}").json()
    assert p["can_edit"] is True and p["can_approve"] is False and p["comments_open"] == 1
    p["design"]["info"]["area"] = "Kawangware"
    assert put(pc, pid, p["design"], p["hash"]).status_code == 200      # planners correct the design
    pc.post(f"/api/projects/{pid}/assign-homes")
    pc.post(f"/api/projects/{pid}/allocate")
    assert pc.post(f"/api/projects/{pid}/revisions", {"note": "x", "design_status": "approved"},
                   content_type="application/json").status_code == 403
    r = ac.post(f"/api/projects/{pid}/revisions", {"note": "ok", "design_status": "approved"}, content_type="application/json")
    assert r.status_code == 200 and r.json()["design"]["info"]["design_status"] == "approved"
    assert pc.delete(f"/api/projects/{pid}").status_code == 403           # only owner / company admin
    assert oc.delete(f"/api/projects/{pid}").status_code == 200


@pytest.mark.django_db
def test_comments_resolve_rules():
    owner, oc = user("owner")
    viewer, vc = user("vic")
    other, wc = user("wes")
    company_with({owner: "owner", viewer: "viewer", other: "viewer"})
    pid = oc.post("/api/projects", {"sample": True}, content_type="application/json").json()["id"]
    cid = vc.post(f"/api/projects/{pid}/comments", {"text": "Pole P002 is leaning"},
                  content_type="application/json").json()[0]["id"]
    assert wc.post(f"/api/projects/{pid}/comments/{cid}/resolve", {}, content_type="application/json").status_code == 403
    assert vc.post(f"/api/projects/{pid}/comments", {"text": "  "}, content_type="application/json").status_code == 400
    done = oc.post(f"/api/projects/{pid}/comments/{cid}/resolve", {}, content_type="application/json").json()
    assert done[0]["resolved"] is True and done[0]["resolved_by"] == "owner"


@pytest.mark.django_db
def test_review_page_approve_and_return():
    planner, pc = user("pat")
    approver, ac = user("ali")
    company_with({planner: "planner", approver: "approver"})
    pid = pc.post("/api/projects", {"sample": True}, content_type="application/json").json()["id"]
    pc.post(f"/api/projects/{pid}/assign-homes")
    pc.post(f"/api/projects/{pid}/allocate")
    pc.post(f"/api/projects/{pid}/revisions", {"note": "please review", "design_status": "in_review"},
            content_type="application/json")
    page = ac.get("/review/")
    assert page.status_code == 200 and b"please review" in page.content and b"Approve design" in page.content
    assert pc.get("/review/").content.count(b"Approve design") == 0     # planners are not asked to approve
    r = ac.post("/review/", {"project": pid, "action": "return", "text": "Move FAT01 to pole P003"})
    assert r.status_code == 302
    p = Project.objects.get(pk=pid)
    assert p.design.info.design_status == "draft" and p.comments.get().text == "Move FAT01 to pole P003"
    pc.post(f"/api/projects/{pid}/revisions", {"note": "fixed", "design_status": "in_review"}, content_type="application/json")
    ac.post("/review/", {"project": pid, "action": "approve"})
    assert Project.objects.get(pk=pid).design.info.design_status == "approved"
    assert p.revisions.first().author == approver


@pytest.mark.django_db
def test_company_admin_manages_members_details_and_projects():
    owner, oc = user("owner")
    bob, bc = user("bob", email="bob@example.com")
    co = company_with({owner: "owner"})
    oc.post("/company/", {"c": co.id, "action": "add_member", "user": "bob@example.com", "role": "approver"})
    m = Membership.objects.get(user=bob, company=co)
    assert m.role == "approver"
    oc.post("/company/", {"c": co.id, "action": "role", "membership": m.id, "role": "viewer"})
    assert Membership.objects.get(pk=m.id).role == "viewer"
    only = Membership.objects.get(user=owner)
    oc.post("/company/", {"c": co.id, "action": "remove", "membership": only.id})
    assert Membership.objects.filter(pk=only.id).exists()                # the last owner stays
    assert bc.post("/company/", {"c": co.id, "action": "details", "name": "Hacked", "currency": "KES"}).status_code == 302
    assert Company.objects.get(pk=co.id).name == "V Squared"             # viewers cannot change details
    oc.post("/company/", {"c": co.id, "action": "details", "name": "V Squared Ltd", "currency": "KES",
                          "email": "info@vsquared.ke"})
    assert Company.objects.get(pk=co.id).email == "info@vsquared.ke"
    Profile.objects.filter(user=owner).delete()
    Membership.objects.filter(user=owner).delete()
    pid = oc.post("/api/projects", {"name": "Old"}, content_type="application/json").json()["id"]  # personal
    Membership.objects.create(user=owner, company=co, role="owner")
    oc.post("/company/", {"c": co.id, "action": "adopt"})
    assert Project.objects.get(pk=pid).company_id == co.id
    assert oc.get("/company/").status_code == 200 and oc.get("/projects/").status_code == 200


@pytest.mark.django_db
def test_profile_page_details_company_and_password():
    u, c = user("ann")
    co = company_with({u: "planner"})
    r = c.post("/profile/", {"action": "profile", "first_name": "Ann", "last_name": "Wanjiru", "email": "ann@example.com",
                             "job_title": "Planner", "phone": "0700", "active_company": co.id})
    assert r.status_code == 302
    u.refresh_from_db()
    assert u.get_full_name() == "Ann Wanjiru" and Profile.objects.get(user=u).active_company == co
    c.post("/profile/", {"action": "password", "old_password": "pw-12345-long", "new_password1": "N3w-strong-pass!",
                         "new_password2": "N3w-strong-pass!"})
    u.refresh_from_db()
    assert u.check_password("N3w-strong-pass!")
    assert c.get("/profile/").status_code == 200                         # still signed in


@pytest.mark.django_db
def test_admin_uses_the_site_theme():
    User.objects.create_superuser("root", "root@example.com", "pw-12345-long")
    c = Client()
    c.login(username="root", password="pw-12345-long")
    r = c.get("/admin/")
    assert r.status_code == 200 and b"planner/admin-theme.css" in r.content and b"ARCHPLANNER" in r.content
    assert c.get("/admin/planner/company/").status_code == 200
    assert c.get("/admin/planner/comment/").status_code == 200
