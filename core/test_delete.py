"""Deleting assets and spare parts: one at a time, several at once, and from the admin."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from calibration.models import CalibrationRecord
from core.models import Role
from core.tests import BaseFixtureMixin
from equipment.models import Equipment
from inventory.models import InventoryItem, StockTransaction, TransactionType
from maintenance.models import MaintenanceRecord


class DeleteTestBase(BaseFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other = Equipment.objects.create(
            code="DMM-900", name="Bench multimeter", category=cls.category, location=cls.location,
            is_measuring_device=True,
        )
        cls.part = InventoryItem.objects.create(code="PRB-900", name="Probe", unit="pcs")
        cls.part2 = InventoryItem.objects.create(code="PRB-901", name="Probe 2", unit="pcs")

    def add_history(self, asset):
        """Logs that hold their asset with PROTECT."""
        MaintenanceRecord.objects.create(equipment=asset)
        CalibrationRecord.objects.create(equipment=asset)


class SingleDeleteTests(DeleteTestBase):
    def test_an_asset_with_history_can_be_deleted(self):
        # Used to fail: the logs protect the asset row.
        self.add_history(self.other)
        self.login(Role.ADMIN)
        response = self.client.post(reverse("equipment:delete", args=[self.other.pk]))
        self.assertRedirects(response, reverse("equipment:list"))
        self.assertFalse(Equipment.objects.filter(pk=self.other.pk).exists())
        self.assertFalse(MaintenanceRecord.objects.filter(equipment_id=self.other.pk).exists())

    def test_the_delete_button_is_on_show(self):
        self.login(Role.ADMIN)
        page = self.client.get(reverse("equipment:detail", args=[self.equipment.pk]))
        self.assertContains(page, 'class="btn btn-danger" title="Delete asset"')

    def test_only_admins_see_or_use_it(self):
        self.login(Role.MANAGER)
        page = self.client.get(reverse("equipment:detail", args=[self.equipment.pk]))
        self.assertNotContains(page, reverse("equipment:delete", args=[self.equipment.pk]))
        self.client.post(reverse("equipment:delete", args=[self.equipment.pk]))
        self.assertTrue(Equipment.objects.filter(pk=self.equipment.pk).exists())


class BulkDeleteTests(DeleteTestBase):
    def ids(self, *objects):
        return ",".join(str(o.pk) for o in objects)

    def test_list_offers_tick_boxes_to_admins_only(self):
        self.login(Role.ADMIN)
        self.assertContains(self.client.get(reverse("equipment:list")), "data-bulk-all")
        self.assertContains(self.client.get(reverse("inventory:parts")), "data-bulk-all")
        self.login(Role.TECHNICIAN)
        self.assertNotContains(self.client.get(reverse("equipment:list")), "data-bulk")
        self.assertNotContains(self.client.get(reverse("inventory:parts")), "data-bulk")

    def test_confirm_page_names_what_goes(self):
        self.add_history(self.other)
        self.login(Role.ADMIN)
        url = reverse("equipment:bulk_delete") + "?ids=" + self.ids(self.equipment, self.other)
        page = self.client.get(url)
        self.assertContains(page, "Delete 2 assets?")
        self.assertContains(page, "DMM-900")
        self.assertContains(page, "maintenance")
        self.assertEqual(Equipment.objects.count(), 2)      # nothing gone yet

    def test_several_assets_go_in_one_action(self):
        self.add_history(self.other)
        self.login(Role.ADMIN)
        response = self.client.post(reverse("equipment:bulk_delete"),
                                    {"ids": self.ids(self.equipment, self.other)})
        self.assertRedirects(response, reverse("equipment:list"))
        self.assertEqual(Equipment.objects.count(), 0)

    def test_several_parts_go_with_their_movements(self):
        StockTransaction(item=self.part, transaction_type=TransactionType.IN, quantity=Decimal("5")).apply()
        self.login(Role.ADMIN)
        self.client.post(reverse("inventory:part_bulk_delete"), {"ids": self.ids(self.part, self.part2)})
        self.assertFalse(InventoryItem.objects.exists())
        self.assertFalse(StockTransaction.objects.exists())

    def test_non_admins_are_refused(self):
        self.login(Role.MANAGER)
        self.client.post(reverse("equipment:bulk_delete"), {"ids": self.ids(self.equipment)})
        self.assertTrue(Equipment.objects.filter(pk=self.equipment.pk).exists())

    def test_nothing_ticked_goes_back_to_the_list(self):
        self.login(Role.ADMIN)
        self.assertRedirects(self.client.get(reverse("inventory:part_bulk_delete")), reverse("inventory:parts"))


class AdminSiteTests(DeleteTestBase):
    def test_the_administrator_role_can_delete_in_the_admin(self):
        # An Administrator who is not a superuser used to reach the admin site
        # with no permissions at all, so nothing could be deleted there.
        admin_user = self.users[Role.ADMIN]
        self.assertFalse(admin_user.is_superuser)
        self.login(Role.ADMIN)
        response = self.client.post(
            reverse("admin:equipment_equipment_delete", args=[self.other.pk]), {"post": "yes"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Equipment.objects.filter(pk=self.other.pk).exists())

    def test_the_admin_also_deletes_an_asset_with_history(self):
        self.add_history(self.other)
        self.login(Role.ADMIN)
        self.client.post(reverse("admin:equipment_equipment_delete", args=[self.other.pk]), {"post": "yes"})
        self.assertFalse(Equipment.objects.filter(pk=self.other.pk).exists())

    def test_other_roles_still_have_no_admin_site(self):
        self.login(Role.MANAGER)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)

    def test_spare_parts_are_in_the_admin(self):
        self.login(Role.ADMIN)
        self.assertEqual(self.client.get(reverse("admin:inventory_inventoryitem_changelist")).status_code, 200)
        response = self.client.post(
            reverse("admin:inventory_inventoryitem_delete", args=[self.part.pk]), {"post": "yes"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(InventoryItem.objects.filter(pk=self.part.pk).exists())
