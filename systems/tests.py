"""
Tests for products, their processes, roles and equipment sets.

The core guarantee — one asset in one place — is enforced by database
constraints, so it is asserted directly. The rest covers set readiness, the
one-save set editor, one-click deletion, the products page and permissions.
"""

from datetime import timedelta

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from calibration.models import CalibrationPlan
from core.models import Category, Customer, Location, Product, Role, User
from equipment.models import Equipment, EquipmentStatus
from systems.models import (
    Installation,
    ProcessRole,
    ProductProcess,
    SlotState,
    SystemType,
    SystemTypeRole,
    TestSet,
)
from systems.services import (
    apply_set_changes,
    delete_with_release,
    deletion_summary,
    evaluate_set,
    products_overview,
)

PASSWORD = "test-pass-2026"


class Fixture:
    @classmethod
    def setUpTestData(cls):
        cls.users = {
            role: User.objects.create_user(
                username=role.lower(), password=PASSWORD, full_name=role.title(), role=role
            )
            for role in [Role.ADMIN, Role.MANAGER, Role.TECHNICIAN, Role.VIEWER]
        }
        cls.cart_cat = Category.objects.create(code="CART", name="Test cart")
        cls.dmm_cat = Category.objects.create(code="DMM", name="Digital multimeter")
        cls.fix_cat = Category.objects.create(code="FIX", name="Fixture")
        cls.room = Location.objects.create(code="L2", name="Line 2")

        cls.fct = SystemType.objects.create(code="FCT", name="Functional test", position=3)
        cls.ict = SystemType.objects.create(code="ICT", name="In-circuit test", position=2)
        for position, (name, cat) in enumerate(
            [("Test Cart", cls.cart_cat), ("Fixture", cls.fix_cat), ("DMM", cls.dmm_cat)], start=1
        ):
            SystemTypeRole.objects.create(system_type=cls.fct, name=name, position=position).allowed_categories.add(cat)

        cls.rheem = Customer.objects.create(code="RHEEM", name="Rheem")
        cls.baf = Customer.objects.create(code="BAF", name="BAF")
        cls.rmmtt01 = Product.objects.create(code="RMMTT01", name="Control", customer=cls.rheem, in_production=True)
        cls.baf0850 = Product.objects.create(code="BAF0850", name="Power", customer=cls.baf, in_production=False)

        def asset(code, cat, **kw):
            return Equipment.objects.create(code=code, name=code, category=cat, location=cls.room, **kw)

        cls.cart1 = asset("CART-001", cls.cart_cat)
        cls.cart2 = asset("CART-002", cls.cart_cat)
        cls.dmm1 = asset("DMM-001", cls.dmm_cat)
        cls.dmm2 = asset("DMM-002", cls.dmm_cat)
        cls.fix1 = asset("FIX-RM01", cls.fix_cat)

    def make_step(self, product=None, process=None):
        step = ProductProcess.objects.create(product=product or self.rmmtt01, process=process or self.fct, position=1)
        step.copy_template()
        return step

    def make_set(self, step=None, number=1):
        return TestSet.objects.create(product_process=step or self.make_step(), number=number, line=self.room)

    ROLE_TYPES = {"Test Cart": "CART", "Fixture": "FIX", "DMM": "DMM"}

    def role(self, test_set, label):
        """Roles are named after their equipment type; find them by that type."""
        return test_set.product_process.roles.get(category__code=self.ROLE_TYPES[label])

    def login(self, role):
        self.client.login(username=role.lower(), password=PASSWORD)


class ProcessTests(Fixture, TestCase):
    def test_template_is_copied_into_the_product_process(self):
        step = self.make_step()
        roles = list(step.roles.values_list("name", "category__code"))
        self.assertEqual(roles, [("Test cart", "CART"), ("Fixture", "FIX"), ("Digital multimeter", "DMM")])

    def test_each_product_edits_its_own_role_list(self):
        a = self.make_step()
        b = self.make_step(product=self.baf0850)
        b.roles.get(category=self.cart_cat).delete()
        ProcessRole.objects.create(product_process=b, name="~x", position=9, category=self.dmm_cat)
        b.name_roles()
        self.assertEqual(a.roles.count(), 3)
        self.assertEqual(
            list(b.roles.values_list("name", flat=True)),
            ["Fixture", "Digital multimeter 1", "Digital multimeter 2"],
        )

    def test_sets_share_the_process_roles_and_number_up(self):
        step = self.make_step()
        s1 = self.make_set(step)
        s2 = TestSet.objects.create(product_process=step, number=step.next_set_number())
        self.assertEqual(s2.number, 2)
        self.assertEqual(str(s2), "RMMTT01 · FCT #2")
        self.assertEqual(s1.product_process.roles.count(), s2.product_process.roles.count())


class FitTests(Fixture, TestCase):
    def setUp(self):
        self.set1 = self.make_set()
        self.set2 = TestSet.objects.create(product_process=self.set1.product_process, number=2)
        self.admin = self.users[Role.ADMIN]

    def test_database_rejects_one_asset_in_two_places(self):
        Installation.fit(self.cart1, self.set1, self.role(self.set1, "Test Cart"), self.admin)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Installation.objects.create(component=self.cart1, test_set=self.set2, role=self.role(self.set2, "Test Cart"))

    def test_database_rejects_two_assets_in_one_role(self):
        role = self.role(self.set1, "Test Cart")
        Installation.fit(self.cart1, self.set1, role, self.admin)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Installation.objects.create(component=self.cart2, test_set=self.set1, role=role)

    def test_asset_in_another_set_is_refused_by_name(self):
        Installation.fit(self.cart1, self.set1, self.role(self.set1, "Test Cart"), self.admin)
        with self.assertRaisesMessage(ValidationError, "RMMTT01 · FCT #1"):
            Installation.fit(self.cart1, self.set2, self.role(self.set2, "Test Cart"), self.admin)

    def test_wrong_kind_of_asset_is_refused(self):
        with self.assertRaisesMessage(ValidationError, "needs a Test cart"):
            Installation.fit(self.dmm1, self.set1, self.role(self.set1, "Test Cart"), self.admin)

    def test_readiness_states(self):
        Installation.fit(self.cart1, self.set1, self.role(self.set1, "Test Cart"), self.admin)
        states = {s.role.name: s.state for s in evaluate_set(self.set1).lines}
        self.assertEqual(states, {
            "Test cart": SlotState.READY, "Fixture": SlotState.EMPTY, "Digital multimeter": SlotState.EMPTY,
        })

    def test_overdue_calibration_makes_an_asset_unusable(self):
        CalibrationPlan.objects.create(
            equipment=self.dmm1, name="Annual", interval_months=12,
            next_due_at=timezone.localdate() - timedelta(days=3),
        )
        Installation.fit(self.dmm1, self.set1, self.role(self.set1, "DMM"), self.admin)
        status = next(s for s in evaluate_set(self.set1).lines if s.role.category == self.dmm_cat)
        self.assertEqual(status.state, SlotState.UNUSABLE)
        self.assertIn("overdue", status.detail)

    def test_down_asset_is_unusable(self):
        self.cart1.status = EquipmentStatus.DOWN
        self.cart1.save()
        Installation.fit(self.cart1, self.set1, self.role(self.set1, "Test Cart"), self.admin)
        status = evaluate_set(self.set1).lines[0]
        self.assertEqual(status.state, SlotState.UNUSABLE)

    def test_apply_changes_swaps_removes_and_keeps_history(self):
        cart_role = self.role(self.set1, "Test Cart")
        apply_set_changes(self.set1, {cart_role.id: self.cart1}, self.admin)
        apply_set_changes(self.set1, {cart_role.id: self.cart2}, self.admin)
        self.assertEqual(self.set1.open_installations().get().component, self.cart2)
        self.assertTrue(Installation.objects.filter(component=self.cart1, removed_at__isnull=False).exists())
        apply_set_changes(self.set1, {cart_role.id: None}, self.admin)
        self.assertFalse(self.set1.open_installations().exists())

    def test_apply_changes_can_move_an_asset_between_sets_after_removal(self):
        role1, role2 = self.role(self.set1, "DMM"), self.role(self.set2, "DMM")
        apply_set_changes(self.set1, {role1.id: self.dmm1}, self.admin)
        with self.assertRaises(ValidationError):
            apply_set_changes(self.set2, {role2.id: self.dmm1}, self.admin)
        apply_set_changes(self.set1, {role1.id: None}, self.admin)
        apply_set_changes(self.set2, {role2.id: self.dmm1}, self.admin)
        self.assertEqual(self.dmm1.fitted_in, self.set2)

    def test_same_asset_for_two_roles_is_refused(self):
        with self.assertRaises(ValidationError):
            apply_set_changes(self.set1, {
                self.role(self.set1, "Test Cart").id: self.cart1,
                self.role(self.set1, "DMM").id: self.cart1,
            }, self.admin)


class DeleteTests(Fixture, TestCase):
    def setUp(self):
        self.set1 = self.make_set()
        Installation.fit(self.cart1, self.set1, self.role(self.set1, "Test Cart"), self.users[Role.ADMIN])

    def test_delete_product_releases_equipment_and_keeps_asset_history(self):
        summary = deletion_summary(self.rmmtt01)
        self.assertEqual([i.component for i in summary["released"]], [self.cart1])
        delete_with_release(self.rmmtt01, self.users[Role.ADMIN])
        self.assertFalse(Product.objects.filter(pk=self.rmmtt01.pk).exists())
        self.assertTrue(Equipment.objects.filter(pk=self.cart1.pk).exists())
        history = Installation.objects.get(component=self.cart1)
        self.assertIsNotNone(history.removed_at)
        self.assertEqual(history.where, "RMMTT01 · FCT #1")

    def test_delete_set_and_process(self):
        delete_with_release(self.set1, self.users[Role.ADMIN])
        self.assertFalse(TestSet.objects.exists())
        step = ProductProcess.objects.get()
        delete_with_release(step, self.users[Role.ADMIN])
        self.assertFalse(ProductProcess.objects.exists())

    def test_deleting_a_process_type_is_not_blocked(self):
        self.fct.delete()
        self.assertFalse(ProductProcess.objects.exists())

    def test_delete_views_are_one_click(self):
        self.login(Role.ADMIN)
        confirm = self.client.get(reverse("systems:product_delete", args=[self.rmmtt01.pk]))
        self.assertContains(confirm, "CART-001")
        self.client.post(reverse("systems:product_delete", args=[self.rmmtt01.pk]))
        self.assertFalse(Product.objects.filter(pk=self.rmmtt01.pk).exists())


class OverviewTests(Fixture, TestCase):
    def test_groups_by_customer_and_hides_products_not_in_production(self):
        self.make_set(self.make_step(product=self.baf0850))
        groups = products_overview()
        self.assertEqual([g.name for g in groups], ["Rheem"])
        groups = products_overview(show_all=True)
        self.assertEqual([g.name for g in groups], ["BAF", "Rheem"])
        self.assertEqual(groups[0].products[0]["product"], self.baf0850)

    def test_only_equipment_in_use_is_listed(self):
        test_set = self.make_set()
        Installation.fit(self.cart1, test_set, self.role(test_set, "Test Cart"), self.users[Role.ADMIN])
        group = products_overview()[0]
        sets = group.products[0]["steps"][0]["sets"]
        self.assertEqual([i.component.code for i in sets[0]["installations"]], ["CART-001"])


class DashboardLineTests(Fixture, TestCase):
    def test_overview_shows_sets_and_what_stops_them(self):
        from systems.services import line_status

        test_set = self.make_set()
        Installation.fit(self.cart1, test_set, self.role(test_set, "Test Cart"), self.users[Role.ADMIN])
        status = line_status()
        self.assertEqual((status["product_count"], status["sets_total"], status["sets_bad"]), (1, 1, 1))
        self.assertEqual({i["line"].role.name for i in status["issues"]}, {"Fixture", "Digital multimeter"})
        self.login(Role.VIEWER)
        body = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("What stops a set", body)
        self.assertIn(f"?set={test_set.pk}", body)
        self.assertIn("Fitted", body)            # the fit shows in recent activity


class PageTests(Fixture, TestCase):
    def setUp(self):
        self.step = self.make_step()
        self.set1 = self.make_set(self.step)
        Installation.fit(self.cart1, self.set1, self.role(self.set1, "Test Cart"), self.users[Role.ADMIN])

    def hx(self, url, method="get", data=None):
        call = getattr(self.client, method)
        return call(url, data or {}, HTTP_HX_REQUEST="true")

    def test_page_and_every_panel_render(self):
        self.login(Role.ADMIN)
        urls = [
            reverse("systems:products"),
            reverse("systems:products") + "?show=all",
            reverse("systems:products") + f"?set={self.set1.pk}",
            reverse("systems:products") + f"?product={self.rmmtt01.pk}",
            reverse("systems:products") + f"?process={self.step.pk}",
            reverse("systems:products") + "?new=product",
        ]
        for url in urls:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertNotIn("{%", body)
                self.assertIn("RMMTT01", body)
        for url in [
            reverse("systems:set_panel", args=[self.set1.pk]),
            reverse("systems:product_panel", args=[self.rmmtt01.pk]),
            reverse("systems:process_panel", args=[self.step.pk]),
            reverse("systems:set_edit", args=[self.set1.pk]),
            reverse("systems:product_edit", args=[self.rmmtt01.pk]),
            reverse("systems:product_create"),
        ]:
            with self.subTest(url=url):
                response = self.hx(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("<html", response.content.decode())

    def test_panel_url_without_htmx_opens_the_full_page(self):
        self.login(Role.VIEWER)
        response = self.client.get(reverse("systems:set_panel", args=[self.set1.pk]))
        self.assertRedirects(response, reverse("systems:products") + f"?set={self.set1.pk}")

    def test_set_panel_shows_equipment_in_use_and_its_parts(self):
        from inventory.models import EquipmentPart, InventoryItem

        probe = InventoryItem.objects.create(code="PRB-1", name="Probe")
        EquipmentPart.objects.create(equipment=self.cart1, item=probe, quantity=12)
        self.login(Role.VIEWER)
        body = self.hx(reverse("systems:set_panel", args=[self.set1.pk])).content.decode()
        self.assertIn("CART-001", body)
        self.assertIn("PRB-1", body)
        self.assertIn("Not ready", body)

    def test_technician_edits_a_set_in_one_save(self):
        self.login(Role.TECHNICIAN)
        fix, dmm = self.role(self.set1, "Fixture"), self.role(self.set1, "DMM")
        cart = self.role(self.set1, "Test Cart")
        response = self.hx(reverse("systems:set_edit", args=[self.set1.pk]), "post", {
            "line": self.room.pk, f"role_{cart.id}": self.cart2.pk,
            f"role_{fix.id}": self.fix1.pk, f"role_{dmm.id}": self.dmm1.pk,
        })
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("systems:products") + f"?set={self.set1.pk}")
        self.assertEqual(
            set(self.set1.open_installations().values_list("component__code", flat=True)),
            {"CART-002", "FIX-RM01", "DMM-001"},
        )
        self.assertTrue(evaluate_set(self.set1).is_ready)

    def test_set_edit_shows_why_when_refused(self):
        other = TestSet.objects.create(product_process=self.step, number=2)
        self.login(Role.TECHNICIAN)
        cart = self.role(other, "Test Cart")
        response = self.hx(reverse("systems:set_edit", args=[other.pk]), "post", {f"role_{cart.id}": self.cart1.pk})
        self.assertContains(response, "currently fitted in RMMTT01 · FCT #1")

    def test_new_product_with_processes_gets_roles_and_a_set_each(self):
        self.login(Role.MANAGER)
        response = self.hx(reverse("systems:product_create"), "post", {
            "customer": self.baf.pk, "code": "baf1950", "name": "Mainboard", "in_production": "on",
            "processes": [self.ict.pk, self.fct.pk],
        })
        self.assertEqual(response.status_code, 204)
        product = Product.objects.get(code="BAF1950")
        self.assertTrue(product.in_production)
        self.assertEqual(list(product.processes.values_list("process__code", flat=True)), ["ICT", "FCT"])
        self.assertEqual(TestSet.objects.filter(product_process__product=product).count(), 2)

    def test_manager_adds_process_reorders_toggles_and_adds_set(self):
        self.login(Role.MANAGER)
        self.hx(reverse("systems:process_add", args=[self.rmmtt01.pk]), "post", {"process": self.ict.pk})
        ict = self.rmmtt01.processes.get(process=self.ict)
        self.hx(reverse("systems:process_move", args=[ict.pk, "up"]), "post")
        self.assertEqual(list(self.rmmtt01.processes.order_by("position").values_list("process__code", flat=True)), ["ICT", "FCT"])
        self.hx(reverse("systems:product_toggle", args=[self.rmmtt01.pk]), "post")
        self.rmmtt01.refresh_from_db()
        self.assertFalse(self.rmmtt01.in_production)
        self.hx(reverse("systems:set_add", args=[self.step.pk]), "post")
        self.assertEqual(self.step.sets.count(), 2)

    def test_drag_and_drop_saves_a_new_route_order(self):
        ict = ProductProcess.objects.create(product=self.rmmtt01, process=self.ict, position=2)
        url = reverse("systems:process_reorder", args=[self.rmmtt01.pk])
        self.login(Role.MANAGER)
        response = self.client.post(url, {"order": f"{ict.pk},{self.step.pk}"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(list(self.rmmtt01.processes.order_by("position").values_list("process__code", flat=True)), ["ICT", "FCT"])

    def test_reorder_refuses_a_wrong_list_and_leaves_order_alone(self):
        ict = ProductProcess.objects.create(product=self.rmmtt01, process=self.ict, position=2)
        other = self.make_step(product=self.baf0850)
        url = reverse("systems:process_reorder", args=[self.rmmtt01.pk])
        self.login(Role.MANAGER)
        for bad in [f"{ict.pk}", f"{ict.pk},{other.pk}", f"{ict.pk},{ict.pk}", "x,y", ""]:
            with self.subTest(order=bad):
                self.assertEqual(self.client.post(url, {"order": bad}).status_code, 400)
        self.assertEqual(list(self.rmmtt01.processes.order_by("position").values_list("process__code", flat=True)), ["FCT", "ICT"])

    def test_technician_cannot_reorder_and_sees_no_drag_handle(self):
        ProductProcess.objects.create(product=self.rmmtt01, process=self.ict, position=2)
        self.login(Role.TECHNICIAN)
        url = reverse("systems:process_reorder", args=[self.rmmtt01.pk])
        self.assertEqual(self.client.post(url, {"order": "1,2"}).status_code, 302)
        body = self.client.get(reverse("systems:products")).content.decode()
        self.assertNotIn('draggable="true"', body)
        self.login(Role.MANAGER)
        self.assertIn('draggable="true"', self.client.get(reverse("systems:products")).content.decode())

    def test_manager_edits_roles_as_equipment_types(self):
        self.login(Role.MANAGER)
        roles = list(self.step.roles.all())
        data = {"roles-TOTAL_FORMS": "4", "roles-INITIAL_FORMS": "3", "roles-MIN_NUM_FORMS": "0", "roles-MAX_NUM_FORMS": "1000"}
        for i, role in enumerate(roles):
            data.update({f"roles-{i}-id": role.pk, f"roles-{i}-category": role.category_id, f"roles-{i}-is_required": "on"})
        data["roles-2-DELETE"] = "on"                                   # drop the DMM
        data.update({"roles-3-category": self.cart_cat.pk, "roles-3-is_required": "on"})   # a second cart
        response = self.hx(reverse("systems:process_roles", args=[self.step.pk]), "post", data)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(list(self.step.roles.values_list("name", flat=True)), ["Test cart 1", "Fixture", "Test cart 2"])

    def test_role_without_type_is_refused(self):
        self.login(Role.MANAGER)
        data = {"roles-TOTAL_FORMS": "1", "roles-INITIAL_FORMS": "0", "roles-MIN_NUM_FORMS": "0",
                "roles-MAX_NUM_FORMS": "1000", "roles-0-category": "", "roles-0-is_required": ""}
        response = self.hx(reverse("systems:process_roles", args=[self.step.pk]), "post", data)
        self.assertEqual(self.step.roles.count(), 3)
        self.assertEqual(response.status_code, 200)

    def test_viewer_and_technician_limits(self):
        writes = [
            reverse("systems:product_toggle", args=[self.rmmtt01.pk]),
            reverse("systems:process_add", args=[self.rmmtt01.pk]),
            reverse("systems:set_add", args=[self.step.pk]),
            reverse("systems:process_roles", args=[self.step.pk]),
        ]
        self.login(Role.TECHNICIAN)
        for url in writes:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 302)
        self.login(Role.VIEWER)
        self.assertEqual(self.client.post(reverse("systems:set_edit", args=[self.set1.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse("systems:product_delete", args=[self.rmmtt01.pk])).status_code, 302)
        self.assertEqual(self.set1.open_installations().count(), 1)


class AdminScopeTests(TestCase):
    def test_admin_keeps_only_equipment_parts_catalogs_and_users(self):
        registered = {model._meta.label for model in admin.site._registry}
        self.assertEqual(
            registered,
            {
                "core.User", "core.Location", "core.Category", "core.Supplier", "core.Customer",
                "equipment.Equipment", "inventory.InventoryItem", "systems.SystemType",
            },
        )


class IdleProductTests(Fixture, TestCase):
    def test_products_not_in_production_come_last_and_look_different(self):
        self.make_set(self.make_step(product=self.baf0850))
        self.make_set()
        self.baf0850.customer = self.rheem          # same group as the live one
        self.baf0850.save()
        groups = products_overview(show_all=True)
        codes = [row["product"].code for row in groups[0].products]
        self.assertEqual(codes, ["RMMTT01", "BAF0850"])     # live first, idle after

        self.login(Role.VIEWER)
        body = self.client.get(reverse("systems:products"), {"show": "all"}).content.decode()
        self.assertIn("Not in production", body)
        self.assertIn('class="prod-line"', body)                          # idle ones take one line
        self.assertLess(body.index("RMMTT01"), body.index("BAF0850"))
        self.assertIn("All products", body)
        body = self.client.get(reverse("systems:products"), {"show": "production"}).content.decode()
        self.assertNotIn("BAF0850", body)
