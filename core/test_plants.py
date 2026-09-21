"""Plants (CTV1/CTV2/CTVN), scheduled maintenance on an asset, and the dashboard numbers."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Location, Plant, Role
from core.tests import BaseFixtureMixin
from equipment.models import Equipment
from inventory.models import InventoryItem


class PlantTests(BaseFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.location.plant = Plant.CTV2
        cls.location.save()
        cls.smt = Location.objects.create(code="SMT-L1", name="SMT Line 1", plant=Plant.CTV1)
        cls.other = Equipment.objects.create(
            code="CART-900", name="Cart", category=cls.category, location=cls.smt
        )
        cls.part = InventoryItem.objects.create(code="PRB-9", name="Probe", plant=Plant.CTV1)

    def test_an_asset_takes_the_plant_of_its_location(self):
        # Giving the location a plant moved the asset already standing there.
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.plant, "CTV2")
        self.assertEqual(self.other.plant, "CTV1")
        self.other.location = self.location
        self.other.save()
        self.assertEqual(self.other.plant, "CTV2")

    def test_the_plant_stays_when_the_location_is_cleared(self):
        self.other.location = None
        self.other.save()
        self.other.refresh_from_db()
        self.assertEqual(self.other.plant, "CTV1")
        self.login(Role.VIEWER)
        page = self.client.get(reverse("equipment:detail", args=[self.other.pk]))
        self.assertContains(page, "Not set")
        listing = self.client.get(reverse("equipment:list") + "?plant=CTV1")
        self.assertContains(listing, "CART-900")

    def test_equipment_list_filters_and_shows_the_plant(self):
        self.login(Role.VIEWER)
        body = self.client.get(reverse("equipment:list")).content.decode()
        self.assertIn("Plant", body)
        filtered = self.client.get(reverse("equipment:list"), {"plant": "CTV1"}).content.decode()
        self.assertIn("CART-900", filtered)
        self.assertNotIn("ICT-FIX-001", filtered)

    def test_parts_list_filters_by_plant(self):
        InventoryItem.objects.create(code="PRB-2", name="Other probe", plant=Plant.CTVN)
        self.login(Role.VIEWER)
        filtered = self.client.get(reverse("inventory:parts"), {"plant": "CTV1"}).content.decode()
        self.assertIn("PRB-9", filtered)
        self.assertNotIn("PRB-2", filtered)

    def test_products_page_filters_by_the_plant_of_the_product(self):
        from core.models import Product

        Product.objects.create(code="PONE01", in_production=True, plant="CTV1")
        Product.objects.create(code="PTWO02", in_production=True)
        self.assertEqual(Product.objects.get(code="PTWO02").plant, "CTV2")      # the default
        self.login(Role.VIEWER)
        body = self.client.get(reverse("systems:products"), {"plant": "CTV1"}).content.decode()
        self.assertIn("PONE01", body)
        self.assertNotIn("PTWO02", body)
        body = self.client.get(reverse("systems:products"), {"plant": "CTV2"}).content.decode()
        self.assertNotIn("PONE01", body)
        self.assertIn("PTWO02", body)


class ScheduledMaintenanceTests(BaseFixtureMixin, TestCase):
    def asset_data(self, **extra):
        data = {
            "code": self.equipment.code, "name": self.equipment.name,
            "category": self.category.pk, "location": self.location.pk,
            "parts-TOTAL_FORMS": "0", "parts-INITIAL_FORMS": "0",
        }
        data.update(extra)
        return data

    def test_tick_and_interval_create_a_plan(self):
        self.login(Role.MANAGER)
        self.client.post(
            reverse("equipment:update", args=[self.equipment.pk]),
            self.asset_data(maintenance_required="on", maintenance_interval_days="30"),
        )
        plan = self.equipment.maintenance_plans.get()
        self.assertEqual((plan.name, plan.interval_days, plan.is_active), ("Scheduled maintenance", 30, True))
        self.assertEqual(plan.next_due_at, timezone.localdate() + timedelta(days=30))

    def test_changing_the_interval_moves_the_next_date(self):
        self.equipment.maintenance_required = True
        self.equipment.maintenance_interval_days = 7
        self.equipment.save()
        self.equipment.sync_maintenance_plan()
        self.equipment.maintenance_interval_days = 365
        self.equipment.save()
        plan = self.equipment.sync_maintenance_plan()
        self.assertEqual(plan.interval_days, 365)
        self.assertEqual(plan.next_due_at, timezone.localdate() + timedelta(days=365))

    def test_unticking_stops_the_round_but_keeps_the_plan(self):
        self.equipment.maintenance_required = True
        self.equipment.maintenance_interval_days = 30
        self.equipment.save()
        self.equipment.sync_maintenance_plan()
        self.equipment.maintenance_required = False
        self.equipment.save()
        plan = self.equipment.sync_maintenance_plan()
        self.assertFalse(plan.is_active)
        self.assertEqual(self.equipment.maintenance_plans.count(), 1)

    def test_interval_is_required_when_ticked(self):
        self.login(Role.MANAGER)
        response = self.client.post(
            reverse("equipment:update", args=[self.equipment.pk]),
            self.asset_data(maintenance_required="on"),
        )
        self.assertContains(response, "Choose how often")
        self.assertFalse(self.equipment.maintenance_plans.exists())


class DashboardNumbersTests(BaseFixtureMixin, TestCase):
    def test_tiles_show_equipment_and_parts_figures(self):
        self.location.plant = Plant.CTV2
        self.location.save()
        InventoryItem.objects.create(code="P-1", name="Part", plant=Plant.CTV2, unit_price=10, quantity_on_hand=3)
        InventoryItem.objects.create(code="P-2", name="Empty", plant=Plant.CTV2, min_quantity=5)
        self.login(Role.VIEWER)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["part_count"], 2)
        self.assertEqual(response.context["out_of_stock_count"], 1)
        plants = {row["code"]: row["assets"] for row in response.context["plants"]}
        self.assertEqual(plants["CTV2"], 1)
        body = response.content.decode()
        self.assertIn("Spare parts", body)
        self.assertIn("By plant:", body)
        # Trimmed in 0.7.1: the fleet bar, the stock value and the due table are gone.
        for dropped in ("Fleet", "Stock value", "Falls due"):
            self.assertNotIn(dropped, body)


class ModalFormTests(BaseFixtureMixin, TestCase):
    """Change status, receive and issue open in a dialog instead of a page."""

    hx = {"HTTP_HX_REQUEST": "true"}

    def setUp(self):
        self.part = InventoryItem.objects.create(code="PRB-5", name="Probe", unit="pcs")

    def test_status_change_opens_as_a_fragment_and_saves(self):
        self.login(Role.TECHNICIAN)
        url = reverse("equipment:status_change", args=[self.equipment.pk])
        fragment = self.client.get(url, **self.hx).content.decode()
        self.assertIn("Change status", fragment)
        self.assertNotIn("<html", fragment)
        response = self.client.post(url, {"status": "DOWN", "reason": "Broken probe plate"}, **self.hx)
        self.assertEqual(response.json(), {"reload": True, "message": ""})
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "DOWN")

    def test_status_change_errors_come_back_as_the_form(self):
        # In production cannot be picked for an asset not fitted to a running product.
        self.login(Role.TECHNICIAN)
        self.equipment.change_status("DOWN", None)
        url = reverse("equipment:status_change", args=[self.equipment.pk])
        response = self.client.post(url, {"status": "IN_PRODUCTION"}, **self.hx)
        self.assertEqual(response["Content-Type"].split(";")[0], "text/html")
        self.assertContains(response, "Select a valid choice")
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "DOWN")

    def test_a_reason_is_optional(self):
        self.login(Role.TECHNICIAN)
        url = reverse("equipment:status_change", args=[self.equipment.pk])
        response = self.client.post(url, {"status": "REPAIR"}, **self.hx)
        self.assertEqual(response.json()["reload"], True)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "REPAIR")

    def test_receive_and_issue_in_the_dialog(self):
        self.login(Role.TECHNICIAN)
        url = reverse("inventory:part_stock", args=[self.part.pk])
        self.assertContains(self.client.get(url + "?type=IN", **self.hx), "Receive —")
        self.assertContains(self.client.get(url + "?type=OUT", **self.hx), "Issue —")
        self.client.post(url + "?type=IN", {"transaction_type": "IN", "quantity": "40"}, **self.hx)
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_on_hand, 40)
        refused = self.client.post(url + "?type=OUT", {
            "transaction_type": "OUT", "quantity": "99", "equipment": self.equipment.pk,
        }, **self.hx)
        self.assertContains(refused, "Not enough stock")
        self.client.post(url + "?type=OUT", {
            "transaction_type": "OUT", "quantity": "10", "equipment": self.equipment.pk,
        }, **self.hx)
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_on_hand, 30)

    def test_the_same_urls_still_work_as_full_pages(self):
        self.login(Role.TECHNICIAN)
        page = self.client.get(reverse("equipment:status_change", args=[self.equipment.pk]))
        self.assertContains(page, "<html")
        response = self.client.post(
            reverse("inventory:part_stock", args=[self.part.pk]),
            {"transaction_type": "IN", "quantity": "5"},
        )
        self.assertRedirects(response, self.part.get_absolute_url())

    def test_buttons_carry_the_dialog_url(self):
        self.login(Role.TECHNICIAN)
        asset_page = self.client.get(self.equipment.get_absolute_url()).content.decode()
        self.assertIn('data-modal-form="/equipment/%d/status/"' % self.equipment.pk, asset_page)
        part_page = self.client.get(self.part.get_absolute_url()).content.decode()
        self.assertIn("data-modal-form=", part_page)
