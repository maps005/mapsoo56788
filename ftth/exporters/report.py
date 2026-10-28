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


def sections(d: Design) -> list[Section]:
    i, r = d.info, d.rules
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
        for sp in sorted(stage1, key=lambda x: x.id):
            kids = fed_by.get(sp.id, [])
            olt = splicing.trace_upstream(d, sp.id)
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

    words = sectors.wording(i.sector)  # fibre words -> the sector's words
    txt = (lambda x: clean(sectors.reword(clean(x), words))) if words else clean
    for sec in out:  # text that XML-based formats (docx, pdf) can store
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
