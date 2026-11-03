"""Indicative rates: a starting price list for the sectors whose materials ship without rates.

They are typical supply-and-install rates in Kenya shillings (KES) for 2026, rounded, for early estimates only: a
company replaces them with its own price list (Materials & rules: Import price list) before a BOQ is issued. Only
items with no rate yet are filled, so a company's own prices are never overwritten.
"""
from __future__ import annotations

from . import sectors
from .model import Design

CURRENCY = "KES"
NOTE = "Indicative 2026 Kenya rate - replace with your supplier's price"

INDICATIVE: dict[str, float] = {
    # ---- construction: substructure, frame, walling, finishes, roofing, doors and windows -------------------
    "EXCAVATION": 850, "HARDCORE": 2600, "DPM": 180, "CONC-FOOTING": 15500, "CONC-SLAB": 17500,
    "CONC-COLUMN": 18500, "CONC-BEAM": 18500, "CONC-STAIR": 19000, "CONC-WALL": 18500, "REBAR": 165, "FORMWORK": 1150,
    "BLOCKWORK-EXT": 1950, "BLOCKWORK-INT": 1600, "BRICKWORK-EXT": 3400, "BRICKWORK-INT": 3000,
    "STONEWORK-EXT": 2700, "STONEWORK-INT": 2400, "LINTEL": 1500, "PLASTER": 520, "RENDER": 650,
    "PAINT-INT": 330, "PAINT-EXT": 420, "SCREED": 750, "CEILING": 1650, "ROOF-SHEETS": 1350, "ROOF-TILES": 2300,
    "ROOF-TIMBER": 480, "RIDGE": 900, "GUTTER": 1400, "FASCIA": 950, "DOOR-SINGLE": 32000, "DOOR-DOUBLE": 68000,
    "DOOR-SLIDING": 85000, "DOOR-ARCHED": 75000, "DOOR-FIRE": 78000, "WINDOW-FIXED": 7500, "WINDOW-CASEMENT": 9500,
    "WINDOW-SLIDING": 11000, "WINDOW-HUNG": 12500,
    # landscaping
    "TOPSOIL": 2200, "MULCH": 3500, "PLANTS-FLOWER": 150, "SHRUBS": 450, "HEDGE": 250, "GRASS": 450,
    "BED-EDGING": 850, "TREE": 3500, "TREE-PIT": 1800, "PAVING": 2400, "ROAD-MARKING": 1500,
    # finishes and building services
    "FLOOR-TILES": 2800, "WALL-TILES": 3000, "SANITARY-SET": 65000, "KITCHEN-UNIT": 180000, "ELEC-INSTALL": 4500,
    "PLUMB-INSTALL": 3500, "FIRE-PROTECTION": 900, "LIFT-STOP": 1100000, "EXTRACT-FAN": 18000,
    "MANHOLE": 45000, "DRAIN-PIPE": 2800, "SEWER-CONNECTION": 250000, "SOAKAWAY": 180000, "DOWNPIPE": 1800,
    "WATER-TANK": 28000, "BOOSTER-PUMP": 650000, "HOSE-REEL": 95000, "FIRE-EXTINGUISHER": 18000,
    "FIRE-ALARM-POINT": 12000, "SMOKE-VENT": 350000, "DRY-RISER": 6500, "FIRE-INLET": 180000, "GENERATOR": 4500000,
    "TRANSFORMER": 6500000, "LIGHTNING": 450000, "SOFFIT-SKIM": 450,
    # ---- dams (earthfill) ----------------------------------------------------------------------------------------
    "DIVERSION": 1500000, "DAM-CLEARING": 60, "RESERVOIR-CLEARING": 30, "DAM-STRIP": 400, "CUTOFF-EXC": 700,
    "DAM-CORE": 950, "DAM-SHELL": 650, "DAM-FILTER": 3500, "DAM-DRAIN": 4000, "DAM-RIPRAP": 4500, "DAM-BEDDING": 3500,
    "DAM-CREST": 1200, "DAM-GRASS": 250, "TOE-DRAIN": 3500, "SPILL-EXC": 800, "SPILL-CONC": 18000, "SPILL-REBAR": 165,
    "OUTLET-PIPE-300": 40000, "OUTLET-PIPE-400": 52000, "OUTLET-PIPE-500": 65000, "OUTLET-PIPE-600": 80000,
    "OUTLET-PIPE-800": 110000, "OUTLET-WORKS": 6500000, "PIEZOMETER": 150000, "SPILL-FORMWORK": 1300,
    "SEEPAGE-WEIR": 350000, "RESERVOIR-GAUGE": 650000, "INVESTIGATIONS": 4500000, "LAND-COMP": 1500000, "SETTLEMENT-PIN": 15000, "DAM-FENCE": 2500, "STEEL-STRUCT": 380, "DOOR-FD30": 52000, "DOOR-FIRE-DOUBLE": 145000, "CHANNEL-DRAIN": 6500, "KERB": 1400,
    "ANTI-TERMITE": 250, "LIFT-PIT": 450000, "EXT-LIGHTING": 45000, "BIN-STORE": 350000, "WATERPROOFING": 2600, "BALUSTRADE": 9500, "BOUNDARY-WALL": 18000, "GATE": 350000,
    # ---- water supply ----------------------------------------------------------------------------------------
    "PIPE-HDPE-DN20": 120, "PIPE-HDPE-DN25": 160, "PIPE-HDPE-DN32": 230, "PIPE-HDPE-DN50": 480, "PIPE-HDPE-DN63": 720,
    "PIPE-HDPE-DN90": 1350, "PIPE-HDPE-DN110": 1950, "PIPE-HDPE-DN160": 3900, "PIPE-HDPE-DN200": 6100,
    "PIPE-HDPE-DN250": 9400, "PIPE-HDPE-DN315": 14800, "VALVE-CHAMBER": 65000, "JUNCTION-CHAMBER": 45000,
    "PRV-STATION": 480000, "METER-CONNECTION": 9500, "AIR-VALVE": 55000, "RESERVOIR": 4500000, "MARKER-POST": 2500,
    "ROAD-X": 95000, "CIVIL-TRENCH": 1200,
    # ---- pipelines ---------------------------------------------------------------------------------------------
    "PIPE-STEEL-DN50": 4200, "PIPE-STEEL-DN80": 6500, "PIPE-STEEL-DN100": 8800, "PIPE-STEEL-DN150": 14500,
    "PIPE-STEEL-DN200": 21000, "PIPE-STEEL-DN250": 28500, "PIPE-STEEL-DN300": 36000, "PIPE-STEEL-DN400": 52000,
    "BLOCK-VALVE": 1600000, "TIE-IN": 650000, "PUMP-STATION": 18000000, "OFFTAKE": 950000, "CP-TEST-POINT": 35000,
    "TERMINAL": 15000000,
    # ---- electricity -------------------------------------------------------------------------------------------
    "COND-16MM": 140, "COND-25MM": 190, "COND-35MM": 250, "COND-50MM": 340, "COND-70MM": 460, "COND-100MM": 640,
    "COND-150MM": 950, "POLE-NEW": 19500, "SUSPENSION-CLAMP": 2400, "DEAD-END-CLAMP": 3600, "CROSS-ARM": 4800,
    "STAY-SET": 7800, "TX-25KVA": 480000, "TX-50KVA": 720000, "TX-100KVA": 1150000, "TX-200KVA": 1900000,
    "TX-315KVA": 2600000, "TX-500KVA": 3800000, "RMU": 1900000, "FEEDER-PILLAR": 230000, "SERVICE-POINT": 8500,
    "EARTHING": 11000, "SUBSTATION": 12000000,
    # ---- street lighting ---------------------------------------------------------------------------------------
    "LV-ARMOURED-4MM": 480, "LV-ARMOURED-6MM": 650, "LV-ARMOURED-10MM": 950, "LV-ARMOURED-16MM": 1400,
    "LV-ARMOURED-25MM": 2100, "LV-ARMOURED-35MM": 2800, "LIGHT-COLUMN": 58000, "LUMINAIRE-30W": 17000,
    "LUMINAIRE-60W": 24000, "LUMINAIRE-90W": 31000, "LUMINAIRE-120W": 38000, "LUMINAIRE-150W": 46000,
    "CUT-OUT": 3800, "CONTROL-CABINET": 125000, "SUPPLY-POINT": 85000,
    # ---- sanitation --------------------------------------------------------------------------------------------
    "SEWER-UPVC-DN110": 950, "SEWER-UPVC-DN160": 1700, "SEWER-UPVC-DN200": 2600, "SEWER-UPVC-DN250": 3900,
    "SEWER-UPVC-DN300": 5400, "SEWER-UPVC-DN400": 8600, "MANHOLE": 95000, "INSPECTION-CHAMBER": 26000,
    "HOUSE-CONNECTION": 16000, "VENT": 12000, "TREATMENT-WORKS": 45000000,
}
# items whose price differs by sector (a sewage pump station is not a pipeline one)
BY_SECTOR: dict[str, dict[str, float]] = {
    "sanitation": {"PUMP-STATION": 8500000, "ROAD-X": 140000, "CIVIL-TRENCH": 1600},
    "pipelines": {"ROAD-X": 260000, "CIVIL-TRENCH": 2600, "MARKER-POST": 3500},
    "electricity": {"ROAD-X": 65000},
    "lighting": {"ROAD-X": 65000, "CIVIL-TRENCH": 1000, "FEEDER-PILLAR": 180000, "EARTHING": 9000},
}


def rate(sector: str, code: str) -> float | None:
    return BY_SECTOR.get(sector, {}).get(code, INDICATIVE.get(code))


class RateError(ValueError):
    pass


def fill(d: Design) -> dict:
    """Give every material with no rate its indicative rate, and add the sector's catalogue items the project is
    missing. Returns what changed."""
    if (d.info.currency or CURRENCY).upper() != CURRENCY:
        raise RateError(f"The indicative rates are in {CURRENCY}; this project is priced in {d.info.currency}")
    sec = d.info.sector
    have = {m.code for m in d.materials}
    added = [m.model_copy() for m in sectors.get(sec).get("materials", []) if m.code not in have]
    d.materials += added
    filled = []
    for m in d.materials:
        r = rate(sec, m.code)
        if not m.rate and r:
            m.rate = float(r)
            filled.append(m.code)
    return {"filled": filled, "added": [m.code for m in added], "note": NOTE}
