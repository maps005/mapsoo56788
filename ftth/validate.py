"""Data-cleaning and design QA checks. Each issue: severity, code, message, ref."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from . import calc, sectors, splicing
from .geo import haversine, valid_coord
from .model import Design


def validate(d: Design) -> list[dict]:
    issues: list[dict] = []
    fibre, sec = sectors.fibre_tools(d), sectors.get(d.info.sector)

    def add(sev, code, msg, ref=None):
        issues.append({"severity": sev, "code": code, "message": msg, "ref": ref})

    # ---- identity ----------------------------------------------------------
    ids = Counter(x.id for coll in (d.poles, d.homes, d.nodes, d.splitters, d.cables) for x in coll)
    for i, n in ids.items():
        if not i or not i.strip():
            add("error", "id_missing", "A feature has an empty ID")
        elif n > 1:
            add("error", "id_duplicate", f"ID {i} is used {n} times", i)
    for i in ids:
        if i and i != i.strip():
            add("warning", "id_whitespace", f"ID '{i}' has leading/trailing spaces", i)

    # ---- survey data -------------------------------------------------------
    for coll, label in ((d.poles, "Pole"), (d.homes, "Home"), (d.nodes, "Node")):
        for x in coll:
            if x.lat is None or x.lon is None:
                if label == "Node" and x.pole and d.pole(x.pole):
                    continue
                add("error", "coord_missing", f"{label} {x.id} has no coordinates", x.id)
            elif not valid_coord(x.lat, x.lon):
                add("error", "coord_invalid", f"{label} {x.id} has invalid coordinates ({x.lat}, {x.lon})", x.id)

    # near-duplicate locations (same kind within 1 m)
    by_kind = defaultdict(list)
    for n in d.nodes:
        by_kind[n.kind].append(n)
    groups = [(d.poles, "Poles"), (d.homes, "Homes")] + \
        [(v, f"{k} equipment") for k, v in by_kind.items() if k != "SLACK"]
    for coll, label in groups:
        pts = [x for x in coll if valid_coord(x.lat, x.lon)]
        grid: dict[tuple, list] = defaultdict(list)
        def cell(x):
            return int(round(x.lat * 1e4)), int(round(x.lon * 1e4))

        for x in pts:
            grid[cell(x)].append(x)
        reported = set()
        for x in pts:
            cx, cy = cell(x)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for y in grid.get((cx + dx, cy + dy), []):
                        if y.id <= x.id or (x.id, y.id) in reported:
                            continue
                        if haversine(x.lat, x.lon, y.lat, y.lon) < 1.0:
                            reported.add((x.id, y.id))
                            add("warning", "location_duplicate",
                                f"{label} {x.id} and {y.id} are less than 1 m apart (possible duplicate)", x.id)

    for h in d.homes:
        if h.units < 0:
            add("error", "units_invalid", f"Home {h.id} has {h.units} units", h.id)
        elif h.units == 0:
            add("info", "units_unknown", f"{h.id}: no viable homepasses recorded (not counted)", h.id)
        if h.kind == "mdu" and h.units == 1:
            add("warning", "mdu_units", f"MDU {h.id} has only {h.units} unit(s)", h.id)

    # ---- network design ----------------------------------------------------
    for n in d.nodes:
        if n.pole and not d.pole(n.pole):
            add("error", "node_pole", f"{n.id} is mounted on unknown pole {n.pole}", n.id)
    for c in d.cables:
        if len(c.path) < 2:
            add("error", "cable_path", f"Cable {c.id} has fewer than 2 points", c.id)
            continue
        if c.cores < 1:
            add("error", "cable_cores", f"Cable {c.id} has {c.cores} cores", c.id)
        for v in c.path:
            if v.pole and not d.pole(v.pole):
                add("error", "cable_pole", f"Cable {c.id} passes unknown pole {v.pole}", c.id)
            if v.node and not d.node(v.node):
                add("error", "cable_node", f"Cable {c.id} passes unknown node {v.node}", c.id)
            p = d.pole(v.pole) if v.pole else None
            if p and valid_coord(p.lat, p.lon) and haversine(p.lat, p.lon, v.lat, v.lon) > 5:
                add("warning", "cable_pole_moved", f"Cable {c.id} vertex at {p.id} is >5 m from the pole "
                                                   f"(pole moved? redraw or re-snap the route)", c.id)
        for end, nid in (("from", c.from_node), ("to", c.to_node)):
            if c.kind != "drop" and not nid and c.status == "proposed":  # existing cables: survey record only
                v = c.path[0] if end == "from" else c.path[-1]
                if any(haversine(v.lat, v.lon, la, lo) <= 15 for la, lo in d.info.extend_to):
                    add("info", "cable_open_end", f"Cable {c.id} '{end}' end is left open at a backbone end "
                                                  f"marker (future extension)", c.id)
                elif c.kind == "main" and v.pole:
                    add("info", "cable_open_end", f"Cable {c.id} '{end}' end stops at pole {v.pole} without "
                                                  f"equipment (backbone stub for future extension)", c.id)
                else:
                    add("warning", "cable_unterminated", f"Cable {c.id} has no '{end}' node", c.id)
            elif nid and not d.node(nid):
                add("error", "cable_end_node", f"Cable {c.id} {end}-node {nid} does not exist", c.id)
        bad = [n for n in c.reserved if not 1 <= n <= c.cores] if fibre else []
        if bad:
            add("error", "reserved_range", f"Cable {c.id} reserves non-existent cores {bad}", c.id)
        if not fibre and c.cores not in sec["sizes"]:
            add("warning", "line_size", f"{sec['line']} {c.id} size {sectors.size_label(d.info.sector, c.cores)} is not "
                                        f"one of the sector's sizes ({', '.join(map(str, sec['sizes']))} {sec['size_unit']})", c.id)
        if c.status == "proposed" and c.install == "aerial" and len(c.path) >= 2 and not any(v.pole for v in c.path):
            add("warning", "aerial_no_poles", f"Aerial cable {c.id} is not attached to any pole", c.id)

    # cable sizing: homes downstream vs. cores is checked by allocation; FAT capacity here
    load = calc.fat_load(d)
    for n in d.nodes if fibre else []:  # FAT ports are fibre; other sectors check their own capacity below
        if n.kind == "FAT":
            cap = n.ports or d.rules.default_fat_ports
            need = math.ceil(load.get(n.id, 0) * d.rules.fat_load_take_rate - 1e-9)
            if need > cap:
                rate = "" if d.rules.fat_load_take_rate >= 1 else f" ({d.rules.fat_load_take_rate:.1%} take rate of {load[n.id]} HPs)"
                add("error", "fat_capacity", f"{n.id} needs {need} ports{rate} but has {cap}", n.id)
    fat_ids = {n.id for n in d.nodes if n.kind == "FAT"}
    for h in d.homes:
        bad = [f for f in h.fats if f not in fat_ids]
        if bad:
            add("error", "home_fat", f"Home {h.id} is assigned to unknown FAT {', '.join(bad)}", h.id)
        elif fat_ids and not h.fat and h.units > 0 and d.info.sector != "lighting":  # no homepasses: no FAT needed
            add("warning", "home_unassigned", f"Home {h.id} is not served by a FAT", h.id)

    if d.cables and not any(n.kind == "POP" or (n.kind in ("ENCLOSURE", "PR_ENCLOSURE") and n.status == "existing")
                            for n in d.nodes):
        k = sec["kinds"]
        add("error", "no_pop", "Design has cables but no starting point (a POP or an existing interception closure)"
            if fibre else f"Design has cables but no starting point (a {k['POP'].lower()} or an existing "
                          f"{k['ENCLOSURE'].lower()})")

    # ---- splicing (fibre) / sector engineering checks ---------------------------
    if fibre:
        issues.extend(splicing.check(d))
    else:
        _sector_checks(d, add)

    # ---- materials -----------------------------------------------------------
    for line in calc.bom(d):
        if line.rate is None:
            add("warning", "material_missing", f"BOM item {line.code} is not in the material catalogue (no rate)", line.code)
        if line.qty < 0:
            add("error", "bom_negative", f"BOM item {line.code} has a negative quantity ({line.qty:g}) after "
                                         f"manual adjustments", line.code)
    for a in d.adjustments:
        if not a.reason.strip():
            add("error", "adjustment_reason", f"Manual adjustment to {a.code} needs a reason before approval", a.code)

    # ---- records -------------------------------------------------------------
    dup_conn = [i for i, n in Counter(c.id for c in d.connections).items() if n > 1]
    for i in dup_conn:
        add("error", "connection_duplicate", f"Connection ID {i} is used more than once", i)
    feature_ids = {x.id for coll in (d.poles, d.homes, d.nodes, d.cables) for x in coll}
    for ph in d.photos:
        if ph.feature and ph.feature not in feature_ids:
            add("warning", "photo_feature", f"Photo '{ph.caption or ph.file}' refers to unknown feature {ph.feature}",
                ph.feature)

    # ---- workflow --------------------------------------------------------------
    if (d.cables or d.nodes) and d.info.survey_status != "approved":
        add("warning", "survey_unapproved", "Design work exists but the survey dataset is not approved")
    words = sectors.wording(d.info.sector)
    if words:  # messages in the sector's words: "Manhole MH-03", "Sewer S004", not pole and cable
        for i in issues:
            i["message"] = sectors.reword(i["message"], words)
    return issues


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _sector_checks(d: Design, add) -> None:
    """Checks a fibre network does not need: sewer fall from invert levels, transformer loading, column spacing."""
    r, key = d.rules, d.info.sector
    if key == "sanitation":
        # invert levels recorded at manholes (supports or equipment) along each sewer, in drawing order
        for c in d.cables:
            pts = []  # (chainage m, invert m, feature id)
            dist = 0.0
            for i, v in enumerate(c.path):
                if i:
                    a = c.path[i - 1]
                    dist += haversine(a.lat, a.lon, v.lat, v.lon)
                f = (d.node(v.node) if v.node else None) or (d.pole(v.pole) if v.pole else None)
                lvl = _num(f.details.get("invert_level_m")) if f else None
                if lvl is not None and (not pts or pts[-1][2] != f.id):
                    pts.append((dist, lvl, f.id))
            if len(pts) < 2:
                continue
            flow = 1 if pts[0][1] >= pts[-1][1] else -1  # sewage runs to the lower end
            for (c1, l1, a), (c2, l2, b) in zip(pts, pts[1:]):
                run = c2 - c1
                if run < 0.5:
                    continue
                fall = (l1 - l2) * flow
                pct = fall / run * 100
                if fall < 0:
                    add("error", "sewer_adverse", f"Sewer {c.id} rises {-fall:.2f} m from {a} to {b} against the flow "
                                                  f"(check the invert levels)", c.id)
                elif pct < r.sewer_min_gradient_pct:
                    add("warning", "sewer_gradient", f"Sewer {c.id} {a} to {b}: gradient {pct:.2f}% is below the "
                                                     f"minimum {r.sewer_min_gradient_pct:g}% (1 in "
                                                     f"{100 / r.sewer_min_gradient_pct:.0f})", c.id)
        for f in list(d.poles) + list(d.nodes):
            cover, inv = _num(f.details.get("cover_level_m")), _num(f.details.get("invert_level_m"))
            if cover is not None and inv is not None and inv >= cover:
                add("error", "manhole_levels", f"{f.id}: invert level {inv:g} m is not below the cover level {cover:g} m",
                    f.id)
    if key == "electricity":
        capacity = sum(n.ports or 0 for n in d.nodes if n.kind == "PON")
        demand = sum((_num(h.details.get("load_kva")) or r.admd_kva) * max(h.units, 0) for h in d.homes)
        if demand and not capacity:
            add("warning", "tx_missing", f"{demand:.0f} kVA of customer demand but no distribution transformer")
        elif capacity and demand > capacity:
            add("error", "tx_overload", f"Customer demand {demand:.0f} kVA exceeds the transformer capacity "
                                        f"{capacity:.0f} kVA (customers without a recorded load count {r.admd_kva:g} kVA)")
        for n in d.nodes:
            if n.kind == "PON" and not n.ports:
                add("warning", "tx_rating", f"Transformer {n.id} has no kVA rating", n.id)
    if key == "lighting":
        cols = {p.id for p in d.poles}
        for c in d.cables:
            seq = []  # lighting columns along the cable, with their chainage
            dist = 0.0
            for i, v in enumerate(c.path):
                if i:
                    dist += haversine(c.path[i - 1].lat, c.path[i - 1].lon, v.lat, v.lon)
                if v.pole in cols and (not seq or seq[-1][1] != v.pole):
                    seq.append((dist, v.pole))
            for (c1, a), (c2, b) in zip(seq, seq[1:]):
                if c2 - c1 > r.max_column_spacing_m:
                    add("warning", "column_spacing", f"Columns {a} and {b} on {c.id} are {c2 - c1:.0f} m apart (more "
                                                     f"than {r.max_column_spacing_m:g} m: dark patch between them)", c.id)


def counts(issues: list[dict]) -> dict:
    c = Counter(i["severity"] for i in issues)
    return {"errors": c.get("error", 0), "warnings": c.get("warning", 0), "notes": c.get("info", 0)}
