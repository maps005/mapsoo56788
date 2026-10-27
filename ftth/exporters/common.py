from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from ..model import Design

KIND_COLOURS = {  # hex RGB used across KML/PDF/DXF legends
    "main": "#e01b24", "spur": "#f5c211", "drop": "#2ec27e",
    "POP": "#9141ac", "ENCLOSURE": "#ff7800", "PR_ENCLOSURE": "#c64600", "JB": "#a347ba",
    "PON": "#e66100", "FAT": "#e01b24", "SLACK": "#57e389", "pole": "#1c71d8", "home": "#33d17a", "mdu": "#26a269",
    "business": "#26a269",
}
NODE_LABEL = {"POP": "POP", "ENCLOSURE": "Splice Enclosure", "PR_ENCLOSURE": "PR Enclosure", "JB": "JB",
              "PON": "PON (1st-stage splitter)", "FAT": "FAT", "SLACK": "Slack loop"}


@dataclass
class Brand:
    """Who issues the documents: the project's company, or the ArchPlanner default."""
    name: str = "ArchPlanner"
    details: str = ""            # address · phone · email · website
    logo: Path | None = None     # PNG / JPG file printed on the documents


@dataclass
class Stamp:
    project: str
    revision: int
    hash: str
    status: str
    date: str
    brand: Brand = field(default_factory=Brand)

    def as_dict(self) -> dict:
        """For JSON outputs: the stamp with the issuer's name (not the logo file)."""
        return {"project": self.project, "revision": self.revision, "hash": self.hash, "status": self.status,
                "date": self.date, "issued_by": self.brand.name}

    @property
    def line(self) -> str:
        return f"{self.project} | Rev {self.revision} | {self.status.upper()} | data {self.hash} | {self.date}"


def logo_size(path: Path | None, max_w: float, max_h: float) -> tuple[float, float] | None:
    """Width and height that fit a logo inside max_w x max_h, keeping its proportions (None if unreadable)."""
    if not path:
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
    except (OSError, ValueError):
        return None
    if not w or not h:
        return None
    k = min(max_w / w, max_h / h)
    return w * k, h * k


def stamp(d: Design, revision: int, brand: Brand | None = None) -> Stamp:
    return Stamp(d.info.name, revision, d.content_hash(), d.info.design_status, date.today().isoformat(),
                 brand or Brand())


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PHOTO_NAME = re.compile(r"[0-9a-f]{10}\.(jpg|jpeg|png)")


def clean(text) -> str:
    """Text without control characters that XML / Excel cannot store."""
    return _CONTROL.sub("", "" if text is None else str(text))


def markup(text) -> str:
    """User text made safe for ReportLab Paragraph markup (no tags, links or images)."""
    return escape(clean(text)).replace("\n", "<br/>")


def photo_path(photo_dir: Path | None, name: str) -> Path | None:
    """The stored photo file, only if the name is a generated photo name inside this project's folder
    and the file really is an image."""
    if photo_dir is None or not PHOTO_NAME.fullmatch(name or ""):
        return None
    path = (photo_dir / name).resolve()
    try:
        path.relative_to(photo_dir.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
    except Exception:
        return None
    return path


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
