"""Buildings for the construction sector: the model, the automatic designer, quantities and checks.

A building is levels of walls (with doors and windows in them), slabs, roofs, stairs and columns, in metres on a
local plane (x east, y north) whose origin sits at Building.origin on the map, turned by rotation_deg. The 3D
designer (planner/static/planner/building3d.js) draws and edits this model; quantities, checks, plans and
elevations are all read from it. The automatic designer follows the ideas of parametric building generators
(walls, openings, roofs, stairs made to your numbers), written for real buildings.
"""
from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Pt = list[float]  # [x, y] metres


def _pt(v: Pt) -> Pt:
    if len(v) != 2 or not all(math.isfinite(c) and abs(c) < 10000 for c in v):
        raise ValueError("a point is [x, y] in metres, within 10 km of the origin")
    return v


class Level(BaseModel):
    name: str = Field(default="Ground floor", max_length=60)
    elevation: float = Field(default=0.0, ge=-20, le=500)  # finished floor level, m
    height: float = Field(default=3.0, gt=1.5, le=20)      # floor to floor, m
    slab: float = Field(default=0.15, gt=0, le=1)           # slab thickness under this level, m


class Wall(BaseModel):
    id: str = Field(max_length=40)
    level: int = Field(default=0, ge=0)
    a: Pt
    b: Pt
    thickness: float = Field(default=0.2, gt=0.05, le=1.5)
    height: Optional[float] = Field(default=None, gt=0.3, le=20)  # None: the level's height
    kind: Literal["external", "internal"] = "external"
    material: Literal["block", "brick", "stone", "concrete"] = "block"
    _a = field_validator("a", "b")(classmethod(lambda cls, v: _pt(v)))


class Opening(BaseModel):
    """A door or window in a wall, its centre `offset` metres from the wall's start (a)."""
    id: str = Field(max_length=40)
    wall: str = Field(max_length=40)
    kind: Literal["door", "window"] = "window"
    offset: float = Field(default=1.0, ge=0)
    width: float = Field(default=1.2, gt=0.2, le=10)
    height: float = Field(default=1.2, gt=0.2, le=6)
    sill: float = Field(default=0.9, ge=0, le=6)  # doors: 0
    style: Literal["single", "double", "sliding", "arched", "fixed", "casement", "hung"] = "casement"


class Slab(BaseModel):
    id: str = Field(max_length=40)
    level: int = Field(default=0, ge=0)
    outline: list[Pt] = Field(min_length=3, max_length=200)
    thickness: float = Field(default=0.15, gt=0.05, le=1)
    _o = field_validator("outline")(classmethod(lambda cls, v: [_pt(p) for p in v]))


class Roof(BaseModel):
    """A roof over the rectangle x0, y0 - x1, y1 (the walls' outer face), on top of `level`."""
    id: str = Field(max_length=40)
    level: int = Field(default=0, ge=0)
    x0: float
    y0: float
    x1: float
    y1: float
    kind: Literal["gable", "hip", "shed", "flat"] = "gable"
    pitch: float = Field(default=25.0, ge=0, le=60)   # degrees (flat: ignored)
    overhang: float = Field(default=0.6, ge=0, le=3)
    ridge: Literal["x", "y"] = "x"                    # the ridge runs along x or y (shed: falls across it)
    covering: Literal["iron sheets", "tiles", "concrete"] = "iron sheets"


class Stair(BaseModel):
    """A straight flight from `level` up to the next, starting at x, y and climbing towards angle (deg, from east)."""
    id: str = Field(max_length=40)
    level: int = Field(default=0, ge=0)
    x: float
    y: float
    angle: float = 90.0
    width: float = Field(default=1.0, gt=0.6, le=4)
    tread: float = Field(default=0.28, gt=0.2, le=0.4)
    max_riser: float = Field(default=0.175, gt=0.12, le=0.22)


class Column(BaseModel):
    id: str = Field(max_length=40)
    level: int = Field(default=0, ge=0)
    x: float
    y: float
    size: float = Field(default=0.3, gt=0.1, le=2)


class Spec(BaseModel):
    """Construction standards the quantities follow (edit per project)."""
    footing_width: float = Field(default=0.6, gt=0.2, le=3)
    footing_thickness: float = Field(default=0.2, gt=0.1, le=1.5)
    excavation_depth: float = Field(default=0.9, gt=0.2, le=5)
    hardcore: float = Field(default=0.2, ge=0, le=1)
    rebar_kg_per_m3: float = Field(default=100.0, ge=0, le=400)
    setback: float = Field(default=3.0, ge=0, le=50)   # minimum distance from the plot boundary, m
    plaster: bool = True                                 # plaster inside, render outside
    rafter_spacing: float = Field(default=0.6, gt=0.2, le=2)


class Building(BaseModel):
    origin: Optional[list[float]] = None  # [lat, lon] of x = y = 0 on the map
    rotation: float = 0.0                 # degrees the building is turned on the map (counter-clockwise)
    # the plot boundary is the project's boundary on the map (ProjectInfo.boundary), drawn on the Site plan
    levels: list[Level] = Field(default_factory=lambda: [Level()], min_length=1, max_length=60)
    walls: list[Wall] = Field(default_factory=list, max_length=5000)
    openings: list[Opening] = Field(default_factory=list, max_length=5000)
    slabs: list[Slab] = Field(default_factory=list, max_length=500)
    roofs: list[Roof] = Field(default_factory=list, max_length=100)
    stairs: list[Stair] = Field(default_factory=list, max_length=100)
    columns: list[Column] = Field(default_factory=list, max_length=2000)
    spec: Spec = Field(default_factory=Spec)

    def wall(self, wid: str) -> Optional[Wall]:
        return next((w for w in self.walls if w.id == wid), None)

    def wall_height(self, w: Wall) -> float:
        lv = self.levels[min(w.level, len(self.levels) - 1)]
        return w.height or lv.height


# ---------------------------------------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------------------------------------
def length(w: Wall) -> float:
    return math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])


def area(poly: list[Pt]) -> float:
    return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(poly, poly[1:] + poly[:1]))) / 2


def to_latlon(b: Building, x: float, y: float) -> Optional[tuple[float, float]]:
    """A local point on the map (needs the building's origin)."""
    if not b.origin:
        return None
    r = math.radians(b.rotation)
    X, Y = x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)
    lat0, lon0 = b.origin
    return lat0 + Y / 111195.08, lon0 + X / (111195.08 * math.cos(math.radians(lat0)))


def from_latlon(b: Building, lat: float, lon: float) -> tuple[float, float]:
    """A map point in the building's local metres (inverse of to_latlon; needs the origin)."""
    lat0, lon0 = b.origin
    X, Y = (lon - lon0) * 111195.08 * math.cos(math.radians(lat0)), (lat - lat0) * 111195.08
    r = math.radians(-b.rotation)
    return X * math.cos(r) - Y * math.sin(r), X * math.sin(r) + Y * math.cos(r)


def footprint(b: Building) -> list[Pt]:
    """Outline of the ground floor: its ground slab, or the box round its external walls."""
    slab = next((s for s in b.slabs if s.level == 0), None)
    if slab:
        return slab.outline
    pts = [p for w in b.walls if w.level == 0 for p in (w.a, w.b)]
    if not pts:
        return []
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if not L else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def _inside(p, poly) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < (x2 - x1) * (p[1] - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def stair_steps(b: Building, s: Stair) -> tuple[int, float, float]:
    """(risers, riser height, going length) of a flight up one level."""
    h = b.levels[min(s.level, len(b.levels) - 1)].height
    n = max(1, math.ceil(h / s.max_riser - 1e-9))
    return n, h / n, (n - 1) * s.tread


def roof_geometry(r: Roof) -> dict:
    """Plan size with the overhang, the rise, the sloped covering area, ridge, eaves and hip lengths."""
    L, W = (r.x1 - r.x0) + 2 * r.overhang, (r.y1 - r.y0) + 2 * r.overhang
    along, across = (L, W) if r.ridge == "x" else (W, L)
    t = math.tan(math.radians(r.pitch)) if r.kind != "flat" else 0.0
    if r.kind == "flat":
        return {"plan": L * W, "area": L * W, "rise": 0.0, "ridge": 0.0, "eaves": 2 * (L + W), "hips": 0.0}
    if r.kind == "shed":
        rise = across * t
        return {"plan": L * W, "area": L * W / math.cos(math.radians(r.pitch)), "rise": rise, "ridge": along,
                "eaves": along, "hips": 0.0}
    rise = across / 2 * t
    area_ = L * W / math.cos(math.radians(r.pitch))  # equal pitches: hip and gable cover the same area
    if r.kind == "gable":
        return {"plan": L * W, "area": area_, "rise": rise, "ridge": along, "eaves": 2 * along, "hips": 0.0}
    ridge = max(0.0, along - across)
    hip = math.hypot(across / 2, across / 2, rise) * 4
    return {"plan": L * W, "area": area_, "rise": rise, "ridge": ridge, "eaves": 2 * (L + W), "hips": hip}


# ---------------------------------------------------------------------------------------------------------
# automatic design
# ---------------------------------------------------------------------------------------------------------
class AutoParams(BaseModel):
    """What the automatic designer needs; everything else follows good practice."""
    width: float = Field(default=12.0, ge=3, le=200)      # along x, outside of the walls
    depth: float = Field(default=9.0, ge=3, le=200)       # along y
    floors: int = Field(default=1, ge=1, le=40)
    floor_height: float = Field(default=3.0, ge=2.4, le=8)
    rooms_x: int = Field(default=2, ge=1, le=20)          # rooms across x on each floor
    rooms_y: int = Field(default=2, ge=1, le=20)
    external_wall: float = Field(default=0.2, ge=0.1, le=0.6)
    internal_wall: float = Field(default=0.15, ge=0.075, le=0.4)
    material: Literal["block", "brick", "stone", "concrete"] = "block"
    window_spacing: float = Field(default=3.0, ge=1.5, le=20)  # one window per this many metres of outside wall
    window_width: float = Field(default=1.2, ge=0.4, le=4)
    window_height: float = Field(default=1.2, ge=0.4, le=3)
    window_style: Literal["fixed", "casement", "sliding", "hung"] = "casement"
    door_style: Literal["single", "double", "sliding", "arched"] = "single"
    roof: Literal["gable", "hip", "shed", "flat"] = "gable"
    pitch: float = Field(default=25.0, ge=0, le=60)
    overhang: float = Field(default=0.6, ge=0, le=2)
    covering: Literal["iron sheets", "tiles", "concrete"] = "iron sheets"
    columns: bool = False                                  # a concrete frame: columns at the wall corners and junctions


def generate(p: AutoParams) -> Building:
    """A building made to the numbers: outer walls, a grid of rooms with doors between them, windows along the
    outside walls, a main door in the front (south) wall, slabs, a stair when there are upper floors, a roof."""
    W, D, te, ti = p.width, p.depth, p.external_wall, p.internal_wall
    # wall centrelines run half a wall inside the outer face
    x0, y0, x1, y1 = te / 2, te / 2, W - te / 2, D - te / 2
    b = Building(levels=[Level(name="Ground floor" if k == 0 else f"Floor {k}", elevation=round(k * p.floor_height, 3),
                               height=p.floor_height) for k in range(p.floors)])
    n = {"w": 0, "o": 0}

    def wid():
        n["w"] += 1
        return f"W{n['w']:03d}"

    def oid():
        n["o"] += 1
        return f"O{n['o']:03d}"
    # upper floors: a straight flight up the inside of the west wall from near the front, in a stair hall that
    # the cross walls of the first row of rooms stop short of
    stair_w = 1.0
    hall = x0 + te / 2 + stair_w + 0.1 if p.floors > 1 else None
    for lv in range(p.floors):
        outer = []
        for a, c in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            w = Wall(id=wid(), level=lv, a=list(a), b=list(c), thickness=te, kind="external", material=p.material)
            b.walls.append(w)
            outer.append(w)
        # windows evenly along each outer wall, clear of the main door in the middle of the front (south) wall
        dw = 1.8 if p.door_style == "double" else 1.0
        for side, w in enumerate(outer):
            L = length(w)
            count = max(1, int(L // p.window_spacing))
            ww = min(p.window_width, L / count - 0.4)
            for k in range(count):
                off = L * (k + 0.5) / count
                if lv == 0 and side == 0 and abs(off - L / 2) < (ww + dw) / 2 + 0.3:
                    continue
                b.openings.append(Opening(id=oid(), wall=w.id, kind="window", offset=round(off, 3), width=ww,
                                          height=p.window_height, sill=0.9, style=p.window_style))
        if lv == 0:  # main door in the middle of the front wall
            b.openings.append(Opening(id=oid(), wall=outer[0].id, kind="door", offset=round(length(outer[0]) / 2, 3),
                                      width=dw, height=2.4 if p.door_style == "arched" else 2.1, sill=0, style=p.door_style))
        # internal walls on a grid, a door in each
        cw, ch = (x1 - x0) / p.rooms_x, (y1 - y0) / p.rooms_y
        for i in range(1, p.rooms_x):
            x = x0 + i * cw
            for j in range(p.rooms_y):
                w = Wall(id=wid(), level=lv, a=[x, y0 + j * ch], b=[x, y0 + (j + 1) * ch], thickness=ti,
                         kind="internal", material=p.material)
                b.walls.append(w)
                if ch >= 1.8:
                    b.openings.append(Opening(id=oid(), wall=w.id, kind="door", offset=round(ch / 2, 3), width=0.9,
                                              height=2.1, sill=0, style="single"))
        for j in range(1, p.rooms_y):
            y = y0 + j * ch
            for i in range(p.rooms_x):
                xa = max(x0 + i * cw, hall) if hall and i == 0 else x0 + i * cw
                if x0 + (i + 1) * cw - xa < 0.5:
                    continue
                w = Wall(id=wid(), level=lv, a=[xa, y], b=[x0 + (i + 1) * cw, y], thickness=ti,
                         kind="internal", material=p.material)
                b.walls.append(w)
                L = length(w)
                if L >= 1.8 and i == 0:  # one door per row of rooms onto the first room
                    b.openings.append(Opening(id=oid(), wall=w.id, kind="door", offset=round(L / 2, 3), width=0.9,
                                              height=2.1, sill=0, style="single"))
        b.slabs.append(Slab(id=f"S{lv + 1:02d}", level=lv, outline=[[0, 0], [W, 0], [W, D], [0, D]],
                            thickness=0.15))
        if hall and lv < p.floors - 1:
            b.stairs.append(Stair(id=f"ST{lv + 1:02d}", level=lv, x=x0 + te / 2 + stair_w / 2 + 0.05,
                                  y=y0 + te / 2 + 0.3, angle=90.0, width=stair_w))
        if p.columns:
            xs = [x0 + i * cw for i in range(p.rooms_x + 1)]
            ys = [y0 + j * ch for j in range(p.rooms_y + 1)]
            b.columns += [Column(id=f"C{lv}-{i}-{j}", level=lv, x=x, y=y, size=max(te, 0.3))
                          for i, x in enumerate(xs) for j, y in enumerate(ys)]
    top = p.floors - 1
    if p.roof == "flat":
        b.slabs.append(Slab(id="SR", level=p.floors, outline=[[0, 0], [W, 0], [W, D], [0, D]], thickness=0.15))
    b.roofs.append(Roof(id="R1", level=top, x0=0, y0=0, x1=W, y1=D, kind=p.roof, pitch=p.pitch if p.roof != "flat" else 0,
                        overhang=p.overhang, ridge="x" if W >= D else "y",
                        covering="concrete" if p.roof == "flat" else p.covering))
    return b


# ---------------------------------------------------------------------------------------------------------
# quantities
# ---------------------------------------------------------------------------------------------------------
WALL_CODES = {"block": "BLOCKWORK", "brick": "BRICKWORK", "stone": "STONEWORK", "concrete": "CONC-WALL"}
DOOR_CODES = {"single": "DOOR-SINGLE", "double": "DOOR-DOUBLE", "sliding": "DOOR-SLIDING", "arched": "DOOR-ARCHED"}
WINDOW_CODES = {"fixed": "WINDOW-FIXED", "casement": "WINDOW-CASEMENT", "sliding": "WINDOW-SLIDING", "hung": "WINDOW-HUNG"}
ROOF_CODES = {"iron sheets": "ROOF-SHEETS", "tiles": "ROOF-TILES", "concrete": "CONC-SLAB"}


def quantities(b: Building) -> list[tuple[str, float, str]]:
    """(material code, quantity, how it was measured), from the model and the specification."""
    sp, out = b.spec, []

    def add(code, q, src):
        if q > 1e-9:
            out.append((code, round(q, 3), src))
    walls0 = [w for w in b.walls if w.level == 0]
    run0 = sum(length(w) for w in walls0)
    add("EXCAVATION", run0 * sp.footing_width * sp.excavation_depth, "Strip footings under ground-floor walls")
    footing = run0 * sp.footing_width * sp.footing_thickness
    add("CONC-FOOTING", footing, "Strip footings: length x width x thickness")
    ground = [s for s in b.slabs if s.level == 0]
    ground_area = sum(area(s.outline) for s in ground)
    add("HARDCORE", ground_area * sp.hardcore, "Under the ground slab")
    add("DPM", ground_area, "Damp-proof membrane under the ground slab")
    slab_vol = sum(area(s.outline) * s.thickness for s in b.slabs)
    suspended = [s for s in b.slabs if s.level > 0]
    add("CONC-SLAB", slab_vol, "Slabs: area x thickness")
    add("FORMWORK", sum(area(s.outline) for s in suspended), "Soffits of suspended slabs")
    add("SCREED", sum(area(s.outline) for s in b.slabs if s.level < len(b.levels)), "Floor screed on each floor")
    add("CEILING", sum(area(s.outline) for s in b.slabs if s.level > 0) +
        sum((r.x1 - r.x0) * (r.y1 - r.y0) for r in b.roofs if r.kind != "flat"), "Ceilings under slabs and roofs")
    col_vol = sum(c.size * c.size * b.levels[min(c.level, len(b.levels) - 1)].height for c in b.columns)
    add("CONC-COLUMN", col_vol, "Columns: section x storey height")
    add("FORMWORK", sum(4 * c.size * b.levels[min(c.level, len(b.levels) - 1)].height for c in b.columns),
        "Column sides")
    stair_vol = 0.0
    for s in b.stairs:
        n, rise, going = stair_steps(b, s)
        stair_vol += s.width * (math.hypot(going, rise * n) * 0.15 + n * s.tread * rise / 2)
    add("CONC-STAIR", stair_vol, "Stairs: waist slab and steps")
    add("REBAR", (footing + slab_vol + col_vol + stair_vol) * sp.rebar_kg_per_m3,
        f"{sp.rebar_kg_per_m3:g} kg per m3 of structural concrete")
    plaster = render = 0.0
    for w in b.walls:
        gross = length(w) * b.wall_height(w)
        ops = sum(o.width * o.height for o in b.openings if o.wall == w.id)
        net = max(0.0, gross - ops)
        if w.material == "concrete":
            add("CONC-WALL", net * w.thickness, "Concrete walls: net area x thickness")
        else:
            add(WALL_CODES[w.material] + ("-EXT" if w.kind == "external" else "-INT"), net,
                f"{w.kind.capitalize()} walls: length x height less openings")
        if w.kind == "external":
            plaster += net
            render += net
        else:
            plaster += 2 * net
    if sp.plaster:
        add("PLASTER", plaster, "Inside faces of the walls")
        add("RENDER", render, "Outside faces of the external walls")
        add("PAINT-INT", plaster, "Over the plaster")
        add("PAINT-EXT", render, "Over the render")
    for o in b.openings:
        if o.kind == "door":
            add(DOOR_CODES[o.style], 1, "Doors")
        else:
            add(WINDOW_CODES[o.style], o.width * o.height, "Windows: width x height")
        add("LINTEL", o.width + 0.3, "Over each opening, 150 mm bearing each side")
    for r in b.roofs:
        g = roof_geometry(r)
        if r.kind == "flat":
            continue  # a flat roof is its slab (above)
        add(ROOF_CODES[r.covering], g["area"], f"{r.kind.capitalize()} roof covering at {r.pitch:g} deg")
        add("RIDGE", g["ridge"] + g["hips"], "Ridge and hip capping")
        add("GUTTER", g["eaves"], "Along the eaves")
        add("FASCIA", g["eaves"], "Along the eaves")
        span = (r.y1 - r.y0 if r.ridge == "x" else r.x1 - r.x0) + 2 * r.overhang
        rafter = (span if r.kind == "shed" else span / 2) / math.cos(math.radians(r.pitch))
        count = math.ceil(g["eaves"] / sp.rafter_spacing) + 1
        add("ROOF-TIMBER", count * rafter + g["ridge"] + 2 * ((r.x1 - r.x0) + (r.y1 - r.y0)),
            f"Rafters at {sp.rafter_spacing:g} m, ridge board and wall plate (estimate)")
    # one line per code
    merged: dict[str, list] = {}
    for code, q, src in out:
        if code in merged:
            merged[code][0] += q
        else:
            merged[code] = [q, src]
    return [(c, round(v[0], 3), v[1]) for c, v in merged.items()]


# ---------------------------------------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------------------------------------
def check(b: Building, boundary: Optional[list[list[float]]] = None) -> list[dict]:
    """Building checks; boundary is the plot on the map ([lat, lon] points) for the setback check."""
    issues = []

    def add(sev, code, msg, ref=None):
        issues.append({"severity": sev, "code": code, "message": msg, "ref": ref})
    ids = {}
    for coll in (b.walls, b.openings, b.slabs, b.roofs, b.stairs, b.columns):
        for x in coll:
            if x.id in ids:
                add("error", "bld_id_duplicate", f"ID {x.id} is used more than once", x.id)
            ids[x.id] = x
    nlev = len(b.levels)
    for coll in (b.walls, b.slabs, b.stairs, b.columns, b.roofs):
        for x in coll:
            if x.level >= nlev + (1 if coll is b.slabs else 0):
                add("error", "bld_level", f"{x.id} is on level {x.level + 1}, but the building has {nlev}", x.id)
    for w in b.walls:
        L = length(w)
        if L < 0.1:
            add("error", "bld_wall_short", f"Wall {w.id} has no length", w.id)
            continue
        ops = sorted((o for o in b.openings if o.wall == w.id), key=lambda o: o.offset)
        h = b.wall_height(w)
        for o in ops:
            if o.offset - o.width / 2 < 0.05 or o.offset + o.width / 2 > L - 0.05:
                add("error", "bld_opening_outside", f"{o.kind.capitalize()} {o.id} runs past the end of wall {w.id}", o.id)
            if o.sill + o.height > h - 0.1:
                add("error", "bld_opening_high", f"{o.kind.capitalize()} {o.id} is taller than wall {w.id} allows", o.id)
        for p, q in zip(ops, ops[1:]):
            if q.offset - q.width / 2 < p.offset + p.width / 2 + 0.1:
                add("error", "bld_opening_overlap", f"Openings {p.id} and {q.id} overlap in wall {w.id}", q.id)
    for o in b.openings:
        if not b.wall(o.wall):
            add("error", "bld_opening_wall", f"Opening {o.id} is in unknown wall {o.wall}", o.id)
        if o.kind == "door" and o.height < 2.0:
            add("warning", "bld_door_low", f"Door {o.id} is {o.height:g} m high (2.0 m or more is usual)", o.id)
    for lv in b.levels:
        if lv.height - lv.slab < 2.4:
            add("warning", "bld_headroom", f"{lv.name}: {lv.height - lv.slab:.2f} m clear height (2.4 m or more is usual)")
    for s in b.stairs:
        n, rise, going = stair_steps(b, s)
        if 2 * rise + s.tread > 0.70 or 2 * rise + s.tread < 0.55:
            add("warning", "bld_stair_pitch", f"Stair {s.id}: {n} risers of {rise * 1000:.0f} mm with {s.tread * 1000:.0f} mm "
                                              f"treads (2 x riser + tread should be 550-700 mm)", s.id)
    if b.walls and not b.roofs and not any(s.level == nlev for s in b.slabs):
        add("warning", "bld_no_roof", "The building has no roof")
    if not b.origin:
        add("info", "bld_no_origin", "The building is not placed on the map yet (Site plan: Place building)")
    plot = [list(from_latlon(b, la, lo)) for la, lo in boundary] if b.origin and boundary and len(boundary) >= 3 else []
    fp = footprint(b)
    if plot and fp:
        out = [p for p in fp if not _inside(p, plot)]
        if out:
            add("error", "bld_outside_plot", "The building is partly outside the plot boundary")
        else:
            near = min(_seg_dist(p, a, c) for p in fp for a, c in zip(plot, plot[1:] + plot[:1]))
            if near < b.spec.setback - 1e-6:
                add("warning", "bld_setback", f"The building is {near:.2f} m from the plot boundary "
                                              f"(setback {b.spec.setback:g} m)")
    return issues
