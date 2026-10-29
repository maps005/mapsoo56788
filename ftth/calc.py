"""Quantity calculations: cable lengths, pole summary, BOM and BOQ.

All quantities derive from the design and the company rules in `Design.rules`.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from . import sectors
from .geo import deflection, haversine, valid_coord
from .model import Cable, Design


def _round_up(x: float, step: float) -> float:
    return math.ceil(x / step - 1e-9) * step if step > 0 else x


@dataclass
class CableLength:
    cable: str
    kind: str
    cores: int
    status: str
    route_m: float
    extra_m: float
    end_m: float
    sag_m: float
    riser_m: float
    rounded_m: float
    slack_m: float
    slack_loops: int
    crossings: int

    @property
    def total_m(self) -> float:
        return self.rounded_m + self.slack_m


def route_length(c: Cable) -> float:
    return sum(haversine(a.lat, a.lon, b.lat, b.lon) for a, b in zip(c.path, c.path[1:]))


def _pole_mounted_end(d: Design, c: Cable, idx: int) -> bool:
    v = c.path[idx]
    n = d.node(v.node) if v.node else None
    return bool(n and n.pole)


def cable_length(d: Design, c: Cable) -> CableLength:
    """route + extra% + end allowance + sag per point (+ risers), rounded up; then slack loops at equipment."""
    r = d.rules
    route = route_length(c)
    last = len(c.path) - 1
    # equipment sites along the cable: co-located equipment (within 3 m; slack loops beside a pole within 10 m)
    # is one site
    sites: list[tuple[int, object]] = []
    for i, v in enumerate(c.path):
        n = d.node(v.node) if v.node else None
        if n is None:
            continue
        gap = haversine(c.path[sites[-1][0]].lat, c.path[sites[-1][0]].lon, v.lat, v.lon) if sites else None
        if gap is not None and gap <= (10 if "SLACK" in (n.kind, sites[-1][1].kind) else 3):
            if i == last:  # the cable ends at this site
                sites[-1] = (i, n)
            continue
        sites.append((i, n))
    ends = sum(1 for i, _ in sites if i in (0, last)) if last > 0 else 0
    passing = sum(1 for i, n in sites if 0 < i < last and
                  (n.kind != "FAT" or c.kind in r.slack_at_passing_fat_cable_kinds))
    risers = sum(1 for i in (0, last) if _pole_mounted_end(d, c, i)) if last > 0 else 0
    extra = route * r.cable_extra_pct / 100
    end = r.cable_end_allowance_m if last > 0 else 0
    sag = r.sag_per_point_m * len(c.path)
    riser = risers * r.riser_per_pole_end_m
    loops = ends + passing if r.slack_per_cable_end_m or r.slack_per_passing_node_m else 0
    return CableLength(
        cable=c.id, kind=c.kind, cores=c.cores, status=c.status, route_m=route, extra_m=extra, end_m=end,
        sag_m=sag, riser_m=riser, rounded_m=_round_up(route + extra + end + sag + riser, r.cable_round_up_m),
        slack_m=ends * r.slack_per_cable_end_m + passing * r.slack_per_passing_node_m, slack_loops=loops,
        crossings=sum(1 for v in c.path[:-1] if v.crossing),
    )


def cable_lengths(d: Design, proposed_only: bool = False) -> list[CableLength]:
    return [cable_length(d, c) for c in d.cables
            if len(c.path) >= 2 and (not proposed_only or c.status == "proposed")]


# ---------------------------------------------------------------------------
# Pole summary
# ---------------------------------------------------------------------------
@dataclass
class PoleRow:
    pole: str
    lat: float | None
    lon: float | None
    status: str
    type: str = ""
    cables: list[str] = field(default_factory=list)
    straight: int = 0
    corners: int = 0
    anchors: int = 0
    ends: int = 0
    crossings: int = 0
    jhooks: int = 0
    tension: int = 0
    upb: int = 0
    ext_arms: int = 0
    equipment: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def jb(self) -> int:
        return sum(1 for e in self.equipment if e.startswith("JB:"))

    @property
    def enclosures(self) -> int:
        return sum(1 for e in self.equipment if e.split(":")[0] in ("ENCLOSURE", "PR_ENCLOSURE", "PON"))

    @property
    def fats(self) -> int:
        return sum(1 for e in self.equipment if e.startswith("FAT:"))


def pole_summary(d: Design, include_unused: bool = False) -> list[PoleRow]:
    """Per-pole accessories for the cables being built (existing cables are already installed)."""
    r = d.rules
    node_pole = {n.id: n.pole for n in d.nodes if n.pole}
    eq_poles = {n.pole for n in d.nodes if n.pole and n.kind != "SLACK"}
    rows = {p.id: PoleRow(p.id, p.lat, p.lon, p.status, p.type) for p in d.poles}
    fibre = sectors.fibre_tools(d)

    for c in d.cables:
        if len(c.path) < 2 or (c.status == "existing" and not r.accessories_on_existing_cables):
            continue
        # buried lines: other sectors list them at their manholes / marker posts, with no pole hardware
        aerial = c.install == "aerial"
        if not aerial and fibre:
            continue
        last = len(c.path) - 1
        run = 0  # J-hook poles since the last anchor on this cable
        prev_pid = None
        for i, v in enumerate(c.path):
            pid = v.pole or node_pole.get(v.node or "")
            if not pid or pid not in rows:
                prev_pid = None
                continue
            row = rows[pid]
            if pid == prev_pid:  # the same pole drawn twice in a row counts once
                continue
            prev_pid = pid
            if c.id not in row.cables:
                row.cables.append(c.id)
            if v.crossing:
                row.crossings += 1
            if not aerial:
                continue
            if i in (0, last):
                row.ends += 1
                run = 0
            else:
                a = next((p for p in reversed(c.path[:i]) if haversine(p.lat, p.lon, v.lat, v.lon) > 0.5), None)
                cc = next((p for p in c.path[i + 1:] if haversine(p.lat, p.lon, v.lat, v.lon) > 0.5), None)
                if a is None or cc is None:  # only repeated points on one side: treat as an end
                    row.ends += 1
                    run = 0
                    continue
                b = v
                if r.anchor_at_passing_equipment and pid in eq_poles:  # spliced / looped at the closure or FAT
                    row.anchors += 1
                    run = 0
                elif deflection((a.lat, a.lon), (b.lat, b.lon), (cc.lat, cc.lon)) >= r.corner_angle_deg:
                    row.corners += 1
                    run = 0
                elif r.max_suspension_poles and run >= r.max_suspension_poles:
                    row.anchors += 1
                    run = 0
                else:
                    row.straight += 1
                    run += 1

    for n in d.nodes:
        if n.pole in rows and n.kind != "SLACK" and (n.status == "proposed" or rows[n.pole].cables):
            rows[n.pole].equipment.append(f"{n.kind}:{n.id}")

    squash = lambda t: re.sub(r"[\s_-]+", "", str(t).upper())  # noqa: E731  "KP TX", "KP-TX" and "KPTX" match
    arm_types = {squash(t) for t in r.extension_arm_pole_types}
    for row in rows.values():
        if row.straight and (row.ends or row.corners or row.anchors):
            if r.tension_pole_passing == "tension":
                row.anchors, row.straight = row.anchors + row.straight, 0
            elif r.tension_pole_passing == "none":
                row.straight = 0
        row.jhooks = row.straight * r.jhook_per_straight_cable
        row.tension = row.ends * r.tension_per_cable_end + \
            (row.corners + row.anchors) * r.tension_per_cable_corner
        row.upb = (math.ceil(row.tension / max(r.upb_tension_per_bracket, 1)) if row.tension else 0) + \
            len(row.equipment) * r.upb_per_equipment
        if row.cables and (squash(row.type) in arm_types or any(squash(row.pole).startswith(t) for t in arm_types)):
            row.ext_arms = 1
        if row.corners:
            row.notes.append("Corner")
        if row.anchors:
            row.notes.append("Anchor")
        if row.ends:
            row.notes.append("Dead-end")
        if row.crossings:
            row.notes.append("Road crossing")
        if fibre:
            if row.jb:
                row.notes.append("JB installed")
            if row.enclosures:
                row.notes.append("Splice enclosure")
            if row.fats:
                row.notes.append("FAT installed")
        else:  # the equipment fitted here, in the sector's names
            row.notes += [sectors.kind_label(d, e.split(":")[0]) for e in dict.fromkeys(
                e.split(":")[0] + ":" for e in row.equipment)]
        if row.ext_arms:
            row.notes.append("Extension arm")
        if not row.notes and row.cables and (fibre or row.straight):
            row.notes.append("Straight")
        if row.status == "proposed":
            row.notes.append("New pole" if fibre else f"New {sectors.get(d.info.sector)['support'].lower()}")
        pole = d.pole(row.pole)
        if pole and pole.notes:
            row.notes.append(pole.notes)
    out = [row for row in rows.values()
           if include_unused or row.cables or row.equipment or row.status == "proposed"]
    return sorted(out, key=lambda x: x.pole)


# ---------------------------------------------------------------------------
# BOM / BOQ
# ---------------------------------------------------------------------------
@dataclass
class BomLine:
    code: str
    description: str
    unit: str
    calculated: float
    adjustment: float = 0.0
    rate: float | None = None
    source: str = ""

    @property
    def qty(self) -> float:
        return self.calculated + self.adjustment

    @property
    def total(self) -> float | None:
        return None if self.rate is None else round(self.qty * self.rate, 2)


def _fmt(template: str, **kw) -> str:
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template


def bom(d: Design) -> list[BomLine]:
    r = d.rules
    qty: dict[str, float] = defaultdict(float)
    src: dict[str, str] = {}

    fibre = sectors.fibre_tools(d)

    def add(code: str, n: float, source: str):
        if n and code:  # an empty code: the sector has no such item (no J-hooks on a buried pipe)
            qty[code] += n
            src.setdefault(code, source)

    for cl in cable_lengths(d, proposed_only=True):
        add(_fmt(r.cable_code, cores=cl.cores), cl.total_m, "Cable routes: allowances, rounding and slack")
        add(r.crossing_code, cl.crossings, "Road crossings on cable routes")
    for n in d.nodes:
        if n.status == "proposed" and n.kind in r.node_codes:
            add(_fmt(r.node_codes[n.kind], ports=n.ports or r.default_fat_ports), 1, "Proposed equipment")
    for s in d.splitters if fibre else []:  # always supplied new, also when fitted in an existing closure
        add(_fmt(r.splitter_code, outputs=s.outputs), 1, f"Stage-{s.stage} splitters")
    support = sectors.get(d.info.sector)["support"]
    for p in d.poles:
        if p.status == "proposed":
            add(r.pole_code, 1, f"Proposed {support.lower()}s")
            for it in r.support_items:  # e.g. luminaires on a new lighting column
                n = p.details.get(it.qty_detail, it.default_qty) if it.qty_detail else it.default_qty
                try:
                    n = float(n)
                except (TypeError, ValueError):
                    n = it.default_qty
                add(_fmt(it.code, **{**it.defaults, **p.details}), n, f"Fitted to new {support.lower()}s")
    totals = {"upb": 0, "tension": 0, "jhook": 0, "pole": 0, "project": 1,
              "jb": sum(1 for n in d.nodes if n.kind == "JB" and n.status == "proposed"),
              "trunking_route": sum(1 for x in d.ducts if x.kind == "trunking" and len(x.path) >= 2),
              "primary_splitter": sum(1 for s in d.splitters if s.stage == 1)}
    for row in pole_summary(d):
        add(r.jhook_code, row.jhooks, "Pole summary")
        add(r.tension_code, row.tension, "Pole summary")
        add(r.upb_code, row.upb, "Pole summary")
        add(r.extension_arm_code, row.ext_arms, "Pole summary (transformer poles)")
        totals["upb"] += row.upb
        totals["tension"] += row.tension
        totals["jhook"] += row.jhooks
        totals["pole"] += 1 if row.cables else 0
    for c in r.consumables:
        base = totals[c.basis] * c.ratio
        step = c.step or 1
        n = math.ceil(base / step - 1e-9) * step if c.rounding == "up" else round(base / step) * step
        if totals[c.basis] and n <= 0:  # at least one pack whenever the item is needed
            n = step
        add(c.code, n if totals[c.basis] else 0, f"{c.ratio:g} per {c.basis}")
    conduit = sum(r.conduit_per_mdu_m for h in d.homes if h.kind == "mdu") + \
        sum(r.conduit_per_home_m for h in d.homes if h.kind != "mdu")
    for x in d.ducts:  # trunking / conduit routes drawn on the map
        if len(x.path) >= 2:
            m = sum(haversine(a.lat, a.lon, b.lat, b.lon) for a, b in zip(x.path, x.path[1:]))
            conduit_m = _round_up(m * (1 + r.duct_extra_pct / 100) + r.duct_allowance_m, r.duct_round_up_m)
            add(r.trunking_code if x.kind == "trunking" else r.conduit_code, conduit_m, "Trunking / conduit routes")
    add(r.conduit_code, math.ceil(conduit), "Building entries")
    if r.implementation_costs:  # Section A of the BOQ: labour and civil works
        for cl in cable_lengths(d, proposed_only=True):
            c = d.cable(cl.cable)
            if c and c.install == "underground":
                add(r.trench_code, math.ceil(cl.route_m), "Underground cable routes (trench length)")
            else:
                add(r.install_aerial_code, cl.total_m, "Aerial cable installed")
        add(r.install_trunking_code, qty.get(r.trunking_code, 0), "Trunking installed")
        fats = {n.id for n in d.nodes if n.kind == "FAT"}
        add(r.building_cabling_code, sum(1 for h in d.homes if h.kind == "mdu" and h.units > 0 and h.fat in fats),
            "MDU buildings cabled")

    if d.building is not None:  # construction: quantities measured from the building model
        from . import building
        for code, q, source in building.quantities(d.building):
            add(code, q, source)

    adj: dict[str, float] = defaultdict(float)
    for a in d.adjustments:
        adj[a.code] += a.qty

    lines = []
    for code in list(qty) + [c for c in adj if c not in qty]:
        m = d.material(code)
        lines.append(BomLine(
            code=code, description=m.description if m else f"{code} (not in catalogue)",
            unit=m.unit if m else "ea", calculated=qty.get(code, 0.0), adjustment=adj.get(code, 0.0),
            rate=m.rate if m else None, source=src.get(code, "Manual adjustment")))
    order = {m.code: i for i, m in enumerate(d.materials)}
    return sorted(lines, key=lambda l: (order.get(l.code, 999), l.code))


def boq_total(lines: list[BomLine]) -> float:
    return round(sum(l.total or 0 for l in lines), 2)


# ---------------------------------------------------------------------------
# Home -> FAT assignment
# ---------------------------------------------------------------------------
def _cap(d: Design, fid: str) -> int:
    n = d.node(fid)
    return (n.ports if n and n.ports else d.rules.default_fat_ports)


def fat_load(d: Design) -> dict[str, int]:
    """Homepasses per FAT; a large MDU served by several FATs fills them in order."""
    load: dict[str, int] = defaultdict(int)
    for h in d.homes:
        fats = h.fats
        if not fats:
            continue
        left = h.units
        for i, f in enumerate(fats):
            take = left if i == len(fats) - 1 else min(left, max(_cap(d, f) - load[f], 0))
            load[f] += take
            left -= take
    return load


def assign_homes(d: Design, max_drop_m: float = 250.0, only_unassigned: bool = True) -> dict:
    """Greedy nearest-FAT assignment respecting FAT port capacity and maximum drop length."""
    fats = []
    for n in d.nodes:  # equipment mounted on a pole may only carry the pole's position
        if n.kind != "FAT":
            continue
        lat, lon = d.node_position(n)
        if valid_coord(lat, lon):
            fats.append(n.model_copy(update={"lat": lat, "lon": lon}))
    if not only_unassigned:
        for h in d.homes:
            h.fat, h.extra_fats = None, []
    skip = {h.id for h in d.homes if h.units == 0}  # no homepasses: nothing to serve (yet)
    load = fat_load(d)
    cap = {f.id: f.ports or d.rules.default_fat_ports for f in fats}
    pairs = []
    for h in d.homes:
        if h.fat or h.id in skip or not valid_coord(h.lat, h.lon):
            continue
        for f in fats:
            dist = haversine(h.lat, h.lon, f.lat, f.lon)
            if dist <= max_drop_m:
                pairs.append((dist, h, f))
    assigned, done = 0, set()
    # small premises first (they fit anywhere), then large MDUs, each taking the nearest free capacity
    for dist, h, f in sorted(pairs, key=lambda p: (p[1].units > 8, p[0])):
        if h.id in done:
            continue
        need = h.units
        if load[f.id] + need <= cap[f.id]:
            h.fat = f.id
            load[f.id] += need
            done.add(h.id)
            assigned += 1
    # large MDUs that no single FAT can take: share FATs close to the building
    for h in d.homes:
        if h.fat or h.id in done or h.id in skip or not valid_coord(h.lat, h.lon):
            continue
        near = sorted((haversine(h.lat, h.lon, f.lat, f.lon), f) for f in fats
                      if haversine(h.lat, h.lon, f.lat, f.lon) <= d.rules.mdu_fat_radius_m and load[f.id] < cap[f.id])
        free = sum(cap[f.id] - load[f.id] for _, f in near)
        if near and free >= h.units:
            left, chosen = h.units, []
            for _, f in near:
                take = min(left, cap[f.id] - load[f.id])
                load[f.id] += take
                left -= take
                chosen.append(f.id)
                if left <= 0:
                    break
            h.fat, h.extra_fats = chosen[0], chosen[1:]
            done.add(h.id)
            assigned += 1
    unassigned = [h.id for h in d.homes if not h.fat and h.id not in skip]
    return {"assigned": assigned, "unassigned": unassigned, "no_homepasses": sorted(skip)}


def summary(d: Design) -> dict:
    lengths = cable_lengths(d, proposed_only=True)
    by_kind: dict[str, float] = defaultdict(float)
    for cl in lengths:
        by_kind[f"{cl.kind} {cl.cores}C"] += cl.total_m
    lines = bom(d)
    return {
        "poles": len(d.poles), "poles_new": sum(p.status == "proposed" for p in d.poles),
        "homes": len(d.homes), "homepasses": sum(h.units for h in d.homes),
        "homes_unassigned": sum(1 for h in d.homes if not h.fat),
        "nodes": {k: sum(n.kind == k for n in d.nodes) for k in ("POP", "ENCLOSURE", "PR_ENCLOSURE", "JB", "PON", "FAT")},
        "cable_m": {k: round(v, 1) for k, v in sorted(by_kind.items())},
        "boq_total": boq_total(lines), "currency": d.info.currency,
        "fat_load": dict(fat_load(d)),
    }
