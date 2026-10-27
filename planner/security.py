"""Sign-in throttling and Content-Security-Policy header."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

MAX_FAILURES = 10          # failed sign-ins per username + address ...
WINDOW_SECONDS = 15 * 60   # ... within this window lock that pair out for the rest of the window


def _client_ip(request) -> str:
    # Caddy / nginx append the real client address as the LAST X-Forwarded-For entry
    # (earlier entries come from the client and can be forged)
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[-1].strip() if fwd else request.META.get("REMOTE_ADDR", "")) or "unknown"


class ThrottledLoginView(auth_views.LoginView):
    def _key(self):
        user = (self.request.POST.get("username") or "").strip().lower()[:150]
        return f"login-fail:{_client_ip(self.request)}:{user}"

    def post(self, request, *args, **kwargs):
        if cache.get(self._key(), 0) >= MAX_FAILURES:
            form = self.get_form()
            form.add_error(None, "Too many failed sign-in attempts. Please wait 15 minutes and try again.")
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        if self.request.method == "POST":
            key = self._key()
            cache.set(key, cache.get(key, 0) + 1, WINDOW_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._key())
        response = super().form_valid(form)
        if not self.request.POST.get("remember"):
            self.request.session.set_expiry(0)  # a shared computer: sign out when the browser closes
        return response


RESET_PER_ADDRESS = 5        # forgot-password requests from one address per hour
RESET_REPEAT = timedelta(hours=1)  # an open request for the same account is not repeated within this time


@require_http_methods(["GET", "POST"])
def forgot_password(request):
    """Notify the administrators that someone cannot sign in. The reply is the same whether or not the account
    exists, so the page cannot be used to find out user names."""
    from .models import PasswordResetRequest
    ctx = {"identifier": "", "note": "", "sent": False, "error": ""}
    if request.method == "POST":
        ident = (request.POST.get("identifier") or "").strip()[:150]
        note = (request.POST.get("note") or "").strip()[:500]
        ctx.update(identifier=ident, note=note)
        if not ident:
            ctx["error"] = "Enter your username or email."
            return render(request, "registration/forgot.html", ctx)
        ip = _client_ip(request)
        key = f"reset-req:{ip}"
        if cache.get(key, 0) >= RESET_PER_ADDRESS:
            ctx["error"] = "Too many requests from this address. Please try again in an hour."
            return render(request, "registration/forgot.html", ctx)
        cache.set(key, cache.get(key, 0) + 1, 3600)
        users = list(get_user_model().objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident),
                                                      is_active=True)[:2])
        if len(users) == 1:  # an email shared by two accounts is ambiguous: notify nobody
            recent = PasswordResetRequest.objects.filter(user=users[0], resolved=False,
                                                         created__gte=timezone.now() - RESET_REPEAT)
            if not recent.exists():
                PasswordResetRequest.objects.create(user=users[0], note=note, ip=ip[:64])
        ctx.update(sent=True, identifier="", note="")
    return render(request, "registration/forgot.html", ctx)


CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://unpkg.com",
    "style-src 'self' https://unpkg.com 'unsafe-inline'",
    "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org "
    "https://*.basemaps.cartocdn.com https://server.arcgisonline.com https://unpkg.com",
    "connect-src 'self' https://unpkg.com",  # Leaflet source map (developer tools)
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


class ContentSecurityPolicyMiddleware:
    """Strict CSP for the planner pages (the Django admin keeps its own defaults)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/admin/") and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = CSP
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")  # map tile servers need the origin
        return response
