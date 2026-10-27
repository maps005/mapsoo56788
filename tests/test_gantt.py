"""Admin Gantt chart: planned dates against the survey / design / review phases."""
from datetime import date, datetime, timedelta, timezone as tz

import pytest
from django.contrib.auth.models import User
from django.test import Client

from ftth.sample import sample_design
from planner import gantt
from planner.models import Project, Revision


def make(owner, name, status="draft", survey_at="", start=None, due=None, created=datetime(2026, 9, 1, tzinfo=tz.utc)):
    d = sample_design()
    d.info.name, d.info.design_status, d.info.survey_approved_at = name, status, survey_at
    p = Project(owner=owner, start_date=start, due_date=due)
    p.set_design(d)
    p.save()
    Project.objects.filter(pk=p.pk).update(created=created)
    return Project.objects.get(pk=p.pk)


def rev(p, version, status, when):
    r = Revision.objects.create(project=p, version=version, status=status, data_hash="x", data={})
    Revision.objects.filter(pk=r.pk).update(created=when)


@pytest.mark.django_db
def test_phases_follow_survey_review_and_approval():
    u = User.objects.create_user("g")
    p = make(u, "Kabiria", status="approved", survey_at="2026-09-05T10:00:00+03:00",
             start=date(2026, 9, 1), due=date(2026, 9, 20))
    rev(p, 1, "in_review", datetime(2026, 9, 12, tzinfo=tz.utc))
    rev(p, 2, "approved", datetime(2026, 9, 25, tzinfo=tz.utc))
    chart = gantt.build([Project.objects.prefetch_related("revisions").get(pk=p.pk)], today=date(2026, 10, 1))
    row = chart["rows"][0]
    assert [(s.kind, s.start, s.end) for s in row.segments] == [
        ("survey", date(2026, 9, 1), date(2026, 9, 5)), ("design", date(2026, 9, 5), date(2026, 9, 12)),
        ("review", date(2026, 9, 12), date(2026, 9, 25))]
    assert row.approved_on == date(2026, 9, 25) and row.late  # approved after its due date
    assert row.planned and 0 <= row.planned.left < row.marker_left <= 100


@pytest.mark.django_db
def test_open_phase_runs_to_today_and_on_time_project_is_not_late():
    u = User.objects.create_user("g")
    p = make(u, "Infinity", due=date(2026, 12, 1))
    row = gantt.build([p], today=date(2026, 10, 10))["rows"][0]
    assert [s.kind for s in row.segments] == ["survey"] and row.segments[0].end == date(2026, 10, 10)
    assert not row.late and row.approved_on is None


@pytest.mark.django_db
def test_admin_gantt_page_and_link():
    admin = User.objects.create_superuser("boss", password="pw-12345-long")
    make(admin, "Open one", due=date.today() - timedelta(days=1))
    make(admin, "Done one", status="approved")
    c = Client()
    c.force_login(admin)
    assert b"/admin/planner/project/gantt/" in c.get("/admin/planner/project/").content
    page = c.get("/admin/planner/project/gantt/").content
    assert b"Open one" in page and b"Done one" not in page and b"1 late" in page
    assert b"Done one" in c.get("/admin/planner/project/gantt/?show=all").content
    staff = User.objects.create_user("plain", password="pw-12345-long", is_staff=True)
    c.force_login(staff)
    assert c.get("/admin/planner/project/gantt/").status_code == 403


@pytest.mark.django_db
def test_assign_action_gives_the_planner_access_and_shows_on_the_chart():
    admin = User.objects.create_superuser("boss", password="pw-12345-long")
    jane = User.objects.create_user("jane", first_name="Jane", last_name="Wanjiku", password="pw-12345-long")
    a, b = make(admin, "Kabiria A"), make(admin, "Kabiria B")
    assert not a.can_edit(jane) and not Project.objects.visible_to(jane).exists()
    c = Client()
    c.force_login(admin)
    url = "/admin/planner/project/"
    form = c.post(url, {"action": "assign_projects", "_selected_action": [a.pk, b.pk]})
    assert form.status_code == 200 and b"Assign 2 projects" in form.content
    bad = c.post(url, {"action": "assign_projects", "_selected_action": [a.pk], "apply": "1"})
    assert b"Choose at least one thing" in bad.content
    c.post(url, {"action": "assign_projects", "_selected_action": [a.pk, b.pk], "apply": "1",
                 "assigned_to": jane.pk, "due_date": "2026-12-01"})
    a.refresh_from_db()
    assert a.assigned_to == jane and a.due_date == date(2026, 12, 1)
    assert a.can_edit(jane) and set(Project.objects.editable_by(jane)) == {a, b}
    page = c.get(f"/admin/planner/project/gantt/?assigned={jane.pk}").content
    assert b"Jane Wanjiku" in page and b"Kabiria A" in page
    c.post(url, {"action": "assign_projects", "_selected_action": [b.pk], "apply": "1", "unassign": "on"})
    b.refresh_from_db()
    assert b.assigned_to is None and b"Kabiria B" in c.get("/admin/planner/project/gantt/?assigned=none").content
