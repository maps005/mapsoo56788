"""Earthfill embankment dams: the survey (the ground along the dam axis, the reservoir's elevation-area table),
hydrology, the reservoir, spillway, freeboard and crest, the zoned embankment, seepage, slope stability, the
outlet, and the quantities.

The design is the preliminary design of a small to medium earth dam by the usual methods (USBR "Design of Small
Dams", ICOLD bulletins, Kenyan practice): Rational-method design flood with the Kirpich time of concentration and
Mononobe intensity; a broad-crested side spillway; Molitor-Stevenson waves for the freeboard; USBR crest width; a
central clay core with chimney and blanket filters, upstream riprap; Dupuit seepage through the core; simplified
Bishop slip circles with pore-pressure ratios for end of construction, steady seepage and rapid drawdown, the
slopes flattened until each case has its factor of safety. The registered dam engineer's design, the
geotechnical and hydrological investigations, and the Water Resources Authority's dam safety approval govern.
"""
from __future__ import annotations

import copy
import math
from typing import Optional

from pydantic import BaseModel, Field, field_validator

G = 9.81
GAMMA_W = 9.81


class Dam(BaseModel):
    """An earthfill dam and its site, as the engineer enters them."""
    name: str = Field(default="Earth dam", max_length=120)
    river: str = Field(default="", max_length=120)
    axis_start: Optional[list[float]] = None   # [lat, lon] of chainage 0 (the left abutment, looking downstream)
    axis_end: Optional[list[float]] = None     # [lat, lon] of the right abutment
    # survey: along the axis [chainage m, ground level m, depth to firm ground m]; reservoir [level m, area m2]
    axis: list[list[float]] = Field(default_factory=list, max_length=500)
    reservoir: list[list[float]] = Field(default_factory=list, max_length=500)
    # hydrology
    catchment_km2: float = Field(default=0.0, ge=0, le=100000)
    stream_km: float = Field(default=0.0, ge=0, le=1000)            # longest watercourse to the dam
    stream_slope: float = Field(default=0.0, ge=0, le=100)          # its average slope, %
    rain_24h: float = Field(default=0.0, ge=0, le=1000)             # design storm, 24 h, mm (1 in 100 years)
    rain_annual: float = Field(default=0.0, ge=0, le=5000)          # mean annual rainfall, mm
    runoff_flood: float = Field(default=0.5, gt=0, le=1)            # Rational C for the flood
    runoff_annual: float = Field(default=0.1, gt=0, le=1)           # share of the annual rain that runs off
    evaporation: float = Field(default=1800.0, ge=0, le=4000)       # open water, mm a year
    demand: float = Field(default=0.0, ge=0, le=1e7)                # m3 a day drawn off
    design_flood: float = Field(default=0.0, ge=0, le=1e5)          # m3/s; 0: by the Rational method
    # reservoir levels
    fsl: float = Field(default=0.0)                                 # full supply level (spillway crest), m; 0: from target
    target_storage: float = Field(default=0.0, ge=0)                # m3 at FSL, when FSL is 0
    outlet_level: float = Field(default=0.0)                        # invert of the draw-off (minimum operating level), m
    # embankment
    crest_width: float = Field(default=0.0, ge=0, le=30)            # m; 0: USBR W = H/5 + 3
    slope_us: float = Field(default=3.0, ge=1.5, le=6)              # horizontal : 1 vertical (the design may flatten)
    slope_ds: float = Field(default=2.5, ge=1.5, le=6)
    core_top: float = Field(default=3.0, ge=1, le=10)               # m
    core_slope: float = Field(default=0.5, ge=0, le=2)              # each side, H:1V
    filter_width: float = Field(default=1.0, ge=0.3, le=3)          # chimney filter, m
    riprap: float = Field(default=0.6, ge=0, le=2)                  # m, on 0.3 m bedding
    cutoff_width: float = Field(default=4.0, ge=2, le=15)           # cut-off trench bottom, m
    wind_kmh: float = Field(default=80.0, ge=0, le=250)
    # materials (the geotechnical report's)
    shell_phi: float = Field(default=30.0, gt=10, le=45)            # degrees
    shell_c: float = Field(default=0.0, ge=0, le=100)               # kPa, effective (0: no cohesion relied on)
    shell_gamma: float = Field(default=19.5, gt=14, le=24)          # kN/m3
    core_k: float = Field(default=1e-8, gt=0, le=1e-3)              # m/s
    # spillway and outlet
    spillway_width: float = Field(default=0.0, ge=0, le=500)        # m; 0: wide enough for the head below
    spillway_head: float = Field(default=1.0, gt=0.2, le=5)         # m, the design flood's head over the crest
    spillway_c: float = Field(default=1.7, gt=1.0, le=2.2)          # broad-crested weir, SI
    spillway_side: str = Field(default="right", pattern="^(left|right)$")
    # safety, sediment and the outlet
    hazard: str = Field(default="high", pattern="^(low|significant|high)$")  # by what a breach would do downstream
    rain_cv: float = Field(default=0.35, gt=0.1, le=1.0)            # coefficient of variation of annual 24 h maxima
    sediment_yield: float = Field(default=300.0, ge=0, le=10000)     # t/km2 a year
    sediment_years: int = Field(default=50, ge=10, le=200)
    fetch_km: float = Field(default=0.0, ge=0, le=100)               # effective fetch from the contour plan; 0: estimated
    compensation: float = Field(default=0.0, ge=0, le=1e7)           # m3 a day released downstream (reserve flow)
    seismic_kh: float = Field(default=0.05, ge=0, le=0.5)            # pseudo-static coefficient (about ag / 2)

    @field_validator("axis", "reservoir")
    @classmethod
    def _rows(cls, v):
        return [[float(x) for x in r] for r in v if len(r) >= 2]


# ---------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------
def _interp(x, xs, ys):
    if not xs:
        return 0.0
    if x <= xs[0]:
        return ys[0]
    for (a, fa), (b, fb) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if a <= x <= b:
            return fa + (fb - fa) * (x - a) / (b - a) if b > a else fb
    return ys[-1]


def capacity(dm: Dam) -> list[tuple[float, float, float]]:
    """The elevation-area-capacity table: (level, area m2, volume m3), volumes by the average end areas from
    the lowest surveyed level (area 0 at the river bed)."""
    rows = sorted((r[0], max(0.0, r[1])) for r in dm.reservoir)
    out, vol = [], 0.0
    for i, (lv, a) in enumerate(rows):
        if i:
            lv0, a0 = rows[i - 1]
            vol += (a0 + a + math.sqrt(a0 * a)) / 3 * (lv - lv0)  # prismoidal (frustum) formula
        out.append((lv, a, vol))
    return out


def _round_up(v, step):
    return math.ceil(v / step - 1e-9) * step


# ---------------------------------------------------------------------------------------------------------
# slope stability: simplified Bishop, circles through the toe zone of the maximum section
# ---------------------------------------------------------------------------------------------------------
def _bishop(H, slope, crest, gamma, c, phi, ru, n_slices=30, kh=0.0):
    """The least factor of safety of circles cutting the face of a slope H high at `slope` H:1V (a homogeneous
    shell, the crest beyond it), with pore pressure ratio ru: simplified Bishop."""
    tphi = math.tan(math.radians(phi))
    # the section: the toe at (0, 0), the crest edge at (slope H, H), the crest level beyond
    def ground(x):
        return 0.0 if x <= 0 else min(H, x / slope)
    best = math.inf
    for fx in (0.2, 0.4, 0.6, 0.8, 1.0):
        for fy in (1.0, 1.4, 1.8, 2.4, 3.2):
            xc, yc = slope * H * fx, H * fy  # centres above the face
            for exit_x in (-0.6 * H, -0.3 * H, -0.1 * H, 0.0):  # at or ahead of the toe: deep circles too
                R = math.hypot(xc - exit_x, yc)
                # where the circle meets the ground again (up the face or on the crest)
                x_end = None
                xs = exit_x
                while xs < slope * H + crest:
                    xs += H / 40
                    yb = yc - math.sqrt(max(0.0, R * R - (xs - xc) ** 2))
                    if yb >= ground(xs) and xs > exit_x + H / 20:
                        x_end = xs
                        break
                if x_end is None or x_end - exit_x < H * 0.3:
                    continue
                b = (x_end - exit_x) / n_slices
                slices = []
                for i in range(n_slices):
                    xm = exit_x + (i + 0.5) * b
                    yb = yc - math.sqrt(max(0.0, R * R - (xm - xc) ** 2))
                    h = ground(xm) - yb
                    if h <= 0:
                        continue
                    alpha = math.asin(max(-0.99, min(0.99, (xm - xc) / R)))
                    slices.append((gamma * h * b, alpha, yc - (yb + ground(xm)) / 2))
                if not slices:
                    continue
                drive = sum(W * math.sin(a) + kh * W * arm / R for W, a, arm in slices)  # + the earthquake
                if drive <= 0:
                    continue
                F = 1.5
                for _ in range(30):  # the factor appears on both sides: iterate
                    res = 0.0
                    for W, a, h in slices:
                        m = math.cos(a) * (1 + math.tan(a) * tphi / F)
                        res += (c * b + W * (1 - ru) * tphi) / max(m, 0.2)
                    F2 = res / drive
                    if abs(F2 - F) < 1e-4:
                        break
                    F = F2
                best = min(best, F)
    return best


STABILITY_CASES = (  # (case, face, pore pressure ratio, required F, earthquake?): USACE EM 1110-2-1902 minima
    ("End of construction", "upstream", 0.30, 1.3, False),
    ("End of construction", "downstream", 0.30, 1.3, False),
    ("Steady seepage, full reservoir", "downstream", 0.10, 1.5, False),
    ("Steady seepage, full reservoir", "upstream", 0.20, 1.5, False),
    ("Rapid drawdown", "upstream", 0.40, 1.2, False),
    ("Earthquake, full reservoir (pseudo-static)", "downstream", 0.10, 1.1, True),
)


FLOOD_T = {"low": (100, 1000), "significant": (500, 5000), "high": (1000, 10000)}  # design, safety check (years)


def growth(T: float, cv: float) -> float:
    """EV1 (Gumbel) growth factor of a rainfall depth for return period T, relative to the mean."""
    K = -math.sqrt(6) / math.pi * (0.5772 + math.log(math.log(T / (T - 1))))
    return 1 + cv * K


# ---------------------------------------------------------------------------------------------------------
# the design
# ---------------------------------------------------------------------------------------------------------
_DESIGNS: dict[str, Optional[dict]] = {}  # by the dam's data: a page load asks for the design several times


def design(dm: Dam) -> Optional[dict]:
    """The preliminary design, or None without a survey (the axis profile and the reservoir table)."""
    if len(dm.axis) < 2 or len(dm.reservoir) < 2:
        return None
    key = dm.model_dump_json()
    if key not in _DESIGNS:
        if len(_DESIGNS) > 64:
            _DESIGNS.clear()
        _DESIGNS[key] = _design(dm)
    return copy.deepcopy(_DESIGNS[key])


def _design(dm: Dam) -> Optional[dict]:
    axis = sorted(dm.axis)
    ch = [r[0] for r in axis]
    gl = [r[1] for r in axis]
    firm = [r[2] if len(r) > 2 else 1.0 for r in axis]
    bed = min(gl)
    cap = capacity(dm)
    levels, areas, vols = [r[0] for r in cap], [r[1] for r in cap], [r[2] for r in cap]
    notes = []
    # ---- reservoir levels
    if dm.fsl:
        fsl = dm.fsl
    elif dm.target_storage and vols[-1] >= dm.target_storage:
        fsl = round(_interp(dm.target_storage, vols, levels), 2)
    else:
        fsl = round(levels[0] + 0.7 * (levels[-1] - levels[0]), 2)
        notes.append("No full supply level or target storage: FSL taken at 70 % of the surveyed range")
    v_sed = dm.catchment_km2 * dm.sediment_yield * dm.sediment_years / 1.3  # m3 at 1.3 t/m3 deposited
    sed_level = _interp(v_sed, vols, levels) if v_sed else bed
    mol = max(dm.outlet_level or round(bed + 1.5, 2), round(sed_level + 1.0, 2))  # the intake clear of the sediment
    v_fsl, a_fsl = _interp(fsl, levels, vols), _interp(fsl, levels, areas)
    v_dead = _interp(mol, levels, vols)
    live = v_fsl - v_dead
    # ---- hydrology: the design flood by the Rational method (Kirpich tc, Mononobe intensity)
    A = dm.catchment_km2
    L_m = dm.stream_km * 1000
    S = max(dm.stream_slope / 100, 1e-4)
    tc_min = 0.0195 * L_m ** 0.77 * S ** -0.385 if L_m else 60.0
    tc_h = max(tc_min / 60, 0.25)
    T_des, T_chk = FLOOD_T[dm.hazard]
    p_des = dm.rain_24h * growth(T_des, dm.rain_cv) / growth(100, dm.rain_cv)  # the storm for the hazard class
    p_chk = dm.rain_24h * growth(T_chk, dm.rain_cv) / growth(100, dm.rain_cv)
    inten = p_des / 24 * (24 / tc_h) ** (2 / 3) if dm.rain_24h else 0.0  # mm/h, Mononobe
    inten_chk = p_chk / 24 * (24 / tc_h) ** (2 / 3) if dm.rain_24h else 0.0
    c_chk = min(0.9, dm.runoff_flood * 1.2)  # wetter ground in the rarer storm
    q_rational = 0.278 * dm.runoff_flood * inten * A
    q100 = dm.design_flood or q_rational  # the design flood (the hazard class's return period)
    q_check = (dm.design_flood * 1.8 if dm.design_flood else 0.278 * c_chk * inten_chk * A)  # safety check flood
    if A > 15 and not dm.design_flood:
        notes.append(f"Catchment {A:g} km2 is beyond the Rational method's usual 15 km2: confirm the flood by the "
                     "TRRL East African flood model or a unit hydrograph")
    # ---- spillway: broad-crested weir at FSL, no routing attenuation (conservative)
    C = dm.spillway_c
    width = dm.spillway_width or max(5.0, _round_up(q100 / (C * dm.spillway_head ** 1.5), 1.0))
    h100 = (q100 / (C * width)) ** (2 / 3) if q100 else 0.0
    h_chk = (q_check / (C * width)) ** (2 / 3) if q100 else 0.0
    mfl = fsl + h100
    v_spill = q100 / (width * max(h100 * 2 / 3, 0.05)) if q100 else 0.0  # velocity at critical depth
    # the chute down to the river and the hydraulic jump in the stilling basin (USBR type II/III proportions)
    drop = max(1.0, fsl - bed)
    v1 = 0.9 * math.sqrt(2 * G * (drop + h100)) if q100 else 0.0
    q_unit = q100 / width if width else 0.0
    y1 = q_unit / v1 if v1 else 0.0
    fr1 = v1 / math.sqrt(G * y1) if y1 else 0.0
    y2 = y1 / 2 * (math.sqrt(1 + 8 * fr1 * fr1) - 1) if y1 else 0.0
    basin_len = max(6.0, 4.5 * y2)
    chute_len = max(30.0, drop * 4)  # about 1 in 4
    side = (gl[-1] if dm.spillway_side == "right" else gl[0])
    cut_spill = max(0.0, side - fsl)  # the cut through the abutment to the crest
    # ---- freeboard: Molitor-Stevenson significant wave, run-up on riprap 1.5 hw
    fetch = dm.fetch_km or (2 * math.sqrt(a_fsl / math.pi) / 1000 if a_fsl else 0.5)  # km (estimate: equal circle)
    U = dm.wind_kmh
    hw = max(0.0, 0.032 * math.sqrt(U * fetch) + 0.763 - 0.271 * fetch ** 0.25) if fetch < 32 else 0.032 * math.sqrt(U * fetch)
    runup = 1.5 * hw
    # riprap by Hudson: W50 = gamma_r H3 / (KD delta3 cot a), quarry rock 26 kN/m3, KD 2.2; two stones thick
    gr, KD = 26.0, 2.2
    w50 = gr * hw ** 3 / (KD * (gr / GAMMA_W - 1) ** 3 * dm.slope_us) if hw else 0.0
    d50 = (w50 / gr) ** (1 / 3) if w50 else 0.0
    riprap_t = max(dm.riprap, round(_round_up(2 * d50, 0.05), 2), 0.45)
    crest_normal = fsl + runup + 0.5
    crest_flood = mfl + 0.5 * runup + 0.5
    crest_check = fsl + h_chk + 0.3
    crest = _round_up(max(crest_normal, crest_flood, crest_check, fsl + 1.5), 0.1)
    height = crest - bed
    camber = round(max(0.01 * height, 0.15), 2)  # settlement allowance, built in
    # ---- embankment
    W = dm.crest_width or max(4.0, _round_up(height / 5 + 3, 0.5))
    # slopes: flattened in 0.25 steps until every stability case passes
    su, sd = dm.slope_us, dm.slope_ds
    stab = []
    for _ in range(20):
        stab = []
        for case, face, ru, need, quake in STABILITY_CASES:
            slope = su if face == "upstream" else sd
            F = _bishop(height, slope, W, dm.shell_gamma, dm.shell_c, dm.shell_phi, ru, kh=dm.seismic_kh if quake else 0.0)
            stab.append({"case": case, "face": face, "ru": ru, "F": round(F, 2), "need": need, "slope": slope, "ok": F >= need})
        bad = [s for s in stab if not s["ok"]]
        if not bad:
            break
        if any(s["face"] == "upstream" for s in bad):
            su += 0.25
        if any(s["face"] == "downstream" for s in bad):
            sd += 0.25
    if su > dm.slope_us or sd > dm.slope_ds:
        notes.append(f"Slopes flattened to {su:g}:1 upstream and {sd:g}:1 downstream for stability")
    # ---- sections along the axis, with the points where the ground rises through the crest level added (the
    # embankment's ends meet the abutments there)
    core_top_level = min(crest - 0.3, max(mfl + 0.3, fsl + h_chk + 0.2, fsl + 0.5))  # above the check flood
    pts = []
    for i, (c_, g_, f_) in enumerate(zip(ch, gl, firm)):
        if i and (gl[i - 1] - crest) * (g_ - crest) < 0:
            t = (crest - gl[i - 1]) / (g_ - gl[i - 1])
            pts.append((ch[i - 1] + t * (c_ - ch[i - 1]), crest, firm[i - 1] + t * (f_ - firm[i - 1])))
        pts.append((c_, g_, f_))
    sections = []
    for c_, g_, f_ in pts:
        h = max(0.0, crest - g_)
        hc = max(0.0, core_top_level - g_)
        total = W * h + 0.5 * (su + sd) * h * h
        core = dm.core_top * hc + dm.core_slope * hc * hc
        chimney = dm.filter_width * hc * math.sqrt(1 + dm.core_slope ** 2) if hc else 0.0
        blanket_len = max(0.0, W / 2 + sd * h - (dm.core_top / 2 + dm.core_slope * hc + dm.filter_width))
        blanket = 0.6 * blanket_len  # gravel, to the toe drain
        blanket_sand = 0.3 * blanket_len  # the sand layer under it
        h_rip = max(0.0, crest - max(g_, mol - 1.5))
        riprap = riprap_t * h_rip * math.sqrt(1 + su * su)
        bedding = 0.3 * h_rip * math.sqrt(1 + su * su)
        shell = max(0.0, total - core - chimney - blanket - blanket_sand - riprap - bedding)
        d_cut = f_ + 0.5 if h > 0 else 0.0  # into firm ground
        cutoff = d_cut * (dm.cutoff_width + d_cut)
        base = W + (su + sd) * h
        sections.append({"ch": c_, "ground": g_, "firm": f_, "h": h, "total": total, "core": core, "chimney": chimney,
                         "blanket": blanket, "blanket_sand": blanket_sand, "riprap": riprap, "bedding": bedding, "shell": shell, "cutoff": cutoff,
                         "base": base, "ds_face": h * math.sqrt(1 + sd * sd), "cut_depth": d_cut})

    def along(key):  # volume (or area) along the axis by average end areas
        return sum((a[key] + b[key]) / 2 * (b["ch"] - a["ch"]) for a, b in zip(sections, sections[1:]))
    # where the crest meets the ground: the crest length
    wet = [s for s in sections if s["ground"] <= crest + 1e-6]  # the embankment, abutment to abutment
    crest_len = (wet[-1]["ch"] - wet[0]["ch"]) if wet else 0.0
    if gl[0] < crest or gl[-1] < crest:
        notes.append("The crest is above the ground at an end of the surveyed axis: extend the survey into the abutments")
    # ---- seepage through the core (Dupuit, no tailwater) along the axis
    q_seep = 0.0
    for a, b in zip(sections, sections[1:]):
        for s in (a, b):
            h1 = max(0.0, fsl - s["ground"])
            Lc = dm.core_top + 2 * dm.core_slope * max(0.0, core_top_level - s["ground"]) / 2
            s["q"] = dm.core_k * h1 * h1 / (2 * max(Lc, 1.0))
        q_seep += (a["q"] + b["q"]) / 2 * (b["ch"] - a["ch"])
    # ---- outlet: the demand (and compensation flow) at the minimum head, drawdown
    q_out = (dm.demand * 1.1 + dm.compensation) / 86400 * 1.5  # raw water (10 % treatment losses) + reserve, peak 1.5
    head_min = max(0.5, mol - (mol - 1.0))  # 1 m of water over the outlet at MOL
    area_req = q_out / (0.6 * math.sqrt(2 * G * head_min)) if q_out else 0.0
    dn = next((d for d in (150, 200, 250, 300, 400, 500, 600, 800) if math.pi * (d / 1000) ** 2 / 4 >= area_req), 800)
    dn = max(dn, 300)  # 300 mm at least: maintainable, and the emergency drawdown
    head_mean = max(1.0, (fsl - (mol - 1.0)) / 2)
    base_len = max((s["base"] for s in sections), default=50.0) + 10
    loss = 1 + 1.5 + 0.02 * base_len / (dn / 1000)  # exit, entrance and valves, friction (Darcy f 0.02)
    q_drain = math.pi * (dn / 1000) ** 2 / 4 * math.sqrt(2 * G * head_mean / loss)
    drawdown_days = live / max(q_drain, 1e-6) / 86400
    # ---- yield
    inflow = A * 1e6 * dm.rain_annual / 1000 * dm.runoff_annual
    evap = a_fsl * 0.7 * dm.evaporation / 1000  # on the mean water area, about 70 % of the full area
    use = dm.demand * 365
    dry = (dm.demand * 180) + evap / 2  # a six-month dry season
    # ---- classification (ICOLD large dam: 15 m high, or 5 m with more than 3 Mm3)
    h_fdn = crest - min(g - f - 0.5 for g, f in zip(gl, firm))  # ICOLD: from the lowest point of the foundation
    large = h_fdn >= 15 or (h_fdn >= 5 and v_fsl > 3e6)
    out = {
        "bed": bed, "fsl": fsl, "mol": mol, "mfl": round(mfl, 2), "crest": round(crest, 2), "height": round(height, 2),
        "camber": camber, "crest_width": W, "crest_length": round(crest_len, 1), "slope_us": su, "slope_ds": sd,
        "core_top_level": round(core_top_level, 2), "storage": round(v_fsl), "area_fsl": round(a_fsl), "dead": round(v_dead),
        "live": round(live), "capacity": cap,
        "hydrology": {"tc_min": round(tc_min, 1), "intensity": round(inten, 1), "q_rational": round(q_rational, 1),
                      "q100": round(q100, 1), "q_check": round(q_check, 1), "catchment": A},
        "spillway": {"width": width, "h100": round(h100, 2), "h_check": round(h_chk, 2), "velocity": round(v_spill, 2),
                     "crest": fsl, "side": dm.spillway_side, "C": C, "drop": round(drop, 2), "v1": round(v1, 2),
                     "y1": round(y1, 3), "fr1": round(fr1, 2), "y2": round(y2, 2), "basin_len": round(basin_len, 1),
                     "chute_len": round(chute_len, 1), "cut": round(cut_spill, 2), "wall": round(1.2 * y2 + 0.5, 2)},
        "flood": {"hazard": dm.hazard, "T_design": T_des, "T_check": T_chk, "p_design": round(p_des, 1), "p_check": round(p_chk, 1),
                  "i_check": round(inten_chk, 1), "c_check": round(c_chk, 2)},
        "sediment": {"volume": round(v_sed), "level": round(sed_level, 2), "years": dm.sediment_years},
        "riprap": {"w50_kn": round(w50, 3), "d50": round(d50, 2), "thickness": riprap_t},
        "foundation_height": round(h_fdn, 2),
        "freeboard": {"fetch_km": round(fetch, 2), "wave": round(hw, 2), "runup": round(runup, 2),
                      "normal": round(crest_normal, 2), "flood": round(crest_flood, 2), "check": round(crest_check, 2),
                      "above_fsl": round(crest - fsl, 2), "above_mfl": round(crest - mfl, 2)},
        "stability": stab,
        "seepage_m3_day": round(q_seep * 86400, 1),
        "outlet": {"q": round(q_out, 4), "dn": dn, "drawdown_days": round(drawdown_days, 1), "length": round(base_len, 1),
                   "q_drain": round(q_drain, 3)},
        "yield": {"inflow": round(inflow), "evaporation": round(evap), "demand": round(use), "dry_season": round(dry),
                  "ok": inflow >= use + evap and live >= dry},
        "large_dam": large,
        "sections": sections,
        "volumes": {k: round(along(k)) for k in ("total", "core", "chimney", "blanket", "blanket_sand", "riprap", "bedding",
                                                  "shell", "cutoff")},
        "footprint": round(along("base")), "ds_face_area": round(along("ds_face")),
        "notes": notes,
    }
    return out


def quantities(dm: Dam) -> list[tuple[str, float, str]]:
    """(material code, quantity, how it was measured) for the BOQ."""
    z = design(dm)
    if not z:
        return []
    v = z["volumes"]
    sp = z["spillway"]
    out = []

    def add(code, q, src):
        if q > 1e-9:
            out.append((code, round(q, 2), src))
    add("DIVERSION", 1, "River diversion and care of water during construction")
    add("DAM-CLEARING", z["footprint"] * 1.2, "Clearing and grubbing the dam footprint and borrow approaches")
    add("RESERVOIR-CLEARING", z["area_fsl"], "Clearing the reservoir basin to full supply level")
    add("DAM-STRIP", z["footprint"] * 0.3, "Stripping topsoil 300 mm under the embankment")
    add("CUTOFF-EXC", v["cutoff"], "Cut-off trench excavation into firm ground")
    add("DAM-CORE", v["core"] + v["cutoff"], "Selected clay, compacted in 150 mm layers: core and cut-off trench backfill")
    add("DAM-SHELL", v["shell"], "Embankment shell fill, compacted in 300 mm layers")
    add("DAM-FILTER", v["chimney"] + v["blanket_sand"] + 3 * (z["outlet"]["dn"] / 1000 + 3) ** 2,
        "Graded sand filter: chimney, the blanket's sand layer, the filter diaphragm round the conduit")
    add("DAM-DRAIN", v["blanket"], "Drainage blanket, graded gravel, to the toe drain")
    add("DAM-RIPRAP", v["riprap"], f"Dumped rock riprap on the upstream face, {z['riprap']['thickness']:g} m "
                                   f"(Hudson D50 {z['riprap']['d50']:g} m)")
    add("DAM-BEDDING", v["bedding"], "Riprap bedding, graded gravel 300 mm")
    add("DAM-CREST", z["crest_width"] * z["crest_length"], "Crest road, gravel wearing course")
    add("DAM-GRASS", z["ds_face_area"], "Grassing the downstream face")
    add("TOE-DRAIN", z["crest_length"], "Downstream toe drain, perforated pipe in filter")
    approach = 40.0
    exc = (sp["width"] + sp["cut"]) * sp["cut"] * approach / 2 + sp["width"] * 1.0 * (sp["chute_len"] + sp["basin_len"])
    add("SPILL-EXC", exc, f"Spillway: the cut through the abutment ({sp['cut']:g} m to the crest, 40 m approach), chute and basin")
    sill = sp["width"] * 1.5 * 1.0
    chute = sp["width"] * sp["chute_len"] * 0.3 + 2 * sp["chute_len"] * 1.5 * 0.3
    basin = sp["width"] * sp["basin_len"] * 0.5 + 2 * sp["basin_len"] * sp["wall"] * 0.4 + sp["width"] * 1.0 * 0.6
    add("SPILL-CONC", sill + chute + basin, f"Spillway: crest sill, chute lining {sp['chute_len']:g} m, stilling basin "
                                          f"{sp['basin_len']:g} m with walls {sp['wall']:g} m and end sill")
    add("SPILL-REBAR", (sill + chute + basin) * 80, "Spillway reinforcement, 80 kg/m3")
    add("SPILL-FORMWORK", 2 * (2 * sp["chute_len"] * 1.5 + 2 * sp["basin_len"] * sp["wall"]) + sp["width"] * 3,
        "Formwork to the walls and the sill")
    base = max((s["base"] for s in z["sections"]), default=0.0)
    add(f"OUTLET-PIPE-{z['outlet']['dn']}", base + 10, f"DN{z['outlet']['dn']} steel outlet pipe, concrete surround, anti-seepage collars")
    add("OUTLET-WORKS", 1, "Multi-level intake tower with screens, upstream guard gate, valve chamber and control valves")
    add("PIEZOMETER", 9, "Piezometers in the core, foundation and downstream shell at three sections")
    add("SEEPAGE-WEIR", 1, "V-notch seepage measuring weir at the toe drain outfall")
    add("RESERVOIR-GAUGE", 1, "Reservoir staff gauges and level recorder")
    add("INVESTIGATIONS", 1, "Further site investigation: boreholes, permeability tests, borrow testing, topographic survey")
    add("LAND-COMP", (z["area_fsl"] + z["footprint"]) / 1e4 * 1.2, "Land and compensation: reservoir, dam and buffer (to valuation)")
    add("SETTLEMENT-PIN", max(4, math.ceil(z["crest_length"] / 25)), "Settlement monuments on the crest")
    add("DAM-FENCE", 2 * z["crest_length"] + 200, "Security fence round the dam and spillway")
    return out


def summary(dm: Optional[Dam]) -> Optional[dict]:
    """The figures the planner shows."""
    if dm is None:
        return None
    z = design(dm)
    if not z:
        return {"designed": False}
    return {"designed": True, **{k: z[k] for k in ("bed", "fsl", "mol", "mfl", "crest", "height", "crest_width",
                                                  "crest_length", "slope_us", "slope_ds", "storage", "live", "area_fsl",
                                                  "seepage_m3_day", "large_dam", "core_top_level", "camber")},
            "q100": z["hydrology"]["q100"], "q_check": z["hydrology"]["q_check"], "T_design": z["flood"]["T_design"],
            "T_check": z["flood"]["T_check"], "foundation_height": z["foundation_height"],
            "sediment_level": z["sediment"]["level"], "basin_len": z["spillway"]["basin_len"],
            "riprap": z["riprap"]["thickness"], "spillway_width": z["spillway"]["width"], "h100": z["spillway"]["h100"],
            "fill": z["volumes"]["total"], "outlet_dn": z["outlet"]["dn"], "yield_ok": z["yield"]["ok"],
            "stability": [{k: s[k] for k in ("case", "face", "F", "need", "ok")} for s in z["stability"]],
            "profile": [[s["ch"], s["ground"], s["ground"] - s["cut_depth"]] for s in z["sections"]],
            "capacity": [[round(a, 2), round(b), round(c)] for a, b, c in z["capacity"]], "notes": z["notes"]}


def check(dm: Optional[Dam]) -> list[tuple[str, str, str]]:
    """QA issues: (severity, code, message)."""
    if dm is None or len(dm.axis) < 2:
        return [("warning", "dam_no_survey", "Enter the ground profile along the dam axis (Site Survey & Hydrology)")]
    if len(dm.reservoir) < 2:
        return [("warning", "dam_no_reservoir", "Enter the reservoir's elevation-area table from the contour survey")]
    z = design(dm)
    out = []
    if not dm.catchment_km2 or not (dm.rain_24h or dm.design_flood):
        out.append(("error", "dam_no_flood", "Catchment area and design rainfall (or a design flood) are needed to size the spillway"))
    ends = sorted(dm.axis)
    if ends[0][1] < z["crest"] or ends[-1][1] < z["crest"]:
        out.append(("error", "dam_abutments", f"The ground at an end of the axis is below the crest ({z['crest']:g} m): "
                                              "extend the survey into the abutments or move the axis"))
    if z["freeboard"]["above_mfl"] < 0.5:
        out.append(("error", "dam_freeboard", f"Only {z['freeboard']['above_mfl']:g} m between the flood level and the crest"))
    for s_ in z["stability"]:
        if not s_["ok"]:
            out.append(("error", "dam_stability", f"{s_['case']} ({s_['face']}): F = {s_['F']:g}, {s_['need']:g} needed"))
    if z["spillway"]["h100"] > 2.0:
        out.append(("warning", "dam_spillway_head", f"{z['spillway']['h100']:g} m over the spillway crest at the design flood: widen it"))
    if z["spillway"]["velocity"] > 6:
        out.append(("warning", "dam_spillway_velocity", f"{z['spillway']['velocity']:g} m/s in the spillway: line it and add a stilling basin"))
    if not z["yield"]["ok"]:
        y = z["yield"]
        out.append(("warning", "dam_yield", f"Annual inflow {y['inflow']:,} m3 against use {y['demand']:,} + evaporation "
                                            f"{y['evaporation']:,} m3, or the live storage short of a 6-month dry season "
                                            f"({y['dry_season']:,} m3): reduce the demand or raise the FSL"))
    out.append(("warning", "dam_detailed_design", "Preliminary design: the detailed design still needs a monthly reservoir "
                                                  "simulation through a 1 in 20 drought, a zoned stability analysis on tested "
                                                  "strengths, foundation seepage and grouting, filter gradations, the flood "
                                                  "routed through the reservoir" + (", a dam-break and inundation study and an "
                                                  "emergency preparedness plan" if dm.hazard != "low" else "")))
    if z["sediment"]["level"] > z["mol"] - 1.0 + 1e-6:
        out.append(("warning", "dam_sediment", "The outlet is not clear of the 50-year sediment level"))
    if z["large_dam"]:
        out.append(("info", "dam_large", f"{z['foundation_height']:g} m above the foundation, {z['storage']:,} m3: a large dam (ICOLD); the Water Resources "
                                         "Authority's dam safety approval, a registered dam engineer and an emergency plan are required"))
    for n in z["notes"]:
        out.append(("warning", "dam_note", n))
    return out
