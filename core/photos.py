"""
Photos of equipment and spare parts.

Stored as attachments of kind PHOTO. Each upload is checked to be a real image,
turned upright (phone EXIF), shrunk to at most 1600 px and saved as JPEG, with a
360 px thumbnail for lists and panels. The first photo of a record becomes its
main photo; any other can be promoted.

Uploaded files are served only to signed-in users (``serve_upload``).
"""

import io
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.static import serve
from PIL import Image, ImageOps, UnidentifiedImageError

from .mixins import CanManageMixin, CanRecordMixin
from .models import Attachment, AttachmentKind

# Records that may carry photos: "app_label.model" as in the URL.
PHOTO_MODELS = {"equipment.equipment", "inventory.inventoryitem", "maintenance.maintenancerecord"}
MAX_SIDE = 1600
THUMB_SIDE = 360
MAX_FILES = 10


def _jpeg(image: Image.Image, side: int) -> ContentFile:
    copy = image.copy()
    copy.thumbnail((side, side))
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=85, optimize=True)
    return ContentFile(buffer.getvalue())


def check_image(upload) -> None:
    """Refuse anything too large or not a picture, before anything is saved."""
    limit = settings.EMA_MAX_UPLOAD_MB * 1024 * 1024
    if upload.size > limit:
        raise ValidationError(f"{upload.name} is larger than {settings.EMA_MAX_UPLOAD_MB} MB.")
    try:
        with Image.open(upload) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValidationError(f"{upload.name} is not an image.")
    finally:
        upload.seek(0)


def remove_photos(obj, photo_ids, kind=AttachmentKind.PHOTO) -> int:
    """Delete the ticked-off photos of ``obj``; another one takes over as main photo."""
    if not photo_ids:
        return 0
    content_type = ContentType.objects.get_for_model(obj)
    doomed = Attachment.objects.filter(
        content_type=content_type, object_id=obj.pk, kind=kind, pk__in=photo_ids
    )
    count = 0
    for photo in doomed:
        photo.delete()          # the post_delete signal takes the files too
        count += 1
    left = Attachment.objects.filter(content_type=content_type, object_id=obj.pk, kind=kind)
    if left.exists() and not left.filter(is_primary=True).exists():
        make_primary(left.order_by("created_at").first())
    return count


def save_photos(obj, uploads, user, kind=AttachmentKind.PHOTO) -> int:
    """Store the photos picked on a form. Returns how many were saved."""
    saved = 0
    for upload in uploads or []:
        save_photo(obj, upload, user, kind=kind)
        saved += 1
    return saved


def save_photo(obj, upload, user, kind=AttachmentKind.PHOTO) -> Attachment:
    """Check, shrink and store one uploaded image as a photo of ``obj``."""
    check_image(upload)
    try:
        image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError):
        raise ValidationError(f"{upload.name} is not an image.")
    image = ImageOps.exif_transpose(image).convert("RGB")

    base = os.path.splitext(os.path.basename(upload.name))[0][:100] or "photo"
    content_type = ContentType.objects.get_for_model(obj)
    has_main = Attachment.objects.filter(
        content_type=content_type, object_id=obj.pk, kind=kind, is_primary=True
    ).exists()
    photo = Attachment(
        content_type=content_type,
        object_id=obj.pk,
        kind=kind,
        original_name=upload.name[:255],
        uploaded_by=user if getattr(user, "is_authenticated", False) else None,
        is_primary=not has_main,
    )
    full = _jpeg(image, MAX_SIDE)
    photo.size_bytes = full.size
    photo.file.save(f"{base}.jpg", full, save=False)
    photo.thumbnail.save(f"{base}-thumb.jpg", _jpeg(image, THUMB_SIDE), save=False)
    photo.save()
    return photo


@transaction.atomic
def make_primary(photo: Attachment):
    Attachment.objects.filter(
        content_type=photo.content_type_id, object_id=photo.object_id, kind=photo.kind
    ).exclude(pk=photo.pk).update(is_primary=False)
    photo.is_primary = True
    photo.save(update_fields=["is_primary", "updated_at"])


@receiver(post_delete, sender=Attachment)
def remove_files(sender, instance, **kwargs):
    """A deleted attachment takes its files with it (also when its record is deleted)."""
    for field in (instance.file, instance.thumbnail):
        if field and field.name:
            field.storage.delete(field.name)


def _target(app_label, model, pk):
    key = f"{app_label}.{model}".lower()
    if key not in PHOTO_MODELS:
        raise ValueError("Photos are not kept for this kind of record.")
    content_type = ContentType.objects.get_by_natural_key(app_label, model)
    return get_object_or_404(content_type.model_class(), pk=pk)


PHOTO_KINDS = {AttachmentKind.PHOTO, AttachmentKind.NAMEPLATE}


class PhotoUploadView(CanRecordMixin, View):
    def post(self, request, app_label, model, pk, kind=AttachmentKind.PHOTO):
        try:
            obj = _target(app_label, model, pk)
        except (ValueError, ContentType.DoesNotExist):
            return redirect("dashboard")
        files = request.FILES.getlist("photos")[:MAX_FILES]
        saved, problems = 0, []
        for upload in files:
            try:
                save_photo(obj, upload, request.user, kind=kind)
                saved += 1
            except ValidationError as error:
                problems.append(error.messages[0])
        noun = "nameplate photo" if kind == AttachmentKind.NAMEPLATE else "photo"
        if saved:
            messages.success(request, f"Added {saved} {noun}{'s' if saved != 1 else ''}.")
        for problem in problems:
            messages.error(request, problem)
        if not files:
            messages.error(request, "Choose one or more image files first.")
        anchor = "#nameplate" if kind == AttachmentKind.NAMEPLATE else "#photos"
        return redirect(obj.get_absolute_url() + anchor)


class PhotoPrimaryView(CanRecordMixin, View):
    def post(self, request, pk):
        photo = get_object_or_404(Attachment, pk=pk, kind__in=PHOTO_KINDS)
        make_primary(photo)
        anchor = "#nameplate" if photo.kind == AttachmentKind.NAMEPLATE else "#photos"
        return redirect(photo.content_object.get_absolute_url() + anchor)


class PhotoDeleteView(CanManageMixin, View):
    def post(self, request, pk):
        photo = get_object_or_404(Attachment, pk=pk, kind__in=PHOTO_KINDS)
        owner = photo.content_object
        was_main, kind = photo.is_primary, photo.kind
        photo.delete()
        if was_main and owner is not None:
            remaining = owner.nameplate_photos if kind == AttachmentKind.NAMEPLATE else owner.photos
            if remaining:
                make_primary(remaining[0])
        messages.success(request, "Photo deleted.")
        anchor = "#nameplate" if kind == AttachmentKind.NAMEPLATE else "#photos"
        return redirect(owner.get_absolute_url() + anchor) if owner else redirect("dashboard")


@login_required
def serve_upload(request, path):
    """Uploaded files, for signed-in users only."""
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Cache-Control"] = "private, max-age=86400"
    return response
