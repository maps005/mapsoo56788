"""Photo AI: provider calls (faked, nothing leaves the machine), answer parsing, storage and the endpoints."""
import json
from io import BytesIO

import pytest
from django.contrib.auth.models import User
from django.test import Client
from PIL import Image

from ftth import vision

ANSWER = {"objects": [{"label": "concrete pole", "confidence": 0.93, "box": [0.4, 0.1, 0.1, 0.8], "note": ""},
                      {"label": "fibre access terminal (FAT)", "confidence": 0.71, "box": None, "note": "on pole"}],
          "pole_labels": ["KPC 06"], "issues": ["pole leaning"], "summary": "Concrete pole with a FAT beside a road."}


def png(w=64, h=48):
    b = BytesIO()
    Image.new("RGB", (w, h), "grey").save(b, "PNG")
    return b.getvalue()


def test_answer_inside_text_and_code_fences_is_read():
    raw = {"outputs": [{"output": "Here you go:\n```json\n" + json.dumps(ANSWER) + "\n```"}]}
    r = vision.normalise(raw)
    assert [o["label"] for o in r["objects"]] == ["concrete pole", "fibre access terminal (FAT)"]
    assert r["pole_labels"] == ["KPC 06"] and r["issues"] == ["pole leaning"] and r["summary"].startswith("Concrete")


def test_roboflow_detection_predictions_are_read():
    raw = {"outputs": [{"predictions": {"image": {"width": 200, "height": 100},
                                        "predictions": [{"class": "splice closure", "confidence": 0.8,
                                                         "x": 100, "y": 50, "width": 40, "height": 20}]}}]}
    r = vision.normalise(raw)
    assert r["objects"][0]["label"] == "splice closure" and r["objects"][0]["box"] == [0.4, 0.4, 0.2, 0.2]


def test_not_configured_is_a_clear_error():
    with pytest.raises(vision.VisionError, match="not set up"):
        vision.analyse(png(), vision.Config())


def test_requests_carry_the_image_prompt_and_key(monkeypatch):
    sent = []
    monkeypatch.setattr(vision, "_post", lambda url, key, body, timeout: sent.append((url, key, body)) or
                        {"choices": [{"message": {"content": json.dumps(ANSWER)}}]})
    r = vision.analyse(png(3000, 2000), vision.Config(provider="groq", key="k1", model="vision-model"))
    url, key, body = sent[0]
    assert url == vision.GROQ_URL and key == "k1" and body["model"] == "vision-model"
    img = body["messages"][0]["content"][1]["image_url"]["url"]
    assert img.startswith("data:image/jpeg;base64,") and r["objects"][0]["label"] == "concrete pole"
    vision.analyse(png(), vision.Config(provider="roboflow", url="https://example.test/wf", key="k2", model="m"))
    url, key, body = sent[1]
    assert url == "https://example.test/wf" and body["inputs"]["image"]["type"] == "base64" and body["inputs"]["model_version"] == "m"
    assert "fibre access terminal" in body["inputs"]["prompt"]


@pytest.mark.django_db
def test_analyse_endpoint_stores_suggestions_and_never_returns_the_key(tmp_path, settings, monkeypatch):
    settings.MEDIA_ROOT = tmp_path
    settings.PHOTO_AI = {"provider": "roboflow", "url": "https://example.test/wf", "key": "SECRET-KEY", "model": ""}
    monkeypatch.setattr(vision, "_post", lambda *a, **k: {"outputs": [{"text": json.dumps(ANSWER)}]})
    c = Client()
    c.force_login(User.objects.create_user("ann", password="pw-12345-long"))
    status = c.get("/api/photo-ai")
    assert status.json()["enabled"] is True and b"SECRET" not in status.content
    pid = c.post("/api/projects", {"name": "A"}, content_type="application/json").json()["id"]
    f = BytesIO(png())
    f.name = "pole.png"
    name = c.post(f"/api/projects/{pid}/photos", {"file": f}).json()["design"]["photos"][0]["file"]
    r = c.post(f"/api/projects/{pid}/photos/{name}/analyse")
    assert r.status_code == 200 and b"SECRET" not in r.content
    stored = r.json()["design"]["photos"][0]["analysis"]
    assert stored["pole_labels"] == ["KPC 06"] and stored["objects"][0]["confidence"] == 0.93
    assert c.post(f"/api/projects/{pid}/photos/0123456789.jpg/analyse").status_code == 404


@pytest.mark.django_db
def test_analyse_without_setup_says_how_to_set_it_up(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    settings.PHOTO_AI = {"provider": "", "url": "", "key": "", "model": ""}
    c = Client()
    c.force_login(User.objects.create_user("ann", password="pw-12345-long"))
    assert c.get("/api/photo-ai").json()["enabled"] is False
    pid = c.post("/api/projects", {"name": "A"}, content_type="application/json").json()["id"]
    f = BytesIO(png())
    f.name = "pole.png"
    name = c.post(f"/api/projects/{pid}/photos", {"file": f}).json()["design"]["photos"][0]["file"]
    r = c.post(f"/api/projects/{pid}/photos/{name}/analyse")
    assert r.status_code == 400 and "PHOTO_AI_PROVIDER" in r.json()["detail"]
