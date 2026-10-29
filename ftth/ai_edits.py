"""Changes the AI assistant may propose to the open project.

The assistant never edits on its own: it ends its answer with an ```actions block (a JSON list); the server reads
and checks it, the planner sees each change in plain words and presses Apply, and only then does the server make
the changes, in one step that Undo takes back like any other edit. Only the operations below exist, each with
checked fields, so a reply cannot do anything else.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from . import building as B, sectors
from .model import Design

MAX_ACTIONS = 12
_BLOCK = re.compile(r"```(?:actions|json)?\s*(\[[\s\S]*?\]|\{[\s\S]*?\})\s*```", re.I)

KIND_NAMES = {"flower_bed": "flower beds", "lawn": "lawn", "shrub_bed": "shrub beds", "paving": "paving",
              "hedge": "hedge", "tree": "trees"}
INFO_FIELDS = ("name", "client", "area", "region")
FTTH_RULES = ("default_fat_ports", "default_fat_split", "default_pon_split", "fat_load_take_rate", "cable_extra_pct",
              "slack_per_cable_end_m", "slack_per_passing_node_m")

CONSTRUCTION_HELP = """
You can also change this building. When the planner asks for a change (or agrees to one you suggested), describe
what you propose in a sentence or two (it is not done yet: say "I propose" or "this will", never "I added"), then
end your answer with ONE fenced block in exactly this form:
```actions
[{"op": "...", ...}]
```
The planner sees the changes and presses Apply; nothing changes until then. Use only these operations:
- {"op": "add_landscape", "kind": "flower_bed"|"lawn"|"shrub_bed"|"paving", "around": "building", "width": 1.5, "gap": 1.0}
  (strips all round the building, gap m from the walls, kept clear of the entrances)
- {"op": "add_landscape", "kind": "flower_bed"|"lawn"|"shrub_bed"|"paving", "rect": [x0, y0, x1, y1]}
- {"op": "add_landscape", "kind": "hedge", "points": [[x, y], [x, y], ...]}
- {"op": "add_trees", "around": "building", "offset": 6, "spacing": 8}  or  {"op": "add_trees", "points": [[x, y], ...]}
- {"op": "remove_landscape", "kind": "tree"}  (leave out kind to remove all landscaping)
- {"op": "design_building", ...brief}  (replaces the building) and {"op": "add_block", ...brief, "x": 0, "y": 0,
  "start_floor": 0}  (a wing, a tower on a podium, a roof plant room). Brief fields: width, depth, floors,
  floor_height, rooms_x, rooms_y, material (block|brick|stone|concrete), columns (true/false), roof
  (gable|hip|shed|flat), pitch, covering (iron sheets|tiles|concrete), parapet, window_width, window_spacing,
  window_style (fixed|casement|sliding|hung), door_style (single|double|sliding|arched), use
  (general|house|office|hospital|school|apartments: names the rooms), corridor (m; 0 = rooms open into each
  other; leave it out for 1.8 m, 2.4 m in a hospital)
- {"op": "set_spec", "footing_width": 0.6, "excavation_depth": 0.9, "setback": 3, "plaster": true, ...}
- {"op": "set_info", "name": "...", "client": "...", "area": "...", "region": "..."}
Coordinates are metres on the building's plan: x east, y north, from the building's south-west corner (see
"footprint" in the summary). The compound is the ground round the footprint. Never invent other operations or
fields; when a request cannot be done with them, say so and point to the app's tools instead.
"""

NETWORK_HELP = """
You can also change a few project settings. When the planner asks for such a change, describe what you propose
briefly (it is not done yet: say "I propose" or "this will", never "I changed"), then end your answer with ONE
fenced block:
```actions
[{"op": "set_info", "name": "...", "client": "...", "area": "...", "region": "..."},
 {"op": "set_rules", "default_fat_ports": 16, "cable_extra_pct": 5}]
```
set_rules accepts only: """ + ", ".join(FTTH_RULES) + """. The planner presses Apply; nothing changes until then.
Drawing and routing changes are made with the app's tools (Auto-design, Auto-allocate, the map), not by you.
"""


class EditError(ValueError):
    pass


def help_text(d: Design) -> str:
    return CONSTRUCTION_HELP if sectors.get(d.info.sector).get("construction") else NETWORK_HELP


def extract(answer: str) -> tuple[str, list]:
    """The answer without its actions block, and the actions in it (unchecked). A block that is not valid JSON
    is left in the text and gives no actions."""
    m = None
    for m in _BLOCK.finditer(answer):
        pass  # the last block is the proposal
    if not m:
        return answer, []
    try:
        acts = json.loads(m.group(1))
    except json.JSONDecodeError:
        return answer, []
    if isinstance(acts, dict):
        acts = [acts]
    if not isinstance(acts, list) or not all(isinstance(a, dict) and isinstance(a.get("op"), str) for a in acts):
        return answer, []
    return (answer[:m.start()] + answer[m.end():]).strip(), acts


def _num(a: dict, k: str, default: float, lo: float, hi: float) -> float:
    v = a.get(k, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise EditError(f"{a['op']}: {k} must be a number from {lo:g} to {hi:g}")
    return float(v)


def _pts(a: dict, k: str = "points", least: int = 1) -> list:
    v = a.get(k)
    if not isinstance(v, list) or len(v) < least or len(v) > 200:
        raise EditError(f"{a['op']}: {k} must be a list of at least {least} [x, y] points")
    try:
        return [B._pt([float(p[0]), float(p[1])]) for p in v if isinstance(p, (list, tuple)) and len(p) == 2]
    except (TypeError, ValueError):
        raise EditError(f"{a['op']}: {k} must be [x, y] points in metres") from None


def _brief(a: dict, keep: tuple = ()) -> B.AutoParams:
    fields = {k: v for k, v in a.items() if k != "op"}
    bad = [k for k in fields if k not in B.AutoParams.model_fields or (k in ("x", "y", "start_floor") and k not in keep)]
    if bad:
        raise EditError(f"{a['op']}: unknown field(s) {', '.join(bad)}")
    try:
        return B.AutoParams.model_validate(fields)
    except ValidationError as e:
        er = e.errors(include_url=False)[0]
        raise EditError(f"{a['op']}: {'.'.join(str(x) for x in er.get('loc', []))}: {er.get('msg', 'invalid')}") from None


def _landscape(b: B.Building, a: dict) -> list[B.Landscape]:
    kind = a.get("kind")
    if kind not in KIND_NAMES or kind == "tree":
        raise EditError("add_landscape: kind must be flower_bed, lawn, shrub_bed, paving or hedge")
    note = str(a.get("note") or "")[:120]
    if kind == "hedge":
        pts = _pts(a, least=2)
        return [B.Landscape(id=f"L{B._next_landscape_id(b)}", kind=kind, points=pts, note=note)]
    if a.get("around") == "building":
        try:
            return B.landscape_around(b, kind, _num(a, "width", 1.5, 0.3, 20), _num(a, "gap", 1.0, 0, 30), note=note)
        except ValueError as e:
            raise EditError(str(e)) from None
    r = a.get("rect")
    if isinstance(r, list) and len(r) == 4:
        try:
            x0, y0, x1, y1 = (float(v) for v in r)
        except (TypeError, ValueError):
            raise EditError("add_landscape: rect is [x0, y0, x1, y1] in metres") from None
        x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
        if x1 - x0 < 0.3 or y1 - y0 < 0.3 or max(abs(x0), abs(x1), abs(y0), abs(y1)) > 2000:
            raise EditError("add_landscape: the rect is too small or too far from the building")
        pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    else:
        pts = _pts(a, least=3)
    return [B.Landscape(id=f"L{B._next_landscape_id(b)}", kind=kind, points=pts, note=note)]


def describe(a: dict) -> str:
    """The change in plain words, for the planner to approve."""
    op = a.get("op")
    kind = KIND_NAMES.get(a.get("kind"), a.get("kind") or "")
    if op == "add_landscape":
        if a.get("around") == "building":
            return f"Add {kind} all round the building, {a.get('width', 1.5):g} m wide, {a.get('gap', 1.0):g} m from the walls (entrances kept clear)"
        if kind == "hedge":
            return f"Add a hedge along {len(a.get('points') or [])} points"
        if a.get("rect"):
            x0, y0, x1, y1 = a["rect"]
            return f"Add {kind}: {abs(x1 - x0):g} x {abs(y1 - y0):g} m at ({min(x0, x1):g}, {min(y0, y1):g})"
        return f"Add {kind} ({len(a.get('points') or [])}-point outline)"
    if op == "add_trees":
        if a.get("around") == "building":
            return f"Plant trees round the building, {a.get('offset', 6):g} m out, every {a.get('spacing', 8):g} m"
        return f"Plant {len(a.get('points') or [])} tree(s)"
    if op == "remove_landscape":
        return f"Remove all {kind}" if kind else "Remove all landscaping"
    if op == "design_building":
        return ("Redesign the building: " + ", ".join(f"{k} {v}" for k, v in a.items() if k != "op"))[:300]
    if op == "add_block":
        return ("Add a block: " + ", ".join(f"{k} {v}" for k, v in a.items() if k != "op"))[:300]
    if op in ("set_spec", "set_info", "set_rules"):
        what = {"set_spec": "Construction standards", "set_info": "Project details", "set_rules": "Design rules"}[op]
        return f"{what}: " + ", ".join(f"{k} = {v}" for k, v in a.items() if k != "op")
    return f"Unknown change: {op}"


def apply(d: Design, actions: list) -> list[str]:
    """Make the changes (all or none: they are checked one after another on the design, which the caller saves
    only when every one worked). Returns what was done, in plain words."""
    if not isinstance(actions, list) or not actions:
        raise EditError("No changes to apply")
    if len(actions) > MAX_ACTIONS:
        raise EditError(f"At most {MAX_ACTIONS} changes at a time")
    construction = bool(sectors.get(d.info.sector).get("construction"))
    done = []
    for a in actions:
        if not isinstance(a, dict) or not isinstance(a.get("op"), str):
            raise EditError("Each change is an object with an op")
        op = a["op"]
        if op == "set_info":
            extra = [k for k in a if k not in ("op", *INFO_FIELDS)]
            if extra:
                raise EditError(f"set_info: unknown field(s) {', '.join(extra)}")
            for k in INFO_FIELDS:
                if k in a:
                    setattr(d.info, k, str(a[k])[:200])
        elif op == "set_rules" and not construction:
            for k, v in a.items():
                if k == "op":
                    continue
                if k not in FTTH_RULES:
                    raise EditError(f"set_rules: {k} cannot be changed here")
                try:
                    d.rules = d.rules.model_validate(d.rules.model_dump() | {k: v})
                except ValidationError:
                    raise EditError(f"set_rules: {k} = {v} is not allowed") from None
        elif not construction:
            raise EditError(f"{op}: not available for this project")
        elif op == "design_building":
            old = d.building
            d.building = B.generate(_brief(a))
            if old is not None:
                d.building.origin, d.building.rotation, d.building.spec = old.origin, old.rotation, old.spec
                d.building.landscape = old.landscape
        else:
            b = d.building
            if b is None or not b.walls:
                raise EditError(f"{op}: design the building first")
            if op == "add_block":
                try:
                    d.building = B.add_block(b, _brief(a, keep=("x", "y", "start_floor")))
                except ValueError as e:
                    raise EditError(f"add_block: {e}") from None
            elif op == "add_landscape":
                b.landscape += _landscape(b, a)
            elif op == "add_trees":
                note = str(a.get("note") or "")[:120]
                if a.get("around") == "building":
                    b.landscape += B.trees_around(b, _num(a, "offset", 6, 1, 100), _num(a, "spacing", 8, 2, 100),
                                                  note=note)
                else:
                    k = B._next_landscape_id(b)
                    b.landscape += [B.Landscape(id=f"L{k + j}", kind="tree", points=[p], note=note)
                                    for j, p in enumerate(_pts(a))]
            elif op == "remove_landscape":
                kind = a.get("kind")
                if kind is not None and kind not in KIND_NAMES:
                    raise EditError("remove_landscape: unknown kind")
                b.landscape = [x for x in b.landscape if kind is not None and x.kind != kind]
            elif op == "set_spec":
                fields = {k: v for k, v in a.items() if k != "op"}
                bad = [k for k in fields if k not in B.Spec.model_fields]
                if bad:
                    raise EditError(f"set_spec: unknown field(s) {', '.join(bad)}")
                try:
                    b.spec = B.Spec.model_validate(b.spec.model_dump() | fields)
                except ValidationError as e:
                    er = e.errors(include_url=False)[0]
                    raise EditError(f"set_spec: {'.'.join(str(x) for x in er.get('loc', []))}: {er.get('msg')}") from None
            else:
                raise EditError(f"{op}: not something the assistant can change")
            try:
                d.building = B.Building.model_validate(d.building.model_dump())
            except ValidationError as e:
                er = e.errors(include_url=False)[0]
                raise EditError(f"{op}: {'.'.join(str(x) for x in er.get('loc', []))}: {er.get('msg')}") from None
        done.append(describe(a))
    if construction:  # older projects: price list entries for codes the change brought in (landscaping)
        have = {m.code for m in d.materials}
        d.materials += [m.model_copy() for m in sectors.get(d.info.sector)["materials"] if m.code not in have]
    return done


def proposal(d: Design, answer: str) -> tuple[str, list, list[str]]:
    """Split an answer into its text and a checked proposal: (text, actions, descriptions). A proposal that would
    fail is dropped, and the text says why."""
    text, acts = extract(answer)
    if not acts:
        return text, [], []
    try:
        apply(d.model_copy(deep=True), acts)  # a dry run on a copy
    except EditError as e:
        return text + f"\n\n(The proposed change could not be prepared: {e})", [], []
    return text, acts, [describe(a) for a in acts]
