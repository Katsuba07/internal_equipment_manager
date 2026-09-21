"""Edit asset / Edit part open in a dialog; the same URLs still work as pages."""

from django.test import TestCase
from django.urls import reverse

from core.models import Role
from core.tests import BaseFixtureMixin
from inventory.models import EquipmentPart, InventoryItem


class EditDialogTests(BaseFixtureMixin, TestCase):
    hx = {"HTTP_HX_REQUEST": "true"}

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.part = InventoryItem.objects.create(code="PRB-100", name="Probe", unit="pcs")

    def asset_data(self, **fields):
        data = {
            "code": self.equipment.code, "name": self.equipment.name,
            "category": self.category.pk, "location": self.location.pk,
            "parts-TOTAL_FORMS": "1", "parts-INITIAL_FORMS": "0",
            "parts-MIN_NUM_FORMS": "0", "parts-MAX_NUM_FORMS": "1000",
            "parts-0-item": self.part.pk, "parts-0-quantity": "12", "parts-0-notes": "",
        }
        data.update(fields)
        return data

    def test_edit_asset_opens_as_a_fragment(self):
        self.login(Role.MANAGER)
        response = self.client.get(reverse("equipment:update", args=[self.equipment.pk]), **self.hx)
        self.assertContains(response, "Edit asset —")
        self.assertContains(response, "parts-TOTAL_FORMS")     # the parts list comes along
        self.assertNotContains(response, "<html")

    def test_saving_in_the_dialog_saves_the_parts_list_too(self):
        self.login(Role.MANAGER)
        response = self.client.post(
            reverse("equipment:update", args=[self.equipment.pk]),
            self.asset_data(name="Renamed fixture"), **self.hx,
        )
        self.assertEqual(response.json(), {"reload": True, "message": ""})
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.name, "Renamed fixture")
        self.assertTrue(EquipmentPart.objects.filter(equipment=self.equipment, item=self.part).exists())

    def test_mistakes_stay_in_the_dialog(self):
        self.login(Role.MANAGER)
        response = self.client.post(
            reverse("equipment:update", args=[self.equipment.pk]), self.asset_data(name=""), **self.hx,
        )
        self.assertContains(response, "Edit asset —")
        self.assertContains(response, "This field is required")
        self.assertNotContains(response, "<html")

    def test_the_page_still_works_on_its_own(self):
        self.login(Role.MANAGER)
        page = self.client.get(reverse("equipment:update", args=[self.equipment.pk]))
        self.assertContains(page, "<html")
        response = self.client.post(reverse("equipment:update", args=[self.equipment.pk]), self.asset_data())
        self.assertRedirects(response, self.equipment.get_absolute_url())

    def test_edit_part_in_the_dialog(self):
        self.login(Role.MANAGER)
        url = reverse("inventory:part_update", args=[self.part.pk])
        self.assertContains(self.client.get(url, **self.hx), "Edit part —")
        response = self.client.post(url, {
            "code": "PRB-100", "name": "Spring probe", "kind": "PROBE", "unit": "pcs",
            "min_quantity": "10", "is_active": "on",
        }, **self.hx)
        self.assertEqual(response.json()["reload"], True)
        self.part.refresh_from_db()
        self.assertEqual(self.part.name, "Spring probe")

    def test_edit_buttons_open_the_dialog(self):
        self.login(Role.MANAGER)
        page = self.client.get(reverse("equipment:detail", args=[self.equipment.pk]))
        self.assertContains(page, f'data-modal-form="{reverse("equipment:update", args=[self.equipment.pk])}"')
        page = self.client.get(reverse("inventory:part_detail", args=[self.part.pk]))
        self.assertContains(page, f'data-modal-form="{reverse("inventory:part_update", args=[self.part.pk])}"')

    def test_technicians_still_cannot_edit(self):
        self.login(Role.TECHNICIAN)
        self.client.post(reverse("equipment:update", args=[self.equipment.pk]),
                         self.asset_data(name="Nope"), **self.hx)
        self.equipment.refresh_from_db()
        self.assertNotEqual(self.equipment.name, "Nope")
