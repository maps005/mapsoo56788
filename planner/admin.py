from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Comment, Company, ExportRecord, Membership, PasswordResetRequest, Profile, Project, Revision


class RevisionInline(admin.TabularInline):
    model = Revision
    fields = ("version", "created", "author", "status", "note", "data_hash")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = False


class CommentInline(admin.TabularInline):
    model = Comment
    fields = ("created", "author", "ref", "text", "resolved")
    readonly_fields = ("created", "author")
    extra = 0


class AssignForm(forms.Form):
    """Bulk 'Assign projects': fields left empty keep each project's current value."""
    assigned_to = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(is_active=True).order_by("username"), required=False,
        label="Assign to", help_text="The planner responsible; they can view and edit the projects")
    unassign = forms.BooleanField(required=False, label="Remove the current assignee instead")
    company = forms.ModelChoiceField(queryset=Company.objects.all(), required=False, label="Move to company")
    start_date = forms.DateField(required=False, label="Planned start", widget=forms.DateInput(attrs={"type": "date"}))
    due_date = forms.DateField(required=False, label="Due date", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        c = super().clean()
        if c.get("assigned_to") and c.get("unassign"):
            raise forms.ValidationError("Choose a person or tick 'remove the current assignee', not both")
        if c.get("start_date") and c.get("due_date") and c["due_date"] < c["start_date"]:
            raise forms.ValidationError("The due date is before the planned start")
        if not any(c.get(k) for k in ("assigned_to", "unassign", "company", "start_date", "due_date")):
            raise forms.ValidationError("Choose at least one thing to change")
        return c


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    change_list_template = "admin/planner/project/change_list.html"
    list_display = ("name", "company", "assigned_to", "owner", "status", "start_date", "due_date", "updated")
    list_editable = ("assigned_to",)
    autocomplete_fields = ("assigned_to",)
    actions = ["assign_projects"]
    fieldsets = (
        (None, {"fields": ("id", "name", "company", "owner", "members", "viewers", "status")}),
        ("Assignment and schedule", {"fields": ("assigned_to", "start_date", "due_date")}),
        ("History", {"fields": ("created", "updated", "updated_by", "data_hash")}),
    )
    search_fields = ("name", "owner__username", "company__name")
    filter_horizontal = ("members", "viewers")
    readonly_fields = ("id", "data_hash", "created", "updated", "updated_by", "status")
    exclude = ("data",)
    inlines = [CommentInline, RevisionInline]

    @admin.display(description="Design status")
    def status(self, obj):
        return (obj.data or {}).get("info", {}).get("design_status", "")

    @admin.action(description="Assign selected projects…", permissions=["change"])
    def assign_projects(self, request, queryset):
        form = AssignForm(request.POST if "apply" in request.POST else None)
        if "apply" in request.POST and form.is_valid():
            c = form.cleaned_data
            changes = {k: c[k] for k in ("company", "start_date", "due_date") if c.get(k)}
            if c.get("assigned_to"):
                changes["assigned_to"] = c["assigned_to"]
            elif c.get("unassign"):
                changes["assigned_to"] = None
            n = queryset.update(**changes)
            who = c["assigned_to"].get_username() if c.get("assigned_to") else ("nobody" if c.get("unassign") else "")
            self.message_user(request, f"{n} project(s) updated" + (f": assigned to {who}" if who else ""))
            return None
        ctx = {**self.admin_site.each_context(request), "title": "Assign projects", "opts": self.model._meta,
               "projects": queryset, "form": form, "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME}
        return TemplateResponse(request, "admin/planner/project/assign.html", ctx)

    def get_urls(self):
        return [path("gantt/", self.admin_site.admin_view(self.gantt_view), name="planner_project_gantt")] +             super().get_urls()

    def gantt_view(self, request):
        """Gantt chart of the projects: planned dates against the survey / design / review phases."""
        from django.core.exceptions import PermissionDenied

        from . import gantt
        if not self.has_view_permission(request):
            raise PermissionDenied
        qs = self.get_queryset(request).select_related("company", "assigned_to").prefetch_related("revisions")
        companies = Company.objects.filter(projects__isnull=False).distinct()
        people = get_user_model().objects.filter(assigned_projects__isnull=False).distinct().order_by("username")
        cid, show, who = request.GET.get("company", ""), request.GET.get("show", "open"), request.GET.get("assigned", "")
        if cid.isdigit():
            qs = qs.filter(company_id=int(cid))
        if who == "none":
            qs = qs.filter(assigned_to__isnull=True)
        elif who.isdigit():
            qs = qs.filter(assigned_to_id=int(who))
        projects = list(qs.order_by("due_date", "start_date", "created")[:200])
        if show == "open":
            projects = [p for p in projects if (p.data or {}).get("info", {}).get("design_status") != "approved"]
        chart = gantt.build(projects)
        ctx = {**self.admin_site.each_context(request), "title": "Project Gantt chart", "opts": self.model._meta,
               "chart": chart, "companies": companies, "company": cid, "show": show, "people": people, "assigned": who,
               "late": sum(r.late for r in chart["rows"])}
        return TemplateResponse(request, "admin/planner/project/gantt.html", ctx)


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 1
    autocomplete_fields = ("user",)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("logo_thumb", "name", "sector", "phone", "email", "members", "projects_count")
    list_filter = ("sector",)
    list_display_links = ("logo_thumb", "name")
    search_fields = ("name", "legal_name")
    inlines = [MembershipInline]

    @admin.display(description="")
    def logo_thumb(self, obj):
        return format_html('<img src="/company/{}/logo" style="height:28px;max-width:80px;object-fit:contain">', obj.id) \
            if obj.logo else ""

    @admin.display(description="Members")
    def members(self, obj):
        return obj.memberships.count()

    @admin.display(description="Projects")
    def projects_count(self, obj):
        return obj.projects.count()


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "company", "role", "added")
    list_filter = ("company", "role")
    search_fields = ("user__username", "company__name")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "job_title", "phone", "active_company")


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("project", "author", "ref", "short", "resolved", "created")
    list_filter = ("resolved", "project__company")
    search_fields = ("text", "ref", "project__name")

    @admin.display(description="Comment")
    def short(self, obj):
        return obj.text[:80]


@admin.register(ExportRecord)
class ExportRecordAdmin(admin.ModelAdmin):
    list_display = ("project", "deliverable", "version", "data_hash", "created", "by")
    list_filter = ("deliverable",)


@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(admin.ModelAdmin):
    list_display = ("created", "user", "email", "note", "ip", "resolved", "set_password")
    list_filter = ("resolved",)
    search_fields = ("user__username", "user__email", "note")
    readonly_fields = ("user", "note", "ip", "created", "resolved_by", "resolved_at")
    fields = readonly_fields + ("resolved",)
    actions = ["mark_resolved"]

    def has_add_permission(self, request):
        return False  # requests come from the sign-in page

    @admin.display(description="Email")
    def email(self, obj):
        return obj.user.email

    @admin.display(description="")
    def set_password(self, obj):
        url = reverse("admin:auth_user_password_change", args=[obj.user_id])
        return format_html('<a class="button" href="{}">Set new password</a>', url)

    @admin.action(description="Mark selected requests as resolved")
    def mark_resolved(self, request, queryset):
        n = queryset.filter(resolved=False).update(resolved=True, resolved_by=request.user, resolved_at=timezone.now())
        self.message_user(request, f"{n} request(s) marked as resolved")

    def save_model(self, request, obj, form, change):
        if "resolved" in form.changed_data:
            obj.resolved_by, obj.resolved_at = (request.user, timezone.now()) if obj.resolved else (None, None)
        super().save_model(request, obj, form, change)
