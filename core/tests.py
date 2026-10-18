"""
Access control and page-rendering tests.

The point of this file: a read-only user must be blocked for real when they
type a URL directly, not merely have the button hidden.
"""

from django.test import TestCase
from django.urls import reverse

from core.models import Category, Location, Role, User
from equipment.models import Equipment, EquipmentStatus

PASSWORD = "test-pass-2026"


class BaseFixtureMixin:
    """Minimum data shared by the test cases below."""

    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for role in [Role.ADMIN, Role.MANAGER, Role.TECHNICIAN, Role.VIEWER]:
            cls.users[role] = User.objects.create_user(
                username=role.lower(),
                password=PASSWORD,
                full_name=f"{role.title()} User",
                role=role,
            )

        cls.category = Category.objects.create(code="FIX-ICT", name="ICT fixture")
        cls.location = Location.objects.create(code="ICT-RM", name="ICT Room")
        cls.equipment = Equipment.objects.create(
            code="ICT-FIX-001",
            name="ICT fixture — Mainboard",
            category=cls.category,
            location=cls.location,
            status=EquipmentStatus.IN_USE,
        )

    def login(self, role):
        self.client.login(username=role.lower(), password=PASSWORD)


class AuthenticationTests(BaseFixtureMixin, TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        for url in [
            reverse("dashboard"),
            reverse("equipment:list"),
            reverse("equipment:detail", args=[self.equipment.pk]),
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login/", response.url)

    def test_login_page_renders(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")


class PageRenderTests(BaseFixtureMixin, TestCase):
    """Every screen must open for an administrator."""

    def test_all_pages_render_for_admin(self):
        self.login(Role.ADMIN)
        urls = [
            reverse("dashboard"),
            reverse("equipment:list"),
            reverse("equipment:create"),
            reverse("equipment:detail", args=[self.equipment.pk]),
            reverse("equipment:update", args=[self.equipment.pk]),
            reverse("equipment:delete", args=[self.equipment.pk]),
            reverse("password_change"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, f"{url} did not render")

    def test_dashboard_renders_for_every_role(self):
        for role in self.users:
            with self.subTest(role=role):
                self.login(role)
                response = self.client.get(reverse("dashboard"))
                self.assertEqual(response.status_code, 200)

    def test_excel_export_returns_spreadsheet(self):
        self.login(Role.VIEWER)
        response = self.client.get(reverse("equipment:export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])

    def test_no_template_comment_markers_leak_into_pages(self):
        """
        Django's {# #} comment is single-line only.

        Spread one over two lines and the tail renders as visible text on the
        page. This catches that, because it is easy to miss in review and
        obvious to every user.
        """
        self.login(Role.ADMIN)
        for url in [
            reverse("dashboard"),
            reverse("equipment:list"),
            reverse("equipment:detail", args=[self.equipment.pk]),
            reverse("equipment:create"),
            reverse("equipment:delete", args=[self.equipment.pk]),
        ]:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertNotIn("{#", body, f"Unclosed template comment on {url}")
                self.assertNotIn("#}", body, f"Leaked comment marker on {url}")
                self.assertNotIn("{%", body, f"Unrendered template tag on {url}")


class PermissionTests(BaseFixtureMixin, TestCase):
    """Typing the URL must be blocked too, not just hiding the button."""

    def assert_blocked(self, url, role, method="get"):
        self.login(role)
        response = getattr(self.client, method)(url)
        self.assertEqual(response.status_code, 302, f"{role} should not reach {url}")
        self.assertEqual(response.url, reverse("dashboard"))

    def test_viewer_cannot_reach_write_screens(self):
        for url in [
            reverse("equipment:create"),
            reverse("equipment:update", args=[self.equipment.pk]),
            reverse("equipment:delete", args=[self.equipment.pk]),
        ]:
            with self.subTest(url=url):
                self.assert_blocked(url, Role.VIEWER)

    def test_viewer_cannot_change_status_by_posting_the_form(self):
        """Blocked even when posting data straight past the interface."""
        self.login(Role.VIEWER)
        response = self.client.post(
            reverse("equipment:update", args=[self.equipment.pk]),
            {"status": EquipmentStatus.BROKEN, "equipment_no": "X-0001", "category": self.category.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, EquipmentStatus.IN_USE)

    def test_technician_cannot_edit_equipment(self):
        self.assert_blocked(reverse("equipment:update", args=[self.equipment.pk]), Role.TECHNICIAN)

    def test_manager_can_edit_but_not_delete(self):
        self.login(Role.MANAGER)
        self.assertEqual(
            self.client.get(reverse("equipment:update", args=[self.equipment.pk])).status_code,
            200,
        )
        self.assert_blocked(reverse("equipment:delete", args=[self.equipment.pk]), Role.MANAGER)

    def test_role_properties(self):
        self.assertTrue(self.users[Role.ADMIN].can_manage)
        self.assertTrue(self.users[Role.MANAGER].can_record)
        self.assertTrue(self.users[Role.TECHNICIAN].can_record)
        self.assertFalse(self.users[Role.TECHNICIAN].can_manage)
        self.assertFalse(self.users[Role.VIEWER].can_record)

    def test_admin_role_grants_django_admin_access(self):
        self.assertTrue(self.users[Role.ADMIN].is_staff)
        self.assertFalse(self.users[Role.VIEWER].is_staff)


class UserDisplayTests(BaseFixtureMixin, TestCase):
    def test_initials_for_avatar(self):
        user = User.objects.create_user(
            username="khanh", password=PASSWORD, full_name="Khanh Pham", role=Role.TECHNICIAN
        )
        self.assertEqual(user.initials, "KP")

    def test_initials_fall_back_to_username(self):
        user = User.objects.create_user(username="operator", password=PASSWORD, role=Role.VIEWER)
        self.assertEqual(user.initials, "OP")
