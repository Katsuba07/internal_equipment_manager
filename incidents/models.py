"""Equipment incident reports."""

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import AttachmentMixin, TimeStampedModel
from core.utils import next_sequence_code


class IncidentSeverity(models.TextChoices):
    LOW = "LOW", "Low — still usable"
    MEDIUM = "MEDIUM", "Medium — reduced throughput"
    HIGH = "HIGH", "High — line stopped"
    CRITICAL = "CRITICAL", "Critical — safety or escape risk"


class IncidentStatus(models.TextChoices):
    NEW = "NEW", "New"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    RESOLVED = "RESOLVED", "Resolved"
    CLOSED = "CLOSED", "Closed"


OPEN_INCIDENT_STATUSES = {
    IncidentStatus.NEW,
    IncidentStatus.ACKNOWLEDGED,
    IncidentStatus.IN_PROGRESS,
}


class IncidentQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=OPEN_INCIDENT_STATUSES)


class IncidentReport(AttachmentMixin, TimeStampedModel):
    """
    A fault reported against an asset.

    This is where the flow starts: report → acknowledge → repair job →
    close the incident.
    """

    code = models.CharField("Ticket", max_length=30, unique=True, blank=True)
    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="Equipment",
        on_delete=models.PROTECT,
        related_name="incidents",
    )
    title = models.CharField(
        "Title", max_length=200, help_text="Short description of the symptom."
    )
    description = models.TextField("Details")
    severity = models.CharField(
        "Severity",
        max_length=20,
        choices=IncidentSeverity.choices,
        default=IncidentSeverity.MEDIUM,
    )
    status = models.CharField(
        "Status",
        max_length=20,
        choices=IncidentStatus.choices,
        default=IncidentStatus.NEW,
        db_index=True,
    )
    stopped_production = models.BooleanField("Line stopped", default=False)
    affected_units = models.PositiveIntegerField(
        "Boards affected",
        null=True,
        blank=True,
        help_text="Optional. Units that may need re-test or containment.",
    )

    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Reported by",
        on_delete=models.SET_NULL,
        null=True,
        related_name="reported_incidents",
    )
    reported_at = models.DateTimeField("Occurred at", default=timezone.now)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Assigned to",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_incidents",
    )
    acknowledged_at = models.DateTimeField("Acknowledged at", null=True, blank=True)
    resolved_at = models.DateTimeField("Resolved at", null=True, blank=True)
    resolution = models.TextField("Resolution", blank=True)

    history = HistoricalRecords(excluded_fields=["created_at", "updated_at"])
    objects = IncidentQuerySet.as_manager()

    class Meta:
        verbose_name = "Incident report"
        verbose_name_plural = "Incident reports"
        ordering = ["-reported_at"]
        indexes = [
            models.Index(fields=["equipment", "-reported_at"]),
            models.Index(fields=["status", "-reported_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.title}"

    def get_absolute_url(self) -> str:
        return reverse("incidents:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_sequence_code(type(self), "INC")
        super().save(*args, **kwargs)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_INCIDENT_STATUSES

    @property
    def severity_badge_class(self) -> str:
        return {
            IncidentSeverity.LOW: "badge-neutral",
            IncidentSeverity.MEDIUM: "badge-info",
            IncidentSeverity.HIGH: "badge-warning",
            IncidentSeverity.CRITICAL: "badge-danger",
        }.get(self.severity, "badge-neutral")

    @property
    def status_badge_class(self) -> str:
        return {
            IncidentStatus.NEW: "badge-danger",
            IncidentStatus.ACKNOWLEDGED: "badge-warning",
            IncidentStatus.IN_PROGRESS: "badge-info",
            IncidentStatus.RESOLVED: "badge-success",
            IncidentStatus.CLOSED: "badge-muted",
        }.get(self.status, "badge-neutral")

    @property
    def response_hours(self) -> float | None:
        """Hours from report to acknowledgement — the response-time metric."""
        if not self.acknowledged_at:
            return None
        return round((self.acknowledged_at - self.reported_at).total_seconds() / 3600, 1)
