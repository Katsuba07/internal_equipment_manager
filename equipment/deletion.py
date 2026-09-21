"""
Deleting assets in one action.

Maintenance, calibration, repair and incident logs point at their asset with
PROTECT, so a plain ``asset.delete()`` refuses as soon as an asset has any
history. The delete screens promise that the history goes with the asset; this
is where that promise is kept — the logs first, then the assets, in one
transaction.
"""

from django.apps import apps
from django.db import transaction

from .models import Equipment

# Logs that hold their asset with PROTECT, deleted ahead of it.
PROTECTING_LOGS = (
    "repairs.RepairRecord",
    "incidents.IncidentReport",
    "maintenance.MaintenanceRecord",
    "calibration.CalibrationRecord",
)


def history_counts(asset_ids) -> dict[str, int]:
    """How many log rows would go with these assets, by kind — for the confirm page."""
    counts = {}
    for label in PROTECTING_LOGS:
        model = apps.get_model(label)
        count = model.objects.filter(equipment_id__in=asset_ids).count()
        if count:
            counts[model._meta.verbose_name_plural.capitalize()] = count
    return counts


@transaction.atomic
def delete_assets(assets) -> int:
    """Delete these assets and everything recorded against them. Returns how many."""
    ids = list(assets.values_list("pk", flat=True)) if hasattr(assets, "values_list") else [a.pk for a in assets]
    for label in PROTECTING_LOGS:
        apps.get_model(label).objects.filter(equipment_id__in=ids).delete()
    # Photos and other files go through the generic relation; fittings,
    # plans, parts lists and status history cascade from the asset itself.
    deleted = 0
    for asset in Equipment.objects.filter(pk__in=ids):
        asset.delete()
        deleted += 1
    return deleted
