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
    style: Literal["single", "double", "sliding", "arched", "fire", "fixed", "casement", "hung"] = "casement"
    flip: bool = False          # doors: open to the wall's right side (default: its left, seen from a to b)
    rating: int = Field(default=0, ge=0, le=240)  # fire resistance, minutes (doors: FD30, FD60)


class Room(BaseModel):
    """A named space on a level: its name and floor area, labelled at x, y on the plans."""
    id: str = Field(max_length=40)
    level: int = Field(default=0, ge=0)
    name: str = Field(max_length=60)
    x: float
    y: float
    area: float = Field(default=0.0, ge=0)
    w: float = Field(default=0.0, ge=0)  # room for the label across the room, m (0: any)
    rect: Optional[list[float]] = None    # [x0, y0, x1, y1] between the wall centrelines: where furniture goes
    door: Optional[Pt] = None             # where its door is (furniture keeps clear and faces it)
    unit: str = Field(default="", max_length=20)  # the flat it belongs to ("2-05": floor 2, flat 5)


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
    kind: Literal["gable", "hip", "shed", "flat", "arch", "dome"] = "gable"  # arch: a pointed vault (mihrab
    # profile) along the ridge; dome: a pointed dome, a pointed arch seen from every side
    pitch: float = Field(default=25.0, ge=0, le=80)   # degrees (flat: ignored; arch: springing to apex, from the eaves)
    overhang: float = Field(default=0.6, ge=0, le=3)
    ridge: Literal["x", "y"] = "x"                    # the ridge runs along x or y (shed: falls across it)
    covering: Literal["iron sheets", "tiles", "concrete"] = "iron sheets"
    parapet: float = Field(default=0.0, ge=0, le=3)  # flat roofs: wall around the roof edge, m high (0 = none)
    # domes: the profile (round: a quarter-ellipse from each side; pointed: a pointed arch), the lean (0: closing
    # evenly; 1: the y0 side rises straight and only the y1 side curves back; -1 the other way), the flat cap at
    # the top (m across) and a mast on it (m high)
    profile: Literal["pointed", "round"] = "pointed"
    lean: float = Field(default=0.0, ge=-1, le=1)
    cap: float = Field(default=0.0, ge=0, le=100)
    mast: float = Field(default=0.0, ge=0, le=100)


class Stair(BaseModel):
    """A stair from `level` up to the next, its first flight starting at x, y and climbing towards angle (deg, from
    east). flights 2: a dog-leg - the first flight to a half landing, the second back alongside it, to its right."""
    id: str = Field(max_length=40)
    level: int = Field(default=0, ge=0)
    x: float
    y: float
    angle: float = 90.0
    width: float = Field(default=1.0, gt=0.6, le=4)
    tread: float = Field(default=0.28, gt=0.2, le=0.4)
    max_riser: float = Field(default=0.175, gt=0.12, le=0.22)
    flights: int = Field(default=1, ge=1, le=2)


class Column(BaseModel):
    id: str = Field(max_length=40)
    level: int = Field(default=0, ge=0)
    x: float
    y: float
    size: float = Field(default=0.3, gt=0.1, le=2)


class BriefRoom(BaseModel):
    """A line of the client's schedule of accommodation: so many rooms of a kind (named as on the plans)."""
    name: str = Field(max_length=60)
    count: int = Field(default=1, ge=0, le=2000)
    area: float = Field(default=0.0, ge=0, le=5000)  # each, m2 (0: any)


class Site(BaseModel):
    """The site survey and the client's brief: ground conditions the foundations depend on, and what the
    building must provide."""
    soil: Literal["", "rock", "murram / gravel", "sand", "clay", "black cotton", "made ground / fill"] = ""
    bearing_capacity: float = Field(default=0.0, ge=0, le=5000)   # safe bearing pressure, kN/m2 (0: not tested)
    water_table: float = Field(default=0.0, ge=0, le=100)         # depth below ground, m (0: not found / not known)
    slope: float = Field(default=0.0, ge=0, le=100)               # fall across the plot, %
    ground_level: float = Field(default=0.0, ge=-500, le=6000)    # ground level at the building, m above datum
    survey_notes: str = Field(default="", max_length=2000)
    geotech_report: str = Field(default="", max_length=120)       # the geotechnical investigation's reference
    client_brief: str = Field(default="", max_length=4000)
    occupants: int = Field(default=0, ge=0, le=100000)
    budget: float = Field(default=0.0, ge=0)                       # in the project's currency (0: none given)
    schedule: list[BriefRoom] = Field(default_factory=list, max_length=100)
    # the plot and its planning limits (0: no limit given); the county confirms them for each plot
    plot_ref: str = Field(default="", max_length=80)               # LR / title number
    zone: str = Field(default="", max_length=80)
    max_coverage: float = Field(default=0.0, ge=0, le=100)         # ground coverage, % of the plot
    max_plot_ratio: float = Field(default=0.0, ge=0, le=5000)      # gross floor area, % of the plot
    max_floors: int = Field(default=0, ge=0, le=200)
    setback_front: float = Field(default=0.0, ge=0, le=100)        # building lines, m (front: the road side, south)
    setback_side: float = Field(default=0.0, ge=0, le=100)
    setback_rear: float = Field(default=0.0, ge=0, le=100)
    parking_per_unit: float = Field(default=0.0, ge=0, le=10)      # car spaces per flat
    # the professionals who sign the drawings
    architect: str = Field(default="", max_length=120)
    architect_reg: str = Field(default="", max_length=60)         # BORAQS registration
    engineer: str = Field(default="", max_length=120)
    engineer_reg: str = Field(default="", max_length=60)          # EBK registration

    def recorded(self) -> bool:
        return bool(self.soil or self.bearing_capacity or self.water_table or self.survey_notes)


class Spec(BaseModel):
    """Construction standards the quantities follow (edit per project)."""
    footing_width: float = Field(default=0.6, gt=0.2, le=3)
    footing_thickness: float = Field(default=0.2, gt=0.1, le=1.5)
    excavation_depth: float = Field(default=0.9, gt=0.2, le=5)
    founding_depth: float = Field(default=1.5, gt=0.3, le=30)  # m: a framed building's pads and rafts (geotechnical)
    hardcore: float = Field(default=0.2, ge=0, le=1)
    rebar_kg_per_m3: float = Field(default=100.0, ge=0, le=400)
    setback: float = Field(default=3.0, ge=0, le=50)   # minimum distance from the plot boundary, m
    plaster: bool = True                                 # plaster inside, render outside
    rafter_spacing: float = Field(default=0.6, gt=0.2, le=2)


LANDSCAPE_AREAS = ("flower_bed", "lawn", "shrub_bed", "paving", "parking")
BAY_W, BAY_L = 2.5, 5.0  # a car parking bay, m
SHAFT_DEPTH = 2.6        # m: a lift shaft (8-13 person / firefighting car), inside the lift bay
BAY_W_ACC = 3.6          # an accessible bay (2.4 m bay and a 1.2 m transfer zone)


class Landscape(BaseModel):
    """Landscaping in the compound, in the building's metres: flower beds, lawns, shrub beds and paving are areas
    (an outline), a hedge is a line, trees are points (one per tree)."""
    id: str = Field(max_length=40)
    kind: Literal["flower_bed", "lawn", "shrub_bed", "paving", "parking", "hedge", "tree"]
    points: list[Pt] = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=120)

    @field_validator("points")
    @classmethod
    def _points(cls, v):
        return [_pt(q) for q in v]


class Building(BaseModel):
    origin: Optional[list[float]] = None  # [lat, lon] of x = y = 0 on the map
    rotation: float = 0.0                 # degrees the building is turned on the map (counter-clockwise)
    # the plot boundary is the project's boundary on the map (ProjectInfo.boundary), drawn on the Site plan
    levels: list[Level] = Field(default_factory=lambda: [Level()], min_length=1, max_length=60)
    walls: list[Wall] = Field(default_factory=list, max_length=10000)
    openings: list[Opening] = Field(default_factory=list, max_length=10000)
    slabs: list[Slab] = Field(default_factory=list, max_length=500)
    roofs: list[Roof] = Field(default_factory=list, max_length=100)
    stairs: list[Stair] = Field(default_factory=list, max_length=100)
    columns: list[Column] = Field(default_factory=list, max_length=5000)
    landscape: list[Landscape] = Field(default_factory=list, max_length=500)
    rooms: list[Room] = Field(default_factory=list, max_length=5000)
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


def parking_bays(x: Landscape) -> list[list[Pt]]:
    """The bays in a parking area: one row of 2.5 x 5 m bays along its long side (two rows, back to back, when
    it is 10 m deep or more)."""
    if x.kind != "parking" or len(x.points) < 3:
        return []
    x0, y0, x1, y1 = _bbox(x.points)
    along_x = (x1 - x0) >= (y1 - y0)
    L, D = (x1 - x0, y1 - y0) if along_x else (y1 - y0, x1 - x0)
    if D < BAY_L - 0.01 <= L:  # too shallow for a bay this way round: the bays run the other way
        along_x, (L, D) = not along_x, (D, L)
    rows = 2 if D >= 2 * BAY_L else 1 if D >= BAY_L - 0.01 else 0
    bw = BAY_W_ACC if "accessible" in x.note.lower() else BAY_W  # a parking area noted "accessible": wider bays
    out = []
    for r in range(rows):
        for i in range(int(L // bw + 1e-9)):
            a0, a1, c0, c1 = i * bw, (i + 1) * bw, r * BAY_L, (r + 1) * BAY_L
            if along_x:
                out.append([[x0 + a0, y0 + c0], [x0 + a1, y0 + c0], [x0 + a1, y0 + c1], [x0 + a0, y0 + c1]])
            else:
                out.append([[x0 + c0, y0 + a0], [x0 + c1, y0 + a0], [x0 + c1, y0 + a1], [x0 + c0, y0 + a1]])
    return out


def footprint(b: Building) -> list[Pt]:
    """Outline of the ground floor: its ground slab, or the box round its external walls (all the blocks on the
    ground: a building with wings has more than one ground slab)."""
    slabs = [s for s in b.slabs if s.level == 0]
    if len(slabs) == 1:
        return slabs[0].outline
    pts = [p for w in b.walls if w.level == 0 for p in (w.a, w.b)] + [p for s in slabs for p in s.outline]
    if not pts:
        return []
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _ground_doors(b: Building) -> list[Pt]:
    """Where the outside doors on the ground floor are (their centres), so planting keeps them clear."""
    out = []
    for o in b.openings:
        w = b.wall(o.wall)
        if o.kind == "door" and w is not None and w.level == 0 and w.kind == "external":
            L = length(w) or 1
            out.append([w.a[0] + (w.b[0] - w.a[0]) / L * o.offset, w.a[1] + (w.b[1] - w.a[1]) / L * o.offset])
    return out


def _next_landscape_id(b: Building) -> int:
    return 1 + max((int(x.id[1:]) for x in b.landscape if x.id[1:].isdigit()), default=0)


def ground_blocks(b: Building) -> list[tuple[float, float, float, float]]:
    """The box round each block standing on the ground (the first design, and each wing added to it)."""
    pts: dict[str, list] = {}
    for w in b.walls:
        if w.level == 0 and w.kind == "external":
            k = w.id.split("-")[0] if w.id.startswith("B") and "-" in w.id else ""
            pts.setdefault(k, []).extend([w.a, w.b])
    return [_bbox(v) for v in pts.values()]


def _cut(a0: float, a1: float, gaps: list[tuple[float, float]], least: float = 0.8) -> list[tuple[float, float]]:
    """[a0, a1] less the gaps, keeping pieces at least `least` long."""
    pieces, start = [], a0
    for g0, g1 in sorted(gaps):
        if g0 > start:
            pieces.append((start, min(g0, a1)))
        start = max(start, g1)
    if a1 > start:
        pieces.append((start, a1))
    return [(s0, s1) for s0, s1 in pieces if s1 - s0 >= least]


def landscape_around(b: Building, kind: str, width: float = 1.5, gap: float = 1.0, clear: float = 3.0,
                     note: str = "") -> list[Landscape]:
    """Strips of planting (or a lawn, or paving) round each block of the building, `gap` m from its walls and `width`
    m wide. They stop where blocks meet (no bed under a wing) and where the outside doors are, so the entrances stay
    clear (`clear` m wide)."""
    if kind not in LANDSCAPE_AREAS:
        raise ValueError(f"{kind} is not an area: use one of {', '.join(LANDSCAPE_AREAS)}")
    blocks = ground_blocks(b)
    if not blocks:
        raise ValueError("Design the building first")
    doors = _ground_doors(b)
    o, w = gap, gap + width
    out, k = [], _next_landscape_id(b)
    for i, (x0, y0, x1, y1) in enumerate(blocks):
        others = [q for j, q in enumerate(blocks) if j != i]
        # four strips: south and north run the full length (corners included), east and west fit between them
        strips = [("x", x0 - w, x1 + w, y0 - w, y0 - o, y0), ("x", x0 - w, x1 + w, y1 + o, y1 + w, y1),
                  ("y", y0 - o, y1 + o, x0 - w, x0 - o, x0), ("y", y0 - o, y1 + o, x1 + o, x1 + w, x1)]
        for axis, a0, a1, c0, c1, side in strips:
            gaps = [((d[0] if axis == "x" else d[1]) - clear / 2, (d[0] if axis == "x" else d[1]) + clear / 2)
                    for d in doors if abs((d[1] if axis == "x" else d[0]) - side) < 0.6]
            for q0x, q0y, q1x, q1y in others:  # another block (with its own gap) stands across the strip
                lo, hi = (q0y - o, q1y + o) if axis == "x" else (q0x - o, q1x + o)
                if c1 > lo and c0 < hi:
                    gaps.append((q0x - o, q1x + o) if axis == "x" else (q0y - o, q1y + o))
            for s0, s1 in _cut(a0, a1, gaps):
                pts = ([[s0, c0], [s1, c0], [s1, c1], [s0, c1]] if axis == "x" else [[c0, s0], [c1, s0], [c1, s1], [c0, s1]])
                out.append(Landscape(id=f"L{k}", kind=kind, points=[[round(x, 2), round(y, 2)] for x, y in pts],
                                     note=note))
                k += 1
    return out


def trees_around(b: Building, offset: float = 6.0, spacing: float = 8.0, clear: float = 4.0,
                 note: str = "") -> list[Landscape]:
    """Trees on a line `offset` m out from each block, every `spacing` m, keeping clear of the entrances and of
    the other blocks."""
    blocks = ground_blocks(b)
    if not blocks:
        raise ValueError("Design the building first")
    doors = _ground_doors(b)
    near = lambda p: any(q0x - offset + 0.5 < p[0] < q1x + offset - 0.5 and q0y - offset + 0.5 < p[1] < q1y + offset - 0.5  # noqa: E731
                         for q0x, q0y, q1x, q1y in blocks)
    pts = []
    for x0, y0, x1, y1 in blocks:
        ring = [[x0 - offset, y0 - offset], [x1 + offset, y0 - offset], [x1 + offset, y1 + offset], [x0 - offset, y1 + offset]]
        for i in range(4):
            a, c = ring[i], ring[(i + 1) % 4]
            L = math.hypot(c[0] - a[0], c[1] - a[1])
            n = max(1, int(L // spacing))
            for j in range(n):
                t = j / n
                p = [round(a[0] + (c[0] - a[0]) * t, 2), round(a[1] + (c[1] - a[1]) * t, 2)]
                if near(p) or any(math.hypot(p[0] - d[0], p[1] - d[1]) < offset + clear / 2 for d in doors)                         or any(math.hypot(p[0] - q[0], p[1] - q[1]) < spacing / 2 for q in pts):
                    continue
                pts.append(p)
    k = _next_landscape_id(b)
    return [Landscape(id=f"L{k + j}", kind="tree", points=[p], note=note) for j, p in enumerate(pts[:200])]


def summary(b: Building) -> dict:
    """Headline figures: floors, gross floor area, height, walls, doors, windows, roof, placed on the site plan."""
    return {"floors": len(b.levels),
            "gross_floor_m2": round(sum(area(s.outline) for s in b.slabs if s.level < len(b.levels)), 1),
            "height_m": round(max((lv.elevation + lv.height for lv in b.levels), default=0.0), 2),
            "walls": len(b.walls), "doors": sum(o.kind == "door" for o in b.openings),
            "windows": sum(o.kind == "window" for o in b.openings), "stairs": len(b.stairs), "columns": len(b.columns),
            "roof": ", ".join(r.kind if r.kind == "flat" else f"{r.kind} {r.pitch:g}°" for r in b.roofs) or "none",
            "landscape": {k: n for k, n in ((k, sum(x.kind == k for x in b.landscape)) for k in
                                            (*LANDSCAPE_AREAS, "hedge", "tree")) if n},
            "placed": b.origin is not None}


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
    """(risers, riser height, going length) of the whole stair up one level."""
    h = b.levels[min(s.level, len(b.levels) - 1)].height
    n = max(1, math.ceil(h / s.max_riser - 1e-9))
    return n, h / n, (n - 1) * s.tread


GAP = 0.1  # between the two flights of a dog-leg


def stair_flights(b: Building, s: Stair) -> tuple[list[tuple], Optional[list[Pt]]]:
    """The flights of a stair: (x, y, angle deg, risers, first riser number) each, and the half landing's outline
    for a dog-leg (None for a straight flight)."""
    n, rise, _ = stair_steps(b, s)
    if s.flights == 1:
        return [(s.x, s.y, s.angle, n, 0)], None
    n1 = math.ceil(n / 2)
    a = math.radians(s.angle)
    ux, uy, rx, ry = math.cos(a), math.sin(a), math.sin(a), -math.cos(a)  # forward, and to the right
    L1 = n1 * s.tread  # to the landing's near edge
    off = s.width + GAP
    landing = [[s.x - rx * s.width / 2 + ux * L1, s.y - ry * s.width / 2 + uy * L1],
               [s.x + rx * (off + s.width / 2) + ux * L1, s.y + ry * (off + s.width / 2) + uy * L1],
               [s.x + rx * (off + s.width / 2) + ux * (L1 + s.width), s.y + ry * (off + s.width / 2) + uy * (L1 + s.width)],
               [s.x - rx * s.width / 2 + ux * (L1 + s.width), s.y - ry * s.width / 2 + uy * (L1 + s.width)]]
    second = (s.x + rx * off + ux * L1, s.y + ry * off + uy * L1, (s.angle + 180) % 360, n - n1, n1)
    return [(s.x, s.y, s.angle, n1, 0), second], landing


def top_height(b: Building) -> float:
    """The highest point: the top storey, or a roof's ridge / apex / parapet over the storey it stands on."""
    top = max(lv.elevation + lv.height for lv in b.levels)
    for r in b.roofs:
        lv = b.levels[min(r.level, len(b.levels) - 1)]
        top = max(top, lv.elevation + lv.height + roof_geometry(r)["rise"] + (r.mast if r.kind == "dome" else 0.0))
    return top


def arch_profile(c0: float, c1: float, rise: float, n: int = 12) -> list[tuple[float, float]]:
    """A two-centred pointed arch from c0 to c1 rising `rise` at the middle: (position across, height) points, the
    springings and the apex included. Each half is an arc of radius (rise2 + a2) / 2a, centred on the springing line."""
    a = (c1 - c0) / 2
    if a <= 0 or rise <= 0:
        return [(c0, 0.0), (c1, 0.0)]
    rad = (rise * rise + a * a) / (2 * a)
    left = [(c0 + a * k / n, math.sqrt(max(0.0, rad * rad - (rad - a * k / n) ** 2))) for k in range(n + 1)]
    right = [(c1 - (c - c0), z) for c, z in reversed(left[:-1])]
    return left + right


def dome_rings(r: Roof, n: int = 16) -> list[tuple[float, float, float, float, float]]:
    """A dome's horizontal sections from the springing to the top: (x0, x1, y0, y1, height above the springing).
    Across x its outline is a pointed arch or a quarter-ellipse each side (the profile) rising `rise`; along y the
    same curve; each section keeps the cap's size at least, and the lean holds one side straight."""
    o = r.overhang
    X0, X1, Y0, Y1 = r.x0 - o, r.x1 + o, r.y0 - o, r.y1 + o
    ax, ay = (X1 - X0) / 2, (Y1 - Y0) / 2
    span = 2 * ax if r.ridge == "y" else 2 * ay
    rise = span / 2 * math.tan(math.radians(r.pitch))
    capx, capy = min(r.cap, 2 * ax), min(r.cap, 2 * ay)
    if r.profile == "round":
        fz = [(math.cos(math.pi / 2 * k / n), rise * math.sin(math.pi / 2 * k / n)) for k in range(n + 1)]
    else:
        fz = [((ax - c) / ax, z) for c, z in arch_profile(0.0, 2 * ax, rise, n)[: n + 1]]
    xc = (X0 + X1) / 2
    out = []
    for f, z in fz:
        wx = capx + (2 * ax - capx) * f
        wy = capy + (2 * ay - capy) * f
        y0 = Y0 + (2 * ay - wy) * (1 - r.lean) / 2
        out.append((xc - wx / 2, xc + wx / 2, y0, y0 + wy, z))
    return out


def dome_outline(r: Roof, proj) -> list[tuple[float, float]]:
    """The dome seen in elevation: (position across the view, height above the springing), from the left foot over
    the top to the right foot; proj maps a plan point to its position across the view."""
    rings = dome_rings(r)
    spans = []
    for x0, x1, y0, y1, z in rings:
        us = [proj((x, y)) for x in (x0, x1) for y in (y0, y1)]
        spans.append((min(us), max(us), z))
    return [(lo, z) for lo, _, z in spans] + [(hi, z) for _, hi, z in reversed(spans)]


def roof_geometry(r: Roof) -> dict:
    """Plan size with the overhang, the rise, the sloped covering area, ridge, eaves and hip lengths."""
    if r.kind == "dome":  # its surface band by band and its cap; covering and glazing share it (fins and glass)
        rings = dome_rings(r)
        area = 0.0
        for (a0, a1, b0, b1, z), (c0, c1, d0, d1, z2) in zip(rings, rings[1:]):
            for p, q in ((b0, d0), (b1, d1)):  # the faces along x, at each side in y
                area += ((a1 - a0) + (c1 - c0)) / 2 * math.hypot(q - p, z2 - z)
            for p, q in ((a0, c0), (a1, c1)):  # the faces along y
                area += ((b1 - b0) + (d1 - d0)) / 2 * math.hypot(q - p, z2 - z)
        x0, x1, y0, y1, ztop = rings[-1]
        area += (x1 - x0) * (y1 - y0)
        L, W = rings[0][1] - rings[0][0], rings[0][3] - rings[0][2]
        return {"plan": L * W, "area": area, "rise": ztop, "ridge": 0.0, "eaves": 2 * (L + W), "hips": 0.0,
                "ends": 0.0}
    L, W = (r.x1 - r.x0) + 2 * r.overhang, (r.y1 - r.y0) + 2 * r.overhang
    along, across = (L, W) if r.ridge == "x" else (W, L)
    t = math.tan(math.radians(r.pitch)) if r.kind != "flat" else 0.0
    if r.kind == "arch":  # the vault's curved surface, and its two pointed end walls
        rise = across / 2 * t
        prof = arch_profile(0.0, across, rise)
        arc = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(prof, prof[1:]))
        ends = sum((q[0] - p[0]) * (p[1] + q[1]) / 2 for p, q in zip(prof, prof[1:]))
        return {"plan": L * W, "area": arc * along, "rise": rise, "ridge": along, "eaves": 2 * along, "hips": 0.0,
                "ends": 2 * ends}
    if r.kind == "flat":  # the parapet, if any, is the top of the building
        return {"plan": L * W, "area": L * W, "rise": r.parapet, "ridge": 0.0, "eaves": 2 * (L + W), "hips": 0.0,
                "parapet": r.parapet * 2 * ((r.x1 - r.x0) + (r.y1 - r.y0))}
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
    use: Literal["general", "house", "office", "hospital", "school", "apartments"] = "general"  # names the rooms
    # a corridor down the length of the building with rooms off it (both sides when deep enough), stair cores at
    # its ends; None: 1.8 m (2.4 m for a hospital), 0: rooms open into each other (a house)
    corridor: Optional[float] = Field(default=None, ge=0, le=6)
    flat_width: Optional[float] = Field(default=None, ge=6, le=16)  # apartments: width of a flat, m (None: 11)
    parapet: float = Field(default=1.0, ge=0, le=3)        # flat roofs: parapet height (0 = none)
    # adding a block to the building (a wing, or a tower on a podium): where its south-west corner goes and the
    # floor it starts from (0 = on the ground; 2 = on top of a two-storey podium)
    x: float = Field(default=0.0, ge=-500, le=500)
    y: float = Field(default=0.0, ge=-500, le=500)
    start_floor: int = Field(default=0, ge=0, le=59)


ROOM_NAMES = {  # (main rooms, service rooms by the stairs, the room inside the main door)
    "general": ("Room", ["Toilets", "Store", "Plant room"], "Entrance hall"),
    "office": ("Office", ["Toilets", "Meeting room", "Kitchenette", "Store"], "Reception"),
    "hospital": ("Ward", ["Nurse station", "Toilets", "Sluice room", "Store"], "Reception"),
    "school": ("Classroom", ["Toilets", "Staff room", "Store"], "Entrance hall"),
    "apartments": ("Apartment", ["Refuse room", "Store"], "Entrance hall"),
    "house": ("Bedroom", ["Bathroom", "Kitchen"], "Living room"),
}


def generate(p: AutoParams) -> Building:
    """A building made to the numbers: outer walls, rooms, doors and windows, slabs, stairs and a roof.

    Buildings deep enough get a corridor down their length with rooms off it (both sides when there is room,
    otherwise one), a stair core at one end (both ends past 30 m, for a second way out), a lift on three floors
    or more, service rooms by the cores and a hall inside the main door. Small buildings and houses (corridor 0)
    are a grid of rooms opening into each other. Windows sit in the middle of each room's outside wall."""
    W, D, te, ti = p.width, p.depth, p.external_wall, p.internal_wall
    b = Building(levels=[Level(name="Ground floor" if k == 0 else f"Floor {k}", elevation=round(k * p.floor_height, 3),
                               height=p.floor_height) for k in range(p.floors)])
    cw = p.corridor if p.corridor is not None else (2.4 if p.use == "hospital" else 1.8)
    if p.use == "house" and p.corridor is None:
        cw = 0.0
    # work along the length (u) and across it (v); a building deeper than it is wide runs north-south
    along_x = W >= D
    Lu, Lv = (W, D) if along_x else (D, W)
    P = (lambda u, v: [round(u, 4), round(v, 4)]) if along_x else (lambda u, v: [round(v, 4), round(u, 4)])
    u0, v0, u1, v1 = te / 2, te / 2, Lu - te / 2, Lv - te / 2  # wall centrelines
    inner = v1 - v0 - te
    layout = "grid"
    if cw > 0 and (Lu >= 15 or p.corridor):  # small buildings stay a few rooms, unless a corridor is asked for
        layout = "double" if inner >= cw + 6.0 else "single" if inner >= cw + 3.0 else "grid"
    if layout == "grid":
        _grid_floors(b, p, W, D, te, ti)
    else:
        _corridor_floors(b, p, P, along_x, u0, v0, u1, v1, cw, layout)
    top = p.floors - 1
    if p.roof == "flat":
        b.slabs.append(Slab(id="SR", level=p.floors, outline=[[0, 0], [W, 0], [W, D], [0, D]], thickness=0.15))
    b.roofs.append(Roof(id="R1", level=top, x0=0, y0=0, x1=W, y1=D, kind=p.roof, pitch=p.pitch if p.roof != "flat" else 0,
                        overhang=p.overhang if p.roof != "flat" else 0, ridge="x" if W >= D else "y",
                        covering="concrete" if p.roof == "flat" else p.covering,
                        parapet=p.parapet if p.roof == "flat" else 0))
    return b


class _Ids:
    def __init__(self):
        self.n = {"W": 0, "O": 0, "RM": 0}

    def __call__(self, k: str) -> str:
        self.n[k] += 1
        return f"{k}{self.n[k]:03d}"


def _grid_floors(b: Building, p: AutoParams, W, D, te, ti):
    """Rooms on a grid opening into each other, a stair hall up the west wall (houses, small buildings)."""
    x0, y0, x1, y1 = te / 2, te / 2, W - te / 2, D - te / 2
    nid = _Ids()
    stair_w = 1.0
    hall = x0 + te / 2 + stair_w + 0.1 if p.floors > 1 else None
    main, service, entry = ROOM_NAMES[p.use]
    for lv in range(p.floors):
        outer = []
        for a, c in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            w = Wall(id=nid("W"), level=lv, a=list(a), b=list(c), thickness=te, kind="external", material=p.material)
            b.walls.append(w)
            outer.append(w)
        dw = 1.8 if p.door_style == "double" else 1.0
        for side, w in enumerate(outer):  # windows evenly along each outer wall, clear of the main door
            L = length(w)
            count = max(1, int(L // p.window_spacing))
            ww = min(p.window_width, L / count - 0.4)
            for k in range(count):
                off = L * (k + 0.5) / count
                if lv == 0 and side == 0 and abs(off - L / 2) < (ww + dw) / 2 + 0.3:
                    continue
                b.openings.append(Opening(id=nid("O"), wall=w.id, kind="window", offset=round(off, 3), width=ww,
                                          height=p.window_height, sill=0.9, style=p.window_style))
        if lv == 0:
            b.openings.append(Opening(id=nid("O"), wall=outer[0].id, kind="door", offset=round(length(outer[0]) / 2, 3),
                                      width=dw, height=2.4 if p.door_style == "arched" else 2.1, sill=0, style=p.door_style))
        cw, ch = (x1 - x0) / p.rooms_x, (y1 - y0) / p.rooms_y
        for i in range(1, p.rooms_x):
            x = x0 + i * cw
            for j in range(p.rooms_y):
                w = Wall(id=nid("W"), level=lv, a=[x, y0 + j * ch], b=[x, y0 + (j + 1) * ch], thickness=ti,
                         kind="internal", material=p.material)
                b.walls.append(w)
                if ch >= 1.8:
                    b.openings.append(Opening(id=nid("O"), wall=w.id, kind="door", offset=round(ch / 2, 3), width=0.9,
                                              height=2.1, sill=0, style="single"))
        for j in range(1, p.rooms_y):
            y = y0 + j * ch
            for i in range(p.rooms_x):
                xa = max(x0 + i * cw, hall) if hall and i == 0 else x0 + i * cw
                if x0 + (i + 1) * cw - xa < 0.5:
                    continue
                w = Wall(id=nid("W"), level=lv, a=[xa, y], b=[x0 + (i + 1) * cw, y], thickness=ti,
                         kind="internal", material=p.material)
                b.walls.append(w)
                L = length(w)
                if L >= 1.8 and i == 0:
                    b.openings.append(Opening(id=nid("O"), wall=w.id, kind="door", offset=round(L / 2, 3), width=0.9,
                                              height=2.1, sill=0, style="single"))
        # names: the room inside the main door, then service rooms, then main rooms
        cells = sorted(((i, j) for i in range(p.rooms_x) for j in range(p.rooms_y)),
                       key=lambda c: (c[1], abs(c[0] - (p.rooms_x - 1) / 2)))
        for k, (i, j) in enumerate(cells):
            name = entry if k == 0 and lv == 0 else service[(k - 1) % len(service)] if 0 < k <= len(service) \
                else main
            b.rooms.append(Room(id=nid("RM"), level=lv, name=name, x=round(x0 + (i + 0.5) * cw, 2),
                                y=round(y0 + (j + 0.5) * ch, 2), area=round((cw - ti) * (ch - ti), 1), w=round(cw - ti, 2),
                                rect=_rect((x0 + i * cw, y0 + j * ch), (x0 + (i + 1) * cw, y0 + (j + 1) * ch)),
                                door=[round(x0 + (i + 0.5) * cw, 2), round(y0 + j * ch, 2)] if j else None))
        b.slabs.append(Slab(id=f"S{lv + 1:02d}", level=lv, outline=[[0, 0], [W, 0], [W, D], [0, D]], thickness=0.15))
        if hall and lv < p.floors - 1:
            b.stairs.append(Stair(id=f"ST{lv + 1:02d}", level=lv, x=x0 + te / 2 + stair_w / 2 + 0.05,
                                  y=y0 + te / 2 + 0.3, angle=90.0, width=stair_w,
                                  max_riser=0.19 if p.use == "house" or p.floors <= 2 else 0.175))
        if p.columns:
            xs = [x0 + i * cw for i in range(p.rooms_x + 1)]
            ys = [y0 + j * ch for j in range(p.rooms_y + 1)]
            b.columns += [Column(id=f"C{lv}-{i}-{j}", level=lv, x=x, y=y, size=max(te, 0.3))
                          for i, x in enumerate(xs) for j, y in enumerate(ys)]


def _rect(p0, p1) -> list[float]:
    return [round(min(p0[0], p1[0]), 3), round(min(p0[1], p1[1]), 3), round(max(p0[0], p1[0]), 3), round(max(p0[1], p1[1]), 3)]


def _corridor_floors(b: Building, p: AutoParams, P, along_x, u0, v0, u1, v1, cw, layout):
    """A corridor down the length with rooms off it; u runs along the corridor, v across it, P(u, v) is the plan
    point. layout: "double" (rooms both sides, corridor in the middle) or "single" (rooms south, corridor north)."""
    te, ti = p.external_wall, p.internal_wall
    nid = _Ids()
    main, service, entry = ROOM_NAMES[p.use]
    if layout == "double":
        cv0 = round((v0 + v1) / 2 - cw / 2, 3)
        cv1 = round(cv0 + cw, 3)
    else:
        cv0, cv1 = round(v1 - cw - te / 2, 3), v1
    # stair cores: a straight flight across the south band (or along it when the band is too shallow)
    rise_n = max(1, math.ceil(p.floor_height / 0.175 - 1e-9))
    stair_w = 1.2 if p.use in ("hospital", "school") or p.floors >= 4 else 1.0
    dogleg = rise_n > 16 or p.floors >= 3
    flight = (math.ceil(rise_n / 2) * 0.28 + stair_w + 0.6) if dogleg else (rise_n * 0.28 + 0.6)
    across = (cv0 - v0) >= flight
    core = round(max(2 * stair_w + GAP + 0.5, stair_w + 1.6) if (across and dogleg) else stair_w + 1.6 if across
                 else flight + 0.4, 2)
    ends = 2 if (u1 - u0) > 30 and p.floors > 1 else 1 if p.floors > 1 else 0
    span0, span1 = u0 + (core if ends >= 1 else 0), u1 - (core if ends == 2 else 0)
    door_w = 1.2 if p.use == "hospital" else 0.9
    nb = max(1, min(int((span1 - span0) // 2.6), max(p.rooms_x, round((span1 - span0) / 6))))  # rooms 2.6-6 m wide
    flats = p.use == "apartments"
    if flats:  # a flat is a bay about 8-11 m wide: one bedroom below 9.5 m, two above
        nb = max(1, round((span1 - span0) / (p.flat_width or 11.0)))
    bays = [span0 + (span1 - span0) * k / nb for k in range(nb + 1)]
    cuts = ([u0] if ends >= 1 else []) + bays + ([u1] if ends == 2 else [])
    cuts = sorted(set(round(c, 4) for c in cuts))
    centre = (u1 + u0) / 2
    lobby = next((k for k in range(len(cuts) - 1) if cuts[k] <= centre <= cuts[k + 1]), 0)  # the bay at the middle
    is_core = lambda k: (ends >= 1 and k == 0) or (ends == 2 and k == len(cuts) - 2)  # noqa: E731
    dw = 1.8 if p.door_style == "double" else 1.0
    lift = p.floors >= 3 and p.use != "house"
    frame_u: set = set()  # extra frame lines through the flats (their room partitions), for shorter spans
    near_core = lambda k: (ends >= 1 and k == 0) or (ends == 2 and k == len(cuts) - 2) or k in (1, len(cuts) - 3)  # noqa: E731

    def flat_split(a, c):
        """The rooms of a flat across its width, (facade rooms, corridor-side rooms): the hall and dining room runs
        along the corridor side and overlaps every facade room, so each room opens off it; the kitchen is open to
        the living room and shares its windows; bathrooms are inside, with mechanical extract."""
        W = c - a
        if W >= 9.5:  # two bedrooms either side of the living room and kitchen; bathroom and shower room behind them
            bw = min(3.4, (W - 4.0) / 2)
            fac = [("Bedroom", a, a + bw), ("Living / kitchen", a + bw, c - bw), ("Bedroom", c - bw, c)]
            svc = [("Bathroom", a, a + bw - 0.9), ("Hall", a + bw - 0.9, c - bw + 0.9),
                   ("Shower room", c - bw + 0.9, c)]
        else:  # one bedroom
            lw, bath = a + W * 0.55, a + min(2.4, W * 0.35)
            fac = [("Living / kitchen", a, lw), ("Bedroom", lw, c)]
            svc = [("Bathroom", a, bath), ("Hall", bath, c)]
        return fac, svc

    def is_flat(k, band, lv):
        if not flats or is_core(k):
            return False
        if band == "s":
            return not (lv == 0 and along_x and k == lobby) and cuts[k + 1] - cuts[k] >= 6
        return layout == "double" and cuts[k + 1] - cuts[k] >= 6  # the core bays are left for the lift and stores

    def flat(k, band, lv, facade, cdoor_wall, cdoor_off, number):
        """Lay out one flat in bay k of the south ("s") or north band: partitions, doors, windows, rooms."""
        a, c = cuts[k], cuts[k + 1]
        vc, vf = (cv0, v0) if band == "s" else (cv1, v1)
        vs = vc + (1 if vf > vc else -1) * 3.2
        fac, svc = flat_split(a, c)
        hall = next((x0, x1) for n, x0, x1 in svc if n.startswith("Hall"))
        unit = f"{lv}-{number:02d}"
        # the front door: FD30 self-closing, opening into the flat (out of the escape corridor)
        opening(cdoor_wall, cdoor_off((hall[0] + hall[1]) / 2), "door", 0.9, "fire", flip=True, rating=30)
        split = wall(P(a, vs), P(c, vs), "internal", lv)
        parts = {}
        for n, x0, x1 in svc[1:]:
            parts[("s", x0)] = wall(P(x0, vc), P(x0, vs), "internal", lv)
        for n, x0, x1 in fac[1:]:
            parts[("f", x0)] = wall(P(x0, vs), P(x0, vf), "internal", lv)
            frame_u.add(round(x0, 4))
        for n, x0, x1 in svc:  # bathrooms off the hall, through the partition between them
            if n in ("Bathroom", "Shower room"):
                xw = x1 if x0 == a else x0
                opening(parts[("s", xw)], 1.6, "door", 0.8, "single")
        for n, x0, x1 in fac:  # every facade room off the hall, through the split wall where they overlap
            lo, hi = max(x0, hall[0]), min(x1, hall[1])
            if n == "Living / kitchen":
                opening(split, (lo + hi) / 2 - a, "door", min(1.6, hi - lo - 0.6), "double")
            else:
                mid = (lo + hi) / 2 if hi - lo < 1.6 else (lo + 0.6 if x0 >= hall[0] else hi - 0.6)
                opening(split, mid - a, "door", min(0.8, hi - lo - 0.1), "single")
            off = (lambda u: u - u0) if facade is south else (lambda u: u1 - u)
            lo2, hi2 = sorted((off(x0), off(x1)))
            windows(facade, lo2 + 0.15, hi2 - 0.15)
        for n, x0, x1, va, vb in [(n, x0, x1, vc, vs) for n, x0, x1 in svc] + [(n, x0, x1, vs, vf) for n, x0, x1 in fac]:
            r = _rect(P(x0, va), P(x1, vb))
            area = round((r[2] - r[0] - ti) * (r[3] - r[1] - ti), 1)
            xy = P((x0 + x1) / 2, (va + vb) / 2)
            door = P((hall[0] + hall[1]) / 2, vc) if n.startswith("Hall") else P((max(x0, hall[0]) + min(x1, hall[1])) / 2, vs) \
                if va == vs else P(hall[0] if x0 < hall[0] else hall[1], (vc + vs) / 2)
            b.rooms.append(Room(id=nid("RM"), level=lv, name=n, x=xy[0], y=xy[1], area=area,
                                w=round((x1 - x0 - ti) if along_x else abs(vb - va) - ti, 2), rect=r, door=door,
                                unit=unit))

    def wall(a, c, kind, lv, core=False):  # core: a 300 mm reinforced concrete wall of a stair / lift core (bracing)
        w = Wall(id=nid("W"), level=lv, a=a, b=c, thickness=0.3 if core else te if kind == "external" else ti, kind=kind,
                 material="concrete" if core else p.material)
        b.walls.append(w)
        return w

    core_lines = {cuts[1]} | ({cuts[-2]} if ends == 2 else set()) if ends else set()
    core_bays = ([(cuts[0], cuts[1])] if ends >= 1 else []) + ([(cuts[-2], cuts[-1])] if ends == 2 else [])
    spine_bays = (([(cuts[1], cuts[2])] if ends >= 1 and len(cuts) > 3 else []) +
                  ([(cuts[-3], cuts[-2])] if ends == 2 and len(cuts) > 4 else [])) if p.floors >= 6 else []

    class Run:
        """A wall line along u at v, made of segments: the stretches across the stair / lift cores in reinforced
        concrete (they close the cores), the rest in the walling. Offsets are measured along the whole line, from
        its start (u0, or u1 when it runs backwards), as for a single wall."""
        def __init__(self, v, kind, lv, rev=False, spine=False):
            # spine: the corridor walls, in RC on through the bay next to each core too (it lengthens the cores
            # along the building, where they are shortest, against wind and earthquake)
            bays = core_bays + (spine_bays if spine else [])
            self.rev, self.segs = rev, []
            stops = sorted({u0, u1} | {x for lo, hi in bays for x in (lo, hi) if u0 < x < u1})
            for s0, s1 in zip(stops, stops[1:]):
                core_ = any(lo - 1e-6 <= s0 and s1 <= hi + 1e-6 for lo, hi in bays)
                w = wall(P(s1, v), P(s0, v), kind, lv, core_) if rev else wall(P(s0, v), P(s1, v), kind, lv, core_)
                self.segs.append((s0, s1, w))
            self.id = self.segs[0][2].id

        def at(self, off):
            u = u1 - off if self.rev else u0 + off
            for s0, s1, w in self.segs:
                if s0 - 1e-6 <= u <= s1 + 1e-6:
                    return w, (s1 - u) if self.rev else (u - s0)
            return self.segs[-1][2], 0.0

    def opening(w, off, kind, width, style, flip=False, rating=0):
        if isinstance(w, Run):
            w, off = w.at(off)
        b.openings.append(Opening(id=nid("O"), wall=w.id, kind=kind, offset=round(off, 3), width=round(width, 2),
                                  height=(2.4 if style == "arched" else 2.1) if kind == "door" else p.window_height,
                                  sill=0 if kind == "door" else 0.9, style=style, flip=flip,
                                  rating=rating or (60 if style == "fire" else 0)))

    def windows(w, a_off, b_off, skip=None):  # windows centred in a stretch of an outside wall
        L = b_off - a_off
        if L < 1.2:
            return
        count = max(1, round(L / p.window_spacing))
        ww = min(p.window_width, L / count - 0.6)
        if ww < 0.5:
            return
        for k in range(count):
            off = a_off + L * (k + 0.5) / count
            if skip and abs(off - skip[0]) < (ww + skip[1]) / 2 + 0.3:
                continue
            opening(w, off, "window", ww, p.window_style)

    for lv in range(p.floors):
        # the long faces in segments (solid RC across the cores); the end walls of the stair cores in RC
        south = Run(v0, "external", lv)
        east = wall(P(u1, v0), P(u1, v1), "external", lv, core=ends == 2 and lv < p.floors)
        north = Run(v1, "external", lv, rev=True)
        west = wall(P(u0, v1), P(u0, v0), "external", lv, core=ends >= 1)
        # the main door: in the middle of the south face, into the hall (along x); at the corridor's south end
        # when the building runs north-south
        if along_x:
            door_at = centre - u0
            if lv == 0:
                opening(south, door_at, "door", dw, p.door_style)
        else:
            door_at = v1 - (cv0 + cv1) / 2
            if lv == 0:
                opening(west, door_at, "door", min(dw, cw - 0.2), p.door_style)
        # the lift shafts: RC boxes at the outer end of the lift bays (the gable, the core cross wall and the
        # facade are three sides; a fourth wall with the lift door faces the lobby)
        lift_bays = ([0] if lift and layout == "double" and ends else []) + \
            ([len(cuts) - 2] if lift and layout == "double" and p.floors >= 6 and ends == 2 else [])
        v_shaft = v1 - SHAFT_DEPTH
        for kk in lift_bays:
            sw = wall(P(cuts[kk], v_shaft), P(cuts[kk + 1], v_shaft), "internal", lv, core=True)
            opening(sw, (cuts[kk + 1] - cuts[kk]) / 2, "door", 1.1, "sliding")
        if lv == 0 and lift_bays:  # a back door from the car park, through the gable into the lift lobby
            back_door = (cv1 + v_shaft) / 2
            opening(west, v1 - back_door, "door", 1.0, "single")
        # each stair core: on the ground floor its own exit (the core's outside walls are solid RC: the stair is
        # vented by an automatic smoke vent at its head, and lit by its windows on the end wall)
        for e in range(ends):
            if lv == 0:
                end, off = (west, v1 - (cv0 - 0.9)) if e == 0 else (east, (cv0 - 0.9) - v0)
                opening(end, off, "door", 1.0, "fire", flip=True)
        # windows: one set per room on the long faces, and on the ends for each band and the corridor
        for k in range(len(cuts) - 1):
            a, c = cuts[k], cuts[k + 1]
            skip = (door_at, dw) if (lv == 0 and along_x and k == lobby) else None
            if not is_core(k) and not is_flat(k, "s", lv):
                windows(south, a - u0, c - u0, skip)
            if layout == "double" and not is_flat(k, "n", lv) and not is_core(k):
                windows(north, u1 - c, u1 - a)
        for w, far in ((east, False), (west, True)):  # end walls run v0 -> v1 (east) and v1 -> v0 (west)
            off = (lambda v: v1 - v) if far else (lambda v: v - v0)
            bands = [(v0, cv0)] + ([(cv1, v1)] if layout == "double" else [])
            for va, vb in bands:
                exit_ = (far and ends >= 1) or (not far and ends == 2)  # this end has a stair, its exit door below
                if va == cv1 and ((far and 0 in lift_bays) or (not far and len(cuts) - 2 in lift_bays)):
                    vb = v_shaft  # no window into the lift shaft
                lo, hi = sorted((off(va), off(vb)))
                skip = (off(cv0 - 0.9), 1.0) if (lv == 0 and exit_ and va == v0) else None
                if lv == 0 and far and va == cv1 and lift_bays:
                    skip = (off(back_door), 1.0)
                windows(w, lo, hi, skip)  # into the rooms (and the stair cores, for light)
            if not (lv == 0 and not along_x and far):  # a window at the corridor's end (not over the door)
                mid = off((cv0 + cv1) / 2)
                opening(w, mid, "window", min(1.0, cw - 0.4), p.window_style)
        # corridor walls, with a door into each room (a wide opening into the hall on the ground floor)
        cs = Run(cv0, "internal", lv, spine=True)
        cn = Run(cv1, "internal", lv, rev=True, spine=True) if layout == "double" else None
        for k in range(len(cuts) - 1):
            a, c = cuts[k], cuts[k + 1]
            mid = (a + c) / 2
            if lv == 0 and along_x and k == lobby:
                opening(cs, mid - u0, "door", min(c - a - 0.6, 2.4), "double")
            elif is_core(k):  # the stair: a fire door (FD60) from the corridor, opening towards the stair
                opening(cs, mid - u0, "door", 1.0, "fire", flip=True)
            elif not is_flat(k, "s", lv):
                opening(cs, mid - u0, "door", door_w, "double" if door_w > 1 else "single")
            if cn is not None and not is_flat(k, "n", lv):
                opening(cn, u1 - mid, "door", door_w, "double" if door_w > 1 else "single")
        # cross walls between the rooms; those closing the stair and lift cores in reinforced concrete (they brace
        # the frame against wind and earthquake)
        for c in cuts[1:-1]:
            wall(P(c, v0), P(c, cv0), "internal", lv, core=c in core_lines)
            if layout == "double":
                wall(P(c, cv1), P(c, v1), "internal", lv, core=c in core_lines)
        if ends and layout == "double" and p.floors > 2:
            # a protected lobby at each core: a fire door across the corridor, so stair, lobby and lift form one
            # fire-fighting shaft; the doors open towards the stairs
            for c in sorted(core_lines):
                cw_ = wall(P(c, cv0), P(c, cv1), "internal", lv, core=True)
                opening(cw_, (cv1 - cv0) / 2, "door", min(1.6, cv1 - cv0 - 0.2), "fire", flip=c != cuts[1], rating=60)
            if (u1 - u0) > 30:  # and the corridor split in the middle (smoke), at the bay line nearest the centre
                mids = [c for c in cuts[2:-2] if c not in core_lines]
                if mids:
                    cm = min(mids, key=lambda c: abs(c - centre))
                    cw_ = wall(P(cm, cv0), P(cm, cv1), "internal", lv)
                    opening(cw_, (cv1 - cv0) / 2, "door", min(1.6, cv1 - cv0 - 0.2), "fire", rating=30)
        # room names and areas
        nserv, nflat = 0, 0
        for k in range(len(cuts) - 1):
            a, c = cuts[k], cuts[k + 1]
            if is_flat(k, "s", lv):
                nflat += 1
                flat(k, "s", lv, south, cs, lambda u: u - u0, nflat)
            if is_flat(k, "n", lv):
                nflat += 1
                flat(k, "n", lv, north, cn, lambda u: u1 - u, nflat)
            area_s = round((c - a - ti) * (cv0 - v0 - te / 2 - ti / 2), 1)
            if is_core(k):
                name = "Stair"
            elif lv == 0 and along_x and k == lobby:
                name = entry
            else:
                name = main
            xy = P((a + c) / 2, (v0 + cv0) / 2)
            if not is_flat(k, "s", lv):
                b.rooms.append(Room(id=nid("RM"), level=lv, name=name, x=xy[0], y=xy[1], area=area_s,
                                    w=round(c - a - ti, 2) if along_x else round(cv0 - v0 - te, 2),
                                    rect=_rect(P(a, v0), P(c, cv0)), door=P((a + c) / 2, cv0)))
            if layout == "double" and not is_flat(k, "n", lv):  # by the cores: the lift, then service rooms
                if near_core(k) and (lift and k == 0):  # above 6 storeys it is a firefighting lift (Code 2024)
                    name_n = "Firefighting lift and lobby" if p.floors > 6 else "Lift and lobby"
                elif near_core(k) and lift and p.floors >= 6 and ends == 2 and k == len(cuts) - 2:
                    name_n = "Lift and lobby"  # a second lift: one is not enough for this many flats
                elif near_core(k):
                    name_n = service[nserv % len(service)]
                    nserv += 1
                else:
                    name_n = main
                area_n = round((c - a - ti) * (v1 - cv1 - te / 2 - ti / 2), 1)
                xy = P((a + c) / 2, (cv1 + v1) / 2)
                b.rooms.append(Room(id=nid("RM"), level=lv, name=name_n, x=xy[0], y=xy[1], area=area_n,
                                    w=round(c - a - ti, 2) if along_x else round(v1 - cv1 - te, 2),
                                    rect=_rect(P(a, cv1), P(c, v1)), door=P((a + c) / 2, cv1)))
        xy = P(centre - (min(5.0, (u1 - u0) / 5) if (u1 - u0) > 20 else 0), (cv0 + cv1) / 2)
        b.rooms.append(Room(id=nid("RM"), level=lv, name="Corridor", x=xy[0], y=xy[1],
                            area=round((u1 - u0 - te) * (cv1 - cv0 - ti), 1)))
        W_, D_ = (u1 + te / 2, v1 + te / 2) if along_x else (v1 + te / 2, u1 + te / 2)
        b.slabs.append(Slab(id=f"S{lv + 1:02d}", level=lv, outline=[[0, 0], [W_, 0], [W_, D_], [0, D_]], thickness=0.15))
        # stairs in the cores, up to the next floor
        if lv < p.floors - 1:
            for e in range(ends):
                ua, uc = (cuts[0], cuts[1]) if e == 0 else (cuts[-2], cuts[-1])
                if across and dogleg:  # a dog-leg: up from the outside wall, back down the other side
                    ang = 90.0 if along_x else 0.0
                    r = (math.sin(math.radians(ang)), -math.cos(math.radians(ang)))
                    du = r[0] if along_x else r[1]  # which way the second flight lies, along u
                    fu = ua + ti / 2 + 0.15 + stair_w / 2 if du > 0 else uc - ti / 2 - 0.15 - stair_w / 2
                    foot = P(fu, v0 + te / 2 + 0.3)
                elif across:  # climbing across the band, from the outside wall towards the corridor
                    foot, ang = P((ua + uc) / 2, v0 + te / 2 + 0.3), (90.0 if along_x else 0.0)
                else:  # along the band, from its outer end
                    up = 1 if e == 0 else -1
                    foot = P(ua + te / 2 + 0.2 if e == 0 else uc - ti / 2 - 0.2, v0 + te / 2 + stair_w / 2 + 0.1)
                    ang = (0.0 if up > 0 else 180.0) if along_x else (90.0 if up > 0 else 270.0)
                b.stairs.append(Stair(id=f"ST{lv + 1:02d}{'' if e == 0 else 'B'}", level=lv, x=foot[0], y=foot[1],
                                      angle=ang, width=stair_w, flights=2 if (across and dogleg) else 1))
        if p.columns:  # on the frame lines: the cross walls by the corridor and outside walls
            vs = [v0, cv0, cv1, v1] if layout == "double" else [v0, cv0, v1]
            pts = {tuple(P(u, v)) for u in sorted(set(cuts) | frame_u) for v in vs}
            b.columns += [Column(id=f"C{lv}-{i}", level=lv, x=x, y=y, size=max(te, 0.3))
                          for i, (x, y) in enumerate(sorted(pts))]


def add_block(b: Building, p: AutoParams) -> Building:
    """Add a block made to the brief to an existing building: a wing beside it, or a tower on top of a podium.
    The block's south-west corner goes to (p.x, p.y) and its floors start at p.start_floor; floors the building
    does not have yet are added. Where the block sits on a lower part, that part's roof becomes the floor."""
    if p.start_floor > len(b.levels):
        raise ValueError(f"start floor {p.start_floor}: the building has only {len(b.levels)} floor(s)")
    new = generate(p.model_copy(update={"floors": p.floors}))
    tag = 1 + max((int(r.id[1:].split("-")[0]) for r in b.roofs if r.id[1:].split("-")[0].isdigit()), default=1)
    pre = f"B{tag}-"
    s = p.start_floor
    for k in range(p.floors):  # the floors this block needs
        lv = s + k
        if lv >= len(b.levels):
            top = b.levels[-1]
            b.levels.append(Level(name=f"Floor {lv}", elevation=round(top.elevation + top.height, 3),
                                  height=p.floor_height, slab=top.slab))
    sh = lambda pt: [round(pt[0] + p.x, 4), round(pt[1] + p.y, 4)]  # noqa: E731
    for w in new.walls:
        b.walls.append(w.model_copy(update={"id": pre + w.id, "level": w.level + s, "a": sh(w.a), "b": sh(w.b)}))
    for o in new.openings:
        b.openings.append(o.model_copy(update={"id": pre + o.id, "wall": pre + o.wall}))
    if s > 0:  # a block on a podium has no front door: the main door belongs to the ground floor
        first = {pre + w.id for w in new.walls if w.level == 0 and w.kind == "external"}
        b.openings = [o for o in b.openings if not (o.wall in first and o.kind == "door")]
    for sl in new.slabs:
        lv = sl.level + s if sl.id != "SR" else s + p.floors
        b.slabs.append(sl.model_copy(update={"id": pre + sl.id, "level": lv, "outline": [sh(q) for q in sl.outline]}))
    for st in new.stairs:
        b.stairs.append(st.model_copy(update={"id": pre + st.id, "level": st.level + s, "x": st.x + p.x, "y": st.y + p.y}))
    for c in new.columns:
        b.columns.append(c.model_copy(update={"id": pre + c.id, "level": c.level + s, "x": c.x + p.x, "y": c.y + p.y}))
    for r in new.rooms:
        b.rooms.append(r.model_copy(update={
            "id": pre + r.id, "level": r.level + s, "x": r.x + p.x, "y": r.y + p.y,
            "rect": [r.rect[0] + p.x, r.rect[1] + p.y, r.rect[2] + p.x, r.rect[3] + p.y] if r.rect else None,
            "door": [r.door[0] + p.x, r.door[1] + p.y] if r.door else None}))
    for r in new.roofs:
        b.roofs.append(r.model_copy(update={"id": f"R{tag}", "level": r.level + s, "x0": r.x0 + p.x, "y0": r.y0 + p.y,
                                            "x1": r.x1 + p.x, "y1": r.y1 + p.y}))
    return Building.model_validate(b.model_dump())


# ---------------------------------------------------------------------------------------------------------
# quantities
# ---------------------------------------------------------------------------------------------------------
WALL_CODES = {"block": "BLOCKWORK", "brick": "BRICKWORK", "stone": "STONEWORK", "concrete": "CONC-WALL"}
DOOR_CODES = {"single": "DOOR-SINGLE", "double": "DOOR-DOUBLE", "sliding": "DOOR-SLIDING", "arched": "DOOR-ARCHED",
              "fire": "DOOR-FIRE"}
WINDOW_CODES = {"fixed": "WINDOW-FIXED", "casement": "WINDOW-CASEMENT", "sliding": "WINDOW-SLIDING", "hung": "WINDOW-HUNG"}
ROOF_CODES = {"iron sheets": "ROOF-SHEETS", "tiles": "ROOF-TILES", "concrete": "CONC-SLAB"}


def quantities(b: Building, bearing: float = 0.0) -> list[tuple[str, float, str]]:
    """(material code, quantity, how it was measured), from the model and the specification. A framed building
    (columns) is measured from its preliminary structural design (ftth/structure.py, bearing: kN/m2)."""
    from . import structure
    sp, out = b.spec, []
    dz = structure.design(b, bearing) if len(b.levels) > 1 else None

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
    slab_vol = sum(area(s.outline) * (dz["slab"] if dz and s.level > 0 else s.thickness) for s in b.slabs)
    suspended = [s for s in b.slabs if s.level > 0]
    add("CONC-SLAB", slab_vol, "Slabs: area x thickness" + (f" (suspended slabs {dz['slab'] * 1000:.0f} mm, "
                                                            f"preliminary design)" if dz else ""))
    add("FORMWORK", sum(area(s.outline) for s in suspended), "Soffits of suspended slabs")
    rc_faces = sum(2 * max(0.0, length(w) * b.wall_height(w) - sum(o.width * o.height for o in b.openings if o.wall == w.id))
                   for w in b.walls if w.material == "concrete")
    add("FORMWORK", rc_faces, "Both faces of the RC core and spine walls")
    add("SCREED", sum(area(s.outline) for s in b.slabs if s.level < len(b.levels)), "Floor screed on each floor")
    if b.columns and len(b.levels) > 1:  # RC slabs: the soffits skimmed and painted, no ceiling boards
        add("SOFFIT-SKIM", sum(area(s.outline) for s in b.slabs if s.level > 0), "Skim coat and paint to the RC slab soffits")
        add("CEILING", sum((r.x1 - r.x0) * (r.y1 - r.y0) for r in b.roofs if r.kind != "flat"), "Ceilings under pitched roofs")
    else:
        add("CEILING", sum(area(s.outline) for s in b.slabs if s.level > 0) +
            sum((r.x1 - r.x0) * (r.y1 - r.y0) for r in b.roofs if r.kind != "flat"), "Ceilings under slabs and roofs")
    if dz:  # the frame as designed: columns by level, beams on the frame lines, pads or a raft
        col_vol = dz["volumes"]["column"]
        add("CONC-COLUMN", col_vol, f"Columns as designed ({len(dz['columns'])} per floor, {dz['concrete']})")
        add("FORMWORK", sum(sum(4 * s * b.levels[i].height for i, s in enumerate(c["sizes"])) for c in dz["columns"]),
            "Column sides")
        beam_vol = dz["volumes"]["beam"]
        add("CONC-BEAM", beam_vol, f"Beams below the slabs ({dz['beam_x']['b'] * 1000:.0f} x {dz['beam_x']['h'] * 1000:.0f} "
                                   f"and {dz['beam_y']['b'] * 1000:.0f} x {dz['beam_y']['h'] * 1000:.0f} mm)")
        add("FORMWORK", beam_vol / max(dz["beam_x"]["b"], 0.2) * 1.2 + beam_vol / max(dz["beam_x"]["h"] - dz["slab"], 0.1),
            "Beam sides and soffits")
        fvol = dz["volumes"]["foundation"]
        add("CONC-FOOTING", fvol, f"Foundations as designed: {dz['foundation']['type']}")
        add("EXCAVATION", fvol * 1.4, "Excavation for the foundations, with working space")
        footing += fvol
        col_vol += beam_vol
    else:
        col_vol = sum(c.size * c.size * b.levels[min(c.level, len(b.levels) - 1)].height for c in b.columns)
        add("CONC-COLUMN", col_vol, "Columns: section x storey height")
        add("FORMWORK", sum(4 * c.size * b.levels[min(c.level, len(b.levels) - 1)].height for c in b.columns),
            "Column sides")
    stair_vol = 0.0
    for s in b.stairs:
        n, rise, going = stair_steps(b, s)
        stair_vol += s.width * (math.hypot(going, rise * n) * 0.15 + n * s.tread * rise / 2)
        if s.flights == 2:
            stair_vol += (2 * s.width + GAP) * s.width * 0.15  # the half landing
    add("CONC-STAIR", stair_vol, "Stairs: waist slab and steps")
    if dz:  # each element at its own scheme rate (kg/m3), the core walls included
        r_ = structure.REBAR
        wall_v = sum(length(w) * b.wall_height(w) * w.thickness for w in b.walls if w.material == "concrete")
        kg = (dz["volumes"]["foundation"] * r_["foundation"] + slab_vol * r_["slab"] + dz["volumes"]["column"] * r_["column"]
              + dz["volumes"]["beam"] * r_["beam"] + stair_vol * r_["stair"] + wall_v * r_["wall"]
              + (footing - dz["volumes"]["foundation"]) * r_["foundation"])
        add("REBAR", kg, f"Foundations {r_['foundation']}, slabs {r_['slab']}, columns {r_['column']}, beams {r_['beam']}, "
                         f"walls {r_['wall']} kg/m3")
    else:
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
            if o.style == "fire" and o.width >= 1.4:  # a pair of fire door leaves (cross-corridor)
                add("DOOR-FIRE-DOUBLE", 1, "Double-leaf fire doors across the corridor and lobbies")
                add("LINTEL", o.width + 0.3, "Over each opening, 150 mm bearing each side")
                continue
            add("DOOR-FD30" if o.style == "fire" and o.rating == 30 else DOOR_CODES[o.style], 1,
                "Fire doors FD30 (flat entrances, corridor)" if o.style == "fire" and o.rating == 30 else "Doors")
        else:
            add(WINDOW_CODES[o.style], o.width * o.height, "Windows: width x height")
        add("LINTEL", o.width + 0.3, "Over each opening, 150 mm bearing each side")
    for r in b.roofs:
        g = roof_geometry(r)
        if r.kind == "flat":  # a flat roof is its slab (above), with its parapet if it has one
            if g.get("parapet"):
                mat, t = next(((w.material, w.thickness) for w in b.walls if w.kind == "external"), ("block", 0.2))
                if mat == "concrete":
                    add("CONC-WALL", g["parapet"] * t, f"Parapet walls {r.parapet:g} m high round the flat roof")
                else:
                    add(WALL_CODES[mat] + "-EXT", g["parapet"], f"Parapet walls {r.parapet:g} m high round the flat roof")
                if sp.plaster:
                    add("RENDER", 2 * g["parapet"], "Both faces of the parapet walls")
            continue
        if r.kind == "dome":  # a steel crown: trusses and fins, glazing between them over most of the surface
            add(ROOF_CODES[r.covering], g["area"] * 0.38, "Dome crown: cladding of the fins")
            add("STEEL-STRUCT", g["area"] * 45, "Dome crown: steel trusses and fin framing, about 45 kg/m2")
            add("WINDOW-FIXED", g["area"] * 0.62, "Dome crown: glazing between the fins")
            add("GUTTER", g["eaves"], "Round the dome's springing")
            continue
        if r.kind == "arch":  # a steel crown: trusses, its covering, and the fins and glazing of its end walls
            add(ROOF_CODES[r.covering], g["area"], "Arch crown: covering of the vault")
            add("STEEL-STRUCT", (g["area"] + g["ends"]) * 45, "Arch crown: steel trusses and fin framing, about 45 kg/m2")
            add("WINDOW-FIXED", g["ends"] * 0.62, "Arch crown: glazing between the fins of its end walls")
            add("GUTTER", g["eaves"], "Along the vault's springing")
            continue
        add(ROOF_CODES[r.covering], g["area"], f"{r.kind.capitalize()} roof covering at {r.pitch:g} deg")
        add("RIDGE", g["ridge"] + g["hips"], "Ridge and hip capping")
        add("GUTTER", g["eaves"], "Along the eaves")
        add("FASCIA", g["eaves"], "Along the eaves")
        span = (r.y1 - r.y0 if r.ridge == "x" else r.x1 - r.x0) + 2 * r.overhang
        rafter = (span if r.kind == "shed" else span / 2) / math.cos(math.radians(r.pitch))
        count = math.ceil(g["eaves"] / sp.rafter_spacing) + 1
        add("ROOF-TIMBER", count * rafter + g["ridge"] + 2 * ((r.x1 - r.x0) + (r.y1 - r.y0)),
            f"Rafters at {sp.rafter_spacing:g} m, ridge board and wall plate (estimate)")
    # finishes and building services: tiling, sanitary fittings and kitchens from the rooms; electrical, plumbing
    # and fire protection by floor area; lifts by the stops they serve
    gfa = sum(area(s.outline) for s in b.slabs if s.level < len(b.levels))
    if b.rooms:
        add("FLOOR-TILES", sum(r.area for r in b.rooms), "Ceramic floor tiles to every room and corridor")
        wet = [r for r in b.rooms if r.name in ("Bathroom", "Shower room", "Toilets", "Sluice room") and r.rect]
        kit = [r for r in b.rooms if r.name in ("Kitchen", "Kitchenette", "Living / kitchen") and r.rect]
        per = lambda r: 2 * ((r.rect[2] - r.rect[0]) + (r.rect[3] - r.rect[1]))  # noqa: E731
        add("WALL-TILES", sum(per(r) * 2.1 for r in wet) + sum(per(r) * 0.6 for r in kit),
            "Wall tiles: wet rooms 2.1 m high, kitchen splashbacks 0.6 m")
        add("SANITARY-SET", sum(1 if r.name in ("Bathroom", "Shower room") else max(1, round(r.area / 4)) for r in wet),
            "WC, basin and shower (bathrooms); a WC and basin per 4 m2 of public toilets")
        add("KITCHEN-UNIT", len(kit), "Kitchen fittings: base and wall units, worktop, sink")
        add("EXTRACT-FAN", sum(1 for r in wet if r.name in ("Bathroom", "Shower room")),
            "Mechanical extract to inner bathrooms, ducted to the roof")
    if b.walls:
        add("ELEC-INSTALL", gfa, "Electrical installation: wiring, lighting, sockets, distribution, by floor area")
        add("PLUMB-INSTALL", gfa, "Internal water and waste pipework, by floor area (fittings and drains itemised)")
        if len(b.levels) > 2:
            add("FIRE-PROTECTION", gfa, "Fire installation wiring, emergency lighting and signage, by floor area")
    lifts = len({r.id for r in b.rooms if "lift" in r.name.lower() and r.level == 0}) or         len({r.id for r in b.rooms if "lift" in r.name.lower() and r.level == 1})
    if lifts:
        add("LIFT-STOP", lifts * len(b.levels), "Passenger lift, supply and install, per floor served")
    # landscaping in the compound (typical rates: a landscape architect sets the species and densities)
    for x in b.landscape:
        if x.kind in LANDSCAPE_AREAS and len(x.points) >= 3:
            A = area(x.points)
            per = sum(math.hypot(x.points[i][0] - x.points[i - 1][0], x.points[i][1] - x.points[i - 1][1])
                      for i in range(len(x.points)))
            if x.kind == "flower_bed":
                add("TOPSOIL", 0.3 * A, "Flower beds: 300 mm of topsoil")
                add("MULCH", 0.05 * A, "Flower beds: 50 mm of mulch")
                add("PLANTS-FLOWER", math.ceil(6 * A), "Flower beds: 6 plants per m2")
                add("BED-EDGING", per, "Edging round the flower and shrub beds")
            elif x.kind == "shrub_bed":
                add("TOPSOIL", 0.3 * A, "Shrub beds: 300 mm of topsoil")
                add("MULCH", 0.05 * A, "Shrub beds: 50 mm of mulch")
                add("SHRUBS", math.ceil(1.5 * A), "Shrub beds: 1.5 shrubs per m2")
                add("BED-EDGING", per, "Edging round the flower and shrub beds")
            elif x.kind == "lawn":
                add("TOPSOIL", 0.15 * A, "Lawns: 150 mm of topsoil")
                add("GRASS", A, "Lawns: grass turf")
            elif x.kind == "parking":
                add("PAVING", A, "Parking: block paving")
                add("ROAD-MARKING", len(parking_bays(x)), "Parking: bay lines and numbers, per bay")
            else:
                add("PAVING", A, "Paving in the compound")
        elif x.kind == "hedge" and len(x.points) >= 2:
            L = sum(math.hypot(x.points[i][0] - x.points[i - 1][0], x.points[i][1] - x.points[i - 1][1])
                    for i in range(1, len(x.points)))
            add("HEDGE", math.ceil(3 * L), "Hedges: 3 plants per metre")
        elif x.kind == "tree":
            add("TREE", len(x.points), "Trees, with a 1 m3 planting pit each")
            add("TREE-PIT", len(x.points), "Planting pits 1 x 1 x 1 m, backfilled with topsoil")
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
def _overlapping_walls(b: Building, add) -> None:
    """Two walls on the same line and level that overlap: one is drawn twice (counted twice in the BOQ)."""
    lines: dict[tuple, list] = {}
    for w in b.walls:
        L = length(w)
        if L < 0.1:
            continue
        ux, uy = (w.b[0] - w.a[0]) / L, (w.b[1] - w.a[1]) / L
        if ux < -1e-9 or (abs(ux) < 1e-9 and uy < 0):
            ux, uy = -ux, -uy
        off = round(-uy * w.a[0] + ux * w.a[1], 2)  # distance of the line from the origin
        key = (w.level, round(ux, 3), round(uy, 3), off)
        s0, s1 = sorted((ux * w.a[0] + uy * w.a[1], ux * w.b[0] + uy * w.b[1]))
        lines.setdefault(key, []).append((s0, s1, w))
    for segs in lines.values():
        segs.sort(key=lambda t: t[0])
        for (a0, a1, w1), (b0, b1, w2) in zip(segs, segs[1:]):
            if min(a1, b1) - b0 > 0.3:
                add("error", "bld_wall_overlap", f"Walls {w1.id} and {w2.id} overlap by {min(a1, b1) - b0:.2f} m "
                                                 f"(a wall drawn twice is counted twice)", w2.id)


def site_checks(st: Site, b: Optional[Building], boq_total: Optional[float] = None, currency: str = "") -> list[dict]:
    """The design against the site survey and the client's brief (st: the project's ProjectInfo.site)."""
    issues, sp = [], (b.spec if b is not None else Spec())

    def add(sev, code, msg, ref=None):
        issues.append({"severity": sev, "code": code, "message": msg, "ref": ref})
    if not st.recorded():
        add("info", "bld_no_ground", "Ground conditions are not recorded yet (Building 3D: Site & brief)")
    if st.soil in ("black cotton", "made ground / fill"):
        add("warning", "bld_soil", f"{st.soil.capitalize()} soil: strip footings are not enough - an engineer "
                                   f"designs the foundations (raft, piles or excavation to firm ground)")
    if b is None or not b.walls:
        return issues
    if st.bearing_capacity and len(b.levels):
        load = 12.0 * len(b.levels)  # rough wall line load per storey, kN/m, for a quick footing check
        need = load / max(sp.footing_width, 0.1)
        if need > st.bearing_capacity:
            add("warning", "bld_bearing", f"Footings {sp.footing_width:g} m wide put about {need:.0f} kN/m² on ground "
                                          f"rated {st.bearing_capacity:g} kN/m²: widen them to "
                                          f"{load / st.bearing_capacity:.2f} m or more (engineer to confirm)")
    if st.water_table and st.water_table < sp.excavation_depth + 0.3:
        add("warning", "bld_water_table", f"Ground water at {st.water_table:g} m is within reach of the "
                                          f"{sp.excavation_depth:g} m excavation: allow for dewatering and tanking")
    if st.slope > 10:
        add("warning", "bld_slope", f"The plot falls {st.slope:g} %: allow for cut and fill or stepped footings")
    if st.budget and boq_total and boq_total > st.budget:
        add("warning", "bld_budget", f"The BOQ estimate ({currency} {boq_total:,.0f}) is over the client's budget "
                                     f"({currency} {st.budget:,.0f}) by {boq_total / st.budget - 1:.0%}")
    have: dict[str, int] = {}
    for r in b.rooms:
        have[r.name.lower()] = have.get(r.name.lower(), 0) + 1
    for want in st.schedule:
        got = have.get(want.name.lower(), 0)
        if want.count and got < want.count:
            add("warning", "bld_brief_rooms", f"The brief asks for {want.count} {want.name}, the design has {got}")
        if want.area:
            small = [r for r in b.rooms if r.name.lower() == want.name.lower() and r.area and r.area < want.area * 0.95]
            if small:
                add("warning", "bld_brief_area", f"{len(small)} {want.name} room(s) are smaller than the "
                                                 f"{want.area:g} m² in the brief", small[0].id)
    return issues


def check(b: Building, boundary: Optional[list[list[float]]] = None) -> list[dict]:
    """Building checks; boundary is the plot on the map ([lat, lon] points) for the setback check."""
    issues = []

    def add(sev, code, msg, ref=None):
        issues.append({"severity": sev, "code": code, "message": msg, "ref": ref})
    ids = {}
    for coll in (b.walls, b.openings, b.slabs, b.roofs, b.stairs, b.columns, b.landscape, b.rooms):
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
    _overlapping_walls(b, add)
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
        most = max(f[3] for f in stair_flights(b, s)[0])
        if most > 16:
            add("warning", "bld_stair_flight", f"Stair {s.id}: a flight of {most} risers (16 at most: add a landing - "
                                               f"a dog-leg stair)", s.id)
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
