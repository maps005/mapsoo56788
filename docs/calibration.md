# Rule calibration: V Squared "Infinity Densification FY26"

**Date:** 2026-10-26.

**Source files** (client data, kept in `calibration/infinity-fy26/`, not in version control):
- `design.kmz`: the design.
- `BOM.xlsx`: pole details, cable lengths and the BOM.
- `BOQ.xlsx`: rates.
- `survey-report.pdf`

**To re-run the comparison:**

```bash
.venv\Scripts\python tools\calibrate.py calibration\infinity-fy26
```

`tests/test_calibration.py` locks in the results below. The test is skipped when the files are absent.

## Rules derived from the project

| Rule | Value | How it was derived |
|---|---|---|
| Cable length | measured + **10 %** + **20 m** end allowance + **0.5 m sag per route point**, rounded **up to 10 m** | Reproduces all 18 "Rounded Length" values in the BOM (17 exactly; 1 crosses a rounding step by 2 m of measurement) |
| Slack | **30 m** per equipment site on the cable: closures, JBs, FATs, slack points. Co-located items count once. Ends with no equipment get none. FATs passed mid-route count only on main (48C) cables | Exact for all four 48C cables. 12C slack is designer judgement (9 of 14 match), total −30 m |
| Tension clamps | 1 per cable end, 2 per cable at corners (deflection ≥ **45°**), and 2 at an **anchor pole after 3 J-hook poles in a row** | 55 against 57 on the 49 BOM poles |
| J-hooks | 1 per cable at other straight poles; none where the pole already carries clamps | 23 against 23 |
| UPB | 1 per started group of **4** tension clamps (6 clamps → 2 UPB) | 26 against 27 |
| Extension arm | 1 on transformer (**KPTX**) poles carrying the new cable | 1, exact (KPTX-01) |
| Accessories on existing cables | not counted | The BOM ignores the existing 24C/48C routes |
| New pole next to existing | a proposed pole within 2.5 m of an existing one takes the equipment and accessories | PR VSQ PL-06 beside KP-W 14 |
| Consumables | steel straps 1 roll per 15 UPB (rounded up); buckle clips 2 per UPB (nearest 10); cable ties 1 pkt per 15 UPB (rounded up) | Fitted to **one** project; confirm with your standards |
| Rates | BOQ item descriptions and KES rates (excl. VAT) | Copied from the BOQ |

## Results

| Item | BOM | Planner |
|---|---|---|
| FAT 16P / FAT 24P | 2 / 17 | 2 / 17 |
| Splice closures (FTB 48c) | 8 | 8 |
| Junction boxes | 3 | 3 |
| Splitters 1x16 / 1x8 | 3 / 18 | 3 / 18 |
| New poles | 6 | 6 |
| 48C cable | 3,150 m | 3,160 m (+0.3 %) |
| 12C cable | 1,830 m | 1,800 m (−1.6 %) |
| Tension clamps / UPB / J-hooks / extension arm on the 49 BOM poles | 57 / 27 / 23 / 1 | 55 / 26 / 23 / 1 (30 poles identical) |

Fibre allocation feeds all 18 FAT splitters from the existing interception closure. The route is Ex Closure 150 → 48C → PR SC-01 / SC-02 / SC-04 / SC-07 primary splitters → 12C spurs.

## Differences to review in the BOM

1. **Poles missing from the BOM's Pole Details sheet.** KP-W 09 and KP-W 15–19, plus PR VSQ PL-05, carry the 48C branch to PR SC-06 and three 12C spurs. The BOM includes those cable lengths but no accessories for these poles. The planner adds 12 tension clamps, 5 UPBs and 4 J-hooks there, so the planner's totals are higher than the BOM's: 69 / 32 / 27 against 57 / 27 / 23.
2. **Extension arm** is listed in Pole Details (KPTX-01) but is not an item in the BOM/BOQ. It is in the planner's BOM without a rate, so add a rate in *Materials & rules*.
3. **Indoor FATs** PR IND FAT-03, -10 and -13 are drawn 4–8 m from their cable. The importer attaches them and says so in the import report.
4. **MDU 121 UC and MDU 147** have no unit count in their names, so they were imported as 1 unit. Correct them in the data tab.
5. **Five large MDUs** cannot be assigned automatically within the 24-port capacity: MDU 116, Beulah Apartments, MDU 155, MDU 157 and Infinity Towers. Assign them manually or add FAT capacity.

## Limits

- One project is a small sample. The anchor spacing and consumable ratios in particular should be checked against one or two more completed projects.
- Per-pole anchor positions follow a fixed rule. Designers choose individual anchor poles by eye, so 20 of 49 poles differ even though the totals match.

## Update after the 2026-10-26 test round

Removing phantom corners (a route point drawn twice on one pole) made KP-W 13 match the BOM exactly: 3 clamps instead of 5. The earlier exact total had partly been two errors cancelling. See `docs/qa-report-2026-10-26.md`.

## Approved project: "Infinity Densification (257 HPs) FY26" (2026-10-26)

Files are in `calibration/infinity-fy26-approved/`:
- HLD KMZ (with 5 pole photos)
- LLD PDF (9 A3 sheets)
- BOM
- BOQ
- home list
- survey report

The approved project is now the reference; `tests/test_calibration_approved.py` locks it in.

**What changed from the draft, and what the planner now does**

| Approved change | Planner |
|---|---|
| 48C rate KES 69/m (draft 44.578) | Catalogue updated. All approved items and rates are in the catalogue: BOM quantities × catalogue rates = **KES 518,758.00**, exactly the approved total |
| Primary splitters 1x8 (draft 1x16) | Default first-stage split is now 1x8 |
| 24 × 1x8 splitters: placemarks such as "1X8 SPL 1A & 2A" hold two | Combined labels import as two splitters, and each one is fed |
| New items: 3 × 20 m 24C tie cables, 2 wall clamps, 30 m plastic trunking | Rules: 20 m 24C per proposed JB; trunking routes from the KMZ = measured +10 % +10 m, rounded up to 10 m; 2 wall clamps per trunking route. All three match exactly. **Confirmed as company standard by V Squared (2026-10-27)** |
| Existing cables in their own `CABLES/EXISTING` folder; no "PR FOC" folder | Every cable outside the EXISTING folder imports as proposed |
| Poles renamed (KP-W 06 → KPW-01 …); the BOM pole sheet still uses the old names | The comparison matches poles by position, and all 49 are found |
| Home list: 257 HPs | Home lists in this layout import and merge with the KMZ buildings (same name, or within 15 m). Blank "VIABLE HP" = not counted. A matching **Home List** deliverable is exported. Homepasses = **257** exactly |
| LLD: cover, safety, legend, Google Earth extract, 3 route sheets, splicing details, pole summary, each with a MAIN WORK LOAD strip and title block | The LLD PDF is now an A3 set: cover, overview, route sheets at 1:1500, splicing details and pole summary (with Extension Arm and Slack). Every sheet has the work-load strip and a title block with company, approved / checked / lead planner / planned / drawn by, drawing number and page |
| Photos embedded in the KMZ | Imported as survey photos and linked to their poles |
| Large MDUs (up to 36 HPs) | Can be served by several FATs within 60 m; all 23 premises are assigned |

**Results against the approved BOM**

- **Exact:** FATs 16P / 24P, splice closures, JBs, 1x8 splitters, new poles, 24C tie cable, trunking, wall clamps, straps, cable ties and homepasses.
- **Cables:** 12C 1,800 m against 1,830 (−1.6 %); 48C 3,160 m against 3,150 (+0.3 %).
- **Pole accessories (tension / UPB / J-hook) on the 49 listed poles:** planner 55 / 26 / 23, approved 57 / 27 / 23.
- **Unlisted poles:** the planner also counts 10 / 4 / 4 on the 8 poles the approved pole summary does not list. These carry the 48C branch to PR SC-06 and three 12C spurs. The approved BOM is unchanged from the draft here, so the omission is still present.
- **BOQ:** planner KES 520,888 against approved 518,758 (+0.4 %). The difference is entirely those extra pole accessories. The extension arm on KPTX has no BOQ rate in the approved BOQ either.

**Not derived:**
- The SLACK column of the approved pole summary (1 at KP-W 06 only). The planner reports slack loops within 10 m of each pole instead.
- The safety-details and legend pages of the approved LLD (static content).
