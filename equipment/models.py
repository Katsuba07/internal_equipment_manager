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
    Equipment status, chosen on the asset form: in use, kept as a spare, or
    broken. Every change writes a row to StatusHistory, so the question "what
    was this asset, since when" always has an answer.
    """

    IN_USE = "IN_USE", "In use"
    SPARE = "SPARE", "Spare"
    BROKEN = "BROKEN", "Broken"


# Badge colour per status, shared by every screen.
STATUS_BADGE_CLASS = {
    EquipmentStatus.IN_USE: "badge-success",
    EquipmentStatus.SPARE: "badge-neutral",
    EquipmentStatus.BROKEN: "badge-danger",
}

# Statuses that mean the asset cannot be used on the line.
UNAVAILABLE_STATUSES = {EquipmentStatus.BROKEN}


class EquipmentQuerySet(models.QuerySet):
    def active(self):
        """Everything that is not broken."""
        return self.exclude(status=EquipmentStatus.BROKEN)

    def with_related(self):
        return self.select_related("category", "location")

    def calibration_date_unknown(self):
        """Assets that need calibration but have no due date on record (see Equipment.calibration_date_unknown)."""
        from calibration.models import CalibrationPlan

        dated = CalibrationPlan.objects.filter(is_active=True, next_due_at__isnull=False).values("equipment_id")
        return self.filter(is_measuring_device=True).exclude(pk__in=dated)

    def with_product_codes(self):
        """Preload what Equipment.product_codes reads, for a list of many assets."""
        from systems.models import Installation

        return self.prefetch_related(models.Prefetch(
            "installations",
            queryset=Installation.objects.filter(removed_at__isnull=True)
            .select_related("test_set__product_process__product", "station")
            .prefetch_related("station__test_sets__product_process__product"),
            to_attr="open_installations",
        ))


class Equipment(AttachmentMixin, TimeStampedModel):
    """A single asset on the floor: tester, fixture, instrument, or cart."""

    # Four identifiers. The Equipment No (type and running number, DMM-0001) is
    # the key people use and the form requires; the ZT Code (the company
    # register, 70-000148) is added when it is known; then the finance asset
    # number and the maker's serial number. Records from before the Equipment
    # No became the key may still lack one until they are inventoried again.
    code = models.CharField(
        "ZT Code",
        max_length=50,
        blank=True,
        db_index=True,
        help_text="The company register code, added when known. Example: 70-000148",
    )
    equipment_no = models.CharField(
        "Equipment No",
        max_length=30,
        blank=True,
        db_index=True,
        help_text="The asset's key: type and running number. Example: DMM-0001",
    )
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
    specifications = models.TextField(
        "Specifications",
        blank=True,
        help_text="Channel count, ranges, accuracy, test coverage...",
    )

    # --- Status ---
    status = models.CharField(
        "Status",
        max_length=20,
        choices=EquipmentStatus.choices,
        default=EquipmentStatus.IN_USE,
        db_index=True,
    )
    status_changed_at = models.DateTimeField("Status changed at", default=timezone.now)
    # Ticked by hand once the label is on the asset, so a stock-take can see
    # which ones still need one.
    labelled = models.BooleanField("Labelled", default=False, db_index=True)

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
        ordering = ["equipment_no", "code"]
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["is_measuring_device"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["code"], condition=~models.Q(code=""), name="zt_code_unique_when_set",
                violation_error_message="Another asset already has this ZT Code.",
            ),
            models.UniqueConstraint(
                fields=["asset_no"], condition=~models.Q(asset_no=""), name="asset_no_unique_when_set",
            ),
            models.UniqueConstraint(
                fields=["equipment_no"], condition=~models.Q(equipment_no=""),
                name="equipment_no_unique_when_set",
                violation_error_message="Another asset already has this Equipment No.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.ident} — {self.name}"

    def get_absolute_url(self) -> str:
        return reverse("equipment:detail", args=[self.pk])

    @property
    def ident(self) -> str:
        """How the asset is named everywhere: its Equipment No, else its ZT Code."""
        return self.equipment_no or self.code or f"#{self.pk}"

    # --- Display helpers ---------------------------------------------------

    @property
    def status_badge_class(self) -> str:
        return STATUS_BADGE_CLASS.get(self.status, "badge-neutral")

    @property
    def is_available(self) -> bool:
        return self.status not in UNAVAILABLE_STATUSES

    @property
    def zt_code_pending(self) -> bool:
        """No real ZT Code yet: none at all, or a retired CTV2020… ID."""
        return not self.code or self.code.upper().startswith("CTV")

    @property
    def calibration_now(self):
        """The active calibration plan that falls due first (its dates are the asset's), or None."""
        plans = [p for p in self.calibration_plans.all() if p.is_active]
        return min(plans, key=lambda p: (p.next_due_at is None, p.next_due_at), default=None)

    @property
    def maintenance_now(self):
        """The active maintenance plan that falls due first, or None."""
        plans = [p for p in self.maintenance_plans.all() if p.is_active]
        return min(plans, key=lambda p: (p.next_due_at is None, p.next_due_at), default=None)

    @property
    def calibration_date_unknown(self) -> bool:
        """
        Needs calibration, but no due date is on record — the sticker was lost
        and no certificate found, say. Treated like an overdue calibration:
        not to be measured with until it is calibrated and the dates entered.
        """
        if not self.is_measuring_device:
            return False
        return not any(plan.is_active and plan.next_due_at for plan in self.calibration_plans.all())

    @property
    def label_qr_url(self) -> str:
        """The QR code's content: the asset in the company register, or its Equipment No until it has a ZT Code."""
        from urllib.parse import quote

        if self.zt_code_pending:
            return self.ident
        return settings.EMA_LABEL_QR_URL.replace("{code}", quote(self.code, safe=""))

    @property
    def plant_display(self) -> str:
        return Plant(self.plant).label if self.plant else "—"

    # Identifying text is kept in capitals, however it was typed or imported,
    # so the same make and model read (and search, and sort) the same.
    UPPER_FIELDS = ("equipment_no", "code", "asset_no", "name", "manufacturer", "model_number", "serial_number")

    def save(self, *args, **kwargs):
        for field in self.UPPER_FIELDS:
            setattr(self, field, " ".join(str(getattr(self, field) or "").split()).upper())
        # The plant is kept on the asset so it survives an empty location;
        # choosing a location that belongs to a plant brings the plant along.
        if self.location_id and self.location.plant:
            self.plant = self.location.plant
        super().save(*args, **kwargs)

    # --- Where this asset is used -----------------------------------------
    # An asset is fitted to at most one role of one equipment set at a time
    # (e.g. BAF1950 · FCT #1 · Fixture); closed installations are its history.

    NO_DIGITS = 4        # DMM-0001

    @staticmethod
    def normalise_equipment_no(value) -> str:
        """Upper case, and a type's running number padded to four digits: dmm-1 -> DMM-0001."""
        import re

        value = " ".join(str(value or "").split()).upper()
        match = re.fullmatch(r"([A-Z][A-Z0-9]*)-(\d+)", value)
        if match:
            value = f"{match.group(1)}-{int(match.group(2)):0{Equipment.NO_DIGITS}d}"
        return value

    @staticmethod
    def equipment_no_counter(category) -> dict:
        """
        Equipment No runs per equipment type: DMM-0001, DMM-0002 ... The prefix is
        the type's code. Returns the last number in use and the next one free.
        """
        import re

        prefix = f"{category.code}-"
        numbers = [
            int(match.group(1))
            for value in Equipment.objects.filter(equipment_no__startswith=prefix).values_list("equipment_no", flat=True)
            if (match := re.fullmatch(re.escape(prefix) + r"(\d+)", value))
        ]
        last = max(numbers, default=0)
        width = Equipment.NO_DIGITS
        return {
            "prefix": category.code,
            "count": len(numbers),
            "last": f"{prefix}{last:0{width}d}" if numbers else "",
            "next": f"{prefix}{last + 1:0{width}d}",
        }

    @property
    def current_installation(self):
        """The open installation, or None when the asset is not fitted anywhere."""
        return (
            self.installations.select_related(
                "test_set__product_process__product", "test_set__product_process__process",
                "test_set__line", "slot__category", "station",
            )
            .filter(removed_at__isnull=True)
            .first()
        )

    @property
    def open_fittings_now(self) -> list:
        """Every open fitting: a station's shared machine has one; a model's own may serve several models."""
        return list(
            self.installations.filter(removed_at__isnull=True).select_related(
                "test_set__product_process__product", "test_set__product_process__process",
                "test_set__station", "slot__category", "station",
            )
        )

    @property
    def where_fitted(self) -> str:
        """Where it is, in words: the station's shared machine, or the model(s) it belongs to and whether mounted."""
        fittings = self.open_fittings_now
        if not fittings:
            return ""
        if len(fittings) == 1:
            return fittings[0].where
        sets = [f.test_set for f in fittings if f.test_set_id]
        station = next((s.station for s in sets if s.station_id), None)
        models = ", ".join(s.product.code for s in sets)
        if station is None:
            return models
        state = "mounted" if any(s.is_running for s in sets) else "kept aside"
        return f"{models} · station {station} ({state})"

    @property
    def fitted_in(self):
        installation = self.current_installation
        return installation.test_set if installation else None

    @property
    def product_codes(self) -> list[str]:
        """
        The products this asset serves now (a list, for the table column): the
        product of the set holding it, or every product run on its station.
        """
        # A list page preloads them (see EquipmentQuerySet.with_product_codes);
        # a single asset looks them up.
        open_now = getattr(self, "open_installations", None)
        if open_now is None:
            open_now = self.installations.filter(removed_at__isnull=True).select_related(
                "test_set__product_process__product", "station",
            ).prefetch_related("station__test_sets__product_process__product")
        codes = set()
        for installation in open_now:
            if installation.test_set_id:
                codes.add(installation.test_set.product_process.product.code)
            if installation.station_id:
                codes.update(s.product_process.product.code for s in installation.station.test_sets.all())
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
        """
        The open fitting of this asset in a set of a product that is in
        production, or at a station one such product runs on, if any.
        """
        from django.db.models import Q

        return self.installations.filter(
            Q(test_set__product_process__product__in_production=True)
            | Q(station__test_sets__product_process__product__in_production=True),
            removed_at__isnull=True,
        ).select_related("test_set", "station").first()

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
        return f"{self.equipment.ident}: {self.get_from_status_display()} → {self.get_to_status_display()}"

    @property
    def to_status_badge_class(self) -> str:
        return STATUS_BADGE_CLASS.get(self.to_status, "badge-neutral")
