"""Shared data-table configuration."""

import django_tables2 as tables
from django.utils.html import format_html


class BaseTable(tables.Table):
    """
    Base table for every list screen.

    Kept in one place so a change to table styling lands everywhere at once
    instead of being repeated across nine modules.
    """

    class Meta:
        attrs = {"class": "data-table"}
        template_name = "tables/table.html"
        empty_text = "Nothing matches these filters."
        per_page = 25


class BadgeColumn(tables.Column):
    """
    Renders the value as a coloured pill.

    The colour comes from the record's ``<column>_badge_class`` property, so
    changing the palette means editing the model, not every table.
    """

    def __init__(self, *args, badge_attr: str | None = None, **kwargs):
        self.badge_attr = badge_attr
        super().__init__(*args, **kwargs)

    def render(self, value, record, bound_column):
        attr = self.badge_attr or f"{bound_column.name}_badge_class"
        css = getattr(record, attr, "badge-neutral")
        display = getattr(record, f"get_{bound_column.name}_display", None)
        label = display() if callable(display) else value
        return format_html('<span class="badge {}">{}</span>', css, label)


class MonoColumn(tables.Column):
    """Monospaced column for identifiers — asset IDs, part numbers, serials."""

    def render(self, value):
        return format_html('<span class="mono">{}</span>', value)
