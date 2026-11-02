"""Building services of a construction project, laid out from the model: foul drainage (stacks from the wet rooms,
inspection chambers, the run to the public sewer), stormwater (roof outlets, downpipes, a soakaway), water
(meter, underground storage, booster pumps, roof tanks) and fire safety (hose reels, extinguishers, alarm,
emergency lighting, escape routes and travel distances). The services engineer details them; these layouts set
the routes, sizes and quantities for the drawings and the BOQ."""
from __future__ import annotations

import math

from . import building as B, compliance
from .model import Design

WATER_L_PER_PERSON = 150          # litres a day (domestic)
STORAGE_DAYS = 2.0                # underground storage, days of demand (Nairobi supply is intermittent)
CLEAR_OF_FOUNDATIONS = 5.0        # m: soakaways and buried tanks from the building's foundations
MAX_TRAVEL_ONE_WAY, MAX_TRAVEL_TWO_WAY = 18.0, 45.0  # m, to a protected stair (BS 9991-style limits)
DRY_RISER_HEIGHT = 18.0   # m: a top floor higher than this needs a dry riser in each stair (BS 9991 / Kenya fire officer)
FIRE_RESERVE = 20.0       # m3 kept in the underground tank for the hose reels and the brigade's first attack


def _cluster(points, gap=3.0):
    """Points closer than `gap` along x merged into one (their average)."""
    out = []
    for p in sorted(points):
        if out and abs(p[0] - out[-1][-1][0]) < gap:
            out[-1].append(p)
        else:
            out.append([p])
    return [(sum(q[0] for q in c) / len(c), sum(q[1] for q in c) / len(c)) for c in out]


def layout(d: Design) -> dict:
    b = d.building
    if not b or not b.walls:
        return {}
    fp = B.footprint(b)
    x0, y0, x1, y1 = B._bbox(fp)
    plot = compliance.plot_local(d)
    px0, py0, px1, py1 = B._bbox(plot) if plot else (x0 - 6, y0 - 6, x1 + 6, y1 + 6)
    off = 1.5  # chambers stand 1.5 m out from the walls
    # foul drainage: a stack at each wet room of the first upper floor (or the ground), down to a chamber outside
    lv = 1 if len(b.levels) > 1 else 0
    wet = [r for r in b.rooms if r.level == lv and r.rect and r.name in ("Bathroom", "Shower room", "Toilets",
                                                                          "Kitchen", "Living / kitchen", "Sluice room")]
    stacks = [((r.rect[0] + r.rect[2]) / 2, (r.rect[1] + r.rect[3]) / 2) for r in wet]
    south = _cluster([(x, y0 - off) for x, y in stacks if y < (y0 + y1) / 2])
    north = _cluster([(x, y1 + off) for x, y in stacks if y >= (y0 + y1) / 2])
    gate_x = min(max((x0 + x1) / 2, px0 + 2), px1 - 2)
    final = (x1 + off, y0 - off)  # the last chamber, at the front corner nearest the driveway side
    sewer = []  # the drain runs: (from, to, purpose)
    if north:
        run = sorted(north) + [(x1 + off, y1 + off), (x1 + off, y0 - off)]
        sewer += [(a, c, "foul") for a, c in zip(run, run[1:])]
    if south:
        run = sorted(south) + [final]
        sewer += [(a, c, "foul") for a, c in zip(run, run[1:])]
    connection = (final[0], py0)  # to the public sewer in the road
    sewer.append((final, connection, "foul"))
    chambers = south + north + [(x1 + off, y1 + off), final]
    # stormwater: downpipes at the roof outlets (the roof plan's), a drain round the building to a soakaway
    outlets = []
    for r in b.roofs:
        if r.kind == "flat":
            n = max(2, math.ceil((r.x1 - r.x0) / 20) * 2) // 2
            outlets += [(r.x0 + 0.6 + (r.x1 - r.x0 - 1.2) * i / max(1, n - 1), yy) for i in range(n) for yy in (r.y0, r.y1)]
        else:
            outlets += [(r.x0, r.y0), (r.x1, r.y0), (r.x0, r.y1), (r.x1, r.y1)]
    # the underground tank and the soakaway 5 m or more clear of the foundations and 1.5 m in from the boundary:
    # in open ground where there is room, else under the paving with a trafficable cover
    gaps = {"rear": py1 - y1, "front": y0 - py0, "west": x0 - px0, "east": px1 - x1}
    paved = [B._bbox(x.points) for x in b.landscape if x.kind in ("paving", "parking") and len(x.points) >= 3]
    grid = [(px0 + 0.5 * i, py0 + 0.5 * j) for i in range(int((px1 - px0) * 2) + 1) for j in range(int((py1 - py0) * 2) + 1)]

    def in_plot(p, margin):  # inside the plot itself (it need not be square to the building), clear of its edges
        if not plot:
            return px0 + margin <= p[0] <= px1 - margin and py0 + margin <= p[1] <= py1 - margin
        inside_, j = False, len(plot) - 1
        for i in range(len(plot)):
            (xi, yi), (xj, yj) = plot[i], plot[j]
            if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
                inside_ = not inside_
            j = i
        return inside_ and min(B._seg_dist(p, plot[i], plot[(i + 1) % len(plot)]) for i in range(len(plot))) >= margin

    def clear(p, size=1.5):
        gap = max(x0 - p[0], p[0] - x1, y0 - p[1], p[1] - y1)  # from the building's outline
        return gap >= CLEAR_OF_FOUNDATIONS + size and in_plot(p, 1.5 + size)

    def on_paving(p):
        return any(r[0] - 0.5 <= p[0] <= r[2] + 0.5 and r[1] - 0.5 <= p[1] <= r[3] + 0.5 for r in paved)
    mid = ((x0 + x1) / 2, (y0 + y1) / 2)
    near = lambda p: math.hypot(p[0] - mid[0], p[1] - mid[1])  # noqa: E731
    tank_spots = [p for p in grid if clear(p, 2.0)]
    tank_at = min(tank_spots, key=near) if tank_spots else \
        ((x0 + 3.0, py0 + 2.0) if y0 - py0 >= 5 else ((x0 + x1) / 2 + 6, y1 + (py1 - y1) / 2))
    spots = [p for p in grid if clear(p) and math.hypot(p[0] - tank_at[0], p[1] - tank_at[1]) >= 6]
    soak_open = [p for p in spots if not on_paving(p)]
    if soak_open or spots:  # open ground first, then under the paving (trafficable cover)
        soakaway = min(soak_open or spots, key=near)
    elif gaps["rear"] >= 8:
        soakaway = (x0 + (x1 - x0) * 0.3, y1 + gaps["rear"] / 2)
    elif gaps["front"] >= 8:
        soakaway = (x0 + (x1 - x0) * 0.3, y0 - gaps["front"] / 2)
    else:
        side = max(("west", "east"), key=lambda k: gaps[k])
        soakaway = ((x0 - gaps["west"] / 2) if side == "west" else (x1 + gaps["east"] / 2), (y0 + y1) / 2)
    storm_ring = [(x0 - 0.8, y0 - 0.8), (x1 + 0.8, y0 - 0.8), (x1 + 0.8, y1 + 0.8), (x0 - 0.8, y1 + 0.8), (x0 - 0.8, y0 - 0.8)]
    sx, sy = soakaway  # from the nearest side of the ring, straight out to the soakaway (never across the building)
    start = (sx, y1 + 0.8) if sy > y1 else (sx, y0 - 0.8) if sy < y0 else ((x0 - 0.8) if sx < x0 else (x1 + 0.8), sy)
    storm = [(a, c, "storm") for a, c in zip(storm_ring, storm_ring[1:])] + [(start, soakaway, "storm")]
    roof_area = sum((r.x1 - r.x0) * (r.y1 - r.y0) for r in b.roofs)
    # water: the meter at the gate, underground storage for a day, booster pumps, roof tanks for half a day
    flats = len({r.unit for r in b.rooms if r.unit})
    people = d.info.site.occupants or max(4, flats * 4)
    demand = people * WATER_L_PER_PERSON / 1000  # m3 a day
    meter = (gate_x + 3, py0 + 0.5)
    # the underground tank in open ground by the front boundary, clear of the driveway and the drains
    tank = tank_at  # clear of the drains
    reserve = FIRE_RESERVE if len(b.levels) > 2 else 0.0
    water = {"people": people, "demand": round(demand, 1), "underground": math.ceil(demand * STORAGE_DAYS + reserve),
             "fire_reserve": reserve, "roof": math.ceil(demand / 2), "days": STORAGE_DAYS,
             "tank_paved": on_paving(tank), "soak_paved": on_paving(soakaway),
             "meter": meter, "tank": tank, "main": [meter, (meter[0], tank[1]), tank]}
    # fire: per floor, a hose reel and two extinguishers at each stair, an alarm call point at each exit
    stairs = [s for s in b.stairs if s.level == 0] or [s for s in b.stairs]
    floors = len(b.levels)
    # the stair doors on a typical floor: doors into a stair room from inside the building (not the flats' doors)
    lv_t = 1 if floors > 1 else 0
    stair_rooms = [r.rect for r in b.rooms if r.level == lv_t and r.name == "Stair" and r.rect]
    stair_doors = []
    for o in b.openings:
        w = b.wall(o.wall)
        if o.kind != "door" or w is None or w.kind != "internal" or w.level != lv_t:
            continue
        L = B.length(w) or 1
        pt = (w.a[0] + (w.b[0] - w.a[0]) / L * o.offset, w.a[1] + (w.b[1] - w.a[1]) / L * o.offset)
        if any(r[0] - 0.3 <= pt[0] <= r[2] + 0.3 and r[1] - 0.3 <= pt[1] <= r[3] + 0.3 for r in stair_rooms):
            stair_doors.append(pt)
    n_stairs = max(1, len(stair_rooms))
    flat_doors = [r.door for r in b.rooms if r.level == (1 if floors > 1 else 0) and r.name.startswith("Hall") and r.door]
    travel = 0.0
    for fd in flat_doors:  # along the corridor to the nearest stair door
        if stair_doors:
            travel = max(travel, min(abs(fd[0] - sd[0]) + abs(fd[1] - sd[1]) for sd in stair_doors))
    two_way = len(stair_doors) >= 2
    top = b.levels[-1].elevation if b.levels else 0.0
    riser = top > DRY_RISER_HEIGHT
    fire = {"hose_reels": floors * n_stairs, "extinguishers": floors * 2 * n_stairs,
            "call_points": floors * n_stairs, "detectors": max(1, flats) + floors * 2,
            "emergency_lights": floors * max(2, math.ceil((x1 - x0) / 10)), "stair_doors": stair_doors,
            "travel": round(travel, 1), "limit": MAX_TRAVEL_TWO_WAY if two_way else MAX_TRAVEL_ONE_WAY,
            "two_way": two_way, "stairs": n_stairs, "top_floor": round(top, 1),
            "dry_riser": riser, "riser_m": round(n_stairs * (top + 1.5), 1) if riser else 0.0,
            "inlets": n_stairs if riser else 0, "smoke_vents": n_stairs if floors > 2 else 0,
            "lobby_vents": floors * n_stairs if floors > 2 else 0,
            "reserve": FIRE_RESERVE if floors > 2 else 0.0,
            "assembly": ((px0 + x0) / 2 if x0 - px0 > 3 else gate_x - 6, (py0 + y0) / 2)}
    # electricity: after diversity about 5 kVA a flat, lifts 15 kVA each, common areas and pumps
    lifts = len({r.id for r in b.rooms if "lift" in r.name.lower() and r.level == 0})
    kva = round(flats * 5 + lifts * 15 + 10 + (7.5 if floors > 2 else 0))
    power = {"kva": kva, "flats": flats, "lifts": lifts,
             "supply": "Kenya Power transformer / substation on the plot (over 100 kVA)" if kva > 100 else "LV supply from the network",
             "transformer": kva > 100, "transformer_kva": next((t for t in (100, 200, 315, 500, 630, 1000) if t >= kva * 1.15), 1000),
             "generator_kva": round(lifts * 15 + 10 + (7.5 if floors > 2 else 0) + 10) if floors > 2 else 0,
             "meters": flats + 1}
    length = lambda runs: sum(math.hypot(c[0] - a[0], c[1] - a[1]) for a, c, _ in runs)  # noqa: E731
    return {"stacks": stacks, "chambers": chambers, "sewer": sewer, "connection": connection,
            "sewer_m": round(length(sewer), 1), "outlets": outlets, "storm": storm, "storm_m": round(length(storm), 1),
            "soakaway": soakaway, "roof_area": round(roof_area), "water": water, "fire": fire, "floors": floors,
            "power": power,
            "stairs": len(stairs)}


def quantities(d: Design) -> list[tuple[str, float, str]]:
    """Services and external works for the BOQ (beyond the building fabric in building.quantities)."""
    L = layout(d)
    if not L:
        return []
    b, out = d.building, []

    def add(code, q, src):
        if q > 1e-9:
            out.append((code, round(q, 2), src))
    add("MANHOLE", len(L["chambers"]), "Inspection chambers on the foul drainage")
    add("DRAIN-PIPE", L["sewer_m"] + L["storm_m"], "uPVC drains: foul to the sewer, stormwater to the soakaway")
    add("SEWER-CONNECTION", 1, "Connection to the public sewer (Nairobi Water)")
    add("SOAKAWAY", 1, f"Soakaway for {L['roof_area']} m2 of roof")
    add("DOWNPIPE", len(L["outlets"]) * (max(lv.elevation + lv.height for lv in b.levels) + 1), "Rainwater downpipes from each outlet")
    add("WATER-TANK", L["water"]["underground"] + L["water"]["roof"],
        f"Water storage: {L['water']['underground']} m3 underground, {L['water']['roof']} m3 on the roof")
    if len(b.levels) > 2:
        add("BOOSTER-PUMP", 1, "Duty and standby booster pumps to the roof tanks")
        add("HOSE-REEL", L["fire"]["hose_reels"], "Fire hose reels at each stair, every floor")
        add("FIRE-EXTINGUISHER", L["fire"]["extinguishers"], "Two extinguishers at each stair, every floor")
        add("FIRE-ALARM-POINT", L["fire"]["call_points"] + L["fire"]["detectors"], "Alarm call points and smoke detectors")
        add("SMOKE-VENT", L["fire"]["smoke_vents"] + L["fire"]["lobby_vents"],
            f"Automatic smoke vents 1 m2: {L['fire']['smoke_vents']} at the stair heads, {L['fire']['lobby_vents']} in the "
            f"lobby / corridor end windows (one per stair, every floor)")
        if L["fire"]["dry_riser"]:
            add("DRY-RISER", L["fire"]["riser_m"], f"100 mm dry riser in each stair, landing valves every floor "
                                                   f"(top floor {L['fire']['top_floor']:g} m)")
            add("FIRE-INLET", L["fire"]["inlets"], "Fire brigade inlet box at the base of each riser, by the access road")
        add("GENERATOR", 1, f"Standby generator {L['power']['generator_kva']} kVA for lifts, pumps, stairs and fire systems")
    if L["power"]["transformer"]:
        add("TRANSFORMER", 1, f"Kenya Power {L['power']['transformer_kva']} kVA transformer, plinth and switchgear")
    if len(b.levels) > 2:
        add("LIGHTNING", 1, "Lightning protection: air terminals, down conductors, earth pits (BS EN 62305)")
    flat_roof = sum((r.x1 - r.x0) * (r.y1 - r.y0) for r in b.roofs if r.kind == "flat")
    add("WATERPROOFING", flat_roof, "Flat roof waterproofing membrane with screed to falls")
    # external works and substructure sundries
    paved = [B._bbox(x.points) for x in b.landscape if x.kind in ("paving", "parking") and len(x.points) >= 3]
    x0, y0, x1, y1 = B._bbox(B.footprint(b))
    paved_area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in paved)
    add("CHANNEL-DRAIN", paved_area / 8, "Channel drains with gratings across the paving and parking, to the storm drains")
    park = [B._bbox(x.points) for x in b.landscape if x.kind == "parking" and len(x.points) >= 3]
    add("KERB", sum(2 * ((r[2] - r[0]) + (r[3] - r[1])) for r in park + paved) / 2, "Precast kerbs to the paving and parking")
    fpa = (x1 - x0) * (y1 - y0)
    add("ANTI-TERMITE", fpa + 2 * ((x1 - x0) + (y1 - y0)), "Anti-termite treatment under the ground slab and round the walls")
    lifts = L["power"]["lifts"]
    add("LIFT-PIT", lifts, "Lift pit 1.5 m deep, RC, tanked, with ladder")
    add("EXT-LIGHTING", max(4, math.ceil((paved_area + fpa) / 150)), "External lights: bollards and pole lights to the paving and parking")
    add("BIN-STORE", 1, "Refuse store by the gate, roofed, with wash-down point")
    rail = sum(2 * (math.ceil(B.stair_steps(b, s)[0] / s.flights) * s.tread) * s.flights + (2 * s.width if s.flights == 2 else 0)
               for s in b.stairs)
    add("BALUSTRADE", rail, "Stair balustrades and handrails")
    plot = compliance.plot_local(d)
    if plot:
        per = sum(math.hypot(plot[i][0] - plot[i - 1][0], plot[i][1] - plot[i - 1][1]) for i in range(len(plot)))
        add("BOUNDARY-WALL", max(0.0, per - 6), "Boundary wall round the plot, less the gate")
        add("GATE", 1, "Vehicle and pedestrian gate, 6 m")
    return out
