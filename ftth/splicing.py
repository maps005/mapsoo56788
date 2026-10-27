"""Fibre core allocation, splice connections, tracing and checks.

Topology: OLT port at the POP -> feeder cores -> 1st-stage splitter at a PON node
-> distribution cores -> 2nd-stage splitter at a FAT -> customer drops.
"""
from __future__ import annotations

from collections import defaultdict, deque

from .model import Cable, Connection, Design, End, Node, Splitter, next_id

# TIA/EIA-598 fibre and tube colour code
COLOURS = [("Blue", "#1f5fd1"), ("Orange", "#f28c28"), ("Green", "#2e9d43"), ("Brown", "#8b5a2b"),
           ("Slate", "#7a8793"), ("White", "#f4f4f4"), ("Red", "#d62828"), ("Black", "#111111"),
           ("Yellow", "#f2d21b"), ("Violet", "#8e44ad"), ("Rose", "#f48fb1"), ("Aqua", "#22c3c9")]


def core_colour(n: int, per_tube: int = 12) -> dict:
    tube, fibre = (n - 1) // per_tube, (n - 1) % per_tube
    return {"tube": tube + 1, "tube_colour": COLOURS[tube % 12][0], "tube_hex": COLOURS[tube % 12][1],
            "fibre_colour": COLOURS[fibre][0], "fibre_hex": COLOURS[fibre][1]}


def _key(e: End) -> tuple:
    return (e.kind, e.ref, e.n)


def end_label(d: Design, e: End) -> str:
    if e.kind == "cable":
        cab = d.cable(e.ref)
        if cab is None or not 1 <= e.n <= cab.cores:
            return f"{e.ref} core {e.n} (no such core)"
        c = core_colour(e.n)
        return f"{e.ref} core {e.n} ({c['tube_colour']}/{c['fibre_colour']})"
    if e.kind == "splitter_in":
        return f"{e.ref} IN"
    if e.kind == "splitter_out":
        return f"{e.ref} OUT {e.n}"
    return f"OLT/feed {e.ref} port {e.n}"


SITE = ""  # pseudo cable id: equipment at the same site (same pole / within SITE_M) spliced with a patch, no core
SITE_M = 3.0


def _pole_equipment(d: Design) -> dict[str, list[str]]:
    """Pole id -> equipment mounted on it (slack loops excluded), closures first."""
    order = {"POP": 0, "ENCLOSURE": 1, "PR_ENCLOSURE": 1, "JB": 2, "PON": 2, "FAT": 3}
    out: dict[str, list[str]] = defaultdict(list)
    for n in sorted(d.nodes, key=lambda n: (order.get(n.kind, 9), n.id)):
        if n.pole and n.kind != "SLACK":
            out[n.pole].append(n.id)
    return out


def _vertex_nodes(d: Design, c: Cable, pole_eq: dict[str, list[str]]) -> list[str]:
    """Equipment along a cable: a vertex's own node, else the first equipment mounted on the vertex's pole."""
    seq = []
    for v in c.path:
        nid = v.node if v.node and d.node(v.node) and d.node(v.node).kind != "SLACK" else None
        if nid is None and v.pole and pole_eq.get(v.pole):
            nid = pole_eq[v.pole][0]
        if nid and (not seq or seq[-1] != nid):
            seq.append(nid)
    return seq


def site_links(d: Design) -> list[tuple[str, str]]:
    """Pairs of equipment at the same site: mounted on the same pole, or within SITE_M metres."""
    from .geo import haversine, valid_coord
    pairs, eq = set(), [n for n in d.nodes if n.kind != "SLACK"]
    for ids in _pole_equipment(d).values():
        pairs.update((a, b) for i, a in enumerate(ids) for b in ids[i + 1:])
    pos = {n.id: d.node_position(n) for n in eq}
    pos = {k: v for k, v in pos.items() if valid_coord(*v)}
    cell = defaultdict(list)
    for k, (la, lo) in pos.items():
        cell[(round(la * 2e4), round(lo * 2e4))].append(k)  # ~5 m grid
    for (gx, gy), ids in cell.items():
        near = [x for dx in (-1, 0, 1) for dy in (-1, 0, 1) for x in cell.get((gx + dx, gy + dy), [])]
        for a in ids:
            for b in near:
                if a < b and haversine(*pos[a], *pos[b]) <= SITE_M:
                    pairs.add((a, b))
    return sorted(pairs)


def site_groups(d: Design):
    """Function: equipment id -> id of its site (equipment on one pole or within SITE_M share a site)."""
    parent = {n.id: n.id for n in d.nodes}

    def site(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x
    for a, b in site_links(d):
        parent[site(a)] = site(b)
    return site


def site_splitters(d: Design, fat_id: str, site=None) -> list[Splitter]:
    """2nd-stage splitters that serve a FAT: its own, else those in other equipment at the same site
    (e.g. a 1x16 in the splice closure on the FAT's pole)."""
    own = [s for s in d.splitters if s.node == fat_id and s.stage == 2]
    if own:
        return own
    site = site or site_groups(d)
    here = site(fat_id)
    return [s for s in d.splitters if s.stage == 2 and s.node != fat_id and site(s.node) == here
            and (d.node(s.node) or Node(id="", kind="FAT")).kind != "FAT"]


def cable_nodes(d: Design, cable_id: str) -> set[str]:
    c = d.cable(cable_id)
    if not c:
        return set()
    s = {v.node for v in c.path if v.node}
    s.update(x for x in (c.from_node, c.to_node) if x)
    s.update(_vertex_nodes(d, c, _pole_equipment(d)))
    return s


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------
def _adjacency(d: Design, kinds: set[str] | None = None) -> dict[str, list[tuple[str, str]]]:
    """Node graph: consecutive equipment sites along each cable are linked by that cable."""
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    pole_eq = _pole_equipment(d)
    for c in d.cables:
        if c.kind == "drop" or (kinds and c.kind not in kinds):
            continue
        seq = _vertex_nodes(d, c, pole_eq)
        if c.from_node and (not seq or seq[0] != c.from_node):
            seq.insert(0, c.from_node)
        if c.to_node and (not seq or seq[-1] != c.to_node):
            seq.append(c.to_node)
        for a, b in zip(seq, seq[1:]):
            if a != b:
                adj[a].append((b, c.id))
                adj[b].append((a, c.id))
    for a, b in site_links(d):  # closure and FAT / JB on the same pole: patched inside the site
        adj[a].append((b, SITE))
        adj[b].append((a, SITE))
    return adj


def _paths_from(d: Design, root: str, kinds: set[str] | None = None, adj=None) -> dict[str, list[tuple[str, str]]]:
    """BFS: node -> list of (cable, node_reached) hops from root (adj: a prebuilt graph, to avoid rebuilding it)."""
    adj = adj if adj is not None else _adjacency(d, kinds)
    paths = {root: []}
    q = deque([root])
    while q:
        u = q.popleft()
        for v, cid in sorted(adj[u]):
            if v not in paths:
                paths[v] = paths[u] + [(cid, v)]
                q.append(v)
    return paths


def feed_root(d: Design, skip: frozenset = frozenset()):
    """Network starting point: the POP (or, without one, the existing interception closure) that reaches most of the network."""
    chosen = d.node(d.info.interception_node) if d.info.interception_node else None
    if chosen is not None:
        return chosen
    pops = [n for n in d.nodes if n.kind == "POP" and n.id not in skip]
    cands = pops or [n for n in d.nodes if n.kind in ("ENCLOSURE", "PR_ENCLOSURE") and n.status == "existing"
                     and n.id not in skip]
    if not cands:
        return None
    mains = {c.from_node for c in d.cables if c.kind == "main" and c.status == "proposed"}
    return max(cands, key=lambda n: (len(_paths_from(d, n.id)), n.id in mains, [-ord(ch) for ch in n.id]))


def feed_roots(d: Design) -> list[Node]:
    """Every interception point: the main one (feed_root) and any further ones listed in the project info."""
    first = feed_root(d, frozenset(d.info.interception_nodes)) or feed_root(d)  # the main one is not one of the others
    out = [first] if first is not None else []
    for nid in d.info.interception_nodes:
        n = d.node(nid)
        if n is not None and n not in out:
            out.append(n)
    return out


def shared_splitter(d: Design, fat_id: str, spur_paths=None, site=None) -> Splitter | None:
    """The 2nd-stage splitter a FAT without one of its own takes fibres from: the first equipment up its
    distribution (spur) cables that holds a splitter, if that splitter is 2nd-stage and sits in a JB or closure -
    or in a FAT, when the rules let neighbouring FATs share (coverage designs)."""
    site = site or site_groups(d)
    if spur_paths is None:
        spur_paths = _paths_from(d, fat_id, adj=_adjacency(d, {"spur"}))
    hosts: dict[str, list[Splitter]] = defaultdict(list)
    for s in d.splitters:
        hosts[s.node].append(s)
    here = site(fat_id)
    best = None
    for nid, hops in spur_paths.items():
        if nid in hosts and site(nid) != here and (best is None or (len(hops), nid) < best[0]):
            best = ((len(hops), nid), nid)
    if best is None:
        return None
    nid = best[1]
    s2 = sorted((s for s in hosts[nid] if s.stage == 2), key=lambda s: s.id)
    if not s2:
        return None  # the nearest splitter up the cable is a PON splitter: the FAT needs its own
    kind = (d.node(nid) or Node(id="", kind="FAT")).kind
    return s2[0] if kind != "FAT" or d.rules.share_fat_splitters else None


def _chained_fat(d: Design, fat_id: str, adj) -> bool:
    """A FAT without its own splitter, cabled directly to a FAT that has one (daisy chain inside a building)."""
    with_splitter = {s.node for s in d.splitters if s.stage == 2}
    return any(nb in with_splitter and (d.node(nb) or Node(id="", kind="POP")).kind == "FAT" for nb, _ in adj[fat_id])


# ---------------------------------------------------------------------------
# Automatic allocation
# ---------------------------------------------------------------------------
def auto_allocate(d: Design) -> dict:
    issues: list[str] = []
    notes: list[str] = []
    node_ids = {n.id for n in d.nodes}
    orphans = [s.id for s in d.splitters if s.node not in node_ids]
    if orphans:
        d.splitters = [s for s in d.splitters if s.node in node_ids]
        notes.append(f"Removed splitters at deleted equipment: {', '.join(orphans)}")
    d.connections = [c for c in d.connections if not c.auto]
    ids = {c.id for c in d.connections}
    taken = {(e.ref, e.n) for c in d.connections for e in (c.a, c.b) if e.kind == "cable"}
    for c in d.cables:
        taken.update((c.id, n) for n in c.reserved)
    used_ports = {_key(e) for c in d.connections for e in (c.a, c.b) if e.kind in ("splitter_out", "olt")}
    created_splitters = 0
    adj = _adjacency(d)
    site = site_groups(d)

    def ensure_splitter(node_id: str, stage: int, outputs: int) -> Splitter:
        nonlocal created_splitters
        s = next((s for s in d.splitters if s.node == node_id and s.stage == stage), None)
        if not s:
            s = Splitter(id=f"S{stage}-{node_id}", node=node_id, stage=stage, outputs=outputs)
            d.splitters.append(s)
            created_splitters += 1
        return s

    def free_core(cable_id: str) -> int | None:
        c = d.cable(cable_id)
        for n in range(1, c.cores + 1):
            if (cable_id, n) not in taken:
                taken.add((cable_id, n))
                return n
        return None

    def connect(node: str, a: End, b: End):
        cid = next_id(ids, "X", 4)
        ids.add(cid)
        d.connections.append(Connection(id=cid, node=node, a=a, b=b, auto=True))

    def run(start_node: str, start_end: End, hops: list[tuple[str, str]], final_end: End, what: str) -> bool:
        """Splice one fibre path; consecutive hops on the same cable stay on one core (express)."""
        legs: list[list] = []  # [cable, node where the leg ends]
        for cid, node in hops:
            if legs and legs[-1][0] == cid:
                legs[-1][1] = node
            else:
                legs.append([cid, node])
        cores = []
        for cid, _ in legs:
            n = None if cid == SITE else free_core(cid)
            if n is None and cid != SITE:
                issues.append(f"Cable {cid} has no free core for {what}")
                for (c2, _), n2 in zip(legs, cores):
                    if n2 is not None:
                        taken.discard((c2, n2))
                return False
            cores.append(n)
        cur_node, cur_end = start_node, start_end
        for (cid, node), n in zip(legs, cores):
            if cid == SITE:  # patched to the neighbouring equipment at the same site: no core used
                cur_node = node
                continue
            new = End(kind="cable", ref=cid, n=n)
            connect(cur_node, cur_end, new)
            cur_node, cur_end = node, new
        connect(cur_node, cur_end, final_end)
        return True

    roots = feed_roots(d)
    if not roots:
        return {"connections": 0, "splitters": 0, "notes": notes,
                "issues": ["No starting point: place a POP or mark the interception closure as existing"]}
    root = roots[0]
    main_adj = _adjacency(d, {"main"})
    spur_adj = _adjacency(d, {"spur"})
    root_paths = {r.id: (_paths_from(d, r.id, adj=adj), _paths_from(d, r.id, adj=main_adj)) for r in roots}
    paths = {}  # node -> hops from the nearest interception
    for r in reversed(roots):
        for k, v in root_paths[r.id][0].items():
            if k not in paths or len(v) <= len(paths[k]):
                paths[k] = v
    olt_next = {r.id: 0 for r in roots}
    fed: set[str] = {c.b.ref for c in d.connections if c.b.kind == "splitter_in"} | \
                    {c.a.ref for c in d.connections if c.a.kind == "splitter_in"}

    # Feeder: OLT / interception -> every 1st-stage splitter (PON nodes get one if they have none)
    for n in sorted((n for n in d.nodes if n.kind == "PON"), key=lambda n: n.id):
        if n.id in paths:
            ensure_splitter(n.id, 1, d.rules.default_pon_split)
        elif not any(s.node == n.id and s.stage == 1 for s in d.splitters):
            issues.append(f"{n.id} is not connected to {root.id} by cables")
    for s1 in sorted((s for s in d.splitters if s.stage == 1), key=lambda s: (s.node, s.id)):
        if s1.id in fed:
            continue
        reach = [r for r in roots if s1.node in root_paths[r.id][0]]
        if not reach:
            issues.append(f"{s1.id} at {s1.node} is not connected to {root.id} by cables")
            continue
        src = min(reach, key=lambda r: len(root_paths[r.id][0][s1.node]))  # the nearest interception feeds it
        all_p, main_p = root_paths[src.id]
        route = main_p.get(s1.node, all_p[s1.node])  # feeders stay on main cables where possible
        olt_next[src.id] += 1
        while ("olt", src.id, olt_next[src.id]) in used_ports:
            olt_next[src.id] += 1
        olt_port = olt_next[src.id]
        if olt_port > (src.ports or 10 ** 6):
            issues.append(f"{src.id} has no free OLT PON port for {s1.id}")
            continue
        if run(src.id, End(kind="olt", ref=src.id, n=olt_port), route,
               End(kind="splitter_in", ref=s1.id), f"feeder to {s1.id}"):
            fed.add(s1.id)

    # Distribution: 1st-stage splitter output -> each FAT's 2nd-stage splitter, then splitters held in a JB or
    # closure that feed the FATs beyond them (shared splitters)
    stage1 = [s for s in d.splitters if s.stage == 1]
    todo: list[tuple[str, list[Splitter]]] = []
    for fat in sorted((n for n in d.nodes if n.kind == "FAT"), key=lambda n: n.id):
        if fat.id not in paths:
            issues.append(f"{fat.id} is not connected to {root.id} by cables")
            continue
        own = site_splitters(d, fat.id, site)
        if not own:
            if _chained_fat(d, fat.id, adj):
                notes.append(f"{fat.id} has no splitter of its own (fed from the neighbouring FAT)")
                continue
            up = shared_splitter(d, fat.id, _paths_from(d, fat.id, adj=spur_adj), site)
            if up is not None:
                notes.append(f"{fat.id} takes fibres from {up.id} at {up.node} (shared splitter)")
                continue
            own = [ensure_splitter(fat.id, 2, d.rules.default_fat_split)]
        todo.append((fat.id, own))
    planned = {s.id for _, own in todo for s in own}
    for s in sorted((s for s in d.splitters if s.stage == 2 and s.id not in planned), key=lambda s: s.id):
        if s.node in paths and (d.node(s.node) or Node(id="", kind="FAT")).kind != "FAT":
            todo.append((s.node, [s]))
    for fat_id, own in todo:
        from_fat = _paths_from(d, fat_id, adj=adj)
        by_spur = _paths_from(d, fat_id, adj=spur_adj)  # a FAT is fed by the PON its own distribution cables reach
        for s2 in sorted(own, key=lambda s: s.id):  # a FAT may hold several 2nd-stage splitters: feed each
            if s2.id in fed:
                continue
            # feed from the nearest fed 1st-stage splitter (fewest hops) that still has a free output
            options = sorted(((s.node not in by_spur, len(by_spur.get(s.node, from_fat[s.node])), s.id not in fed,
                               len(from_fat[s.node]), s.id), s) for s in stage1 if s.node in from_fat)
            if not options:
                issues.append(f"{fat_id} cannot be reached from any 1st-stage splitter")
                break
            chosen = None
            for _, s1 in options:
                port = next((p for p in range(1, s1.outputs + 1) if ("splitter_out", s1.id, p) not in used_ports), None)
                if port is not None:
                    chosen = (s1, port)
                    break
            if chosen is None:
                issues.append(f"No 1st-stage splitter that reaches {fat_id} has a free output for {s2.id}")
                continue
            s1, port = chosen
            back = by_spur.get(s1.node) or from_fat[s1.node]  # hops FAT -> splitter (own distribution cables first)
            nodes_back = [fat_id] + [n for _, n in back]
            hops = [(back[i][0], nodes_back[i]) for i in range(len(back) - 1, -1, -1)]
            if run(s1.node, End(kind="splitter_out", ref=s1.id, n=port), hops,
                   End(kind="splitter_in", ref=s2.id), f"{fat_id} ({s2.id})"):
                used_ports.add(("splitter_out", s1.id, port))
                fed.add(s2.id)

    return {"connections": sum(c.auto for c in d.connections), "splitters": created_splitters,
            "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Tracing and core tables
# ---------------------------------------------------------------------------
def _index(d: Design) -> dict[tuple, list[tuple[Connection, End]]]:
    idx: dict[tuple, list[tuple[Connection, End]]] = defaultdict(list)
    for c in d.connections:
        idx[_key(c.a)].append((c, c.b))
        idx[_key(c.b)].append((c, c.a))
    return idx


def trace_upstream(d: Design, splitter_id: str) -> dict:
    """Follow the fibre feeding a splitter back to the OLT."""
    idx = _index(d)
    steps, seen = [], set()
    cur = End(kind="splitter_in", ref=splitter_id)
    prev_conn = None
    for _ in range(200):
        nxt = [(c, o) for c, o in idx.get(_key(cur), []) if c.id != prev_conn]
        if not nxt:
            return {"ok": False, "steps": steps, "reason": f"{end_label(d, cur)} is not connected"}
        conn, other = nxt[0]
        if conn.id in seen:
            return {"ok": False, "steps": steps, "reason": "loop detected"}
        seen.add(conn.id)
        steps.append({"node": conn.node, "from": end_label(d, cur), "to": end_label(d, other)})
        if other.kind == "olt":
            return {"ok": True, "steps": steps, "olt": f"{other.ref} PON {other.n}"}
        if other.kind == "splitter_out":
            cur, prev_conn = End(kind="splitter_in", ref=other.ref), None
        elif other.kind == "cable":
            cur, prev_conn = other, conn.id
        else:
            return {"ok": False, "steps": steps, "reason": f"unexpected {end_label(d, other)}"}
    return {"ok": False, "steps": steps, "reason": "trace too long"}


def core_table(d: Design) -> list[dict]:
    uses: dict[tuple[str, int], list[str]] = defaultdict(list)
    for c in d.connections:
        for e, o in ((c.a, c.b), (c.b, c.a)):
            if e.kind == "cable":
                uses[(e.ref, e.n)].append(f"{c.node}: {end_label(d, o)}")
    out = []
    for cab in d.cables:
        cores = []
        for n in range(1, cab.cores + 1):
            u = uses.get((cab.id, n), [])
            status = "reserved" if n in cab.reserved else ("used" if u else "spare")
            cores.append({"n": n, **core_colour(n), "status": status, "uses": u})
        out.append({"cable": cab.id, "kind": cab.kind, "cores": cab.cores,
                    "used": sum(c["status"] == "used" for c in cores),
                    "reserved": len(cab.reserved),
                    "spare": sum(c["status"] == "spare" for c in cores), "core_list": cores})
    return out


def node_splicing(d: Design, node_id: str) -> dict:
    conns = [c for c in d.connections if c.node == node_id]
    return {
        "node": node_id,
        "splitters": [s.model_dump() | {"ratio": s.ratio} for s in d.splitters if s.node == node_id],
        "cables": sorted(c.id for c in d.cables if node_id in cable_nodes(d, c.id)),
        "connections": [{"id": c.id, "a": c.a.model_dump(), "b": c.b.model_dump(), "auto": c.auto,
                         "a_label": end_label(d, c.a), "b_label": end_label(d, c.b),
                         "a_hex": core_colour(c.a.n)["fibre_hex"] if c.a.kind == "cable" else None,
                         "b_hex": core_colour(c.b.n)["fibre_hex"] if c.b.kind == "cable" else None}
                        for c in conns],
    }


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check(d: Design) -> list[dict]:
    issues: list[dict] = []

    def err(code, msg, ref, sev="error"):
        issues.append({"severity": sev, "code": code, "message": msg, "ref": ref})

    node_ids = {n.id for n in d.nodes}
    for s in d.splitters:
        if s.node not in node_ids:
            err("splitter_node", f"Splitter {s.id} is at unknown node {s.node}", s.id)
        if s.outputs not in (2, 4, 8, 16, 32, 64):
            err("splitter_ratio", f"Splitter {s.id} has unusual ratio 1x{s.outputs}", s.id, "warning")

    # equipment at one site (same pole / a few metres apart) is spliced together: treat it as one place
    site = site_groups(d)
    pole_eq = _pole_equipment(d)
    reach = {c.id: {site(x) for x in ({v.node for v in c.path if v.node} | {c.from_node, c.to_node}
                                      | set(_vertex_nodes(d, c, pole_eq))) if x} for c in d.cables}

    per_end: dict[tuple, list[Connection]] = defaultdict(list)
    for c in d.connections:
        if c.node not in node_ids:
            err("conn_node", f"Connection {c.id} is at unknown node {c.node}", c.id)
        for e in (c.a, c.b):
            per_end[_key(e)].append(c)
            if e.kind == "cable":
                cab = d.cable(e.ref)
                if not cab:
                    err("conn_cable", f"Connection {c.id} uses unknown cable {e.ref}", c.id)
                    continue
                if not 1 <= e.n <= cab.cores:
                    err("core_range", f"{c.id}: {e.ref} has {cab.cores} cores, core {e.n} does not exist", c.id)
                if e.n in cab.reserved:
                    err("core_reserved", f"{c.id}: core {e.n} of {e.ref} is reserved", c.id)
                if site(c.node) not in reach.get(e.ref, ()):
                    err("cable_absent", f"{c.id}: cable {e.ref} does not reach node {c.node}", c.id)
            elif e.kind in ("splitter_in", "splitter_out"):
                s = d.splitter(e.ref)
                if not s:
                    err("conn_splitter", f"Connection {c.id} uses unknown splitter {e.ref}", c.id)
                    continue
                if s.node != c.node and site(s.node) != site(c.node):
                    err("splitter_elsewhere", f"{c.id}: splitter {s.id} is at {s.node}, not {c.node}", c.id)
                if e.kind == "splitter_out" and not 1 <= e.n <= s.outputs:
                    err("port_range", f"{c.id}: {s.id} ({s.ratio}) has no output {e.n}", c.id)
            elif e.kind == "olt":
                pop = d.node(e.ref)
                if not pop or not (pop.kind == "POP" or (pop.kind in ("ENCLOSURE", "PR_ENCLOSURE")
                                                         and pop.status == "existing")):
                    err("olt_node", f"{c.id}: feed {e.ref} is not a POP or existing interception closure", c.id)
                elif pop.ports and e.n > pop.ports:
                    err("olt_port", f"{c.id}: {pop.id} has {pop.ports} PON ports, port {e.n} does not exist", c.id)

    for (kind, ref, n), conns in per_end.items():
        if kind == "cable":
            nodes = [c.node for c in conns]
            dup_nodes = {x for x in nodes if nodes.count(x) > 1}
            if dup_nodes:
                clash = [c for c in conns if c.node in dup_nodes]
                err("core_duplicate", f"Core {n} of {ref} is assigned more than once at {', '.join(sorted(dup_nodes))} "
                                      f"({', '.join(c.id for c in clash)})", ref)
            elif len(conns) > 2:
                err("core_duplicate", f"Core {n} of {ref} is connected at more than two places "
                                      f"({', '.join(f'{c.id}@{c.node}' for c in conns)})", ref)
        elif len(conns) > 1:
            label = {"splitter_in": f"{ref} input", "splitter_out": f"{ref} output {n}", "olt": f"OLT {ref} port {n}"}[kind]
            err("port_duplicate", f"{label} is connected more than once ({', '.join(c.id for c in conns)})", ref)

    # every FAT must be fed from the OLT before the design can be approved, allocated yet or not
    sev = "error"
    for s in d.splitters:
        if s.stage == 2:
            t = trace_upstream(d, s.id)
            if not t["ok"]:
                err("fat_unfed", f"{s.node} splitter {s.id} is not fed from the OLT: {t['reason']}", s.node, sev)
    if d.connections:
        adj = _adjacency(d)
        with_splitter = {s.node for s in d.splitters if s.stage == 2}
        for n in d.nodes:
            if n.kind == "FAT" and n.id not in with_splitter and not _chained_fat(d, n.id, adj) \
                    and not site_splitters(d, n.id, site) and shared_splitter(d, n.id, site=site) is None:
                err("fat_no_splitter", f"{n.id} has no splitter, none in equipment on its pole, and no shared "
                                       f"splitter up its cable (run Auto-allocate or add a splitter)", n.id)
    return issues
