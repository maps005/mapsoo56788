"""Sharing a project: can edit / can view, by username or email, people search, and who may change sharing."""
import pytest
from django.contrib.auth.models import User
from django.test import Client

from planner.models import Company, Membership, Project


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def login(name, **kw):
    u = User.objects.create_user(name, password="pw-12345-long", **kw)
    c = Client()
    c.force_login(u)
    return u, c


def share(c, pid, **body):
    return c.post(f"/api/projects/{pid}/share", body, content_type="application/json")


@pytest.mark.django_db
def test_can_view_and_can_edit_access():
    owner, oc = login("owner")
    viewer, vc = login("vera", email="vera@example.com", first_name="Vera")
    editor, ec = login("eddy")
    pid = oc.post("/api/projects", {"sample": True}, content_type="application/json").json()["id"]
    st = share(oc, pid, username="VERA@example.com", access="view").json()  # email, any case
    st = share(oc, pid, username="eddy", access="edit").json()
    assert {(p["username"], p["access"]) for p in st["people"]} == {("owner", "owner"), ("vera", "view"), ("eddy", "edit")}
    assert vc.get(f"/api/projects/{pid}").status_code == 200        # viewers can open it
    p = Project.objects.get(pk=pid)
    assert not p.can_edit(viewer) and p.can_edit(editor)
    assert share(vc, pid, username="eddy", access="remove").status_code == 403  # only owner / company admin
    share(oc, pid, username="vera", access="edit")
    assert Project.objects.get(pk=pid).can_edit(viewer)              # changing access replaces the old one
    share(oc, pid, username="vera", access="remove")
    assert vc.get(f"/api/projects/{pid}").status_code == 404
    assert share(oc, pid, username="owner", access="view").status_code == 400
    assert share(oc, pid, username="nobody", access="view").status_code == 404
    assert share(oc, pid, username="eddy", access="admin").status_code == 400


@pytest.mark.django_db
def test_people_search_lists_colleagues_and_exact_matches_only():
    me, c = login("me")
    co = Company.objects.create(name="Acme")
    mate, _ = login("wanjiku", first_name="Grace", last_name="Wanjiku")
    stranger, _ = login("wambui", email="wambui@other.example")
    for u in (me, mate):
        Membership.objects.create(user=u, company=co, role="planner")
    names = [x["username"] for x in c.get("/api/people?q=wan").json()]
    assert names == ["wanjiku"]                                      # strangers are not listed by partial match
    assert [x["username"] for x in c.get("/api/people?q=wambui@other.example").json()] == ["wambui"]
    assert c.get("/api/people?q=w").json() == []                     # at least 2 characters
