"""Shared form widgets and mixins."""

from django import forms
from django.core.exceptions import ValidationError


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

    @property
    def current_user(self):
        user = getattr(self.request, "user", None)
        return user if getattr(user, "is_authenticated", False) else None


class PhotoPicker(forms.FileInput):
    """
    One button for several pictures. ``accept="image/*"`` is what makes a
    phone offer both the camera and the gallery; a PC opens its file browser.
    (``capture`` is left off on purpose: it would force the camera.)
    """

    allow_multiple_selected = True

    def __init__(self, attrs=None):
        # data-photo-stage: each pick is added to the ones before (app.js), so
        # a phone can take photo after photo instead of replacing the last.
        super().__init__({"accept": "image/*", "multiple": True, "data-photo-stage": True, **(attrs or {})})


class PhotosField(forms.FileField):
    """Pictures picked on a create or edit form, each checked before the save."""

    widget = PhotoPicker

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("label", "Add photos")
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        from .photos import MAX_FILES, check_image

        files = [f for f in (data if isinstance(data, (list, tuple)) else [data]) if f]
        if len(files) > MAX_FILES:
            raise ValidationError(f"At most {MAX_FILES} photos at a time.")
        cleaned = []
        for upload in files:
            upload = super().clean(upload, initial)
            check_image(upload)
            cleaned.append(upload)
        return cleaned


def photos_to_remove_field() -> forms.MultipleChoiceField:
    """Tick boxes over the photos already on the record; ticked ones go on save."""
    return forms.MultipleChoiceField(required=False, label="", widget=forms.CheckboxSelectMultiple)


def offer_photo_removal(form, field: str = "remove_photos", attr: str = "photos") -> None:
    photos = getattr(form.instance, attr) if form.instance.pk else []
    form.fields[field].choices = [(str(photo.pk), str(photo.pk)) for photo in photos]
