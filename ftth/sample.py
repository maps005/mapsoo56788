"""A small, internally consistent demo project (Nairobi area) for trying the tool."""
from __future__ import annotations

from .model import DEFAULT_MATERIALS, Cable, Design, Home, Material, Node, Pole, ProjectInfo, Vertex


def sample_design() -> Design:
    d = Design(info=ProjectInfo(
        name="Sample FTTH project (demo)", area="Demo estate, Nairobi", client="Demo ISP",
        prepared_by="Planner", survey_date="2026-10-20",
        introduction="Ground survey and FTTH design for the Infinity Area estate along the Eastern Bypass.",
        findings="Existing wooden poles along the main access road are in good condition. "
                 "An existing splice enclosure (POP) is located at the estate entrance.",
        proposed_solution="A 48-core main cable from the POP along the access road with a first-stage 1x8 "
                          "splitter enclosure, and 12-core spur cables to FATs with 1x8 second-stage splitters.",
        special_requirements="One road crossing near P004 requires crossing protection.",
        recommendations="Proceed with construction after wayleave approval for the road crossing.",
        boundary=[[-1.3105, 36.8195], [-1.3105, 36.8265], [-1.3165, 36.8265], [-1.3165, 36.8195]],
    ), materials=[m.model_copy() for m in DEFAULT_MATERIALS] + [  # demo only: the company catalogue has no rate
        Material(code="ROAD-X", description="Road crossing protection (sample rate)", unit="ea", rate=1500.0,
                 category="Civil")])

    # main road poles (west -> east) and a spur street (south)
    main = [(-1.3123, 36.8211), (-1.3125, 36.8222), (-1.3127, 36.8233), (-1.3129, 36.8244), (-1.3131, 36.8255)]
    spur = [(-1.3138, 36.8233), (-1.3149, 36.8234), (-1.3158, 36.8235)]
    for i, (la, lo) in enumerate(main + spur, start=1):
        d.poles.append(Pole(id=f"P{i:03d}", lat=la, lon=lo, type="wood", height_m=9,
                            condition="good", status="existing" if i <= 5 else "proposed"))

    d.nodes += [
        Node(id="POP01", kind="POP", lat=-1.3121, lon=36.8205, status="existing", ports=16, notes="Existing enclosure"),
        Node(id="PON01", kind="PON", lat=-1.3127, lon=36.8233, pole="P003"),
        Node(id="JB01", kind="JB", lat=-1.3131, lon=36.8255, pole="P005"),
        Node(id="FAT01", kind="FAT", lat=-1.3129, lon=36.8244, pole="P004", ports=16),
        Node(id="FAT02", kind="FAT", lat=-1.3158, lon=36.8235, pole="P008", ports=16),
    ]

    def v(pid=None, node=None, crossing=False):
        if node:
            n = next(x for x in d.nodes if x.id == node)
            return Vertex(lat=n.lat, lon=n.lon, node=node, pole=n.pole, crossing=crossing)
        p = d.pole(pid)
        return Vertex(lat=p.lat, lon=p.lon, pole=pid, crossing=crossing)

    d.cables += [
        Cable(id="C001", kind="main", cores=48, from_node="POP01", to_node="PON01",
              path=[v(node="POP01"), v("P001"), v("P002"), v(node="PON01")]),
        Cable(id="C002", kind="spur", cores=12, from_node="PON01", to_node="FAT01",
              path=[v(node="PON01"), v(node="FAT01")]),
        Cable(id="C003", kind="spur", cores=12, from_node="FAT01", to_node="JB01",
              path=[v(node="FAT01", crossing=True), v(node="JB01")]),
        Cable(id="C004", kind="spur", cores=12, from_node="PON01", to_node="FAT02",
              path=[v(node="PON01"), v("P006"), v("P007"), v(node="FAT02")]),
    ]

    homes = [(-1.3119, 36.8240, 1), (-1.3118, 36.8247, 1), (-1.3136, 36.8246, 4), (-1.3134, 36.8251, 1),
             (-1.3150, 36.8243, 1), (-1.3155, 36.8243, 1), (-1.3162, 36.8228, 3), (-1.3153, 36.8226, 1)]
    for i, (la, lo, u) in enumerate(homes, start=1):
        d.homes.append(Home(id=f"H{i:03d}", lat=la, lon=lo, units=u, kind="mdu" if u > 1 else "home",
                            name=f"Plot {100 + i}"))
    return d


def sample_building() -> Design:
    """A construction demo: a two-storey house placed on its plot (Nairobi), with the plot boundary drawn."""
    from . import building as B, sectors
    d = Design(info=ProjectInfo(
        name="Sample house (demo)", area="Demo plot, Nairobi", client="Demo client", prepared_by="Planner",
        introduction="Design and quantities for a two-storey family house on a 24 x 21 m plot.",
        proposed_solution="Blockwork walls on strip footings, concrete floor slab, hip roof in iron sheets."))
    sectors.apply(d, "construction")
    d.building = B.generate(B.AutoParams(width=12, depth=9, floors=2, rooms_x=3, rooms_y=2, roof="hip"))
    d.building.origin = [-1.3130, 36.8230]
    d.info.boundary = [list(B.to_latlon(d.building, x, y)) for x, y in ((-6, -6), (18, -6), (18, 15), (-6, 15))]
    return d
