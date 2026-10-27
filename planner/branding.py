"""Whose name and logo the site and the documents show.

The site shows the signed-in user's active company (its logo, name and details); documents show the project's
company. With no company - or once the company is deleted - both fall back to the ArchPlanner defaults.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.templatetags.static import static

from ftth.exporters.common import Brand

DEFAULT_NAME = "ArchPlanner"
DEFAULT_LOGO_FILE = Path(settings.BASE_DIR) / "planner" / "static" / "planner" / "img" / "archplanner-logo.png"


def _details(c) -> str:
    return " · ".join(x for x in (c.address.replace("\n", ", ").strip(), c.phone, c.email, c.website,
                                   f"PIN {c.tax_pin}" if c.tax_pin else "") if x)


def _logo_file(c) -> Path | None:
    try:
        p = Path(c.logo.path) if c and c.logo else None
    except (ValueError, NotImplementedError):
        return None
    return p if p and p.is_file() else None


def site_brand(user) -> dict:
    """Header, admin and favicon branding for a user."""
    from .views import active_company
    c = active_company(user) if getattr(user, "is_authenticated", False) else None
    if c is None:
        return {"is_company": False, "name": DEFAULT_NAME, "logo": "", "icon": static("planner/img/favicon.png"),
                "details": ""}
    logo = f"/company/{c.id}/logo" if _logo_file(c) else ""
    return {"is_company": True, "id": c.id, "name": c.name, "legal_name": c.legal_name, "logo": logo,
            "icon": logo or static("planner/img/favicon.png"), "details": _details(c)}


def document_brand(company) -> Brand:
    """Name, details and logo printed on a project's documents."""
    if company is None:
        return Brand(name=DEFAULT_NAME, logo=DEFAULT_LOGO_FILE if DEFAULT_LOGO_FILE.is_file() else None)
    logo = _logo_file(company)
    return Brand(name=company.legal_name or company.name, details=_details(company),
                 logo=logo or (DEFAULT_LOGO_FILE if DEFAULT_LOGO_FILE.is_file() else None))


def context(request) -> dict:
    """Template context processor: {{ brand }} everywhere."""
    return {"brand": site_brand(getattr(request, "user", None))}
