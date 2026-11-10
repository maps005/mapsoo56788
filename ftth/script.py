"""Design scripts: build or change a project from lines of plain commands (the planner's Script tab).

One command a line; '#' starts a comment; words with spaces go in quotes; options are key=value. A point is
"lat,lon", or "E,N" in the project's grid (UTM; a number above 180 is read as grid). The whole script runs or
none of it does: the first bad line stops it with its line number. Each command needs the member's occupation
to include its feature (ftth.occupations), as the tabs do.

    name "Kasarani phase 1"            area "Kasarani, Nairobi"         crs utm        scale 1000
    boundary -1.22,36.89; -1.22,36.90; -1.23,36.90; -1.23,36.89
    pole P001 -1.2201,36.8951 type=concrete height=9 status=proposed
    home H001 -1.2203,36.8953 units=4 kind=mdu
    fat FAT01 on=P001 ports=8          pop POP01 -1.2199,36.8949
    cable C001 main 48 POP01 > P001 > P002 > FAT01 install=aerial
    autodesign                         assign max=250                   allocate
    site soil=clay bearing_capacity=150             room Bedroom 24 12
    building width=24 depth=12 floors=4 use=apartments roof=flat        place -1.2201,36.8951 rotation=15
    dam catchment_km2=18 rain_24h=110 fsl=1515      axis 0 1522 2       reservoir 1500 0
    set rules.cable_extra_pct = 4          delete P009 H017                 check
"""
from __future__ import annotations

import shlex

from pydantic import BaseModel, ValidationError

from . import calc, sectors, splicing, validate
from .geo import GridProjection, LocalProjection, valid_coord
from .model import Cable, Design, Home, Node, Pole, Vertex


class ScriptError(ValueError):
    def __init__(self, line: int, msg: str):
        super().__init__(f"Line {line}: {msg}")
        self.line = line


NODE_WORDS = {"pop": "POP", "closure": "ENCLOSURE", "enclosure": "ENCLOSURE", "prclosure": "PR_ENCLOSURE",
              "jb": "JB", "pon": "PON", "fat": "FAT", "slack": "SLACK"}
# command: (features that allow it (any), the kind of project it is for: "network", "building", "dam" or None)
NEEDS = {
    "pole": ({"network_edit", "survey"}, "network"), "home": ({"network_edit", "survey"}, "network"),
    "node": ({"network_edit"}, "network"), "cable": ({"network_edit"}, "network"), "assign": ({"network_edit"}, "network"),
    "autodesign": ({"autodesign"}, "network"), "allocate": ({"splicing"}, "network"),
    "site": ({"building_design"}, "building"), "room": ({"building_design"}, "building"),
    "building": ({"building_design"}, "building"), "place": ({"building_design"}, "building"),
    "dam": ({"dam"}, "dam"), "axis": ({"dam"}, "dam"), "reservoir": ({"dam"}, "dam"), "damaxis": ({"dam"}, "dam"),
    "sector": ({"costing"}, None),
}
HELP = ("Commands: name area client prepared crs scale boundary set check delete · network: pole home pop closure jb "
        "pon fat slack node cable autodesign assign allocate · building: site room building place · dam: dam axis "
        "reservoir damaxis · sector")


def _num(s: str, what: str) -> float:
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"{what} must be a number, not '{s}'") from None


def _value(v: str):
    """A key=value value as the model expects: number, true / false, none, or text."""
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("none", "null"):
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def _opts(words: list[str]) -> tuple[list[str], dict]:
    pos, opt = [], {}
    for w in words:
        if "=" in w and not w.startswith("="):
            k, v = w.split("=", 1)
            opt[k.strip().lower()] = _value(v.strip())
        else:
            pos.append(w)
    return pos, opt


def _update(model: BaseModel, changes: dict, what: str) -> BaseModel:
    unknown = [k for k in changes if k not in type(model).model_fields]
    if unknown:
        raise ValueError(f"{what} has no {', '.join(unknown)} (it has {', '.join(list(type(model).model_fields)[:12])}...)")
    try:
        return type(model).model_validate({**model.model_dump(), **changes})
    except ValidationError as e:
        er = e.errors(include_url=False)[0]
        raise ValueError(f"{what}.{'.'.join(str(x) for x in er.get('loc', []))}: {er.get('msg', 'invalid value')}") from None


class _Run:
    def __init__(self, d: Design, features: set[str]):
        self.d, self.features, self.log = d, features, []
        s = sectors.get(d.info.sector)
        self.kind = "dam" if s.get("dam") else "building" if s.get("construction") else "network"

    # -- points ---------------------------------------------------------------------------------------------
    def grid(self):
        d = self.d
        pts = [(x.lat, x.lon) for coll in (d.poles, d.homes, d.nodes) for x in coll if valid_coord(x.lat, x.lon)]
        pts += [tuple(b) for b in d.info.boundary]
        c = LocalProjection.for_points(pts) if pts else LocalProjection(-1.0, 37.0)  # Kenya: zone 37 south
        return GridProjection(d.info.crs if d.info.crs in ("utm", "arc1960") else "utm", c.lat0, c.lon0)

    def point(self, text: str) -> tuple[float, float]:
        parts = text.replace(";", ",").split(",")
        if len(parts) != 2:
            raise ValueError(f"'{text}' is not a point: write lat,lon (or E,N in the project's grid)")
        a, b = _num(parts[0], "a coordinate"), _num(parts[1], "a coordinate")
        if abs(a) > 180 or abs(b) > 180:  # grid easting, northing
            a, b = self.grid().latlon(a, b)
        if not valid_coord(a, b):
            raise ValueError(f"'{text}' is not a valid latitude, longitude")
        return round(a, 7), round(b, 7)

    def feature_at(self, ref: str) -> tuple[float, float, str | None, str | None]:
        """A path element: a pole / equipment / premise ID, or a point. (lat, lon, pole, node)"""
        d = self.d
        if "," in ref:
            la, lo = self.point(ref)
            return la, lo, None, None
        if (p := d.pole(ref)) is not None:
            return p.lat, p.lon, p.id, None
        if (n := d.node(ref)) is not None:
            if n.lat is None and n.pole and d.pole(n.pole):
                return d.pole(n.pole).lat, d.pole(n.pole).lon, n.pole, n.id
            return n.lat, n.lon, n.pole, n.id
        if (h := next((x for x in d.homes if x.id == ref), None)) is not None:
            return h.lat, h.lon, None, None
        raise ValueError(f"no pole, equipment or premise '{ref}' (define it on an earlier line)")

    # -- commands -------------------------------------------------------------------------------------------
    def run_line(self, cmd: str, words: list[str]):
        d = self.d
        pos, opt = _opts(words)
        if cmd in NODE_WORDS:
            cmd, pos = "node", [NODE_WORDS[cmd]] + pos
        need, kind = NEEDS.get(cmd, (None, None))
        if kind and kind != self.kind:
            raise ValueError(f"'{cmd}' is for a {kind} project; this is a {sectors.get(d.info.sector)['label']} project")
        if need and not need & self.features:
            raise ValueError(f"'{cmd}' is not part of your occupation's work")
        fn = getattr(self, "c_" + cmd, None)
        if fn is None:
            raise ValueError(f"unknown command '{cmd}'. {HELP}")
        fn(pos, opt)

    def c_name(self, pos, opt):
        self.d.info.name = " ".join(pos)[:200] or self.d.info.name
        self.log.append(f"Project name: {self.d.info.name}")

    def c_area(self, pos, opt):
        self.d.info.area = " ".join(pos)[:200]

    def c_client(self, pos, opt):
        self.d.info.client = " ".join(pos)[:200]

    def c_prepared(self, pos, opt):
        self.d.info.prepared_by = " ".join(pos)[:200]

    def c_crs(self, pos, opt):
        if not pos or pos[0].lower() not in ("utm", "arc1960", "local"):
            raise ValueError("crs utm, arc1960 or local")
        self.d.info.crs = pos[0].lower()

    def c_scale(self, pos, opt):
        n = int(_num(pos[0].replace("1:", ""), "the scale")) if pos else 0
        if not 100 <= n <= 20000:
            raise ValueError("scale between 1:100 and 1:20000, e.g. scale 1000")
        self.d.info.cad_scale = n

    def c_boundary(self, pos, opt):
        pts = [self.point(p) for p in " ".join(pos).split(";") if p.strip()]
        if len(pts) < 3:
            raise ValueError("a boundary needs three points or more: boundary lat,lon; lat,lon; lat,lon")
        self.d.info.boundary = [list(p) for p in pts]
        self.log.append(f"Boundary: {len(pts)} corners")

    def c_sector(self, pos, opt):
        if not pos or pos[0] not in sectors.SECTORS:
            raise ValueError(f"sector one of {', '.join(sectors.SECTORS)}")
        sectors.apply(self.d, pos[0])
        s = sectors.get(pos[0])
        self.kind = "dam" if s.get("dam") else "building" if s.get("construction") else "network"
        self.log.append(f"Sector: {s['label']}")

    def c_set(self, pos, opt):
        text = " ".join(pos) + "".join(f" {k}={v}" for k, v in opt.items())
        if "=" not in text:
            raise ValueError("set <section>.<field> = <value>, e.g. set rules.cable_extra_pct = 4")
        path, val = (x.strip() for x in text.split("=", 1))
        root, _, field = path.partition(".")
        targets = {"info": (self.d, "info", None), "site": (self.d.info, "site", "building_design"),
                   "dam": (self.d, "dam", "dam"), "rules": (self.d, "rules", "costing")}
        if root not in targets or not field:
            raise ValueError("set info.<field>, site.<field>, dam.<field> or rules.<field>")
        owner, attr, feat = targets[root]
        if feat and feat not in self.features:
            raise ValueError(f"changing {root} is not part of your occupation's work")
        model = getattr(owner, attr)
        if model is None:
            from .dam import Dam
            model = Dam()
        setattr(owner, attr, _update(model, {field: _value(val.strip('"'))}, root))
        self.log.append(f"{root}.{field} = {val}")

    def c_check(self, pos, opt):
        c = validate.counts(validate.validate(self.d))
        self.log.append(f"Check: {c['errors']} errors, {c['warnings']} warnings, {c['notes']} notes (QA tab for the list)")

    def c_delete(self, pos, opt):
        d, gone = self.d, set(pos)
        before = sum(len(c) for c in (d.poles, d.homes, d.nodes, d.cables))
        d.poles = [x for x in d.poles if x.id not in gone]
        d.homes = [x for x in d.homes if x.id not in gone]
        d.nodes = [x for x in d.nodes if x.id not in gone]
        d.cables = [x for x in d.cables if x.id not in gone]
        n = before - sum(len(c) for c in (d.poles, d.homes, d.nodes, d.cables))
        if n == 0:
            raise ValueError(f"nothing to delete: no {', '.join(sorted(gone))[:200]}")
        self.log.append(f"Deleted {n}" + (f" of {len(gone)} (the others were not found)" if n < len(gone) else ""))

    # network
    def _put(self, coll: list, item):
        for i, x in enumerate(coll):
            if x.id == item.id:
                coll[i] = item
                return "updated"
        coll.append(item)
        return "added"

    def c_pole(self, pos, opt):
        if len(pos) < 2:
            raise ValueError("pole <ID> <lat,lon> [type=wood height=9 status=proposed]")
        la, lo = self.point(pos[1])
        o = {"height_m" if k == "height" else k: v for k, v in opt.items()}
        self.log.append(f"Pole {pos[0]} {self._put(self.d.poles, _update(Pole(id=pos[0], lat=la, lon=lo), o, 'pole'))}")

    def c_home(self, pos, opt):
        if len(pos) < 2:
            raise ValueError("home <ID> <lat,lon> [units=1 kind=home|mdu|business name=...]")
        la, lo = self.point(pos[1])
        self.log.append(f"Premise {pos[0]} {self._put(self.d.homes, _update(Home(id=pos[0], lat=la, lon=lo), opt, 'home'))}")

    def c_node(self, pos, opt):
        if len(pos) < 2 or pos[0].upper() not in NODE_WORDS.values():
            raise ValueError("node <POP|ENCLOSURE|PR_ENCLOSURE|JB|PON|FAT|SLACK> <ID> <lat,lon> or on=<pole> [ports=8]")
        kind, nid = pos[0].upper(), pos[1]
        on = opt.pop("on", None)
        if on is not None:
            p = self.d.pole(str(on))
            if p is None:
                raise ValueError(f"no pole '{on}'")
            n = Node(id=nid, kind=kind, lat=p.lat, lon=p.lon, pole=p.id)
        elif len(pos) >= 3:
            la, lo = self.point(pos[2])
            n = Node(id=nid, kind=kind, lat=la, lon=lo)
        else:
            raise ValueError(f"{kind} {nid}: give its position (lat,lon) or the pole it is on (on=P001)")
        self.log.append(f"{sectors.kind_label(self.d, kind)} {nid} {self._put(self.d.nodes, _update(n, opt, kind))}")

    def c_cable(self, pos, opt):
        if len(pos) < 5 or ">" not in pos:
            raise ValueError("cable <ID> <main|spur|drop> <size> <from> > <via> > ... > <to> [install=aerial status=existing]")
        cid, kind, size = pos[0], pos[1].lower(), int(_num(pos[2].rstrip("Cc"), "the cable size"))
        refs = [r for r in " ".join(pos[3:]).split(">")]
        refs = [r.strip() for r in refs if r.strip()]
        if len(refs) < 2:
            raise ValueError("a cable needs two points or more along its route")
        path = []
        for r in refs:
            la, lo, pole, node = self.feature_at(r)
            path.append(Vertex(lat=la, lon=lo, pole=pole, node=node))
        first, last = self.feature_at(refs[0])[3], self.feature_at(refs[-1])[3]
        c = Cable(id=cid, kind=kind if kind in ("main", "spur", "drop") else "spur", cores=size, from_node=first,
                  to_node=last, path=path)
        self.log.append(f"Cable {cid} ({kind} {size}) {self._put(self.d.cables, _update(c, opt, 'cable'))}")

    def c_autodesign(self, pos, opt):
        from . import autodesign
        if self.d.info.design_status == "approved":
            raise ValueError("the design is approved: return it to draft first")
        style = str(opt.pop("preset", self.d.info.design_style))
        if style not in autodesign.PRESETS:
            raise ValueError(f"preset one of {', '.join(autodesign.PRESETS)}")
        res = autodesign.auto_design(self.d, autodesign.Options(**{**autodesign.PRESETS[style], **opt}))
        self.log.append("Auto-design: " + ", ".join(f"{k} {v}" for k, v in res.items() if isinstance(v, (int, float)))[:300])

    def c_assign(self, pos, opt):
        res = calc.assign_homes(self.d, float(opt.get("max", 250)), only_unassigned=not opt.get("reassign", False))
        self.log.append(f"Assign premises: {res}"[:300])

    def c_allocate(self, pos, opt):
        res = splicing.auto_allocate(self.d)
        self.log.append(f"Allocate fibres: {res.get('connections', 0)} connections, {len(res.get('issues', []))} issues")

    # building
    def c_site(self, pos, opt):
        self.d.info.site = _update(self.d.info.site, opt, "site")
        self.log.append(f"Site: {', '.join(opt)}")

    def c_room(self, pos, opt):
        from .building import BriefRoom
        if not pos:
            raise ValueError("room <name> [number] [area each m2], e.g. room Bedroom 24 12")
        nums = [w for w in pos if w.replace(".", "", 1).isdigit()]
        name = " ".join(w for w in pos if w not in nums)
        r = BriefRoom(name=name[:60], count=int(float(nums[0])) if nums else 1, area=float(nums[1]) if len(nums) > 1 else 0.0)
        sched = [x for x in self.d.info.site.schedule if x.name != r.name] + [r]
        self.d.info.site = _update(self.d.info.site, {"schedule": [x.model_dump() for x in sched]}, "site")
        self.log.append(f"Room: {r.count} x {r.name}")

    def c_building(self, pos, opt):
        from . import building as B
        add = "add" in [p.lower() for p in pos]
        try:
            params = B.AutoParams.model_validate(opt)
        except ValidationError as e:
            er = e.errors(include_url=False)[0]
            raise ValueError(f"building {'.'.join(str(x) for x in er.get('loc', []))}: {er.get('msg')}") from None
        old = self.d.building
        if add:
            if old is None or not old.walls:
                raise ValueError("design the first block first, then 'building add ...' for a wing or tower")
            self.d.building = B.add_block(old, params)
        else:
            self.d.building = B.generate(params)
            if old is not None:
                self.d.building.origin, self.d.building.rotation, self.d.building.spec = old.origin, old.rotation, old.spec
        b = self.d.building
        self.log.append(f"Building: {len(b.levels)} levels, {len(b.walls)} walls, {len(b.openings)} doors and windows")

    def c_place(self, pos, opt):
        if not pos:
            raise ValueError("place <lat,lon> [rotation=degrees]: where the building's south-west corner goes")
        if self.d.building is None:
            raise ValueError("design the building first (building ...)")
        la, lo = self.point(pos[0])
        self.d.building.origin = [la, lo]
        if "rotation" in opt:
            self.d.building.rotation = float(opt["rotation"])
        self.log.append(f"Building placed at {la}, {lo}")

    # dam
    def _dam(self):
        from .dam import Dam
        if self.d.dam is None:
            self.d.dam = Dam()
        return self.d.dam

    def c_dam(self, pos, opt):
        self.d.dam = _update(self._dam(), opt, "dam")
        self.log.append(f"Dam: {', '.join(opt)}")

    def c_axis(self, pos, opt):
        dm = self._dam()
        if pos and pos[0].lower() == "clear":
            self.d.dam = _update(dm, {"axis": []}, "dam")
            return
        if len(pos) < 2:
            raise ValueError("axis <chainage> <ground level> [depth to firm ground]")
        row = [_num(pos[0], "chainage"), _num(pos[1], "ground level"), _num(pos[2], "depth") if len(pos) > 2 else 0.0]
        self.d.dam = _update(dm, {"axis": sorted([r for r in dm.axis if r[0] != row[0]] + [row])}, "dam")

    def c_reservoir(self, pos, opt):
        dm = self._dam()
        if pos and pos[0].lower() == "clear":
            self.d.dam = _update(dm, {"reservoir": []}, "dam")
            return
        if len(pos) < 2:
            raise ValueError("reservoir <water level> <area m2>")
        row = [_num(pos[0], "level"), _num(pos[1], "area")]
        self.d.dam = _update(dm, {"reservoir": sorted([r for r in dm.reservoir if r[0] != row[0]] + [row])}, "dam")

    def c_damaxis(self, pos, opt):
        if len(pos) < 2:
            raise ValueError("damaxis <left abutment lat,lon> <right abutment lat,lon>")
        a, b = self.point(pos[0]), self.point(pos[1])
        self.d.dam = _update(self._dam(), {"axis_start": list(a), "axis_end": list(b)}, "dam")


def run(d: Design, text: str, features: list[str] | set[str]) -> list[str]:
    """Run the script on d (changed in place); the log. ScriptError at the first bad line."""
    r = _Run(d, set(features))
    lines = text.splitlines()
    if len(lines) > 5000:
        raise ScriptError(5001, "a script can have 5000 lines at most")
    n = 0
    for i, raw in enumerate(lines, start=1):
        line = raw.split("#", 1)[0].strip() if not raw.lstrip().startswith('"') else raw.strip()
        if not line:
            continue
        try:
            words = shlex.split(line, posix=True)
        except ValueError as e:
            raise ScriptError(i, f"{e} (check the quotes)") from None
        try:
            r.run_line(words[0].lower(), words[1:])
        except ScriptError:
            raise
        except (ValueError, KeyError, TypeError) as e:
            raise ScriptError(i, str(e)) from None
        n += 1
    r.log.append(f"{n} command(s) run")
    return r.log
