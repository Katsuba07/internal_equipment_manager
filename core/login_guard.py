"""
Against password guessing, now that the sign-in page can be reached from the
internet (through the Cloudflare Tunnel, see EMA_PUBLIC_URL).

Failed sign-ins are counted per user name and per address. Past
EMA_LOGIN_MAX_FAILURES within EMA_LOGIN_LOCKOUT_MINUTES, signing in is refused
for that long — with the right password too — on the app's page and on
/admin/ alike, since both go through the authentication backend below. A
successful sign-in clears the user name's count.

The counts live in Django's cache: the app runs as one process (Waitress), so
the default in-memory cache is shared by every request. A restart clears them.
"""

import time

from django.conf import settings
from django.contrib.auth import user_login_failed, user_logged_in
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.dispatch import receiver


def client_address(request) -> str:
    """The visitor's address: Cloudflare passes it on; on the LAN it is the socket's."""
    if request is None:
        return ""
    meta = request.META
    return (meta.get("HTTP_CF_CONNECTING_IP") or meta.get("REMOTE_ADDR") or "").strip()


def _keys(username: str, address: str) -> list[str]:
    keys = []
    if username:
        keys.append(f"login-fail:user:{username.strip().lower()}")
    if address:
        keys.append(f"login-fail:addr:{address}")
    return keys


def _window() -> int:
    return settings.EMA_LOGIN_LOCKOUT_MINUTES * 60


def minutes_locked(username: str, address: str) -> int:
    """Minutes left before this user name or address may try again; 0 when not locked."""
    now = time.time()
    left = 0
    for key in _keys(username, address):
        entry = cache.get(key)
        if entry and entry["count"] >= settings.EMA_LOGIN_MAX_FAILURES:
            left = max(left, entry["until"] - now)
    return int(left // 60) + 1 if left > 0 else 0


@receiver(user_login_failed)
def count_failure(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get("username", "")
    now = time.time()
    for key in _keys(username, client_address(request)):
        entry = cache.get(key) or {"count": 0}
        entry["count"] += 1
        entry["until"] = now + _window()          # the window restarts with each failure
        cache.set(key, entry, _window())


@receiver(user_logged_in)
def clear_failures(sender, request, user, **kwargs):
    cache.delete(f"login-fail:user:{user.get_username().strip().lower()}")


class GuardedModelBackend(ModelBackend):
    """The usual username + password check, refused while the name or address is locked out."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if minutes_locked(username or "", client_address(request)):
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)


class GuardedAuthenticationForm(AuthenticationForm):
    """The sign-in form, saying plainly when signing in is locked for a while."""

    def clean(self):
        username = self.cleaned_data.get("username") or ""
        minutes = minutes_locked(username, client_address(self.request))
        if minutes:
            raise ValidationError(
                f"Too many failed sign-ins. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                code="locked",
            )
        return super().clean()
