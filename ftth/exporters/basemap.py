"""Map tiles under the drawing sheets: OpenStreetMap streets or Esri World Imagery for an area, as one image.

Tiles (Web Mercator, 256 px) are fetched in parallel, stitched and cropped to the area. Over a project's few
kilometres the local plane of the drawings (ftth.geo.LocalProjection) and Web Mercator differ by far less than a
pixel, so the image is placed by its corners. A tile that cannot be fetched is left blank; if none can be, there
is no image and the sheet is drawn without a map.
"""
from __future__ import annotations

import io
import math
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

STYLES = {
    "streets": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap contributors"),
    "satellite": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                  "Imagery © Esri, Maxar, Earthstar Geographics"),
}
# OpenStreetMap's tile policy asks for an identifying User-Agent
USER_AGENT = "ArchPlanner/1.0 (network planning drawings; https://github.com/maps005/mapsoo56788)"
MAX_TILES = 64            # per image: the zoom drops until the area fits
_CACHE: dict[tuple, bytes | None] = {}
_CACHE_MAX = 600          # tiles kept between the sheets of one drawing (about 15 MB)
_LOCK = threading.Lock()


def _http(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read() if r.status == 200 else None
    except OSError:
        return None


FETCH = _http  # tests replace this; no network in tests


def _tile(style: str, z: int, x: int, y: int) -> bytes | None:
    key = (style, z, x, y)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    data = FETCH(STYLES[style][0].format(z=z, x=x, y=y))
    with _LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = data
    return data


def _merc(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Web Mercator pixel position at zoom z."""
    n = 256 * 2 ** z
    s = math.sin(math.radians(max(min(lat, 85.0), -85.0)))
    return (lon + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def image(style: str, south: float, west: float, north: float, east: float, width_px: int) -> Image.Image | None:
    """The map of the area, width_px wide (height in proportion), or None when no tile could be fetched."""
    if style not in STYLES or not (north > south and east > west) or width_px < 8:
        return None
    lat = (north + south) / 2
    metres = (east - west) * 111195.08 * math.cos(math.radians(lat))
    z = max(1, min(19, round(math.log2(156543.03 * math.cos(math.radians(lat)) / (metres / width_px)))))
    while True:
        x0, y0 = _merc(north, west, z)
        x1, y1 = _merc(south, east, z)
        tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= MAX_TILES or z <= 1:
            break
        z -= 1
    tiles = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        data = list(pool.map(lambda t: _tile(style, z, t[0] % 2 ** z, t[1]), tiles))
    if not any(data):
        return None
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (235, 235, 235))
    for (tx, ty), raw in zip(tiles, data):
        if raw:
            try:
                mosaic.paste(Image.open(io.BytesIO(raw)).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
            except OSError:
                pass  # a broken tile stays blank
    crop = mosaic.crop((round(x0 - tx0 * 256), round(y0 - ty0 * 256), round(x1 - tx0 * 256), round(y1 - ty0 * 256)))
    height = max(1, round(width_px * (north - south) / ((east - west) * math.cos(math.radians(lat)))))
    return crop.resize((width_px, height), Image.LANCZOS)


def faded(img: Image.Image, white: float = 0.35) -> Image.Image:
    """Lighter map so the drawing on it stays readable."""
    return Image.blend(img, Image.new("RGB", img.size, (255, 255, 255)), white)


def attribution(style: str) -> str:
    return STYLES[style][1] if style in STYLES else ""
