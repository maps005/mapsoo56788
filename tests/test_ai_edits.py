"""The AI assistant proposes changes; they are checked, shown, and only made when the planner presses Apply."""
import io
import json
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pypdf import PdfReader

from ftth import ai_edits, assistant, building as B, calc, sectors
from ftth.exporters import plans
from ftth.exporters.common import stamp
from ftth.model import Design
from planner.models import Company, Membership, Profile


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def hospital():
    d = Design()
    sectors.apply(d, "construction")
    d.building = B.generate(B.AutoParams(width=40, depth=16, floors=4, roof="flat", material="block", columns=True,
                                         door_style="double"))
    return d


ANSWER = """Flower beds along the walls and a row of trees will soften the compound.

```actions
[{"op": "add_landscape", "kind": "flower_bed", "around": "building", "width": 1.5, "gap": 1.0},
 {"op": "add_trees", "around": "building", "offset": 6, "spacing": 8},
 {"op": "add_landscape", "kind": "lawn", "rect": [-10, -20, 50, -8]}]
```"""


def test_an_answer_becomes_a_checked_proposal_and_applying_it_adds_the_landscaping():
    d = hospital()
    text, acts, changes = ai_edits.proposal(d, ANSWER)
    assert "```" not in text and text.startswith("Flower beds") and len(acts) == 3
    assert changes[0].startswith("Add flower beds all round") and "trees" in changes[1]
    assert not d.building.landscape  # nothing changes until Apply
    done = ai_edits.apply(d, acts)
    assert len(done) == 3
    kinds = [x.kind for x in d.building.landscape]
    assert kinds.count("lawn") == 1 and kinds.count("tree") >= 10 and kinds.count("flower_bed") >= 4
    assert len({x.id for x in d.building.landscape}) == len(kinds)
    # the front door stays clear: no bed crosses it
    door = B._ground_doors(d.building)[0]
    for x in d.building.landscape:
        if x.kind == "flower_bed" and min(p[1] for p in x.points) < 0:
            xs = [p[0] for p in x.points]
            assert not (min(xs) < door[0] < max(xs))
    q = {code: qty for code, qty, _ in B.quantities(d.building)}
    beds = sum(B.area(x.points) for x in d.building.landscape if x.kind == "flower_bed")
    assert q["TOPSOIL"] == pytest.approx(0.3 * beds + 0.15 * 60 * 12, rel=0.01) and q["GRASS"] == pytest.approx(720)
    assert q["PLANTS-FLOWER"] >= 6 * beds and q["TREE"] == kinds.count("tree")
    assert any(ln.code == "PLANTS-FLOWER" and ln.qty for ln in calc.bom(d))  # priced from the catalogue
    pdf = PdfReader(io.BytesIO(plans.build_plans_pdf(d, stamp(d, 1))))
    assert any("Landscaping" in pg.extract_text() for pg in pdf.pages)
    ai_edits.apply(d, [{"op": "remove_landscape", "kind": "tree"}])
    assert "tree" not in [x.kind for x in d.building.landscape] and d.building.landscape
    ai_edits.apply(d, [{"op": "remove_landscape"}])
    assert not d.building.landscape


def test_bad_or_unknown_changes_are_refused():
    d = hospital()
    for acts in ([{"op": "delete_everything"}], [{"op": "set_spec", "rm": "-rf"}],
                 [{"op": "add_landscape", "kind": "volcano", "around": "building"}],
                 [{"op": "add_block", "floors": 99}], [{"op": "set_rules", "default_fat_ports": 8}],
                 [{"op": "add_trees", "points": "everywhere"}], [{"op": "set_info", "owner": "me"}], [], "x"):
        with pytest.raises(ai_edits.EditError):
            ai_edits.apply(d.model_copy(deep=True), acts)
    text, acts, _ = ai_edits.proposal(d, "Sure.\n```actions\n[{\"op\": \"teleport\"}]\n```")
    assert acts == [] and "could not be prepared" in text
    assert ai_edits.proposal(d, "No changes here.") == ("No changes here.", [], [])
    # all or nothing: a bad change after a good one leaves the design as it was (the caller saves only on success)
    before = d.model_dump_json()
    with pytest.raises(ai_edits.EditError):
        ai_edits.apply(d, [{"op": "set_info", "name": "Renamed"}, {"op": "teleport"}])
    assert d.info.name == "Renamed"  # the copy the view works on is thrown away on error
    assert json.loads(before)["building"] == json.loads(d.model_dump_json())["building"]


def test_network_projects_can_change_only_their_settings():
    d = Design()
    ai_edits.apply(d, [{"op": "set_rules", "default_fat_ports": 16}, {"op": "set_info", "client": "Acme"}])
    assert d.rules.default_fat_ports == 16 and d.info.client == "Acme"
    with pytest.raises(ai_edits.EditError):
        ai_edits.apply(d, [{"op": "add_trees", "around": "building"}])


@pytest.mark.django_db
def test_editors_get_an_apply_button_and_viewers_do_not(settings):
    settings.AI_CHAT = {"key": "test-key"}
    u = User.objects.create_user("planner-ai", password="pw-12345-long")
    co = Company.objects.create(name="Build Co", sector="construction")
    Membership.objects.create(user=u, company=co, role="owner")
    Profile.objects.update_or_create(user=u, defaults={"active_company": co})
    c = Client()
    c.force_login(u)
    pid = c.post("/api/projects", {}, content_type="application/json").json()["id"]
    c.post(f"/api/projects/{pid}/building/generate", {"width": 30, "depth": 12, "floors": 2, "roof": "flat"},
           content_type="application/json")
    with mock.patch.object(assistant, "chat", return_value=ANSWER) as chat:
        r = c.post(f"/api/projects/{pid}/ai-chat", {"messages": [{"role": "user", "content": "add flowers"}]},
                   content_type="application/json").json()
    assert chat.call_args.kwargs["can_edit"] is True
    assert len(r["actions"]) == 3 and len(r["changes"]) == 3 and "```" not in r["answer"]
    st = c.post(f"/api/projects/{pid}/ai-apply", {"actions": r["actions"]}, content_type="application/json")
    assert st.status_code == 200, st.json()
    assert len(st.json()["result"]) == 3 and st.json()["design"]["building"]["landscape"]
    assert c.post(f"/api/projects/{pid}/ai-apply", {"actions": [{"op": "teleport"}]},
                  content_type="application/json").status_code == 400
    # a viewer may ask, but gets no changes and cannot apply any
    v = User.objects.create_user("viewer-ai", password="pw-12345-long")
    Membership.objects.create(user=v, company=co, role="viewer")
    Profile.objects.update_or_create(user=v, defaults={"active_company": co})
    cv = Client()
    cv.force_login(v)
    with mock.patch.object(assistant, "chat", return_value=ANSWER) as chat:
        r = cv.post(f"/api/projects/{pid}/ai-chat", {"messages": [{"role": "user", "content": "add flowers"}]},
                    content_type="application/json").json()
    assert chat.call_args.kwargs["can_edit"] is False and r["actions"] == []
    assert cv.post(f"/api/projects/{pid}/ai-apply", {"actions": [{"op": "remove_landscape"}]},
                   content_type="application/json").status_code in (403, 404)


def test_the_model_is_told_how_to_propose_changes_only_when_the_planner_may_edit():
    d = hospital()
    sent = {}

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake(req, timeout):
        sent["body"] = json.loads(req.data)
        return R()
    cfg = assistant.Config(key="k")
    with mock.patch("urllib.request.urlopen", fake):
        assistant.chat(d, [{"role": "user", "content": "hi"}], cfg, can_edit=True)
        assert "```actions" in sent["body"]["messages"][0]["content"] and '"footprint"' in sent["body"]["messages"][0]["content"]
        assistant.chat(d, [{"role": "user", "content": "hi"}], cfg, can_edit=False)
        assert "```actions" not in sent["body"]["messages"][0]["content"]
