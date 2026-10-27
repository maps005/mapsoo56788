# Requirements checklist (2026-10-27)

Each requirement of *FTTH Network Planning and Design System* mapped to where the planner meets it.
✅ = in the app and covered by tests or a check on the approved Infinity 257 HPs project. ◐ = met with a stated limit.

## The seven-step workflow (Overview page)

The Overview tab mirrors the process diagram: the seven steps across the top, each showing its live status and
opening its stage, then the HLD, LLD, pole summary, BOM, BOQ, splicing diagram and survey report panels, all
drawn from the one project database, with one-click downloads in the "One central database" bar.

| # | Requirement | Where | Status |
|---|---|---|---|
| 1 | Import survey data: Excel / CSV | Survey & validation > Import. Multi-sheet workbooks (Poles, Homes, Equipment, Splitters, Cables), blank template download, CSV with columns detected by name | ✅ |
| 1 | Import KML / KMZ, GPS / survey apps | KML/KMZ (folders, photos inside KMZ), GPX. Survey apps (ODK, KoBo, Fulcrum...) via their CSV/Excel/KML export | ◐ no direct app connection |
| 1 | Manual entry and map editing | HLD map: add / drag poles, homes, equipment; draw cables; edit any field in the side panel or data tables | ✅ |
| 2 | Flag duplicate IDs, missing coordinates, invalid data | Validation (duplicates, IDs with spaces, missing / invalid / swapped coordinates, points < 1 m apart, invalid units) | ✅ |
| 2 | Existing vs surveyed vs proposed | Status on every pole, equipment and cable; existing GIS records are not checked as design | ✅ |
| 2 | Correct errors, then approve the survey dataset | Data tables + **Approve survey dataset** (blocked while survey errors exist; records who and when) | ✅ |
| 3 | Boundary, poles, homes, start point, main and spur routes, equipment, cable sizes | HLD map tools; interception point; **Auto-design** proposes FATs, splitters, closures, JBs, 48C/12C routes and new poles from the survey | ✅ |
| 3 | Link homes to serving points | Auto-assign homes to FATs within port capacity; manual FAT per home | ✅ |
| 3 | KML/KMZ export and import | HLD KML, KMZ, PDF | ✅ |
| 4 | Material catalogue: cables, enclosures, JB, FAT, PON, splitters, J-hooks, tension clamps, UPBs, extension arms, poles, conduit / trunking, crossings | Materials & rules: catalogue with unit and rate; construction rules; consumables | ✅ |
| 4 | Quantities from the design, authorised manual adjustments | BOM from routes and rules; adjustments need a reason before approval | ✅ |
| 4 | Manholes, road-crossing protection | Catalogue items + road crossings counted per cable; manholes added as adjustments | ◐ not placed on the map |
| 5 | LLD: pole-to-pole routes, equipment, core counts, splice points, FATs, building entries | LLD drawing tab (CAD view), DXF with layers, A3 PDF sheet set with work-load strip and title block | ✅ |
| 5 | DWG | DXF opens in AutoCAD; save as DWG. No native DWG writer (as the spec allows) | ◐ |
| 6 | Pole summary per pole: cables, J-hooks, tension clamps, UPBs, corners, crossings, equipment, notes | Pole summary · BOM · BOQ tab; Excel and PDF | ✅ |
| 7 | BOM / BOQ: cable lengths with slack, risers, building entries; accessories; equipment; conduit; rates and totals | Excel (live formulas) and PDF; reproduces the approved Infinity BOQ, KES 518,758 | ✅ |
| 8 | Splicing: cable IDs, core colours, enclosures, PON and FAT splitters, incoming / outgoing, used / spare / reserved | Splicing tab: schematic, connection editor, core table, FAT-to-OLT traces; PDF, Excel and JSON | ✅ |
| 8 | Check allocation against capacity; flag duplicate / unavailable / invalid connections | Splicing checks (duplicate cores, reserved / non-existent cores, double-used ports, unfed FATs) | ✅ |
| 8 | Visual splicing editor | Schematic + form-based connection editor | ◐ not drag-and-drop |
| 9 | Survey report sections 1-8, photos, no invented details | Survey report tab; Word, PDF and Excel; empty sections print "Not recorded" | ✅ |
| 10 | Consistency across all deliverables | Every file generated from the same data and stamped with revision and data hash | ✅ |
| 10 | Review, amend, approve; versions, dates, status, change records | QA & approval: revisions with notes, submit for review, approve (permission), restore; editing an approved design returns it to draft | ✅ |
| 10 | Final package | One zip with all deliverables and MANIFEST.json (blocked while errors exist unless forced) | ✅ |

## Required outputs

| Deliverable | Required | Planner |
|---|---|---|
| HLD | KML/KMZ and PDF | KML, KMZ, PDF ✅ |
| LLD | DWG/DXF and PDF | DXF, PDF ✅ (DWG via AutoCAD) |
| Pole summary | Excel and PDF | Excel, PDF ✅ |
| BOM | Excel and PDF | Excel, PDF ✅ |
| BOQ | Excel and PDF | Excel, PDF ✅ |
| Splicing diagram | PDF and editable data | PDF, Excel, JSON ✅ |
| Survey report | Word and PDF | Word, PDF, Excel ✅ |
| Project data | Excel/CSV and database | Excel (re-uploadable), CSV zip, JSON; PostgreSQL / SQLite ✅ |
| QA report | (not required) | PDF, Excel |

## "Enter once, reuse everywhere"

- Moving a cable route recalculates its length and quantities immediately; each deliverable shows *Needs
  regenerating* only if the data it is built from changed (per-deliverable data hash).
- Moving a FAT moves its cables' end points and updates HLD, LLD, schedules and splicing from the same record.

## Testing against completed projects

Calibrated and tested on the approved V Squared *Infinity Densification (257 HPs) FY26* project:
equipment, splitters and homepasses exact, cables within 2 %, BOQ reproduced to the shilling, Excel round trip
exact (`docs/calibration.md`, `docs/blind-test-2026-10-27.md`).
