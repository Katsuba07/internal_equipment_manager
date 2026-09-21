"""Top-level URL map."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("equipment/", include("equipment.urls")),
    path("parts/", include("inventory.urls")),
    path("", include("systems.urls")),
    path("", include("core.urls")),
]

# Uploaded files (photos, attachments) are served by core.photos.serve_upload,
# in development and production alike, and only to signed-in users.
