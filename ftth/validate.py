"""Data-cleaning and design QA checks. Each issue: severity, code, message, ref."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from . import calc, splicing
from .geo import haversine, valid_coord
from .model import Design


def validate(d: Design) -> list[dict]:
    issues: list[dict] = []

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
        bad = [n for n in c.reserved if not 1 <= n <= c.cores]
        if bad:
            add("error", "reserved_range", f"Cable {c.id} reserves non-existent cores {bad}", c.id)
        if c.status == "proposed" and c.install == "aerial" and len(c.path) >= 2 and not any(v.pole for v in c.path):
            add("warning", "aerial_no_poles", f"Aerial cable {c.id} is not attached to any pole", c.id)

    # cable sizing: homes downstream vs. cores is checked by allocation; FAT capacity here
    load = calc.fat_load(d)
    for n in d.nodes:
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
        elif fat_ids and not h.fat and h.units > 0:  # premises with no homepasses need no FAT
            add("warning", "home_unassigned", f"Home {h.id} is not served by a FAT", h.id)

    if d.cables and not any(n.kind == "POP" or (n.kind in ("ENCLOSURE", "PR_ENCLOSURE") and n.status == "existing")
                            for n in d.nodes):
        add("error", "no_pop", "Design has cables but no starting point (a POP or an existing interception closure)")

    # ---- splicing ------------------------------------------------------------
    issues.extend(splicing.check(d))

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
    return issues


def counts(issues: list[dict]) -> dict:
    c = Counter(i["severity"] for i in issues)
    return {"errors": c.get("error", 0), "warnings": c.get("warning", 0), "notes": c.get("info", 0)}
