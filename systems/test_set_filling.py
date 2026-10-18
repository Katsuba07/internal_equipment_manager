"""Filling a model's set on its station with search boxes — within a technician's reach."""

from django.test import TestCase
from django.urls import reverse

from core.models import Product, Role
from systems.models import Installation, TestSet
from systems.tests import Fixture


class SetFillingTests(Fixture, TestCase):
    hx = {"HTTP_HX_REQUEST": "true"}

    def setUp(self):
        self.step = self.make_step()
        self.set1 = self.make_set(self.step)
        self.station = self.set1.station

    def editor(self, test_set=None):
        test_set = test_set or self.set1
        return reverse("systems:station_model_edit", args=[test_set.station_id, test_set.pk])

    def test_the_station_editor_offers_each_slot_its_own_kind(self):
        self.login(Role.TECHNICIAN)
        page = self.client.get(self.editor()).content.decode()
        self.assertIn("data-picker", page)
        self.assertIn(f"category={self.cart_cat.pk}", page)        # each box offers its own kind

    def test_search_offers_only_the_role_s_kind_and_marks_busy_machines(self):
        Installation.fit(self.dmm1, self.set1, self.role(self.set1, "DMM"), self.users[Role.MANAGER])
        set2 = TestSet.objects.create(product_process=self.step, number=2)
        self.login(Role.TECHNICIAN)
        rows = self.client.get(reverse("equipment:search"),
                               {"category": self.dmm_cat.pk, "set": set2.pk}).json()["results"]
        codes = [r["code"] for r in rows]
        self.assertEqual(sorted(codes), ["DMM-001", "DMM-002"])        # multimeters only
        self.assertEqual(codes[0], "DMM-002")                           # the free one first
        busy = {r["code"]: r["busy"] for r in rows}
        self.assertIn("#1", busy["DMM-001"])
        self.assertEqual(busy["DMM-002"], "")

    def test_search_finds_a_machine_by_asset_no_or_serial(self):
        self.dmm2.asset_no, self.dmm2.serial_number = "103220100359", "41415453WS"
        self.dmm2.save()
        self.login(Role.TECHNICIAN)
        for typed in ("1032201003", "41415453"):
            rows = self.client.get(reverse("equipment:search"), {"q": typed}).json()["results"]
            self.assertEqual([r["code"] for r in rows], ["DMM-002"])

    def test_a_technician_saves_the_model_s_machines(self):
        self.login(Role.TECHNICIAN)
        role = self.role(self.set1, "DMM")
        response = self.client.post(self.editor(), {f"slot_{role.pk}": self.dmm2.pk})
        self.assertRedirects(response, reverse("systems:station_detail", args=[self.station.pk]), fetch_redirect_response=False)
        self.assertTrue(self.set1.open_installations().filter(component=self.dmm2).exists())

    def test_one_machine_in_two_slots_is_refused(self):
        from systems.models import StationSlot

        StationSlot.objects.create(station=self.station, category=self.dmm_cat, position=9)
        slots = list(self.station.slots.filter(category=self.dmm_cat))
        self.login(Role.MANAGER)
        response = self.client.post(self.editor(), {f"slot_{s.pk}": self.dmm1.pk for s in slots})
        self.assertContains(response, "The same asset is chosen for two slots")
        self.assertFalse(self.set1.open_installations().exists())

    def test_a_viewer_cannot_change_machines(self):
        self.login(Role.VIEWER)
        role = self.role(self.set1, "DMM")
        self.client.post(self.editor(), {f"slot_{role.pk}": self.dmm2.pk})
        self.assertFalse(self.set1.open_installations().exists())

    def test_the_products_page_shows_machines_but_does_not_choose_them(self):
        Installation.fit(self.dmm1, self.set1, self.role(self.set1, "DMM"), self.users[Role.MANAGER])
        self.login(Role.MANAGER)
        panel = self.client.get(reverse("systems:process_panel", args=[self.step.pk]), **self.hx).content.decode()
        self.assertIn("DMM-001", panel)
        self.assertIn(self.station.code, panel)
        self.assertNotIn("data-picker", panel)
        self.assertIn(self.editor(), panel)

    def test_a_product_needs_no_name(self):
        self.login(Role.MANAGER)
        self.client.post(reverse("systems:product_create"),
                         {"code": "BAF1950", "customer": self.baf.pk, "is_active": "on"}, **self.hx)
        product = Product.objects.get(code="BAF1950")
        self.assertEqual(product.name, "")
        panel = self.client.get(reverse("systems:product_panel", args=[product.pk]), **self.hx).content.decode()
        self.assertNotIn("BAF · ", panel)
