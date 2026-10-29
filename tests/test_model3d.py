"""Construction: starting a building from a 3D model, parapets, and adding blocks (wings, towers on a podium)."""
import struct

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from ftth import building as B, calc, model3d, sectors
from ftth.model import Design
from planner.models import Company, Membership, Profile


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def block(w, d, floors, fh, roof_rise=0.0):
    """Points (metres, Z up) and triangles of a box w x d with rings at every floor, sill and window head, and a
    gable roof when roof_rise > 0."""
    zs = sorted({round(k * fh + o, 3) for k in range(floors) for o in (0, 0.9, 2.1)} | {floors * fh})
    V, F = [], []
    for z in zs:
        V += [(0, 0, z), (w, 0, z), (w, d, z), (0, d, z)]
    for r in range(len(zs) - 1):
        a, b = 4 * r, 4 * (r + 1)
        for k in range(4):
            F += [[a + k, a + (k + 1) % 4, b + (k + 1) % 4], [a + k, b + (k + 1) % 4, b + k]]
    top = 4 * (len(zs) - 1)
    if roof_rise:
        V += [(0, d / 2, floors * fh + roof_rise), (w, d / 2, floors * fh + roof_rise)]
        r1, r2 = len(V) - 2, len(V) - 1
        F += [[top, top + 1, r2], [top, r2, r1], [top + 3, r1, r2], [top + 3, r2, top + 2],
              [top, r1, top + 3], [top + 1, top + 2, r2]]
    else:
        F += [[top, top + 1, top + 2], [top, top + 2, top + 3]]
    return V, F


def obj_bytes(V, F, scale=1.0):
    """Wavefront .obj, Y up, as most exporters write it."""
    lines = [f"v {x * scale:.5f} {z * scale:.5f} {-y * scale:.5f}" for x, y, z in V]
    lines += ["f " + " ".join(str(i + 1) for i in f) for f in F]
    return ("# test\n" + "\n".join(lines)).encode()


def tds_bytes(V, F, scale=1.0):
    """A minimal 3D Studio file: one mesh, Z up."""
    def chunk(cid, body):
        return struct.pack("<HI", cid, 6 + len(body)) + body
    pts = struct.pack("<H", len(V)) + b"".join(struct.pack("<3f", *(c * scale for c in p)) for p in V)
    tri = struct.pack("<H", len(F)) + b"".join(struct.pack("<4H", *f, 0) for f in F)
    mesh = chunk(0x4100, chunk(0x4110, pts) + chunk(0x4120, tri))
    return chunk(0x4D4D, chunk(0x3D3D, chunk(0x4000, b"house\0" + mesh)))


def test_a_flat_roofed_block_in_centimetres_is_measured():
    V, F = block(24, 12, 4, 3.2)
    m = model3d.measure("flats.obj", obj_bytes(V, F, 100))
    assert m["unit"] == "centimetres" and m["up"] == "y"
    br = m["brief"]
    assert (br["width"], br["depth"], br["floors"], br["roof"]) == (24, 12, 4, "flat")
    assert br["floor_height"] == pytest.approx(3.2, abs=0.1)
    assert br["material"] == "concrete" and br["columns"] is True


def test_a_pitched_house_in_millimetres_is_measured_and_the_units_can_be_overridden():
    V, F = block(12, 9, 1, 3.0, roof_rise=2.0)
    data = tds_bytes(V, F, 1000)
    m = model3d.measure("house.3ds", data)
    assert m["unit"] == "millimetres" and m["brief"]["roof"] == "gable" and m["brief"]["floors"] == 1
    assert m["brief"]["pitch"] == pytest.approx(24, abs=2)
    big = model3d.measure("house.3ds", data, unit="centimetres")
    assert big["unit"] == "centimetres" and big["brief"]["width"] == 120
    with pytest.raises(model3d.ModelError):
        model3d.measure("house.3ds", data, unit="furlongs")
    with pytest.raises(model3d.ModelError):
        model3d.measure("house.3ds", b"not a model at all")
    with pytest.raises(model3d.ModelError):
        model3d.measure("house.skp", data)


def test_a_tower_on_a_podium_is_noticed():
    V1, F1 = block(60, 40, 2, 4.0)
    V2, F2 = block(20, 20, 12, 3.5)
    V2 = [(x + 20, y + 10, z) for x, y, z in V2]
    V, F = V1 + V2, F1 + [[a + len(V1), b + len(V1), c + len(V1)] for a, b, c in F2]
    m = model3d.measure("tower.3ds", tds_bytes(V, F))
    assert m["brief"]["width"] == 60 and m["tower"] == {"width": 20, "depth": 20}
    assert any("tall part" in n for n in m["notes"])
    t = m["blocks"][0]
    assert t["what"] == "tower" and (t["x"], t["y"], t["width"], t["depth"]) == (20, 10, 20, 20)
    assert m["brief"]["floors"] == 2 and t["start_floor"] == 2
    assert 8 + t["floors"] * t["floor_height"] == pytest.approx(42, abs=1)  # the tower reaches the top


def test_a_stair_tower_on_the_roof_is_found_where_it_stands():
    V1, F1 = block(30, 15, 3, 3.2)
    V2, F2 = block(5, 4, 1, 2.8)
    V2 = [(x + 20, y + 2, z + 9.6) for x, y, z in V2]
    V, F = V1 + V2, F1 + [[a + len(V1), b + len(V1), c + len(V1)] for a, b, c in F2]
    m = model3d.measure("flats.3ds", tds_bytes(V, F))
    assert m["brief"]["floors"] == 3 and m["brief"]["roof"] == "flat"
    (s,) = m["blocks"]
    assert s["what"] == "on the roof" and s["start_floor"] == 3 and s["floors"] == 1
    assert (s["x"], s["y"], s["width"], s["depth"]) == (20, 2, 5, 4)
    b = B.generate(B.AutoParams(**m["brief"]))
    b = B.add_block(b, B.AutoParams(**{k: v for k, v in s.items() if k != "what"}))
    assert len(b.levels) == 4 and len(b.roofs) == 2


def test_hip_and_gable_roofs_are_told_apart():
    V, F = block(14, 9, 1, 3.0)
    top = len(V) - 4
    V += [(4.5, 4.5, 5.0), (9.5, 4.5, 5.0)]  # hip: the ridge stops short of the ends
    r1, r2 = len(V) - 2, len(V) - 1
    F = F[:-2] + [[top, top + 1, r2], [top, r2, r1], [top + 3, r1, r2], [top + 3, r2, top + 2],
                  [top, r1, top + 3], [top + 1, top + 2, r2]]
    assert model3d.measure("hip.3ds", tds_bytes(V, F))["brief"]["roof"] == "hip"


def test_flat_roofs_get_a_parapet_in_the_drawings_and_the_quantities():
    d = Design()
    sectors.apply(d, "construction")
    d.building = B.generate(B.AutoParams(width=12, depth=8, floors=2, roof="flat", parapet=1.2))
    r = d.building.roofs[0]
    assert r.parapet == 1.2 and r.overhang == 0 and B.roof_geometry(r)["rise"] == 1.2
    plain = Design()
    sectors.apply(plain, "construction")
    plain.building = B.generate(B.AutoParams(width=12, depth=8, floors=2, roof="flat", parapet=0))
    ext = lambda dd: sum(ln.qty for ln in calc.bom(dd) if ln.code.endswith("-EXT"))  # noqa: E731
    assert ext(d) == pytest.approx(ext(plain) + 1.2 * 2 * (12 + 8), rel=0.01)


def test_a_tower_block_is_added_on_a_podium():
    b = B.generate(B.AutoParams(width=40, depth=30, floors=2, roof="flat"))
    b = B.add_block(b, B.AutoParams(width=16, depth=14, floors=6, roof="flat", x=12, y=8, start_floor=2))
    assert len(b.levels) == 8 and len(b.roofs) == 2
    tower = [w for w in b.walls if w.id.startswith("B2-")]
    assert tower and min(w.level for w in tower) == 2 and max(w.level for w in tower) == 7
    xs = [p[0] for w in tower for p in (w.a, w.b)]
    assert min(xs) == pytest.approx(12, abs=0.3) and max(xs) == pytest.approx(28, abs=0.3)
    assert not any(o.kind == "door" and b.walls[[w.id for w in b.walls].index(o.wall)].level == 2
                   and o.wall.startswith("B2-") and o.sill == 0 and o.style != "single" for o in b.openings)
    assert len({w.id for w in b.walls}) == len(b.walls)  # ids stay unique
    wing = B.add_block(b, B.AutoParams(width=10, depth=10, floors=1, roof="hip", x=40, y=0))
    assert len(wing.roofs) == 3 and any(w.id.startswith("B3-") for w in wing.walls)
    with pytest.raises(ValueError):
        B.add_block(b, B.AutoParams(floors=1, start_floor=20))


@pytest.mark.django_db
def test_the_api_measures_models_and_adds_blocks():
    u = User.objects.create_user("builder3d", password="pw-12345-long")
    co = Company.objects.create(name="Build Co", sector="construction")
    Membership.objects.create(user=u, company=co, role="owner")
    Profile.objects.update_or_create(user=u, defaults={"active_company": co})
    c = Client()
    c.force_login(u)
    st = c.post("/api/projects", {}, content_type="application/json").json()
    pid = st["id"]
    V, F = block(24, 12, 4, 3.2)
    r = c.post(f"/api/projects/{pid}/building/measure", {"file": SimpleUploadedFile("flats.obj", obj_bytes(V, F))})
    assert r.status_code == 200, r.json()
    assert r.json()["brief"]["floors"] == 4
    r = c.post(f"/api/projects/{pid}/building/measure", {"file": SimpleUploadedFile("flats.obj", obj_bytes(V, F)),
                                                         "unit": "millimetres"})
    assert r.status_code == 400  # 24 mm wide: no building there
    assert c.post(f"/api/projects/{pid}/building/measure", {}).status_code == 400
    assert c.post(f"/api/projects/{pid}/building/generate", {"mode": "add", "floors": 1},
                  content_type="application/json").status_code == 400  # nothing to add to yet
    c.post(f"/api/projects/{pid}/building/generate", {"width": 30, "depth": 20, "floors": 2, "roof": "flat"},
           content_type="application/json")
    r = c.post(f"/api/projects/{pid}/building/generate",
               {"mode": "add", "width": 12, "depth": 10, "floors": 3, "roof": "flat", "x": 9, "y": 5, "start_floor": 2},
               content_type="application/json")
    assert r.status_code == 200, r.json()
    assert len(r.json()["design"]["building"]["levels"]) == 5 and len(r.json()["design"]["building"]["roofs"]) == 2
