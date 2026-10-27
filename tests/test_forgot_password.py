"""'Forgot password' on the sign-in page notifies the administrators in the admin."""
import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client

from planner.models import PasswordResetRequest

SENT = b"If an account matches"


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_login_page_links_to_forgot_password():
    r = Client().get("/accounts/login/")
    assert b'href="/accounts/forgot/"' in r.content and b"Forgot password?" in r.content


@pytest.mark.django_db
def test_request_by_username_or_email_is_recorded_once():
    u = User.objects.create_user("jane", email="jane@example.com", password="pw-12345-long")
    c = Client()
    r = c.post("/accounts/forgot/", {"identifier": "JANE", "note": "call 0700 000000"})
    assert r.status_code == 200 and SENT in r.content
    req = PasswordResetRequest.objects.get()
    assert req.user == u and req.note == "call 0700 000000" and not req.resolved
    c.post("/accounts/forgot/", {"identifier": "jane@example.com"})  # same account again within the hour
    assert PasswordResetRequest.objects.count() == 1


@pytest.mark.django_db
def test_unknown_account_gets_the_same_answer_and_nothing_is_stored():
    r = Client().post("/accounts/forgot/", {"identifier": "nobody"})
    assert SENT in r.content and not PasswordResetRequest.objects.exists()
    assert b"Enter your username" in Client().post("/accounts/forgot/", {"identifier": " "}).content


@pytest.mark.django_db
def test_requests_from_one_address_are_limited():
    c = Client()
    for _ in range(5):
        c.post("/accounts/forgot/", {"identifier": "x"})
    assert b"Too many requests" in c.post("/accounts/forgot/", {"identifier": "x"}).content


@pytest.mark.django_db
def test_admin_sees_the_notification_and_resolves_it():
    u = User.objects.create_user("jane", password="pw-12345-long")
    admin = User.objects.create_superuser("boss", password="pw-12345-long")
    Client().post("/accounts/forgot/", {"identifier": "jane"})
    c = Client()
    c.force_login(admin)
    page = c.get("/admin/").content
    assert b"1 password reset request waiting" in page and f"/admin/auth/user/{u.id}/password/".encode() in page
    req = PasswordResetRequest.objects.get()
    c.post("/admin/planner/passwordresetrequest/", {"action": "mark_resolved", "_selected_action": [req.id]})
    req.refresh_from_db()
    assert req.resolved and req.resolved_by == admin
    assert b"password reset request" not in c.get("/admin/").content.split(b"<body", 1)[1].split(b"content-main")[0]
    staff = User.objects.create_user("plain", password="pw-12345-long", is_staff=True)  # no permission: no banner
    PasswordResetRequest.objects.create(user=u)
    c.force_login(staff)
    assert b"ap-notice" not in c.get("/admin/").content
