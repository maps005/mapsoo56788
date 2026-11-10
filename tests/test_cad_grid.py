"""CAD coordinates and scale: UTM grid projections, the DXF in real coordinates, symbols sized for the scale."""
import io

import ezdxf
import pytest

from ftth.exporters import dxf
from ftth.exporters.common import stamp
from ftth.geo import GridProjection, projection
from ftth.sample import sample_design


@pytest.mark.parametrize("crs", ["utm", "arc1960"])
def test_grid_round_trips_and_names_its_zone(crs):
    g = GridProjection(crs, -1.2864, 36.8172)
    e, n = g.xy(-1.2864, 36.8172)
    lat, lon = g.latlon(e, n)
    assert abs(lat + 1.2864) < 1e-7 and abs(lon - 36.8172) < 1e-7  # a centimetre or better
    assert g.name.startswith("WGS 84 / UTM zone 37S (EPSG:32737)" if crs == "utm" else "Arc 1960 / UTM zone 37S (EPSG:21037)")


def test_utm_matches_the_published_grid():
    # Nairobi (1.2864 S, 36.8172 E) in WGS 84 / UTM 37S: about E 257 111, N 9 857 710
    e, n = GridProjection("utm", -1.2864, 36.8172).xy(-1.2864, 36.8172)
    assert abs(e - 257110.7) < 1 and abs(n - 9857710.0) < 1
    # Arc 1960 sits about 100 m west and 300 m north of WGS 84 on the grid in Kenya
    e2, n2 = GridProjection("arc1960", -1.2864, 36.8172).xy(-1.2864, 36.8172)
    assert -130 < e2 - e < -70 and 250 < n2 - n < 350


def _dxf(d):
    return ezdxf.read(io.StringIO(dxf.build_dxf(d, stamp(d, 1)).decode())).modelspace()


def test_the_dxf_uses_the_projects_coordinates_and_scale():
    d = sample_design()
    assert d.info.crs == "utm" and d.info.cad_scale == 1500
    p = d.poles[0]
    e, n = projection("utm", [(p.lat, p.lon)]).xy(p.lat, p.lon)
    msp = _dxf(d)
    circles = [c for c in msp if c.dxftype() == "CIRCLE" and c.dxf.layer == "POLES"]
    assert min(abs(c.dxf.center.x - e) + abs(c.dxf.center.y - n) for c in circles) < 0.5  # at the pole's grid position
    assert any(t.dxf.text.startswith("Coordinates: WGS 84 / UTM") for t in msp if t.dxftype() == "TEXT")
    d.info.cad_scale = 500  # a third of the paper scale: symbols a third of the size
    small = [c for c in _dxf(d) if c.dxftype() == "CIRCLE" and c.dxf.layer == "POLES"]
    assert abs(min(c.dxf.radius for c in small) - min(c.dxf.radius for c in circles) / 3) < 1e-6
    d.info.crs = "local"
    assert max(abs(c.dxf.center.x) for c in _dxf(d) if c.dxftype() == "CIRCLE") < 5000  # metres round the centre
