"""JSON API used by the planner UI, plus the page itself.

All design logic lives in the framework-independent `ftth` package; these views
handle authentication, access control, persistence and concurrent editing.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import uuid
from urllib.parse import quote
from dataclasses import asdict
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from pydantic import ValidationError

from ftth import calc, importers, sectors, splicing, standards, validate
from ftth.exporters import package
from ftth.exporters.common import stamp
from ftth.model import DEFAULT_MATERIALS, Design, Photo, ProjectInfo
from ftth.sample import sample_design

from .models import Comment, Company, ExportRecord, Membership, Profile, Project, Revision, role_in


class ApiError(Exception):
    def __init__(self, status: int, detail: str, **extra):
        super().__init__(detail)
        self.status, self.detail, self.extra = status, detail, extra


def api(*methods: str):
    """JSON endpoint: authenticated users only; ApiError becomes a JSON error response."""
    def deco(fn):
        @require_http_methods(list(methods))
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"detail": "Please sign in"}, status=401)
            try:
                return fn(request, *args, **kwargs)
            except ApiError as e:
                return JsonResponse({"detail": e.detail, **e.extra}, status=e.status)
        return wrapper
    return deco


def _project(request, pid: str, lock: bool = False, edit: bool = True) -> Project:
    """The project if the user may see it (edit=False) or change it (edit=True: owner, shared member, or a
    planner / approver / admin of its company; company viewers only read and comment)."""
    qs = Project.objects.editable_by(request.user) if edit else Project.objects.visible_to(request.user)
    if lock:
        qs = qs.select_for_update()
    try:
        return qs.get(pk=pid)
    except Project.DoesNotExist:
        if edit and Project.objects.visible_to(request.user).filter(pk=pid).exists():
            raise ApiError(403, "You can view this project but not change it (company viewer)")
        raise ApiError(404, "Project not found")


def _body(request) -> dict:
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError(400, "Invalid JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "Expected a JSON object")
    return body


def _text(body: dict, key: str, max_len: int = 500, default: str = "") -> str:
    v = body.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError(400, f"'{key}' must be text")
    return v.strip()[:max_len]


SURVEY_ERROR_CODES = {"id_missing", "id_duplicate", "coord_missing", "coord_invalid", "units_invalid"}


SURVEY_POLE = ("id", "lat", "lon", "type", "height_m", "condition", "status", "notes")
SURVEY_HOME = ("id", "lat", "lon", "kind", "units", "name", "address", "access_notes", "acquired", "field_type", "notes")
SURVEY_NODE = ("id", "kind", "lat", "lon", "pole", "status", "ports", "notes")


def _survey_fingerprint(d: Design) -> str:
    """Hash of what the survey delivered: existing poles, premises (not their FAT assignment), existing equipment
    and cables. Design work (new poles, FATs, routes, assignments) does not change it, so approval survives it;
    editing surveyed data after approval returns the survey to draft."""
    import hashlib
    pick = lambda x, keys: [getattr(x, k) for k in keys]  # noqa: E731
    raw = json.dumps([
        [pick(p, SURVEY_POLE) for p in d.poles if p.status == "existing"],
        [pick(h, SURVEY_HOME) for h in d.homes],
        [pick(n, SURVEY_NODE) for n in d.nodes if n.status == "existing"],
        [[c.id, c.cores, [[round(v.lat, 7), round(v.lon, 7)] for v in c.path]] for c in d.cables if c.status == "existing"],
    ], sort_keys=True, default=str)
    return "v2:" + hashlib.sha256(raw.encode()).hexdigest()[:12]


@api("POST")
def apply_standard(request, pid):
    """Reset the project's rules and design style to a design standard (default: its company's)."""
    body = _body(request)

    def run(d):
        proj = Project.objects.select_related("company").get(pk=pid)
        key = body.get("standard") or (proj.company.design_standard if proj.company else "system")
        if key not in standards.STANDARDS:
            raise ApiError(400, f"standard must be one of {', '.join(standards.STANDARDS)}")
        if d.info.design_status == "approved":
            raise ApiError(409, "The design is approved: return it to draft before changing its rules")
        standards.apply(d, key)
        return {"standard": key, "label": standards.STANDARDS[key]["label"]}
    st, res = _operate(request, pid, run)
    return JsonResponse(st | {"result": res})


@api("GET")
def list_sectors(request):
    return JsonResponse([{"key": k, "label": v["label"]} for k, v in sectors.SECTORS.items()], safe=False)


@api("POST")
def apply_sector(request, pid):
    """Switch the project to a sector (names, rules and - unless keep_materials - its material catalogue)."""
    body = _body(request)
    key = body.get("sector")
    if key not in sectors.SECTORS:
        raise ApiError(400, f"sector must be one of {', '.join(sectors.SECTORS)}")

    def run(d):
        if d.info.design_status == "approved":
            raise ApiError(409, "The design is approved: return it to draft before changing its sector")
        sectors.apply(d, key, materials=not body.get("keep_materials"))
        return {"sector": key, "label": sectors.SECTORS[key]["label"]}
    st, res = _operate(request, pid, run)
    return JsonResponse(st | {"result": res})


@api("GET")
def list_standards(request):
    return JsonResponse([{"key": k, "label": v["label"], "design_style": v["design_style"]}
                         for k, v in standards.STANDARDS.items()], safe=False)


def _num_or_none(v):
    """A whole number, or None (24.5, "16x" and True are not whole numbers of ports or cores)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else None


def _photo_dir(pid: str) -> Path:
    p = Path(settings.MEDIA_ROOT) / "photos" / pid
    p.mkdir(parents=True, exist_ok=True)
    return p


def _can_approve(user, p: Project | None = None) -> bool:
    if p is not None:
        return p.can_approve(user)
    return user.has_perm("planner.approve_design") or \
        Membership.objects.filter(user=user, role__in=["approver", "admin", "owner"]).exists()


def active_company(user) -> Company | None:
    """The company new projects go to: the profile's choice, else the user's only company."""
    prof = Profile.objects.filter(user=user).select_related("active_company").first()
    if prof and prof.active_company and Membership.objects.filter(user=user, company=prof.active_company).exists():
        return prof.active_company
    ms = list(Membership.objects.filter(user=user).select_related("company")[:2])
    return ms[0].company if len(ms) == 1 else None


def _doc_brand(request, p: Project):
    """Documents carry the project's company (else the user's company, else the ArchPlanner default)."""
    from .branding import document_brand
    return document_brand(p.company or active_company(request.user))


def company_dict(c: Company | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "name": c.name, "logo": f"/company/{c.id}/logo" if c.logo else "",
            "design_standard": c.design_standard, "sector": c.sector}


def _person(u, access: str) -> dict:
    return {"username": u.get_username(), "name": u.get_full_name(), "email": u.email, "access": access}


def _people(p: Project) -> list[dict]:
    """Everyone with access to the project, most access first."""
    out = [_person(p.owner, "owner")]
    if p.assigned_to_id and p.assigned_to_id != p.owner_id:
        out.append(_person(p.assigned_to, "assigned"))
    seen = {x["username"] for x in out}
    out += [_person(u, "edit") for u in p.members.order_by("username") if u.get_username() not in seen]
    seen |= {x["username"] for x in out}
    out += [_person(u, "view") for u in p.viewers.order_by("username") if u.get_username() not in seen]
    return out


def _version(p: Project) -> str:
    """The project's version token: the hash stored when it was last saved. Saves compare against this same
    stored value, so a newer data model (new fields with defaults change content_hash) never makes an
    unchanged project look as if someone else had saved it."""
    return p.data_hash or p.design.content_hash()


def _state(request, p: Project, d: Design | None = None) -> dict:
    d = d or p.design
    issues = validate.validate(d)
    h = _version(p)
    exports = {e.deliverable: e for e in p.exports.all()}
    part = {k: package.deliverable_hash(d, k) for k in package.DELIVERABLES}
    return {
        "id": p.id, "design": d.model_dump(mode="json"), "hash": h, "revision": p.current_version,
        "issues": issues, "counts": validate.counts(issues), "summary": calc.summary(d),
        "owner": p.owner.get_username(), "members": [u.get_username() for u in p.members.all()],
        "people": _people(p),
        "sector": sectors.profile(d.info.sector),
        "is_owner": p.owner_id == request.user.id or request.user.is_superuser,
        "can_edit": p.can_edit(request.user), "can_approve": p.can_approve(request.user),
        "can_manage": p.can_manage(request.user), "company": company_dict(p.company),
        "comments_open": p.comments.filter(resolved=False).count(),
        "updated": p.updated.isoformat() if p.updated else None,
        "updated_by": p.updated_by.get_username() if p.updated_by else None,
        "outputs": {k: {"title": package.TITLES[k], "formats": list(v),
                        "last": ({"hash": exports[k].data_hash, "version": exports[k].version,
                                  "created": exports[k].created.isoformat()} if k in exports else None),
                        "stale": k in exports and exports[k].data_hash != part[k]}
                    for k, v in package.DELIVERABLES.items()},
    }


def _save(request, p: Project, d: Design) -> dict:
    p.set_design(d, request.user)
    p.save()
    return _state(request, p, d)


def _commit(request, pid: str, base_hash: str, d: Design) -> Project:
    """Write d in a short transaction, only if the project is still the version the work started from.
    Long calculations run before this, so they never hold the database lock (SQLite allows one writer)."""
    with transaction.atomic():
        p = _project(request, pid, lock=True)
        if _version(p) != base_hash:
            who = p.updated_by.get_username() if p.updated_by else "another user"
            raise ApiError(409, f"{who} saved changes to this project while this was running. "
                                f"Reload to get the latest version, then run it again.", conflict=True)
        p.set_design(d, request.user)
        p.save()
    return p


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
@ensure_csrf_cookie
@login_required
def index(request):
    return render(request, "planner/index.html", {"can_approve": _can_approve(request.user)})


@api("GET")
def defaults(request):
    """Company default rules and material catalogue (used by 'Load company rules / catalogue')."""
    c = active_company(request.user)
    d = Design()
    standards.apply(d, c.design_standard if c is not None and c.design_standard in standards.STANDARDS else "system")
    return JsonResponse({"rules": d.rules.model_dump(mode="json"), "design_style": d.info.design_style,
                         "materials": [m.model_dump(mode="json") for m in DEFAULT_MATERIALS]})


@api("POST")
def import_prices(request, pid):
    """Update the project's material catalogue from a price list or BOQ template (Excel)."""
    f = request.FILES.get("file")
    if not f or not f.name.lower().endswith((".xlsx", ".xlsm")):
        raise ApiError(400, "Choose an Excel price list (.xlsx)")
    data = f.read()

    def run(d):
        try:
            return importers.import_price_list(d, data)
        except Exception as e:  # malformed workbook
            raise ApiError(400, f"Could not read {f.name}: {e}")
    st, report = _operate(request, pid, run)
    return JsonResponse(st | {"prices": report})


@api("GET")
def survey_template(request):
    """Blank Excel workbook for uploading survey data (poles, homes, equipment, splitters, cables)."""
    from ftth.exporters import excel
    return _download(excel.survey_template_xlsx(), "FTTH_survey_upload_template.xlsx", "xlsx")


@api("GET")
def me(request):
    u = request.user
    return JsonResponse({"username": u.get_username(), "name": u.get_full_name() or u.get_username(),
                         "can_approve": _can_approve(u), "is_staff": u.is_staff,
                         "company": company_dict(active_company(u))})


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@api("GET", "POST")
def projects(request):
    if request.method == "GET":
        return JsonResponse([{"id": p.id, "name": p.name, "owner": p.owner.get_username(),
                              "company": p.company.name if p.company else "", "updated": p.updated.isoformat()}
                             for p in Project.objects.visible_to(request.user).select_related("owner", "company")],
                            safe=False)
    body = _body(request)
    if body.get("sample") is True:
        d = sample_design()
    else:
        d = Design(info=ProjectInfo(name=_text(body, "name", 200) or "New FTTH project"),
                   materials=[m.model_copy() for m in DEFAULT_MATERIALS])
    d.info.prepared_by = d.info.prepared_by or request.user.get_full_name() or request.user.get_username()
    company = active_company(request.user)
    if company is not None and Membership.RANK[role_in(request.user, company)] < Membership.RANK["planner"]:
        company = None  # viewers create personal projects only
    if company is not None:
        d.info.company = d.info.company or company.name
        d.info.currency = company.currency or d.info.currency
        if company.design_standard in standards.STANDARDS and not body.get("sample"):
            standards.apply(d, company.design_standard)  # the company's design style and rules
        if company.sector in sectors.SECTORS and company.sector != sectors.FIBRE and not body.get("sample"):
            sectors.apply(d, company.sector)  # names, materials and rules of the company's sector
            if not _text(body, "name", 200):
                d.info.name = f"New {sectors.SECTORS[company.sector]['label'].lower()} project"
    p = Project(owner=request.user, company=company, data={})
    return JsonResponse(_save(request, p, d))


@api("GET", "PUT", "DELETE")
def project(request, pid):
    if request.method == "GET":
        return JsonResponse(_state(request, _project(request, pid, edit=False)))
    if request.method == "DELETE":
        p = _project(request, pid, edit=False)
        if not p.can_manage(request.user):
            raise ApiError(403, "Only the project owner or a company admin can delete it")
        photos = _photo_dir(p.id)
        p.delete()
        shutil.rmtree(photos, ignore_errors=True)
        return JsonResponse({"ok": True})

    try:
        d = Design.model_validate(_body(request))
    except ValidationError as e:
        errs = e.errors(include_url=False)
        first = errs[0] if errs else {}
        where = ".".join(str(x) for x in first.get("loc", []))
        raise ApiError(422, f"Not saved: {where} - {first.get('msg', 'invalid value')}"
                       + (f" (and {len(errs) - 1} more)" if len(errs) > 1 else ""),
                       errors=[{"loc": er.get("loc"), "msg": er.get("msg")} for er in errs[:20]])
    base = request.headers.get("X-Base-Hash")
    if not base:
        raise ApiError(428, "Missing X-Base-Hash header (the hash of the version you edited)")
    # checks on a plain read; the short write transaction in _commit re-checks the version
    p = _project(request, pid)
    if base != _version(p):
        who = p.updated_by.get_username() if p.updated_by else "another user"
        raise ApiError(409, f"{who} saved changes to this project after you opened it. "
                            f"Reload to get the latest version, then reapply your change.", conflict=True)
    old = p.design
    # survey approval: checked and recorded here; later survey edits return the survey to draft
    if d.info.survey_status == "approved":
        if old.info.survey_status != "approved":
            errs = [i for i in validate.validate(d) if i["severity"] == "error" and i["code"] in SURVEY_ERROR_CODES]
            if errs:
                raise ApiError(409, f"Cannot approve the survey: {len(errs)} survey error(s) - {errs[0]['message']}")
            d.info.survey_approved_by = request.user.get_username()
            d.info.survey_approved_at = timezone.now().isoformat(timespec="seconds")
            d.info.survey_fingerprint = _survey_fingerprint(d)
        elif old.info.survey_fingerprint.startswith("v2:") and _survey_fingerprint(d) != old.info.survey_fingerprint:
            d.info.survey_status = "draft"
            d.info.survey_approved_by = d.info.survey_approved_at = ""
        else:
            d.info.survey_approved_by = old.info.survey_approved_by
            d.info.survey_approved_at = old.info.survey_approved_at
            # approvals recorded before survey-only fingerprints: adopt the current survey data
            d.info.survey_fingerprint = old.info.survey_fingerprint if old.info.survey_fingerprint.startswith("v2:") \
                else _survey_fingerprint(d)
    if d.info.design_status == "approved":
        # approval covers exactly the approved revision; any later change returns the design to draft
        approved = p.revisions.filter(status="approved").first()
        # both sides read with the current data model: a stored hash from an older model would not compare
        if not approved or Design.model_validate(approved.data).content_hash() != d.content_hash():
            d.info.design_status = "draft"
    p = _commit(request, pid, base, d)
    return JsonResponse(_state(request, p, d))


@api("POST")
def share(request, pid):
    p = _project(request, pid, edit=False)
    if not p.can_manage(request.user):
        raise ApiError(403, "Only the project owner or a company admin can change sharing")
    body = _body(request)
    who = _text(body, "username", 150).strip()
    users = get_user_model().objects.filter(Q(username__iexact=who) | Q(email__iexact=who), is_active=True)
    user = users.first() if who else None
    if user is None:
        raise ApiError(404, "No active user with that username or email")
    access = "remove" if body.get("remove") else body.get("access", "edit")
    if access not in ("edit", "view", "remove"):
        raise ApiError(400, "access must be edit, view or remove")
    if user == p.owner:
        raise ApiError(400, "The owner always has full access")
    p.members.remove(user)
    p.viewers.remove(user)
    if access == "edit":
        p.members.add(user)
    elif access == "view":
        p.viewers.add(user)
    return JsonResponse(_state(request, p))


@api("GET")
def find_people(request):
    """People to share with: users in the same companies whose name, username or email matches, plus an exact
    username / email match for anyone else (other users are not listed)."""
    q = (request.GET.get("q") or "").strip()[:100]
    if len(q) < 2:
        return JsonResponse([], safe=False)
    User = get_user_model()
    mine = Membership.objects.filter(user=request.user).values("company")
    near = User.objects.filter(is_active=True, memberships__company__in=mine).filter(
        Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    exact = User.objects.filter(is_active=True).filter(Q(username__iexact=q) | Q(email__iexact=q))
    users = list({u.pk: u for u in list(exact) + list(near.distinct()[:8])}.values())[:8]
    return JsonResponse([{"username": u.get_username(), "name": u.get_full_name(), "email": u.email}
                         for u in users if u.pk != request.user.pk], safe=False)


# ---------------------------------------------------------------------------
# Design operations (run on the saved design)
# ---------------------------------------------------------------------------
def _operate(request, pid, fn):
    """Run fn on the saved design and save the result (fn runs outside the write lock)."""
    p = _project(request, pid)
    base, d = _version(p), p.design
    result = fn(d)
    p = _commit(request, pid, base, d)
    return _state(request, p, d), result


@api("POST")
def import_data(request, pid):
    f = request.FILES.get("file")
    if not f:
        raise ApiError(400, "Choose a file to import")
    target, status = request.POST.get("target", "auto"), request.POST.get("status", "existing")
    data = f.read()

    def run(d):
        try:
            return importers.import_file(d, f.name, data, target, status)
        except (ValueError, StopIteration) as e:
            raise ApiError(400, str(e) or "Could not read file")
        except Exception as e:  # malformed XML / workbook
            raise ApiError(400, f"Could not read {f.name}: {e}")

    st, report = _operate(request, pid, run)
    if f.name.lower().endswith(".kmz") and target == "auto":
        added = _import_kmz_photos(request, pid, data)
        if added:
            report["problems"].insert(1, f"{added} survey photo(s) from the KMZ added to the report")
            st = _state(request, _project(request, pid, edit=False))
    return JsonResponse(st | {"import": report})


def _store_image(pid: str, blob: bytes) -> str | None:
    """Save verified JPEG/PNG bytes under a generated name; None if the bytes are not an image."""
    from io import BytesIO
    try:
        from PIL import Image
        with Image.open(BytesIO(blob)) as im:
            im.verify()
            fmt = im.format
    except Exception:
        return None
    if fmt not in ("JPEG", "PNG"):
        return None
    name = f"{uuid.uuid4().hex[:10]}{'.png' if fmt == 'PNG' else '.jpg'}"
    (_photo_dir(pid) / name).write_bytes(blob)
    return name


def _import_kmz_photos(request, pid: str, data: bytes) -> int:
    photos = importers.extract_kmz_photos(data)
    if not photos:
        return 0
    stored = [(feature, _store_image(pid, blob)) for feature, _, blob in photos]
    stored = [(feature, name) for feature, name in stored if name]

    def add(d):
        ids = {x.id for coll in (d.poles, d.homes, d.nodes, d.cables) for x in coll}
        for feature, name in stored:
            d.photos.append(Photo(id=name.split(".")[0], file=name, caption=f"{feature} (photo from KMZ)"[:500],
                                  feature=feature if feature in ids else None))
    _operate(request, pid, add)
    return len(stored)


@api("POST")
def assign_homes(request, pid):
    try:
        max_drop = float(request.GET.get("max_drop_m", 250))
    except ValueError:
        raise ApiError(400, "max_drop_m must be a number of metres")
    if not math.isfinite(max_drop) or not 1 <= max_drop <= 5000:
        raise ApiError(400, "max_drop_m must be between 1 and 5000 metres")
    reassign = request.GET.get("reassign") == "true"
    st, res = _operate(request, pid, lambda d: calc.assign_homes(d, max_drop, only_unassigned=not reassign))
    return JsonResponse(st | {"result": res})


@api("POST")
def auto_design(request, pid):
    """Design the network from the survey data (replaces the current proposed design)."""
    from ftth import autodesign
    body = _body(request)
    preset = body.get("preset")
    if preset is not None and preset not in autodesign.PRESETS:
        raise ApiError(400, f"preset must be one of {', '.join(autodesign.PRESETS)}")
    overrides: dict = {}
    limits = {  # option -> (min, max); the Settings tab offers the same ranges
        "take_rate": (0.05, 1), "indoor_fat_ports": (4, 48), "outdoor_fat_ports": (4, 48), "small_premise_max_hp": (1, 24),
        "outdoor_cluster_radius_m": (10, 300), "max_span_m": (20, 150), "new_pole_spacing_m": (15, 100),
        "drop_to_pole_m": (5, 300), "branch_closure_gap_m": (0, 300), "merge_closures_m": (0, 300),
        "slack_interval_m": (0, 1000), "coverage_radius_m": (20, 1000), "coverage_take_rate": (0.005, 1)}
    choices = {"fat_split": (4, 8, 16, 32, 64), "pon_split": (2, 4, 8, 16, 32), "spur_cores": (6, 8, 12, 24, 48, 96)}
    for k, allowed in choices.items():
        if k in body:
            if _num_or_none(body[k]) not in allowed:
                raise ApiError(400, f"{k} must be one of {', '.join(map(str, allowed))}")
            overrides[k] = int(body[k])
    for k, (lo, hi) in limits.items():
        if k not in body:
            continue
        try:
            v = float(body[k])
        except (TypeError, ValueError):
            raise ApiError(400, f"{k} must be a number")
        if not lo <= v <= hi:
            raise ApiError(400, f"{k} must be between {lo:g} and {hi:g}")
        overrides[k] = int(v) if isinstance(getattr(autodesign.Options(), k), int) else v

    def run(d):
        style = preset or d.info.design_style  # the project remembers its company's design style
        d.info.design_style = style
        opt = autodesign.Options(**{**autodesign.PRESETS[style], **overrides})
        if d.info.design_status == "approved":
            raise ApiError(409, "The design is approved: return it to draft before auto-designing")
        try:
            return autodesign.auto_design(d, opt)
        except ValueError as e:
            raise ApiError(400, str(e))
    st, res = _operate(request, pid, run)
    return JsonResponse(st | {"result": res})


@api("POST")
def allocate(request, pid):
    st, res = _operate(request, pid, splicing.auto_allocate)
    return JsonResponse(st | {"result": res})


@api("GET")
def calculations(request, pid):
    d = _project(request, pid, edit=False).design
    lines = calc.bom(d)
    return JsonResponse({
        "cables": [asdict(c) | {"total_m": c.total_m} for c in calc.cable_lengths(d, proposed_only=True)],
        "poles": [asdict(p) | {"jb": p.jb, "enclosures": p.enclosures, "fats": p.fats} for p in calc.pole_summary(d)],
        "bom": [asdict(l) | {"qty": l.qty, "total": l.total} for l in lines],
        "boq_total": calc.boq_total(lines), "currency": d.info.currency,
    })


@api("GET")
def splicing_view(request, pid):
    d = _project(request, pid, edit=False).design
    node = request.GET.get("node")
    return JsonResponse({
        "cores": splicing.core_table(d),
        "nodes": [splicing.node_splicing(d, n.id) for n in d.nodes if node in (None, "", n.id)],
        "traces": {(s.node if sum(x.node == s.node and x.stage == 2 for x in d.splitters) == 1
                    else f"{s.node} ({s.id})"): splicing.trace_upstream(d, s.id)
                   for s in d.splitters if s.stage == 2},
        "colours": splicing.COLOURS,
    })


# ---------------------------------------------------------------------------
# QA, approval and revisions
# ---------------------------------------------------------------------------
@api("GET", "POST")
def revisions(request, pid):
    p = _project(request, pid, edit=request.method != "GET")
    if request.method == "GET":
        return JsonResponse([{"version": r.version, "created": r.created.isoformat(),
                              "author": r.author.get_username() if r.author else "", "note": r.note,
                              "status": r.status, "hash": r.data_hash}
                             for r in p.revisions.select_related("author")], safe=False)
    body = _body(request)
    p, d, rev = record_revision(request, pid, body.get("design_status") or None, _text(body, "note", 500))
    return JsonResponse(_state(request, p, d) | {"version": rev.version})


def record_revision(request, pid: str, status: str | None, note: str):
    """Save a revision, optionally changing the design status (approval is checked here). Used by the app and
    by the Review page."""
    if status not in (None, "draft", "in_review", "approved"):
        raise ApiError(400, "Unknown status")
    p = _project(request, pid)
    base, d = _version(p), p.design
    # approval checks (validation, BOQ) run before taking the write lock
    if status == "approved":
        if not p.can_approve(request.user):
            raise ApiError(403, "You do not have permission to approve designs")
        errs = [i for i in validate.validate(d) if i["severity"] == "error"]
        if errs:
            raise ApiError(409, f"Cannot approve: {len(errs)} validation error(s) must be fixed first "
                                f"(first: {errs[0]['message']})")
        unpriced = [l.code for l in calc.bom(d) if l.rate is None]
        if unpriced:
            raise ApiError(409, f"Cannot approve: {len(unpriced)} BOQ item(s) have no rate in the material catalogue "
                                f"({', '.join(unpriced)}), so the BOQ total would be short. Add the rate(s) or "
                                f"remove the item(s) first.")
    if status:
        d.info.design_status = status
    elif d.info.design_status == "approved" and not p.can_approve(request.user):
        d.info.design_status = "in_review"  # only approvers can record an approved revision
    with transaction.atomic():
        p = _project(request, pid, lock=True)
        if _version(p) != base:
            raise ApiError(409, "The project changed while the revision was being checked. Reload and try again.",
                           conflict=True)
        p.set_design(d, request.user)
        p.save()
        for _ in range(3):  # retry if two users save a revision at the same moment
            try:
                with transaction.atomic():
                    rev = Revision.objects.create(
                        project=p, version=p.current_version + 1, author=request.user,
                        note=note, status=d.info.design_status,
                        data_hash=d.content_hash(), data=p.data)
                break
            except IntegrityError:
                continue
        else:
            raise ApiError(409, "Could not save the revision, please retry")
    return p, d, rev


@api("POST")
def restore_revision(request, pid, version):
    with transaction.atomic():
        p = _project(request, pid, lock=True)
        rev = p.revisions.filter(version=version).first()
        if not rev:
            raise ApiError(404, "Revision not found")
        d = Design.model_validate(rev.data)
        d.info.design_status = "draft"  # a restore is a change: it needs reviewing and approving again
        p.set_design(d, request.user)
        p.save()
        Revision.objects.create(project=p, version=p.current_version + 1, author=request.user,
                                note=f"Restored revision {version}", status="draft",
                                data_hash=d.content_hash(), data=p.data)
        return JsonResponse(_state(request, p, d))


# ---------------------------------------------------------------------------
# Photos (private: served only to users who can see the project)
# ---------------------------------------------------------------------------
PHOTO_NAME = re.compile(r"[0-9a-f]{10}\.(jpg|jpeg|png)")


@api("POST")
def upload_photo(request, pid):
    f = request.FILES.get("file")
    ext = Path(f.name if f else "").suffix.lower()
    if not f or ext not in (".jpg", ".jpeg", ".png"):
        raise ApiError(400, "Photos must be JPG or PNG")
    try:  # must really be a JPEG/PNG image, whatever the file name says
        from PIL import Image
        with Image.open(f) as im:
            im.verify()
            if im.format not in ("JPEG", "PNG"):
                raise ValueError(im.format)
        f.seek(0)
    except Exception:
        raise ApiError(400, "The file is not a valid JPG or PNG image")
    name = f"{uuid.uuid4().hex[:10]}{'.png' if ext == '.png' else '.jpg'}"
    p = _project(request, pid)
    path = _photo_dir(p.id) / name
    with open(path, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    caption, feature = request.POST.get("caption", "")[:500], request.POST.get("feature", "")[:100]
    try:
        st, _ = _operate(request, pid, lambda d: d.photos.append(
            Photo(id=name.split(".")[0], file=name, caption=caption, feature=feature or None)))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return JsonResponse(st)


def _vision_config():
    from ftth import vision
    return vision.Config(**getattr(settings, "PHOTO_AI", {}))


def _chat_config():
    from ftth import assistant
    return assistant.Config(**getattr(settings, "AI_CHAT", {}))


AI_CHAT_PER_10_MIN = 30


@api("GET")
def ai_chat_status(request):
    """Whether the AI assistant is set up (never returns the key) and whether Photo AI feeds it."""
    cfg = _chat_config()
    return JsonResponse({"enabled": cfg.enabled, "photo_ai": _vision_config().enabled})


@api("POST")
def ai_chat(request, pid):
    """One assistant answer about the project: the conversation so far plus a summary of the project go to Groq."""
    from django.core.cache import cache
    from ftth import assistant
    p = _project(request, pid, edit=False)  # viewers may ask too: the assistant never changes the design
    key = f"ai-chat:{request.user.pk}"
    if cache.get(key, 0) >= AI_CHAT_PER_10_MIN:
        raise ApiError(429, "Too many questions in a short time: please wait a few minutes")
    cache.set(key, cache.get(key, 0) + 1, 600)
    upload = None
    if request.content_type.startswith("multipart/"):
        try:
            messages = json.loads(request.POST.get("messages") or "[]")
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid messages")
        upload = request.FILES.get("file")
    else:
        messages = _body(request).get("messages")
    try:
        attached = assistant.attachment_text(upload.name, upload.read(), _vision_config()) if upload else None
        answer = assistant.chat(p.design, messages, _chat_config(), attached)
    except assistant.AssistantError as e:
        msg = str(e)
        raise ApiError(502 if msg.startswith(("Could not reach", "The AI service")) or " from the " in msg else 400, msg)
    return JsonResponse({"answer": answer, "attachment": attached or ""})


@api("GET")
def photo_ai(request):
    """Whether Photo AI is set up on this server (never returns the key)."""
    cfg = _vision_config()
    return JsonResponse({"enabled": cfg.enabled, "provider": cfg.label if cfg.enabled else ""})


@api("POST")
def analyse_photo(request, pid, name):
    """Send one survey photo to the vision model and store its suggestions on the photo."""
    from ftth import vision
    if not PHOTO_NAME.fullmatch(name):
        raise ApiError(404, "Unknown photo")
    p = _project(request, pid)
    if not any(ph.file == name for ph in p.design.photos):
        raise ApiError(404, "Unknown photo")
    path = _photo_dir(p.id) / name
    if not path.exists():
        raise ApiError(404, "Photo file missing")
    try:
        result = vision.analyse(path.read_bytes(), _vision_config())
    except vision.VisionError as e:
        raise ApiError(400 if "not set up" in str(e) else 502, str(e))
    result["at"] = timezone.now().isoformat(timespec="seconds")

    def run(d):
        for ph in d.photos:
            if ph.file == name:
                ph.analysis = result
        return result
    st, res = _operate(request, pid, run)
    return JsonResponse(st | {"analysis": res})


def get_photo(request, pid, name):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Please sign in"}, status=401)
    if not PHOTO_NAME.fullmatch(name) or not Project.objects.visible_to(request.user).filter(pk=pid).exists():
        raise Http404
    path = _photo_dir(pid) / name
    if not path.exists():
        raise Http404
    return FileResponse(open(path, "rb"))


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
def _download(content: bytes, fname: str, fmt: str) -> HttpResponse:
    r = HttpResponse(content, content_type=package.MIME.get(fmt, "application/octet-stream"))
    ascii_name = fname.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    r["Content-Disposition"] = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"
    return r


def _record(request, p: Project, hashes: dict[str, str], version: int):
    for k, h in hashes.items():
        ExportRecord.objects.update_or_create(project=p, deliverable=k,
                                              defaults={"data_hash": h, "version": version, "by": request.user})


@api("GET")
def export(request, pid, deliverable, fmt):
    p = _project(request, pid, edit=False)
    if fmt not in package.DELIVERABLES.get(deliverable, {}):
        raise ApiError(404, "Unknown deliverable or format")
    d, rev = p.design, p.current_version
    content = package.build(d, deliverable, fmt, stamp(d, rev, _doc_brand(request, p)), _photo_dir(p.id))
    _record(request, p, {deliverable: package.deliverable_hash(d, deliverable)}, rev)
    return _download(content, package.filename(d, deliverable, fmt, rev), fmt)


@api("GET")
def export_package(request, pid):
    p = _project(request, pid, edit=False)
    d, rev = p.design, p.current_version
    errs = [i for i in validate.validate(d) if i["severity"] == "error"]
    if errs and request.GET.get("force") != "true":
        raise ApiError(409, f"{len(errs)} validation error(s). Fix them or download anyway.")
    content = package.build_package(d, stamp(d, rev, _doc_brand(request, p)), _photo_dir(p.id))
    _record(request, p, {k: package.deliverable_hash(d, k) for k in package.DELIVERABLES}, rev)
    return _download(content, package.filename(d, "package", "zip", rev), "zip")


# ---------------------------------------------------------------------------
# Review comments
# ---------------------------------------------------------------------------
@api("GET", "POST")
def comments(request, pid):
    """Anyone who can see a project can read and add review comments."""
    p = _project(request, pid, edit=False)
    if request.method == "POST":
        body = _body(request)
        text = _text(body, "text", 2000).strip()
        if not text:
            raise ApiError(400, "Write a comment first")
        Comment.objects.create(project=p, author=request.user, text=text, ref=_text(body, "ref", 100).strip(),
                               revision=p.current_version or None)
    return JsonResponse([c.as_dict() for c in p.comments.select_related("author", "resolved_by")], safe=False)


@api("POST")
def resolve_comment(request, pid, cid):
    p = _project(request, pid, edit=False)
    c = p.comments.filter(pk=cid).first()
    if c is None:
        raise ApiError(404, "Comment not found")
    if not (p.can_edit(request.user) or c.author_id == request.user.id):
        raise ApiError(403, "Only the author or someone who can edit the project can resolve a comment")
    reopen = bool(_body(request).get("reopen"))
    c.resolved, c.resolved_by = (False, None) if reopen else (True, request.user)
    c.resolved_at = None if reopen else timezone.now()
    c.save()
    return JsonResponse([x.as_dict() for x in p.comments.select_related("author", "resolved_by")], safe=False)


def company_logo(request, cid):
    """A company's logo (signed-in users only; logos are not secret but media is not public)."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Please sign in"}, status=401)
    c = Company.objects.filter(pk=cid).first()
    if c is None or not c.logo:
        raise Http404
    try:
        return FileResponse(c.logo.open("rb"))
    except FileNotFoundError:
        raise Http404
