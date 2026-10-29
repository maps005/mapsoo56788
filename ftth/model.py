"""Central FTTH design model.

Every deliverable (KML, DXF, pole summary, BOM, BOQ, splicing, report) is
generated from one `Design` document, so a change made once flows everywhere.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

import re

from pydantic import BaseModel, Field, PrivateAttr, field_validator

Status = Literal["existing", "proposed"]
NodeKind = Literal["POP", "ENCLOSURE", "PR_ENCLOSURE", "JB", "PON", "FAT", "SLACK"]
CableKind = Literal["main", "spur", "drop"]

Detail = Optional[str | float | int | bool]


def _check_details(v: dict) -> dict:
    """Sector details (pipe material, voltage, invert level...): short keys, plain values, a sensible amount."""
    if len(v) > 60:
        raise ValueError("at most 60 detail fields per feature")
    for k, x in v.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", k):
            raise ValueError(f"detail name '{k}' must be lower-case letters, digits and _")
        if isinstance(x, str) and len(x) > 300:
            raise ValueError(f"detail '{k}' is longer than 300 characters")
    return {k: x for k, x in v.items() if x not in (None, "")}


NODE_PREFIX = {"POP": "POP", "ENCLOSURE": "SE", "PR_ENCLOSURE": "PR", "JB": "JB", "PON": "PON", "FAT": "FAT",
               "SLACK": "SL"}


class Pole(BaseModel):
    id: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    type: str = "wood"
    height_m: Optional[float] = None
    condition: str = ""
    status: Status = "existing"
    notes: str = ""
    details: dict[str, Detail] = Field(default_factory=dict)  # sector details (fields: ftth.sectors SECTORS[..]["details"])

    _details = field_validator("details")(classmethod(lambda cls, v: _check_details(v)))


class Home(BaseModel):
    id: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    kind: Literal["home", "mdu", "business"] = "home"
    units: int = Field(default=1, ge=0)  # viable homepasses; 0 = not counted (unknown / under construction)
    name: str = ""
    address: str = ""
    fat: Optional[str] = None
    extra_fats: list[str] = Field(default_factory=list)  # further FATs serving a large MDU
    acquired: bool = False
    field_type: Literal["green", "brown", ""] = ""  # green field / brown field
    access_notes: str = ""
    notes: str = ""
    details: dict[str, Detail] = Field(default_factory=dict)

    _details = field_validator("details")(classmethod(lambda cls, v: _check_details(v)))

    @property
    def fats(self) -> list[str]:
        return ([self.fat] if self.fat else []) + [f for f in self.extra_fats if f and f != self.fat]


class Node(BaseModel):
    """Network equipment location: POP, splice enclosure, JB, PON (1st-stage split) or FAT."""
    id: str
    kind: NodeKind
    lat: Optional[float] = None
    lon: Optional[float] = None
    pole: Optional[str] = None
    status: Status = "proposed"
    ports: Optional[int] = None  # customer ports for a FAT; OLT PON ports for a POP
    notes: str = ""
    details: dict[str, Detail] = Field(default_factory=dict)

    _details = field_validator("details")(classmethod(lambda cls, v: _check_details(v)))


class Splitter(BaseModel):
    id: str
    node: str
    stage: Literal[1, 2] = 1
    outputs: int = 8  # 1xN

    @property
    def ratio(self) -> str:
        return f"1x{self.outputs}"


class Vertex(BaseModel):
    lat: float
    lon: float
    pole: Optional[str] = None
    node: Optional[str] = None
    crossing: bool = False  # the span leaving this vertex crosses a road


class Duct(BaseModel):
    """Building-entry or wall route that is not a cable: plastic trunking, PVC conduit."""
    id: str
    kind: Literal["trunking", "conduit"] = "trunking"
    path: list[Vertex] = Field(default_factory=list)
    notes: str = ""


class Cable(BaseModel):
    id: str
    kind: CableKind = "spur"
    cores: int = 12
    from_node: Optional[str] = None
    to_node: Optional[str] = None
    install: Literal["aerial", "underground"] = "aerial"
    status: Status = "proposed"
    path: list[Vertex] = Field(default_factory=list)
    reserved: list[int] = Field(default_factory=list)
    notes: str = ""
    details: dict[str, Detail] = Field(default_factory=dict)

    _details = field_validator("details")(classmethod(lambda cls, v: _check_details(v)))


class End(BaseModel):
    """One side of a fibre connection inside a node."""
    kind: Literal["cable", "splitter_in", "splitter_out", "olt"]
    ref: str  # cable id, splitter id, or POP node id for OLT ports
    n: int = 1  # core number, splitter output port, or OLT PON port


class Connection(BaseModel):
    id: str
    node: str
    a: End
    b: End
    auto: bool = False
    note: str = ""


class Material(BaseModel):
    code: str
    description: str
    unit: str = "ea"
    rate: float = 0.0
    category: str = "General"


class Adjustment(BaseModel):
    """Authorised manual change to a calculated quantity."""
    code: str
    qty: float
    reason: str = ""
    by: str = ""


class Consumable(BaseModel):
    """Material quantity derived from another quantity, e.g. buckle clips per UPB."""
    code: str
    basis: Literal["upb", "tension", "jhook", "pole", "project", "jb", "trunking_route", "primary_splitter"] = "upb"
    ratio: float = 1.0
    rounding: Literal["up", "nearest"] = "up"
    step: float = 1.0  # round to multiples of this (pack size)


class SupportItem(BaseModel):
    """Material fitted to every new support, e.g. luminaires on a lighting column; the code may name the support's
    details ("LUMINAIRE-{lamp_w}W") and the quantity may come from a detail ("lamps")."""
    code: str
    qty_detail: str = ""
    default_qty: float = 1.0
    defaults: dict[str, Detail] = Field(default_factory=dict)


class Rules(BaseModel):
    """Company construction standards used for every quantity calculation.

    Defaults are calibrated against the V Squared "Infinity Densification FY26" project
    (see docs/calibration.md); adjust per company standard in the Materials & rules tab.
    """
    corner_angle_deg: float = 45.0
    jhook_per_straight_cable: int = 1
    tension_per_cable_end: int = 1
    tension_per_cable_corner: int = 2
    max_suspension_poles: int = 3       # anchor (2 tension clamps) after this many J-hook poles in a row; 0 = off
    tension_pole_passing: Literal["jhook", "none", "tension"] = "none"  # straight cable at a pole that has clamps
    upb_tension_per_bracket: int = 4    # 1 UPB per started group of this many tension clamps
    upb_per_equipment: int = 0
    anchor_at_passing_equipment: bool = False  # a cable passing a pole with a closure / FAT is anchored there (2 clamps)
    extension_arm_pole_types: list[str] = Field(default_factory=lambda: ["KPTX"])
    accessories_on_existing_cables: bool = False
    # cable length = round_up(route + extra% + end allowance + sag per point, step) + slack
    cable_extra_pct: float = 10.0
    cable_end_allowance_m: float = 20.0
    sag_per_point_m: float = 0.5
    cable_round_up_m: float = 10.0
    slack_per_cable_end_m: float = 30.0     # at an end vertex that is equipment (closure, FAT, JB...)
    slack_per_passing_node_m: float = 30.0  # at each equipment site the cable passes
    slack_at_passing_fat_cable_kinds: list[str] = Field(default_factory=lambda: ["main"])  # FAT mid-route: slack on
    riser_per_pole_end_m: float = 0.0       # vertical run down to pole-mounted equipment
    conduit_per_mdu_m: float = 0.0
    conduit_per_home_m: float = 0.0
    default_pon_split: int = 8
    default_fat_split: int = 8
    default_fat_ports: int = 24
    # material code mapping (must exist in the catalogue to be priced)
    cable_code: str = "FOC-{cores}C"
    node_codes: dict[str, str] = Field(default_factory=lambda: {
        "ENCLOSURE": "ENC-SPLICE", "PR_ENCLOSURE": "ENC-SPLICE", "JB": "JB", "FAT": "FAT-{ports}P",
        "PON": "ENC-SPLICE"})
    splitter_code: str = "SPL-1X{outputs}"
    jhook_code: str = "J-HOOK"
    tension_code: str = "TENSION-CLAMP"
    upb_code: str = "UPB"
    extension_arm_code: str = "EXT-ARM"
    pole_code: str = "POLE-NEW"
    conduit_code: str = "PVC-CONDUIT"
    trunking_code: str = "TRUNKING"
    duct_extra_pct: float = 10.0          # trunking / conduit = measured + % + allowance, rounded up
    duct_allowance_m: float = 10.0
    duct_round_up_m: float = 10.0
    mdu_fat_radius_m: float = 60.0        # further FATs within this distance may share a large MDU
    crossing_code: str = "ROAD-X"
    # share of a FAT's homepasses that need a port: 1.0 = every homepass (per-premise design); a coverage
    # design (outdoor FATs serving the area around them) counts its take rate
    fat_load_take_rate: float = 1.0
    # a FAT with no splitter of its own may take fibres from the 1x16 of a FAT up its distribution cable
    # (coverage designs share one splitter between neighbouring boxes); splitters in a JB or closure always may
    share_fat_splitters: bool = False
    # Section A of the V Squared BOQ: off by default (the approved Infinity BOQ is materials only)
    implementation_costs: bool = False
    install_aerial_code: str = "INST-AERIAL"      # per metre of new aerial cable
    install_trunking_code: str = "INST-TRUNKING"  # per metre of trunking
    trench_code: str = "CIVIL-TRENCH"             # per metre of underground route
    building_cabling_code: str = "BUILDING-CABLING"  # per MDU building served
    support_items: list[SupportItem] = Field(default_factory=list)
    # sector checks (see ftth.validate): sewer fall, transformer loading, lighting column spacing
    sewer_min_gradient_pct: float = 0.5   # 1 in 200
    admd_kva: float = 1.5                 # after-diversity demand of a customer with no load recorded
    max_column_spacing_m: float = 40.0
    consumables: list[Consumable] = Field(default_factory=lambda: [
        Consumable(code="STEEL-STRAP", basis="upb", ratio=1 / 15, rounding="up"),
        Consumable(code="BUCKLE-CLIP", basis="upb", ratio=2, rounding="nearest", step=10),
        Consumable(code="CABLE-TIES", basis="upb", ratio=1 / 15, rounding="up"),
        Consumable(code="FOC-24C", basis="jb", ratio=20, rounding="up"),          # 20 m 24C tie cable per JB
        Consumable(code="WALL-CLAMP", basis="trunking_route", ratio=2, rounding="up"),
    ])


class Photo(BaseModel):
    id: str = Field(max_length=40)
    file: str  # generated name of the stored file, e.g. 3fa2b1c9d0.jpg
    caption: str = Field(default="", max_length=500)
    feature: Optional[str] = Field(default=None, max_length=100)
    analysis: dict = Field(default_factory=dict)  # Photo AI suggestions (objects, pole labels, issues, summary)

    @field_validator("file")
    @classmethod
    def _stored_name(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{10}\.(jpg|jpeg|png)", v):
            raise ValueError("photo file must be a stored photo name (upload photos through the app)")
        return v


MarkupKind = Literal["line", "polyline", "circle", "arc", "point", "text", "leader", "dimension"]
_POINTS = {"line": (2, 2), "polyline": (2, 500), "circle": (2, 2), "arc": (3, 3), "point": (1, 1), "text": (1, 1),
           "leader": (2, 50), "dimension": (2, 3)}
_DIM_POINTS = {"aligned": 2, "horizontal": 2, "vertical": 2, "radius": 2, "angular": 3}
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


class Markup(BaseModel):
    """Drafting on the drawing (lines, shapes, notes, leaders, dimensions). Not part of the network: it is never
    counted in quantities or checks, only drawn on the LLD / HLD sheets and in the DXF.

    points are [lat, lon]: a line has its two ends, a polyline or leader its vertices (a leader's text sits at its
    last point), a circle its centre and a point on its edge, an arc its start, a point on it and its end, a text
    or point its position. A dimension measures its points: two for aligned / horizontal / vertical, the centre
    and a point on the edge for radius, and arm - vertex - arm for angular."""
    id: str = Field(max_length=40)
    kind: MarkupKind
    points: list[list[float]]
    closed: bool = False                          # polyline: closed shape (rectangles are closed polylines)
    text: str = Field(default="", max_length=300)
    size: float = Field(default=2.0, gt=0, le=50)  # text height, metres on the ground
    colour: str = "#00e5ff"
    layer: str = Field(default="0", min_length=1, max_length=40)  # a drafting layer (Design.cad_layers) or "0"
    fill: str = ""                                 # hatch: closed polyline or circle filled with this colour
    dim: Literal["aligned", "horizontal", "vertical", "radius", "angular"] = "aligned"

    @field_validator("colour")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX.fullmatch(v):
            raise ValueError("colour must be #rrggbb")
        return v

    @field_validator("fill")
    @classmethod
    def _fill(cls, v: str) -> str:
        if v and not _HEX.fullmatch(v):
            raise ValueError("fill must be #rrggbb or empty")
        return v

    @field_validator("points")
    @classmethod
    def _coords(cls, v: list[list[float]]) -> list[list[float]]:
        for p in v:
            if len(p) != 2 or not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180):
                raise ValueError("each markup point must be [lat, lon]")
        return v

    def model_post_init(self, _ctx) -> None:
        lo, hi = _POINTS[self.kind]
        if self.kind == "dimension":
            lo = hi = _DIM_POINTS[self.dim]
        if not lo <= len(self.points) <= hi:
            raise ValueError(f"a {self.kind} markup needs {lo}{'' if lo == hi else f' to {hi}'} point(s)")


class CadLayer(BaseModel):
    """A drafting layer: markups on a hidden layer are not drawn or exported; on a locked one they cannot be
    picked for editing. Written to the DXF as a layer of its own."""
    name: str = Field(min_length=1, max_length=40)
    colour: str = "#00e5ff"
    visible: bool = True
    locked: bool = False

    @field_validator("colour")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX.fullmatch(v):
            raise ValueError("colour must be #rrggbb")
        return v


class ProjectInfo(BaseModel):
    name: str = "New FTTH project"
    area: str = ""
    client: str = ""
    prepared_by: str = ""
    survey_date: str = ""
    currency: str = "KES"
    region: str = ""
    zone: str = ""
    cluster: str = ""
    surveyors: str = ""
    olt_name: str = ""
    olt_ports_available: str = ""
    interception: str = ""
    interception_node: str = ""   # ID of the existing closure / POP the new network starts from
    interception_nodes: list[str] = Field(default_factory=list)  # further interception points (large areas)
    sector: Literal["fibre", "water", "pipelines", "electricity", "lighting", "sanitation"] = "fibre"  # ftth.sectors
    design_style: Literal["per_premise", "coverage"] = "per_premise"  # how Auto-design sizes FATs (see autodesign)
    extend_to: list[list[float]] = Field(default_factory=list)  # [[lat, lon]] backbone must reach (future phases)
    feeder_cores_available: str = ""
    company: str = ""           # shown in the drawing title block
    drawing_no: str = ""
    lead_planner: str = ""
    planned_by: str = ""
    drawn_by: str = ""
    checked_by: str = ""
    approved_by: str = ""
    introduction: str = ""
    findings: str = ""
    proposed_solution: str = ""
    special_requirements: str = ""
    recommendations: str = ""
    boundary: list[list[float]] = Field(default_factory=list)  # [[lat, lon], ...]
    survey_status: Literal["draft", "approved"] = "draft"
    survey_approved_by: str = ""     # set by the server
    survey_approved_at: str = ""
    survey_fingerprint: str = ""
    design_status: Literal["draft", "in_review", "approved"] = "draft"
    sheet_map: Literal["off", "streets", "satellite"] = "off"  # map under the LLD / HLD PDF sheets and in the DXF


class Design(BaseModel):
    info: ProjectInfo = Field(default_factory=ProjectInfo)
    poles: list[Pole] = Field(default_factory=list)
    homes: list[Home] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    splitters: list[Splitter] = Field(default_factory=list)
    cables: list[Cable] = Field(default_factory=list)
    ducts: list[Duct] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    materials: list[Material] = Field(default_factory=list)
    adjustments: list[Adjustment] = Field(default_factory=list)
    rules: Rules = Field(default_factory=Rules)
    photos: list[Photo] = Field(default_factory=list)
    markups: list[Markup] = Field(default_factory=list, max_length=5000)
    cad_layers: list[CadLayer] = Field(default_factory=list, max_length=100)

    def markup_visible(self, m: Markup) -> bool:
        """Drawn and exported: its layer is not hidden ("0" and unknown layers always show)."""
        lay = next((x for x in self.cad_layers if x.name == m.layer), None)
        return lay is None or lay.visible

    # ---- lookups -------------------------------------------------------
    _index: dict = PrivateAttr(default_factory=dict)

    def _find(self, coll: str, key: str, value: str):
        """O(1) lookup by id; the index checks itself, so edits, renames and replacements are always seen."""
        items = getattr(self, coll)
        idx = self._index.get(coll)
        if idx is None or idx[0] is not items or idx[1] != len(items):
            idx = (items, len(items), {})
            for i, x in enumerate(items):
                idx[2].setdefault(getattr(x, key), i)
            self._index[coll] = idx
        i = idx[2].get(value)
        if i is None:
            return None
        if getattr(items[i], key) == value:
            return items[i]
        # an item was replaced or renamed in place: rebuild once and look again
        self._index.pop(coll, None)
        return next((x for x in items if getattr(x, key) == value), None)

    def pole(self, pid: str) -> Optional[Pole]:
        return self._find("poles", "id", pid)

    def node(self, nid: str) -> Optional[Node]:
        return self._find("nodes", "id", nid)

    def cable(self, cid: str) -> Optional[Cable]:
        return self._find("cables", "id", cid)

    def splitter(self, sid: str) -> Optional[Splitter]:
        return self._find("splitters", "id", sid)

    def material(self, code: str) -> Optional[Material]:
        return self._find("materials", "code", code)

    def node_position(self, n: Node) -> tuple[Optional[float], Optional[float]]:
        """A node's own coordinates, or those of the pole it is mounted on."""
        if n.lat is not None and n.lon is not None:
            return n.lat, n.lon
        p = self.pole(n.pole) if n.pole else None
        return (p.lat, p.lon) if p else (None, None)

    def content_hash(self) -> str:
        """Hash of the design data; deliverables stamped with it can be checked for staleness."""
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


def next_id(existing: set[str], prefix: str, width: int = 3) -> str:
    i = 1
    while f"{prefix}{i:0{width}d}" in existing:
        i += 1
    return f"{prefix}{i:0{width}d}"


def all_ids(d: Design) -> set[str]:
    return {x.id for coll in (d.poles, d.homes, d.nodes, d.splitters, d.cables) for x in coll}


# Item descriptions and KES rates (excl. VAT) from the approved V Squared BOQ
# "Infinity Densification (257 HPs) FY26".
# Items without a confirmed rate are left out so the BOQ flags them instead of pricing them at zero.
DEFAULT_MATERIALS = [
    Material(code="FOC-12C", description="ADSS fiber cable, 100m s/s clear span 12 xSM G652D", unit="M", rate=70.0, category="Cable"),
    Material(code="FOC-48C", description="ADSS fiber cable, 100m s/s clear span 48 xSM G652D", unit="M", rate=69.0, category="Cable"),
    Material(code="FOC-24C", description="ADSS fiber cable, 100m s/s clear span 24 xSM G652D", unit="M", rate=56.0, category="Cable"),
    Material(code="FAT-16P", description="FAT 16 Port wall/pole mounted outdoor plastic", unit="PCS", rate=2800.0, category="FAT"),
    Material(code="FAT-24P", description="FAT 24 Port wall/pole mounted outdoor plastic", unit="PCS", rate=3500.0, category="FAT"),
    Material(code="ENC-SPLICE", description="Fiber Termination Box 48c-ADSS", unit="PCS", rate=3300.0, category="Splice Closure"),
    Material(code="JB", description="Junction Box 24P ADSS", unit="PCS", rate=2600.0, category="Junction Box"),
    Material(code="POLE-NEW", description="Pole, Supply & installation Wooden 8m", unit="PCS", rate=5500.0, category="Pole"),
    Material(code="J-HOOK", description="Supply of J - Hooks(Small)", unit="PCS", rate=200.0, category="Pole Accessories"),
    Material(code="J-HOOK-L", description="Supply of J - Hooks(Large)", unit="PCS", rate=300.0, category="Pole Accessories"),
    Material(code="UPB", description="Supply of Universal Pole bracket", unit="PCS", rate=200.0, category="Pole Accessories"),
    Material(code="TENSION-CLAMP", description="Supply of Pole Tension Clamp PA 1500", unit="PCS", rate=250.0, category="Pole Accessories"),
    Material(code="TENSION-CLAMP-2000", description="Supply of Pole Tension Clamp PA 2000", unit="PCS", rate=300.0, category="Pole Accessories"),
    Material(code="STEEL-STRAP", description="Supply of Pole Steel Straps", unit="ROLL", rate=2000.0, category="Pole Accessories"),
    Material(code="BUCKLE-CLIP", description="Supply of Buckle Clips", unit="PCS", rate=14.0, category="Pole Accessories"),
    Material(code="CABLE-TIES", description="Supply of Cable Ties (Large)", unit="PKT", rate=260.0, category="Pole Accessories"),
    Material(code="EXT-ARM", description="Supply of Extension Arms(Medium)", unit="PCS", rate=3500.0, category="Pole Accessories"),
    Material(code="EXT-ARM-L", description="Supply of Extension Arms(Large)", unit="PCS", rate=6500.0, category="Pole Accessories"),
    Material(code="WALL-CLAMP", description="Wall Clamp", unit="PCS", rate=300.0, category="Pole Accessories"),
    Material(code="TRUNKING", description="PlasticTrunking size 38*25mm", unit="M", rate=115.0, category="Duct"),
    Material(code="HDPE-DUCT", description="HDPE Low Friction, Silicon lined  32/26mm", unit="M", rate=45.0, category="Duct"),
    Material(code="SPL-1X16", description="1X16 splitters for closures", unit="PCS", rate=350.0, category="Splitter"),
    Material(code="SPL-1X8", description="1X8 splitters for closures", unit="PCS", rate=172.0, category="Splitter"),
    # Section A implementation costs (V Squared BOQ template)
    Material(code="INST-AERIAL", description="Installation of Aerial Cable", unit="M", rate=22.0, category="Implementation"),
    Material(code="INST-TRUNKING", description="Install PlasticTrunking size 38*25mm", unit="M", rate=55.0, category="Implementation"),
    Material(code="CIVIL-TRENCH", description="Civil Works for Main Route(1.2 Trench)", unit="M", rate=550.0, category="Implementation"),
    Material(code="BUILDING-CABLING", description="Building Cabling", unit="PCS", rate=3000.0, category="Implementation"),
]
