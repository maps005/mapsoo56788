"""Company design standards: a design style for Auto-design plus the rules (Materials & rules tab) that price it.

A company picks one on its company page; new projects start from it, and Settings can re-apply it to a project.
"""
from .model import Consumable, Rules

STANDARDS = {
    "system": {
        "label": "System defaults (per-premise, Infinity calibration)",
        "design_style": "per_premise",
        "rules": {},
    },
    "vsquared_coverage": {
        "label": "V Squared coverage (Kabiria calibration)",
        "design_style": "coverage",
        "rules": {
            "cable_extra_pct": 0.0, "cable_end_allowance_m": 0.0, "sag_per_point_m": 0.0, "cable_round_up_m": 1.0,
            "slack_per_cable_end_m": 20.0, "slack_per_passing_node_m": 20.0,
            "extension_arm_pole_types": ["KPTX", "KP TX"], "upb_tension_per_bracket": 2,
            "tension_pole_passing": "jhook", "default_fat_split": 16, "default_fat_ports": 16,
            "share_fat_splitters": True, "anchor_at_passing_equipment": True,
            # no 24C tie cable per JB in this standard
            "consumables": [c.model_dump() for c in Rules().consumables if c.code != "FOC-24C"],
        },
    },
}

CHOICES = [(k, v["label"]) for k, v in STANDARDS.items()]


def apply(d, key: str) -> None:
    """Reset a design's rules to the standard (rules it does not name go back to the system defaults)."""
    std = STANDARDS[key]
    d.rules = Rules(**{**Rules().model_dump(), **std["rules"]})
    d.info.design_style = std["design_style"]
