"""Maintenance schedules and maintenance logs."""

from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import AttachmentMixin, DueScheduleMixin, TimeStampedModel


class MaintenanceKind(models.TextChoices):
    PREVENTIVE = "PREVENTIVE", "Preventive maintenance"
    INSPECTION = "INSPECTION", "Inspection"
    CLEANING = "CLEANING", "Cleaning"
    PROBE_SERVICE = "PROBE_SERVICE", "Probe / pogo pin service"
    SELF_TEST = "SELF_TEST", "Self-test / verification"
    FIRMWARE = "FIRMWARE", "Firmware / software update"
    REPLACEMENT = "REPLACEMENT", "Scheduled replacement"
    OTHER = "OTHER", "Other"


class MaintenanceResult(models.TextChoices):
    OK = "OK", "Pass — operating normally"
    NEEDS_FOLLOWUP = "NEEDS_FOLLOWUP", "Pass — monitor closely"
    NEEDS_REPAIR = "NEEDS_REPAIR", "Fault found — repair required"


class MaintenancePlan(DueScheduleMixin, TimeStampedModel):
    """
    A recurring maintenance task for one asset.

    An asset can carry several plans — weekly probe cleaning, quarterly
    contact resistance check, annual overhaul.
    """

    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="Equipment",
        on_delete=models.CASCADE,
        related_name="maintenance_plans",
    )
    name = models.CharField("Task name", max_length=200)
    kind = models.CharField(
        "Type",
        max_length=20,
        choices=MaintenanceKind.choices,
        default=MaintenanceKind.PREVENTIVE,
    )
    description = models.TextField("Description", blank=True)
    checklist = models.TextField(
        "Checklist",
        blank=True,
        help_text="One item per line. Shown to the technician when logging the work.",
    )

    interval_days = models.PositiveIntegerField(
        "Interval (days)",
        help_text="7 = weekly, 30 = monthly, 90 = quarterly, 365 = yearly.",
    )
    trigger_cycles = models.PositiveIntegerField(
        "Or after N test cycles",
        null=True,
        blank=True,
        help_text="Optional. For fixtures, wear follows insertion count rather "
        "than calendar time. Recorded for reference; the schedule still runs on days.",
    )
    estimated_minutes = models.PositiveIntegerField(
        "Estimated duration (min)", null=True, blank=True
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Owner",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_plans",
    )
    last_done_at = models.DateField("Last performed", null=True, blank=True)

    history = HistoricalRecords(excluded_fields=["created_at", "updated_at"])

    class Meta:
        verbose_name = "Maintenance plan"
        verbose_name_plural = "Maintenance plans"
        ordering = ["next_due_at", "equipment__code"]
        indexes = [models.Index(fields=["is_active", "next_due_at"])]

    def __str__(self) -> str:
        return f"{self.equipment.ident} — {self.name}"

    def get_absolute_url(self) -> str:
        return reverse("maintenance:plan_detail", args=[self.pk])

    @property
    def checklist_items(self) -> list[str]:
        return [line.strip() for line in self.checklist.splitlines() if line.strip()]

    def save(self, *args, **kwargs):
        # A brand-new plan that has never run counts from today.
        if not self.next_due_at:
            base = self.last_done_at or timezone.localdate()
            self.next_due_at = base + timedelta(days=self.interval_days)
        super().save(*args, **kwargs)

    def mark_done(self, done_date, save: bool = True):
        """Record the latest run and roll the due date forward."""
        self.last_done_at = done_date
        self.next_due_at = done_date + timedelta(days=self.interval_days)
        if save:
            self.save(update_fields=["last_done_at", "next_due_at", "updated_at"])


class MaintenanceRecord(AttachmentMixin, TimeStampedModel):
    """A log entry for maintenance that was actually performed."""

    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="Equipment",
        on_delete=models.PROTECT,
        related_name="maintenance_records",
    )
    plan = models.ForeignKey(
        MaintenancePlan,
        verbose_name="Against plan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="records",
        help_text="Leave empty for unplanned work.",
    )
    kind = models.CharField(
        "Type",
        max_length=20,
        choices=MaintenanceKind.choices,
        default=MaintenanceKind.PREVENTIVE,
    )
    performed_at = models.DateField("Performed on", default=timezone.localdate)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Performed by",
        on_delete=models.SET_NULL,
        null=True,
        related_name="maintenance_records",
    )
    work_done = models.TextField("Work performed")
    checklist_result = models.TextField("Checklist result", blank=True)
    result = models.CharField(
        "Result",
        max_length=20,
        choices=MaintenanceResult.choices,
        default=MaintenanceResult.OK,
    )
    downtime_minutes = models.PositiveIntegerField(
        "Downtime (min)",
        default=0,
        help_text="Minutes the asset was unavailable for production.",
    )
    cost = models.DecimalField(
        "Cost (USD)", max_digits=15, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField("Notes", blank=True)

    history = HistoricalRecords(excluded_fields=["created_at", "updated_at"])

    class Meta:
        verbose_name = "Maintenance log"
        verbose_name_plural = "Maintenance logs"
        ordering = ["-performed_at", "-created_at"]
        indexes = [models.Index(fields=["equipment", "-performed_at"])]

    def __str__(self) -> str:
        return f"{self.equipment.ident} — maintenance {self.performed_at:%d %b %Y}"

    def get_absolute_url(self) -> str:
        return reverse("maintenance:record_detail", args=[self.pk])

    @property
    def result_badge_class(self) -> str:
        return {
            MaintenanceResult.OK: "badge-success",
            MaintenanceResult.NEEDS_FOLLOWUP: "badge-warning",
            MaintenanceResult.NEEDS_REPAIR: "badge-danger",
        }.get(self.result, "badge-neutral")

    @transaction.atomic
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Once logged, the matching plan must roll forward — otherwise the
        # task keeps showing as overdue after it has been done.
        if self.plan_id and self.plan.last_done_at != self.performed_at:
            self.plan.mark_done(self.performed_at)
