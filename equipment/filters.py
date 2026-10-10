"""Filters for the equipment list."""

import django_filters
from django import forms
from django.db.models import Q
from django.urls import reverse_lazy

from core.models import Category, Location, Plant

from .models import Equipment, EquipmentStatus

SELECT_ATTRS = {"class": "form-select"}
SEARCH_ATTRS = {
    "class": "search-input",
    "placeholder": "Search ZT code, equipment no., asset no., S/N, name...",
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
    """Search box plus the four filters people actually reach for."""

    q = django_filters.CharFilter(
        method="search", label="Search", widget=forms.TextInput(attrs=SEARCH_ATTRS)
    )
    category = django_filters.ModelChoiceFilter(
        queryset=Category.objects.active(),
        label="Category",
        empty_label="All categories",
        widget=forms.Select(attrs=SELECT_ATTRS),
    )
    location = django_filters.ModelChoiceFilter(
        queryset=Location.objects.active(),
        label="Location",
        empty_label="All locations",
        widget=forms.Select(attrs=SELECT_ATTRS),
    )
    plant = django_filters.ChoiceFilter(
        field_name="plant", label="Plant", choices=Plant.choices,
        empty_label="All plants", widget=forms.Select(attrs=SELECT_ATTRS),
    )
    status = django_filters.ChoiceFilter(
        choices=EquipmentStatus.choices,
        label="Status",
        empty_label="Any status",
        widget=forms.Select(attrs=SELECT_ATTRS),
    )
    serial = django_filters.ChoiceFilter(
        label="S/N", method="filter_serial", empty_label="Any S/N",
        choices=[("missing", "S/N missing"), ("set", "S/N entered")],
        widget=forms.Select(attrs=SELECT_ATTRS),
    )
    is_measuring_device = django_filters.BooleanFilter(
        label="Calibration",
        widget=forms.Select(
            attrs=SELECT_ATTRS,
            choices=[
                ("", "All equipment"),
                ("true", "Needs calibration"),
                ("false", "No calibration"),
            ],
        ),
    )

    class Meta:
        model = Equipment
        fields = ["q", "category", "location", "status", "is_measuring_device"]

    def filter_serial(self, queryset, name, value):
        """For reviewing serial numbers: the ones still to fill in, or the ones done."""
        if value == "missing":
            return queryset.filter(serial_number="")
        if value == "set":
            return queryset.exclude(serial_number="")
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
