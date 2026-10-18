"""The Recent activity panel and the Activity page."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.activity import recent_activity
from core.models import Role
from core.tests import BaseFixtureMixin
from equipment.models import Equipment, EquipmentStatus
from inventory.models import InventoryItem, StockTransaction, TransactionType


class ActivityTests(BaseFixtureMixin, TestCase):
    def tags(self, **kwargs):
        return [(e["code"], e["tag"]) for e in recent_activity(**kwargs)]

    def test_adding_editing_and_deleting_equipment_all_show(self):
        asset = Equipment.objects.create(code="CTV20200999", name="DMM", category=self.category)
        asset.serial_number = "SN-1"
        asset.save()
        gone = Equipment.objects.create(code="CTV20200998", name="Old", category=self.category)
        gone.delete()
        events = recent_activity()
        tags = [(e["code"], e["tag"]) for e in events]
        for expected in [("CTV20200999", "Added"), ("CTV20200999", "Edited"), ("CTV20200998", "Deleted")]:
            self.assertIn(expected, tags)
        edited = next(e for e in events if e["tag"] == "Edited")
        self.assertIn("Serial", edited["text"])                              # says what changed
        deleted = next(e for e in events if e["tag"] == "Deleted")
        self.assertIsNone(deleted["url"])                                    # nothing to open

    def test_a_status_change_is_not_shown_twice(self):
        self.equipment.change_status(EquipmentStatus.BROKEN, self.users[Role.TECHNICIAN], "broken pin")
        tags = [tag for code, tag in self.tags() if code == "ICT-FIX-001"]
        self.assertNotIn("Edited", tags)
        self.assertEqual(len(tags), 2)                                       # added + the status change

    def test_stock_movements_show_with_where_the_part_went(self):
        part = InventoryItem.objects.create(code="PRB-01", name="Probe", quantity_on_hand=Decimal("5"))
        StockTransaction(item=part, transaction_type=TransactionType.OUT, quantity=Decimal("2"),
                         equipment=self.equipment, performed_by=self.users[Role.TECHNICIAN]).apply()
        events = [e for e in recent_activity() if e["code"] == "PRB-01"]
        self.assertEqual([e["tag"] for e in events], ["Issued", "Added"])  # the balance edit stays quiet
        self.assertIn("to ICT-FIX-001", events[0]["text"])
        self.assertIn("balance 3", events[0]["text"])

    def test_the_overview_lists_more_than_a_handful(self):
        for n in range(20):
            Equipment.objects.create(code=f"CTV2020{n:04d}", name="Item", category=self.category)
        self.login(Role.VIEWER)
        body = self.client.get(reverse("dashboard")).content.decode()
        self.assertEqual(sum(body.count(f"CTV2020{n:04d}") > 0 for n in range(20)), 20)
        self.assertIn(reverse("activity"), body)

    def test_the_activity_page_filters_by_kind(self):
        InventoryItem.objects.create(code="PRB-02", name="Probe")
        self.login(Role.VIEWER)
        body = self.client.get(reverse("activity"), {"kind": "part"}).content.decode()
        self.assertIn("PRB-02", body)
        self.assertNotIn("ICT-FIX-001", body)
        body = self.client.get(reverse("activity")).content.decode()
        self.assertIn("PRB-02", body)
        self.assertIn("ICT-FIX-001", body)
