r"""Blind design test: strip the designer's network from an approved project, let the planner design it
from survey data only, and compare with the approved design.

Usage:  .venv\Scripts\python tools\blind_test.py calibration\infinity-fy26-approved
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from calibrate import load_design, reference  # noqa: E402

from ftth import autodesign, calc, validate  # noqa: E402
from ftth.geo import haversine  # noqa: E402


def survey_only(d, interception=None, extend=True):
    """What a survey team delivers: existing poles and infrastructure, premises with HP counts."""
    s = d.model_copy(deep=True)
    s.cables = [c for c in s.cables if c.status == "existing"]
    s.nodes = [n for n in s.nodes if n.status == "existing" and n.kind != "SLACK"]
    keep_poles = {p.id for p in s.poles if p.status == "existing"}
    s.poles = [p for p in s.poles if p.id in keep_poles]
    keep_nodes = {n.id for n in s.nodes}
    for n in s.nodes:
        if n.pole not in keep_poles:
            n.pole = None
    for c in s.cables:  # existing cables keep their geometry, but not links to removed design features
        for v in c.path:
            v.pole = v.pole if v.pole in keep_poles else None
            v.node = v.node if v.node in keep_nodes else None
        c.from_node = c.from_node if c.from_node in keep_nodes else None
        c.to_node = c.to_node if c.to_node in keep_nodes else None
    s.info.interception_node = interception or ""
    if not extend:
        s.info.extend_to = []
    s.splitters, s.connections, s.ducts = [], [], []
    for h in s.homes:
        h.fat, h.extra_fats = None, []
    return s


def route_overlap(a_cables, b_cables, tol=12.0):
    """Share of a's proposed cable length that lies within tol metres of b's proposed cables."""
    pts_b = []
    for c in b_cables:
        for u, v in zip(c.path, c.path[1:]):
            L = haversine(u.lat, u.lon, v.lat, v.lon)
            n = max(1, int(L / 5))
            pts_b += [(u.lat + (v.lat - u.lat) * k / n, u.lon + (v.lon - u.lon) * k / n) for k in range(n + 1)]
    tot = near = 0.0
    for c in a_cables:
        for u, v in zip(c.path, c.path[1:]):
            L = haversine(u.lat, u.lon, v.lat, v.lon)
            n = max(1, int(L / 5))
            for k in range(n):
                la, lo = u.lat + (v.lat - u.lat) * (k + .5) / n, u.lon + (v.lon - u.lon) * (k + .5) / n
                tot += L / n
                if any(haversine(la, lo, *q) <= tol for q in pts_b):
                    near += L / n
    return near / tot if tot else 0.0


def run(folder: Path, verbose=True, opt=None, interception="Ex Closure 01", extend=True):
    approved, _ = load_design(folder)
    ref = reference(folder)
    s = survey_only(approved, interception, extend)
    res = autodesign.auto_design(s, opt)
    ours = {l.code: l.qty for l in calc.bom(s)}
    rows = [(c, ref["bom"].get(c), ours.get(c)) for c in sorted(set(ref["bom"]) | set(ours))]
    prop_a = [c for c in approved.cables if c.status == "proposed"]
    prop_s = [c for c in s.cables if c.status == "proposed"]
    fa = [n for n in approved.nodes if n.kind == "FAT"]
    fs = [n for n in s.nodes if n.kind == "FAT"]
    fat_dist = sorted(min(haversine(a.lat, a.lon, b.lat, b.lon) for b in fs) for a in fa) if fs else []
    out = {
        "log": res["log"], "unassigned": res["unassigned"], "alloc": res["allocation_issues"], "bom": rows,
        "errors": [i for i in validate.validate(s) if i["severity"] == "error"],
        "overlap_approved_in_planner": route_overlap(prop_a, prop_s),
        "overlap_planner_in_approved": route_overlap(prop_s, prop_a),
        "fat_within_15m": sum(1 for x in fat_dist if x <= 15) / len(fa) if fa else 0,
        "boq": calc.boq_total(calc.bom(s)), "design": s,
        "homepasses": calc.summary(s)["homepasses"],
    }
    if verbose:
        print("\n".join(res["log"]), "| unassigned:", res["unassigned"], "| allocation issues:", res["allocation_issues"])
        print("validation errors:", [e["message"] for e in out["errors"]][:5])
        print(f"\n{'Item':16s} {'Approved':>9s} {'Planner':>9s}  diff")
        for c, a, b in rows:
            pct = f"{((b or 0) - (a or 0)) / a * 100:+.0f}%" if a else ""
            print(f"{c:16s} {a if a is not None else '-':>9} {b if b is not None else '-':>9}  {pct}")
        print(f"\nRoutes: {out['overlap_approved_in_planner']:.0%} of the approved new cable length is followed by the "
              f"planner (within 12 m); {out['overlap_planner_in_approved']:.0%} of the planner's is on approved routes")
        print(f"FATs: {out['fat_within_15m']:.0%} of approved FATs have a planner FAT within 15 m")
        print(f"BOQ: planner KES {out['boq']:,.0f} vs approved KES 518,758")
    return out


if __name__ == "__main__":
    run(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "calibration" / "infinity-fy26-approved"))
