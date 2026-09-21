"""Shared routes: dashboard and authentication."""

from django.contrib.auth import views as auth_views
from django.urls import path

from .photos import PhotoDeleteView, PhotoPrimaryView, PhotoUploadView, serve_upload
from .quickadd import QuickAddView
from .views import ActivityView, DashboardView

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("activity/", ActivityView.as_view(), name="activity"),
    path("quick-add/<str:kind>/", QuickAddView.as_view(), name="quick_add"),
    path("photos/<str:app_label>/<str:model>/<int:pk>/", PhotoUploadView.as_view(), name="photo_upload"),
    path("photos/<int:pk>/primary/", PhotoPrimaryView.as_view(), name="photo_primary"),
    path("photos/<int:pk>/delete/", PhotoDeleteView.as_view(), name="photo_delete"),
    path("uploads/<path:path>", serve_upload, name="upload"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change.html",
            success_url="/password/changed/",
        ),
        name="password_change",
    ),
    path(
        "password/changed/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/password_change_done.html"
        ),
        name="password_change_done",
    ),
]
