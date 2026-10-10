"""The equipment list table."""

import django_tables2 as tables
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from core.tables import BadgeColumn, BaseTable

from .models import Equipment


class AssetColumn(tables.Column):
    """Asset ID and name in one cell — two columns' worth of information
    without two columns' worth of horizontal space."""

    def render(self, value, record):
        # Only the ID navigates to the detail page; the name is plain text —
        # clicking it opens the row's quick-look preview instead (see app.js).
        return format_html(
            '<a class="mono cell-id" href="{}">{}</a>'
            '<span class="cell-sub">{}</span>',
            record.get_absolute_url(),
            record.code,
            record.name,
        )


class SerialColumn(tables.Column):
    """An identifier (asset number, serial) to read down the list. Changed through Edit only."""

    def render(self, value, record):
        return format_html('<span class="mono">{}</span>', value) if value else format_html(
            '<span class="cell-muted">—</span>'
        )


class ProductsColumn(tables.Column):
    """
    Which product codes this asset helps test.

    Derived from the sets it is fitted to, so a shared instrument shows every
    code it serves.
    """

    def render(self, value, record):
        codes = record.product_codes
        if not codes:
            return format_html('<span class="cell-muted">—</span>')

        shown = codes[:3]
        tags = format_html_join(
            "", '<span class="cell-tag">{}</span>', ((code,) for code in shown)
        )
        if len(codes) > len(shown):
            return format_html(
                '{}<span class="cell-tag">+{}</span>', tags, len(codes) - len(shown)
            )
        return tags


class EquipmentTable(BaseTable):
    # Tick boxes for "Delete selected"; the list view drops the column for
    # anyone who is not an administrator.
    select = tables.CheckBoxColumn(
        accessor="pk", orderable=False,
        attrs={
            "th": {"class": "col-select"}, "td": {"class": "col-select"},
            "th__input": {"data-bulk-all": "", "aria-label": "Select all on this page"},
            "td__input": {"data-bulk": "", "aria-label": "Select"},
        },
    )
    code = AssetColumn(verbose_name="ZT Code", order_by=("code",))
    equipment_no = SerialColumn(verbose_name="Equipment No", empty_values=(), order_by=("equipment_no",))
    asset_no = SerialColumn(verbose_name="Asset No.", empty_values=(), order_by=("asset_no",))
    serial_number = SerialColumn(verbose_name="S/N", empty_values=(), order_by=("serial_number",))
    category = tables.Column(verbose_name="Category", accessor="category__name")
    location = tables.Column(verbose_name="Location", accessor="location__name")
    products = ProductsColumn(
        verbose_name="Used for", orderable=False, empty_values=(), accessor="pk"
    )
    plant = tables.Column(verbose_name="Plant", accessor="plant", orderable=True)
    status = BadgeColumn(verbose_name="Status")
    is_measuring_device = tables.Column(
        verbose_name="Calibration", orderable=True, empty_values=()
    )

    class Meta(BaseTable.Meta):
        model = Equipment
        # Clicking a row opens the quick-look drawer (see app.js).
        row_attrs = {"data-preview-url": lambda record: reverse("equipment:preview", args=[record.pk])}
        fields = ("code", "equipment_no", "asset_no", "serial_number", "category", "plant", "location", "products", "status", "is_measuring_device")
        sequence = ("select", "...")
        order_by = "code"

    def render_is_measuring_device(self, value, record):
        if not record.is_measuring_device:
            return format_html('<span class="cell-muted">—</span>')
        return format_html('<span class="badge badge-outline">Required</span>')
