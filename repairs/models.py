"""Repair and replacement logs."""

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import AttachmentMixin, TimeStampedModel
from core.utils import next_sequence_code


class RepairStatus(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    WAITING_PARTS = "WAITING_PARTS", "Waiting for parts"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class RepairResult(models.TextChoices):
    FIXED = "FIXED", "Fully repaired"
    TEMPORARY = "TEMPORARY", "Temporary fix — permanent action pending"
    REPLACED = "REPLACED", "Unit or module replaced"
    UNREPAIRABLE = "UNREPAIRABLE", "Beyond repair — recommend retirement"


class RepairRecord(AttachmentMixin, TimeStampedModel):
    """A repair or replacement job on an asset."""

    code = models.CharField("Job number", max_length=30, unique=True, blank=True)
    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="Equipment",
        on_delete=models.PROTECT,
        related_name="repair_records",
    )
    incident = models.ForeignKey(
        "incidents.IncidentReport",
        verbose_name="From incident",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repairs",
        help_text="Leave empty for planned repairs not triggered by an incident.",
    )

    status = models.CharField(
        "Status",
        max_length=20,
        choices=RepairStatus.choices,
        default=RepairStatus.IN_PROGRESS,
        db_index=True,
    )
    started_at = models.DateTimeField("Started at", default=timezone.now)
    finished_at = models.DateTimeField("Finished at", null=True, blank=True)

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Technician",
        on_delete=models.SET_NULL,
        null=True,
        related_name="repair_records",
    )
    is_outsourced = models.BooleanField("Outsourced", default=False)
    vendor = models.ForeignKey(
        "core.Supplier",
        verbose_name="Service provider",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repair_records",
    )

    symptom = models.TextField("Symptom")
    cause = models.TextField("Root cause", blank=True)
    action_taken = models.TextField("Action taken", blank=True)
    parts_replaced = models.TextField(
        "Parts replaced",
        blank=True,
        help_text="Free text for now. From the stock release, parts will be "
        "picked from the catalog and deducted automatically.",
    )
    result = models.CharField(
        "Result", max_length=20, choices=RepairResult.choices, blank=True
    )

    downtime_minutes = models.PositiveIntegerField("Downtime (min)", default=0)
    labor_cost = models.DecimalField(
        "Labour cost (USD)", max_digits=15, decimal_places=2, null=True, blank=True
    )
    parts_cost = models.DecimalField(
        "Parts cost (USD)", max_digits=15, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField("Notes", blank=True)

    history = HistoricalRecords(excluded_fields=["created_at", "updated_at"])

    class Meta:
        verbose_name = "Repair log"
        verbose_name_plural = "Repair logs"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["equipment", "-started_at"])]

    def __str__(self) -> str:
        return f"{self.code} — {self.equipment.code}"

    def get_absolute_url(self) -> str:
        return reverse("repairs:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_sequence_code(type(self), "REP")
        super().save(*args, **kwargs)

    @property
    def total_cost(self):
        return (self.labor_cost or 0) + (self.parts_cost or 0)

    @property
    def status_badge_class(self) -> str:
        return {
            RepairStatus.IN_PROGRESS: "badge-info",
            RepairStatus.WAITING_PARTS: "badge-warning",
            RepairStatus.COMPLETED: "badge-success",
            RepairStatus.CANCELLED: "badge-muted",
        }.get(self.status, "badge-neutral")

    @property
    def duration_hours(self) -> float | None:
        if not self.finished_at:
            return None
        return round((self.finished_at - self.started_at).total_seconds() / 3600, 1)
