"""Filters for the equipment list."""

import django_filters
from django import forms
from django.db.models import Q
from django.urls import reverse_lazy
from django.utils import timezone

from core.models import Category, Plant

from .models import Equipment, EquipmentStatus

SELECT_ATTRS = {"class": "form-select"}
SEARCH_ATTRS = {
    "class": "search-input",
    "placeholder": "Search equipment no., ZT code, asset no., S/N, name...",
    "autocomplete": "off",
    # Live results while typing, without a full page reload — see #results
    # in equipment_list.html.
    "hx-get": reverse_lazy("equipment:list"),
    "hx-trigger": "input changed delay:300ms",
    "hx-include": "closest form",
    "hx-target": "#results",
    "hx-select": "#results",
    "hx-swap": "outerHTML",
    "hx-push-url": "true",
}


class EquipmentFilter(django_filters.FilterSet):
    """
    Search box plus the filters people actually reach for.

    Each filter sits in the header of its own column (see ``HEADER_FILTERS`` in
    the list view), so its empty choice reads as the column's title.
    """

    q = django_filters.CharFilter(
        method="search", label="Search", widget=forms.TextInput(attrs=SEARCH_ATTRS)
    )
    category = django_filters.ModelChoiceFilter(
        queryset=Category.objects.active(),
        label="Category",
        empty_label="Category",
        widget=forms.Select(attrs=SELECT_ATTRS),
    )
    plant = django_filters.ChoiceFilter(
        field_name="plant", label="Plant", choices=Plant.choices,
        empty_label="Plant", widget=forms.Select(attrs=SELECT_ATTRS),
    )
    status = django_filters.ChoiceFilter(
        choices=EquipmentStatus.choices,
        label="Status",
        empty_label="Status",
        widget=forms.Select(attrs=SELECT_ATTRS),
    )
    labelled = django_filters.BooleanFilter(
        label="Label",
        widget=forms.Select(attrs=SELECT_ATTRS, choices=[("", "Label"), ("true", "Labelled"), ("false", "Not labelled")]),
    )
    serial = django_filters.ChoiceFilter(
        label="S/N", method="filter_serial", empty_label="S/N",
        choices=[("missing", "S/N missing"), ("set", "S/N entered"), ("repeated", "S/N repeated")],
        widget=forms.Select(attrs=SELECT_ATTRS),
    )
    is_measuring_device = django_filters.ChoiceFilter(
        label="Calibration", method="filter_calibration", empty_label="Calibration",
        choices=[
            ("true", "Needs calibration"),
            ("unknown", "Date unknown"),
            ("overdue", "Overdue or unknown"),
            ("false", "No calibration"),
        ],
        widget=forms.Select(attrs=SELECT_ATTRS),
    )

    def filter_calibration(self, queryset, name, value):
        from calibration.models import CalibrationPlan

        if value == "true":
            return queryset.filter(is_measuring_device=True)
        if value == "false":
            return queryset.filter(is_measuring_device=False)
        unknown = queryset.calibration_date_unknown()
        if value == "unknown":
            return unknown
        if value == "overdue":
            late = CalibrationPlan.objects.filter(
                is_active=True, next_due_at__lt=timezone.localdate()).values("equipment_id")
            return queryset.filter(Q(pk__in=unknown.values("pk")) | Q(is_measuring_device=True, pk__in=late))
        return queryset

    class Meta:
        model = Equipment
        fields = ["q", "category", "plant", "status", "labelled", "is_measuring_device"]

    def filter_serial(self, queryset, name, value):
        """For reviewing serial numbers: the ones still to fill in, or the ones done."""
        if value == "missing":
            return queryset.filter(serial_number="")
        if value == "set":
            return queryset.exclude(serial_number="")
        if value == "repeated":
            # The same S/N on more than one asset (stand-ins like NA aside): a misread to put right.
            from django.db.models import Count

            from .forms import EquipmentForm

            repeated = (
                Equipment.objects.exclude(serial_number="").exclude(serial_number__in=EquipmentForm.NO_SERIAL)
                .values("serial_number").annotate(n=Count("id")).filter(n__gt=1).values("serial_number")
            )
            return queryset.filter(serial_number__in=repeated).order_by("serial_number", "equipment_no")
        return queryset

    def search(self, queryset, name, value):
        """One box searches every field people might remember."""
        value = value.strip()
        if not value:
            return queryset
        return queryset.filter(
            Q(code__icontains=value)
            | Q(equipment_no__icontains=value)
            | Q(asset_no__icontains=value)
            | Q(name__icontains=value)
            | Q(serial_number__icontains=value)
            | Q(model_number__icontains=value)
            | Q(manufacturer__icontains=value)
        )
