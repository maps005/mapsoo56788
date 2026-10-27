"""Calibration against the APPROVED V Squared project "Infinity Densification (257 HPs) FY26".

Client data lives in calibration/infinity-fy26-approved (not in version control); skipped when absent.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "calibration" / "infinity-fy26-approved"
pytestmark = pytest.mark.skipif(not (FOLDER / "design.kmz").exists() or not (FOLDER / "BOM.xlsx").exists(),
                                reason="approved project files not present")
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(scope="module")
def result():
    from calibrate import compare
    return compare(FOLDER, verbose=False)


def test_homepasses_match_home_list(result):
    from ftth import calc
    assert calc.summary(result["design"])["homepasses"] == 257


def test_items_that_match_exactly(result):
    bom = {code: (ref, ours) for code, ref, ours in result["bom"]}
    for code in ("FAT-16P", "FAT-24P", "ENC-SPLICE", "JB", "SPL-1X8", "POLE-NEW", "FOC-24C", "TRUNKING",
                 "WALL-CLAMP", "STEEL-STRAP", "CABLE-TIES"):
        assert bom[code][0] == bom[code][1], (code, bom[code])


def test_cables_within_two_percent(result):
    bom = {code: (ref, ours) for code, ref, ours in result["bom"]}
    for code in ("FOC-12C", "FOC-48C"):
        ref, ours = bom[code]
        assert abs(ours - ref) / ref <= 0.02, (code, ref, ours)


def test_pole_accessories_on_listed_poles(result):
    assert result["matched"] == 49  # every BOM pole found by position although the KMZ renamed them
    for k in ("tension", "upb", "jhooks"):
        ref, ours = result["ref_tot"][k], result["on_ref"][k]
        assert abs(ours - ref) <= max(1, 0.05 * ref), (k, ref, ours)


def test_catalogue_reproduces_approved_boq_total():
    from calibrate import reference
    from ftth.model import DEFAULT_MATERIALS
    rate = {m.code: m.rate for m in DEFAULT_MATERIALS}
    bom = reference(FOLDER)["bom"]
    assert round(sum(q * rate[c] for c, q in bom.items()), 2) == 518758.00


def test_design_is_fully_fed_and_error_free(result):
    from ftth import calc, splicing, validate
    d = result["design"]
    assert calc.assign_homes(d, 300)["unassigned"] == []
    assert splicing.auto_allocate(d)["issues"] == []
    assert all(splicing.trace_upstream(d, s.id)["ok"] for s in d.splitters if s.stage == 2)
    assert validate.counts(validate.validate(d))["errors"] == 0


def test_kmz_photos_are_found():
    from ftth import importers
    photos = importers.extract_kmz_photos((FOLDER / "design.kmz").read_bytes())
    assert len(photos) == 5 and {"KPW-20", "EX VSQ PL-01"} <= {p[0] for p in photos}
