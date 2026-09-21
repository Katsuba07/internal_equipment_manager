"""The "+ New" pop-up forms, the "Still in use" tick, and review regressions."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Category, Customer, Location, Product, Role
from equipment.models import Equipment
from inventory.models import InventoryItem
from systems.models import Installation, SystemType
from systems.tests import Fixture


class QuickAddTests(Fixture, TestCase):
    def quick(self, kind, data):
        return self.client.post(reverse("quick_add", args=[kind]), data)

    def test_every_form_renders_with_its_own_ids(self):
        self.login(Role.MANAGER)
        for kind in ["customer", "product", "systemtype", "location", "category", "supplier", "equipment", "part"]:
            with self.subTest(kind=kind):
                body = self.client.get(reverse("quick_add", args=[kind])).content.decode()
                self.assertIn("<form", body)
                self.assertIn('id="qa_code"', body)
                self.assertNotIn('id="id_code"', body)

    def test_new_customer_and_product(self):
        self.login(Role.MANAGER)
        customer = self.quick("customer", {"code": "krain", "name": "K-Rain"}).json()
        self.assertEqual(Customer.objects.get(pk=customer["id"]).code, "KRAIN")
        product = self.quick("product", {"customer": customer["id"], "code": "kmcb011", "name": "Main"}).json()
        self.assertEqual(Product.objects.get(pk=product["id"]).customer.name, "K-Rain")

    def test_errors_come_back_as_the_form(self):
        self.login(Role.MANAGER)
        response = self.quick("product", {"code": "RMMTT01", "name": "Duplicate"})
        self.assertEqual(response["Content-Type"].split(";")[0], "text/html")
        self.assertContains(response, "already exists")

    def test_new_process_with_template_roles(self):
        self.login(Role.MANAGER)
        data = self.quick("systemtype", {
            "code": "burnin", "name": "Burn-in", "roles": "fix\n\nFixture: FIX\nDMM",
        }).json()
        process = SystemType.objects.get(pk=data["id"])
        roles = list(process.roles.order_by("position"))
        self.assertEqual([r.name for r in roles], ["Fixture 1", "Fixture 2", "Digital multimeter"])
        self.assertEqual(list(roles[0].allowed_categories.all()), [self.fix_cat])

    def test_unknown_category_code_in_roles_is_refused(self):
        self.login(Role.MANAGER)
        response = self.quick("systemtype", {"code": "X", "name": "X", "roles": "Thing: NOPE"})
        self.assertContains(response, "No equipment type with code NOPE")

    def test_new_asset_gets_opening_history(self):
        self.login(Role.MANAGER)
        data = self.quick("equipment", {
            "code": "cart-009", "name": "Cart", "category": self.cart_cat.pk, "location": self.room.pk,
        }).json()
        asset = Equipment.objects.get(pk=data["id"])
        self.assertEqual(asset.code, "CART-009")
        self.assertEqual(asset.status_history.count(), 1)

    def test_new_part_with_opening_stock(self):
        self.login(Role.MANAGER)
        data = self.quick("part", {
            "code": "prb-1", "name": "Probe", "kind": "PROBE", "unit": "pcs",
            "min_quantity": "10", "opening_stock": "100",
        }).json()
        self.assertEqual(InventoryItem.objects.get(pk=data["id"]).quantity_on_hand, 100)

    def test_new_location_and_category(self):
        self.login(Role.MANAGER)
        self.assertTrue(Location.objects.filter(pk=self.quick("location", {"code": "l9", "name": "Line 9"}).json()["id"]).exists())
        self.assertTrue(Category.objects.filter(pk=self.quick("category", {"code": "scp", "name": "Scope"}).json()["id"]).exists())

    def test_technician_and_viewer_cannot_add(self):
        for role in (Role.TECHNICIAN, Role.VIEWER):
            self.login(role)
            with self.subTest(role=role):
                self.assertEqual(self.quick("product", {"code": "X1", "name": "x"}).status_code, 302)
        self.assertFalse(Product.objects.filter(code="X1").exists())

    def test_unknown_kind_is_404(self):
        self.login(Role.MANAGER)
        self.assertEqual(self.client.get("/quick-add/nothing/").status_code, 404)


class ActiveTickTests(Fixture, TestCase):
    def test_hidden_on_create_explained_on_edit(self):
        self.login(Role.MANAGER)
        hx = {"HTTP_HX_REQUEST": "true"}
        create = self.client.get(reverse("systems:product_create"), **hx).content.decode()
        self.assertNotIn('name="is_active"', create)
        edit = self.client.get(reverse("systems:product_edit", args=[self.rmmtt01.pk]), **hx).content.decode()
        self.assertIn("Still in use", edit)
        part_create = self.client.get(reverse("inventory:part_create")).content.decode()
        self.assertNotIn('name="is_active"', part_create)


class ReviewFixTests(Fixture, TestCase):
    """Regressions found in the browser review of 19 Sep 2026."""

    def test_used_for_is_the_product_of_the_set_holding_the_asset(self):
        test_set = self.make_set()
        Installation.fit(self.dmm2, test_set, self.role(test_set, "DMM"), self.users[Role.ADMIN])
        self.assertEqual(self.dmm2.product_codes, ["RMMTT01"])

    def test_one_day_overdue_is_singular(self):
        from calibration.models import CalibrationPlan

        plan = CalibrationPlan(next_due_at=timezone.localdate() - timedelta(days=1))
        self.assertEqual(plan.due_display, "1 day overdue")


class TemplateAdminTests(Fixture, TestCase):
    def test_admin_template_roles_are_equipment_types(self):
        admin_user = self.users[Role.ADMIN]
        admin_user.is_superuser = True
        admin_user.save()
        self.login(Role.ADMIN)
        url = reverse("admin:systems_systemtype_change", args=[self.fct.pk])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        roles = list(self.fct.roles.order_by("position"))
        data = {
            "code": "FCT", "name": "Functional test", "position": "3", "is_active": "on",
            "roles-TOTAL_FORMS": "4", "roles-INITIAL_FORMS": "3",
            "roles-MIN_NUM_FORMS": "0", "roles-MAX_NUM_FORMS": "1000",
        }
        for i, role in enumerate(roles):
            data.update({
                f"roles-{i}-id": role.pk, f"roles-{i}-system_type": self.fct.pk,
                f"roles-{i}-position": role.position, f"roles-{i}-category": role.allowed_categories.first().pk,
                f"roles-{i}-is_required": "on",
            })
        data.update({"roles-3-system_type": self.fct.pk, "roles-3-position": "4",
                     "roles-3-category": self.dmm_cat.pk, "roles-3-is_required": "on"})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context.get("errors"))
        self.assertEqual(
            list(self.fct.roles.order_by("position").values_list("name", flat=True)),
            ["Test cart", "Fixture", "Digital multimeter 1", "Digital multimeter 2"],
        )
