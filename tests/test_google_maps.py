"""Google Maps imagery: Map Tiles API sessions for the browser when the server has a key, nothing otherwise."""
import io
import json

import pytest
from django.contrib.auth.models import User
from django.test import Client

from planner import views


@pytest.fixture
def client():
    u = User.objects.create_user("map-user", password="x")
    c = Client(HTTP_HOST="localhost")
    c.force_login(u)
    return c


@pytest.mark.django_db
def test_no_key_no_google(client, settings):
    settings.GOOGLE_MAPS_API_KEY = ""
    assert client.get("/api/maps/google").json() == {"enabled": False}


@pytest.mark.django_db
def test_sessions_for_each_map_type(client, settings, monkeypatch):
    settings.GOOGLE_MAPS_API_KEY = "test-key"
    views._GOOGLE_SESSIONS.clear()
    asked = []

    def fake_urlopen(req, timeout=10):
        body = json.loads(req.data)
        asked.append((req.full_url, body))
        return io.BytesIO(json.dumps({"session": f"tok-{body['mapType']}-{len(asked)}", "expiry": "9999999999"}).encode())
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    j = client.get("/api/maps/google").json()
    assert j["enabled"] and j["key"] == "test-key" and set(j["sessions"]) == {"satellite", "hybrid", "roadmap"}
    assert asked[1][1]["layerTypes"] == ["layerRoadmap"] and "createSession?key=test-key" in asked[0][0]
    client.get("/api/maps/google")
    assert len(asked) == 3  # sessions are reused until they near expiry
    csp = client.get("/").headers.get("Content-Security-Policy", "")
    assert "https://tile.googleapis.com" in csp
