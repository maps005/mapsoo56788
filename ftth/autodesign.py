"""Automatic network design from survey data.

Input: poles (existing, optionally proposed), premises with homepass counts, the existing
interception closure / POP. Output: FATs, splitters, PON closures with junction boxes, a 48C
main along the poles, 12C spurs to the buildings and new poles where spans are too long.

Rules follow the V Squared design standard (docs/calibration.md):
- indoor FATs per MDU      = ceil(HPs / FAT ports)           (24-port indoor FAT)
- 2nd-stage 1x8 splitters  = ceil(HPs x take rate / 8)       (take rate 50 %)
- small premises (SDU / shops) share outdoor 16-port FATs on poles
- 1st-stage 1x8 splitter per 8 FAT splitters, in a splice closure with a junction box
- 48C main from the interception closure to every PON / branch closure along the poles
- one 12C spur per building (or outdoor FAT) from the nearest closure on the main
The planner reviews and edits the result; nothing here is final until approved.
"""
from __future__ import annotations

import heapq
import math
import re
from collections import defaultdict
from dataclasses import dataclass

from . import calc, splicing
from .geo import LocalProjection, haversine, valid_coord
from .model import Cable, Design, Node, Pole, Splitter, Vertex


@dataclass
class Options:
    take_rate: float = 0.5
    indoor_fat_ports: int = 24
    outdoor_fat_ports: int = 16
    small_premise_max_hp: int = 4      # premises up to this many HPs share outdoor FATs
    outdoor_cluster_radius_m: float = 60.0
    max_span_m: float = 65.0           # longest aerial span between poles
    new_pole_spacing_m: float = 45.0
    drop_to_pole_m: float = 60.0       # a FAT connects to a pole within this distance, else new poles
    branch_closure_gap_m: float = 30.0  # nearest closure this much farther than the main: add a branch closure
    merge_closures_m: float = 60.0      # branch closures closer than this along the main are shared
    slack_interval_m: float = 200.0     # slack loop on the 48C at least this often (0 = none)
    extend_backbone: bool = True        # run the 48C to the project's "extend to" points
    replace: bool = True               # remove the existing proposed design first
    # design style: "per_premise" gives every homepass a FAT port (Infinity); "coverage" puts outdoor FATs on poles
    # that serve the premises around them at a take rate (Kabiria)
    fat_model: str = "per_premise"
    coverage_radius_m: float = 100.0    # coverage: premises within this distance of a FAT's pole
    coverage_take_rate: float = 0.06    # coverage: share of homepasses that need a FAT port
    fat_split: int = 8                  # 2nd-stage splitter outputs (1x8, 1x16)
    pon_split: int = 8                  # 1st-stage (PON) splitter outputs
    spur_cores: int = 12                # distribution cable size (12C, 24C)
    spur_style: str = "per_building"    # "tree": one distribution cable tree per PON through its FATs
    max_fats_per_pole: int = 1          # coverage: FATs on one pole (more demand goes to the next pole)
    big_fat_demand: float = 3.0         # coverage: larger box where the demand around the pole is this many boxes
    closure_at_fats: bool = False       # tree spurs: a closure where the distribution cable passes a FAT's pole


PRESETS = {  # company standards seen so far
    "per_premise": {},
    "coverage": {"fat_model": "coverage", "fat_split": 16, "spur_cores": 24, "spur_style": "tree",
                 "coverage_take_rate": 0.036, "coverage_radius_m": 200.0, "max_span_m": 100.0,
                 "closure_at_fats": True},
}


def pon_label(k: int) -> str:
    """A, B ... Z, AA, AB ...: PON letters that stay readable past 26 PONs."""
    out = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        out = chr(65 + r) + out
    return out


# ---------------------------------------------------------------------------
# graph helpers
# ---------------------------------------------------------------------------
def _dijkstra(adj, src, weights=None):
    dist, prev = {src: 0.0}, {}
    q = [(0.0, src)]
    while q:
        du, u = heapq.heappop(q)
        if du > dist.get(u, math.inf):
            continue
        for v, w in adj[u]:
            if weights is not None:
                w = weights.get((u, v), w)
            nd = du + w
            if nd < dist.get(v, math.inf) - 1e-9:
                dist[v], prev[v] = nd, u
                heapq.heappush(q, (nd, v))
    return dist, prev


def _path(prev, src, dst):
    out = [dst]
    while out[-1] != src:
        if out[-1] not in prev:
            return None
        out.append(prev[out[-1]])
    return out[::-1]


def _grid(items, cell_m):
    cell = cell_m / 111_000
    g = defaultdict(list)
    for x in items:
        g[(int(x.lat / cell), int(x.lon / cell))].append(x)
    return g, cell


def _neighbours(items, radius_m):
    """id -> items within radius_m (itself included), using a grid instead of comparing every pair."""
    g, cell = _grid(items, radius_m)
    out = {}
    for x in items:
        gx, gy = int(x.lat / cell), int(x.lon / cell)
        out[x.id] = [y for dx in (-1, 0, 1) for dy in (-1, 0, 1) for y in g.get((gx + dx, gy + dy), ())
                     if haversine(x.lat, x.lon, y.lat, y.lon) <= radius_m]
    return out


def _reach(poles, homes, radius_m):
    """pole id -> [(distance, home)] for homes within radius_m."""
    g, cell = _grid(homes, radius_m)
    out = {}
    for p in poles:
        gx, gy = int(p.lat / cell), int(p.lon / cell)
        out[p.id] = [(dd, h) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for h in g.get((gx + dx, gy + dy), ())
                     if (dd := haversine(p.lat, p.lon, h.lat, h.lon)) <= radius_m]
    return out


ROUTE_NOTE = re.compile(r"j[\s-]*hook|tension|upb|extension\s*arm|clamp|bracket", re.I)
FAT_NOTE = re.compile(r"(\d+)\s*(?:no\.?\s*)?fats?\b", re.I)


class Designer:
    def __init__(self, d: Design, opt: Options):
        self.d, self.o = d, opt
        self.log: list[str] = []
        self.refresh_ids()
        self.seq = defaultdict(int)

    def refresh_ids(self):
        """IDs in use (taken after clearing, so a re-run numbers its features the same way)."""
        d = self.d
        self.ids = {x.id for coll in (d.poles, d.homes, d.nodes, d.splitters, d.cables) for x in coll}

    def nid(self, fmt: str) -> str:
        while True:
            self.seq[fmt] += 1
            i = fmt.format(self.seq[fmt])
            if i not in self.ids:
                self.ids.add(i)
                return i

    def unique(self, name: str) -> str:
        i, k = name, 1
        while i in self.ids:
            k += 1
            i = f"{name} {k}"
        self.ids.add(i)
        return i

    # ---- step 0: clear previous proposed design ---------------------------
    def clear(self):
        d = self.d
        d.cables = [c for c in d.cables if c.status == "existing"]
        keep = {n.id for n in d.nodes if n.status == "existing"}
        d.nodes = [n for n in d.nodes if n.id in keep]
        d.splitters, d.connections = [], []
        d.poles = [p for p in d.poles if p.status == "existing" or not p.notes.startswith("auto")]
        for h in d.homes:
            h.fat, h.extra_fats = None, []
        self.refresh_ids()

    # ---- step 1: pole graph ------------------------------------------------
    def build_graph(self):
        d = self.d
        self.poles = {p.id: p for p in d.poles if valid_coord(p.lat, p.lon)}
        self.adj = defaultdict(list)
        ps = list(self.poles.values())
        cell = 0.0007  # ~75 m grid for neighbour search
        grid = defaultdict(list)
        for p in ps:
            grid[(int(p.lat / cell), int(p.lon / cell))].append(p)
        # surveyed pole lines: consecutive poles of existing cables, and poles the survey gave accessory notes
        line = set()
        for c in d.cables:
            if c.status == "existing":
                ps_ = [v.pole for v in c.path if v.pole in self.poles]
                line |= {frozenset(e) for e in zip(ps_, ps_[1:]) if e[0] != e[1]}
        noted = {p.id for p in ps if ROUTE_NOTE.search(p.notes or "")}
        proj = LocalProjection.for_points([(p.lat, p.lon) for p in ps] or [(0, 0)])
        xy = {p.id: proj.xy(p.lat, p.lon) for p in ps}
        for p in ps:
            gx, gy = int(p.lat / cell), int(p.lon / cell)
            near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in grid[(gx + dx, gy + dy)]]
            for q in near:
                if q.id <= p.id:
                    continue
                dist = haversine(p.lat, p.lon, q.lat, q.lon)
                if not 1 < dist <= self.o.max_span_m:
                    continue
                if frozenset((p.id, q.id)) not in line and self._passes_pole(xy, p.id, q.id, near, self.o.max_span_m):
                    continue  # a cable may not fly past a pole on its line: it goes pole to pole
                w = dist * (1.0 if p.status == q.status == "existing" else 1.15)
                if frozenset((p.id, q.id)) in line:
                    w *= 0.6   # follow the surveyed line of the existing network
                elif p.id in noted and q.id in noted:
                    w *= 0.75  # both poles were surveyed for accessories: the intended route
                elif p.id in noted or q.id in noted:
                    w *= 0.9
                self.adj[p.id].append((q.id, w))
                self.adj[q.id].append((p.id, w))
        # spans that already carry an existing cable are usable whatever their length (they exist on the ground)
        have = {frozenset((a, b)) for a, nb in self.adj.items() for b, _ in nb}
        for e in line - have:
            a, b = tuple(e)
            w = haversine(self.poles[a].lat, self.poles[a].lon, self.poles[b].lat, self.poles[b].lon) * 0.6
            self.adj[a].append((b, w))
            self.adj[b].append((a, w))

    @staticmethod
    def _passes_pole(xy, a, b, others, max_span: float, tol_m: float = 4.0) -> bool:
        """True when the straight span a-b passes within tol_m of another pole between its ends that the cable
        can use instead (both hops within the maximum span)."""
        (ax, ay), (bx, by) = xy[a], xy[b]
        L2 = (bx - ax) ** 2 + (by - ay) ** 2
        if L2 <= 0:
            return False
        for r in others:
            if r.id in (a, b) or r.id not in xy:
                continue
            rx, ry = xy[r.id]
            t = ((rx - ax) * (bx - ax) + (ry - ay) * (by - ay)) / L2
            if 0.05 < t < 0.95:
                px, py = ax + t * (bx - ax), ay + t * (by - ay)
                hops = math.dist((ax, ay), (rx, ry)) <= max_span and math.dist((rx, ry), (bx, by)) <= max_span
                if hops and (rx - px) ** 2 + (ry - py) ** 2 <= max(tol_m, 0.08 * math.sqrt(L2)) ** 2:
                    return True
        return False

    def add_pole(self, lat, lon) -> Pole:
        p = Pole(id=self.nid("AUTO PL-{:02d}"), lat=lat, lon=lon, status="proposed", type="8m wooden",
                 notes="auto: new pole (span too long)")
        self.d.poles.append(p)
        self.poles[p.id] = p
        for q in list(self.poles.values()):
            if q.id != p.id:
                dist = haversine(lat, lon, q.lat, q.lon)
                if 1 < dist <= self.o.max_span_m:
                    self.adj[p.id].append((q.id, dist * 1.15))
                    self.adj[q.id].append((p.id, dist * 1.15))
        return p

    def connect_point(self, lat, lon) -> str:
        """Pole that serves a location; plants new poles towards the network if none is close enough."""
        near = min(((haversine(lat, lon, p.lat, p.lon), p) for p in self.poles.values()), default=None,
                   key=lambda t: t[0])
        if near and near[0] <= self.o.drop_to_pole_m:
            return near[1].id
        if near is None:
            return self.add_pole(lat, lon).id
        # walk from the nearest pole towards the location, planting poles every new_pole_spacing_m
        dist, start = near
        steps = max(1, math.ceil((dist - self.o.drop_to_pole_m * 0.5) / self.o.new_pole_spacing_m))
        last = start
        for k in range(1, steps + 1):
            t = min(1.0, k * self.o.new_pole_spacing_m / dist)
            last = self.add_pole(start.lat + t * (lat - start.lat), start.lon + t * (lon - start.lon))
        return last.id

    def ensure_reachable(self, root_pole: str, targets: list[str]):
        """Bridge disconnected parts of the pole network with new poles."""
        for _ in range(50):
            dist, _ = _dijkstra(self.adj, root_pole)
            missing = [t for t in targets if t not in dist]
            if not missing:
                return
            t = self.poles[missing[0]]
            reach = [self.poles[p] for p in dist if p in self.poles]
            best = min(reach, key=lambda p: haversine(p.lat, p.lon, t.lat, t.lon))
            gap = haversine(best.lat, best.lon, t.lat, t.lon)
            n = max(1, math.ceil(gap / self.o.new_pole_spacing_m) - 1)
            for k in range(1, n + 1):
                f = k / (n + 1)
                self.add_pole(best.lat + f * (t.lat - best.lat), best.lon + f * (t.lon - best.lon))

    # ---- step 2: FATs and splitters ---------------------------------------
    def _add_fat_splitters(self):
        o = self.o
        for fid, n in self.fat_splitters.items():
            for _ in range(n):
                self.d.splitters.append(Splitter(id=self.nid(f"1X{o.fat_split} SPL {{:02d}}"), node=fid, stage=2,
                                                 outputs=o.fat_split))

    def place_fats_coverage(self):
        """Outdoor FATs on poles, each serving the premises within coverage_radius_m (greedy set cover: the pole
        that serves the most still-unserved demand first). Ports are sized from the take rate (16 or 24)."""
        d, o = self.d, self.o
        homes = [h for h in d.homes if valid_coord(h.lat, h.lon) and h.units > 0]
        zero = [h for h in d.homes if h.units == 0]
        self.fat_splitters = {}
        # a standard box (outdoor_fat_ports, one splitter) where the demand fits, else the larger box
        # (indoor_fat_ports, e.g. 24P with a second splitter) instead of stacking FATs on the pole
        cap_small = o.outdoor_fat_ports
        cap_big = max(o.indoor_fat_ports, o.outdoor_fat_ports)
        on_pole: dict[str, int] = defaultdict(int)
        cap_fill = min(cap_small, o.fat_split)  # subscribers one FAT serves: one 2nd-stage splitter
        demand = {h.id: h.units * o.coverage_take_rate for h in homes}
        reach = _reach(list(self.poles.values()), homes, o.coverage_radius_m)  # pole id -> [(dist, home)]
        open_ = {h.id for h in homes}

        def gain(pid):
            g, n = 0.0, 0
            for _, h in reach[pid]:
                if h.id in open_:
                    g += demand[h.id]
                    n += 1
            return min(g, cap_fill) + 1e-3 * n, n
        heap = [(-gain(pid)[0], pid) for pid in reach if reach[pid]]
        heapq.heapify(heap)
        made = 0

        def make_fat(pid, members, wanted=0.0):
            nonlocal made
            p = self.poles[pid]
            need = sum(demand[h.id] for h in members)
            # one splitter's worth of subscribers; a dense pole (more demand around it than one box takes) gets the
            # larger box so later take-up has spare ports
            f = Node(id=self.nid("PR OTD FAT-{:02d}"), kind="FAT", lat=p.lat, lon=p.lon, pole=pid, status="proposed",
                     ports=cap_small if max(need, wanted) <= o.big_fat_demand * cap_small else cap_big,
                     notes=f"Outdoor FAT: {len(members)} premises, {sum(h.units for h in members)} HPs")
            d.nodes.append(f)
            for h in members:
                h.fat, h.extra_fats = f.id, []
                open_.discard(h.id)
            self.fat_splitters[f.id] = max(1, math.ceil(need / o.fat_split - 1e-9))
            on_pole[pid] += 1
            made += 1

        while heap and open_:
            neg, pid = heapq.heappop(heap)
            if o.max_fats_per_pole and on_pole[pid] >= o.max_fats_per_pole:
                continue
            g, n = gain(pid)
            if n == 0:
                continue
            if heap and -heap[0][0] > g + 1e-9:  # stale: someone else took part of this pole's premises
                heapq.heappush(heap, (-g, pid))
                continue
            members, need = [], 0.0
            wanted = sum(demand[h.id] for _, h in reach[pid] if h.id in open_)
            for _, h in sorted(reach[pid], key=lambda t: t[0]):
                if h.id in open_ and (not members or need + demand[h.id] <= cap_fill):
                    members.append(h)
                    need += demand[h.id]
            make_fat(pid, members, wanted)
            if any(h.id in open_ for _, h in reach[pid]) and (not o.max_fats_per_pole
                                                              or on_pole[pid] < o.max_fats_per_pole):
                heapq.heappush(heap, (-gain(pid)[0], pid))  # the same pole may take a second FAT
        for h in [x for x in homes if x.id in open_]:  # out of reach of every pole: plant poles towards it
            if h.id not in open_:
                continue
            pid = self.connect_point(h.lat, h.lon)
            near = sorted(((haversine(h.lat, h.lon, x.lat, x.lon), x) for x in homes if x.id in open_
                           and haversine(self.poles[pid].lat, self.poles[pid].lon, x.lat, x.lon) <= o.coverage_radius_m),
                          key=lambda t: t[0])
            members, need = [], 0.0
            for _, x in near:
                if not members or need + demand[x.id] <= cap_fill:
                    members.append(x)
                    need += demand[x.id]
            make_fat(pid, members or [h])
        if zero:
            self.log.append(f"{len(zero)} premises with 0 homepasses left unassigned")
        self._add_fat_splitters()
        self.log.append(f"{made} outdoor FATs covering {len(homes)} premises within {o.coverage_radius_m:g} m "
                        f"({o.coverage_take_rate:.0%} take rate), {sum(self.fat_splitters.values())} 1x{o.fat_split} splitters")

    def place_fats(self):
        if self.o.fat_model == "coverage":
            return self.place_fats_coverage()
        d, o = self.d, self.o
        homes = [h for h in d.homes if valid_coord(h.lat, h.lon)]
        big = [h for h in homes if h.units > o.small_premise_max_hp]
        small = [h for h in homes if 0 < h.units <= o.small_premise_max_hp]
        zero = [h for h in homes if h.units == 0]
        self.fat_splitters: dict[str, int] = {}
        proj = LocalProjection.for_points([(h.lat, h.lon) for h in homes] or [(0, 0)])
        for h in sorted(big, key=lambda h: h.id):
            n_fat = max(1, math.ceil(h.units / o.indoor_fat_ports))
            asked = [int(m) for t in (h.notes, h.access_notes, h.name) for m in FAT_NOTE.findall(t or "")]
            if asked and 1 <= max(asked) <= 10:  # the survey asks for more FATs (e.g. "2 FATs on 2nd floor")
                n_fat = max(n_fat, max(asked))
            n_spl = max(n_fat, math.ceil(h.units * o.take_rate / o.fat_split))  # at least one splitter per FAT
            fats = []
            for k in range(n_fat):
                off = (k - (n_fat - 1) / 2) * 8 / 111_320  # a few metres apart inside the building
                f = Node(id=self.nid("PR IND FAT-{:02d}"), kind="FAT", lat=h.lat, lon=h.lon + off,
                         ports=o.indoor_fat_ports, status="proposed", notes=f"Indoor FAT for {h.id}")
                d.nodes.append(f)
                fats.append(f)
            for k in range(n_spl):
                self.fat_splitters[fats[k % n_fat].id] = self.fat_splitters.get(fats[k % n_fat].id, 0) + 1
            h.fat, h.extra_fats = fats[0].id, [f.id for f in fats[1:]]
        # small premises: greedy clusters around the premise with the most neighbours (neighbour lists
        # come from a grid, so large areas stay fast)
        left = list(small)
        nb = _neighbours(left, o.outdoor_cluster_radius_m)
        alive = {h.id for h in left}
        count = {h.id: len(nb[h.id]) for h in left}
        while left:
            seed = max(left, key=lambda h: (count[h.id], h.id))
            group = sorted((x for x in nb[seed.id] if x.id in alive),
                           key=lambda x: haversine(seed.lat, seed.lon, x.lat, x.lon))
            chosen, hp = [], 0
            for x in group:
                if hp + x.units <= o.outdoor_fat_ports:
                    chosen.append(x)
                    hp += x.units
            clat = sum(x.lat for x in chosen) / len(chosen)
            clon = sum(x.lon for x in chosen) / len(chosen)
            pole = min(self.poles.values(), key=lambda p: haversine(clat, clon, p.lat, p.lon), default=None)
            on_pole = pole is not None and haversine(clat, clon, pole.lat, pole.lon) <= o.outdoor_cluster_radius_m
            f = Node(id=self.nid("PR OTD FAT-{:02d}"), kind="FAT", ports=o.outdoor_fat_ports, status="proposed",
                     lat=pole.lat if on_pole else clat, lon=pole.lon if on_pole else clon,
                     pole=pole.id if on_pole else None, notes="Outdoor FAT")
            d.nodes.append(f)
            self.fat_splitters[f.id] = max(1, math.ceil(hp * o.take_rate / o.fat_split))
            for x in chosen:
                x.fat = f.id
                left.remove(x)
                alive.discard(x.id)
                for y in nb[x.id]:
                    count[y.id] -= 1
        # premises without homepasses get no FAT: assign them when the survey gives a count
        if zero:
            self.log.append(f"{len(zero)} premises with 0 homepasses left unassigned")
        self._add_fat_splitters()
        self.log.append(f"{sum(1 for n in d.nodes if n.kind == 'FAT')} FATs, "
                        f"{sum(self.fat_splitters.values())} 2nd-stage splitters")

    # ---- step 3: PON groups, closures, main and spurs ---------------------
    def route(self):
        d, o = self.d, self.o
        roots = splicing.feed_roots(d)
        if not roots:
            raise ValueError("No interception point: add the existing closure (or POP) the network starts from")
        root_node_at: dict[str, Node] = {}
        for r in roots:
            lat, lon = d.node_position(r)
            rp = r.pole if r.pole in self.poles else self.connect_point(lat, lon)
            root_node_at.setdefault(rp, r)
        # one virtual source linked to every interception pole: shortest paths start at the nearest interception
        root_pole = "__ROOT__"
        self.adj[root_pole] = [(rp, 0.0) for rp in root_node_at]
        fats = [n for n in d.nodes if n.kind == "FAT" and n.status == "proposed"]
        fat_pole = {f.id: (f.pole if f.pole in self.poles else self.connect_point(f.lat, f.lon)) for f in fats}
        self.ensure_reachable(root_pole, list(set(fat_pole.values())))
        dist_root, prev_root = _dijkstra(self.adj, root_pole)

        # PON groups: capacity-limited clusters of FAT splitters (8 per 1x8 primary), by graph distance
        n_groups = max(1, math.ceil(sum(self.fat_splitters.values()) / o.pon_split))
        order = sorted(fats, key=lambda f: dist_root.get(fat_pole[f.id], math.inf))
        cache = {}

        def gdist(a, b):
            if a not in cache:
                cache[a] = _dijkstra(self.adj, a)[0]
            return cache[a].get(b, math.inf)

        # seeds: spread out along the network (farthest-point), then capacity-limited assignment
        seeds = [order[-1]]
        while len(seeds) < n_groups:
            seeds.append(max(order, key=lambda f: min(gdist(fat_pole[s.id], fat_pole[f.id]) for s in seeds)))
        groups = {s.id: [] for s in seeds}
        load = defaultdict(int)
        pairs = sorted(((gdist(fat_pole[s.id], fat_pole[f.id]), s.id, f) for s in seeds for f in fats),
                       key=lambda t: t[0])
        placed = set()
        for _, sid, f in pairs:
            if f.id in placed or load[sid] + self.fat_splitters.get(f.id, 1) > o.pon_split:
                continue
            groups[sid].append(f)
            load[sid] += self.fat_splitters.get(f.id, 1)
            placed.add(f.id)
        for f in fats:  # anything left over (capacity) goes to the least loaded group
            if f.id not in placed:
                sid = min(groups, key=lambda g: load[g])
                groups[sid].append(f)
                load[sid] += self.fat_splitters.get(f.id, 1)

        # PON closure site: pole minimising (distance to its FATs) + 0.3 x (distance from the interception)
        cand = [p for p in self.poles if p in dist_root]
        pon_sites = []
        for k, (sid, members) in enumerate(sorted(groups.items()), start=0):
            if not members:
                continue
            mp = {fat_pole[f.id] for f in members}
            best = min(cand, key=lambda p: sum(gdist(p, m) for m in mp) + 0.3 * dist_root[p])
            pon_sites.append((best, members, pon_label(k)))

        # 48C main: dig-once shortest paths from the interception to every PON closure
        weights = {}
        tree_edges = set()
        feeds: dict[str, int] = defaultdict(int)  # interception pole -> PONs it feeds
        for site, _, _ in sorted(pon_sites, key=lambda t: dist_root[t[0]]):
            _, prev = _dijkstra(self.adj, root_pole, weights)
            path = _path(prev, root_pole, site)[1:]  # drop the virtual source
            feeds[path[0]] += 1
            for a, b in zip(path, path[1:]):
                tree_edges.add(frozenset((a, b)))
                weights[(a, b)] = weights[(b, a)] = 0.001
        ext_poles = []
        if o.extend_backbone:
            for lat_, lon_ in d.info.extend_to:
                tp = self.connect_point(lat_, lon_)
                self.ensure_reachable(root_pole, [tp])
                _, prev = _dijkstra(self.adj, root_pole, weights)
                path = _path(prev, root_pole, tp)
                path = path[1:] if path else None
                if path:
                    ext_poles.append(tp)
                    for a, b in zip(path, path[1:]):
                        tree_edges.add(frozenset((a, b)))
                        weights[(a, b)] = weights[(b, a)] = 0.001
            dist_root, prev_root = _dijkstra(self.adj, root_pole)
        tree_adj = defaultdict(set)
        for e in tree_edges:
            a, b = tuple(e)
            tree_adj[a].add(b)
            tree_adj[b].add(a)

        closures: dict[str, Node] = {}  # pole -> closure

        def closure_at(pole_id, why) -> Node:
            if pole_id in closures:
                return closures[pole_id]
            p = self.poles[pole_id]
            n = Node(id=self.nid("PR SC-{:02d}"), kind="ENCLOSURE", lat=p.lat, lon=p.lon, pole=pole_id,
                     status="proposed", notes=why)
            d.nodes.append(n)
            closures[pole_id] = n
            return n

        for rp, n in feeds.items():  # feeder capacity: one 48C core and one OLT port per PON
            r = root_node_at[rp]
            limit = min(48, r.ports or 48)
            if n > limit:
                self.log.append(f"WARNING: {n} PONs are fed from {r.id}, but its 48C feeder / OLT has {limit} "
                                f"- add another interception point or a larger feeder")
        for site, members, letter in pon_sites:
            sc = closure_at(site, f"PON {letter} (1st-stage splitter)")
            d.splitters.append(Splitter(id=self.unique(f"PR 1X{o.pon_split} SPL {letter}"), node=sc.id, stage=1,
                                        outputs=o.pon_split))
            p = self.poles[site]
            d.nodes.append(Node(id=self.nid("PR JB-{:02d}"), kind="JB", lat=p.lat, lon=p.lon, pole=site,
                                status="proposed", notes=f"PON {letter}"))

        # spurs: each building / outdoor FAT from the nearest closure on the main (new branch closure if far)
        tree_poles = set(tree_adj) | set(root_node_at)
        by_building = defaultdict(list)
        for f in fats:
            key = f.notes.replace("Indoor FAT for ", "") if f.notes.startswith("Indoor FAT for ") else f.id
            by_building[key].append(f)
        spur_plan = []
        branch_sites: list[str] = []
        # nearest buildings first, so later ones can share their branch closures
        items = sorted(by_building.items(), key=lambda kv: dist_root.get(fat_pole[kv[1][0].id], math.inf))
        for key, fs in (items if o.spur_style != "tree" else []):
            fp = fat_pole[fs[0].id]
            dist_f, prev_f = _dijkstra(self.adj, fp)
            on_main = min((p for p in tree_poles if p in dist_f), key=lambda p: dist_f[p])
            sites = list(closures) + branch_sites
            near_closure = min((p for p in sites if p in dist_f), key=lambda p: dist_f[p], default=None)
            if near_closure is not None and dist_f[near_closure] <= dist_f[on_main] + o.branch_closure_gap_m:
                start = near_closure
            else:
                share = [b for b in branch_sites if gdist(on_main, b) <= o.merge_closures_m]
                start = min(share, key=lambda b: dist_f.get(b, math.inf)) if share else on_main
                if start not in branch_sites:
                    branch_sites.append(start)
            spur_plan.append((start, fs, _path(prev_f, fp, start)[::-1]))
        for start, fs, path in spur_plan:
            if start not in closures:
                closure_at(start, "Branch closure")

        # build 48C cables: split the main tree at closures and branch points
        def vtx(pole_id, node=None):
            p = self.poles[pole_id]
            return Vertex(lat=p.lat, lon=p.lon, pole=pole_id, node=node.id if node else None)

        # cables run through closures (passing splices) and split only where the main branches;
        # a 48C branch is spliced, so every branch point gets a closure
        for p, nb in tree_adj.items():
            if len(nb) >= 3 and p not in root_node_at:
                closure_at(p, "Branch closure (48C split)")
        stops = set(root_node_at) | {p for p, nb in tree_adj.items() if len(nb) != 2}
        slack_nodes = {}
        for tp in ext_poles:  # slack loop at each backbone end, ready for the next phase
            p = self.poles[tp]
            slack_nodes[tp] = Node(id=self.nid("PR SLACK {:02d}"), kind="SLACK", lat=p.lat, lon=p.lon,
                                   status="proposed", notes="Backbone end (future extension)")
            d.nodes.append(slack_nodes[tp])
        seen_edges = set()
        n48 = 0
        for s in sorted(stops):
            for nb in sorted(tree_adj[s]):
                if frozenset((s, nb)) in seen_edges:
                    continue
                seq = [s, nb]
                seen_edges.add(frozenset((s, nb)))
                while seq[-1] not in stops:
                    nxt = [x for x in tree_adj[seq[-1]] if frozenset((seq[-1], x)) not in seen_edges]
                    if not nxt:
                        break
                    seen_edges.add(frozenset((seq[-1], nxt[0])))
                    seq.append(nxt[0])
                def at(p):
                    return root_node_at.get(p) or closures.get(p) or slack_nodes.get(p)
                if dist_root.get(seq[0], 0) > dist_root.get(seq[-1], 0):  # run outward from the interception
                    seq = seq[::-1]
                a_node, b_node = at(seq[0]), at(seq[-1])
                path = [vtx(seq[0], a_node)] + [vtx(p, closures.get(p)) for p in seq[1:-1]] + [vtx(seq[-1], b_node)]
                if o.slack_interval_m:  # slack loops along long runs
                    run_m = 0.0
                    for k in range(1, len(path) - 1):
                        u, v = path[k - 1], path[k]
                        run_m += haversine(u.lat, u.lon, v.lat, v.lon)
                        if v.node:
                            run_m = 0.0
                        elif run_m >= o.slack_interval_m:
                            sl = Node(id=self.nid("PR SLACK {:02d}"), kind="SLACK", lat=v.lat, lon=v.lon,
                                      status="proposed", notes="Slack loop on the 48C")
                            d.nodes.append(sl)
                            v.node = sl.id
                            run_m = 0.0
                n48 += 1
                d.cables.append(Cable(id=self.nid("48C ADSS FOC {:02d}"), kind="main", cores=48, status="proposed",
                                      from_node=a_node.id if a_node else None, to_node=b_node.id if b_node else None,
                                      path=path, notes="auto"))
        # spurs: closure -> poles -> FAT(s) of the building (daisy-chained inside)
        tag = f"{o.spur_cores}C"
        for start, fs, path in spur_plan:
            sc = closures[start]
            verts = [vtx(start, sc)] + [vtx(p) for p in path[1:]]
            for f in fs:
                verts.append(Vertex(lat=f.lat, lon=f.lon, node=f.id, pole=f.pole))
            d.cables.append(Cable(id=self.nid(tag + " SPUR {:02d}"), kind="spur", cores=o.spur_cores, status="proposed",
                                  from_node=sc.id, to_node=fs[-1].id, path=verts, notes="auto"))
        n_spur = len(spur_plan)
        if o.spur_style == "tree":  # one distribution tree per PON, through its FATs, closures where it branches
            n_spur = self._spur_trees(pon_sites, fat_pole, closures, closure_at, vtx)
        self.log.append(f"{len(pon_sites)} PON closures, {len(closures)} closures in total, {n48} 48C cables, "
                        f"{n_spur} {tag} spurs, {sum(1 for p in d.poles if p.notes.startswith('auto'))} new poles")

    def _spur_trees(self, pon_sites, fat_pole, closures, closure_at, vtx) -> int:
        d, o = self.d, self.o
        fat_at = defaultdict(list)
        for f in d.nodes:
            if f.kind == "FAT" and f.id in fat_pole:
                fat_at[fat_pole[f.id]].append(f)
        tag, n = f"{o.spur_cores}C", 0
        for site, members, letter in pon_sites:
            weights, edges = {}, set()
            targets = sorted({fat_pole[f.id] for f in members} - {site})
            dist0 = _dijkstra(self.adj, site)[0]
            for t in sorted(targets, key=lambda t: dist0.get(t, math.inf)):  # dig once: reuse earlier legs
                _, prev = _dijkstra(self.adj, site, weights)
                path = _path(prev, site, t)
                if not path:
                    continue
                for a, b in zip(path, path[1:]):
                    edges.add(frozenset((a, b)))
                    weights[(a, b)] = weights[(b, a)] = 0.001
            tadj = defaultdict(set)
            for e in edges:
                a, b = tuple(e)
                tadj[a].add(b)
                tadj[b].add(a)
            through = set()
            for p_, nb in tadj.items():  # a branching distribution cable is spliced in a closure
                if len(nb) >= 3 and p_ != site:
                    closure_at(p_, f"Branch closure ({tag} split, PON {letter})")
                elif o.closure_at_fats and len(nb) == 2 and p_ != site and fat_at.get(p_):
                    closure_at(p_, f"FAT closure ({tag} spliced through to {fat_at[p_][0].id}, PON {letter})")
                    through.add(p_)
            stops = {site} | {p_ for p_, nb in tadj.items() if len(nb) != 2}  # cables pass FAT closures (mid-span splice)
            seen = set()
            for s0 in sorted(stops):
                for nb0 in sorted(tadj[s0]):
                    if frozenset((s0, nb0)) in seen:
                        continue
                    seq = [s0, nb0]
                    seen.add(frozenset((s0, nb0)))
                    while seq[-1] not in stops:
                        nxt = [x for x in tadj[seq[-1]] if frozenset((seq[-1], x)) not in seen]
                        if not nxt:
                            break
                        seen.add(frozenset((seq[-1], nxt[0])))
                        seq.append(nxt[0])
                    if dist0.get(seq[0], 0) > dist0.get(seq[-1], 0):
                        seq = seq[::-1]

                    def at(p_):
                        return closures.get(p_) or (fat_at[p_][0] if fat_at.get(p_) else None)
                    path = [vtx(p_, at(p_)) for p_ in seq]
                    a_node, b_node = at(seq[0]), at(seq[-1])
                    d.cables.append(Cable(id=self.nid(tag + " SPUR {:02d}"), kind="spur", cores=o.spur_cores,
                                          status="proposed", from_node=a_node.id if a_node else None,
                                          to_node=b_node.id if b_node else None, path=path, notes=f"auto, PON {letter}"))
                    n += 1
        return n


def auto_design(d: Design, opt: Options | None = None) -> dict:
    opt = opt or Options()
    des = Designer(d, opt)
    if opt.replace:
        des.clear()
    d.rules.fat_load_take_rate = opt.coverage_take_rate if opt.fat_model == "coverage" else 1.0
    des.build_graph()
    des.place_fats()
    des.route()
    used = {v.pole for c in d.cables for v in c.path} | {n.pole for n in d.nodes}
    unused = [p.id for p in d.poles if p.status == "proposed" and p.notes.startswith("auto") and p.id not in used]
    if unused:  # poles planted while searching for routes that no cable ended up using
        d.poles = [p for p in d.poles if p.id not in set(unused)]
        des.log.append(f"{len(unused)} unused new poles removed")
    assign = calc.assign_homes(d, 300)  # premises not placed above (if any)
    alloc = splicing.auto_allocate(d)
    return {"log": des.log, "unassigned": assign["unassigned"], "allocation_issues": alloc["issues"]}
