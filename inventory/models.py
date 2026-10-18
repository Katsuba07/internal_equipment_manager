"""Spare units, consumables and stock movements."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Count, F
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import AttachmentMixin, Plant, TimeStampedModel


class ItemKind(models.TextChoices):
    SPARE_PART = "SPARE_PART", "Spare part"
    CONSUMABLE = "CONSUMABLE", "Consumable"
    SPARE_EQUIPMENT = "SPARE_EQUIPMENT", "Spare unit"
    PROBE = "PROBE", "Probe / pogo pin"
    CABLE = "CABLE", "Cable / harness"
    TOOL = "TOOL", "Tool"


class InventoryItemQuerySet(models.QuerySet):
    def below_minimum(self):
        """Items at or under their reorder point."""
        return self.filter(is_active=True, quantity_on_hand__lte=F("min_quantity"))


class InventoryItem(AttachmentMixin, TimeStampedModel):
    """A stocked item: spare part, consumable, probe, or standby unit."""

    code = models.CharField("Part number", max_length=50, unique=True)
    name = models.CharField("Name", max_length=200)
    kind = models.CharField(
        "Type", max_length=20, choices=ItemKind.choices, default=ItemKind.SPARE_PART
    )
    specification = models.CharField("Specification", max_length=255, blank=True)
    manufacturer_part = models.CharField(
        "Manufacturer P/N", max_length=120, blank=True
    )
    unit = models.CharField(
        "Unit", max_length=30, default="pcs", help_text="pcs, set, m, L, kg..."
    )

    quantity_on_hand = models.DecimalField(
        "On hand", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    min_quantity = models.DecimalField(
        "Reorder point",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="When stock reaches this level the system raises a low-stock alert.",
    )

    plant = models.CharField(
        "Plant", max_length=10, choices=Plant.choices, blank=True,
        help_text="Which factory's store this stock sits in.",
    )
    storage_location = models.CharField("Bin location", max_length=120, blank=True)
    unit_price = models.DecimalField(
        "Unit price (USD)", max_digits=15, decimal_places=2, null=True, blank=True
    )
    lead_time_days = models.PositiveIntegerField(
        "Lead time (days)",
        null=True,
        blank=True,
        help_text="Typical time from order to delivery. Useful when setting the reorder point.",
    )
    supplier = models.ForeignKey(
        "core.Supplier",
        verbose_name="Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_items",
    )
    notes = models.TextField("Notes", blank=True)
    is_active = models.BooleanField("Active", default=True)

    history = HistoricalRecords(excluded_fields=["created_at", "updated_at"])
    objects = InventoryItemQuerySet.as_manager()

    class Meta:
        verbose_name = "Stock item"
        verbose_name_plural = "Stock items"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def get_absolute_url(self) -> str:
        return reverse("inventory:part_detail", args=[self.pk])

    @property
    def is_below_minimum(self) -> bool:
        return self.is_active and self.quantity_on_hand <= self.min_quantity

    @property
    def is_out_of_stock(self) -> bool:
        return self.quantity_on_hand <= 0

    @property
    def stock_badge_class(self) -> str:
        if self.is_out_of_stock:
            return "badge-danger"
        return "badge-warning" if self.is_below_minimum else "badge-success"

    @property
    def stock_status(self) -> tuple[str, str]:
        """(label, badge class) for the status column of the parts list."""
        if not self.is_active:
            return "Inactive", "badge-muted"
        if self.is_out_of_stock:
            return "Out of stock", "badge-danger"
        if self.is_below_minimum:
            return "Low stock", "badge-warning"
        return "In stock", "badge-success"

    @property
    def stock_cell_class(self) -> str:
        """Table cell highlight: nothing when stock is fine."""
        if self.is_out_of_stock:
            return "cell-danger"
        return "cell-warn" if self.is_below_minimum else ""

    @property
    def quantity_display(self) -> str:
        return f"{self.quantity_on_hand.normalize():f} {self.unit}"


class EquipmentPart(TimeStampedModel):
    """
    One line of an asset's own parts list: which stocked part it is built
    with, and how many — e.g. fixture FIX-BAF1950 carries 120 x PRB-100-3A.

    Declaring a part here does not move stock; issues go through
    StockTransaction.
    """

    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="Equipment",
        on_delete=models.CASCADE,
        related_name="parts",
    )
    item = models.ForeignKey(
        InventoryItem,
        verbose_name="Part",
        on_delete=models.CASCADE,
        related_name="used_in",
    )
    quantity = models.DecimalField(
        "Qty", max_digits=10, decimal_places=2, default=Decimal("1")
    )
    notes = models.CharField("Note", max_length=200, blank=True)

    class Meta:
        verbose_name = "Equipment part"
        verbose_name_plural = "Equipment parts"
        ordering = ["item__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipment", "item"], name="one_line_per_part_per_equipment"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="equipment_part_quantity_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.equipment.ident}: {self.quantity_display} x {self.item.code}"

    @property
    def quantity_display(self) -> str:
        return f"{self.quantity.normalize():f}"


class TransactionType(models.TextChoices):
    IN = "IN", "Receipt"
    OUT = "OUT", "Issue"
    ADJUST = "ADJUST", "Stocktake / adjustment"


class StockTransaction(TimeStampedModel):
    """
    One receipt, issue, or adjustment.

    Stock levels only ever change through ``apply`` (new movement) or
    ``recalculate`` (after editing/deleting a past movement) below — never by
    editing ``InventoryItem.quantity_on_hand`` by hand — so the balance and
    the movement history can never drift apart.
    """

    item = models.ForeignKey(
        InventoryItem,
        verbose_name="Item",
        # Deleting a part is one action; its movements go with it.
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    transaction_type = models.CharField(
        "Movement", max_length=10, choices=TransactionType.choices
    )
    quantity = models.DecimalField(
        "Quantity",
        max_digits=12,
        decimal_places=2,
        help_text="Always positive. For a stocktake, enter the counted quantity.",
    )
    quantity_after = models.DecimalField(
        "Balance after", max_digits=12, decimal_places=2, default=Decimal("0")
    )

    occurred_at = models.DateTimeField("Date", default=timezone.now)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="By",
        on_delete=models.SET_NULL,
        null=True,
        related_name="stock_transactions",
    )
    reason = models.CharField("Reason", max_length=255, blank=True)

    # Where an issued part went. Required for an issue (see StockMovementForm),
    # so the shelf balance and the assets always agree on where a part ended up.
    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="Issue to",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="part_issues",
    )

    # Links back to the job that consumed the part, so any issue can be traced
    # to the work it was used for.
    maintenance_record = models.ForeignKey(
        "maintenance.MaintenanceRecord",
        verbose_name="Maintenance log",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_transactions",
    )
    repair_record = models.ForeignKey(
        "repairs.RepairRecord",
        verbose_name="Repair job",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_transactions",
    )
    note = models.TextField("Note", blank=True)

    class Meta:
        verbose_name = "Stock movement"
        verbose_name_plural = "Stock movements"
        ordering = ["-occurred_at", "-created_at"]
        indexes = [
            models.Index(fields=["item", "-occurred_at"]),
            models.Index(fields=["equipment", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_transaction_type_display()} {self.quantity} {self.item.unit} — {self.item.code}"

    def clean(self):
        if self.quantity is not None and self.quantity < 0:
            raise ValidationError({"quantity": "Quantity must be positive."})

    @transaction.atomic
    def apply(self):
        """
        Write the movement and update the balance in one database transaction.

        The item row is locked before reading so two people issuing stock at
        the same moment cannot overwrite each other's result.
        """
        item = InventoryItem.objects.select_for_update().get(pk=self.item_id)

        if self.transaction_type == TransactionType.IN:
            new_quantity = item.quantity_on_hand + self.quantity
        elif self.transaction_type == TransactionType.OUT:
            if self.quantity > item.quantity_on_hand:
                raise ValidationError(
                    f"Not enough stock: {item.name} has only "
                    f"{item.quantity_on_hand:g} {item.unit} on hand."
                )
            new_quantity = item.quantity_on_hand - self.quantity
        else:  # Stocktake: the quantity entered is the counted balance
            new_quantity = self.quantity

        item.quantity_on_hand = new_quantity
        item.save(update_fields=["quantity_on_hand", "updated_at"])

        self.item = item
        self.quantity_after = new_quantity
        self.save()
        return self

    @classmethod
    def recalculate(cls, item_id):
        """
        Rebuild every movement's running balance and the item's on-hand total
        from scratch, oldest first.

        Needed after a movement is edited or deleted: ``quantity_after`` is a
        running balance, so changing one entry invalidates every balance
        recorded after it. Raises ``ValidationError`` (rolling back the
        caller's transaction) if the result would take the item negative.
        """
        with transaction.atomic():
            item = InventoryItem.objects.select_for_update().get(pk=item_id)
            balance = Decimal("0")
            changed = []
            for movement in cls.objects.filter(item=item).order_by(
                "occurred_at", "created_at", "pk"
            ):
                if movement.transaction_type == TransactionType.IN:
                    balance += movement.quantity
                elif movement.transaction_type == TransactionType.OUT:
                    balance -= movement.quantity
                    if balance < 0:
                        raise ValidationError(
                            f"Can't do that: {item.name} would go negative at the "
                            f"{movement.occurred_at:%d %b %Y} issue. Fix or remove "
                            f"that movement first."
                        )
                else:  # ADJUST: the counted quantity becomes the new balance
                    balance = movement.quantity
                if movement.quantity_after != balance:
                    movement.quantity_after = balance
                    changed.append(movement)
            if changed:
                cls.objects.bulk_update(changed, ["quantity_after"])
            if item.quantity_on_hand != balance:
                item.quantity_on_hand = balance
                item.save(update_fields=["quantity_on_hand", "updated_at"])
            return balance

    @classmethod
    def reason_suggestions(cls, kind, limit=20):
        """
        Past issue reasons for this kind of part, most used first.

        Powers the reason dropdown on the issue form — typing a new reason
        needs no extra step to "add" it, since the next issue of any part of
        this kind will simply see it show up here too.
        """
        return list(
            cls.objects.filter(item__kind=kind, transaction_type=TransactionType.OUT)
            .exclude(reason="")
            .values("reason")
            .annotate(uses=Count("reason"))
            .order_by("-uses", "reason")
            .values_list("reason", flat=True)[:limit]
        )
