"""Server-rendered pages around the planner: projects, review and approval, company setup and profile.

They use the same access rules as the JSON API (planner.models: Project.can_edit / can_approve / can_manage,
company roles in Membership).
"""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from ftth import calc, sectors, validate

from .models import Comment, Company, Membership, Profile, Project
from .views import ApiError, active_company, record_revision

STATUS_LABEL = {"draft": "Draft", "in_review": "In review", "approved": "Approved"}


def _nav(request, active: str) -> dict:
    u = request.user
    review_n = sum(1 for p in Project.objects.visible_to(u).only("id", "data", "company", "owner")
                   if (p.data or {}).get("info", {}).get("design_status") == "in_review" and p.can_approve(u))
    return {"nav": active, "company": active_company(u), "review_count": review_n}


def _status(p: Project) -> tuple[str, str]:
    info = (p.data or {}).get("info", {})
    return info.get("design_status", "draft"), info.get("survey_status", "draft")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@login_required
def projects_page(request):
    u = request.user
    admin_of = list(Company.objects.filter(memberships__user=u, memberships__role__in=["admin", "owner"]))
    if request.method == "POST":
        p = get_object_or_404(Project.objects.visible_to(u), pk=request.POST.get("project"))
        if not p.can_manage(u):
            messages.error(request, "Only the project owner or a company admin can move a project.")
        else:
            cid = request.POST.get("company") or ""
            target = next((c for c in admin_of if str(c.id) == cid), None) if cid else None
            if cid and target is None and not u.is_superuser:
                messages.error(request, "You can only move projects into a company you administer.")
            else:
                p.company = target or (Company.objects.filter(pk=cid).first() if cid else None)
                p.save(update_fields=["company"])
                messages.success(request, f"{p.name} moved to {p.company or 'personal projects'}.")
        return redirect(request.get_full_path())
    qs = Project.objects.visible_to(u).select_related("owner", "company").annotate(
        open_comments=Count("comments", filter=Q(comments__resolved=False)))
    q, comp, status = request.GET.get("q", "").strip(), request.GET.get("company", ""), request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(owner__username__icontains=q))
    if comp == "personal":
        qs = qs.filter(company__isnull=True)
    elif comp:
        qs = qs.filter(company_id=comp)
    rows = []
    for p in qs:
        ds, ss = _status(p)
        if status and ds != status:
            continue
        rows.append({"p": p, "design": ds, "design_label": STATUS_LABEL.get(ds, ds), "survey": ss,
                     "can_manage": p.can_manage(u), "revision": p.current_version})
    companies = Company.objects.filter(memberships__user=u).distinct() if not u.is_superuser else Company.objects.all()
    return render(request, "planner/projects.html", _nav(request, "projects") | {
        "rows": rows, "companies": companies, "admin_of": admin_of if not u.is_superuser else list(Company.objects.all()),
        "q": q, "f_company": comp, "f_status": status})


# ---------------------------------------------------------------------------
# Review and approval
# ---------------------------------------------------------------------------
@login_required
def review_page(request):
    u = request.user
    if request.method == "POST":
        p = get_object_or_404(Project.objects.visible_to(u), pk=request.POST.get("project"))
        action, text = request.POST.get("action"), (request.POST.get("text") or "").strip()[:2000]
        try:
            if action == "comment":
                if not text:
                    raise ApiError(400, "Write a comment first")
                Comment.objects.create(project=p, author=u, text=text, ref=(request.POST.get("ref") or "")[:100],
                                       revision=p.current_version or None)
                messages.success(request, "Comment added.")
            elif action in ("approve", "return"):
                if not p.can_approve(u):
                    raise ApiError(403, "You do not have permission to approve this project")
                if text:
                    Comment.objects.create(project=p, author=u, text=text, revision=p.current_version or None)
                note = text or ("Approved" if action == "approve" else "Returned to the planner for corrections")
                _, _, rev = record_revision(request, p.pk, "approved" if action == "approve" else "draft", note[:500])
                messages.success(request, f"{p.name}: revision {rev.version} "
                                          f"{'approved' if action == 'approve' else 'returned to draft'}.")
            elif action in ("resolve", "reopen"):
                c = get_object_or_404(Comment, pk=request.POST.get("comment"), project=p)
                if not (p.can_edit(u) or c.author_id == u.id):
                    raise ApiError(403, "Only the author or someone who can edit the project can resolve a comment")
                c.resolved = action == "resolve"
                c.resolved_by = u if c.resolved else None
                from django.utils import timezone
                c.resolved_at = timezone.now() if c.resolved else None
                c.save()
        except ApiError as e:
            messages.error(request, e.detail)
        return redirect(f"{request.path}?{request.GET.urlencode()}" if request.GET else request.path)

    show = request.GET.get("show", "queue")
    cards = []
    for p in Project.objects.visible_to(u).select_related("owner", "company").order_by("-updated"):
        ds, ss = _status(p)
        open_n = p.comments.filter(resolved=False).count()
        if show == "queue" and not (ds == "in_review" and p.can_approve(u)):
            continue
        if show == "comments" and not open_n:
            continue
        if show == "approved" and ds != "approved":
            continue
        d = p.design
        s, counts = calc.summary(d), validate.counts(validate.validate(d))
        last = p.revisions.select_related("author").first()
        cards.append({"p": p, "design": ds, "design_label": STATUS_LABEL.get(ds, ds), "survey": ss, "s": s,
                      "sec": sectors.get(d.info.sector),  # the figures in the project's sector words
                      "counts": counts, "last": last, "can_approve": p.can_approve(u), "can_edit": p.can_edit(u),
                      "comments": list(p.comments.select_related("author", "resolved_by")[:30]), "open": open_n,
                      "unpriced": [l.code for l in calc.bom(d) if l.rate is None]})
        if len(cards) >= 30:
            break
    return render(request, "planner/review.html", _nav(request, "review") | {"cards": cards, "show": show})


# ---------------------------------------------------------------------------
# Company setup
# ---------------------------------------------------------------------------
class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["name", "legal_name", "logo", "registration_no", "tax_pin", "address", "phone", "email", "website",
                  "currency", "sector", "design_standard"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sector"].required = False  # left out: fibre, as before sectors existed

    def clean_sector(self):
        return self.cleaned_data.get("sector") or "fibre"

    def clean_logo(self):
        f = self.cleaned_data.get("logo")
        if f and getattr(f, "size", 0) > 2 * 1024 * 1024:
            raise forms.ValidationError("The logo must be smaller than 2 MB")
        return f


@login_required
def company_page(request):
    u = request.user
    mine = Membership.objects.filter(user=u).select_related("company")
    sel = request.GET.get("c") or request.POST.get("c")
    m = next((x for x in mine if str(x.company_id) == str(sel)), None) or \
        next((x for x in mine if active_company(u) and x.company_id == active_company(u).id), None) or \
        (mine[0] if mine else None)
    company = m.company if m else None
    can_admin = bool(m and m.at_least("admin")) or u.is_superuser and company is not None
    action = request.POST.get("action")

    if request.method == "POST":
        if action == "create":
            form = CompanyForm(request.POST, request.FILES)
            if form.is_valid():
                with transaction.atomic():
                    c = form.save()
                    Membership.objects.create(user=u, company=c, role="owner")
                    prof, _ = Profile.objects.get_or_create(user=u)
                    prof.active_company = c
                    prof.save()
                messages.success(request, f"Company {c.name} created. You are its owner.")
                return redirect(f"{request.path}?c={c.id}")
            return render(request, "planner/company.html", _nav(request, "company") | {
                "memberships": mine, "form": form, "creating": True})
        if company is None or not can_admin:
            messages.error(request, "Only a company admin or owner can change the company.")
            return redirect(request.path)
        if action == "details":
            form = CompanyForm(request.POST, request.FILES, instance=company)
            if form.is_valid():
                form.save()
                messages.success(request, "Company details saved.")
            else:
                return render(request, "planner/company.html", _ctx_company(request, mine, company, m, form))
        elif action == "add_member":
            who = (request.POST.get("user") or "").strip()
            role = request.POST.get("role") if request.POST.get("role") in Membership.RANK else "planner"
            User = get_user_model()
            target = User.objects.filter(Q(username__iexact=who) | Q(email__iexact=who)).first() if who else None
            if target is None:
                messages.error(request, f'No user "{who}". Ask the system administrator to create the account first.')
            elif role == "owner" and not m.at_least("owner") and not u.is_superuser:
                messages.error(request, "Only an owner can add another owner.")
            else:
                Membership.objects.update_or_create(user=target, company=company, defaults={"role": role})
                messages.success(request, f"{target.get_username()} is now {role} of {company.name}.")
        elif action in ("role", "remove"):
            mem = get_object_or_404(Membership, pk=request.POST.get("membership"), company=company)
            owners = company.memberships.filter(role="owner").count()
            new = request.POST.get("role")
            if mem.role == "owner" and owners <= 1 and (action == "remove" or new != "owner"):
                messages.error(request, "A company needs at least one owner.")
            elif (mem.role == "owner" or new == "owner") and not m.at_least("owner") and not u.is_superuser:
                messages.error(request, "Only an owner can change owners.")
            elif action == "remove":
                mem.delete()
                messages.success(request, f"{mem.user.get_username()} removed from {company.name}.")
            elif new in Membership.RANK:
                mem.role = new
                mem.save()
                messages.success(request, f"{mem.user.get_username()} is now {new}.")
        elif action == "adopt":
            n = Project.objects.filter(owner=u, company__isnull=True).update(company=company)
            messages.success(request, f"{n} of your personal project(s) added to {company.name}.")
        return redirect(f"{request.path}?c={company.id}")

    if company is None or request.GET.get("new"):
        return render(request, "planner/company.html", _nav(request, "company") | {
            "memberships": mine, "form": CompanyForm(), "creating": True})
    return render(request, "planner/company.html",
                  _ctx_company(request, mine, company, m, CompanyForm(instance=company) if can_admin else None))


def _ctx_company(request, mine, company, m, form) -> dict:
    projects = company.projects.select_related("owner").order_by("-updated")
    stats = {"total": projects.count(), "draft": 0, "in_review": 0, "approved": 0}
    for p in projects:
        stats[_status(p)[0]] = stats.get(_status(p)[0], 0) + 1
    return _nav(request, "company") | {
        "memberships": mine, "c": company, "me": m, "form": form,
        "can_admin": bool(m and m.at_least("admin")) or request.user.is_superuser,
        "members": company.memberships.select_related("user"), "roles": Membership.ROLES,
        "projects": [{"p": p, "design_label": STATUS_LABEL.get(_status(p)[0], "")} for p in projects[:50]],
        "stats": stats,
        "personal": Project.objects.filter(owner=request.user, company__isnull=True).count()}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
class ProfileForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    job_title = forms.CharField(max_length=100, required=False)
    phone = forms.CharField(max_length=60, required=False)
    active_company = forms.ModelChoiceField(queryset=Company.objects.none(), required=False,
                                            help_text="New projects are created in this company")

    def __init__(self, user, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["active_company"].queryset = Company.objects.filter(memberships__user=user)


@login_required
def profile_page(request):
    u = request.user
    prof, _ = Profile.objects.get_or_create(user=u)
    form = ProfileForm(u, initial={"first_name": u.first_name, "last_name": u.last_name, "email": u.email,
                                   "job_title": prof.job_title, "phone": prof.phone, "active_company": prof.active_company})
    pw = PasswordChangeForm(u)
    if request.method == "POST":
        if request.POST.get("action") == "password":
            pw = PasswordChangeForm(u, request.POST)
            if pw.is_valid():
                pw.save()
                update_session_auth_hash(request, pw.user)
                messages.success(request, "Password changed.")
                return redirect(request.path)
        else:
            form = ProfileForm(u, request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                u.first_name, u.last_name, u.email = cd["first_name"], cd["last_name"], cd["email"]
                u.save(update_fields=["first_name", "last_name", "email"])
                prof.job_title, prof.phone, prof.active_company = cd["job_title"], cd["phone"], cd["active_company"]
                prof.save()
                messages.success(request, "Profile saved.")
                return redirect(request.path)
    return render(request, "planner/profile.html", _nav(request, "profile") | {
        "form": form, "pw": pw, "prof": prof,
        "memberships": Membership.objects.filter(user=u).select_related("company"),
        "owned": Project.objects.filter(owner=u).count()})
