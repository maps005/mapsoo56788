"""Automatic design from survey data."""
import sys
from pathlib import Path

import pytest

from ftth import autodesign, calc, splicing, validate
from ftth.sample import sample_design

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "calibration" / "infinity-fy26-approved"
sys.path.insert(0, str(ROOT / "tools"))


def test_auto_design_on_sample_is_complete_and_fed():
    d = sample_design()
    res = autodesign.auto_design(d)
    assert res["allocation_issues"] == [] and res["unassigned"] == []
    assert all(splicing.trace_upstream(d, s.id)["ok"] for s in d.splitters if s.stage == 2)
    assert validate.counts(validate.validate(d))["errors"] == 0
    assert any(c.cores == 48 for c in d.cables if c.status == "proposed")


def test_auto_design_needs_an_interception_point():
    d = sample_design()
    d.nodes = [n for n in d.nodes if n.kind != "POP"]
    d.cables = []
    with pytest.raises(ValueError):
        autodesign.auto_design(d)


@pytest.mark.skipif(not (FOLDER / "design.kmz").exists(), reason="approved project files not present")
def test_blind_design_of_approved_project():
    import blind_test
    r = blind_test.run(FOLDER, verbose=False)
    bom = {c: (a, b) for c, a, b in r["bom"]}
    assert r["alloc"] == [] and r["unassigned"] == [] and r["errors"] == []
    assert r["homepasses"] == 257
    assert r["fat_within_15m"] >= 0.9                     # FAT locations
    assert bom["JB"][0] == bom["JB"][1]                    # one PON per 8 FAT splitters
    assert abs(bom["SPL-1X8"][1] - bom["SPL-1X8"][0]) <= 2
    assert abs(bom["FOC-12C"][1] - bom["FOC-12C"][0]) / bom["FOC-12C"][0] <= 0.15
    assert r["overlap_planner_in_approved"] >= 0.8         # the planner's cables follow approved routes
    assert r["overlap_approved_in_planner"] >= 0.6
