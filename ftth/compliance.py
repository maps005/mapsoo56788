"""Planning and building-code compliance of a construction project: the figures a county planning officer and a
building inspector check, worked out from the model.

- Planning (the plot's limits in ProjectInfo.site): ground coverage, plot ratio, floors, setbacks from the plot
  boundary, car parking per flat.
- Building code (Kenya: Local Government (Adoptive By-laws) Building Order 1968, by-laws 133, 151, 156 and 159, and
  the National Building Code 2024): habitable rooms of 7 m2 or more, one room per flat of 13.9 m2, no side under
  2.13 m, kitchens of 5.6 m2, rooms 2.4 m high, glazing of a tenth of the floor, escape stairs and a lift.

The limits are entered per plot (the county confirms them); the code figures are the by-laws' own.
"""
from __future__ import annotations

import math
from collections import defaultdict

from . import building as B
from .model import Design

HABITABLE = {"Living room", "Living / kitchen", "Bedroom", "Office", "Ward", "Classroom", "Apartment", "Staff room", "Meeting room"}
MIN_HABITABLE, MIN_MAIN_ROOM, MIN_SIDE, MIN_KITCHEN, MIN_HEIGHT, MIN_GLAZING = 7.0, 13.9, 2.13, 5.6, 2.4, 0.10


def plot_local(d: Design) -> list[B.Pt]:
    """The plot boundary in the building's metres (needs the building placed on the map)."""
    b = d.building
    if not b or not b.origin or len(d.info.boundary) < 3:
        return []
    return [list(B.from_latlon(b, la, lo)) for la, lo in d.info.boundary]


def _windows_by_room(b: B.Building) -> dict[str, float]:
    """Glazed area of the outside windows on each room's edges (a window belongs to the room its wall bounds)."""
    out: dict[str, float] = defaultdict(float)
    rooms = [r for r in b.rooms if r.rect]
    for o in b.openings:
        w = b.wall(o.wall)
        if o.kind != "window" or w is None or w.kind != "external":
            continue
        L = B.length(w) or 1
        cx, cy = w.a[0] + (w.b[0] - w.a[0]) / L * o.offset, w.a[1] + (w.b[1] - w.a[1]) / L * o.offset
        for r in rooms:
            x0, y0, x1, y1 = r.rect
            if r.level == w.level and x0 - 0.3 <= cx <= x1 + 0.3 and y0 - 0.3 <= cy <= y1 + 0.3:
                out[r.id] += o.width * o.height
                break
    return out


def figures(d: Design) -> dict:
    """The project's planning figures: plot, footprint, coverage, gross floor area, plot ratio, floors, height,
    flats by type, parking required and provided, and the nearest distance to each side of the plot."""
    b, st = d.building, d.info.site
    if not b or not b.walls:
        return {}
    plot = plot_local(d)
    plot_area = B.area(plot) if plot else 0.0
    ground = [s for s in b.slabs if s.level == 0]
    footprint = sum(B.area(s.outline) for s in ground)
    gfa = sum(B.area(s.outline) for s in b.slabs if s.level < len(b.levels))
    height_roof = max(lv.elevation + lv.height for lv in b.levels)
    height = max(height_roof, B.top_height(b))  # to the parapet / ridge / apex
    units: dict[str, dict] = {}
    for r in b.rooms:
        if r.unit:
            u = units.setdefault(r.unit, {"level": r.level, "area": 0.0, "bedrooms": 0})
            u["area"] += r.area
            u["bedrooms"] += r.name == "Bedroom"
    types: dict[str, list] = defaultdict(list)
    for u in units.values():
        types[f"{u['bedrooms']}-bedroom" if u["bedrooms"] else "Studio"].append(u["area"])
    bays = sum(len(B.parking_bays(x)) for x in b.landscape)
    need = math.ceil(len(units) * st.parking_per_unit) if st.parking_per_unit else 0
    fp = B.footprint(b)
    gaps = {}
    if plot and fp:  # the clear distance from the building to the plot boundary on each side
        x0, y0, x1, y1 = B._bbox(fp)
        px0, py0, px1, py1 = B._bbox(plot)
        gaps = {"front": round(y0 - py0, 2), "rear": round(py1 - y1, 2), "west": round(x0 - px0, 2),
                "east": round(px1 - x1, 2)}
    return {"plot_area": round(plot_area, 1), "footprint": round(footprint, 1), "gfa": round(gfa, 1),
            "coverage": round(100 * footprint / plot_area, 1) if plot_area else None,
            "plot_ratio": round(100 * gfa / plot_area, 1) if plot_area else None,
            "floors": len(b.levels), "height": round(height, 2), "height_roof": round(height_roof, 2), "flats": len(units),
            "flat_types": {k: {"count": len(v), "average": round(sum(v) / len(v), 1), "smallest": round(min(v), 1)}
                           for k, v in sorted(types.items())},
            "parking_required": need, "parking_provided": bays, "setbacks": gaps,
            "lifts": sum("lift" in r.name.lower() for r in b.rooms if r.level == 0) or
                     sum("lift" in r.name.lower() for r in b.rooms if r.level == 1),
            "firefighting_lift": any("firefighting" in r.name.lower() for r in b.rooms),
            "stair_exits": sum(1 for o in b.openings if o.kind == "door" and o.style == "fire" and b.wall(o.wall)
                               and b.wall(o.wall).kind == "external" and b.wall(o.wall).level == 0),
            "stairs": len({s.id[:-1] if s.id.endswith("B") else s.id for s in b.stairs if s.level == 0}) and
                      sum(1 for s in b.stairs if s.level == 0)}


def check(d: Design) -> list[dict]:
    """Planning and building-code issues, in the QA format."""
    b, st = d.building, d.info.site
    out: list[dict] = []
    if not b or not b.walls:
        return out

    def add(sev, code, msg, ref=None):
        out.append({"severity": sev, "code": code, "message": msg, "ref": ref})
    f = figures(d)
    if f["plot_area"]:
        if st.max_coverage and f["coverage"] > st.max_coverage:
            add("error", "plan_coverage", f"Ground coverage {f['coverage']:g} % is over the {st.max_coverage:g} % allowed")
        if st.max_plot_ratio and f["plot_ratio"] > st.max_plot_ratio:
            add("error", "plan_plot_ratio", f"Plot ratio {f['plot_ratio']:g} % is over the {st.max_plot_ratio:g} % allowed")
        for side, need in (("front", st.setback_front), ("rear", st.setback_rear), ("west", st.setback_side),
                           ("east", st.setback_side)):
            got = f["setbacks"].get(side)
            if need and got is not None and got < need - 1e-6:
                add("error", "plan_setback", f"The building is {got:g} m from the {side} boundary "
                                             f"({need:g} m building line)")
    elif d.info.boundary:
        add("info", "plan_not_placed", "Place the building on the site plan to check coverage, plot ratio and setbacks")
    else:
        add("info", "plan_no_plot", "Draw the plot boundary on the site plan to check coverage and plot ratio")
    if st.max_floors and f["floors"] > st.max_floors:
        add("error", "plan_floors", f"{f['floors']} floors: the zone allows {st.max_floors}")
    if f["parking_required"] and f["parking_provided"] < f["parking_required"]:
        add("error", "plan_parking", f"{f['parking_provided']} car spaces for {f['flats']} flats: "
                                     f"{f['parking_required']} required ({st.parking_per_unit:g} per flat)")
    if f["parking_provided"]:  # 2024 Code: accessible bays, EV charging
        acc = max(1, math.ceil(f["parking_provided"] * 0.01))
        f["parking_accessible"], f["parking_ev"] = acc, max(1, math.ceil(f["parking_provided"] * 0.05))
    # building code: rooms, kitchens, heights, light
    glaze = _windows_by_room(b)
    main_room: dict[str, float] = defaultdict(float)
    for r in b.rooms:
        if not r.rect:
            continue
        side = min(r.rect[2] - r.rect[0], r.rect[3] - r.rect[1]) - 0.15
        if r.unit:
            main_room[r.unit] = max(main_room[r.unit], r.area if r.name in HABITABLE else 0)
        if r.name in HABITABLE:
            if r.area < MIN_HABITABLE:
                add("error", "code_room_small", f"{r.name} {r.id} is {r.area:g} m² (by-law 159: 7 m² or more)", r.id)
            if side < MIN_SIDE:
                add("error", "code_room_narrow", f"{r.name} {r.id} is {side:.2f} m wide (by-law 159: 2.13 m or more)", r.id)
            if r.area and glaze.get(r.id, 0) < MIN_GLAZING * r.area:
                add("warning", "code_light", f"{r.name} {r.id}: {glaze.get(r.id, 0):.2f} m² of windows for {r.area:g} m² "
                                             f"(by-law 151: a tenth of the floor, {MIN_GLAZING * r.area:.2f} m²)", r.id)
        if r.name in ("Kitchen", "Kitchenette") and r.unit and r.area < MIN_KITCHEN:
            add("error", "code_kitchen", f"Kitchen {r.id} is {r.area:g} m² (by-law 156: 5.6 m² or more)", r.id)
    for unit, area in main_room.items():
        if area < MIN_MAIN_ROOM:
            add("error", "code_main_room", f"Flat {unit} has no room of 13.9 m² (by-law 159)")
    if b.rooms and any(r.name in ("Bathroom", "Toilets", "Kitchen") and r.unit for r in b.rooms):
        if not any(glaze.get(r.id) for r in b.rooms if r.name == "Bathroom"):
            add("info", "code_ventilation", "Inner bathrooms have no outside window: extract fans ducted to the roof "
                                            "(in the BOQ, ducts marked EXT DUCT on the floor plans)")
    for lv in b.levels:
        if lv.height - lv.slab < MIN_HEIGHT:
            add("error", "code_height", f"{lv.name}: {lv.height - lv.slab:.2f} m clear (2.4 m required)")
    floors = len(b.levels)
    if floors > 4 and f["stairs"] < 2:
        add("error", "code_escape", f"{floors} floors need two escape stairs (Building Code 2024); the design has {f['stairs']}")
    if floors > 4 and not f["lifts"]:
        add("warning", "code_lift", f"{floors} floors and no lift")
    if floors > 6 and not f["firefighting_lift"]:
        add("warning", "code_firefighting_lift", "Above 6 storeys one lift must be a firefighting lift (Building Code 2024, "
                                               "para 364): specify it on the services drawings")
    if floors >= 4 and b.columns:  # the frame braced against wind and earthquake
        from . import structure
        dz = structure.design(b, d.info.site.bearing_capacity)
        lat = dz["lateral"] if dz else None
        if lat and not lat["cores"]:
            add("warning", "code_lateral", f"{floors} floors with no stair or lift cores to brace the frame against wind and earthquake")
        elif lat and max(lat["use_x"] or 0, lat["use_y"] or 0) > 1:
            add("warning", "code_lateral", f"The RC cores are {max(lat['use_x'] or 0, lat['use_y'] or 0):.0%} used against "
                                           f"the {lat['governs_x']} load: lengthen or add shear walls")
        if dz and dz["headroom"] < structure.HEADROOM - 1e-6:
            add("warning", "code_beam_headroom", f"{dz['headroom']:g} m clear under the deepest beam ({structure.HEADROOM:g} m "
                                                 "needed): raise the floor height or use flat slabs")
        if dz and any(not c["ok"] for c in dz["foundation"].get("cores", [])):
            add("warning", "code_core_raft", "A core raft is over the safe bearing pressure: piles or a full raft needed")
    if f["height"] > 30:
        add("warning", "code_sprinklers", f"{f['height']:g} m high: over 30 m needs sprinklers, detection and alarms")
    if floors > 4 and not d.info.site.geotech_report:
        add("warning", "code_geotech", "Over 4 storeys a geotechnical report (boreholes) is required (Building Code "
                                       "2024, para 85): record its reference in Site survey & brief")
    return out
