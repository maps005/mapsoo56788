"""Occupations: each member of a company works with only the tools and deliverables of their trade.

A project's sector decides which features exist at all (a dam has no splicing, a fibre network no building); a
member's occupation, set by a company admin, narrows that to their own work: a splicing technician gets the
splicing editor and the drawings it needs, an architect the building and its plans, a structural engineer the
structural calculations and bar bending schedule, a quantity surveyor the BOM, BOQ and rates. "Full access" (the
default) keeps every feature of the sector. Roles (viewer, planner, approver, admin) still decide who may edit,
approve and manage; occupations decide what they see and which parts of a design they may change.
"""
from __future__ import annotations

from . import sectors

# feature: what it gives
FEATURES = {
    "map": "Network map / site plan",
    "network_edit": "Draw and edit the network: supports, premises, equipment, lines; assign premises",
    "autodesign": "Fibre auto-design",
    "splicing": "Splicing, splitters and fibre allocation",
    "cad": "Detailed (CAD) drawing",
    "schedules": "Line lengths and support schedule",
    "costing": "Materials, rates, BOM and BOQ",
    "survey": "Survey import, dataset and photographs",
    "report": "Survey / building report text",
    "building_design": "Design the building (brief, walls, rooms, openings, roof, place on the site)",
    "building_view": "View the building model",
    "structure": "Structural calculations and bar bending schedule",
    "dam": "Dam design",
}

_NETWORK = ["map", "network_edit", "cad", "schedules", "costing", "survey", "report"]
_SECTOR_FEATURES = {
    "fibre": _NETWORK + ["autodesign", "splicing"],
    "construction": ["map", "building_design", "building_view", "structure", "costing", "report"],
    "dams": ["map", "dam", "costing"],
}
NETWORK_SECTORS = ("fibre", "water", "pipelines", "electricity", "lighting", "sanitation")
ALL = "all"

# key: (label, sectors it applies to, features)
OCCUPATIONS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    ALL: ("Full access", (), ()),
    "fibre_planner": ("Fibre planner / designer", ("fibre",),
                      ("map", "network_edit", "autodesign", "splicing", "cad", "schedules", "costing", "survey", "report")),
    "splicing_technician": ("Splicing technician", ("fibre",), ("map", "splicing", "cad")),
    "network_engineer": ("Network design engineer", NETWORK_SECTORS[1:],
                         ("map", "network_edit", "cad", "schedules", "costing", "survey", "report")),
    "field_surveyor": ("Field surveyor", NETWORK_SECTORS, ("map", "survey", "report")),
    "cad_drafter": ("CAD drafter", NETWORK_SECTORS, ("map", "cad", "schedules")),
    "architect": ("Architect", ("construction",), ("map", "building_design", "building_view", "report")),
    "structural_engineer": ("Structural engineer", ("construction",), ("building_view", "structure")),
    "dam_engineer": ("Dam engineer", ("dams",), ("map", "dam", "costing")),
    "quantity_surveyor": ("Quantity surveyor", NETWORK_SECTORS + ("construction", "dams"),
                          ("costing", "schedules", "building_view", "map")),
}

# deliverable: the features that use it (any one is enough); QA and the project data are everyone's
DELIVERABLE_FEATURES = {
    "hld": {"map"}, "lld": {"cad", "splicing"}, "pole_summary": {"schedules"}, "splicing": {"splicing"},
    "home_list": {"survey", "network_edit"}, "bom": {"costing"}, "boq": {"costing"}, "report": {"report"},
    "plans": {"building_design", "structure"}, "bbs": {"structure", "costing"}, "calcs": {"structure"},
    "schedules": {"building_design", "costing"}, "ifc": {"building_design", "structure"},
    "dam_drawings": {"dam"}, "dam_report": {"dam"},
}

# design section: the features that may change it (sections not listed - title block, boundary, photos - are open)
SECTION_FEATURES = {
    "poles": {"network_edit", "survey"}, "homes": {"network_edit", "survey"}, "nodes": {"network_edit"},
    "cables": {"network_edit"}, "splitters": {"splicing"}, "connections": {"splicing"},
    "building": {"building_design"}, "dam": {"dam"}, "materials": {"costing"}, "rules": {"costing"},
    "adjustments": {"costing"}, "markups": {"cad"}, "cad_layers": {"cad"},
}


def sector_features(sector: str) -> list[str]:
    key = sector if sector in sectors.SECTORS else sectors.FIBRE
    if key in _SECTOR_FEATURES:
        return list(_SECTOR_FEATURES[key])
    return list(_NETWORK)  # water, pipelines, electricity, lighting, sanitation


def for_sector(sector: str) -> list[tuple[str, str]]:
    """(key, label) of the occupations a company of this sector can give its members."""
    return [(k, v[0]) for k, v in OCCUPATIONS.items() if not v[1] or sector in v[1]]


def features(sector: str, occupation: str | None) -> list[str]:
    """What a member of this occupation sees on a project of this sector. An occupation that does not belong
    to the sector (a project of another sector in the same company) gives full access to that sector."""
    have = sector_features(sector)
    occ = OCCUPATIONS.get(occupation or ALL)
    if occ is None or not occ[1] or sector not in occ[1]:
        return have
    return [f for f in have if f in occ[2]]


def label(occupation: str | None) -> str:
    return OCCUPATIONS.get(occupation or ALL, OCCUPATIONS[ALL])[0]


def deliverables(relevant: list[str], feats: list[str]) -> list[str]:
    """The project's deliverables this member uses."""
    f = set(feats)
    return [k for k in relevant if k not in DELIVERABLE_FEATURES or DELIVERABLE_FEATURES[k] & f]


def forbidden_changes(old: dict, new: dict, feats: list[str]) -> list[str]:
    """Design sections changed between two designs (model_dump) that the member's features do not cover."""
    f = set(feats)
    return [s for s, need in SECTION_FEATURES.items() if not need & f and old.get(s) != new.get(s)]
