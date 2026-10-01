"""Top-level URL map."""

from django.contrib import admin
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Pages without a <link rel="icon">, such as the admin site, ask for this.
    path("favicon.ico", RedirectView.as_view(url=static("img/favicon.svg"), permanent=True)),
    path("equipment/", include("equipment.urls")),
    path("parts/", include("inventory.urls")),
    path("", include("systems.urls")),
    path("", include("core.urls")),
]
