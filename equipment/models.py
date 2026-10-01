"""Equipment records and their status history."""

from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import AttachmentMixin, Plant, TimeStampedModel


class EquipmentStatus(models.TextChoices):
    """
    Equipment status.

    Every change writes a row to StatusHistory, so the question "where has
    this asset been, doing what, since when" always has an answer.
    """

    IN_PRODUCTION = "IN_PRODUCTION", "In production"
    AVAILABLE = "AVAILABLE", "Available / in storage"
    MAINTENANCE = "MAINTENANCE", "Under maintenance"
    REPAIR = "REPAIR", "Under repair"
    CALIBRATION = "CALIBRATION", "Out for calibration"
    DOWN = "DOWN", "Down — awaiting action"
    RETIRED = "RETIRED", "Retired"


class EquipmentCondition(models.TextChoices):
    """How the asset came to the company — not tracked after that."""

    NEW = "NEW", "New"
    USED = "USED", "Used"


# Badge colour per status, shared by every screen.
STATUS_BADGE_CLASS = {
    EquipmentStatus.IN_PRODUCTION: "badge-success",
    EquipmentStatus.AVAILABLE: "badge-neutral",
    EquipmentStatus.MAINTENANCE: "badge-info",
    EquipmentStatus.REPAIR: "badge-warning",
    EquipmentStatus.CALIBRATION: "badge-primary",
    EquipmentStatus.DOWN: "badge-danger",
    EquipmentStatus.RETIRED: "badge-muted",
}

# Statuses that mean the asset cannot be used on the line right now.
UNAVAILABLE_STATUSES = {
    EquipmentStatus.MAINTENANCE,
    EquipmentStatus.REPAIR,
    EquipmentStatus.CALIBRATION,
    EquipmentStatus.DOWN,
    EquipmentStatus.RETIRED,
}


class EquipmentQuerySet(models.QuerySet):
    def active(self):
        """Everything except retired assets."""
        return self.exclude(status=EquipmentStatus.RETIRED)

    def measuring_devices(self):
        return self.filter(is_measuring_device=True)

    def with_related(self):
        return self.select_related("category", "location", "supplier")


class Equipment(AttachmentMixin, TimeStampedModel):
    """A single asset on the floor: tester, fixture, instrument, or cart."""

    code = models.CharField(
        "Equipment ID",
        max_length=50,
        unique=True,
        help_text="The internal equipment ID, printed on the QR label. Example: CTV20200077",
    )
    # Three identifiers, each kept by a different part of the company: the
    # internal equipment ID above, the finance asset number here, and the
    # maker's serial number further down.
    asset_no = models.CharField(
        "Asset No.",
        max_length=40,
        blank=True,
        db_index=True,
        help_text="The company asset number. Example: 103220100359",
    )
    name = models.CharField("Name", max_length=200)
    category = models.ForeignKey(
        "core.Category",
        verbose_name="Category",
        on_delete=models.PROTECT,
        related_name="equipments",
    )
    location = models.ForeignKey(
        "core.Location",
        verbose_name="Location",
        # Optional: an asset can be on record before anyone has said where it
        # is. Deleting a location clears it here instead of being refused.
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipments",
        help_text="Where it is now. Leave empty until it is known.",
    )
    plant = models.CharField(
        "Plant",
        max_length=10,
        choices=Plant.choices,
        blank=True,
        db_index=True,
        help_text="Taken from the location when one is chosen.",
    )
    # --- Technical details ---
    manufacturer = models.CharField("Manufacturer", max_length=150, blank=True)
    model_number = models.CharField("Model", max_length=150, blank=True)
    serial_number = models.CharField("Serial number", max_length=150, blank=True)
    year_made = models.PositiveIntegerField("Year of manufacture", null=True, blank=True)
    firmware_version = models.CharField(
        "Firmware / software version", max_length=100, blank=True
    )
    specifications = models.TextField(
        "Specifications",
        blank=True,
        help_text="Channel count, ranges, accuracy, test coverage...",
    )
    voltage = models.CharField("Voltage", max_length=50, blank=True, help_text="e.g. AC220V")
    power_watt = models.PositiveIntegerField("Power (W)", null=True, blank=True)
    dimensions = models.CharField(
        "Size, mm (L × W × H)", max_length=100, blank=True, help_text="e.g. 105 × 65 × 160"
    )
    country_of_origin = models.CharField("Country of origin", max_length=100, blank=True)
    condition = models.CharField(
        "Condition when received", max_length=10, choices=EquipmentCondition.choices, blank=True
    )

    # --- Status ---
    status = models.CharField(
        "Status",
        max_length=20,
        choices=EquipmentStatus.choices,
        default=EquipmentStatus.AVAILABLE,
        db_index=True,
    )
    status_changed_at = models.DateTimeField("Status changed at", default=timezone.now)

    # --- Purchasing and warranty ---
    supplier = models.ForeignKey(
        "core.Supplier",
        verbose_name="Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipments",
    )
    purchase_date = models.DateField("Purchase date", null=True, blank=True)
    purchase_cost = models.DecimalField(
        "Purchase cost (USD)", max_digits=15, decimal_places=2, null=True, blank=True
    )
    commissioned_date = models.DateField("In service since", null=True, blank=True)
    warranty_until = models.DateField("Warranty until", null=True, blank=True)

    # --- Calibration ---
    maintenance_required = models.BooleanField(
        "Maintenance required",
        default=False,
    )
    maintenance_interval_days = models.PositiveIntegerField(
        "Maintenance every",
        null=True,
        blank=True,
        choices=[(7, "1 week"), (30, "1 month"), (90, "3 months"), (180, "6 months"), (365, "1 year")],
    )

    is_measuring_device = models.BooleanField(
        "Requires calibration",
        default=False,
    )

    notes = models.TextField("Notes", blank=True)

    history = HistoricalRecords(excluded_fields=["created_at", "updated_at"])
    objects = EquipmentQuerySet.as_manager()

    class Meta:
        verbose_name = "Equipment"
        verbose_name_plural = "Equipment"
        ordering = ["code"]
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["is_measuring_device"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["asset_no"], condition=~models.Q(asset_no=""), name="asset_no_unique_when_set",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def get_absolute_url(self) -> str:
        return reverse("equipment:detail", args=[self.pk])

    # --- Display helpers ---------------------------------------------------

    @property
    def status_badge_class(self) -> str:
        return STATUS_BADGE_CLASS.get(self.status, "badge-neutral")

    @property
    def is_available(self) -> bool:
        return self.status not in UNAVAILABLE_STATUSES

    @property
    def is_under_warranty(self) -> bool:
        return bool(self.warranty_until and self.warranty_until >= timezone.localdate())

    @property
    def age_years(self) -> float | None:
        """Years in service, counted from commissioning (or purchase)."""
        start = self.commissioned_date or self.purchase_date
        if not start:
            return None
        return round((timezone.localdate() - start).days / 365.25, 1)

    @property
    def plant_display(self) -> str:
        return Plant(self.plant).label if self.plant else "—"

    def save(self, *args, **kwargs):
        # The plant is kept on the asset so it survives an empty location;
        # choosing a location that belongs to a plant brings the plant along.
        if self.location_id and self.location.plant:
            self.plant = self.location.plant
        super().save(*args, **kwargs)

    # --- Where this asset is used -----------------------------------------
    # An asset is fitted to at most one role of one equipment set at a time
    # (e.g. BAF1950 · FCT #1 · Fixture); closed installations are its history.

    @property
    def current_installation(self):
        """The open installation, or None when the asset is not fitted anywhere."""
        return (
            self.installations.select_related(
                "test_set__product_process__product", "test_set__product_process__process",
                "test_set__line", "role",
            )
            .filter(removed_at__isnull=True)
            .first()
        )

    @property
    def fitted_in(self):
        installation = self.current_installation
        return installation.test_set if installation else None

    @property
    def product_codes(self) -> list[str]:
        """The product whose set holds this asset now (a list, for the table column)."""
        codes = self.installations.filter(removed_at__isnull=True).values_list(
            "test_set__product_process__product__code", flat=True
        )
        return sorted(code for code in codes if code)

    # --- Behaviour ---------------------------------------------------------

    SCHEDULED_PLAN_NAME = "Scheduled maintenance"

    @transaction.atomic
    def sync_maintenance_plan(self):
        """
        Keep the asset's scheduled maintenance plan in step with the tick and
        the interval on the asset form.

        One plan per asset carries the routine round; extra plans (a quarterly
        deep clean, say) are entered separately and are left alone here.
        """
        from maintenance.models import MaintenancePlan

        plan = self.maintenance_plans.filter(name=self.SCHEDULED_PLAN_NAME).first()
        if not (self.maintenance_required and self.maintenance_interval_days):
            if plan and plan.is_active:
                plan.is_active = False
                plan.save(update_fields=["is_active", "updated_at"])
            return plan

        interval = self.maintenance_interval_days
        if plan is None:
            return MaintenancePlan.objects.create(
                equipment=self, name=self.SCHEDULED_PLAN_NAME, interval_days=interval,
                next_due_at=timezone.localdate() + timedelta(days=interval),
            )
        changed = ["is_active", "updated_at"]
        plan.is_active = True
        if plan.interval_days != interval:
            plan.interval_days = interval
            start = plan.last_done_at or timezone.localdate()
            plan.next_due_at = start + timedelta(days=interval)
            changed += ["interval_days", "next_due_at"]
        plan.save(update_fields=changed)
        return plan

    def running_fitting(self):
        """The open fitting of this asset in a set of a product that is in production, if any."""
        return self.installations.filter(
            removed_at__isnull=True,
            test_set__product_process__product__in_production=True,
        ).select_related("test_set").first()

    def refresh_production_status(self, user=None):
        """
        "In production" means fitted to an equipment set of a product that is
        running — nothing else. Moves the asset between Available and In
        production to match. Down, repair, calibration, maintenance and retired
        are a person's call and are left alone.
        """
        fitting = self.running_fitting()
        if fitting and self.status == EquipmentStatus.AVAILABLE:
            return self.change_status(
                EquipmentStatus.IN_PRODUCTION, user,
                reason=f"Fitted to {fitting.where}, which is in production",
            )
        if not fitting and self.status == EquipmentStatus.IN_PRODUCTION:
            return self.change_status(
                EquipmentStatus.AVAILABLE, user,
                reason="Not fitted to a product in production",
            )
        return None

    @transaction.atomic
    def change_status(self, new_status: str, user, reason: str = "", note: str = ""):
        """
        Change status and write one history row.

        Always go through this instead of assigning ``equipment.status``
        directly — a direct assignment leaves a gap in the history and breaks
        traceability.
        """
        if new_status == self.status:
            return None

        old_status = self.status
        self.status = new_status
        self.status_changed_at = timezone.now()
        self.save(update_fields=["status", "status_changed_at", "updated_at"])

        return StatusHistory.objects.create(
            equipment=self,
            from_status=old_status,
            to_status=new_status,
            changed_by=user if getattr(user, "is_authenticated", False) else None,
            reason=reason,
            note=note,
        )


class StatusHistory(TimeStampedModel):
    """One status change on an asset — this is what makes status traceable."""

    equipment = models.ForeignKey(
        Equipment,
        verbose_name="Equipment",
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    from_status = models.CharField(
        "From", max_length=20, choices=EquipmentStatus.choices, blank=True
    )
    to_status = models.CharField("To", max_length=20, choices=EquipmentStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Changed by",
        on_delete=models.SET_NULL,
        null=True,
        related_name="status_changes",
    )
    reason = models.CharField("Reason", max_length=255, blank=True)
    note = models.TextField("Details", blank=True)

    class Meta:
        verbose_name = "Status history"
        verbose_name_plural = "Status history"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["equipment", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.equipment.code}: {self.get_from_status_display()} → {self.get_to_status_display()}"

    @property
    def to_status_badge_class(self) -> str:
        return STATUS_BADGE_CLASS.get(self.to_status, "badge-neutral")
