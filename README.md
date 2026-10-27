# faibaplaning: FTTH Network Planning & Design System

A Django web application for FTTH planning. It takes ground-survey data and produces a complete, consistent design package: HLD, LLD, pole summary, BOM, BOQ, splicing diagram and survey report, all generated from **one central data set**. Teams sign in, share projects, and approve designs with a permission.

## Run it on your computer

Double-click **`run.bat`**, or from a terminal:

```bash
run.bat
```

The first run installs dependencies (Python 3.11+), creates the database and asks you to create an administrator account. The app then opens at http://127.0.0.1:8000. Click **Sample project** for a ready-made example.

Local data: database `data/planner.sqlite3`, survey photos in `data/media/photos/`.

To run the tests: `.venv\Scripts\python -m pytest`

## Users and permissions

- **Accounts:** administrators create them at `/admin/` (Users → Add). There is no public sign-up.
- **Projects:** each project belongs to its creator. The owner shares it with colleagues using **Share** in the header, or in admin under *Projects → members*. Others cannot see it.
- **Approval:** approving a design needs the **"Can approve an FTTH design for issue"** permission. Give it to a user or a group in admin; everyone else can only save revisions and submit for review. Revisions record the signed-in user.
- **Simultaneous editing:** if two people edit the same project, a save made from an out-of-date copy is refused. The user is asked to reload instead of silently overwriting the other person's work.

## Put it on the web

The app is ready for any host that runs Docker (for example Render, Railway, Fly.io, DigitalOcean App Platform or your own VPS):

1. Build the image from the `Dockerfile`, or point the host at this folder.
2. Set the environment variables from `.env.example`:
   - `DJANGO_SECRET_KEY` (a long random string)
   - `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` (your domain)
   - `DATABASE_URL` (PostgreSQL is recommended for teams)
   - `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD` (first admin account)
3. Mount a persistent volume at `/data` for survey photos (and SQLite, if not using PostgreSQL).
4. Serve it over HTTPS. The container runs gunicorn on `$PORT` (default 8000), applies migrations on start, and serves static files with WhiteNoise.

To bring over projects from the earlier stand-alone version:

```bash
.venv\Scripts\python manage.py import_legacy --owner admin
```

## How the workflow maps to the app

The app opens on an **Overview** laid out like the process diagram: the seven workflow steps across the top, each with its live status (click one to open that stage), then the HLD on satellite imagery, the LLD in a CAD-style view, the pole summary, BOM, BOQ, fibre splicing schematic and survey report, with one-click downloads in the "One central database" bar. Every panel is drawn from the same project data as the files. The full checklist against the requirements is in `docs/requirements-checklist.md`.

| Step | Where | What it does |
|---|---|---|
| 1 Survey import | *Survey data* tab | Imports Excel workbooks with several sheets in one go (Poles, Homes, Equipment, Splitters, Cables; **Download Excel template** gives a blank one), CSV (columns detected by name), KML/KMZ and GPX. A project's Project Data Excel export uploads back unchanged. Also supports manual entry on the map. Rows with bad coordinates are kept and flagged; swapped lat/lon is corrected |
| 2 Cleaning & validation | *Survey data* / *QA* | Flags duplicate IDs, missing or invalid coordinates, points less than 1 m apart, and invalid units. **Approve survey dataset** is blocked until errors are fixed |
| 3 HLD | *Map / HLD* tab | Street or satellite map. Add poles, homes and equipment (POP, splice enclosure, PR, JB, PON, FAT). Draw cables pole-to-pole, mark road crossings, draw the boundary, auto-assign homes to FATs within capacity. Moving a pole moves its cables and equipment |
| 3a Auto-design | *Map / HLD*: **Auto-design** | From the survey data alone (existing closure, poles, premises with HP counts), places indoor/outdoor FATs, 2nd-stage splitters, PON closures with JB and primary splitter, routes the 48C backbone and 12C spurs along the pole network, adds closures, slack loops and new poles where spans are too long, then allocates fibres. Mark future backbone ends with **Backbone end**. Results: `docs/blind-test-2026-10-27.md` |
| 4 Materials | *Materials & rules* tab | Material catalogue with rates, construction rules (J-hooks, tension clamps, UPBs, slack, risers, conduit, splitter defaults) and authorised manual adjustments that require a reason |
| 5 LLD | *Outputs*: LLD | DXF (layers per element, labels, title block) and an A3 PDF sheet. DWG: open the DXF in AutoCAD and save as DWG |
| 6 Pole summary | *Schedules* / *Outputs* | Per-pole cables, J-hooks, tension clamps, UPBs, JB/enclosure/FAT and notes (corner, dead-end, crossing, new pole). Excel and PDF |
| 7 BOM / BOQ | *Schedules* / *Outputs* | Quantities from routes plus slack and risers, equipment, splitters, accessories, conduit and crossings. The BOQ uses rates, with live Excel formulas. Excel and PDF |
| 8 Splicing | *Splicing* tab | Auto-allocates OLT → feeder core → 1st-stage splitter → distribution core → FAT splitter. Has a manual connection editor, TIA-598 colours, core usage, and FAT-to-OLT traces. Flags duplicate or reserved/non-existent cores, double-used ports and unfed FATs. PDF and JSON |
| 9 Survey report | *Survey report* tab | Narrative only from text you enter, plus facts from the data (never invented). Photos with captions. Word (.docx) and PDF |
| 10 QA & approval | *QA & approval* / *Outputs* | QA & approval report (PDF and Excel), validation list, revisions with notes, review/approve. Approval is blocked while errors exist, and editing an approved design returns it to draft. Every file is stamped with revision and data hash; outputs show "Needs regenerating" when the design changed. Complete package zip with `MANIFEST.json` |

Every report (pole summary, BOM, BOQ, splicing, survey report, home list, QA) downloads as both PDF and Excel; the survey report also as Word.

**BOQ template.** The Excel BOQ is produced in the V Squared company template (`ftth/templates/vsquared_boq.xlsx`): logos, project overview, cost summary, Section A implementation costs, Section B material costs with live formulas, the approval block and the price list sheet. The company catalogue carries the template's items and prices (including extension arms Medium KES 3,500 / Large KES 6,500). Section A is filled only when the rule *implementation costs* is switched on (Materials & rules); the approved Infinity BOQ is materials only. When prices change, upload the new template or any price list under Materials & rules > **Import price list**: rates are matched by item description, new items are added. To change the layout or the approval names, replace the template file.

### Drawing and editing tools

| Where | Tools |
|---|---|
| HLD map | Undo / redo (Ctrl+Z / Ctrl+Y, also undoes Auto-design and other server operations), select and drag, add pole / home / equipment, draw cable, boundary, backbone end, measure distance and area, find by ID or name, go to coordinates, snapping to poles and equipment, grip editing of a selected cable (drag a point, drag "+" to insert, right-click to remove), labels on/off, fullscreen, print, street / CARTO / satellite base maps, layer switcher, scale bar, cursor coordinates, keyboard shortcuts (press ?) |
| LLD drawing | Zoom in / out / extents / window, pan, measure, layer manager (boundary, drops, existing, 48C, 12C, buildings, poles, equipment, labels, cable tags), grid, black or white background, text size, cursor X/Y in metres and lat/lon, export SVG / PNG, print; DXF and A3 PDF sheets for AutoCAD |
| Settings | Project and title-block fields, Auto-design options (take rate, FAT ports, cluster radius, spans, pole spacing, closure gaps, slack interval), map and drawing preferences (snap distance, labels, drop links, CAD background, grid, text size); rules and catalogue in *Materials & rules* |

Code:
- **`ftth/`:** engineering logic with no web framework.
  - `model.py`: central design model.
  - `calc.py`: lengths, pole summary, BOM/BOQ.
  - `splicing.py`, `validate.py`, `importers.py`.
  - `autodesign.py`: automatic network design from survey data.
  - `exporters/`: KML, DXF, Excel, PDF, Word.
- **`planner/`:** the Django app.
  - `models.py`: projects, revisions, export tracking, approval permission.
  - `views.py`: JSON API, access control, conflict checks.
  - `templates/`, `static/planner/`: user interface (`app.js` editing and tabs, `overview.js` workflow strip, Overview, LLD view and splicing schematic).
- **`planner_site/`:** settings and URLs.

## Limits to know before production use

- Quantity rules and rates are calibrated on the approved V Squared project *Infinity Densification (257 HPs) FY26* (`docs/calibration.md`). Equipment, splitters, homepasses and building materials match exactly; cables are within 2 %; the catalogue reproduces the approved BOQ total. The tie-cable, trunking and wall-clamp rules are confirmed company standard.
- Auto-design is a first draft for the planner to review, not a final design. In the blind test it placed 95 % of FATs within 15 m of the approved ones and matched JBs and splitters, but it only routes the 48C backbone where the survey marks a reason to go (PON sites and Backbone end markers), and it cannot decide trunking or wall clamps (those depend on building entry seen on site).
- No native DWG writer. DXF is the CAD exchange format, and AutoCAD saves it as DWG.
- Editing is one person at a time per project: a stale save is refused rather than merged.
- Map tiles come from OpenStreetMap and Esri imagery. For heavy production use, check their usage policies or configure a commercial tile provider.

## Folder layout

| Path | Contents |
|---|---|
| `ftth/`, `planner/`, `planner_site/`, `tests/` | The application (engineering logic, Django app, settings, tests) |
| `run.bat`, `manage.py`, `requirements.txt`, `Dockerfile`, `.env.example` | Local start-up, dependencies and web deployment |
| `docs/requirements.md` | The full 10-step workflow and system requirements, with `ftth-process-overview.webp` |
| `research/open-source-tools.md` | Code-level study of 6 open-source FTTH tools, with a coverage matrix against our 10 steps |
| `research/commercial-tools.md` | Desk research on commercial tools (Comsof, Setics, Biarri, VETRO, 3-GIS, Splice.me and others) |
| `research/routing-algorithms_ftth_planner_and_qgis_thesis.md` | Routing and serving-point algorithms worth re-implementing |
| `reference/` | Shallow clones of the studied repos (read-only references, not our code) |

## Key findings (2026-10-26)

1. **Nothing on the market or on GitHub does the whole workflow.** The commercial tools (IQGeo Comsof Fiber, Setics Sttar, Biarri) automate HLD/LLD and BOM. The open-source tools each cover part of it.
2. **No tool, commercial or open source, builds a pole-by-pole accessory summary (J-hooks, tension clamps, UPBs) from company rules.** This also holds for Word survey reports built from survey data. These are our differentiators.
3. **Closest open-source matches:**
   - **openFTTH** (MIT): has a central design model, a DXF writer, splitters and colours, a splice schedule, a BOQ with rates, and git versioning. It's the one we can legally reuse code from.
   - **aviva-geoplan** (no license): has the same overall shape we want: mobile survey → PostGIS → map → one design pack feeding an xlsx BOQ, a Word report and schematics.
   - **netbox-fms** (AGPL): has the best splice/core model, colour tables, conflict checks and an approval state machine.
   - **FiberQ** (GPL): a QGIS editor with a strong validation-rule engine and KML export.
4. **Licensing:** only openFTTH (MIT) can have its code copied freely. GPL and AGPL code would force our app to be open source under the same terms, and code with no license can't be copied at all. For everything except openFTTH, re-implement the ideas.

## Suggested build direction

- **Data model:** one project database (PostGIS, or SQLite/GeoPackage for a single user). It holds survey features, network elements (POP, enclosure, JB, FAT, PON/splitter, pole, home), cables with core counts, a fibre-connection table, a material catalogue, and per-element **quantity rules**. Align it with [OFDS](https://open-fibre-data-standard.readthedocs.io/) where practical.
- **Phase 1:** survey import (Excel/CSV/KML) with validation rules modelled on FiberQ, a MapLibre map editor, and KML/KMZ export.
- **Phase 2:** material catalogue and rule engine → pole summary, BOM and BOQ (xlsx with rate formulas, plus PDF).
- **Phase 3:** DXF export (adapt openFTTH's writer, MIT) and a splice editor (netbox-fms colour/conflict ideas plus openFTTH splitter cascade).
- **Phase 4:** Word/PDF survey report, cross-deliverable QA, approval states and design versions (aviva-geoplan / openFTTH patterns).

## About REA

The `reverse-engineer-anything` skill was used to plan this investigation. Its own guidance says to use normal code reading for open-source repos and to use REA only for shipped apps without source. None of the commercial tools were installed locally, so REA had nothing to inspect. If you install a trial desktop build (for example a vendor's Windows client), REA can then analyse how it does a specific feature.
