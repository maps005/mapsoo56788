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

    @classmethod
    def for_points(cls, pts: list[tuple[float, float]]) -> "LocalProjection":
        if not pts:
            return cls(0.0, 0.0)
        return cls(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def valid_coord(lat, lon) -> bool:
    return (lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180
            and not (abs(lat) < 1e-9 and abs(lon) < 1e-9))
