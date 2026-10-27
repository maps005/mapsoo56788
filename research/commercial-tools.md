# Commercial and closed-source FTTH design tools

Desk research, 2026-10-26. These tools are commercial, mostly SaaS, and were **not installed or tested**. The claims below come from vendor pages and third-party listings, so confirm them in a demo or trial before relying on them.

| Tool | Type | What it covers (claimed) | Fit to our 10 steps | Source |
|---|---|---|---|---|
| **IQGeo Comsof Fiber** | Desktop + GIS, automated design | Automated HLD/LLD from GIS data, splice structures, fibre strand assignment, BOM/cost. Vendor claims up to 90% faster planning. | Steps 3, 4, 7, 8 strong; DXF/GIS exports | [SoftwareOne listing](https://platform.softwareone.com/product/comsof-fiber/PCP-2171-8636), [IQGeo SUEZ case](https://www.iqgeo.com/customer-stories/suez-consulting?hsLang=en) |
| **Setics Sttar** | Desktop automation + GIS front-end (QGIS/ArcGIS/MapInfo) | Automated HLD and LLD, multi-scenario cost, BOM/BOQ, diagrams, engineering-rule compliance; used in France's national FTTH plan | Steps 3, 4, 5, 7; splicing and DXF not confirmed | [Esri partner page](https://www.esri.com/partners/setics-a2TUU000000gGbR2AU/setics-sttar-a2dUU000006MmfFYAS), [Fibre Systems](https://www.fibre-systems.com/product/setics-upgrades-fttx-design-software) |
| **Biarri Networks (FOND)** | Optimisation-based design service/platform | Pre-processing → "Solve" generates the network → post-processing; HLD to LLD with pole surveys and make-ready | Steps 2, 3, 5, 7 | [Biarri LLD article](https://biarrinetworks.com/articles/from-blueprint-to-build-streamlining-the-low-level-design-process-1) |
| **VETRO FiberMap** | Web SaaS | Collaborative map-based design and as-built documentation tied to live inventory | Steps 1, 3, 8, 10 | [AlternativeTo](https://alternativeto.net/software/vetro-fibermap), [Capterra](https://www.capterra.ca/alternatives/193245/vetro-fibermap) |
| **3-GIS** | Enterprise GIS (Esri-based) | Governed design across planning, construction and maintenance | Steps 3, 8, 10 | [Worldmetrics roundup](https://worldmetrics.org/best/fiber-design-software/) |
| **Splice.me** | Web SaaS | Splice diagrams "in 3 clicks": cables, nodes, splitters, colourised fibres, splice tracing. About $75–99 per month | Step 8 only | [Lightwave directory](https://www.lightwaveonline.com/directory/design-production/design-software/product/55275254/spliceme-fiber-splice-diagrams-made-in-3-clicks) |
| **PATCH MANAGER** | Physical-layer management | Interactive graphical splicing diagrams, REST API, splicing work orders | Steps 8, 10 | [patchmanager.com](https://patchmanager.com/?p=8069) |
| **cvFiber** | OSP mapping | Graphical multi-cable splicing, TIA-598C colour code, field splitters | Steps 3, 8 | [AlternativeTo](https://alternativeto.net/software/cvfiber/about) |
| **NetDesign (ITS)** | AutoCAD-based | FTTH/FTTx design in AutoCAD with costing, cabling, labelling, P2P↔GPON | Steps 5, 7 | [Gitnux list](https://gitnux.org/best/ftth-design-software/) |
| **FiberQ CAD** | Free AutoCAD add-in (reported open source) | FTTH/GPON schematics, `FQBOM` builds a BOM from the drawing, optical loss budget | Steps 5, 7 | [Gitnux list](https://gitnux.org/best/ftth-design-software/); repository not located |
| **FTTHGPT** | Paid QGIS plugin ($70) | Automatic FTTH network generation from a polygon layer | Step 3 | [Gumroad](https://qalifa.gumroad.com/l/owkbp) |

## Observations

- No single commercial tool clearly covers **all ten** steps. The big platforms (Comsof, Setics, Biarri) are strongest at automated HLD/LLD and BOM. Pole-by-pole accessory schedules (J-hooks, tension clamps, UPBs) and Word survey reports are usually done by hand or by consultancy services such as [Osmose make-ready](https://www.osmose.com/make-ready-survey-design).
- Our requirement for **company-specific pole accessory rules** (Step 6) and a **generated survey report** (Step 9) is where a custom tool adds the most value.
- **Data standard:** the [Open Fibre Data Standard (OFDS)](https://open-fibre-data-standard.readthedocs.io/en/0.3/primer/openfibredatastandard.html) and its QGIS plugin [OFDS Studio](https://plugins.qgis.org/plugins/ofds_studio/) define nodes and spans for fibre networks. They're worth aligning our central data model with so data can be exchanged.
- **Why REA wasn't used here:** these products are cloud services or paid installers that we don't have locally. REA inspects files and apps on this machine, so it applies only once a trial build or desktop app is downloaded (for example, a vendor's Electron or .NET desktop client).
