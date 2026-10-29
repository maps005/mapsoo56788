"""Sectors: one planning platform for fibre, water supply, pipelines, electricity, street lighting and sanitation.

The design model is the same for every sector - point features (supports, premises, equipment) joined by lines -
so a sector only changes what things are called, which materials and BOQ items are used, how line lengths and
support hardware are counted (overhead or buried), which detail fields each feature records, which sector checks
QA runs, and which fibre-only tools (splicing, splitters, fibre allocation) are shown. A company picks its sector;
its projects inherit it.

Materials are listed without rates: a company imports its own price list (Materials & rules tab).
"""
from __future__ import annotations

from .model import Consumable, Material, Rules, SupportItem

FIBRE = "fibre"


def _m(code, description, unit, category):
    return Material(code=code, description=description, unit=unit, rate=0.0, category=category)


def _f(key, label, kind="text", unit=""):
    """A detail field: kind is "text", "number", "int" or a list of choices."""
    return {"key": key, "label": label, "kind": kind, "unit": unit}


_STEPS_QA = ("Quality Assurance & Approval", ["Cross-check all outputs", "Validate quantities & connections",
                                              "Version control & revisions", "Final design package"])
_STEPS_CLEAN = ("Data Cleaning & Validation", ["Remove duplicates", "Correct coordinates", "Standardise IDs",
                                               "Validate completeness"])

# line lengths and support hardware: overhead lines on poles, or buried pipes / cables in trenches
_OVERHEAD = {"cable_extra_pct": 3.0, "cable_end_allowance_m": 5.0, "sag_per_point_m": 0.5, "cable_round_up_m": 1.0,
             "slack_per_cable_end_m": 0.0, "slack_per_passing_node_m": 0.0, "riser_per_pole_end_m": 0.0,
             "extension_arm_pole_types": [], "upb_per_equipment": 0}
_BURIED = {"cable_extra_pct": 2.0, "cable_end_allowance_m": 0.0, "sag_per_point_m": 0.0, "cable_round_up_m": 1.0,
           "slack_per_cable_end_m": 0.0, "slack_per_passing_node_m": 0.0, "riser_per_pole_end_m": 0.0,
           "jhook_per_straight_cable": 0, "tension_per_cable_end": 0, "tension_per_cable_corner": 0,
           "max_suspension_poles": 0, "extension_arm_pole_types": [], "upb_per_equipment": 0,
           "jhook_code": "", "tension_code": "", "upb_code": "", "extension_arm_code": "",
           # Section A: trench per metre of buried route (aerial installation, trunking and building cabling: none)
           "implementation_costs": True, "install_aerial_code": "", "install_trunking_code": "",
           "building_cabling_code": "", "trench_code": "CIVIL-TRENCH"}

SECTORS: dict[str, dict] = {
    "fibre": {
        "sizes": [2, 4, 6, 8, 12, 24, 48, 72, 96, 144], "size_defaults": {"main": 48, "spur": 12, "drop": 2},
        "label": "Fibre / FTTH",
        "network": "FTTH network",
        "report_title": "FTTH Survey and Design Report",
        "fibre_tools": True,
        "install": "aerial",
        "unit": "homepasses", "unit_one": "homepass",
        "premise": "Home / MDU", "support": "Pole", "line": "Cable", "size": "Cores", "size_unit": "C",
        "lines": {"main": "Main cable (48C)", "spur": "Spur cable (12C)", "drop": "Drop"},
        "kinds": {"POP": "POP", "ENCLOSURE": "Splice enclosure", "PR_ENCLOSURE": "PR Enclosure", "JB": "JB",
                  "PON": "PON (1st-stage splitter)", "FAT": "FAT", "SLACK": "Slack loop"},
        "ports": {"POP": "OLT PON ports", "FAT": "Ports"},
        "hardware": [["tension", "Tension Clamps"], ["upb", "UPB"], ["jhooks", "J-Hooks"], ["ext_arms", "Extension Arm"]],
        "steps": None,  # the page's own text
        "details": {},
    },
    "water": {
        "sizes": [20, 25, 32, 50, 63, 90, 110, 160, 200, 250, 315], "size_defaults": {"main": 160, "spur": 90, "drop": 25},
        "label": "Water supply",
        "network": "water supply network",
        "report_title": "Water Supply Survey and Design Report",
        "fibre_tools": False,
        "install": "underground",
        "unit": "connections", "unit_one": "connection",
        "premise": "Property / customer", "support": "Marker post", "line": "Pipe", "size": "Diameter (DN)",
        "size_unit": "mm",
        "lines": {"main": "Transmission / trunk main", "spur": "Distribution main", "drop": "Service connection"},
        "kinds": {"POP": "Source / reservoir", "ENCLOSURE": "Valve chamber", "PR_ENCLOSURE": "Valve chamber (new)",
                  "JB": "Junction / tee chamber", "PON": "Pressure zone (PRV / booster)",
                  "FAT": "Meter / service connection", "SLACK": "Air valve / washout"},
        "ports": {},
        "hardware": [],
        "steps": [
            ("Ground Survey & Data Collection", ["Existing mains, valves, hydrants", "Properties & customers",
                                                 "Road reserves, crossings", "Levels & ground conditions",
                                                 "Photos & site notes"]),
            _STEPS_CLEAN,
            ("Network Layout (GIS)", ["Define supply area", "Plot properties & existing mains",
                                      "Plan trunk & distribution mains", "Place valves, chambers, PRVs",
                                      "Export KML/KMZ"]),
            ("Material Assignment", ["Select pipe sizes & materials", "Valves, fittings, chambers",
                                     "Meters & service connections", "Auto-calculate quantities"]),
            ("Detailed Design (CAD)", ["Pipe routes & chainages", "Valve & chamber schedule",
                                       "Crossings & thrust blocks", "Export CAD (DXF / PDF)"]),
            ("Generate Deliverables", ["Layout (KML/PDF) · Detail (DXF/PDF)", "Route & chamber schedules",
                                       "BOM · BOQ (Excel/PDF)", "Survey & design report"]),
            _STEPS_QA,
        ],
        "materials": [_m(f"PIPE-HDPE-DN{dn}", f"HDPE pipe PN10, DN{dn} mm", "M", "Pipe") for dn in (20, 25, 32, 50, 63, 90, 110, 160, 200, 250, 315)]
        + [_m("VALVE-CHAMBER", "Gate valve with chamber and cover", "PCS", "Valves & chambers"),
           _m("JUNCTION-CHAMBER", "Tee / junction with chamber", "PCS", "Valves & chambers"),
           _m("PRV-STATION", "Pressure reducing valve station", "PCS", "Valves & chambers"),
           _m("METER-CONNECTION", "Customer meter and service connection", "PCS", "Connections"),
           _m("AIR-VALVE", "Air valve / washout with chamber", "PCS", "Valves & chambers"),
           _m("RESERVOIR", "Storage reservoir / source works", "PCS", "Works"),
           _m("MARKER-POST", "Pipe route marker post", "PCS", "Route"),
           _m("ROAD-X", "Road crossing (sleeve and reinstatement)", "PCS", "Civil works"),
           _m("CIVIL-TRENCH", "Trench excavation, bedding and backfill", "M", "Civil works")],
        "rules": {**_BURIED, "cable_code": "PIPE-HDPE-DN{cores}", "pole_code": "MARKER-POST",
                  "node_codes": {"POP": "RESERVOIR", "ENCLOSURE": "VALVE-CHAMBER", "PR_ENCLOSURE": "VALVE-CHAMBER",
                                 "JB": "JUNCTION-CHAMBER", "PON": "PRV-STATION", "FAT": "METER-CONNECTION",
                                 "SLACK": "AIR-VALVE"}},
        "details": {
            "cable": [_f("material", "Pipe material", ["HDPE", "uPVC", "Ductile iron", "GI", "Steel"]),
                      _f("pressure_class", "Pressure class", ["PN6", "PN10", "PN12.5", "PN16"]),
                      _f("cover_depth_m", "Cover depth", "number", "m")],
            "node": [_f("valve_type", "Valve type", ["Gate", "Butterfly", "Air", "Washout", "PRV", "Non-return", "Hydrant"]),
                     _f("ground_level_m", "Ground level", "number", "m")],
            "home": [_f("customer_type", "Customer type", ["Domestic", "Commercial", "Institutional", "Kiosk"]),
                     _f("meter_size_mm", "Meter size", ["15", "20", "25", "40", "50"], "mm")],
            "pole": [],
        },
    },
    "pipelines": {
        "sizes": [50, 80, 100, 150, 200, 250, 300, 400], "size_defaults": {"main": 300, "spur": 150, "drop": 50},
        "label": "Pipelines (oil & gas)",
        "network": "pipeline system",
        "report_title": "Pipeline Route Survey and Design Report",
        "fibre_tools": False,
        "install": "underground",
        "unit": "delivery points", "unit_one": "delivery point",
        "premise": "Delivery point / consumer", "support": "Marker post", "line": "Pipeline",
        "size": "Diameter (DN)", "size_unit": "mm",
        "lines": {"main": "Trunk pipeline", "spur": "Lateral / spur line", "drop": "Service line"},
        "kinds": {"POP": "Station / terminal", "ENCLOSURE": "Block valve station", "PR_ENCLOSURE": "Valve station (new)",
                  "JB": "Tie-in / junction", "PON": "Pump / compressor station", "FAT": "Offtake / metering point",
                  "SLACK": "CP test point"},
        "ports": {},
        "hardware": [],
        "steps": [
            ("Route Survey & Data Collection", ["Route corridor & way-leaves", "Existing pipelines & utilities",
                                                "Crossings (roads, rivers, rail)", "Terrain & ground conditions",
                                                "Photos & site notes"]),
            _STEPS_CLEAN,
            ("Route Design (GIS)", ["Define corridor", "Plot stations & delivery points", "Plan trunk & lateral lines",
                                    "Place valves, tie-ins, offtakes", "Export KML/KMZ"]),
            ("Material Assignment", ["Select pipe grades & sizes", "Valves, fittings, CP", "Markers & crossings",
                                     "Auto-calculate quantities"]),
            ("Detailed Design (CAD)", ["Alignment sheets", "Valve & station schedule", "Crossing details",
                                       "Export CAD (DXF / PDF)"]),
            ("Generate Deliverables", ["Route map (KML/PDF) · Alignment (DXF/PDF)", "Station & valve schedules",
                                       "BOM · BOQ (Excel/PDF)", "Route survey & design report"]),
            ("Quality Assurance & Approval", ["Cross-check all outputs", "Validate quantities & crossings",
                                              "Version control & revisions", "Final design package"]),
        ],
        "materials": [_m(f"PIPE-STEEL-DN{dn}", f"Coated steel line pipe, DN{dn} mm", "M", "Pipe") for dn in (50, 80, 100, 150, 200, 250, 300, 400)]
        + [_m("BLOCK-VALVE", "Block valve station", "PCS", "Valves"),
           _m("TIE-IN", "Tie-in / junction fitting", "PCS", "Fittings"),
           _m("PUMP-STATION", "Pump / compressor station", "PCS", "Stations"),
           _m("OFFTAKE", "Offtake / metering skid", "PCS", "Stations"),
           _m("CP-TEST-POINT", "Cathodic protection test point", "PCS", "Corrosion protection"),
           _m("TERMINAL", "Station / terminal works", "PCS", "Stations"),
           _m("MARKER-POST", "Pipeline marker post", "PCS", "Route"),
           _m("ROAD-X", "Road / river crossing", "PCS", "Crossings"),
           _m("CIVIL-TRENCH", "Trench excavation, padding and backfill", "M", "Civil works")],
        "rules": {**_BURIED, "cable_code": "PIPE-STEEL-DN{cores}", "pole_code": "MARKER-POST",
                  "node_codes": {"POP": "TERMINAL", "ENCLOSURE": "BLOCK-VALVE", "PR_ENCLOSURE": "BLOCK-VALVE",
                                 "JB": "TIE-IN", "PON": "PUMP-STATION", "FAT": "OFFTAKE", "SLACK": "CP-TEST-POINT"}},
        "details": {
            "cable": [_f("grade", "Line pipe grade", ["API 5L Gr B", "X42", "X52", "X60", "X65", "HDPE PE100"]),
                      _f("wall_thickness_mm", "Wall thickness", "number", "mm"),
                      _f("coating", "Coating", ["3LPE", "FBE", "Coal tar", "None"]),
                      _f("maop_bar", "MAOP", "number", "bar"),
                      _f("cover_depth_m", "Cover depth", "number", "m")],
            "node": [_f("valve_type", "Valve type", ["Ball", "Gate", "Check", "Plug"]),
                     _f("ground_level_m", "Ground level", "number", "m")],
            "home": [_f("product", "Product", ["Crude oil", "Refined products", "Natural gas", "LPG", "Water"])],
            "pole": [],
        },
    },
    "electricity": {
        "sizes": [16, 25, 35, 50, 70, 100, 150], "size_defaults": {"main": 100, "spur": 50, "drop": 16},
        "label": "Electricity distribution",
        "network": "power distribution network",
        "report_title": "Power Distribution Survey and Design Report",
        "fibre_tools": False,
        "install": "aerial",
        "unit": "customers", "unit_one": "customer",
        "premise": "Customer / premises", "support": "Pole", "line": "Line", "size": "Conductor size",
        "size_unit": "mm²",
        "lines": {"main": "MV feeder", "spur": "LV distribution line", "drop": "Service cable"},
        "kinds": {"POP": "Substation", "ENCLOSURE": "Switching point / RMU", "PR_ENCLOSURE": "Switching point (new)",
                  "JB": "LV feeder pillar", "PON": "Distribution transformer", "FAT": "Service point / meter",
                  "SLACK": "Earthing point"},
        "ports": {"PON": "Rating (kVA)"},
        "port_sizes": {"PON": [25, 50, 100, 200, 315, 500]}, "port_defaults": {"PON": 100},
        "hardware": [["jhooks", "Suspension clamps"], ["tension", "Dead-end clamps"], ["upb", "Cross-arms"]],
        "steps": [
            ("Ground Survey & Data Collection", ["Poles (IDs, GPS, condition)", "Customers & loads",
                                                 "Existing lines & transformers", "Way-leaves, crossings",
                                                 "Photos & site notes"]),
            _STEPS_CLEAN,
            ("Network Layout (GIS)", ["Define supply area", "Plot poles & customers", "Plan MV & LV lines",
                                      "Place transformers, switches, pillars", "Export KML/KMZ"]),
            ("Material Assignment", ["Select conductors", "Pole hardware (clamps, cross-arms)",
                                     "Transformers & service points", "Auto-calculate quantities"]),
            ("Detailed Design (CAD)", ["Line routes & spans", "Pole & stay schedule", "Transformer zones",
                                       "Export CAD (DXF / PDF)"]),
            ("Generate Deliverables", ["Layout (KML/PDF) · Detail (DXF/PDF)", "Pole schedule (Excel/PDF)",
                                       "BOM · BOQ (Excel/PDF)", "Survey & design report"]),
            ("Quality Assurance & Approval", ["Cross-check all outputs", "Validate quantities & loads",
                                              "Version control & revisions", "Final design package"]),
        ],
        "materials": [_m(f"COND-{s}MM", f"Conductor / ABC cable {s} mm²", "M", "Conductor") for s in (16, 25, 35, 50, 70, 100, 150)]
        + [_m("POLE-NEW", "Wooden pole 9-11 m, supply and install", "PCS", "Poles"),
           _m("SUSPENSION-CLAMP", "Suspension clamp / insulator set", "PCS", "Pole hardware"),
           _m("DEAD-END-CLAMP", "Dead-end (strain) clamp set", "PCS", "Pole hardware"),
           _m("CROSS-ARM", "Cross-arm / pole bracket", "PCS", "Pole hardware"),
           _m("STAY-SET", "Stay set", "PCS", "Pole hardware")]
        + [_m(f"TX-{k}KVA", f"Distribution transformer {k} kVA", "PCS", "Transformers") for k in (25, 50, 100, 200, 315, 500)]
        + [_m("RMU", "Ring main unit / switching point", "PCS", "Switchgear"),
           _m("FEEDER-PILLAR", "LV feeder pillar", "PCS", "Switchgear"),
           _m("SERVICE-POINT", "Customer service point and meter", "PCS", "Connections"),
           _m("EARTHING", "Earthing set", "PCS", "Pole hardware"),
           _m("SUBSTATION", "Substation works", "PCS", "Works"),
           _m("ROAD-X", "Road crossing", "PCS", "Crossings")],
        "rules": {**_OVERHEAD, "cable_code": "COND-{cores}MM", "pole_code": "POLE-NEW", "jhook_code": "SUSPENSION-CLAMP",
                  "tension_code": "DEAD-END-CLAMP", "upb_code": "CROSS-ARM", "extension_arm_code": "",
                  # a stay set holds each pair of dead-end clamps (line ends, corners, anchors)
                  "consumables": [Consumable(code="STAY-SET", basis="tension", ratio=0.5, rounding="up").model_dump()],
                  "node_codes": {"POP": "SUBSTATION", "ENCLOSURE": "RMU", "PR_ENCLOSURE": "RMU", "JB": "FEEDER-PILLAR",
                                 "PON": "TX-{ports}KVA", "FAT": "SERVICE-POINT", "SLACK": "EARTHING"}},
        "details": {
            "cable": [_f("voltage", "Voltage", ["LV 415 V", "MV 11 kV", "MV 33 kV"]),
                      _f("conductor", "Conductor", ["ABC", "AAC", "ACSR", "Cu XLPE"]),
                      _f("phases", "Phases", ["1", "3"])],
            "pole": [_f("pole_material", "Pole material", ["Wood", "Concrete", "Steel"]),
                     _f("structure", "Structure", ["Intermediate", "Angle", "Terminal", "Section", "Transformer"])],
            "node": [_f("voltage_ratio", "Voltage ratio", ["11/0.415 kV", "33/0.415 kV", "33/11 kV"])],
            "home": [_f("load_kva", "Load (after diversity)", "number", "kVA"), _f("phases", "Phases", ["1", "3"])],
        },
    },
    "lighting": {
        "sizes": [4, 6, 10, 16, 25, 35], "size_defaults": {"main": 16, "spur": 10, "drop": 4},
        "label": "Street lighting",
        "network": "street lighting network",
        "report_title": "Street Lighting Survey and Design Report",
        "fibre_tools": False,
        "install": "underground",
        "unit": "lighting points", "unit_one": "lighting point",
        "premise": "Lighting point / area", "support": "Lighting column", "line": "Cable", "size": "Cable size",
        "size_unit": "mm²",
        "lines": {"main": "Supply feeder cable", "spur": "Lighting circuit cable", "drop": "Column supply cable"},
        "kinds": {"POP": "Supply point / transformer", "ENCLOSURE": "Feeder pillar", "PR_ENCLOSURE": "Feeder pillar (new)",
                  "JB": "Cut-out / junction box", "PON": "Control cabinet (photocell / timer)", "FAT": "Wall-mounted light",
                  "SLACK": "Earthing point"},
        "ports": {},
        "hardware": [],
        "steps": [
            ("Ground Survey & Data Collection", ["Roads & lighting class", "Existing columns & lights",
                                                 "Supply points", "Crossings, other utilities", "Photos & site notes"]),
            _STEPS_CLEAN,
            ("Lighting Layout (GIS)", ["Define roads to light", "Place columns (spacing)", "Plan feeder & circuit cables",
                                       "Place feeder pillars & controls", "Export KML/KMZ"]),
            ("Material Assignment", ["Columns & brackets", "Luminaires (wattage)", "Cables & pillars",
                                     "Auto-calculate quantities"]),
            ("Detailed Design (CAD)", ["Column positions & spacing", "Circuit schedule", "Cable routes & crossings",
                                       "Export CAD (DXF / PDF)"]),
            ("Generate Deliverables", ["Layout (KML/PDF) · Detail (DXF/PDF)", "Column schedule (Excel/PDF)",
                                       "BOM · BOQ (Excel/PDF)", "Survey & design report"]),
            ("Quality Assurance & Approval", ["Cross-check all outputs", "Validate spacing & quantities",
                                              "Version control & revisions", "Final design package"]),
        ],
        "materials": [_m(f"LV-ARMOURED-{s}MM", f"Armoured LV cable, {s} mm²", "M", "Cable") for s in (4, 6, 10, 16, 25, 35)]
        + [_m("LIGHT-COLUMN", "Street lighting column with foundation, supply and install", "PCS", "Columns")]
        + [_m(f"LUMINAIRE-{w}W", f"LED street luminaire {w} W", "PCS", "Luminaires") for w in (30, 60, 90, 120, 150)]
        + [_m("FEEDER-PILLAR", "Street lighting feeder pillar", "PCS", "Switchgear"),
           _m("CUT-OUT", "Column cut-out / junction box", "PCS", "Switchgear"),
           _m("CONTROL-CABINET", "Lighting control cabinet (photocell / timer)", "PCS", "Controls"),
           _m("SUPPLY-POINT", "Supply point connection", "PCS", "Works"),
           _m("EARTHING", "Earthing set", "PCS", "Earthing"),
           _m("ROAD-X", "Road crossing (duct and reinstatement)", "PCS", "Civil works"),
           _m("CIVIL-TRENCH", "Cable trench excavation and backfill", "M", "Civil works")],
        "rules": {**_BURIED, "cable_code": "LV-ARMOURED-{cores}MM", "pole_code": "LIGHT-COLUMN",
                  "support_items": [SupportItem(code="LUMINAIRE-{lamp_w}W", qty_detail="lamps", default_qty=1,
                                                defaults={"lamp_w": 60}).model_dump()],
                  "node_codes": {"POP": "SUPPLY-POINT", "ENCLOSURE": "FEEDER-PILLAR", "PR_ENCLOSURE": "FEEDER-PILLAR",
                                 "JB": "CUT-OUT", "PON": "CONTROL-CABINET", "FAT": "LUMINAIRE-60W",
                                 "SLACK": "EARTHING"}},
        "details": {
            "pole": [_f("column_height_m", "Column height", ["6", "8", "10", "12"], "m"),
                     _f("lamps", "Luminaires on the column", "int"),
                     _f("lamp_w", "Luminaire wattage", ["30", "60", "90", "120", "150"], "W"),
                     _f("bracket", "Bracket", ["Single arm", "Double arm", "Post top"])],
            "cable": [_f("cable_type", "Cable type", ["Armoured Cu", "Armoured Al", "ABC"]),
                      _f("circuit", "Circuit", "text")],
            "node": [_f("control", "Control", ["Photocell", "Timer", "Smart / CMS"])],
            "home": [_f("lighting_class", "Lighting class", ["M3", "M4", "M5", "P3", "P4"])],
        },
    },
    "sanitation": {
        "sizes": [110, 160, 200, 250, 300, 400], "size_defaults": {"main": 300, "spur": 200, "drop": 110},
        "label": "Sanitation / sewerage",
        "network": "sewerage network",
        "report_title": "Sewerage Survey and Design Report",
        "fibre_tools": False,
        "install": "underground",
        "unit": "connections", "unit_one": "connection",
        "premise": "Property / connection", "support": "Manhole", "line": "Sewer", "size": "Diameter (DN)",
        "size_unit": "mm",
        "lines": {"main": "Trunk sewer", "spur": "Lateral / collector sewer", "drop": "House connection"},
        "kinds": {"POP": "Treatment works / outfall", "ENCLOSURE": "Manhole", "PR_ENCLOSURE": "Manhole (new)",
                  "JB": "Inspection chamber", "PON": "Sewage pumping station", "FAT": "House connection chamber",
                  "SLACK": "Vent / drop structure"},
        "ports": {},
        "hardware": [],
        "steps": [
            ("Ground Survey & Data Collection", ["Existing sewers & manholes", "Properties & connections",
                                                 "Levels & falls", "Crossings, other utilities",
                                                 "Photos & site notes"]),
            _STEPS_CLEAN,
            ("Network Layout (GIS)", ["Define catchment", "Plot properties & existing sewers",
                                      "Plan trunk & lateral sewers", "Place manholes, chambers, pump stations",
                                      "Export KML/KMZ"]),
            ("Material Assignment", ["Select pipe sizes & materials", "Manholes & chambers", "House connections",
                                     "Auto-calculate quantities"]),
            ("Detailed Design (CAD)", ["Sewer routes & gradients", "Manhole schedule", "Long sections",
                                       "Export CAD (DXF / PDF)"]),
            ("Generate Deliverables", ["Layout (KML/PDF) · Detail (DXF/PDF)", "Manhole & route schedules",
                                       "BOM · BOQ (Excel/PDF)", "Survey & design report"]),
            _STEPS_QA,
        ],
        "materials": [_m(f"SEWER-UPVC-DN{dn}", f"uPVC sewer pipe, DN{dn} mm", "M", "Pipe") for dn in (110, 160, 200, 250, 300, 400)]
        + [_m("MANHOLE", "Manhole with cover (supply and construct)", "PCS", "Manholes & chambers"),
           _m("INSPECTION-CHAMBER", "Inspection chamber", "PCS", "Manholes & chambers"),
           _m("PUMP-STATION", "Sewage pumping station", "PCS", "Works"),
           _m("HOUSE-CONNECTION", "House connection with chamber", "PCS", "Connections"),
           _m("VENT", "Vent / drop structure", "PCS", "Manholes & chambers"),
           _m("TREATMENT-WORKS", "Treatment works / outfall", "PCS", "Works"),
           _m("ROAD-X", "Road crossing", "PCS", "Civil works"),
           _m("CIVIL-TRENCH", "Trench excavation, bedding and backfill", "M", "Civil works")],
        "rules": {**_BURIED, "cable_code": "SEWER-UPVC-DN{cores}", "pole_code": "MANHOLE",
                  "node_codes": {"POP": "TREATMENT-WORKS", "ENCLOSURE": "MANHOLE", "PR_ENCLOSURE": "MANHOLE",
                                 "JB": "INSPECTION-CHAMBER", "PON": "PUMP-STATION", "FAT": "HOUSE-CONNECTION",
                                 "SLACK": "VENT"}},
        "details": {
            "pole": [_f("cover_level_m", "Cover level", "number", "m"), _f("invert_level_m", "Invert level", "number", "m"),
                     _f("manhole_type", "Manhole type", ["Brick", "Precast concrete", "Plastic"])],
            "node": [_f("cover_level_m", "Cover level", "number", "m"), _f("invert_level_m", "Invert level", "number", "m")],
            "cable": [_f("material", "Pipe material", ["uPVC", "HDPE", "Concrete", "Vitrified clay"])],
            "home": [_f("connection_type", "Connection", ["Domestic", "Commercial", "Institutional"])],
        },
    },
    # Buildings, not networks: the Building 3D tab designs them (ftth.building); the network map, the LLD
    # drawing and HLD outputs are not used. Quantities come from the building model.
    "construction": {
        "construction": True,
        "sizes": [1], "size_defaults": {"main": 1, "spur": 1, "drop": 1},
        "label": "Construction / buildings",
        "network": "building",
        "report_title": "Building Design and Quantities Report",
        "fibre_tools": False,
        "install": "underground",
        "unit": "dwellings", "unit_one": "dwelling",
        "premise": "Building", "support": "Site point", "line": "Line", "size": "Size", "size_unit": "",
        "lines": {"main": "Line", "spur": "Line", "drop": "Line"},
        "kinds": {"POP": "Site point", "ENCLOSURE": "Site point", "PR_ENCLOSURE": "Site point", "JB": "Site point",
                  "PON": "Site point", "FAT": "Site point", "SLACK": "Site point"},
        "ports": {},
        "hardware": [],
        "steps": [
            ("Site Survey & Brief", ["Plot boundary on the map", "Levels & ground conditions", "Client brief & rooms",
                                     "Photos & site notes"]),
            _STEPS_CLEAN,
            ("Building Design (3D)", ["Auto design from the brief", "Walls, doors & windows", "Floors, stairs & roof",
                                      "Place on the site plan"]),
            ("Quantities & Materials", ["Concrete, blocks, steel", "Roofing & finishes", "Doors & windows",
                                        "Rates from the price list"]),
            ("Plans & Elevations", ["Floor plans with dimensions", "Four elevations", "3D model (GLB / OBJ / STL / DXF)"]),
            ("Generate Deliverables", ["Plans & elevations (PDF)", "BOM · BOQ (Excel/PDF)", "Design & quantities report"]),
            ("Quality Assurance & Approval", ["Openings, headroom, stairs", "Setback from the plot boundary",
                                              "Version control & revisions", "Final design package"]),
        ],
        "materials": [
            _m("EXCAVATION", "Excavation for strip footings", "M3", "Substructure"),
            _m("HARDCORE", "Hardcore filling, compacted", "M3", "Substructure"),
            _m("DPM", "Damp-proof membrane", "M2", "Substructure"),
            _m("CONC-FOOTING", "Concrete C20 in strip footings", "M3", "Concrete"),
            _m("CONC-SLAB", "Concrete C25 in slabs", "M3", "Concrete"),
            _m("CONC-COLUMN", "Concrete C25 in columns", "M3", "Concrete"),
            _m("CONC-STAIR", "Concrete C25 in stairs", "M3", "Concrete"),
            _m("CONC-WALL", "Concrete C25 in walls", "M3", "Concrete"),
            _m("REBAR", "High-yield reinforcement bars", "KG", "Reinforcement"),
            _m("FORMWORK", "Formwork to soffits and columns", "M2", "Concrete"),
            _m("BLOCKWORK-EXT", "200 mm blockwork, external walls", "M2", "Walling"),
            _m("BLOCKWORK-INT", "150 mm blockwork, internal walls", "M2", "Walling"),
            _m("BRICKWORK-EXT", "Brickwork, external walls", "M2", "Walling"),
            _m("BRICKWORK-INT", "Brickwork, internal walls", "M2", "Walling"),
            _m("STONEWORK-EXT", "Dressed stone, external walls", "M2", "Walling"),
            _m("STONEWORK-INT", "Dressed stone, internal walls", "M2", "Walling"),
            _m("LINTEL", "Reinforced concrete lintel", "M", "Walling"),
            _m("PLASTER", "Internal plaster, 12 mm", "M2", "Finishes"),
            _m("RENDER", "External render, 15 mm", "M2", "Finishes"),
            _m("PAINT-INT", "Emulsion paint, 3 coats", "M2", "Finishes"),
            _m("PAINT-EXT", "Weatherproof paint, 3 coats", "M2", "Finishes"),
            _m("SCREED", "Floor screed, 40 mm", "M2", "Finishes"),
            _m("CEILING", "Ceiling boards on brandering", "M2", "Finishes"),
            _m("ROOF-SHEETS", "Pre-painted iron roofing sheets", "M2", "Roofing"),
            _m("ROOF-TILES", "Roof tiles on battens", "M2", "Roofing"),
            _m("ROOF-TIMBER", "Treated roof timber (rafters, ridge, wall plate)", "M", "Roofing"),
            _m("RIDGE", "Ridge and hip capping", "M", "Roofing"),
            _m("GUTTER", "Gutters", "M", "Roofing"),
            _m("FASCIA", "Fascia boards", "M", "Roofing"),
            _m("DOOR-SINGLE", "Single door with frame and ironmongery", "PCS", "Doors"),
            _m("DOOR-DOUBLE", "Double door with frame and ironmongery", "PCS", "Doors"),
            _m("DOOR-SLIDING", "Sliding door", "PCS", "Doors"),
            _m("DOOR-ARCHED", "Arched door", "PCS", "Doors"),
            _m("WINDOW-FIXED", "Fixed window, glazed", "M2", "Windows"),
            _m("WINDOW-CASEMENT", "Casement window, glazed", "M2", "Windows"),
            _m("WINDOW-SLIDING", "Sliding window, glazed", "M2", "Windows"),
            _m("WINDOW-HUNG", "Hung sash window, glazed", "M2", "Windows")],
        "rules": {**_BURIED, "cable_code": "", "pole_code": "", "crossing_code": "", "node_codes": {},
                  "implementation_costs": False},
        "details": {},
    },
}
CHOICES = [(k, v["label"]) for k, v in SECTORS.items()]

# document wording: fibre words -> the sector's words (applied to report and QA text of non-fibre projects)
_SHORT = {"water": ("service connection", "marker post", "pipe"), "pipelines": ("offtake", "marker post", "pipeline"),
          "electricity": ("service point", "pole", "line"), "lighting": ("light", "lighting column", "cable"),
          "sanitation": ("house connection", "manhole", "sewer")}


def wording(key: str | None) -> list[tuple[str, str]]:
    """(fibre word, sector word) pairs, longest first, for report text; empty for fibre."""
    if not key or key == FIBRE or key not in SECTORS or SECTORS[key].get("construction"):
        return []
    p, (fat, support, line) = SECTORS[key], _SHORT[key]
    premise = p["premise"].split("/")[0].strip()
    pairs = [("Homepasses", p["unit"].capitalize()), ("homepasses", p["unit"]), ("homepass", p["unit_one"]),
             ("HPs", p["unit"]), ("FTTH network", p["network"]), ("FTTH", p["label"]), ("FATs", fat + "s"),
             ("FAT", fat), ("Homes", premise + "s"), ("Home", premise), ("Poles", support.capitalize() + "s"),
             ("poles", support + "s"), ("Pole", support.capitalize()), ("pole", support),
             ("Cables", line.capitalize() + "s"), ("cables", line + "s"), ("Cable", line.capitalize()),
             ("cable", line), ("fibre", line), ("Fibre", line.capitalize()), ("Cores", p["size"]),
             ("cores", p["size"].lower())]
    return pairs


def reword(text: str, pairs) -> str:
    import re
    for a, b in pairs:  # whole words only: IDs such as FAT-01 or POLE-NEW keep their text
        text = re.sub(rf"(?<![\w-]){re.escape(a)}(?![\w-])", b, text)
    if pairs:  # "a FAT" became "a offtake"
        text = re.sub(r"\b([Aa]) (?=(?:offtake|air|earthing|inspection|LV)\b)", r"\1n ", text)
    return text


def get(key: str | None) -> dict:
    return SECTORS.get(key or FIBRE, SECTORS[FIBRE])


def kind_label(d, kind: str) -> str:
    return get(getattr(d.info, "sector", FIBRE))["kinds"].get(kind, kind)


def size_label(key: str | None, size: int) -> str:
    """A line size in the sector's unit: 48C, DN160, 50 mm²."""
    p = get(key)
    if p["size_unit"] == "C":
        return f"{size}C"
    return f"DN{size}" if p["size_unit"] == "mm" else f"{size} {p['size_unit']}"


def schedule_columns(key: str | None) -> list[tuple[str, str]]:
    """(PoleRow attribute, heading) for the support schedule: the sector's support hardware, then equipment."""
    p = get(key)
    kinds = p["kinds"]
    return [tuple(h) for h in p["hardware"]] + [("jb", kinds["JB"]), ("enclosures", kinds["ENCLOSURE"]),
                                                 ("fats", kinds["FAT"])]


def profile(key: str | None) -> dict:
    """What the planner page needs to relabel itself (no materials or rules)."""
    p = get(key)
    return {"key": key if key in SECTORS else FIBRE, **{k: p[k] for k in (
        "label", "network", "report_title", "fibre_tools", "install", "unit", "unit_one", "premise", "support",
        "line", "size", "size_unit", "lines", "kinds", "ports", "hardware", "steps", "sizes", "size_defaults",
        "details")}, "port_sizes": p.get("port_sizes", {}), "port_defaults": p.get("port_defaults", {}),
        "construction": bool(p.get("construction")),
        "schedule": [list(c) for c in schedule_columns(key)]}


def _nearest(sizes: list[int], v) -> int:
    return min(sizes, key=lambda s: (abs(s - (v or 0)), s))


def apply(d, key: str, materials: bool = True) -> None:
    """Switch a design to a sector: its names, its rules and material catalogue, and line sizes, installation
    and equipment ratings the sector's catalogue has (a fibre 48C main becomes the water sector's trunk-main DN)."""
    if key not in SECTORS:
        raise ValueError(f"Unknown sector: {key}")
    old = d.info.sector
    d.info.sector = key
    p = SECTORS[key]
    if key == FIBRE:
        return  # fibre keeps the design standard's rules and catalogue
    base = Rules().model_dump()
    d.rules = Rules(**{**base, "consumables": [], "share_fat_splitters": False, **p["rules"]})
    if materials:
        d.materials = [m.model_copy() for m in p["materials"]]
    if old == key:
        return
    sizes = p["sizes"]
    for c in d.cables:
        if c.cores not in sizes:  # a size from another sector: the sector's usual size for this kind of line
            c.cores = p["size_defaults"].get(c.kind, sizes[0])
        if c.status == "proposed":
            c.install = p["install"]
    port_sizes, port_defaults = p.get("port_sizes", {}), p.get("port_defaults", {})
    for n in d.nodes:
        if n.kind in port_sizes:
            n.ports = n.ports if n.ports in port_sizes[n.kind] else port_defaults[n.kind]
        elif n.kind not in p["ports"]:
            n.ports = None
    # splitters, fibre connections and core reservations stay in the design for a switch back to fibre;
    # calculations and QA ignore them in other sectors (fibre_tools)


def fibre_tools(d) -> bool:
    return get(getattr(d.info, "sector", FIBRE))["fibre_tools"]
