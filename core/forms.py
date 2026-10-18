"""Shared form widgets and mixins."""

from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import format_html, format_html_join


class DateInput(forms.DateInput):
    """
    The browser's native date picker.

    Browsers always submit yyyy-mm-dd but display the date in the viewer's own
    locale, so the format here must be ISO while DATE_INPUT_FORMATS in
    settings accepts both shapes.
    """

    input_type = "date"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs, format or "%Y-%m-%d")


class DateTimeInput(forms.DateTimeInput):
    """The browser's native date-and-time picker."""

    input_type = "datetime-local"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs, format or "%Y-%m-%dT%H:%M")


def retire_field(form, noun: str) -> None:
    """
    The "Active" tick only matters once something exists: it retires an entry
    without deleting it. Hide it on create; explain it on edit.
    """
    if "is_active" not in form.fields:
        return
    if not form.instance.pk:
        del form.fields["is_active"]
        return
    field = form.fields["is_active"]
    field.label = "Still in use"
    field.help_text = (
        f"Untick to retire this {noun}: it keeps its history but is no longer "
        "offered in dropdowns. Delete it instead if it was entered by mistake."
    )


class RequestFormMixin:
    """Receives the request from the view so the form knows who is acting."""

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)


class StagedPhoto(str):
    """The token of a photo uploaded ahead of its form (see core.photos.stage_upload)."""


class PhotoPicker(forms.FileInput):
    """
    One button for several pictures. ``accept="image/*"`` is what makes a
    phone offer both the camera and the gallery; a PC opens its file browser.
    (``capture`` is left off on purpose: it would force the camera.)

    Each picture is uploaded as soon as it is picked (app.js) and comes back
    with the form as a token in ``<name>__staged``; the previews below the
    button are drawn here too, so a form returned with an error keeps them.
    """

    allow_multiple_selected = True

    def __init__(self, attrs=None):
        super().__init__({"accept": "image/*", "multiple": True, "data-photo-stage": True, **(attrs or {})})

    def value_from_datadict(self, data, files, name):
        from .photos import STAGE_TOKEN

        picked = list(super().value_from_datadict(data, files, name) or [])
        tokens = data.getlist(f"{name}__staged") if hasattr(data, "getlist") else []
        return picked + [StagedPhoto(t) for t in dict.fromkeys(tokens) if STAGE_TOKEN.match(t)]

    def value_omitted_from_data(self, data, files, name):
        return super().value_omitted_from_data(data, files, name) and not (
            hasattr(data, "getlist") and data.getlist(f"{name}__staged")
        )

    def render(self, name, value, attrs=None, renderer=None):
        picker = super().render(name, None, attrs, renderer)
        return format_html("{}{}", picker, photo_stage_html(name, value, (attrs or {}).get("id", "")))


def photo_stage_html(name, value, input_id):
    """
    The previews under a photo picker, with the photos already sent ahead.

    The forms rendered by crispy draw the picker from crispy's own template,
    so they put this in with ``{{ form.photos|photo_stage }}``.
    """
    from django.urls import reverse

    staged = [v for v in (value or []) if isinstance(v, StagedPhoto)] if isinstance(value, (list, tuple)) else []
    items = format_html_join(
        "",
        '<div class="photo-stage-item is-done"><img src="{}" alt="">'
        '<input type="hidden" name="{}__staged" value="{}">'
        '<button type="button" data-photo-unstage title="Take this photo out" aria-label="Take this photo out">'
        '<i class="bi bi-x-lg"></i></button></div>',
        ((reverse("photo_staged", args=[token]), name, token) for token in staged),
    )
    return format_html('<div class="photo-stage" data-photo-stage-for="{}">{}</div>', input_id, items)


class PhotosField(forms.FileField):
    """Pictures picked on a create or edit form, each checked before the save."""

    widget = PhotoPicker

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("label", "Add photos")
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        from .photos import MAX_FILES, check_image, staged_file

        items = [f for f in (data if isinstance(data, (list, tuple)) else [data]) if f]
        if len(items) > MAX_FILES:
            raise ValidationError(f"At most {MAX_FILES} photos at a time.")
        cleaned = []
        for item in items:
            if isinstance(item, StagedPhoto):
                upload = staged_file(item)
                if upload is None:
                    raise ValidationError("A photo sent earlier is no longer on the server. Add it again.")
            else:
                upload = super().clean(item, initial)
                check_image(upload)
            cleaned.append(upload)
        return cleaned

    def bound_data(self, data, initial):
        return data          # the staged tokens, so a returned form shows them again


class PhotoRemovalWidget(forms.SelectMultiple):
    """
    The record's photos as thumbnails, each with an × that marks it for removal.

    The same markup the equipment and spare part forms write by hand, for
    forms that are rendered whole (``{{ form|crispy }}``).
    """

    photos = ()

    def render(self, name, value, attrs=None, renderer=None):
        chosen = {str(item) for item in (value or [])}
        return format_html(
            '<div class="form-photos">{}</div>',
            format_html_join(
                "",
                '<label class="form-photo" title="tick × to delete on save">'
                '<input type="checkbox" name="{}" value="{}"{}>'
                '<img src="{}" alt="">'
                '<span class="form-photo-x" aria-label="Delete this photo"><i class="bi bi-x-lg"></i></span>'
                '<span class="form-photo-gone">Deleted on save</span></label>',
                (
                    (name, photo.pk, " checked" if str(photo.pk) in chosen else "",
                     (photo.thumbnail or photo.file).url)
                    for photo in self.photos
                ),
            ),
        )


def photos_to_remove_field() -> forms.MultipleChoiceField:
    """The photos already on the record, to tick for removal; ticked ones go on save."""
    return forms.MultipleChoiceField(required=False, label="Photos", widget=PhotoRemovalWidget)


def offer_photo_removal(form, field: str = "remove_photos", attr: str = "photos") -> None:
    photos = list(getattr(form.instance, attr)) if form.instance.pk else []
    form.fields[field].choices = [(str(photo.pk), str(photo.pk)) for photo in photos]
    form.fields[field].widget.photos = photos
