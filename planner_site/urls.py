from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.shortcuts import redirect

from planner.security import ThrottledLoginView, forgot_password

admin.site.site_header = "ArchPlanner administration"
admin.site.site_title = "ArchPlanner admin"
admin.site.index_title = "Users, companies and projects"
admin.site.site_url = "/"

urlpatterns = [
    # admin sign-in uses the site's own sign-in page
    path("admin/login/", lambda r: redirect(f"/accounts/login/?{urlencode({'next': r.GET.get('next') or '/admin/'})}")),
    path("admin/", admin.site.urls),
    path("accounts/login/", ThrottledLoginView.as_view(), name="login"),
    path("accounts/forgot/", forgot_password, name="forgot_password"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/", auth_views.PasswordChangeView.as_view(success_url="/"), name="password_change"),
    path("", include("planner.urls")),
]
