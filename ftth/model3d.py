"""Measure a building from a 3D model (Wavefront .obj or 3D Studio .3ds) and suggest a brief for the designer.

Only geometry is read (vertices and faces); nothing in the file is executed, and textures, materials and scripts
are ignored. The main building is the largest connected mass above the ground (site clutter, trees and ground
planes are left out). From it: the tightest rectangle round it (size and turn), the height, the storey height
(from the heights that repeat up the facade: sills, window heads, floor bands), the floors, and the roof (sloped
faces covering a real share of the plan: pitched; otherwise flat, with what stands above the top floor as its
parapet). Units are worked out from the sizes, and the planner can override them.
"""
from __future__ import annotations

import math
import struct
from collections import Counter

MAX_VERTICES = 3_000_000


class ModelError(Exception):
    pass


def _read_obj(data: bytes):
    verts, faces = [], []
    for line in data.decode("utf-8", "replace").splitlines():
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                except ValueError:
                    continue
                verts.append((x, y, z))  # as in the file: Y-up or Z-up is decided in measure()
                if len(verts) > MAX_VERTICES:
                    raise ModelError("The model is too detailed (over 3 million points)")
        elif line.startswith("f "):
            idx = []
            for t in line.split()[1:]:
                try:
                    i = int(t.split("/")[0])
                except ValueError:
                    break
                idx.append(i - 1 if i > 0 else len(verts) + i)
            if len(idx) >= 3:
                faces.extend([idx[0], idx[k], idx[k + 1]] for k in range(1, len(idx) - 1))
    return verts, faces


def _read_3ds(data: bytes):
    verts, faces, base = [], [], [0]

    def walk(start, end, depth=0):
        pos = start
        while pos + 6 <= end and depth < 20:
            cid, length = struct.unpack_from("<HI", data, pos)
            if length < 6 or pos + length > end:
                break
            body = pos + 6
            if cid in (0x4D4D, 0x3D3D, 0x4100):  # main, editor, triangle mesh
                walk(body, pos + length, depth + 1)
            elif cid == 0x4000:  # named object
                n = data.find(b"\0", body, pos + length)
                if n >= 0:
                    walk(n + 1, pos + length, depth + 1)
            elif cid == 0x4110:  # vertex list (Z up)
                (cnt,) = struct.unpack_from("<H", data, body)
                if body + 2 + 12 * cnt > pos + length:
                    break
                base[0] = len(verts)
                verts.extend(struct.unpack_from("<3f", data, body + 2 + 12 * k) for k in range(cnt))
                if len(verts) > MAX_VERTICES:
                    raise ModelError("The model is too detailed (over 3 million points)")
            elif cid == 0x4120:  # face list
                (cnt,) = struct.unpack_from("<H", data, body)
                if body + 2 + 8 * cnt > pos + length:
                    break
                for k in range(cnt):
                    a, b, c, _ = struct.unpack_from("<4H", data, body + 2 + 8 * k)
                    faces.append([base[0] + a, base[0] + b, base[0] + c])
            pos += length
    if len(data) < 6 or struct.unpack_from("<H", data, 0)[0] != 0x4D4D:
        raise ModelError("This is not a 3D Studio (.3ds) file")
    walk(0, len(data))
    return verts, faces


def _hull(pts):
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def _area(poly):
    return abs(sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))) / 2


def _min_rect(poly):
    """Width (>= depth), depth and the turn (deg) of the tightest rectangle round a convex polygon."""
    best = None
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i - 1], poly[i]
        a = math.atan2(y2 - y1, x2 - x1)
        c, s = math.cos(-a), math.sin(-a)
        r = [(x * c - y * s, x * s + y * c) for x, y in poly]
        w = max(p[0] for p in r) - min(p[0] for p in r)
        d = max(p[1] for p in r) - min(p[1] for p in r)
        if w > 0 and d > 0 and (best is None or w * d < best[0]):
            best = (w * d, w, d, math.degrees(a) % 180)
    if best is None:
        return 0.0, 0.0, 0.0
    _, w, d, ang = best
    return (w, d, ang) if w >= d else (d, w, (ang + 90) % 180)


def _tri(V, f):
    """Area and |normal z| of a triangle."""
    a, b, c = V[f[0]], V[f[1]], V[f[2]]
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    n = math.sqrt(nx * nx + ny * ny + nz * nz)
    return n / 2, (abs(nz) / n if n else 0.0)


def _normal_xy(V, f):
    """Plan direction of a triangle's normal (not normalised)."""
    a, b, c = V[f[0]], V[f[1]], V[f[2]]
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return uy * vz - uz * vy, uz * vx - ux * vz


def _rect_block(pts_uv, u0, v0, w, d):
    """The rectangle round some points, in the building's frame, kept inside the main block: x, y (its corner from
    the building's corner), width and depth - ready for 'Add as a new block'."""
    if len(pts_uv) < 3:
        return None
    x0 = max(0.0, min(p[0] for p in pts_uv) - u0)
    y0 = max(0.0, min(p[1] for p in pts_uv) - v0)
    x1 = min(w, max(p[0] for p in pts_uv) - u0)
    y1 = min(d, max(p[1] for p in pts_uv) - v0)
    bw, bd = round(x1 - x0, 2), round(y1 - y0, 2)
    if bw < 1 or bd < 1:
        return None
    return {"x": round(x0, 2), "y": round(y0, 2), "width": max(3.0, bw), "depth": max(3.0, bd),
            "rooms_x": max(1, round(bw / 4.5)), "rooms_y": max(1, round(bd / 4.5)), "roof": "flat"}


def _parts_above(V, faces, keep, z_cut, cell=1.0):
    """Separate parts standing above a height (stair towers, plant rooms): their plan points and top, biggest first
    (at most six). Faces are laid on a 1 m plan grid (a plain wall covers the cells along it) and parts within 2 m
    of each other count as one."""
    occ = {}
    for f in faces:
        pts = [V[i] for i in f[:3]]
        if not all(keep[i] for i in f[:3]) or min(p[2] for p in pts) <= z_cut:
            continue
        cx0, cx1 = int(min(p[0] for p in pts) // cell), int(max(p[0] for p in pts) // cell)
        cy0, cy1 = int(min(p[1] for p in pts) // cell), int(max(p[1] for p in pts) // cell)
        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > 2500:
            continue
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                occ.setdefault((cx, cy), []).extend(f[:3])
    seen, parts = set(), []
    for c in occ:
        if c in seen:
            continue
        stack, comp = [c], []
        seen.add(c)
        while stack:
            k = stack.pop()
            comp += occ[k]
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    n = (k[0] + dx, k[1] + dy)
                    if n in occ and n not in seen:
                        seen.add(n)
                        stack.append(n)
        parts.append(([(V[i][0], V[i][1]) for i in comp], max(V[i][2] for i in comp)))
    parts.sort(key=lambda p: -(max(q[0] for q in p[0]) - min(q[0] for q in p[0]))
               * (max(q[1] for q in p[0]) - min(q[1] for q in p[0])))
    return parts[:6]


# common model units first: metres, millimetres, centimetres, inches, then odd scales seen in model libraries
SCALES = [(1.0, "metres"), (0.001, "millimetres"), (0.01, "centimetres"), (0.0254, "inches"), (0.1, "decimetres"),
          (1000.0, "kilometres"), (0.0001, "tenths of a millimetre"), (10.0, "tens of metres"), (100.0, "hectometres")]
# (kilometres leads the odd ones: some converters write metre models in km)
UNIT_NAMES = {name: sc for sc, name in SCALES}


def _core_size(raw):
    """Plan span (5th-95th percentile, so stray site objects do not count) and height."""
    xs = sorted(v[0] for v in raw)
    ys = sorted(v[1] for v in raw)
    k = len(xs)
    span = max(xs[int(k * 0.95)] - xs[int(k * 0.05)], ys[int(k * 0.95)] - ys[int(k * 0.05)])
    return span, max(v[2] for v in raw)


def _choose_scale(raw):
    """The unit that makes a typical building (3-60 m high, 5-150 m across), else any building-sized reading."""
    span, H = _core_size(raw)
    common, odd = SCALES[:4], SCALES[4:]
    for scales, (lo_h, hi_h, lo_s, hi_s) in ((common, (3, 60, 5, 150)), (common, (2.5, 400, 3, 2000)),
                                              (odd, (3, 60, 5, 150)), (odd, (2.5, 400, 3, 2000))):
        for s, name in scales:
            if lo_h <= H * s <= hi_h and lo_s <= span * s <= hi_s:
                return s, name
    raise ModelError("Could not tell the model's units: it is not building-sized at any usual scale")


def _storey(zs, top):
    """Floor-to-floor height from the heights that repeat up the facade (sills, heads, floor bands): the lag, between
    2.6 and 4.6 m, at which the heights of the model's points best match themselves shifted up. None when nothing
    repeats clearly."""
    if top < 5:
        return None
    step = 0.05
    hist = Counter(round(z / step) for z in zs if 0.3 < z < top)
    if not hist:
        return None
    norm = {k: math.sqrt(v) for k, v in hist.items()}  # so one very detailed band does not swamp the rest
    scores = {}
    for lag in range(round(2.6 / step), round(4.6 / step) + 1):
        scores[lag] = sum(v * max(norm.get(k + lag + d, 0) for d in (-1, 0, 1)) for k, v in norm.items())
    mean = sum(scores.values()) / len(scores) or 1
    lag = max(scores, key=lambda q: (scores[q], -q))
    return round(lag * step, 2) if scores[lag] > 1.5 * mean else None


def _main_mass(V, faces, cell=1.0):
    """Points of the largest connected mass above the ground (0.5 m): faces are laid on a 1 m plan grid (a long
    wall covers every cell along it, not just its corners) and touching cells join up."""
    occ = {}
    for f in faces:
        pts = [V[i] for i in f[:3]]
        if max(p[2] for p in pts) <= 0.5:
            continue
        cx0, cx1 = int(min(p[0] for p in pts) // cell), int(max(p[0] for p in pts) // cell)
        cy0, cy1 = int(min(p[1] for p in pts) // cell), int(max(p[1] for p in pts) // cell)
        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > 40000:  # a ground plane or sky dome, not a building part
            continue
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                occ.setdefault((cx, cy), []).extend(f[:3])
    seen, best, best_size = set(), [], 0.0
    for c in occ:
        if c in seen:
            continue
        stack, comp, cells = [c], set(), 0
        seen.add(c)
        while stack:
            k = stack.pop()
            comp.update(occ[k])
            cells += 1
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (k[0] + dx, k[1] + dy)
                    if n in occ and n not in seen:
                        seen.add(n)
                        stack.append(n)
        size = cells * max(V[i][2] for i in comp)  # the biggest mass by bulk, not by how detailed it is
        if size > best_size:
            best, best_size = sorted(comp), size
    return best


def measure(filename: str, data: bytes, unit: str | None = None, up: str | None = None) -> dict:
    """unit: one of UNIT_NAMES (else worked out); up: "y" or "z", the file's up axis (else .3ds is Z-up and an
    .obj is Y-up as the format expects, unless reading it Z-up makes the building clearly lower: exporters differ)."""
    low = filename.lower()
    if low.endswith(".obj"):
        verts, faces = _read_obj(data)
    elif low.endswith(".3ds"):
        verts, faces = _read_3ds(data)
    else:
        raise ModelError("Upload a Wavefront .obj or a 3D Studio .3ds model")
    faces = [f for f in faces if max(f) < len(verts) and min(f) >= 0]
    if len(verts) < 8 or not faces:
        raise ModelError("The file has no 3D geometry")
    if up not in (None, "y", "z"):
        raise ModelError("up must be y or z")
    if up is None:
        up = "z"
        if low.endswith(".obj"):
            ext = [max(v[i] for v in verts) - min(v[i] for v in verts) for i in range(3)]
            up = "z" if ext[2] < 0.85 * ext[1] else "y"  # the OBJ convention, unless Z-up stands clearly lower
    if up == "y":
        verts = [(x, -z, y) for x, y, z in verts]
    z0 = min(v[2] for v in verts)
    x0, y0 = min(v[0] for v in verts), min(v[1] for v in verts)
    raw = [(x - x0, y - y0, z - z0) for x, y, z in verts]
    if unit:
        if unit not in UNIT_NAMES:
            raise ModelError(f"unit must be one of {', '.join(UNIT_NAMES)}")
        s = UNIT_NAMES[unit]
    else:
        s, unit = _choose_scale(raw)
    V = [(x * s, y * s, z * s) for x, y, z in raw]
    mass = _main_mass(V, faces)
    if len(mass) < 8:
        raise ModelError("Could not find a building in the model at this unit")
    keep = [False] * len(V)
    for i in mass:
        keep[i] = True
    hull = _hull([(V[i][0], V[i][1]) for i in mass])
    w, d, turn = _min_rect(hull)
    H = max(V[i][2] for i in mass)
    plan = _area(hull) or w * d
    # roof: sloped faces high up that cover a real share of the plan (not a dome, a mast or a few panels)
    ct, st = math.cos(math.radians(turn)), math.sin(math.radians(turn))
    sloped_area, along_u, rise_lo, flat_at, flat_low = 0.0, 0.0, H, Counter(), Counter()
    for f in faces:
        if not (keep[f[0]] and keep[f[1]] and keep[f[2]]):
            continue
        zs = [V[i][2] for i in f[:3]]
        a, nz = _tri(V, f)
        if nz > 0.97 and min(zs) > 0.3 * H:  # flat areas up high, by height: the main roof is the biggest
            flat_at[round(sum(zs) / 3, 1)] += a
        elif nz > 0.97 and min(zs) > 2.0:  # lower ones: a podium's roof
            flat_low[round(sum(zs) / 3, 1)] += a
        if min(zs) < 0.55 * H:
            continue
        if 0.45 < nz < 0.97:
            sloped_area += a * nz  # the plan area it covers
            rise_lo = min(rise_lo, *zs)
            nx, ny = _normal_xy(V, f)  # which way the slope faces: along the length (hip ends) or across it
            if abs(nx * ct + ny * st) > abs(-nx * st + ny * ct):
                along_u += a * nz
    pitched = sloped_area > 0.35 * plan and H - rise_lo > 0.6
    # a flat roof is at its main roof, not at the top of a stair tower, plant room or mast on it
    main_roof = max(flat_at, key=flat_at.get) if flat_at else H
    eaves = rise_lo if pitched else (main_roof if flat_at[main_roof] > 0.25 * plan else H)
    notes = []
    fh = _storey([V[i][2] for i in mass], eaves)
    if fh is None:
        fh = 3.0
        if eaves > 4.5:
            notes.append("No repeating storey height found in the model: floors estimated at 3 m each - check them.")
    floors = max(1, min(40, int(eaves / fh + 0.35)))
    roof, pitch, parapet = "flat", 0.0, 0.0
    if pitched:
        pitch = min(60.0, round(math.degrees(math.atan((H - rise_lo) / max(d / 2, 0.5))), 1))
        roof = "hip" if along_u > 0.12 * sloped_area else "gable"  # a gable's slopes all face across the length
    else:
        fh = eaves / floors  # the storeys fill the height to the roof
        extra = H - eaves
        parapet = round(max(0.0, min(1.2, extra)), 2)
        if extra > 1.5:
            notes.append(f"About {extra:.1f} m of structures stand above the roof (stair tower, plant room, masts): "
                         f"add them as a block on the top floor if they matter.")
    # plan positions in the building's own frame: u along its width, v along its depth, from its corner
    uv = lambda x, y: (x * ct + y * st, -x * st + y * ct)  # noqa: E731
    hu = [uv(*p) for p in hull]
    u0, v0 = min(p[0] for p in hu), min(p[1] for p in hu)
    blocks = []  # parts to add on top of the main block: a tower on a podium, stair towers and plant rooms
    tower = None
    high = _hull([(V[i][0], V[i][1]) for i in mass if V[i][2] > 0.6 * H])
    if not pitched and len(high) >= 3 and _area(high) < 0.4 * plan:  # a tower on a wider, lower base (podium)
        tw, td, _ = _min_rect(high)
        tower = {"width": round(tw, 2), "depth": round(td, 2)}
        low = flat_low + Counter({z: a for z, a in flat_at.items() if z < 0.6 * H})
        base_z = eaves if eaves < 0.6 * H else (max(low, key=low.get) if low else 2 * fh)
        base_floors = max(1, min(39, int(base_z / fh + 0.35)))
        rise = H - base_z  # the tower's own storeys, from the podium roof up
        tfh = _storey([V[i][2] - base_z for i in mass if V[i][2] > base_z], rise) or fh
        tfloors = max(1, min(60 - base_floors, int(rise / tfh + 0.35)))
        b = _rect_block([uv(*p) for p in high], u0, v0, w, d)
        notes = [n for n in notes if "stand above the roof" not in n]
        if b:
            blocks.append({**b, "floors": tfloors, "floor_height": round(max(2.4, min(8.0, tfh)), 2),
                           "start_floor": base_floors, "parapet": parapet or 1.0, "what": "tower"})
            floors, fh = base_floors, base_z / base_floors
        notes.append(f"The tall part is only about {tw:.0f} x {td:.0f} m on a wider, lower base of {base_floors} "
                     f"floor(s): the tower is added on it as a block of {tfloors} floor(s).")
    elif not pitched and H - eaves > 1.5:  # stair towers, lift rooms and plant rooms standing on the main roof
        for pts, top in _parts_above(V, faces, keep, eaves + 1.0):
            b = _rect_block([uv(x, y) for x, y in pts], u0, v0, w, d)
            if not b or b["width"] < 1.5 or b["depth"] < 1.5:
                continue  # masts, aerials, railings
            rise = top - eaves
            n = max(1, round(rise / 3.2))
            blocks.append({**b, "floors": n, "floor_height": round(min(4.5, max(2.4, (rise - 0.3) / n)), 2),
                           "start_floor": floors, "parapet": 0.3, "what": "on the roof"})
        if blocks:
            notes[-1] = (f"{len(blocks)} part(s) stand up to {H - eaves:.1f} m above the main roof (stair towers, "
                         f"plant rooms): they are added on the top floor as blocks.")
    fill = plan / (w * d) if w and d else 1
    if fill < 0.8:
        notes.append(f"The building fills {fill:.0%} of its rectangle (an L, T or courtyard plan): design the main "
                     f"block, then add the other parts with 'Add as a new block'.")
    above = sum(1 for v in V if v[2] > 0.5)
    if len(mass) < 0.6 * above:
        notes.append("Other objects in the model (site items, trees, separate blocks) were left out.")
    if w > 200 or d > 200:
        notes.append("Larger than 200 m: trimmed to the designer's limit.")
    w, d = round(max(3.0, min(200.0, w)), 2), round(max(3.0, min(200.0, d)), 2)
    brief = {"width": w, "depth": d, "floors": floors, "floor_height": round(max(2.4, min(8.0, fh)), 2),
             "rooms_x": max(1, min(20, round(w / 4.5))), "rooms_y": max(1, min(20, round(d / 4.5))),
             "roof": roof, "pitch": pitch or 25.0, "parapet": parapet, "columns": floors >= 4,
             "material": "concrete" if floors >= 4 else "block"}
    summary = (f"{w:g} x {d:g} m, {floors} floor(s) of {brief['floor_height']:g} m, {H:.1f} m high, "
               f"{roof} roof{f' at {pitch:g} deg' if roof != 'flat' else ''}; turned {turn:.0f} deg; units: {unit}, {up.upper()} up")
    return {"brief": brief, "summary": summary, "notes": notes, "turn_deg": round(turn, 1), "height_m": round(H, 2),
            "unit": unit, "units": list(UNIT_NAMES), "up": up, "tower": tower, "blocks": blocks, "vertices": len(verts), "faces": len(faces)}
