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
            record.ident,
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


def labelled_toggle(record, can_change):
    """The "label is on it" tick box; ticking it saves at once (htmx)."""
    if not can_change:
        return format_html(
            '<input type="checkbox" class="label-tick" data-asset="{}" disabled{} aria-label="Labelled">',
            record.pk, " checked" if record.labelled else "",
        )
    # data-asset lets a label printed from the pop-up tick it in place (app.js).
    return format_html(
        '<input type="checkbox" class="label-tick" data-asset="{}" name="labelled" value="1"{} '
        'hx-post="{}" hx-trigger="change" hx-swap="outerHTML" '
        'title="Tick once the label is on the asset" aria-label="Labelled">',
        record.pk, " checked" if record.labelled else "",
        reverse("equipment:labelled", args=[record.pk]),
    )


def W(width):
    """A column's fixed width."""
    return {"th": {"style": f"width:{width}"}}


class EquipmentTable(BaseTable):
    # Tick boxes for "Delete selected"; the list view drops the column for
    # anyone who is not an administrator.
    select = tables.CheckBoxColumn(
        accessor="pk", orderable=False,
        attrs={
            "th": {"class": "col-select", "style": "width:2.4rem"}, "td": {"class": "col-select"},
            "th__input": {"data-bulk-all": "", "aria-label": "Select all on this page"},
            "td__input": {"data-bulk": "", "aria-label": "Select"},
        },
    )
    # empty_values=(): the accessor is the ZT Code, often still blank, but the
    # cell shows the Equipment No — it must render, not fall back to "—".
    code = AssetColumn(verbose_name="Equipment No", order_by=("equipment_no", "code"), empty_values=())
    # Each column keeps a fixed width (the table is laid out "fixed"), so
    # choosing a filter or typing a search never makes the columns jump.
    # The asset column takes whatever width is left.
    zt_code = SerialColumn(verbose_name="ZT Code", accessor="code", empty_values=(), order_by=("code",), attrs=W("7.5rem"))
    asset_no = SerialColumn(verbose_name="Asset No.", empty_values=(), order_by=("asset_no",), attrs=W("9rem"))
    serial_number = SerialColumn(verbose_name="S/N", empty_values=(), order_by=("serial_number",), attrs=W("9.5rem"))
    category = tables.Column(verbose_name="Category", accessor="category__name", attrs=W("10rem"))
    products = ProductsColumn(
        verbose_name="Used for", orderable=False, empty_values=(), accessor="pk", attrs=W("8rem"),
    )
    plant = tables.Column(verbose_name="Plant", accessor="plant", orderable=True, attrs=W("6.5rem"))
    status = BadgeColumn(verbose_name="Status", attrs=W("10.5rem"))
    labelled = tables.Column(verbose_name="Label", orderable=True, empty_values=(),
                             attrs={"th": {"style": "width:7rem"}, "td": {"style": "text-align:center"}})
    is_measuring_device = tables.Column(
        verbose_name="Calibration", orderable=True, empty_values=(), attrs=W("9.5rem"),
    )

    class Meta(BaseTable.Meta):
        model = Equipment
        # The fixed columns take about 80rem; the asset column keeps 12rem.
        attrs = {"class": "data-table fixed-cols", "style": "--table-min:92rem"}
        # Clicking a row opens the quick-look drawer (see app.js).
        row_attrs = {"data-preview-url": lambda record: reverse("equipment:preview", args=[record.pk])}
        fields = ("code", "zt_code", "asset_no", "serial_number", "category", "plant", "products", "status", "labelled", "is_measuring_device")
        sequence = ("select", "...")
        order_by = "code"           # the asset column, sorted by Equipment No

    def render_labelled(self, value, record):
        user = getattr(getattr(self, "request", None), "user", None)
        return labelled_toggle(record, can_change=bool(user and getattr(user, "can_record", False)))

    def render_is_measuring_device(self, value, record):
        if not record.is_measuring_device:
            return format_html('<span class="cell-muted">—</span>')
        if record.calibration_date_unknown:
            return format_html('<span class="badge badge-danger" title="No due date on record: do not measure '
                               'with it until it is calibrated and the dates entered">Date unknown</span>')
        # Where it stands, not just that it needs it: days left, due soon, or overdue.
        plan = min((p for p in record.calibration_plans.all() if p.is_active and p.next_due_at),
                   key=lambda p: p.next_due_at)
        return format_html('<span class="badge {}" title="Calibration due {}">{}</span>',
                           plan.due_badge_class, plan.next_due_at.strftime("%d/%m/%Y"), plan.due_display)
