"""Small geodesy helpers (WGS84 lat/lon)."""
from __future__ import annotations

import math

R = 6371008.8  # mean Earth radius, metres


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def deflection(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """Change of direction in degrees at b when travelling a -> b -> c (0 = straight)."""
    d = abs(bearing(*a, *b) - bearing(*b, *c)) % 360
    return 360 - d if d > 180 else d


class LocalProjection:
    """Equirectangular projection to metres around an origin; accurate to well under 0.1% over a few km."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = math.radians(1) * R * math.cos(math.radians(lat0))
        self.ky = math.radians(1) * R

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        """Inverse of xy."""
        return self.lat0 + y / self.ky, self.lon0 + x / self.kx

    @classmethod
    def for_points(cls, pts: list[tuple[float, float]]) -> "LocalProjection":
        if not pts:
            return cls(0.0, 0.0)
        return cls(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


# ---------------------------------------------------------------------------------------------------------
# grid coordinates for CAD: Transverse Mercator (UTM) on WGS 84, or on Arc 1960 (Clarke 1880, Kenya's survey datum)
# ---------------------------------------------------------------------------------------------------------
ELLIPSOIDS = {"wgs84": (6378137.0, 1 / 298.257223563), "clarke1880": (6378249.145, 1 / 293.465)}
ARC1960_SHIFT = (157.0, 2.0, 299.0)  # WGS 84 -> Arc 1960 (Kenya), metres: the reverse of Arc 1960 -> WGS 84 (-157, -2, -299)
CRS_LABELS = {"local": "Local plane", "utm": "WGS 84 / UTM", "arc1960": "Arc 1960 / UTM"}


def _ecef(lat, lon, h, a, f):
    e2 = f * (2 - f)
    p, l = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    return (n + h) * math.cos(p) * math.cos(l), (n + h) * math.cos(p) * math.sin(l), (n * (1 - e2) + h) * math.sin(p)


def _geodetic(x, y, z, a, f):
    e2 = f * (2 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(6):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * n * math.sin(lat), p)
    return math.degrees(lat), math.degrees(lon)


def wgs84_to_arc1960(lat, lon):
    x, y, z = _ecef(lat, lon, 0.0, *ELLIPSOIDS["wgs84"])
    dx, dy, dz = ARC1960_SHIFT
    return _geodetic(x + dx, y + dy, z + dz, *ELLIPSOIDS["clarke1880"])


def arc1960_to_wgs84(lat, lon):
    x, y, z = _ecef(lat, lon, 0.0, *ELLIPSOIDS["clarke1880"])
    dx, dy, dz = ARC1960_SHIFT
    return _geodetic(x - dx, y - dy, z - dz, *ELLIPSOIDS["wgs84"])


def tm_forward(lat, lon, lon0, a, f, k0=0.9996, fe=500000.0, fn=0.0):
    """Transverse Mercator (Snyder, USGS PP 1395): easting, northing in metres."""
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    p, dl = math.radians(lat), math.radians(lon - lon0)
    n = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    t, c = math.tan(p) ** 2, ep2 * math.cos(p) ** 2
    A = dl * math.cos(p)
    m = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * p - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * p)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * p) - (35 * e2 ** 3 / 3072) * math.sin(6 * p))
    x = k0 * n * (A + (1 - t + c) * A ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * A ** 5 / 120)
    y = k0 * (m + n * math.tan(p) * (A * A / 2 + (5 - t + 9 * c + 4 * c * c) * A ** 4 / 24
                                     + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * A ** 6 / 720))
    return fe + x, fn + y


def tm_inverse(e, nn, lon0, a, f, k0=0.9996, fe=500000.0, fn=0.0):
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    m = (nn - fn) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(p1) ** 2)
    t1, c1 = math.tan(p1) ** 2, ep2 * math.cos(p1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(p1) ** 2) ** 1.5
    d = (e - fe) / (n1 * k0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
                                           + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120) / math.cos(p1)
    return math.degrees(lat), lon0 + math.degrees(lon)


class GridProjection:
    """UTM grid coordinates (easting, northing in metres) on WGS 84 or Arc 1960, the zone from the project centre;
    the same xy / latlon interface as LocalProjection, so drawings come out in real survey coordinates."""

    def __init__(self, crs: str, lat0: float, lon0: float):
        self.crs = crs
        self.zone = max(1, min(60, int((lon0 + 180) // 6) + 1))
        self.south = lat0 < 0
        self.lon0 = (self.zone - 1) * 6 - 180 + 3
        self.fn = 10000000.0 if self.south else 0.0
        self.ell = ELLIPSOIDS["clarke1880" if crs == "arc1960" else "wgs84"]

    @property
    def name(self) -> str:
        epsg = (21000 + self.zone + (0 if self.south else 60)) if self.crs == "arc1960" else (32700 if self.south else 32600) + self.zone
        return f"{CRS_LABELS[self.crs]} zone {self.zone}{'S' if self.south else 'N'} (EPSG:{epsg})"

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        if self.crs == "arc1960":
            lat, lon = wgs84_to_arc1960(lat, lon)
        return tm_forward(lat, lon, self.lon0, *self.ell, fn=self.fn)

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        lat, lon = tm_inverse(x, y, self.lon0, *self.ell, fn=self.fn)
        return arc1960_to_wgs84(lat, lon) if self.crs == "arc1960" else (lat, lon)


def projection(crs: str, pts: list[tuple[float, float]]):
    """The drawing's projection: a local plane round the points, or UTM grid coordinates."""
    local = LocalProjection.for_points(pts)
    if crs in ("utm", "arc1960") and pts:
        g = GridProjection(crs, local.lat0, local.lon0)
        g.lat0, g.local = local.lat0, local
        return g
    local.name = f"Local plane, origin {local.lat0:.6f}, {local.lon0:.6f} (WGS 84)"
    return local


def valid_coord(lat, lon) -> bool:
    return (lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180
            and not (abs(lat) < 1e-9 and abs(lon) < 1e-9))
