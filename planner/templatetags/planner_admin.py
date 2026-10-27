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
