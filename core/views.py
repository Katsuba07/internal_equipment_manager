"""Dashboard and other shared screens."""

import calendar as calendar_module
from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.utils import timezone
from django.views.generic import TemplateView

from calibration.models import CalibrationPlan
from core.activity import recent_activity
from core.models import Plant
from equipment.models import Equipment, EquipmentStatus
from incidents.models import IncidentReport
from inventory.models import InventoryItem
from maintenance.models import MaintenancePlan
from systems.services import busy_map, line_status


# How many rows each dashboard panel loads. The panels are a fixed height and
# scroll, so this is about query cost rather than what fits on screen.
PANEL_LIMIT = 40
ACTIVITY_LIMIT = 40          # the panel scrolls; the Activity page shows more


CALENDAR_DAY_LIMIT = 3  # chips shown before a day collapses to "+N more"


def _due_calendar(first_of_month, calibration_qs, maintenance_qs, fitted):
    """
    Weeks of the displayed month (Monday-first, with padding days from the
    adjacent months so every week is a full row), each day carrying the
    calibration and maintenance plans due that date.
    """
    weeks = calendar_module.Calendar(firstweekday=0).monthdatescalendar(
        first_of_month.year, first_of_month.month
    )
    grid_start, grid_end = weeks[0][0], weeks[-1][-1]
    today = timezone.localdate()

    by_day = {}
    for kind, qs in (("calibration", calibration_qs), ("maintenance", maintenance_qs)):
        for plan in mark_fitted(qs.filter(next_due_at__range=(grid_start, grid_end)), fitted):
            by_day.setdefault(plan.next_due_at, []).append({"kind": kind, "plan": plan})

    rows = []
    for week in weeks:
        row = []
        for day in week:
            items = by_day.get(day, [])
            row.append({
                "date": day,
                "in_month": day.month == first_of_month.month,
                "is_today": day == today,
                "items": items[:CALENDAR_DAY_LIMIT],
                "overflow": max(0, len(items) - CALENDAR_DAY_LIMIT),
            })
        rows.append(row)
    return rows


def _due_list(calibration_qs, maintenance_qs, fitted, limit):
    """
    Every active plan, soonest due (or most overdue) first, regardless of
    month — the calendar only shows one month at a time, so this is how the
    full picture of what needs calibration or maintenance stays reachable.
    """
    entries = [
        {"kind": kind, "plan": plan}
        for kind, qs in (("calibration", calibration_qs), ("maintenance", maintenance_qs))
        for plan in mark_fitted(qs, fitted)
    ]
    entries.sort(key=lambda entry: entry["plan"].next_due_at or date.max)
    return entries[:limit]


def mark_fitted(items, fitted):
    """Note on each row which set its asset sits in, so the to-do lists link to the line."""
    items = list(items)
    for item in items:
        item.fitted_in = fitted.get(item.equipment_id, "")
    return items


class DashboardView(LoginRequiredMixin, TemplateView):
    """
    Floor overview.

    Reads from every module, including ones that do not have their own screens
    yet — data entered through the admin still surfaces here.
    """

    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        next_week = today + timedelta(days=7)
        next_month = today + timedelta(days=30)

        equipment = Equipment.objects.all()
        counts = {
            row["status"]: row["count"]
            for row in equipment.values("status").annotate(count=Count("id"))
        }
        total = equipment.count()

        context["total_equipment"] = total
        context["measuring_count"] = equipment.filter(is_measuring_device=True).count()
        context["in_production_count"] = counts.get(EquipmentStatus.IN_PRODUCTION, 0)
        context["down_count"] = (
            counts.get(EquipmentStatus.DOWN, 0)
            + counts.get(EquipmentStatus.REPAIR, 0)
        )

        # --- Things that need attention ---
        maintenance = MaintenancePlan.objects.filter(is_active=True).select_related(
            "equipment"
        )
        context["maintenance_overdue_count"] = maintenance.filter(next_due_at__lt=today).count()
        context["maintenance_due_count"] = maintenance.filter(next_due_at__lte=next_week).count()
        fitted = busy_map()

        calibration = CalibrationPlan.objects.filter(is_active=True).select_related(
            "equipment"
        )
        context["calibration_overdue_count"] = calibration.filter(next_due_at__lt=today).count()
        context["calibration_due_count"] = calibration.filter(next_due_at__lte=next_month).count()

        # Calibration and maintenance due dates, as a navigable month calendar
        # (see dashboard.html) — easier to plan around than a flat list.
        month_param = self.request.GET.get("month", "")
        try:
            cal_year, cal_month = (int(part) for part in month_param.split("-", 1))
            calendar_first = date(cal_year, cal_month, 1)
        except (TypeError, ValueError):
            calendar_first = today.replace(day=1)
        context["calendar_weeks"] = _due_calendar(calendar_first, calibration, maintenance, fitted)
        context["calendar_month_label"] = calendar_first.strftime("%B %Y")
        context["calendar_is_current_month"] = calendar_first == today.replace(day=1)
        prev_month = (calendar_first - timedelta(days=1)).replace(day=1)
        next_month_first = (calendar_first.replace(day=28) + timedelta(days=4)).replace(day=1)
        context["calendar_prev"] = prev_month.strftime("%Y-%m")
        context["calendar_next"] = next_month_first.strftime("%Y-%m")
        context["due_list"] = _due_list(calibration, maintenance, fitted, PANEL_LIMIT)
        context["due_list_count"] = calibration.count() + maintenance.count()

        open_incidents = IncidentReport.objects.open().select_related("equipment")
        context["open_incident_count"] = open_incidents.count()
        context["open_incidents"] = mark_fitted(open_incidents.order_by("-reported_at")[:PANEL_LIMIT], fitted)

        low_stock = InventoryItem.objects.below_minimum()
        context["low_stock_count"] = low_stock.count()
        context["low_stock_items"] = low_stock.order_by("code")[:PANEL_LIMIT]

        # --- Plant split and the spare parts side of the house ---
        by_plant = {
            row["plant"]: row["count"]
            for row in equipment.values("plant").annotate(count=Count("id"))
        }
        parts = InventoryItem.objects.filter(is_active=True)
        parts_by_plant = {
            row["plant"]: row["count"] for row in parts.values("plant").annotate(count=Count("id"))
        }
        context["plants"] = [
            {
                "code": value, "label": label,
                "assets": by_plant.get(value, 0), "parts": parts_by_plant.get(value, 0),
            }
            for value, label in Plant.choices
        ]
        context["part_count"] = parts.count()
        context["out_of_stock_count"] = parts.filter(quantity_on_hand__lte=0).count()
        context["maintenance_required_count"] = equipment.filter(maintenance_required=True).count()

        context["activity"] = recent_activity(ACTIVITY_LIMIT)
        context["line"] = line_status()

        context["attention_total"] = (
            context["line"]["sets_bad"]
            + len(context["line"]["golden_warnings"])
            + context["maintenance_overdue_count"]
            + context["calibration_overdue_count"]
            + context["open_incident_count"]
            + context["low_stock_count"]
        )
        return context


ACTIVITY_KINDS = [
    ("", "Everything"),
    ("equipment", "Equipment"),
    ("part", "Spare parts"),
    ("set", "Fitted / removed"),
    ("record", "Maintenance, calibration, incidents, documents"),
]


class ActivityView(LoginRequiredMixin, TemplateView):
    """The longer list behind the Overview's Recent activity panel."""

    template_name = "core/activity.html"
    limit = 300

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        kind = self.request.GET.get("kind", "")
        if kind not in dict(ACTIVITY_KINDS):
            kind = ""
        context.update(
            kind=kind, kinds=ACTIVITY_KINDS, limit=self.limit,
            activity=recent_activity(self.limit, [kind] if kind else None),
        )
        return context
