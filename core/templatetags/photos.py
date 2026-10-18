"""Template filters for photo pickers."""

from django import template

from core.forms import photo_stage_html

register = template.Library()


@register.filter
def photo_stage(bound_field):
    """The previews under a photo picker, keeping the photos sent ahead: {{ form.photos|photo_stage }}."""
    return photo_stage_html(bound_field.html_name, bound_field.value(), bound_field.id_for_label)
