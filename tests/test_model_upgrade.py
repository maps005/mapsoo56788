"""Projects saved before the data model gained fields stay savable and keep their approval."""
import pytest
from django.contrib.auth.models import User
from django.test import Client

from ftth.sample import sample_design
from planner.models import Project, Revision


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def older_project(user, status="draft"):
    """A project as an older version of the app stored it: no 'markups' or 'sheet_map', and the hash of that."""
    d = sample_design()
    d.info.design_status = status
    data = d.model_dump(mode="json")
    data.pop("markups")
    data["info"].pop("sheet_map")
    p = Project.objects.create(owner=user, data=data, name=d.info.name, data_hash="0ld0ld0ld0ld")
    return p, data


@pytest.mark.django_db
def test_a_project_from_an_older_model_can_be_saved():
    u = User.objects.create_superuser("planner", password="pw-12345-long")
    c = Client()
    c.force_login(u)
    p, _ = older_project(u)
    st = c.get(f"/api/projects/{p.id}").json()
    assert st["hash"] == "0ld0ld0ld0ld"  # the stored version, which saves are checked against
    st["design"]["markups"] = [{"id": "MK001", "kind": "text", "points": [[-1.29, 36.82]], "text": "note"}]
    r = c.put(f"/api/projects/{p.id}", st["design"], content_type="application/json", HTTP_X_BASE_HASH=st["hash"])
    assert r.status_code == 200, r.json()
    assert r.json()["design"]["markups"][0]["text"] == "note"
    assert r.json()["hash"] == Project.objects.get(pk=p.id).data_hash != "0ld0ld0ld0ld"
    # an out-of-date version is still refused
    r = c.put(f"/api/projects/{p.id}", st["design"], content_type="application/json", HTTP_X_BASE_HASH="0ld0ld0ld0ld")
    assert r.status_code == 409


@pytest.mark.django_db
def test_an_approved_design_from_an_older_model_stays_approved_when_saved_unchanged():
    u = User.objects.create_superuser("approver", password="pw-12345-long")
    c = Client()
    c.force_login(u)
    p, data = older_project(u, "approved")
    Revision.objects.create(project=p, version=1, author=u, status="approved", data_hash="0ld0ld0ld0ld", data=data)
    st = c.get(f"/api/projects/{p.id}").json()
    r = c.put(f"/api/projects/{p.id}", st["design"], content_type="application/json", HTTP_X_BASE_HASH=st["hash"])
    assert r.status_code == 200 and r.json()["design"]["info"]["design_status"] == "approved"
