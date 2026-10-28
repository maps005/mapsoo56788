"""Admin notifications: open 'forgot password' requests."""
from django import template

from planner.models import PasswordResetRequest

register = template.Library()


@register.simple_tag(takes_context=True)
def open_reset_requests(context) -> list:
    request = context.get("request")
    user = getattr(request, "user", None)
    if not user or not user.is_staff or not user.has_perm("planner.view_passwordresetrequest"):
        return []
    return list(PasswordResetRequest.objects.filter(resolved=False).select_related("user")[:6])


@register.simple_tag(takes_context=True)
def admin_dashboard(context) -> dict:
    """Figures for the admin home page (only what the signed-in staff member may see)."""
    from datetime import date

    from django.contrib.auth import get_user_model

    from planner.models import Company, Project
    request = context.get("request")
    user = getattr(request, "user", None)
    out = {"projects": None}
    if not user or not user.is_staff:
        return out
    if user.has_perm("planner.view_project"):
        rows = list(Project.objects.select_related("company", "assigned_to").order_by("-updated")
                    .only("id", "name", "data", "updated", "due_date", "company__name", "assigned_to__username"))
        status = [(p, (p.data or {}).get("info", {}).get("design_status", "draft")) for p in rows]
        today = date.today()
        out.update(projects=len(rows), draft=sum(s == "draft" for _, s in status),
                   in_review=sum(s == "in_review" for _, s in status), approved=sum(s == "approved" for _, s in status),
                   late=sum(1 for p, s in status if p.due_date and p.due_date < today and s != "approved"),
                   recent=[{"project": p, "status": s, "late": bool(p.due_date and p.due_date < today and s != "approved")}
                           for p, s in status[:8]])
    if user.has_perm("planner.view_company"):
        out["companies"] = Company.objects.count()
    if user.has_perm("auth.view_user"):
        out["users"] = get_user_model().objects.filter(is_active=True).count()
    return out
