"""Parts lists on equipment, the spare parts screens, and parts per run."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Product, Role
from core.tests import BaseFixtureMixin
from equipment.models import Equipment
from inventory.models import EquipmentPart, InventoryItem, StockTransaction, TransactionType


class PartsTestBase(BaseFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.probe = InventoryItem.objects.create(code="PRB-100-3A", name="Spring probe", unit="pcs")
        cls.spring = InventoryItem.objects.create(code="FIX-SPR-25", name="Spring 25 N", unit="pcs")

    def asset_data(self, rows, existing=0, **fields):
        """POST data for the asset form plus its parts formset."""
        data = {
            "code": "FIX-NEW-001", "name": "New fixture",
            "category": self.category.pk, "location": self.location.pk,
            "parts-TOTAL_FORMS": str(len(rows)), "parts-INITIAL_FORMS": str(existing),
            "parts-MIN_NUM_FORMS": "0", "parts-MAX_NUM_FORMS": "1000",
        }
        data.update(fields)
        for i, row in enumerate(rows):
            for key, value in row.items():
                data[f"parts-{i}-{key}"] = value
        return data


class EquipmentPartModelTests(PartsTestBase):
    def test_one_line_per_part_per_asset(self):
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=10)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=5)

    def test_quantity_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=0)

    def test_deleting_part_removes_its_lines_and_movements_in_one_go(self):
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=10)
        StockTransaction(item=self.probe, transaction_type=TransactionType.IN, quantity=5).apply()
        self.probe.delete()
        self.assertFalse(EquipmentPart.objects.exists())
        self.assertFalse(StockTransaction.objects.exists())
        self.assertTrue(Equipment.objects.filter(pk=self.equipment.pk).exists())


class EquipmentFormPartsTests(PartsTestBase):
    def test_create_asset_with_parts_and_quantities(self):
        self.login(Role.MANAGER)
        response = self.client.post(reverse("equipment:create"), self.asset_data([
            {"item": self.probe.pk, "quantity": "120", "notes": "Top plate"},
            {"item": self.spring.pk, "quantity": "4"},
            {"item": "", "quantity": "1"},  # untouched extra row is ignored
        ]))
        self.assertEqual(response.status_code, 302)
        asset = Equipment.objects.get(code="FIX-NEW-001")
        lines = {line.item.code: line.quantity for line in asset.parts.all()}
        self.assertEqual(lines, {"PRB-100-3A": Decimal("120"), "FIX-SPR-25": Decimal("4")})

    def test_same_part_twice_is_refused(self):
        self.login(Role.MANAGER)
        response = self.client.post(reverse("equipment:create"), self.asset_data([
            {"item": self.probe.pk, "quantity": "10"},
            {"item": self.probe.pk, "quantity": "5"},
        ]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "listed twice")
        self.assertFalse(Equipment.objects.filter(code="FIX-NEW-001").exists())

    def test_edit_changes_and_removes_parts(self):
        line = EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=10)
        self.login(Role.MANAGER)
        url = reverse("equipment:update", args=[self.equipment.pk])
        data = self.asset_data(
            [{"id": line.pk, "item": self.probe.pk, "quantity": "12"}],
            existing=1, code=self.equipment.code, name=self.equipment.name,
        )
        self.assertEqual(self.client.post(url, data).status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.quantity, Decimal("12"))

        data["parts-0-DELETE"] = "on"
        self.client.post(url, data)
        self.assertFalse(EquipmentPart.objects.exists())

    def test_asset_page_lists_its_parts(self):
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=356)
        self.login(Role.VIEWER)
        response = self.client.get(reverse("equipment:detail", args=[self.equipment.pk]))
        self.assertContains(response, "PRB-100-3A")
        self.assertContains(response, "356")


class PartScreensTests(PartsTestBase):
    def test_pages_render(self):
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=10)
        self.login(Role.ADMIN)
        for url in [
            reverse("inventory:parts"),
            reverse("inventory:parts") + "?low=1&kind=PROBE&q=prb&inactive=1",
            reverse("inventory:part_detail", args=[self.probe.pk]),
            reverse("inventory:part_create"),
            reverse("inventory:part_update", args=[self.probe.pk]),
            reverse("inventory:part_stock", args=[self.probe.pk]),
            reverse("inventory:part_delete", args=[self.probe.pk]),
            reverse("equipment:create"),
            reverse("equipment:update", args=[self.equipment.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_detail_shows_where_used(self):
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=10)
        self.login(Role.VIEWER)
        response = self.client.get(reverse("inventory:part_detail", args=[self.probe.pk]))
        self.assertContains(response, "ICT-FIX-001")

    def test_create_with_opening_stock(self):
        self.login(Role.MANAGER)
        self.client.post(reverse("inventory:part_create"), {
            "code": "prb-050-1a", "name": "Probe 50 mil", "kind": "PROBE", "unit": "pcs",
            "min_quantity": "10", "is_active": "on", "opening_stock": "250",
        })
        part = InventoryItem.objects.get(code="PRB-050-1A")
        self.assertEqual(part.quantity_on_hand, Decimal("250"))
        self.assertEqual(part.transactions.count(), 1)

    def test_issue_more_than_on_hand_is_refused(self):
        self.login(Role.TECHNICIAN)
        response = self.client.post(reverse("inventory:part_stock", args=[self.probe.pk]), {
            "transaction_type": "OUT", "quantity": "5", "reason": "x",
            "equipment": self.equipment.pk,
        })
        self.assertContains(response, "Not enough stock")

    def test_receive_then_issue(self):
        self.login(Role.TECHNICIAN)
        url = reverse("inventory:part_stock", args=[self.probe.pk])
        self.client.post(url, {"transaction_type": "IN", "quantity": "50"})
        self.client.post(url, {
            "transaction_type": "OUT", "quantity": "8", "reason": "Fixture rework",
            "equipment": self.equipment.pk,
        })
        self.probe.refresh_from_db()
        self.assertEqual(self.probe.quantity_on_hand, Decimal("42"))

    def test_viewer_cannot_write(self):
        self.login(Role.VIEWER)
        for url in [
            reverse("inventory:part_create"),
            reverse("inventory:part_update", args=[self.probe.pk]),
            reverse("inventory:part_stock", args=[self.probe.pk]),
            reverse("inventory:part_delete", args=[self.probe.pk]),
        ]:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (302, 403))

    def test_one_click_delete(self):
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=10)
        self.login(Role.ADMIN)
        response = self.client.post(reverse("inventory:part_delete", args=[self.probe.pk]))
        self.assertRedirects(response, reverse("inventory:parts"))
        self.assertFalse(InventoryItem.objects.filter(pk=self.probe.pk).exists())
        self.assertTrue(Equipment.objects.filter(pk=self.equipment.pk).exists())


class PartStatusColumnTests(PartsTestBase):
    def test_status_tags_follow_stock_level(self):
        self.probe.min_quantity = 10
        self.probe.save()
        cases = [(Decimal("0"), True, "Out of stock"), (Decimal("5"), True, "Low stock"),
                 (Decimal("50"), True, "In stock"), (Decimal("50"), False, "Inactive")]
        for qty, active, label in cases:
            with self.subTest(label=label):
                self.probe.quantity_on_hand, self.probe.is_active = qty, active
                self.assertEqual(self.probe.stock_status[0], label)

    def test_list_shows_status_column_not_cell_highlight(self):
        self.login(Role.VIEWER)
        body = self.client.get(reverse("inventory:parts") + "?inactive=1").content.decode()
        self.assertIn("<th>Status</th>", body)
        self.assertIn("Out of stock", body)          # both demo parts start at zero
        self.assertNotIn("cell-danger", body)


class PreviewDrawerTests(PartsTestBase):
    def test_equipment_preview(self):
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=12)
        self.login(Role.VIEWER)
        url = reverse("equipment:preview", args=[self.equipment.pk])
        body = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("ICT-FIX-001", body)
        self.assertIn("PRB-100-3A", body)
        self.assertNotIn("<html", body)
        self.assertRedirects(self.client.get(url), self.equipment.get_absolute_url())
        listing = self.client.get(reverse("equipment:list")).content.decode()
        self.assertIn(f'data-preview-url="{url}"', listing)
        self.assertIn('id="preview"', listing)

    def test_part_preview(self):
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=12)
        self.login(Role.VIEWER)
        url = reverse("inventory:part_preview", args=[self.probe.pk])
        body = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("PRB-100-3A", body)
        self.assertIn("ICT-FIX-001", body)
        self.assertNotIn("Receive", body)                 # viewers get no stock buttons
        self.assertRedirects(self.client.get(url), self.probe.get_absolute_url())
        listing = self.client.get(reverse("inventory:parts")).content.decode()
        self.assertIn(f'data-preview-url="{url}"', listing)
        self.assertIn('id="preview"', listing)          # the drawer itself is on the page


class IssueTargetTests(PartsTestBase):
    """An issue must say which asset the part is going on."""

    def setUp(self):
        super().setUp()
        StockTransaction(
            item=self.probe, transaction_type=TransactionType.IN, quantity=Decimal("100")
        ).apply()
        self.probe.refresh_from_db()

    def issue(self, **extra):
        data = {"transaction_type": "OUT", "quantity": "5", "reason": "Rework"}
        data.update(extra)
        return self.client.post(
            reverse("inventory:part_stock", args=[self.probe.pk]), data
        )

    def test_issue_without_an_asset_is_refused_and_stock_is_untouched(self):
        self.login(Role.TECHNICIAN)
        response = self.issue()
        self.assertContains(response, "Choose the asset this part is going to.")
        self.probe.refresh_from_db()
        self.assertEqual(self.probe.quantity_on_hand, Decimal("100"))

    def test_issue_records_the_asset(self):
        self.login(Role.TECHNICIAN)
        self.issue(equipment=self.equipment.pk)
        movement = StockTransaction.objects.filter(transaction_type="OUT").get()
        self.assertEqual(movement.equipment, self.equipment)
        self.probe.refresh_from_db()
        self.assertEqual(self.probe.quantity_on_hand, Decimal("95"))

    def test_a_receipt_keeps_no_destination(self):
        self.login(Role.TECHNICIAN)
        self.client.post(reverse("inventory:part_stock", args=[self.probe.pk]), {
            "transaction_type": "IN", "quantity": "5", "equipment": self.equipment.pk,
        })
        movement = StockTransaction.objects.filter(transaction_type="IN").latest("created_at")
        self.assertIsNone(movement.equipment)

    def test_the_form_is_a_search_box_not_a_dropdown(self):
        self.login(Role.TECHNICIAN)
        page = self.client.get(reverse("inventory:part_stock", args=[self.probe.pk]) + "?type=OUT")
        self.assertContains(page, "data-picker")
        self.assertContains(page, f"part={self.probe.pk}")
        self.assertNotContains(page, '<select name="equipment"')

    def test_both_pages_show_where_the_part_went(self):
        self.login(Role.TECHNICIAN)
        self.issue(equipment=self.equipment.pk)
        part_page = self.client.get(reverse("inventory:part_detail", args=[self.probe.pk]))
        self.assertContains(part_page, "Issued to")
        self.assertContains(part_page, self.equipment.code)
        asset_page = self.client.get(reverse("equipment:detail", args=[self.equipment.pk]))
        self.assertContains(asset_page, "Parts issued to this asset")
        self.assertContains(asset_page, self.probe.code)


class MovementEditDeleteTests(PartsTestBase):
    """Correcting a mis-entered movement or a wrong stocktake."""

    def setUp(self):
        super().setUp()
        self.receipt = StockTransaction(
            item=self.probe, transaction_type=TransactionType.IN, quantity=Decimal("10"),
        ).apply()
        self.issue = StockTransaction(
            item=self.probe, transaction_type=TransactionType.OUT, quantity=Decimal("4"),
            equipment=self.equipment,
        ).apply()  # balance now 6

    def test_manager_can_backdate_a_movement(self):
        """Needed to backfill history, e.g. syncing an old paper log."""
        self.login(Role.MANAGER)
        url = reverse("inventory:movement_edit", args=[self.receipt.pk])
        response = self.client.post(url, {
            "transaction_type": "IN", "quantity": "10", "occurred_at": "2020-01-15",
        })
        self.assertRedirects(response, self.probe.get_absolute_url())
        self.receipt.refresh_from_db()
        self.assertEqual(timezone.localtime(self.receipt.occurred_at).date().isoformat(), "2020-01-15")

    def test_leaving_the_date_blank_keeps_it_at_now(self):
        self.login(Role.TECHNICIAN)
        url = reverse("inventory:part_stock", args=[self.probe.pk])
        self.client.post(url, {"transaction_type": "IN", "quantity": "5"})
        newest = StockTransaction.objects.filter(item=self.probe, transaction_type="IN").latest("created_at")
        self.assertAlmostEqual(
            newest.occurred_at.timestamp(), timezone.now().timestamp(), delta=5
        )

    def test_manager_can_fix_a_mis_entered_quantity(self):
        self.login(Role.MANAGER)
        url = reverse("inventory:movement_edit", args=[self.issue.pk])
        response = self.client.post(url, {
            "transaction_type": "OUT", "quantity": "1", "equipment": self.equipment.pk,
        })
        self.assertRedirects(response, self.probe.get_absolute_url())
        self.issue.refresh_from_db()
        self.probe.refresh_from_db()
        self.assertEqual(self.issue.quantity, Decimal("1"))
        self.assertEqual(self.issue.quantity_after, Decimal("9"))
        self.assertEqual(self.probe.quantity_on_hand, Decimal("9"))

    def test_fixing_a_stocktake_updates_on_hand(self):
        self.login(Role.MANAGER)
        adjust = StockTransaction(
            item=self.probe, transaction_type=TransactionType.ADJUST, quantity=Decimal("6"),
            reason="Month-end count",
        ).apply()
        url = reverse("inventory:movement_edit", args=[adjust.pk])
        response = self.client.post(url, {"transaction_type": "ADJUST", "quantity": "9"})
        self.assertRedirects(response, self.probe.get_absolute_url())
        self.probe.refresh_from_db()
        self.assertEqual(self.probe.quantity_on_hand, Decimal("9"))

    def test_technician_and_viewer_cannot_edit(self):
        url = reverse("inventory:movement_edit", args=[self.issue.pk])
        for role in (Role.TECHNICIAN, Role.VIEWER):
            with self.subTest(role=role):
                self.login(role)
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_admin_can_delete_a_movement(self):
        self.login(Role.ADMIN)
        url = reverse("inventory:movement_delete", args=[self.issue.pk])
        response = self.client.post(url)
        self.assertRedirects(response, self.probe.get_absolute_url())
        self.assertFalse(StockTransaction.objects.filter(pk=self.issue.pk).exists())
        self.probe.refresh_from_db()
        self.assertEqual(self.probe.quantity_on_hand, Decimal("10"))

    def test_manager_cannot_delete_only_admin_can(self):
        self.login(Role.MANAGER)
        url = reverse("inventory:movement_delete", args=[self.issue.pk])
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_deleting_a_movement_that_would_go_negative_is_refused(self):
        self.login(Role.ADMIN)
        response = self.client.post(
            reverse("inventory:movement_delete", args=[self.receipt.pk])
        )
        self.assertRedirects(response, self.probe.get_absolute_url())
        # The delete must not have gone through.
        self.assertTrue(StockTransaction.objects.filter(pk=self.receipt.pk).exists())
        self.probe.refresh_from_db()
        self.assertEqual(self.probe.quantity_on_hand, Decimal("6"))


class EquipmentSearchTests(PartsTestBase):
    """The type-ahead behind the picker."""

    def setUp(self):
        super().setUp()
        self.url = reverse("equipment:search")
        EquipmentPart.objects.create(equipment=self.equipment, item=self.probe, quantity=10)
        self.other = Equipment.objects.create(
            code="DMM-999", name="Bench multimeter",
            category=self.category, location=self.location,
        )

    def results(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return response.json()["results"]

    def test_with_nothing_typed_it_offers_the_assets_that_use_the_part(self):
        self.login(Role.TECHNICIAN)
        rows = self.results(part=self.probe.pk)
        self.assertEqual([row["code"] for row in rows], [self.equipment.code])
        self.assertTrue(rows[0]["on_list"])

    def test_typing_searches_every_asset_with_the_listed_ones_first(self):
        self.login(Role.TECHNICIAN)
        self.assertEqual([row["code"] for row in self.results(q="DMM-9")], ["DMM-999"])
        rows = self.results(q="", part=self.probe.pk)
        self.assertEqual(len(rows), 1)
        rows = self.results(q="-", part=self.probe.pk)
        self.assertEqual(rows[0]["code"], self.equipment.code)   # on the parts list, so first
        self.assertIn("DMM-999", [row["code"] for row in rows])

    def test_retired_assets_are_not_offered(self):
        self.login(Role.TECHNICIAN)
        Equipment.objects.filter(pk=self.other.pk).update(status="RETIRED")
        self.assertNotIn("DMM-999", [row["code"] for row in self.results(q="DMM")])

    def test_signing_in_is_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
