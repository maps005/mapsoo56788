# Can the planner build the approved project? (2026-10-27)

Reference: V Squared *VSQ_FTTH_INFINITY DENSIFICATION (257 HPs) FY26*, approved design
(`calibration/infinity-fy26-approved`: design.kmz, BOM, BOQ, LLD, home list, survey report).

Two tests were run.

| Test | Input given to the planner | Question |
|---|---|---|
| 1 Rebuild | The approved HLD (KMZ) and home list | Given the same design, does the planner produce the same BOM, BOQ and pole summary? |
| 2 Blind design | Survey data only: existing closure *Ex Closure 01*, existing cables, poles, premises with HP counts and one *Proposed Cable End* marker. All proposed FATs, splitters, closures and cables removed | Can the planner design the network by itself, close to what the designer drew? |

Reproduce with `python tools/calibrate.py calibration/infinity-fy26-approved` (test 1) and
`python tools/blind_test.py calibration/infinity-fy26-approved` (test 2), or in the web app:
open the survey-only project and press **Auto-design**.

## Test 1: rebuild from the approved HLD

| Item | Approved | Planner | |
|---|---|---|---|
| Homepasses | 257 | 257 | exact |
| FATs, splitters, JBs, closures | as BOM | same | exact |
| 24C tie cable, trunking, wall clamps, steel strap, buckle clips, cable ties | as BOM | same | exact |
| 12C cable | as BOM | −1.6 % | within rounding |
| 48C cable | as BOM | +0.3 % | within rounding |
| BOQ total with the approved quantities | KES 518,758.00 | KES 518,758.00 | exact (catalogue rates) |
| BOQ total from the planner's own quantities | KES 518,758.00 | KES 520,888.00 | +0.4 % |

**Where the planner is more accurate:** the +0.4 % comes from 8 poles that carry the
proposed cable on the HLD but are missing from the approved pole summary, so their
J-hooks / tension clamps / UPBs were never counted. On the poles the approved summary does
list, accessories are 55 / 26 / 23 against 57 / 27 / 23. The planner counts every pole the
cable actually passes, so it cannot silently drop one.

## Test 2: blind auto-design from survey data

Result in the web app (Auto-design button, 0 errors, all 257 HPs served, all FATs fed):

| Item | Approved | Auto-design | |
|---|---|---|---|
| FATs (24P indoor + 16P outdoor) | 19 (17 + 2) | 19 (16 + 3) | total exact; 95 % within 15 m of an approved FAT |
| Splitters (1x8, both stages) | 24 | 25 | +1 |
| JB | 3 | 3 | exact |
| Closures | 8 | 7 | −1 |
| 12C spur | 1,830 m | 1,770 m | −3 % |
| 48C backbone | 3,150 m | 1,920 m | −39 % (see below) |
| Approved routes followed by auto-design | | 65 % | 88 % of the auto-design lies on approved routes |
| BOQ | KES 518,758 | KES 438,070 | −16 %, mostly the 48C gap |

The scripted run (`tools/blind_test.py`) gives the same network with a BOQ of KES 432,570.

**Why the 48C is short:** the approved design takes the backbone south to KPW-25 for a
future phase. Nothing in the survey data says so: there is no marker, premise or FAT
there. After adding one **Backbone end** marker at that point, auto-design gives 48C
2,600 m (−17 %), closures 8 (exact), new poles 5 vs 6, routes 78 % / 89 %, BOQ KES 453,530.
The rest of the gap is the designer's choice of side streets, which is a judgement call
and not a rule.

**Not derivable blind:** trunking and wall clamps depend on how each building is entered,
which is seen on site and not in the survey points. They stay at 0 until the planner
draws the trunking routes; then the confirmed rules (+10 % +10 m rounded up to 10 m, 2
wall clamps per route) apply automatically.

The 18 warnings left after auto-design all concern the *existing* network in the survey
(5 existing cables with no end equipment, 6 MDUs without a unit count, survey not yet
approved). None comes from the designed network.

## Conclusion

- **Same design in, same quantities out:** yes. BOM items are exact, cables within 2 %, the
  BOQ reproduces to the shilling, and the planner also finds the 8 poles the approved
  summary missed.
- **Design from survey alone:** a good first draft. FAT count, FAT positions, JBs and
  splitters match closely and every premise is served with valid splicing. The planner
  must still mark backbone ends for future phases and draw building-entry trunking.
  Review the routes before issuing.
