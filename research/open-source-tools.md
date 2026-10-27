# Open-source FTTH tools: code study

Clones are in `../reference/` (shallow, taken 2026-10-26). Each status below is checked against code, not just the README.
Legend: ✅ supported · 🟡 partial · ❌ missing.

## Coverage matrix against our 10 steps

| Step | FiberQ | openFTTH | netbox-fms | aviva-geoplan | ftth_planner | QGIS thesis |
|---|---|---|---|---|---|---|
| 1 Survey import (Excel/CSV/KML/GPS) | 🟡 KML/KMZ/SHP/GPX/DXF, no Excel | ✅ KML/KMZ/GPKG/SHP/DXF/CSV + import profiles, no XLSX | ❌ | 🟡 KML boundary/streets, mobile GPS, one-off xlsx | ❌ OSM only | 🟡 Czech SHP only |
| 2 Cleaning / validation | 🟡 rule engine A1–E2 (topology, FK, dup UUID, CRS) | 🟡 dup locations, ID pattern/uniqueness | 🟡 model checks | 🟡 geometry repair, verification states | ❌ | ❌ |
| 3 HLD map + KML/KMZ | ✅ manual drawing + KML/KMZ export | 🟡 auto-design, GPKG/GeoJSON (no KML) | ❌ | 🟡 MapLibre + auto FAT/FDH, no KML | 🟡 plot only | 🟡 SHP |
| 4 Material catalogue + rules | ❌ | 🟡 YAML rulebook, prices | 🟡 cable-type catalogue | 🟡 rules + stock, lines hard-coded | 🟡 flat rates | 🟡 excavation prices |
| 5 LLD DXF/DWG + PDF | 🟡 reads DWG/DXF only | ✅ DXF R12 writer + A3/A1 PDF sheets | ❌ | ❌ SVG/PNG | ❌ | ❌ |
| 6 Pole summary (J-hooks, clamps, UPBs) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 7 BOM / BOQ with rates (Excel/PDF) | 🟡 counts → XLSX, no rates | 🟡 `BoqLine` with rates → CSV | ❌ | ✅ BOQ xlsx with Rate/Amount formulas | 🟡 DataFrames | 🟡 one budget figure |
| 8 Splicing / cores / splitters | ❌ | ✅ 1/2-stage splitters, TIA-598 colours, splice schedule, power budget | ✅ cores: splice plans, colour tables, conflict check (no splitters) | 🟡 splitter stages, loss budget, no strands | ❌ | ❌ |
| 9 Survey report (Word/PDF) | ❌ | 🟡 CSV reports | ❌ | ✅ Word `.docx` design report | ❌ | 🟡 PDF budget table |
| 10 QA, approval, versioning | 🟡 validation panel, schema migrations | ✅ checks, approval gating, git versions | 🟡 splice-plan approval state machine | 🟡 design runs, audit, readiness | ❌ | ❌ |
| **License** | GPL-3.0 | **MIT** | AGPL-3.0 | none | none | none |
| Stack | QGIS plugin, Python | Python engine + Rust desktop + LLM agents/MCP | Django / NetBox plugin | FastAPI + PostGIS + React/MapLibre + Expo mobile | Python + Streamlit | QGIS 2 (obsolete) |
| Maturity | v1.5, ~1,290 tests, active | beta 0.1, ~116 tests, active | alpha 0.6, ~1,022 tests | one-site deployment, ~210 tests | 2022 proof of concept, buggy | 2018 thesis |

**No project covers Step 6 (pole summary with accessories).** That, plus company-specific material rules, is where our own build is needed most.

## Per-project notes

### FiberQ: `reference/fiberq` (GPL-3.0)
- Manual QGIS drawing tool. It keeps one GeoPackage layer per entity type, all keyed by `fiberq_uuid` (`fiberq/models/schema.py`). Many field names are Serbian, with English aliases.
- Ideas worth borrowing:
  - The schema registry with versioned migrations (`core/migrations.py`).
  - A rule-registry validation engine with ID, severity and category for each rule (`core/validation_rules.py`).
  - A BOM that reports what it couldn't measure instead of treating it as zero (`dialogs/bom_dialog.py`).
  - KML/KMZ export with reprojection to WGS84 (`core/export_manager.py`).
  - An open interchange format (`docs/interchange-format.md`, CC-BY-4.0).
- PostGIS publishing and the map preview are gated by a "Pro" key (`core/license_manager.py:28`).

### openFTTH: `reference/openFTTH` (MIT, can be reused)
- Its central `Design` model holds GeoJSON-like features plus a `fiber_connection` table (`interchange/model.py`). **This matches our "enter once, reuse everywhere" principle.**
- Deterministic engine: geopandas, networkx, OR-Tools CP-SAT. Design rules live in YAML rulebooks.
- Parts worth borrowing:
  - `deliver/dxf.py`: a DXF R12 writer with no dependencies.
  - `deliver/sheets.py`: PDF plan sheets.
  - `deliver/boq.py`: the `BoqLine` model.
  - `deliver/splice.py`: the splice schedule.
  - `solve/fibers.py`: TIA-598 colour assignment.
  - `validate/checks.py`: capacity, power budget and splitter-cascade checks.
  - `ingest/sources.py` and `ingest/profiles.py`: GDAL import plus column-mapping profiles.
  - `project.py`: dulwich (git) versioning.
- It's weighted toward underground/OSM networks. There's no XLSX, Word or PDF BOQ, and no pole accessories.

### netbox-fms: `reference/netbox-fms` (AGPL-3.0, re-implement ideas only)
- The best **splice / core** data model we found:
  - A `FiberCableType` blueprint creates the tubes and strands.
  - Strand colour is derived from position plus colour scheme. EIA-598, ABNT and DIN/IEC tables are in `netbox_fms/constants.py`.
  - `SplicePlanEntry` pairs two fibres on a tray.
- Conflict check: one fibre can't be claimed by two active plans (`models.py:1567-1621`).
- Approval state machine: draft → pending_approval → approved → archived.
- Diagram export to draw.io (`export.py`).
- It has no splitters, poles, homes or geometry, and it needs NetBox to run.

### aviva-geoplan: `reference/aviva-geoplan` (no license, reference only)
- **Architecturally closest to our spec.** It has a survey mobile app (Expo, offline-idempotent capture), a FastAPI + PostGIS backend and a React/MapLibre map.
- `services/design_pack_service.py` builds one data dict that feeds the xlsx BOQ (with Rate/Amount formulas), the Word report (`word_report_service.py`) and the schematics.
- Other good ideas:
  - Versioned `DesignRun` that records the rules used. Boundaries are superseded, never overwritten.
  - Verification states with protected writes.
  - A readiness checklist and stale-design detection.
  - Splitter stage planning against stock, and an optical loss budget.
- It's built for a single site (Wuye, Abuja). It has no KML or DXF export, no pole model and no strands or splices.

### ftth_planner and the QGIS thesis plugin (no license)
- Useful only as algorithm references. See `routing-algorithms_ftth_planner_and_qgis_thesis.md`: dig-once weighted Dijkstra, capacity-constrained k-means for serving points, and MST vs shortest-path-tree topologies.
