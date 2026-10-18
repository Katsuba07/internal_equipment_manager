"""
What happened lately, from every log the app keeps, as one list.

Each event is a plain dict: when, who, code (the asset or part), url (None
when the thing is gone), tag + badge, and a one-line text. Sources:

* equipment and spare parts added, edited or deleted (their change history);
* status changes, fits and removals in a set;
* stock received, issued or counted;
* maintenance, calibration and incident records;
* documents added to SharePoint from the app.

An edit that only moved the status or the stock level is left out of the
"Edited" rows: the status change or the stock movement already says it.
"""

from django.urls import reverse

from calibration.models import CalibrationRecord
from equipment.models import Equipment, StatusHistory
from incidents.models import IncidentReport
from inventory.models import InventoryItem, StockTransaction, TransactionType
from maintenance.models import MaintenanceRecord
from systems.models import Installation, ProductDocument

# Fields whose change is shown by another kind of event.
QUIET_FIELDS = {
    Equipment: {"status", "status_changed_at"},
    InventoryItem: {"quantity_on_hand"},
}
DETAIL_URLS = {Equipment: "equipment:detail", InventoryItem: "inventory:part_detail"}
HISTORY_TAGS = {"+": ("Added", "badge-success"), "~": ("Edited", "badge-info"), "-": ("Deleted", "badge-danger")}
STOCK_TAGS = {
    TransactionType.IN: ("Received", "badge-success"),
    TransactionType.OUT: ("Issued", "badge-warning"),
    TransactionType.ADJUST: ("Counted", "badge-neutral"),
}


def _number(value) -> str:
    """12.00 -> '12', 1.50 -> '1.5'."""
    return f"{value:f}".rstrip("0").rstrip(".") if value is not None else ""


def _history_events(model, limit, kind):
    events = []
    alive = set(model.objects.values_list("pk", flat=True))
    ordered = model.history.select_related("history_user").order_by("-history_date", "-history_id")
    # Some edits are skipped, so look a little further back than the limit.
    records = list(ordered[: limit * 3])
    # The version before each edit, for every edited item in one query.
    previous_of = {}
    edited = {r.id for r in records if r.history_type == "~"}
    last_seen = {}
    for record in model.history.filter(id__in=edited).order_by("history_date", "history_id"):
        if record.id in last_seen:
            previous_of[record.history_id] = last_seen[record.id]
        last_seen[record.id] = record
    for record in records:
        tag, badge = HISTORY_TAGS.get(record.history_type, ("Changed", "badge-neutral"))
        text = record.name or ""
        if record.history_type == "~":
            previous = previous_of.get(record.history_id)
            if previous is not None:
                changed = [c.field for c in record.diff_against(previous).changes]
                changed = [f for f in changed if f not in QUIET_FIELDS.get(model, set())]
                if not changed:
                    continue
                labels = [str(model._meta.get_field(f).verbose_name) for f in changed]
                text = ", ".join(label[:1].upper() + label[1:] for label in labels)
        url = reverse(DETAIL_URLS[model], args=[record.id]) if record.id in alive and record.history_type != "-" else None
        events.append({
            "when": record.history_date, "who": record.history_user, "code": getattr(record, "equipment_no", "") or record.code, "url": url,
            "tag": tag, "badge": badge, "text": text, "kind": kind,
        })
        if len(events) >= limit:
            break
    return events


def recent_activity(limit=40, kinds=None):
    """The latest ``limit`` events, newest first. ``kinds`` narrows to equipment/part/set/record."""
    want = set(kinds or ["equipment", "part", "set", "record"])
    events = []

    if "equipment" in want:
        events += _history_events(Equipment, limit, "equipment")
        changes = StatusHistory.objects.exclude(from_status="")   # the first one is the "Added" row
        for change in changes.select_related("equipment", "changed_by").order_by("-created_at")[:limit]:
            events.append({
                "when": change.created_at, "who": change.changed_by, "code": change.equipment.ident,
                "url": change.equipment.get_absolute_url(), "kind": "equipment",
                "badge": change.to_status_badge_class, "tag": change.get_to_status_display(),
                "text": change.reason,
            })

    if "set" in want:
        fits = Installation.objects.select_related(
            "component", "installed_by", "removed_by",
            "test_set__product_process__product", "test_set__product_process__process",
        )
        for inst in fits.order_by("-installed_at")[:limit]:
            events.append({
                "when": inst.installed_at, "who": inst.installed_by, "code": inst.component.ident,
                "url": inst.component.get_absolute_url(), "kind": "set",
                "badge": "badge-primary", "tag": "Fitted", "text": f"in {inst.where}",
            })
        for inst in fits.filter(removed_at__isnull=False).order_by("-removed_at")[:limit]:
            events.append({
                "when": inst.removed_at, "who": inst.removed_by, "code": inst.component.ident,
                "url": inst.component.get_absolute_url(), "kind": "set",
                "badge": "badge-neutral", "tag": "Removed", "text": f"from {inst.where}",
            })

    if "part" in want:
        events += _history_events(InventoryItem, limit, "part")
        moves = StockTransaction.objects.select_related("item", "performed_by", "equipment")
        for move in moves.order_by("-occurred_at", "-created_at")[:limit]:
            tag, badge = STOCK_TAGS.get(move.transaction_type, ("Moved", "badge-neutral"))
            text = f"{_number(move.quantity)} {move.item.unit or ''}".strip()
            if move.equipment_id:
                text += f" to {move.equipment.ident}"
            text += f" · balance {_number(move.quantity_after)}"
            if move.reason:
                text += f" · {move.reason}"
            events.append({
                "when": move.occurred_at, "who": move.performed_by, "code": move.item.code,
                "url": move.item.get_absolute_url(), "kind": "part",
                "tag": tag, "badge": badge, "text": text,
            })

    if "record" in want:
        for record in MaintenanceRecord.objects.select_related("equipment", "performed_by").order_by("-created_at")[:limit]:
            events.append({
                "when": record.created_at, "who": record.performed_by, "code": record.equipment.ident,
                "url": record.get_absolute_url(), "kind": "record",
                "tag": "Maintenance", "badge": "badge-info", "text": record.work_done,
            })
        for record in CalibrationRecord.objects.select_related("equipment", "performed_by").order_by("-created_at")[:limit]:
            events.append({
                "when": record.created_at, "who": record.performed_by, "code": record.equipment.ident,
                "url": record.get_absolute_url(), "kind": "record",
                "tag": "Calibrated", "badge": "badge-info", "text": record.get_result_display(),
            })
        for report in IncidentReport.objects.select_related("equipment", "reported_by").order_by("-created_at")[:limit]:
            events.append({
                "when": report.created_at, "who": report.reported_by, "code": report.equipment.ident,
                "url": report.get_absolute_url(), "kind": "record",
                "tag": "Incident", "badge": "badge-danger", "text": report.title,
            })
        docs = ProductDocument.objects.exclude(uploaded_by=None).select_related("uploaded_by").prefetch_related("products")
        for doc in docs.order_by("-updated_at")[:limit]:
            product = next(iter(doc.products.all()), None)
            events.append({
                "when": doc.updated_at, "who": doc.uploaded_by, "code": product.code if product else "—",
                "url": reverse("systems:products") + f"?product={product.pk}" if product else None,
                "kind": "record", "tag": "Document", "badge": "badge-primary", "text": doc.file_name,
            })

    events.sort(key=lambda e: e["when"], reverse=True)
    return events[:limit]
