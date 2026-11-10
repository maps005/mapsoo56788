"""Survey and design report content, shared by the PDF, Word and Excel writers.

Narrative text comes only from what the planner entered in the project details; every figure and table is
derived from the recorded survey and design data. Nothing is invented: empty narrative fields are marked
"Not recorded" so a reviewer can see what is missing.

A section is a list of blocks, in order:
  ("p", text)                      paragraph
  ("missing", text)                planner text that was not entered
  ("h", text)                      sub-heading
  ("kv", [[label, value], ...])    two-column detail table
  ("table", headers, rows, total)  data table (total=True: last row is a total)
  ("cards", [(label, value), ...]) key figures
  ("bullets", [text, ...])         bullet list
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .. import calc, sectors, splicing, validate
from ..model import Design
from .common import NODE_LABEL, clean

NOT_RECORDED = "Not recorded."
KIND_LABEL = {"home": "Single dwelling", "mdu": "Multi-dwelling unit (MDU)", "business": "Business / institution"}
STYLE_LABEL = {"per_premise": "Per premise (every homepass gets a FAT port)",
               "coverage": "Coverage (outdoor FATs on poles sized by take rate)"}
MAX_ROWS = 400  # longest table printed; the full data is in the Excel deliverables


@dataclass
class Section:
    title: str
    blocks: list = field(default_factory=list)

    def p(self, text):
        self.blocks.append(("p", text))

    def text(self, value):
        """Planner-entered narrative, or the 'not recorded' marker."""
        self.blocks.append(("p", value, "planner") if value and value.strip() else ("missing", NOT_RECORDED))

    def h(self, text):
        self.blocks.append(("h", text))

    def kv(self, rows):
        self.blocks.append(("kv", [[k, v if v not in (None, "") else "Not recorded"] for k, v in rows]))

    def table(self, headers, rows, total=False):
        self.blocks.append(("table", headers, rows[:MAX_ROWS], total))
        if len(rows) > MAX_ROWS:
            self.p(f"Only the first {MAX_ROWS} of {len(rows)} rows are shown; the full list is in the Excel files.")

    def cards(self, items):
        self.blocks.append(("cards", items))

    def bullets(self, items):
        if items:
            self.blocks.append(("bullets", items))

    # older callers read paragraphs / tables directly
    @property
    def paragraphs(self) -> list[str]:
        return [b[1] for b in self.blocks if b[0] in ("p", "missing")]

    @property
    def tables(self) -> list[tuple[list[str], list[list]]]:
        return [(["Item", "Detail"], b[1]) if b[0] == "kv" else (b[1], b[2]) for b in self.blocks if b[0] in ("kv", "table")]


EXTERNAL_CODES = {"MANHOLE", "DRAIN-PIPE", "SEWER-CONNECTION", "SOAKAWAY", "BOUNDARY-WALL", "GATE", "PAVING",
                  "ROAD-MARKING", "TOPSOIL", "MULCH", "PLANTS-FLOWER", "SHRUBS", "HEDGE", "GRASS", "BED-EDGING", "TREE",
                  "TREE-PIT", "TRANSFORMER", "CHANNEL-DRAIN", "KERB", "EXT-LIGHTING", "BIN-STORE"}


def project_cost(total: float) -> dict:
    """The construction cost from the measured work: preliminaries 10 % and contingency 7.5 % of it, VAT 16 % on
    the lot (the one figure the report, the budget check and the summary use)."""
    pre, cont = 0.10 * total, 0.075 * total
    vat = 0.16 * (total + pre + cont)
    return {"pre": pre, "cont": cont, "vat": vat, "whole": total + pre + cont + vat}


def _m(v: float) -> str:
    return f"{v:,.0f} m"


def _feeding_pon(idx, splitter_id: str) -> str:
    """The 1st-stage splitter whose output feeds a 2nd-stage splitter ('' if not allocated)."""
    cur, prev, seen = splicing.End(kind="splitter_in", ref=splitter_id), None, set()
    for _ in range(200):
        nxt = [(c, o) for c, o in idx.get(splicing._key(cur), []) if c.id != prev]
        if not nxt or nxt[0][0].id in seen:
            return ""
        conn, other = nxt[0]
        seen.add(conn.id)
        if other.kind == "splitter_out":
            return other.ref
        if other.kind != "cable":
            return ""
        cur, prev = other, conn.id
    return ""


def _building_sections(d: Design) -> list[Section]:
    """The report of a construction project: the building, its quantities and the checks."""
    from .. import building as B
    i, b = d.info, d.building
    issues = validate.validate(d)
    qa = validate.counts(issues)
    bom = calc.bom(d)
    total = calc.boq_total(bom)
    out: list[Section] = []
    ex = Section("Executive Summary")
    if not b or not b.walls:
        ex.p("No building has been designed yet (Building 3D: Auto design, or draw the walls).")
        return [ex]
    gross = sum(B.area(s.outline) for s in b.slabs if s.level < len(b.levels))
    ex.cards([("Floors", str(len(b.levels))), ("Gross floor area", f"{gross:,.0f} m²"),
              ("Walls", f"{len(b.walls)}"), ("Doors / windows", f"{sum(o.kind == 'door' for o in b.openings)} / "
                                                             f"{sum(o.kind == 'window' for o in b.openings)}"),
              ("BOQ estimate", f"{i.currency} {total:,.0f}")]
             + ([("Cost per m²", f"{i.currency} {total / gross:,.0f}")] if total and gross else []))
    ex.p(f"This report covers the design and quantities of {i.name or 'the building'}"
         + (f" in {i.area}" if i.area else "") + (f" for {i.client}" if i.client else "") + ". "
         f"The quality checks report {qa['errors']} error(s) and {qa['warnings']} warning(s).")
    out.append(ex)
    intro = Section("1. Introduction")
    intro.text(i.introduction)
    intro.kv([["Project", i.name], ["Site", i.area], ["Client", i.client], ["Prepared by", i.prepared_by],
              ["Located on the map", "yes" if b.origin else "not yet"]])
    out.append(intro)
    st = i.site
    site = Section("2. Site and Brief")
    site.h("2.1 Ground conditions")
    if st.recorded():
        site.kv([["Soil", st.soil or "not recorded"],
                 ["Safe bearing capacity", f"{st.bearing_capacity:g} kN/m²" if st.bearing_capacity else "not tested"],
                 ["Ground water", f"{st.water_table:g} m below ground" if st.water_table else "not found / not recorded"],
                 ["Fall across the plot", f"{st.slope:g} %"], ["Ground level", f"{st.ground_level:g} m above datum"]])
        site.text(st.survey_notes)
    else:
        site.p("Ground conditions have not been recorded: a soil investigation (trial pits, bearing capacity, ground "
               "water) is needed before the foundations are designed.")
    site.h("2.2 The client's brief")
    site.text(st.client_brief or "No brief has been recorded.")
    rows = [["Occupants", f"{st.occupants:,}" if st.occupants else "-"],
            ["Budget", f"{i.currency} {st.budget:,.0f}" if st.budget else "not given"]]
    if st.budget and total:  # the whole construction cost (with preliminaries, contingency and VAT), not bare work
        whole = project_cost(total)["whole"]
        rows.append(["Estimated construction cost against the budget", f"{whole / st.budget:.0%} "
                                                                      f"({i.currency} {whole:,.0f} all-in)"])
    site.kv(rows)
    if st.schedule:
        have: dict[str, list] = {}
        for r in b.rooms:
            have.setdefault(r.name.lower(), []).append(r)
        site.table(["Room", "Required", "Designed", "Area each (brief)", "Smallest designed"],
                   [[x.name, x.count, len(have.get(x.name.lower(), [])), f"{x.area:g} m²" if x.area else "-",
                     f"{min(r.area for r in have[x.name.lower()]):g} m²" if have.get(x.name.lower()) else "-"]
                    for x in st.schedule])
    out.append(site)
    bld = Section("3. The Building")
    bld.text(i.proposed_solution)
    bld.h("3.1 Levels")
    bld.table(["Level", "Floor level", "Height", "Floor area", "Walls", "Doors", "Windows"],
              [[lv.name, f"{lv.elevation:+.2f} m", f"{lv.height:.2f} m",
                f"{sum(B.area(s.outline) for s in b.slabs if s.level == k):,.1f} m²",
                sum(w.level == k for w in b.walls),
                sum(o.kind == "door" and b.wall(o.wall) and b.wall(o.wall).level == k for o in b.openings),
                sum(o.kind == "window" and b.wall(o.wall) and b.wall(o.wall).level == k for o in b.openings)]
               for k, lv in enumerate(b.levels)])
    if b.roofs:
        bld.h("3.2 Roofs")
        bld.table(["Roof", "Type", "Pitch", "Covering", "Covered area", "Ridge + hips", "Eaves"],
                  [[r.id, r.kind, f"{r.pitch:g}°", r.covering, f"{B.roof_geometry(r)['area']:,.1f} m²",
                    f"{B.roof_geometry(r)['ridge'] + B.roof_geometry(r)['hips']:,.1f} m",
                    f"{B.roof_geometry(r)['eaves']:,.1f} m"] for r in b.roofs])
    sp = b.spec
    bld.h("3.3 Specification")
    framed = bool(b.columns) and len(b.levels) > 1
    bld.kv([["Foundations", f"to the structural calculations, founded at -{sp.founding_depth:g} m; wall footings "
                            f"{sp.footing_width:g} x {sp.footing_thickness:g} m under the ground-floor walls"] if framed else
            ["Strip footings", f"{sp.footing_width:g} m wide, {sp.footing_thickness:g} m thick, "
                               f"excavated {sp.excavation_depth:g} m"],
            ["Hardcore under the ground slab", f"{sp.hardcore:g} m"],
            ["Reinforcement", "by element (kg/m³): foundations 90, slabs and stairs 110, walls 120, beams 180, columns 220"
             if framed else f"{sp.rebar_kg_per_m3:g} kg/m³"],
            ["Plaster and render", "yes" if sp.plaster else "no"],
            ["Building lines", (f"front {i.site.setback_front:g} m, sides {i.site.setback_side:g} m, rear {i.site.setback_rear:g} m"
                                if i.site.setback_front or i.site.setback_side else f"{sp.setback:g} m all round")]])
    out.append(bld)
    mat = Section("4. Bill of Quantities Summary")
    mat.table(["Item", "Unit", "Quantity", "Rate", "Amount"],
              [[ln.description, ln.unit, f"{ln.qty:,.2f}", f"{ln.rate:,.2f}" if ln.rate is not None else "not priced",
                f"{ln.total:,.2f}" if ln.total is not None else "-"] for ln in bom if ln.qty] +
              [["Total", "", "", "", f"{total:,.2f}"]], total=True)
    unpriced = sum(1 for ln in bom if ln.qty and not ln.rate)
    if unpriced:
        mat.p(f"{unpriced} item(s) have no rate yet: import a price list in Materials & rules, or press Fill missing "
              f"rates there for indicative rates.")
    if total and gross:  # the measured work, then the whole project cost
        pc = project_cost(total)
        ext = sum(ln.total or 0 for ln in bom if ln.qty and ln.code in EXTERNAL_CODES)
        building = project_cost(total - ext)["whole"]
        mat.h("Estimated project cost")
        mat.table(["Item", "Basis", "Amount"],
                  [["Measured work (the BOQ above)", f"{i.currency} {total / gross:,.0f} per m²", f"{total:,.0f}"],
                   ["Preliminaries and general items", "10 % of the measured work", f"{pc['pre']:,.0f}"],
                   ["Contingency", "7.5 % of the measured work", f"{pc['cont']:,.0f}"], ["VAT", "16 %", f"{pc['vat']:,.0f}"],
                   ["Estimated construction cost", f"{i.currency} {pc['whole'] / gross:,.0f} per m²", f"{pc['whole']:,.0f}"],
                   ["  of which the building", f"{i.currency} {building / gross:,.0f} per m²", f"{building:,.0f}"],
                   ["  of which external works and utilities", "drains, walls, gate, landscaping, transformer",
                    f"{pc['whole'] - building:,.0f}"]], total=True)
        mat.p(f"The estimated construction cost, {i.currency} {pc['whole']:,.0f}, is the one figure used throughout. "
              "Benchmark for the building of a mid-range Nairobi apartment block: about KES 68,000-75,000 per m² of "
              "gross floor area (Cytonn 2025, all-in, without external works). Professional fees and approvals are "
              "excluded.")
    out.append(mat)
    from .. import compliance
    f = compliance.figures(d)
    st_ = i.site
    from .. import structure
    dz = structure.design(b, st_.bearing_capacity) if len(b.levels) > 1 else None
    if dz:
        calc_ = Section("Structural Calculations (preliminary)")
        lat = dz["lateral"]
        worst = max(dz["columns"], key=lambda c: c["N_uls"])
        calc_.p(dz["note"])
        calc_.kv([["Materials", f"{dz['concrete']} frame and cores, {dz['foundation_concrete']} foundations, {dz['steel']} bars"],
                  ["Loads", f"imposed {dz['imposed']:g} kN/m2 (roof 1.5); slab self-weight + finishes 1.5 + partitions "
                            f"{structure.PARTITIONS:g}; roof screed, waterproofing and plant 4.0 kN/m2; beams, facades "
                            f"({structure.WALL_LINE:g} kN/m a storey) and columns' own weight in the takedown"],
                  ["Design loads (1.35G + 1.5Q)", f"floors {dz['w_floor']:g} kN/m2, roof {dz['w_roof']:g} kN/m2"],
                  ["Slab", f"{dz['slab'] * 1000:.0f} mm {'two-way' if dz['two_way'] else 'one-way'} over {min(dz['spans']):g} x "
                           f"{max(dz['spans']):g} m panels (span/depth {min(dz['spans']) / dz['slab']:.0f}); {dz['rebar']['slab']}"],
                  ["Beams", f"B1 {dz['beam_x']['b'] * 1000:.0f} x {dz['beam_x']['h'] * 1000:.0f} ({dz['rebar']['beam_x']}); "
                            f"B2 {dz['beam_y']['b'] * 1000:.0f} x {dz['beam_y']['h'] * 1000:.0f} ({dz['rebar']['beam_y']})"],
                  ["Heaviest column", f"{worst['id']}: {worst['trib']:g} m2 tributary, N = {worst['N_uls']:,} kN (ultimate) "
                                      f"-> {max(worst['sizes']) * 1000:.0f} mm square with 2 % steel and bending allowance; "
                                      f"{dz['rebar']['column']}"],
                  ["Foundations", ((f"{len(dz['foundation'].get('pads', []))} pads and {len(dz['foundation'].get('combined', []))} "
                                    f"combined footings on {dz['bearing']:g} kN/m2 at -{dz['foundation']['depth']:g} m "
                                    f"(net {dz['bearing'] - structure.GAMMA_SOIL * dz['foundation']['depth']:g} kN/m2 for the column "
                                    f"loads); {dz['rebar']['foundation']}")
                                   if dz["foundation"]["type"] == "pads" else
                                   f"raft {dz['foundation']['thickness'] * 1000:.0f} mm under the whole building at "
                                   f"-{dz['foundation']['depth']:g} m, {dz['foundation']['pressure']} kN/m2 at its edge with "
                                   f"the overturning, no uplift; {dz['rebar']['foundation']}")
                   + "".join(f"; core raft CR{n + 1} {c['L']:g} x {c['B']:g} x {c['t']:g} m, {c['pressure']} kN/m2 at its edge "
                             f"with the overturning (no uplift)" for n, c in enumerate(dz["foundation"].get("cores", [])))
                   + (f"; core rafts {dz['rebar']['core_raft']}" if dz["rebar"].get("core_raft") else "")],
                  ["Headroom", f"{dz['headroom']:g} m clear under the deepest beam (2.25 m required; door heads 2.1 m)"],
                  ["Lateral", f"{lat['cores']} RC cores; seismic weight {lat['weight']:,} kN (floors, frame, cores, facades); "
                              f"earthquake {lat['seismic']:,} kN ({lat['coeff']:g} W), wind {lat['wind_x']:,} / {lat['wind_y']:,} kN; "
                              f"solid walls {lat['walls_x']:g} m x {lat['t_x'] * 1000:.0f} mm along x "
                              f"({(lat['use_x'] or 0):.0%} used), {lat['walls_y']:g} m x {lat['t_y'] * 1000:.0f} mm along y "
                              f"({(lat['use_y'] or 0):.0%} used); overturning {lat['M_x']:,} / {lat['M_y']:,} kNm a core; "
                              f"horizontal {lat['h_bars_x']} / {lat['h_bars_y']}, vertical {lat['v_bars_x']} / {lat['v_bars_y']}"]])
        out.append(calc_)
    cmp_ = Section("5. Planning and Building Code Compliance")
    cmp_.kv([["Plot", st_.plot_ref or "-"], ["Zone", st_.zone or "-"],
             ["Plot area", f"{f['plot_area']:,.0f} m²" if f.get("plot_area") else "not drawn"],
             ["Ground coverage", f"{f['coverage']:g} % (limit {st_.max_coverage:g} %)" if f.get("coverage") is not None else "-"],
             ["Plot ratio", f"{f['plot_ratio']:g} % (limit {st_.max_plot_ratio:g} %)" if f.get("plot_ratio") is not None else "-"],
             ["Floors / height", f"{f.get('floors')} floors, {f.get('height_roof')} m to the roof, {f.get('height')} m to the parapet"
              + (f" (limit {st_.max_floors} floors)" if st_.max_floors else "")],
             ["Geotechnical report", st_.geotech_report or "not recorded"],
             ["Flats", ", ".join(f"{v['count']} x {t} (average {v['average']:g} m²)" for t, v in f.get("flat_types", {}).items()) or "-"],
             ["Car parking", f"{f.get('parking_provided', 0)} provided, {f.get('parking_required', 0)} required"],
             ["Setbacks", ", ".join(f"{k} {v:g} m" for k, v in f.get("setbacks", {}).items()) or "-"],
             ["Escape stairs / lifts", f"{f.get('stairs')} / {f.get('lifts')}"]])
    allc = compliance.check(d)
    codes = [x for x in allc if x["severity"] in ("error", "warning")]
    notes_ = [x["message"] for x in allc if x["severity"] == "info"]
    cmp_.p("No planning or code check fails or warns." if not codes else
           f"{len(codes)} planning or code item(s) need attention (listed in section 6).")
    for n_ in notes_:
        cmp_.p("To complete: " + n_)
    out.append(cmp_)
    con = Section("6. Quality Checks and Recommendations")
    con.text(i.recommendations)
    errs = [x for x in issues if x["severity"] in ("error", "warning")]
    if errs:
        con.table(["Severity", "Check"], [[x["severity"], x["message"]] for x in errs])
    else:
        con.p("No errors or warnings.")
    out.append(con)
    return out


def sections(d: Design) -> list[Section]:
    i, r = d.info, d.rules
    if sectors.get(i.sector).get("construction"):
        return _finish(_building_sections(d), [])
    s = calc.summary(d)
    lengths = calc.cable_lengths(d, proposed_only=True)
    issues = validate.validate(d)
    qa = validate.counts(issues)
    bom = calc.bom(d)
    load = calc.fat_load(d)
    fats = [n for n in d.nodes if n.kind == "FAT"]
    homes_hp = [h for h in d.homes if h.units > 0]
    new_poles = [p for p in d.poles if p.status == "proposed"]
    out: list[Section] = []
    sec_p = sectors.get(i.sector)
    fibre = sec_p["fibre_tools"]
    NODE_LABEL = sec_p["kinds"]  # equipment names in the project's sector

    def line_key(c):  # "48C main"; other sectors "DN160 Distribution main"
        return f"{c.cores}C {c.kind}" if fibre else \
            f"{sectors.size_label(i.sector, c.cores)} {sec_p['lines'].get(c.kind, c.kind)}"

    def size(n):
        return n if fibre else sectors.size_label(i.sector, n)
    by_cable = defaultdict(float)
    for c in lengths:
        by_cable[line_key(c)] += c.total_m

    # --- executive summary ----------------------------------------------------------------------------
    ex = Section("Executive Summary")
    ex.cards([("Homepasses", f"{s['homepasses']:,}"), ("Premises", f"{len(d.homes):,}"),
              ("Poles / new poles", f"{len(d.poles):,} / {len(new_poles):,}"), ("FATs", f"{len(fats):,}"),
              ("Fibre (design length)", _m(sum(c.total_m for c in lengths))),
              ("BOQ estimate", f"{s['currency']} {s['boq_total']:,.0f}")])
    served = sum(h.units for h in homes_hp if h.fat)
    share = (served / s["homepasses"] * 100) if s["homepasses"] else 0
    ex.p(f"This report covers the survey and {sec_p['network']} design for {i.name or 'the project'}"
         + (f" in {i.area}" if i.area else "") + (f" for {i.client}" if i.client else "") + ". "
         f"The survey recorded {len(d.homes):,} premises with {s['homepasses']:,} homepasses and {len(d.poles):,} poles. "
         f"The proposed design serves {served:,} of the homepasses ({share:.0f}%) from {len(fats)} FATs"
         + (f" fed through {sum(sp.stage == 1 for sp in d.splitters)} PON splitter(s)." if fibre else "."))
    ex.p(f"Design status: {i.design_status.replace('_', ' ')}; survey dataset: {i.survey_status}. The quality checks "
         f"report {qa['errors']} error(s) and {qa['warnings']} warning(s)"
         + ("; the design is ready for approval." if qa["errors"] == 0 else "; the errors must be fixed before approval."))
    out.append(ex)

    # --- 1 introduction -------------------------------------------------------------------------------
    intro = Section("1. Introduction")
    intro.text(i.introduction)
    intro.h("1.1 Project details")
    intro.kv([["Project", i.name], ["Area", i.area], ["Client", i.client],
              ["Region / zone", " / ".join(x for x in (i.region, i.zone) if x)], ["Cluster", i.cluster],
              ["Survey date", i.survey_date], ["Surveyor(s)", i.surveyors], ["Prepared by", i.prepared_by],
              ["Design style", STYLE_LABEL.get(i.design_style, i.design_style)]])
    intro.h("1.2 Feeder and interception" if fibre else "1.2 Supply and connection point")
    roots = [x for x in [i.interception_node, *i.interception_nodes] if x]
    intro.kv([["OLT", i.olt_name], ["OLT ports available", i.olt_ports_available],
              ["Interception point(s)", ", ".join(roots) or i.interception],
              ["Feeder cores available", i.feeder_cores_available]] if fibre else
             [["Connection point(s)", ", ".join(roots) or i.interception]])
    out.append(intro)

    # --- 2 survey findings ----------------------------------------------------------------------------
    sv = Section("2. Survey Findings and Existing Infrastructure")
    sv.text(i.findings)
    sv.h("2.1 Premises and homepasses")
    kinds = Counter(h.kind for h in d.homes)
    hp_kind = Counter()
    for h in d.homes:
        hp_kind[h.kind] += h.units
    rows = [[KIND_LABEL.get(k, k), f"{kinds[k]:,}", f"{hp_kind[k]:,}"] for k in ("home", "mdu", "business") if kinds[k]]
    sv.table(["Premise type", "Premises", "Homepasses"], rows + [["Total", f"{len(d.homes):,}", f"{s['homepasses']:,}"]],
             total=True)
    sv.p(f"The survey found {sum(h.kind == 'mdu' and h.units > 0 for h in d.homes)} viable MDUs (multi-dwelling "
         f"buildings with homepasses), {kinds['home']} single dwellings and {kinds['business']} business or "
         f"institutional premises.")
    zero = sum(h.units == 0 for h in d.homes)
    if zero:
        sv.p(f"{zero} premise(s) have no homepasses recorded (vacant, under construction or not counted) and are not served.")
    big = [h for h in sorted(homes_hp, key=lambda h: -h.units)[:10] if h.units > 1]
    if big:
        sv.h("2.2 Largest buildings")
        sv.table(["Premise", "Name", "Type", "Homepasses", "Served by"],
                 [[h.id, h.name or "-", KIND_LABEL.get(h.kind, h.kind), h.units, ", ".join(h.fats) or "not served"]
                  for h in big])
    sv.h("2.3 Poles")
    ptype = Counter((p.type or "unspecified", p.status) for p in d.poles)
    sv.table(["Pole type", "Existing", "Proposed (new)"],
             [[t, ptype.get((t, "existing"), 0), ptype.get((t, "proposed"), 0)] for t in sorted({t for t, _ in ptype})] +
             [["Total", sum(p.status == "existing" for p in d.poles), len(new_poles)]], total=True)
    cond = Counter(p.condition for p in d.poles if p.condition)
    if cond:
        sv.p("Pole condition recorded: " + ", ".join(f"{k} {v}" for k, v in cond.most_common()) + ".")
    existing = [n for n in d.nodes if n.status == "existing"]
    ex_cables = [c for c in d.cables if c.status == "existing"]
    if existing or ex_cables:
        sv.h("2.4 Existing network")
        if existing:
            sv.table(["ID", "Type", "Pole", "Notes"], [[n.id, NODE_LABEL[n.kind], n.pole or "-", n.notes or ""] for n in existing])
        if ex_cables:
            sv.table(["Cable", "Cores", "Type", "Route length"],
                     [[c.id, size(c.cores), c.kind if fibre else sec_p["lines"].get(c.kind, c.kind),
                       _m(calc.route_length(c))] for c in ex_cables])
    out.append(sv)

    # --- 3 proposed solution --------------------------------------------------------------------------
    sol = Section("3. Proposed Network Solution")
    sol.text(i.proposed_solution)
    sol.h("3.1 Network elements")
    node_rows = [[NODE_LABEL[k], v] for k, v in s["nodes"].items() if v]
    split = Counter((sp.stage, sp.ratio) for sp in d.splitters)
    if fibre:
        node_rows += [[f"Splitter {ratio} (stage {stage})", v] for (stage, ratio), v in sorted(split.items())]
    if fibre:
        node_rows += [[f"FAT {p}-port", v] for p, v in sorted(Counter(n.ports or r.default_fat_ports for n in fats).items())]
    for k, label in sec_p.get("ports", {}).items() if not fibre else []:  # e.g. transformers by kVA
        node_rows += [[f"{NODE_LABEL[k]} {p} {label.split('(')[-1].rstrip(')')}", v] for p, v in
                      sorted(Counter(n.ports for n in d.nodes if n.kind == k and n.ports).items())]
    if node_rows:
        sol.table(["Element", "Quantity"], node_rows)
    stage1 = [sp for sp in d.splitters if sp.stage == 1]
    if stage1 and fibre:
        sol.h("3.2 PON structure")
        idx = splicing._index(d)
        fed_by = defaultdict(list)
        for sp in d.splitters:
            if sp.stage == 2:
                fed_by[_feeding_pon(idx, sp.id)].append(sp)
        rows = []
        traces = splicing.trace_all(d, 1)
        for sp in sorted(stage1, key=lambda x: x.id):
            kids = fed_by.get(sp.id, [])
            olt = traces[sp.id]
            rows.append([sp.id, sp.node, sp.ratio, olt.get("olt", "") if olt["ok"] else "not allocated",
                         f"{len(kids)}/{sp.outputs}", sum(load.get(k.node, 0) for k in kids)])
        sol.table(["PON splitter", "Location", "Ratio", "OLT port", "Outputs used", "Homepasses"], rows)
        if fed_by.get(""):
            sol.p(f"{len(fed_by[''])} FAT splitter(s) are not yet allocated to a PON (run Auto-allocate).")
    if fats and fibre:
        sol.h("3.3 FAT loading")
        used = [load.get(f.id, 0) * r.fat_load_take_rate / (f.ports or r.default_fat_ports) for f in fats]
        sol.p(f"Capacity is checked at a {r.fat_load_take_rate:.0%} take rate of the homepasses each FAT serves. "
              f"Average port use is {sum(used) / len(used):.0%} and the highest is {max(used):.0%}; "
              f"{sum(u > 1 for u in used)} FAT(s) are over capacity.")
    sol.h("3.4 Design rules applied")
    sol.kv(([["FAT and splitter", f"{r.default_fat_ports}-port FAT with 1x{r.default_fat_split} splitter"],
             ["PON splitter", f"1x{r.default_pon_split}"], ["FAT sizing take rate", f"{r.fat_load_take_rate:.0%}"]]
            if fibre else [["Sector", sec_p["label"]], [f"{sec_p['line']} sizes", f"{sec_p['size']} ({sec_p['size_unit']})"]]) + [
            ["Cable allowance", f"{r.cable_extra_pct:g}% + {r.cable_end_allowance_m:g} m per cable, rounded up to "
                                f"{r.cable_round_up_m:g} m"]] +
           ([["Slack", f"{r.slack_per_cable_end_m:g} m per equipment end, {r.slack_per_passing_node_m:g} m per pass-through"]]
            if fibre else [["Installation", "overhead on poles" if sec_p["install"] == "aerial" else "buried in trench"]]))
    out.append(sol)

    # --- 4 cable routing ------------------------------------------------------------------------------
    route = Section("4. Cable Routing and Installation")
    if lengths:
        route.h("4.1 Cable totals")
        route.table(["Cable", "Cables", "Route length", "Design length"],
                    [[k, sum(1 for c in lengths if line_key(c) == k),
                      _m(sum(c.route_m for c in lengths if line_key(c) == k)), _m(v)]
                     for k, v in sorted(by_cable.items())] +
                    [["Total", len(lengths), _m(sum(c.route_m for c in lengths)), _m(sum(c.total_m for c in lengths))]],
                    total=True)
        if fibre:
            route.p(f"Design lengths add {r.cable_extra_pct:g}% route allowance, {r.slack_per_cable_end_m:g} m slack per "
                    f"cable end at equipment, {r.slack_per_passing_node_m:g} m per pass-through enclosure and "
                    f"{r.riser_per_pole_end_m:g} m riser per pole-mounted end. Road crossings: "
                    f"{sum(c.crossings for c in lengths)}.")
        else:
            route.p(f"Design lengths add {r.cable_extra_pct:g}% for fittings and jointing"
                    + (f", {r.cable_end_allowance_m:g} m per end and {r.sag_per_point_m:g} m sag per support"
                       if sec_p["install"] == "aerial" else "") +
                    f", rounded up to {r.cable_round_up_m:g} m. Road crossings: {sum(c.crossings for c in lengths)}.")
        route.h("4.2 Cable schedule")
        route.table(["Cable", "Type", "Cores", "Install", "From", "To", "Route", "Design"],
                    [[c.cable, c.kind if fibre else sec_p["lines"].get(c.kind, c.kind), size(c.cores),
                      d.cable(c.cable).install, d.cable(c.cable).from_node or "-",
                      d.cable(c.cable).to_node or "-", _m(c.route_m), _m(c.total_m)] for c in lengths])
    else:
        route.p("No cable routes have been designed yet.")
    used_rows = [x for x in calc.pole_summary(d) if x.cables]
    if used_rows and not fibre:  # the sector's support hardware (none for buried networks)
        route.h(f"4.3 {sec_p['support']}s on the route")
        route.table(["Item", "Quantity"], [[f"{sec_p['support']}s on new {sec_p['line'].lower()}s", len(used_rows)]] +
                    [[h, sum(getattr(x, k) for x in used_rows)] for k, h in sec_p["hardware"]])
    elif used_rows:
        route.h("4.3 Pole accessories")
        route.table(["Item", "Quantity"], [["Poles carrying new cable", len(used_rows)],
                                           ["J-hooks", sum(x.jhooks for x in used_rows)],
                                           ["Tension clamps", sum(x.tension for x in used_rows)],
                                           ["Universal pole brackets", sum(x.upb for x in used_rows)],
                                           ["Extension arms", sum(x.ext_arms for x in used_rows)]])
    out.append(route)

    # --- 5 equipment ----------------------------------------------------------------------------------
    eq = Section("5. Equipment Schedule")
    if fats and fibre:
        eq.h("5.1 FATs")
        eq.table(["FAT", "Ports", "Pole", "Splitter", "Homepasses", "Status"],
                 [[f.id, f.ports or r.default_fat_ports, f.pole or "-",
                   ", ".join(sp.ratio for sp in d.splitters if sp.node == f.id) or "shared",
                   load.get(f.id, 0), f.status] for f in sorted(fats, key=lambda n: n.id)])
    elif fats:
        eq.h(f"5.1 {NODE_LABEL['FAT']}s")
        eq.table(["ID", "Pole", "Homepasses", "Status"],
                 [[f.id, f.pole or "-", load.get(f.id, 0), f.status] for f in sorted(fats, key=lambda n: n.id)])
    other = [n for n in d.nodes if n.kind not in ("FAT", "SLACK")]
    dets = sec_p["details"].get("node", [])

    def node_details(n):
        return "; ".join(f"{f['label']}: {n.details[f['key']]}{' ' + f['unit'] if f['unit'] else ''}"
                         for f in dets if f["key"] in n.details)
    if other and fibre:
        eq.h("5.2 Closures, junction boxes and PON points")
        eq.table(["ID", "Type", "Status", "Pole", "Latitude", "Longitude", "Splitters"],
                 [[n.id, NODE_LABEL[n.kind], n.status, n.pole or "-",
                   f"{n.lat:.6f}" if n.lat is not None else "-", f"{n.lon:.6f}" if n.lon is not None else "-",
                   ", ".join(sp.ratio for sp in d.splitters if sp.node == n.id) or "-"] for n in other])
    elif other:
        eq.h("5.2 Network equipment")
        rating = sec_p.get("ports", {})
        eq.table(["ID", "Type", "Status", "Pole", "Latitude", "Longitude", "Rating and details"],
                 [[n.id, NODE_LABEL[n.kind], n.status, n.pole or "-",
                   f"{n.lat:.6f}" if n.lat is not None else "-", f"{n.lon:.6f}" if n.lon is not None else "-",
                   "; ".join(x for x in ((f"{rating[n.kind]}: {n.ports}" if n.kind in rating and n.ports else ""),
                                         node_details(n)) if x) or "-"] for n in other])
    if new_poles:
        eq.h("5.3 New poles")
        eq.table(["Pole", "Type", "Latitude", "Longitude", "Notes"],
                 [[p.id, p.type, f"{p.lat:.6f}" if p.lat is not None else "-",
                   f"{p.lon:.6f}" if p.lon is not None else "-", p.notes or ""] for p in new_poles])
    if not d.nodes:
        eq.p("No equipment has been placed yet.")
    out.append(eq)

    # --- 6 materials ----------------------------------------------------------------------------------
    mat = Section("6. Bill of Quantities Summary")
    priced = [ln for ln in bom if ln.qty]
    if priced:
        mat.table(["Item", "Unit", "Quantity", "Rate", "Amount"],
                  [[ln.description, ln.unit, f"{ln.qty:,.0f}", f"{ln.rate:,.2f}" if ln.rate is not None else "not priced",
                    f"{ln.total:,.2f}" if ln.total is not None else "-"] for ln in priced] +
                  [["Total", "", "", "", f"{s['currency']} {s['boq_total']:,.2f}"]], total=True)
        unpriced = sum(ln.rate is None for ln in priced)
        if unpriced:
            mat.p(f"{unpriced} line(s) have no rate in the price list and are not included in the total.")
    else:
        mat.p("No materials have been calculated yet.")
    out.append(mat)

    # --- 7 quality ------------------------------------------------------------------------------------
    q = Section("7. Quality Assurance")
    q.kv([["Survey dataset", i.survey_status + (f" by {i.survey_approved_by} on {i.survey_approved_at[:10]}"
                                                 if i.survey_approved_by else "")],
          ["Design status", i.design_status.replace("_", " ")],
          ["Errors / warnings / notes", f"{qa['errors']} / {qa['warnings']} / {qa['notes']}"],
          ["Ready for approval", "Yes" if qa["errors"] == 0 else "No - fix the errors first"]])
    top = Counter((x["severity"], x["code"]) for x in issues if x["severity"] in ("error", "warning"))
    if top:
        first = {}
        for x in issues:
            first.setdefault((x["severity"], x["code"]), x["message"])
        q.table(["Severity", "Check", "Count", "Example"],
                [[sev, code.replace("_", " "), n, first[(sev, code)]]
                 for (sev, code), n in sorted(top.items(), key=lambda t: (t[0][0] != "error", -t[1]))])
    out.append(q)

    # --- 8 access -------------------------------------------------------------------------------------
    sp = Section("8. Special Requirements and Access Restrictions")
    sp.text(i.special_requirements)
    access = [[h.id, h.name or "-", h.access_notes] for h in d.homes if h.access_notes]
    if access:
        sp.table(["Premise", "Name", "Access notes"], access)
    out.append(sp)

    # --- 9 conclusion ---------------------------------------------------------------------------------
    con = Section("9. Conclusion and Recommendations")
    con.text(i.recommendations)
    nxt = []
    if i.survey_status != "approved":
        nxt.append("Approve the survey dataset.")
    if qa["errors"]:
        nxt.append(f"Resolve the {qa['errors']} QA error(s) listed in section 7.")
    unserved = sum(1 for h in homes_hp if not h.fat)
    if unserved:
        nxt.append(f"Assign a FAT to the {unserved} premise(s) with homepasses that are not yet served.")
    if any(ln.rate is None for ln in priced):
        nxt.append("Add rates for the unpriced BOQ lines.")
    if i.design_status != "approved" and not qa["errors"]:
        nxt.append("Submit the design for review and approval.")
    if nxt:
        con.h("Outstanding actions")
        con.bullets(nxt)
    con.p(f"Estimated material cost (BOQ): {s['currency']} {s['boq_total']:,.2f}.")
    out.append(con)

    return _finish(out, sectors.wording(i.sector))


def _finish(out: list[Section], words) -> list[Section]:
    """Fibre words -> the sector's words, and text that XML-based formats (docx, pdf) can store."""
    txt = (lambda x: clean(sectors.reword(clean(x), words))) if words else clean
    for sec in out:
        sec.title = txt(sec.title)
        blocks = []
        for b in sec.blocks:
            if b[0] in ("p", "missing", "h"):  # the planner's own words are kept as written
                blocks.append((b[0], clean(b[1]) if b[2:] == ("planner",) else txt(b[1])))
            elif b[0] == "kv":
                blocks.append(("kv", [[txt(k), clean(v)] for k, v in b[1]]))
            elif b[0] == "table":
                blocks.append(("table", [txt(h) for h in b[1]], [[clean(c) for c in row] for row in b[2]], b[3]))
            elif b[0] == "cards":
                blocks.append(("cards", [(txt(k), clean(v)) for k, v in b[1]]))
            elif b[0] == "bullets":
                blocks.append(("bullets", [txt(x) for x in b[1]]))
        sec.blocks = blocks
    return out


def document_control(d: Design, st) -> list[list[str]]:
    i = d.info
    return [["Document", sectors.get(i.sector)["report_title"]], ["Project", clean(i.name)], ["Revision", str(st.revision)],
            ["Status", st.status.replace("_", " ").title()], ["Date", st.date], ["Data reference", st.hash],
            ["Issued by", clean(st.brand.name)]]


def signoff(d: Design) -> list[list[str]]:
    i = d.info
    return [["Prepared / planned by", clean(i.planned_by or i.prepared_by)], ["Lead planner", clean(i.lead_planner)],
            ["Checked by", clean(i.checked_by)], ["Approved by", clean(i.approved_by)]]
