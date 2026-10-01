"""Values made available to every template."""

from django.conf import settings

APP_NAME = "Equipment Manager"
APP_SHORT_NAME = "EMA"
APP_VERSION = "0.9.7"

# Files whose changes must reach the browser immediately.
_VERSIONED_ASSETS = ("static/css/app.css", "static/js/app.js")

_cached_version: str | None = None


def _compute_static_version() -> str:
    """
    A token that changes whenever the stylesheet or script changes.

    Appended to the asset URLs so the browser fetches the new file instead of
    reusing a cached copy. Without it, a style change is invisible until the
    person thinks to hard-refresh — which they have no reason to know about,
    and which makes a working change look broken.
    """
    newest = 0.0
    for relative in _VERSIONED_ASSETS:
        path = settings.BASE_DIR / relative
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return str(int(newest)) if newest else APP_VERSION


def static_version() -> str:
    """Recomputed every request while developing, cached once when serving."""
    global _cached_version
    if settings.DEBUG:
        return _compute_static_version()
    if _cached_version is None:
        _cached_version = _compute_static_version()
    return _cached_version


def app_info(request):
    return {
        "APP_NAME": APP_NAME,
        "APP_SHORT_NAME": APP_SHORT_NAME,
        "APP_VERSION": APP_VERSION,
        "STATIC_VERSION": static_version(),
        "DEBUG": settings.DEBUG,
    }
