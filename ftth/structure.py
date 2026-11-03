"""Preliminary structural design of a framed building: loads, slab thickness, beam and column sizes, and the
foundations, from the frame in the model (its columns) and the ground's bearing capacity.

It is a scheme design for costing and coordination, by the usual first-pass rules (Eurocode 2 load factors, span /
depth ratios, columns sized for axial load with 2 % steel, pads or a raft from the safe bearing pressure). The
registered (EBK) engineer's design and calculations govern: every output says so.
"""
from __future__ import annotations

import math
from typing import Optional

from . import building as B

CONCRETE, FOUNDATION_CONCRETE = "C30/37", "C25/30"
FCK, FYK, STEEL = 30.0, 500.0, 0.02                  # MPa, MPa, column steel ratio
GAMMA_C, FINISHES, PARTITIONS = 25.0, 1.5, 2.4      # kN/m3, kN/m2, kN/m2 (block partitions, EN 1991-1-1 6.3.1.2)
ROOF_IMPOSED, WALL_LINE = 1.5, 12.0                  # kN/m2 (accessible flat roof), kN/m per storey (200 mm blockwork)
ROOF_DEAD = 4.0          # kN/m2 on a flat roof slab: screed to falls (~125 mm average), waterproofing, tanks and plant
WIND_PRESSURE = 1.0      # kN/m2: the floor on the peak velocity pressure (older code allowance)
VB = 28.0                # m/s basic wind speed, Nairobi (EN 1991-1-4 with the Kenyan wind map; to confirm)
Z0, ZMIN = 0.3, 5.0      # terrain category III (suburban, towns): roughness length and minimum height, m
CF = 1.3                 # force coefficient on the whole building: windward 0.8 + leeward 0.5 (EN 1991-1-4 7.2.2)
# fire resistance (EN 1992-1-2 tabulated data; the period from the height of the top floor, as the 2024 Kenya
# Building Code and UK Approved Document B): minimum sizes and axis distances, mm
FIRE_MIN = {  # minutes: column side / axis (5.2a, mu 0.7), slab h / axis (5.8 two-way), wall t / axis (5.4),
    #           continuous beam b / axis (5.6)
    60: {"column": (300, 40), "slab": (80, 10), "wall": (130, 10), "beam": (200, 12)},
    90: {"column": (350, 40), "slab": (100, 15), "wall": (140, 25), "beam": (250, 25)},
    120: {"column": (350, 57), "slab": (120, 20), "wall": (160, 35), "beam": (300, 35)},
}


def fire_period(b: B.Building) -> int:
    """Minutes of fire resistance the structure needs: by the height of the top floor (R60 up to 18 m, R90 up
    to 30 m, R120 above)."""
    top = max((lv.elevation for lv in b.levels), default=0.0)
    return 60 if top <= 18 else 90 if top <= 30 else 120


def wind_peak(z: float) -> dict:
    """EN 1991-1-4 4.5: the peak velocity pressure qp(z), kN/m2, at height z over terrain category III."""
    z = max(z, ZMIN)
    kr = 0.19 * (Z0 / 0.05) ** 0.07
    cr = kr * math.log(z / Z0)
    vm = cr * VB
    iv = 1 / math.log(z / Z0)
    qp = (1 + 7 * iv) * 0.5 * 1.25 * vm * vm / 1000
    return {"z": z, "kr": kr, "cr": cr, "vm": vm, "iv": iv, "qp": qp, "qb": 0.5 * 1.25 * VB * VB / 1000}
SEISMIC_COEFF = 0.08     # base shear / weight: Nairobi ag about 0.1 g, ductility class medium RC walls (EN 1998)
GAMMA_SOIL = 20.0        # kN/m3: backfill over the foundations
HEADROOM = 2.25          # m clear from the finished floor to a beam soffit (door heads at 2.1 m)
REBAR = {"column": 220, "beam": 180, "slab": 110, "foundation": 90, "wall": 120, "stair": 110}  # kg/m3, scheme rates
IMPOSED = {"Ward": 2.0, "Office": 2.5, "Classroom": 3.0, "Corridor": 3.0}


def _round_up(v: float, step: float) -> float:
    return math.ceil(v / step - 1e-9) * step


def imposed_load(b: B.Building) -> float:
    """Imposed floor load from the rooms (residential 1.5 kN/m2; offices, wards, classrooms more)."""
    loads = [IMPOSED.get(r.name, 1.5) for r in b.rooms if r.name != "Corridor"]
    return max(loads) if loads else 2.0


def design(b: B.Building, bearing: float = 0.0) -> Optional[dict]:
    """The scheme design, or None when the building has no frame (no columns)."""
    if not b.columns or not b.levels:
        return None
    floors = len(b.levels)
    cols0 = [c for c in b.columns if c.level == 0]
    if not cols0:
        return None
    # the frame: each column's neighbours along x and y (columns on a common line)
    def gaps(c, axis):
        same = [d for d in cols0 if d is not c and abs((d.y if axis == "x" else d.x) - (c.y if axis == "x" else c.x)) < 0.3]
        pos = c.x if axis == "x" else c.y
        lo = [pos - (d.x if axis == "x" else d.y) for d in same if (d.x if axis == "x" else d.y) < pos]
        hi = [(d.x if axis == "x" else d.y) - pos for d in same if (d.x if axis == "x" else d.y) > pos]
        return (min(lo) if lo else 0.0), (min(hi) if hi else 0.0)
    spans_x, spans_y, trib, strips = [], [], {}, {}
    for c in cols0:
        lx, hx = gaps(c, "x")
        ly, hy = gaps(c, "y")
        spans_x += [v for v in (lx, hx) if v > 0.5]
        spans_y += [v for v in (ly, hy) if v > 0.5]
        edge = (lx == 0) + (hx == 0) + (ly == 0) + (hy == 0)
        ax_, ay_ = (lx + hx) / 2 + (0.15 if lx == 0 or hx == 0 else 0), (ly + hy) / 2 + (0.15 if ly == 0 or hy == 0 else 0)
        trib[c.id] = ax_ * ay_, edge
        strips[c.id] = (ax_, ay_)  # the lengths of beam along x and y the column carries
    long_x, long_y = max(spans_x, default=4.0), max(spans_y, default=4.0)
    short = min(long_x, long_y)
    two_way = max(long_x, long_y) / short <= 2.0
    slab = max(0.15, _round_up(short / (30 if two_way else 26), 0.025))  # slab panels between the beams
    q = imposed_load(b)
    while slab < 0.4 and not slab_deflection(slab, short, q)["ok"]:  # thicker until it passes EC2 7.4.2
        slab = round(slab + 0.025, 3)
    g = GAMMA_C * slab + FINISHES + PARTITIONS
    w_floor = 1.35 * g + 1.5 * q                     # kN/m2 at the ultimate limit state
    w_roof = 1.35 * (GAMMA_C * slab + ROOF_DEAD) + 1.5 * ROOF_IMPOSED
    sls = (g + q) / w_floor                           # service / ultimate
    sigma = 0.4 * FCK + 0.67 * FYK * STEEL           # MPa: axial capacity of a column section
    heights = [lv.height for lv in b.levels]
    storey = min(heights) - b.levels[0].slab
    fire = FIRE_MIN[fire_period(b)]
    fire_col = fire["column"][0] / 1000
    beam_x, beam_y = _beam(long_x, slab, storey, fire["beam"][0] / 1000), _beam(long_y, slab, storey, fire["beam"][0] / 1000)
    for bm, tw in ((beam_x, short / 2), (beam_y, short)):  # no compression steel: widen until K <= K' (0.167)
        bm["trib"] = tw
        while bm["b"] < 1.2:
            wl = w_floor * tw + 1.35 * GAMMA_C * bm["b"] * (bm["h"] - slab)
            if wl * bm["span"] ** 2 / 10 * 1e6 / (bm["b"] * 1000 * ((bm["h"] - 0.05) * 1000) ** 2 * FCK) <= 0.167:
                break
            bm["b"] = round(bm["b"] + 0.05, 3)
    beam_w = lambda bm: GAMMA_C * bm["b"] * (bm["h"] - slab)  # noqa: E731  kN/m of downstand
    columns, worst = [], 0.0
    for c in cols0:
        A, edge = trib[c.id]
        sx, sy = strips[c.id]
        beams = 1.35 * (beam_w(beam_x) * sx + beam_w(beam_y) * sy)
        facade = 1.35 * WALL_LINE * ((sx if sy < sx else sy) if edge else 0)  # the outside wall an edge column carries
        per_level, own = [], 0.0
        for lv in reversed(range(floors)):  # down the building: roof, each floor, the walls and the columns above
            n_floor = floors - lv - 1
            N = A * (w_roof + w_floor * n_floor) + beams * (n_floor + 1) + facade * (floors - lv) + own
            moment = 1.1 if not edge else 1.25 if edge == 1 else 1.5  # bending allowance: internal, edge, corner
            side = max(0.3, fire_col, _round_up(math.sqrt(N * moment * 1e3 / sigma) / 1e3, 0.025))
            own += 1.35 * GAMMA_C * side * side * heights[lv]
            per_level.append((round(N + 1.35 * GAMMA_C * side * side * heights[lv]), round(side, 3)))
        per_level.reverse()
        worst = max(worst, per_level[0][0])
        columns.append({"id": c.id, "x": c.x, "y": c.y, "trib": round(A, 1), "edge": int(edge),
                        "N_uls": per_level[0][0], "sizes": [s for _, s in per_level]})
    # foundations from the safe bearing pressure (an assumed 150 kN/m2 until the geotechnical report gives it), at
    # the founding depth: the net pressure left for the column load is q less the backfill over the footing
    q_allow = bearing or 150.0
    Df = b.spec.founding_depth
    q_net = q_allow - GAMMA_SOIL * Df
    fp = B.footprint(b)
    foot_area = B.area(fp) if fp else 0.0
    lateral = _lateral(b, g, q, floors, heights, slab, columns, beam_x, beam_y, q_allow, Df)
    on_core = lambda c: any(r[0] <= c["x"] <= r[2] and r[1] <= c["y"] <= r[3] for r in lateral["rafts_rect"])  # noqa: E731
    pads = []
    for c in columns:
        if on_core(c):
            continue  # it stands on its core's raft
        n_sls = c["N_uls"] * sls
        side = max(1.0, _round_up(math.sqrt(n_sls / q_net), 0.1))
        pads.append({"id": c["id"], "side": round(side, 2), "depth": max(0.5, _round_up(side / 4, 0.05)),
                     "N_sls": round(n_sls), "pressure": round(n_sls / side ** 2 + GAMMA_SOIL * Df)})
    by_id = {c["id"]: c for c in columns}
    groups = {p["id"]: {p["id"]} for p in pads}  # pads closer than their half-widths join into one footing
    for i, p1 in enumerate(pads):
        for p2 in pads[i + 1:]:
            c1, c2 = by_id[p1["id"]], by_id[p2["id"]]
            if math.hypot(c1["x"] - c2["x"], c1["y"] - c2["y"]) < (p1["side"] + p2["side"]) / 2 + 0.3:
                grp = groups[p1["id"]] | groups[p2["id"]]
                for m in grp:
                    groups[m] = grp
    combined = []
    for grp in {frozenset(x) for x in groups.values() if len(x) > 1}:
        cs_ = [by_id[i] for i in grp]
        n_sls = sum(p["N_sls"] for p in pads if p["id"] in grp)
        xs_, ys_ = [c["x"] for c in cs_], [c["y"] for c in cs_]
        along = (max(ys_) - min(ys_)) >= (max(xs_) - min(xs_))
        L = (max(ys_) - min(ys_) if along else max(xs_) - min(xs_)) + max(p["side"] for p in pads if p["id"] in grp)
        Bw = max(1.2, _round_up(n_sls / q_net / L, 0.1))
        combined.append({"ids": sorted(grp), "L": round(L, 2), "B": Bw, "depth": max(0.6, _round_up(max(Bw, L / 3) / 4, 0.05)),
                         "N_sls": round(n_sls), "along": "y" if along else "x",
                         "pressure": round(n_sls / (L * Bw) + GAMMA_SOIL * Df),
                         "x": sum(xs_) / len(xs_), "y": sum(ys_) / len(ys_)})
    joined = {i for c in combined for i in c["ids"]}
    pads = [p for p in pads if p["id"] not in joined]
    pad_area = sum(p["side"] ** 2 for p in pads) + sum(c["L"] * c["B"] for c in combined)
    total_sls = sum(c["N_uls"] for c in columns) * sls + lateral["core_weight"]
    cores_fail = any(not r["ok"] for r in lateral["rafts"])
    if foot_area and (cores_fail or pad_area > 0.5 * foot_area or max([p["side"] for p in pads] + [0]) > 0.8 * short):
        # one raft under the whole building: the cores' overturning spread over its length (the frame's weight
        # holds the cores down), checked with no tension each way
        x0, y0, x1, y1 = B._bbox(fp)
        raft_t = max(0.45, _round_up(max(long_x, long_y) / 10 + 0.05 * floors / 2, 0.05))
        Nt = total_sls + GAMMA_C * raft_t * foot_area
        n_c = max(1, lateral["cores"])
        Mx_, My_ = lateral.get("M_x", 0) * n_c / 1.5, lateral.get("M_y", 0) * n_c / 1.5
        pressure = max(_edge_pressure(Nt, Mx_, x1 - x0, y1 - y0), _edge_pressure(Nt, My_, y1 - y0, x1 - x0)) \
            + GAMMA_SOIL * max(0.0, Df - raft_t)
        found = {"type": "raft", "thickness": raft_t, "pressure": round(pressure), "piles": pressure > q_allow,
                 "average": round(Nt / foot_area), "why": "core overturning" if cores_fail else "pads too large"}
        lateral["rafts"], lateral["rafts_rect"] = [], []  # the cores stand on the raft
    else:
        found = {"type": "pads", "pads": pads, "combined": combined}
    found["depth"] = Df
    found["cores"] = lateral["rafts"]
    # quantities
    col_vol = sum(sum(s * s * heights[i] for i, s in enumerate(c["sizes"])) for c in columns)
    lines_x = len({round(c["y"], 1) for c in columns})
    lines_y = len({round(c["x"], 1) for c in columns})
    xs, ys = [c["x"] for c in columns], [c["y"] for c in columns]
    run_x, run_y = (max(xs) - min(xs)) * lines_x, (max(ys) - min(ys)) * lines_y
    beam_vol = floors * (run_x * beam_x["b"] * (beam_x["h"] - slab) + run_y * beam_y["b"] * (beam_y["h"] - slab))
    if found["type"] == "raft":
        found_vol = foot_area * found["thickness"]
    else:
        found_vol = sum(p["side"] ** 2 * p["depth"] for p in pads) + sum(c["L"] * c["B"] * c["depth"] for c in combined)
        found_vol += sum(r["L"] * r["B"] * r["t"] for r in lateral["rafts"])
    return {"concrete": CONCRETE, "steel": f"B{FYK:.0f}", "imposed": q, "w_floor": round(w_floor, 2),
            "two_way": two_way, "lateral": lateral, "foundation_concrete": FOUNDATION_CONCRETE,
            "rebar": _reinforcement(slab, short, w_floor, beam_x, beam_y, long_x, long_y, columns, found, q_net),
            "headroom": round(storey - 0.05 - max(beam_x["h"], beam_y["h"]) + slab, 2),
            "stair": stair_design(b),
            "w_roof": round(w_roof, 2), "slab": slab, "spans": (round(long_x, 2), round(long_y, 2)),
            "beam_x": beam_x, "beam_y": beam_y, "columns": columns, "worst_N": worst, "bearing": q_allow,
            "bearing_assumed": not bearing, "foundation": found,
            "volumes": {"column": round(col_vol, 1), "beam": round(beam_vol, 1), "foundation": round(found_vol, 1),
                        "wall": lateral["core_volume"]},
            "note": "Preliminary sizes for costing and coordination: the registered structural engineer's design, "
                    "drawings and calculations govern."}


STAIR_IMPOSED = 3.0  # kN/m2, escape stairs (EN 1991-1-1 category C3)


def stair_design(b: B.Building) -> Optional[dict]:
    """The waist slab of the stairs, simply supported between the floor and the half landing (or the next floor):
    the thinnest waist (in 25 mm steps from 150) that carries the bending without compression steel and passes
    EC2 7.4.2, and its bars."""
    st = next((s for s in b.stairs if s.level == 0), None) or (b.stairs[0] if b.stairs else None)
    if not st:
        return None
    n, rise, _ = B.stair_steps(b, st)
    per = math.ceil(n / max(1, st.flights))
    run = per * st.tread
    span = run + (1.0 if st.flights == 2 else 0.3)  # the going and the landing it bears on
    cos = run / math.hypot(run, per * rise)
    t = 0.15
    while True:
        gk = GAMMA_C * (t / cos + rise / 2) + FINISHES
        w = 1.35 * gk + 1.5 * STAIR_IMPOSED
        M = w * span ** 2 / 8
        d = (t - 0.025 - 0.006) * 1000
        K = M * 1e6 / (1000 * d * d * FCK)
        z = min(0.95, 0.5 + math.sqrt(max(0.0, 0.25 - K / 1.134))) * d
        As = max(M * 1e6 / (0.87 * FYK * z), 0.0013 * 1e6 * t)
        lim = span_depth_limit(As / (1000 * d), 1.0)
        if (K <= 0.167 and span * 1000 / d <= lim) or t >= 0.4:
            break
        t = round(t + 0.025, 3)
    main = _bars(As, (12, 16))
    return {"waist": t, "span": round(span, 2), "risers": n, "rise": rise, "going": st.tread, "flights": st.flights,
            "cos": cos, "gk": gk, "w": w, "M": M, "d": d, "K": K, "As": As, "ld": span * 1000 / d, "limit": lim,
            "main": main, "dist": _bars(max(0.2 * As, 0.0013 * 1e6 * t * 0.5), (10, 12))}


def span_depth_limit(rho: float, K: float = 1.3) -> float:
    """EN 1992-1-1 expression 7.16: the basic span / effective depth for a tension steel ratio rho (no
    compression steel), K by the span's support (1.0 simply supported, 1.3 end span, 1.5 interior)."""
    rho0 = math.sqrt(FCK) / 1000
    rho = max(rho, 1e-5)
    if rho <= rho0:
        lim = K * (11 + 1.5 * math.sqrt(FCK) * rho0 / rho + 3.2 * math.sqrt(FCK) * (rho0 / rho - 1) ** 1.5)
    else:
        lim = K * (11 + 1.5 * math.sqrt(FCK) * rho0 / rho)
    return min(lim, 40 * K)


def slab_deflection(h: float, span: float, q: float) -> dict:
    """EN 1992-1-1 7.4.2: the span / effective depth of a slab h thick spanning `span` against the limit of
    expression 7.16 (K = 1.3, an end span of a continuous slab), with the steel its bending needs."""
    fyd = 0.87 * FYK
    d = h - 0.03
    w = 1.35 * (GAMMA_C * h + FINISHES + PARTITIONS) + 1.5 * q
    m = w * span ** 2 / 10
    K = m * 1e6 / (1000 * (d * 1000) ** 2 * FCK)
    z = min(0.95, 0.5 + math.sqrt(max(0.0, 0.25 - K / 1.134))) * d * 1000
    As = max(m * 1e6 / (fyd * z), 0.0013 * 1e6 * h)
    rho0, rho = math.sqrt(FCK) / 1000, As / (1000 * d * 1000)
    Kd = 1.3
    if rho <= rho0:
        lim = Kd * (11 + 1.5 * math.sqrt(FCK) * rho0 / rho + 3.2 * math.sqrt(FCK) * (rho0 / rho - 1) ** 1.5)
    else:
        lim = Kd * (11 + 1.5 * math.sqrt(FCK) * rho0 / rho)
    lim = min(lim, 40 * Kd)
    return {"ld": span / d, "limit": lim, "rho": rho, "rho0": rho0, "K": Kd, "ok": span / d <= lim}


def _beam(L: float, slab: float, storey: float, b_min: float = 0.0) -> dict:
    """A beam on a frame line: span / 12 deep; where that leaves less than HEADROOM under it (with a 50 mm
    screed), a wider, shallower beam, span / 16 at the least; never narrower than the fire period allows."""
    h = max(0.4, _round_up(L / 12, 0.05))
    b = max(0.3 if L > 4.5 else 0.23, b_min)
    room = math.floor((storey - HEADROOM - 0.05 + slab) / 0.05 + 1e-9) * 0.05
    if h > room:
        h, b = max(room, _round_up(L / 16, 0.05)), max(b_min, 0.45 if L <= 7 else 0.6)
    return {"span": round(L, 2), "b": b, "h": round(h, 3)}


def column_types(dz: dict) -> list[dict]:
    """Columns grouped by size, by level: C1, C2, ... for the schedule."""
    groups: dict[tuple, list] = {}
    for c in dz["columns"]:
        groups.setdefault(tuple(c["sizes"]), []).append(c["id"])
    out = []
    for i, (sizes, ids) in enumerate(sorted(groups.items(), key=lambda t: -t[0][0])):
        out.append({"type": f"C{i + 1}", "count": len(ids), "sizes": list(sizes), "ids": ids})
    return out


def _pieces(b: B.Building, w: B.Wall) -> list[float]:
    """The solid lengths of a wall between its openings (0.6 m and more: shorter piers are not counted)."""
    L = B.length(w)
    out, at = [], 0.0
    for a, c in sorted((o.offset - o.width / 2, o.offset + o.width / 2) for o in b.openings if o.wall == w.id):
        if a - at > 0:
            out.append(a - at)
        at = max(at, c)
    if L - at > 0:
        out.append(L - at)
    return [p for p in out if p >= 0.6]


def _cores(b: B.Building) -> list[list]:
    """The reinforced concrete walls of the ground floor, grouped into cores (walls that meet)."""
    walls = [w for w in b.walls if w.level == 0 and w.material == "concrete"]
    group = {w.id: {w.id} for w in walls}
    near = lambda p, w: B._seg_dist(p, w.a, w.b) < 0.35  # noqa: E731
    for i, w1 in enumerate(walls):
        for w2 in walls[i + 1:]:
            if any(near(p, w2) for p in (w1.a, w1.b)) or any(near(p, w1) for p in (w2.a, w2.b)):
                gr = group[w1.id] | group[w2.id]
                for m in gr:
                    group[m] = gr
    by_id = {w.id: w for w in walls}
    return sorted(([by_id[i] for i in sorted(gr)] for gr in {frozenset(v) for v in group.values()}),
                  key=lambda ws: min(min(w.a[0], w.b[0]) for w in ws))


def _edge_pressure(N: float, M: float, L: float, B: float, lift: bool = True) -> float:
    """The greatest ground pressure under a footing L long (in the direction of M) and B wide, with no tension:
    the trapezium while the eccentricity is within L/6, the triangle of a partly lifted footing up to L/3, and
    infinite beyond (it overturns)."""
    e = M / N if N > 0 else math.inf
    if e <= L / 6:
        return N / (L * B) * (1 + 6 * e / L)
    if lift and e < L / 3:  # lift: a partly lifted footing is allowed (not for a core raft)
        return 2 * N / (3 * B * (L / 2 - e))
    return math.inf


def _bar_choice(need: float, sizes=(10, 12, 16, 20, 25)) -> Optional[tuple]:
    """Bars each face (diameter, spacing) giving at least `need` mm2 per metre over both faces, or None."""
    for d in sizes:
        for sp in (200, 150, 125, 100):
            if 2 * math.pi * d * d / 4 * 1000 / sp >= need:
                return d, sp
    return None


def _area_bars(bar: tuple) -> float:
    return 2 * math.pi * bar[0] ** 2 / 4 * 1000 / bar[1]


def _lateral(b, g, q, floors, heights, slab, columns, beam_x, beam_y, q_allow, Df) -> dict:
    """Wind and earthquake carried by the reinforced concrete cores (the stair and lift shafts: the walls in the
    model): the seismic weight of the whole building, base shear and overturning each way shared between the
    cores by their wall length, each core analysed as a box: shear on its walls along the load (horizontal steel,
    EC2 6.2.3 with cot = 1, solid lengths between openings only), bending taken by the walls across it (the
    flanges: vertical steel for the tension, concrete stress for the compression), and a raft under it."""
    fyd = 0.87 * FYK
    fp = B.footprint(b)
    x0, y0, x1, y1 = B._bbox(fp) if fp else (0, 0, 1, 1)
    H = sum(heights)
    area = sum(B.area(s.outline) for s in b.slabs if s.level < len(b.levels))
    cores = _cores(b)
    wall_vol = sum(B.length(w) * b.wall_height(w) * w.thickness for w in b.walls if w.material == "concrete")
    col_vol = sum(sum(s * s * heights[i] for i, s in enumerate(c["sizes"])) for c in columns)
    xs, ys = [c["x"] for c in columns], [c["y"] for c in columns]
    beam_vol = floors * ((max(xs) - min(xs)) * len({round(v, 1) for v in ys}) * beam_x["b"] * (beam_x["h"] - slab)
                         + (max(ys) - min(ys)) * len({round(v, 1) for v in xs}) * beam_y["b"] * (beam_y["h"] - slab))
    facade = sum(B.length(w) for w in b.walls if w.kind == "external" and w.material != "concrete") * WALL_LINE
    # the seismic weight: floors (slab, finishes, partitions, 30 % of the imposed load), frame, cores and facades
    weight = area * (g + 0.3 * q) + GAMMA_C * (wall_vol + col_vol + beam_vol) + facade
    v_seis = SEISMIC_COEFF * weight
    wq = wind_peak(H)  # the peak pressure at the top, over the whole height (conservative), times the force coefficient
    wp = max(WIND_PRESSURE, CF * wq["qp"])
    wind_x, wind_y = wp * (y1 - y0) * H, wp * (x1 - x0) * H
    out = {"cores": len(cores), "weight": round(weight), "height": round(H, 1), "seismic": round(v_seis),
           "wind_x": round(wind_x), "wind_y": round(wind_y), "coeff": SEISMIC_COEFF, "wind_kpa": round(wp, 2), "qp": round(wq["qp"], 2), "cf": CF,
           "core_volume": round(wall_vol, 1), "rafts": [], "rafts_rect": [], "core_weight": 0.0}
    info = []
    for ws in cores:  # each core's walls along x and y (solid lengths) and the gravity load on it
        px = [(p, w.thickness) for w in ws if abs(w.b[0] - w.a[0]) >= abs(w.b[1] - w.a[1]) for p in _pieces(b, w)]
        py = [(p, w.thickness) for w in ws if abs(w.b[0] - w.a[0]) < abs(w.b[1] - w.a[1]) for p in _pieces(b, w)]
        box = (min(min(w.a[0], w.b[0]) for w in ws), min(min(w.a[1], w.b[1]) for w in ws),
               max(max(w.a[0], w.b[0]) for w in ws), max(max(w.a[1], w.b[1]) for w in ws))
        N = GAMMA_C * sum(B.length(w) * w.thickness for w in ws) * H + \
            floors * (g + 0.3 * q) * (box[2] - box[0]) * (box[3] - box[1]) * 0.5  # walls, and half the floor in the box
        info.append({"x": px, "y": py, "box": box, "N": N})
    out["walls_x"] = round(sum(p for c in info for p, _ in c["x"]), 1)
    out["walls_y"] = round(sum(p for c in info for p, _ in c["y"]), 1)
    out["t_x"] = max([t for c in info for _, t in c["x"]] or [0.2])
    out["t_y"] = max([t for c in info for _, t in c["y"]] or [0.2])
    for ax, wind in (("x", wind_x), ("y", wind_y)):
        V = max(v_seis, wind)
        arm = 2 * H / 3 if v_seis >= wind else H / 2  # inverted triangle (earthquake) or uniform (wind)
        out[f"governs_{ax}"] = "earthquake" if v_seis >= wind else "wind"
        out[f"V_{ax}"] = round(V)
        webs = sum(p for c in info for p, _ in c[ax])
        out[f"use_{ax}"], out[f"h_bars_{ax}"], out[f"v_bars_{ax}"], out[f"M_{ax}"] = None, "", "", 0
        if not webs:
            continue
        worst, hb, vb, stress_w = -1.0, None, None, 0.0
        for c in info:
            lw = sum(p for p, _ in c[ax])
            if not lw:
                continue
            t = max(t for _, t in c[ax])
            # accidental torsion (EN 1998-1 4.3.3.2.4): 1 + 0.6 x / Le for a core x from the middle
            xs_c = [(cc["box"][0] + cc["box"][2]) / 2 if ax == "y" else (cc["box"][1] + cc["box"][3]) / 2 for cc in info]
            mid_c, Le = (min(xs_c) + max(xs_c)) / 2, max(1.0, max(xs_c) - min(xs_c))
            pos = (c["box"][0] + c["box"][2]) / 2 if ax == "y" else (c["box"][1] + c["box"][3]) / 2
            tors = 1 + 0.6 * abs(pos - mid_c) / Le if len(info) > 1 else 1.3
            Vc = V * lw / webs * tors
            Mc = Vc * arm
            out[f"M_{ax}"] = max(out[f"M_{ax}"], round(Mc))
            need_h = Vc * 1e3 / (0.8 * lw * 1000 * fyd) * 1000  # mm2 per metre height, both faces
            hb_c = _bar_choice(max(need_h, 0.001 * t * 1e6))
            bx0, by0, bx1, by1 = c["box"]
            length_ = (bx1 - bx0) if ax == "x" else (by1 - by0)
            flange = max(1.0, sum(p for p, _ in c["y" if ax == "x" else "x"]) / 2)  # each end's walls across
            z = 0.9 * max(length_, 1.0)
            T = Mc / z - 0.9 * c["N"] / 2
            need_v = max(0.0, T) * 1e3 / fyd / flange
            vb_c = _bar_choice(max(need_v, 0.002 * t * 1e6))
            stress = (Mc / z + c["N"] / 2) * 1e3 / (t * 1000 * flange * 1000)  # MPa in the compression flange
            use = stress / (0.567 * FCK)
            use = max(use, need_h / _area_bars(hb_c) if hb_c else 9, need_v / _area_bars(vb_c) if vb_c else 9)
            if use > worst:
                worst, hb, vb, stress_w = use, hb_c, vb_c, stress
        out[f"use_{ax}"] = round(worst, 2)
        out[f"stress_{ax}"] = round(stress_w, 1)
        out[f"h_bars_{ax}"] = f"T{hb[0]}@{hb[1]} EF" if hb else "over T25@100"
        out[f"v_bars_{ax}"] = f"T{vb[0]}@{vb[1]} EF" if vb else "over T25@100"
    # a raft under each core: the core's load and its share of the overturning within the safe bearing pressure
    for c in info:
        bx0, by0, bx1, by1 = c["box"]
        N = c["N"] / 1.35
        Mx_, My_ = out["M_x"] / 1.5, out["M_y"] / 1.5  # service: the load factor off
        m = 0.75
        while True:
            L, Bw = (bx1 - bx0) + 2 * m, (by1 - by0) + 2 * m
            t = max(0.8, _round_up(max(beam_x["span"], beam_y["span"]) / 10 + 0.05 * floors / 2, 0.05))  # by the span
            Nt = N + GAMMA_C * L * Bw * t
            p = max(_edge_pressure(Nt, Mx_, L, Bw, False), _edge_pressure(Nt, My_, Bw, L, False)) + GAMMA_SOIL * max(0.0, Df - t)
            if p <= q_allow or m >= 3.0:
                break
            m += 0.25
        out["rafts"].append({"x": round((bx0 + bx1) / 2, 2), "y": round((by0 + by1) / 2, 2), "L": round(L, 2),
                             "B": round(Bw, 2), "t": t, "pressure": round(p) if p < 1e9 else 9999, "ok": p <= q_allow,
                             "rect": [round(bx0 - m, 2), round(by0 - m, 2), round(bx1 + m, 2), round(by1 + m, 2)]})
        out["rafts_rect"].append((bx0 - m, by0 - m, bx1 + m, by1 + m))
        out["core_weight"] += N
    out["core_weight"] = round(out["core_weight"])
    return out


def _bars(As_mm2_per_m: float, sizes=(10, 12, 16)) -> str:
    """Bars and spacing giving at least As (mm2 per metre), spacing a multiple of 25 mm, 300 mm at most."""
    for d in sizes:
        a = math.pi * d * d / 4
        sp = min(300, math.floor(1000 * a / max(As_mm2_per_m, 1) / 25) * 25)
        if sp >= 125:
            return f"T{d}@{sp}"
    return f"T{sizes[-1]}@125"


def _reinforcement(slab, short, w, beam_x, beam_y, long_x, long_y, columns, found, q_allow) -> dict:
    """Scheme reinforcement: slabs and beams from wL2/10 moments, columns at 2 %, pads from the cantilever
    moment, with z = 0.9 d and 0.87 fyk (BS 8110 / EC2 simplified)."""
    fy = 0.87 * FYK
    d = (slab - 0.03) * 1000
    m_slab = w * short ** 2 / 10  # kNm per metre
    As_slab = max(0.0013 * 1000 * slab * 1000, m_slab * 1e6 / (fy * 0.9 * d))
    out = {"slab": f"{_bars(As_slab)} bottom both ways, {_bars(As_slab * 0.8)} top over beams",
           "slab_As": round(As_slab)}
    for key, bm, L in (("beam_x", beam_x, long_x), ("beam_y", beam_y, long_y)):
        wl = w * min(long_x, long_y) + 25 * bm["b"] * (bm["h"] - slab)  # kN/m on the beam
        M = wl * L ** 2 / 10
        dd = (bm["h"] - 0.05) * 1000
        As = M * 1e6 / (fy * 0.9 * dd)
        n16, n20 = math.ceil(As / 201), math.ceil(As / 314)
        main = f"{max(2, n16)}T16" if n16 <= 4 else f"{max(2, n20)}T20"
        out[key] = f"{main} bottom, {main} top over supports (wL2/10 hogging), links T10@{150 if L > 5 else 200}"
    big = max(max(c["sizes"]) for c in columns)
    As_c = STEEL * (big * 1000) ** 2
    n = max(4, math.ceil(As_c / 314 / 2) * 2)
    out["column"] = f"{n}T20 in the {big * 1000:.0f} mm columns (2 %), links T10@200"
    if found["type"] == "pads" and (found.get("pads") or found.get("combined")):
        side = max([p["side"] for p in found.get("pads", [])] + [c["B"] for c in found.get("combined", [])])
        dp = max([p["depth"] for p in found.get("pads", [])] + [c["depth"] for c in found.get("combined", [])])
        M = q_allow * 1.4 * (side / 2 - 0.2) ** 2 / 2  # per metre, ultimate
        As = max(0.0013 * 1000 * dp * 1000, M * 1e6 / (fy * 0.9 * (dp - 0.07) * 1000))
        out["foundation"] = f"{_bars(As, (12, 16, 20))} bottom both ways, 75 mm cover, 50 mm blinding"
    if found.get("cores"):  # the core rafts: spanning between the column lines under their edge pressure
        cr = max(found["cores"], key=lambda c: c["pressure"])
        M = 1.4 * min(cr["pressure"], q_allow) * max(long_x, long_y) ** 2 / 10
        As = max(0.0013 * 1e6 * cr["t"], M * 1e6 / (fy * 0.9 * (cr["t"] - 0.08) * 1000))
        out["core_raft"] = f"{_bars(As, (16, 20, 25))} top and bottom both ways (core rafts {cr['t'] * 1000:.0f} mm)"
    if found["type"] == "raft":
        tr = found["thickness"]  # the raft spans between the column lines under the ground pressure: wL2/10
        M = 1.4 * found.get("average", q_allow) * max(long_x, long_y) ** 2 / 10
        As = max(0.0013 * 1e6 * tr, M * 1e6 / (fy * 0.9 * (tr - 0.08) * 1000))
        out["foundation"] = f"{_bars(As, (16, 20, 25))} top and bottom both ways (raft {tr * 1000:.0f} mm, M = {M:.0f} kNm/m)"
    out.setdefault("foundation", out.get("core_raft", ""))  # every column on a core raft
    return out
