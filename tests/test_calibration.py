"""Calibration against a completed V Squared project (Infinity Densification FY26).

The project files are client data kept out of version control in calibration/;
the test is skipped when they are not present.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "calibration" / "infinity-fy26"
pytestmark = pytest.mark.skipif(not (FOLDER / "design.kmz").exists() or not (FOLDER / "BOM.xlsx").exists(),
                                reason="calibration project files not present")
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(scope="module")
def result():
    from calibrate import compare
    return compare(FOLDER, verbose=False)


def test_equipment_matches_bom_exactly(result):
    # SPL-1X8 is checked against the approved project: the draft BOM counted the placemarks
    # "1X8 SPL 1A & 2A" / "3C & 4C" as one splitter each, which the approved BOM corrected.
    bom = {code: (ref, ours) for code, ref, ours in result["bom"]}
    for code in ("FAT-16P", "FAT-24P", "ENC-SPLICE", "JB", "SPL-1X16", "POLE-NEW"):
        assert bom[code][0] == bom[code][1], code


def test_cable_totals_within_two_percent(result):
    bom = {code: (ref, ours) for code, ref, ours in result["bom"]}
    for code in ("FOC-12C", "FOC-48C"):
        ref, ours = bom[code]
        assert abs(ours - ref) / ref <= 0.02, (code, ref, ours)


def test_pole_accessories_on_bom_poles(result):
    # totals within 5 % on the poles the BOM lists; anchor poles are chosen by eye, so not every pole matches
    for k in ("tension", "upb", "jhooks"):
        ref, ours = result["ref_tot"][k], result["on_ref"][k]
        assert abs(ours - ref) <= max(1, 0.05 * ref), (k, ref, ours)
    assert result["on_ref"]["ext_arms"] == result["ref_tot"]["ext_arms"]
    assert result["exact"] >= 30


def test_allocation_feeds_every_fat_splitter(result):
    from ftth import calc, splicing, validate
    d = result["design"]
    calc.assign_homes(d, 300)
    res = splicing.auto_allocate(d)
    assert res["issues"] == []
    assert all(splicing.trace_upstream(d, s.id)["ok"] for s in d.splitters if s.stage == 2)
    assert validate.counts(validate.validate(d))["errors"] == 0
