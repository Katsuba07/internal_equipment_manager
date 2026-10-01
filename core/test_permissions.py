"""Every URL of the app, posted to by a viewer: nothing may change."""

import re

from django.apps import apps
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from core.models import Role
from core.tests import BaseFixtureMixin

# A viewer may still do these: they write nothing that belongs to anyone else.
ALLOWED_FOR_VIEWERS = {"logout", "password_change", "password_change_done", "login", "document_sync"}
# Downloads: answering a POST with the file is harmless.
READ_ONLY = {"import_template", "export"}


def all_routes(resolver=None, prefix=""):
    for entry in (resolver or get_resolver()).url_patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            if route.startswith("admin/"):
                continue
            yield from all_routes(entry, route)
        elif isinstance(entry, URLPattern):
            yield route, entry.name


def sample_url(route):
    url = re.sub(r"<int:\w+>", "1", route)
    url = re.sub(r"<path:\w+>", "x/y", url)
    url = re.sub(r"<(?:str|slug):\w+>", "equipment", url)
    return "/" + url.lstrip("^").rstrip("$")


def row_counts():
    return {m._meta.label: m.objects.count() for m in apps.get_models() if not m._meta.label.startswith("sessions.")}


class ViewerCannotWriteAnywhereTests(BaseFixtureMixin, TestCase):
    def test_every_post_is_refused_and_changes_nothing(self):
        self.login(Role.VIEWER)
        before = row_counts()
        checked = 0
        for route, name in all_routes():
            if name in ALLOWED_FOR_VIEWERS:
                continue
            url = sample_url(route)
            with self.subTest(url=url, name=name):
                response = self.client.post(url, {"code": "X", "name": "X", "quantity": "1", "pk": "1"})
                # Refused: sent back with a message (3xx), or turned away outright.
                allowed = (301, 302, 400, 403, 404, 405) + ((200,) if name in READ_ONLY else ())
                self.assertIn(response.status_code, allowed, url)
                checked += 1
        self.assertGreater(checked, 30)
        self.assertEqual(row_counts(), before)
