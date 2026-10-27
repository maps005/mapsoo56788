"""Persistence for the FTTH design document.

The design itself stays one JSON document (`ftth.model.Design`), so every
deliverable is generated from the same data; Django adds users, sharing,
revisions and export tracking around it.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from ftth.model import Design
from ftth.standards import CHOICES as STANDARD_CHOICES


def short_id() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Companies: the system can serve several companies, each with its own members and projects
# ---------------------------------------------------------------------------
class Company(models.Model):
    name = models.CharField(max_length=120, unique=True)
    logo = models.ImageField(upload_to="company_logos/", blank=True,
                             help_text="PNG or JPG; shown in the app header and on the company pages")
    legal_name = models.CharField(max_length=200, blank=True)
    registration_no = models.CharField("registration no.", max_length=60, blank=True)
    tax_pin = models.CharField("tax / KRA PIN", max_length=60, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    currency = models.CharField(max_length=8, default="KES")
    design_standard = models.CharField(
        max_length=40, default="system", blank=True, choices=STANDARD_CHOICES,
        help_text="Design style and construction rules every new project of the company starts with")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name


class Membership(models.Model):
    """A user's role in a company. Roles, from least to most:
    viewer (see and comment), planner (create and edit), approver (also approve designs),
    admin (also manage members, details and projects), owner (same as admin; the company's creator)."""
    ROLES = [("viewer", "Viewer"), ("planner", "Planner"), ("approver", "Approver"), ("admin", "Admin"), ("owner", "Owner")]
    RANK = {r: i for i, (r, _) in enumerate(ROLES)}
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=ROLES, default="planner")
    added = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["company", "user__username"]
        constraints = [models.UniqueConstraint(fields=["user", "company"], name="unique_membership")]

    def __str__(self):
        return f"{self.user} - {self.company} ({self.role})"

    def at_least(self, role: str) -> bool:
        return self.RANK[self.role] >= self.RANK[role]


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    active_company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                       help_text="New projects are created in this company")

    def __str__(self):
        return f"Profile of {self.user}"


def role_in(user, company) -> str | None:
    """The user's role in a company (None if not a member)."""
    if company is None or not getattr(user, "is_authenticated", False):
        return None
    m = Membership.objects.filter(user=user, company=company).only("role").first()
    return m.role if m else None


def _at_least(role: str | None, need: str) -> bool:
    return role is not None and Membership.RANK[role] >= Membership.RANK[need]


class ProjectQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user.is_superuser:
            return self
        return self.filter(Q(owner=user) | Q(members=user) | Q(viewers=user) | Q(assigned_to=user) |
                           Q(company__memberships__user=user)).distinct()

    def editable_by(self, user):
        if user.is_superuser:
            return self
        return self.filter(Q(owner=user) | Q(members=user) | Q(assigned_to=user) |
                           Q(company__memberships__user=user,
                             company__memberships__role__in=["planner", "approver", "admin", "owner"])).distinct()


class Project(models.Model):
    id = models.CharField(primary_key=True, max_length=16, default=short_id, editable=False)
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_projects")
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="shared_projects",
                                     help_text="Users who can view and edit this project")
    viewers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="viewable_projects",
                                     help_text="Users who can view and comment on this project, but not edit it")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects",
                                help_text="Company members see the project; planners and approvers can edit it")
    data = models.JSONField(help_text="The complete design document (ftth.model.Design)")
    data_hash = models.CharField(max_length=16, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="assigned_projects", verbose_name="assigned to",
                                    help_text="The planner responsible for the project; they can view and edit it")
    start_date = models.DateField("planned start", null=True, blank=True, help_text="Shown on the Gantt chart")
    due_date = models.DateField("due date", null=True, blank=True,
                                help_text="Design approval due; the Gantt chart flags projects that run late")

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ["-updated"]
        permissions = [("approve_design", "Can approve an FTTH design for issue")]

    def __str__(self):
        return self.name

    @property
    def design(self) -> Design:
        return Design.model_validate(self.data)

    def set_design(self, d: Design, user=None) -> None:
        self.data = d.model_dump(mode="json")
        self.name = d.info.name[:200]
        self.data_hash = d.content_hash()
        if user is not None and user.is_authenticated:
            self.updated_by = user

    @property
    def current_version(self) -> int:
        return self.revisions.aggregate(v=models.Max("version"))["v"] or 0

    # ---- access ----------------------------------------------------------
    def can_edit(self, user) -> bool:
        if user.is_superuser or user.id in (self.owner_id, self.assigned_to_id) or                 self.members.filter(pk=user.pk).exists():
            return True
        return _at_least(role_in(user, self.company), "planner")

    def can_approve(self, user) -> bool:
        """Global 'approve design' permission, or approver / admin / owner of the project's company."""
        return user.has_perm("planner.approve_design") or _at_least(role_in(user, self.company), "approver")

    def can_manage(self, user) -> bool:
        """Delete, share and move between companies: the owner, or an admin of the project's company."""
        return user.is_superuser or self.owner_id == user.id or _at_least(role_in(user, self.company), "admin")


class Comment(models.Model):
    """Review comment on a project, optionally about one feature (pole, cable, FAT...)."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    text = models.TextField(max_length=2000)
    ref = models.CharField("feature", max_length=100, blank=True, help_text="Pole, cable or equipment ID")
    revision = models.PositiveIntegerField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.project}: {self.text[:40]}"

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "ref": self.ref, "revision": self.revision,
                "author": self.author.get_full_name() or self.author.get_username() if self.author else "",
                "created": self.created.isoformat(), "resolved": self.resolved,
                "resolved_by": self.resolved_by.get_username() if self.resolved_by else ""}


class Revision(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveIntegerField()
    created = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20)
    data_hash = models.CharField(max_length=16)
    data = models.JSONField()

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="unique_revision")]

    def __str__(self):
        return f"{self.project} rev {self.version}"


class ExportRecord(models.Model):
    """Data hash each deliverable was last generated from, to flag outputs that need regenerating."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="exports")
    deliverable = models.CharField(max_length=40)
    data_hash = models.CharField(max_length=16)
    version = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "deliverable"], name="unique_export")]


class PasswordResetRequest(models.Model):
    """'Forgot password' from the sign-in page: an administrator sets a new password and marks it resolved."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reset_requests")
    note = models.CharField("message", max_length=500, blank=True)
    ip = models.CharField("from address", max_length=64, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["resolved", "-created"]
        verbose_name = "password reset request"

    def __str__(self):
        return f"{self.user} ({self.created:%Y-%m-%d %H:%M})"
