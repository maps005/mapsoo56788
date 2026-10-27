from django.urls import path

from . import pages, views

P = "api/projects/<str:pid>"

urlpatterns = [
    path("", views.index, name="index"),
    path("projects/", pages.projects_page, name="projects_page"),
    path("review/", pages.review_page, name="review_page"),
    path("company/", pages.company_page, name="company_page"),
    path("profile/", pages.profile_page, name="profile_page"),
    path("api/me", views.me),
    path("api/defaults", views.defaults),
    path("api/standards", views.list_standards),
    path("api/photo-ai", views.photo_ai),
    path("api/ai-chat", views.ai_chat_status),
    path("api/people", views.find_people),
    path("api/survey-template.xlsx", views.survey_template),
    path("api/projects", views.projects),
    path(P, views.project),
    path(f"{P}/share", views.share),
    path(f"{P}/comments", views.comments),
    path(f"{P}/comments/<int:cid>/resolve", views.resolve_comment),
    path("company/<int:cid>/logo", views.company_logo, name="company_logo"),
    path(f"{P}/import", views.import_data),
    path(f"{P}/prices", views.import_prices),
    path(f"{P}/assign-homes", views.assign_homes),
    path(f"{P}/allocate", views.allocate),
    path(f"{P}/auto-design", views.auto_design),
    path(f"{P}/ai-chat", views.ai_chat),
    path(f"{P}/apply-standard", views.apply_standard),
    path(f"{P}/calc", views.calculations),
    path(f"{P}/splicing", views.splicing_view),
    path(f"{P}/revisions", views.revisions),
    path(f"{P}/revisions/<int:version>/restore", views.restore_revision),
    path(f"{P}/photos", views.upload_photo),
    path(f"{P}/photos/<str:name>", views.get_photo),
    path(f"{P}/photos/<str:name>/analyse", views.analyse_photo),
    path(f"{P}/export/<str:deliverable>.<str:fmt>", views.export),
    path(f"{P}/package.zip", views.export_package),
]
