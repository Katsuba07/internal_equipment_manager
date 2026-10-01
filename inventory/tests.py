"""Stock tests: the balance must always match the movement history."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import Role, User
from inventory.models import InventoryItem, StockTransaction, TransactionType


class StockTransactionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="storeman", password="x", full_name="Duy Le", role=Role.TECHNICIAN
        )

    def setUp(self):
        self.item = InventoryItem.objects.create(
            code="PRB-100-3A",
            name="Spring probe 100 mil, 3 A",
            unit="pcs",
            min_quantity=Decimal("5"),
        )

    def receive(self, quantity):
        return StockTransaction(
            item=self.item,
            transaction_type=TransactionType.IN,
            quantity=Decimal(quantity),
            performed_by=self.user,
        ).apply()

    def test_receiving_increases_stock(self):
        self.receive(10)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_on_hand, Decimal("10"))

    def test_issuing_decreases_stock(self):
        self.receive(10)
        StockTransaction(
            item=self.item,
            transaction_type=TransactionType.OUT,
            quantity=Decimal("3"),
            performed_by=self.user,
        ).apply()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_on_hand, Decimal("7"))

    def test_cannot_issue_more_than_available(self):
        self.receive(2)
        movement = StockTransaction(
            item=self.item,
            transaction_type=TransactionType.OUT,
            quantity=Decimal("5"),
            performed_by=self.user,
        )
        with self.assertRaises(ValidationError):
            movement.apply()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_on_hand, Decimal("2"))
        # A failed movement must not leave a stray row behind.
        self.assertEqual(self.item.transactions.count(), 1)

    def test_stocktake_sets_absolute_quantity(self):
        self.receive(10)
        StockTransaction(
            item=self.item,
            transaction_type=TransactionType.ADJUST,
            quantity=Decimal("8"),
            performed_by=self.user,
            reason="Month-end count",
        ).apply()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_on_hand, Decimal("8"))

    def test_quantity_after_is_recorded_on_each_movement(self):
        """This column is what makes the balance at any past date readable."""
        self.receive(10)
        StockTransaction(
            item=self.item,
            transaction_type=TransactionType.OUT,
            quantity=Decimal("4"),
            performed_by=self.user,
        ).apply()

        history = list(self.item.transactions.order_by("created_at"))
        self.assertEqual(history[0].quantity_after, Decimal("10"))
        self.assertEqual(history[1].quantity_after, Decimal("6"))

    def test_below_minimum_detection(self):
        self.receive(4)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_below_minimum)
        self.assertIn(self.item, InventoryItem.objects.below_minimum())

        self.receive(10)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_below_minimum)
        self.assertNotIn(self.item, InventoryItem.objects.below_minimum())

    def test_negative_quantity_is_rejected_by_validation(self):
        movement = StockTransaction(
            item=self.item, transaction_type=TransactionType.IN, quantity=Decimal("-5")
        )
        with self.assertRaises(ValidationError):
            movement.full_clean()


class StockTransactionRecalculateTests(TestCase):
    """Editing or deleting a past movement must not let the ledger drift."""

    def setUp(self):
        self.item = InventoryItem.objects.create(
            code="PRB-100-3A", name="Spring probe", unit="pcs",
        )

    def receive(self, quantity):
        return StockTransaction(
            item=self.item, transaction_type=TransactionType.IN, quantity=Decimal(quantity),
        ).apply()

    def issue(self, quantity):
        return StockTransaction(
            item=self.item, transaction_type=TransactionType.OUT, quantity=Decimal(quantity),
        ).apply()

    def test_editing_an_earlier_quantity_updates_every_later_balance(self):
        first = self.receive(10)
        second = self.issue(4)  # balance now 6

        first.quantity = Decimal("20")
        first.save()
        StockTransaction.recalculate(self.item.pk)

        first.refresh_from_db()
        second.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(first.quantity_after, Decimal("20"))
        self.assertEqual(second.quantity_after, Decimal("16"))
        self.assertEqual(self.item.quantity_on_hand, Decimal("16"))

    def test_deleting_a_movement_rebuilds_the_balance_from_what_remains(self):
        self.receive(10)
        second = self.issue(4)  # balance now 6
        self.receive(5)  # balance 11

        second.delete()
        StockTransaction.recalculate(self.item.pk)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_on_hand, Decimal("15"))

    def test_recalculate_refuses_a_result_that_goes_negative(self):
        first = self.receive(10)
        self.issue(8)  # balance 2, depends on the receipt above

        first.quantity = Decimal("3")
        first.save()
        with self.assertRaises(ValidationError):
            StockTransaction.recalculate(self.item.pk)

        # The failed recalculation must not have partially applied.
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_on_hand, Decimal("2"))
