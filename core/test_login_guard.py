"""Password guessing: sign-in locked for a while after too many failures, per user name and per address."""

import time
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Role
from core.tests import PASSWORD, BaseFixtureMixin


@override_settings(EMA_LOGIN_MAX_FAILURES=5, EMA_LOGIN_LOCKOUT_MINUTES=15)
class LoginGuardTests(BaseFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.username = self.users[Role.MANAGER].username

    def attempt(self, password, username=None, address="203.0.113.7", url=None):
        return self.client.post(url or reverse("login"), {"username": username or self.username, "password": password},
                                HTTP_CF_CONNECTING_IP=address)

    def signed_in(self):
        return "_auth_user_id" in self.client.session

    def test_five_failures_lock_even_the_right_password_out(self):
        for _ in range(5):
            self.attempt("wrong")
        response = self.attempt(PASSWORD)
        self.assertFalse(self.signed_in())
        self.assertContains(response, "Too many failed sign-ins. Try again in 15 minutes.")

    def test_fewer_failures_then_the_right_password_signs_in_and_clears_the_count(self):
        for _ in range(4):
            self.attempt("wrong")
        self.attempt(PASSWORD)
        self.assertTrue(self.signed_in())
        self.client.logout()
        for _ in range(4):
            self.attempt("wrong", address="198.51.100.9")      # a fresh address: the name starts again at 0
        self.attempt(PASSWORD, address="198.51.100.9")
        self.assertTrue(self.signed_in())

    def test_the_lock_ends_after_its_time(self):
        for _ in range(5):
            self.attempt("wrong")
        later = time.time() + 16 * 60
        with mock.patch("core.login_guard.time.time", return_value=later):
            self.attempt(PASSWORD)
        self.assertTrue(self.signed_in())

    def test_one_address_trying_many_names_is_locked_too(self):
        for n in range(5):
            self.attempt("wrong", username=f"nobody{n}")
        self.attempt(PASSWORD)                                   # a real user, from that address
        self.assertFalse(self.signed_in())
        self.attempt(PASSWORD, address="198.51.100.20")          # the same user from elsewhere: name not locked
        self.assertTrue(self.signed_in())

    def test_the_admin_sign_in_is_guarded_as_well(self):
        admin = self.users[Role.ADMIN]
        admin.is_staff = admin.is_superuser = True
        admin.save()
        url = reverse("admin:login")
        for _ in range(5):
            self.attempt("wrong", username=admin.username, url=url)
        self.attempt(PASSWORD, username=admin.username, address="203.0.113.7", url=url)
        self.assertFalse(self.signed_in())


@override_settings(ALLOWED_HOSTS=["ema.example.com", "testserver"], CSRF_TRUSTED_ORIGINS=["https://ema.example.com"],
                   SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
class ThroughTheTunnelTests(BaseFixtureMixin, TestCase):
    """A form posted on the public https address passes the CSRF check, as Cloudflare forwards it."""

    def test_sign_in_through_the_tunnel(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        page = client.get(reverse("login"), HTTP_HOST="ema.example.com", HTTP_X_FORWARDED_PROTO="https")
        token = page.cookies["csrftoken"].value
        client.post(reverse("login"), {"username": self.users[Role.MANAGER].username, "password": PASSWORD,
                                       "csrfmiddlewaretoken": token},
                    HTTP_HOST="ema.example.com", HTTP_X_FORWARDED_PROTO="https",
                    HTTP_ORIGIN="https://ema.example.com", HTTP_REFERER="https://ema.example.com/login/")
        self.assertIn("_auth_user_id", client.session)
