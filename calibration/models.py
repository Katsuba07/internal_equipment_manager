"""Calibration schedules and calibration certificates for measuring equipment."""

from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import AttachmentMixin, DueScheduleMixin, TimeStampedModel


def add_months(source_date, months: int):
    """
    Add months to a date, keeping the day of month where possible.

    31 Jan plus one month gives 28 Feb (29 in a leap year) rather than raising.
    """
    month_index = source_date.month - 1 + months
    year = source_date.year + month_index // 12
    month = month_index % 12 + 1
    # First day of the month after the target month
    if month == 12:
        next_month_first = source_date.replace(year=year + 1, month=1, day=1)
    else:
        next_month_first = source_date.replace(year=year, month=month + 1, day=1)
    last_day = (next_month_first - timedelta(days=1)).day
    return source_date.replace(year=year, month=month, day=min(source_date.day, last_day))


class CalibrationResult(models.TextChoices):
    PASS = "PASS", "Pass"
    ADJUSTED = "ADJUSTED", "Pass after adjustment"
    LIMITED = "LIMITED", "Pass with limited use"
    FAIL = "FAIL", "Fail"


class CalibrationPlan(DueScheduleMixin, TimeStampedModel):
    """A recurring calibration schedule for one measuring instrument."""

    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="Instrument",
        on_delete=models.CASCADE,
        related_name="calibration_plans",
        limit_choices_to={"is_measuring_device": True},
    )
    name = models.CharField(
        "Scope",
        max_length=200,
        help_text="For example: DC voltage 0–30 V, torque 0.5–3.0 Nm.",
    )
    interval_months = models.PositiveIntegerField(
        "Interval (months)", default=12, help_text="Typically 6 or 12 months."
    )
    measurement_range = models.CharField("Range", max_length=150, blank=True)
    tolerance = models.CharField(
        "Tolerance",
        max_length=150,
        blank=True,
        help_text="For example: ±0.05 % of reading, ±0.5 °C.",
    )
    standard_reference = models.CharField(
        "Standard / procedure", max_length=200, blank=True
    )
    is_internal = models.BooleanField(
        "Calibrated in-house",
        default=False,
        help_text="Turn off when an external laboratory performs it.",
    )
    provider = models.ForeignKey(
        "core.Supplier",
        verbose_name="Calibration laboratory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calibration_plans",
        limit_choices_to={"is_calibration_provider": True},
    )
    last_calibrated_at = models.DateField("Last calibrated", null=True, blank=True)

    # Warn a month ahead (the dashboard and the register count "due within 30
    # days" too): an instrument has to be booked in and sent out in time.
    WARNING_DAYS = 30

    history = HistoricalRecords(excluded_fields=["created_at", "updated_at"])

    class Meta:
        verbose_name = "Calibration plan"
        verbose_name_plural = "Calibration plans"
        ordering = ["next_due_at", "equipment__code"]
        indexes = [models.Index(fields=["is_active", "next_due_at"])]

    def __str__(self) -> str:
        return f"{self.equipment.ident} — {self.name}"

    def get_absolute_url(self) -> str:
        return reverse("calibration:plan_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        # The due date follows from the last calibration. Without one, it is
        # left empty — never guessed from today — so an instrument whose
        # sticker was lost shows "Calibration date unknown" until it is done.
        if not self.next_due_at and self.last_calibrated_at:
            self.next_due_at = add_months(self.last_calibrated_at, self.interval_months)
        super().save(*args, **kwargs)

    def mark_done(self, done_date, next_due=None, save: bool = True):
        """
        Update after a calibration has been carried out.

        ``next_due`` lets the due date on the certificate win, because that
        date is the auditable one — not the interval configured here.
        """
        self.last_calibrated_at = done_date
        self.next_due_at = next_due or add_months(done_date, self.interval_months)
        if save:
            self.save(update_fields=["last_calibrated_at", "next_due_at", "updated_at"])


class CalibrationRecord(AttachmentMixin, TimeStampedModel):
    """A completed calibration, with its certificate attached."""

    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="Instrument",
        on_delete=models.PROTECT,
        related_name="calibration_records",
    )
    plan = models.ForeignKey(
        CalibrationPlan,
        verbose_name="Against plan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="records",
    )

    calibrated_at = models.DateField("Calibration date", default=timezone.localdate)
    next_due_at = models.DateField(
        "Certificate due date",
        null=True,
        blank=True,
        help_text="Take this from the certificate. Left empty, the system "
        "calculates it from the interval.",
    )

    is_internal = models.BooleanField("Calibrated in-house", default=False)
    provider = models.ForeignKey(
        "core.Supplier",
        verbose_name="Performed by (lab)",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calibration_records",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Logged by",
        on_delete=models.SET_NULL,
        null=True,
        related_name="calibration_records",
    )

    certificate_number = models.CharField(
        "Certificate number", max_length=100, blank=True
    )
    result = models.CharField(
        "Result",
        max_length=20,
        choices=CalibrationResult.choices,
        default=CalibrationResult.PASS,
    )
    reading_before = models.TextField(
        "As-found readings",
        blank=True,
        help_text="Reference value versus instrument reading, before adjustment.",
    )
    reading_after = models.TextField("As-left readings", blank=True)
    deviation = models.CharField("Measured deviation", max_length=150, blank=True)
    cost = models.DecimalField(
        "Cost (USD)", max_digits=15, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField("Notes", blank=True)

    history = HistoricalRecords(excluded_fields=["created_at", "updated_at"])

    class Meta:
        verbose_name = "Calibration record"
        verbose_name_plural = "Calibration records"
        ordering = ["-calibrated_at", "-created_at"]
        indexes = [models.Index(fields=["equipment", "-calibrated_at"])]

    def __str__(self) -> str:
        return f"{self.equipment.ident} — calibrated {self.calibrated_at:%d %b %Y}"

    def get_absolute_url(self) -> str:
        return reverse("calibration:record_detail", args=[self.pk])

    @property
    def result_badge_class(self) -> str:
        return {
            CalibrationResult.PASS: "badge-success",
            CalibrationResult.ADJUSTED: "badge-warning",
            CalibrationResult.LIMITED: "badge-warning",
            CalibrationResult.FAIL: "badge-danger",
        }.get(self.result, "badge-neutral")

    @transaction.atomic
    def save(self, *args, **kwargs):
        if not self.next_due_at and self.plan_id:
            self.next_due_at = add_months(self.calibrated_at, self.plan.interval_months)
        super().save(*args, **kwargs)
        if self.plan_id:
            self.plan.mark_done(self.calibrated_at, next_due=self.next_due_at)
