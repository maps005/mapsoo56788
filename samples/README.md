# Sample project: "Sample FTTH project (demo)"

A small made-up project (Demo estate, Nairobi, for "Demo ISP") for trying ArchPlanner end to end. It contains no
client data. Regenerate the files with `python tools/make_samples.py`.

| Step | File | What to do with it |
|---|---|---|
| 1. Survey | `1-survey/demo-survey-data.xlsx` | Create a **New** project and import this file on the **Survey & validation** tab: 5 existing poles, 8 premises (13 homepasses) and the existing POP. Approve the survey, then run **Auto-design**. |
| 2. Design | `2-design/demo-design.kmz` | The finished design (HLD) as Google Earth KMZ: open it in Google Earth or import it into a new project. |
| 2. Design | `2-design/demo-project.json` | The complete project data, as the app stores it. |
| 3. Deliverables | `3-deliverables/demo-design-package.zip` | Every deliverable generated from the design: HLD (KMZ/KML/PDF), LLD (DXF/PDF), pole summary, BOM, BOQ, splicing, survey report (PDF/Word/Excel), home list, QA report and project data. |

The quickest way to see the same project inside the app is the **Sample** button in the planner header.
