"""Foundation models: users, shared catalogs, and file attachments."""

import os
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    """The four roles that can use the system."""

    ADMIN = "ADMIN", "Administrator"
    MANAGER = "MANAGER", "Manager"
    TECHNICIAN = "TECHNICIAN", "Technician"
    VIEWER = "VIEWER", "Viewer"


class User(AbstractUser):
    """
    A system user.

    Uses a single ``full_name`` field instead of Django's first/last name pair,
    because many names this system will hold do not split naturally in two.
    """

    full_name = models.CharField("Full name", max_length=150, blank=True)
    employee_code = models.CharField(
        "Employee ID", max_length=30, blank=True, null=True, unique=True
    )
    department = models.CharField("Department", max_length=100, blank=True)
    phone = models.CharField("Phone", max_length=30, blank=True)
    role = models.CharField(
        "Role", max_length=20, choices=Role.choices, default=Role.VIEWER
    )

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["full_name", "username"]

    def __str__(self) -> str:
        return self.full_name or self.username

    def save(self, *args, **kwargs):
        # Administrators get the Django admin site; other roles do not.
        if self.role == Role.ADMIN:
            self.is_staff = True
        elif not self.is_superuser:
            self.is_staff = False
        super().save(*args, **kwargs)

    def has_perm(self, perm, obj=None) -> bool:
        # The Administrator role runs the admin site in full — view, change and
        # delete — without anyone having to tick a hundred permission boxes.
        if self.is_active and self.role == Role.ADMIN:
            return True
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label) -> bool:
        if self.is_active and self.role == Role.ADMIN:
            return True
        return super().has_module_perms(app_label)

    def get_full_name(self) -> str:
        return self.full_name or super().get_full_name() or self.username

    def get_short_name(self) -> str:
        return self.full_name.split()[-1] if self.full_name else self.username

    @property
    def initials(self) -> str:
        parts = (self.full_name or self.username).split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return (parts[0][:2] if parts else "?").upper()

    # --- Permission checks ------------------------------------------------
    # Used both in views (real enforcement) and templates (hiding controls).

    @property
    def is_admin(self) -> bool:
        return self.is_superuser or self.role == Role.ADMIN

    @property
    def can_manage(self) -> bool:
        """Create equipment, plan maintenance and calibration, edit catalogs."""
        return self.is_admin or self.role == Role.MANAGER

    @property
    def can_record(self) -> bool:
        """Log maintenance, repairs, calibration, stock moves, and incidents."""
        return self.can_manage or self.role == Role.TECHNICIAN

    @property
    def role_badge_class(self) -> str:
        return {
            Role.ADMIN: "badge-danger",
            Role.MANAGER: "badge-primary",
            Role.TECHNICIAN: "badge-success",
            Role.VIEWER: "badge-neutral",
        }.get(self.role, "badge-neutral")


class Plant(models.TextChoices):
    """The company's three factories. Everything sits in one of them."""

    CTV1 = "CTV1", "CTV1"
    CTV2 = "CTV2", "CTV2"
    CTVN = "CTVN", "CTVN"


class TimeStampedModel(models.Model):
    """Base class that records when a row was created and last changed."""

    created_at = models.DateTimeField("Created at", auto_now_add=True)
    updated_at = models.DateTimeField("Updated at", auto_now=True)

    class Meta:
        abstract = True


class ActiveQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class NamedCatalog(TimeStampedModel):
    """Shared shape for simple catalogs: code, name, description, on/off."""

    code = models.CharField("Code", max_length=30, unique=True)
    name = models.CharField("Name", max_length=150)
    description = models.TextField("Description", blank=True)
    is_active = models.BooleanField("Active", default=True)

    objects = ActiveQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Location(NamedCatalog):
    """Where equipment lives: line, area, room, or storage — inside one plant."""

    plant = models.CharField(
        "Plant", max_length=10, choices=Plant.choices, blank=True,
        help_text="Everything at this location belongs to this plant.",
    )

    parent = models.ForeignKey(
        "self",
        verbose_name="Parent location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )

    class Meta:
        verbose_name = "Location"
        verbose_name_plural = "Locations"
        ordering = ["code"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Assets keep their own plant (so it survives an empty location), but
        # everything standing here belongs to this location's plant.
        if self.plant:
            self.equipments.exclude(plant=self.plant).update(plant=self.plant)

    @property
    def full_path(self) -> str:
        """For example 'Test Area / FCT Room'. Depth-capped to avoid loops."""
        parts, node, depth = [], self, 0
        while node is not None and depth < 10:
            parts.append(node.name)
            node = node.parent
            depth += 1
        return " / ".join(reversed(parts))


class Category(NamedCatalog):
    """Equipment family: ICT fixture, power supply, DMM, test station, ..."""

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["code"]


class Customer(NamedCatalog):
    """Who a product is built for — Rheem, BAF, BRNA, K-Rain. Products group under it."""

    class Meta:
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Product(NamedCatalog):
    """
    A product code the line builds and tests — the factory's model code.

    It runs through an ordered list of processes (ICT, FCT, ...), each with its
    own equipment sets; see ``systems.ProductProcess``.
    """

    # Products go by their model code (RMMTT01, BAF1950); a name is optional.
    name = models.CharField("Name", max_length=150, blank=True)
    plant = models.CharField(
        "Plant", max_length=10, choices=Plant.choices, default=Plant.CTV2, blank=True, db_index=True,
        help_text="The factory that builds it.",
    )
    revision = models.CharField(
        "Revision",
        max_length=30,
        blank=True,
        help_text="Kept separate from the code so revisions of one board group together.",
    )
    customer = models.ForeignKey(
        Customer,
        verbose_name="Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    in_production = models.BooleanField(
        "In production",
        default=False,
        help_text="Switched by hand. The products page shows these first.",
    )

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.revision}".strip() if self.revision else self.code

    @property
    def display_name(self) -> str:
        """Code plus revision, with the description trailing. For headings."""
        head = str(self)
        return f"{head} — {self.name}" if self.name else head

    def save(self, *args, user=None, **kwargs):
        # ``user`` is who flipped "In production", for the assets' status history.
        was_running = None
        if self.pk:
            was_running = type(self).objects.filter(pk=self.pk).values_list("in_production", flat=True).first()
        super().save(*args, **kwargs)
        if was_running is not None and was_running != self.in_production:
            self.refresh_equipment_status(user)

    def refresh_equipment_status(self, user=None):
        """Starting or stopping production moves every asset fitted to this product."""
        from equipment.models import Equipment

        fitted = Equipment.objects.filter(
            installations__removed_at__isnull=True,
            installations__test_set__product_process__product=self,
        ).distinct()
        for asset in fitted:
            asset.refresh_production_status(user)


class Supplier(NamedCatalog):
    """A vendor for equipment or parts, or an external calibration provider."""

    contact_person = models.CharField("Contact person", max_length=120, blank=True)
    phone = models.CharField("Phone", max_length=50, blank=True)
    email = models.EmailField("Email", blank=True)
    address = models.CharField("Address", max_length=255, blank=True)
    is_calibration_provider = models.BooleanField(
        "Calibration provider",
        default=False,
        help_text="Tick if this vendor performs calibration services.",
    )

    class Meta:
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"
        ordering = ["code"]


def attachment_upload_path(instance: "Attachment", filename: str) -> str:
    """
    Store uploads under year/month with a random filename.

    Renaming avoids two problems at once: name collisions, and non-ASCII
    filenames that break on some systems. The original name is kept in
    ``original_name`` so people still see what they uploaded.
    """
    today = timezone.now()
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"{today:%Y/%m}/{uuid.uuid4().hex}{ext}"


class AttachmentKind(models.TextChoices):
    PHOTO = "PHOTO", "Photo"
    MANUAL = "MANUAL", "Manual / datasheet"
    CERTIFICATE = "CERTIFICATE", "Calibration certificate"
    DRAWING = "DRAWING", "Drawing / wiring diagram"
    INVOICE = "INVOICE", "Invoice / document"
    OTHER = "OTHER", "Other"


class Attachment(TimeStampedModel):
    """
    A file attached to any record — equipment, incident, calibration entry —
    through Django's generic foreign key.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    file = models.FileField("File", upload_to=attachment_upload_path, max_length=255)
    original_name = models.CharField("Original filename", max_length=255)
    kind = models.CharField(
        "File type",
        max_length=20,
        choices=AttachmentKind.choices,
        default=AttachmentKind.OTHER,
    )
    description = models.CharField("Description", max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField("Size (bytes)", default=0)
    # Photos only: the one shown first, and a small copy for quick display.
    is_primary = models.BooleanField("Main photo", default=False)
    thumbnail = models.FileField("Thumbnail", upload_to=attachment_upload_path, max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Uploaded by",
        on_delete=models.SET_NULL,
        null=True,
        related_name="attachments",
    )

    class Meta:
        verbose_name = "Attachment"
        verbose_name_plural = "Attachments"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return self.original_name

    @property
    def size_display(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    @property
    def is_image(self) -> bool:
        return os.path.splitext(self.file.name)[1].lower() in {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".bmp",
        }


class AttachmentMixin(models.Model):
    """Adds the attachment relation, and photo helpers, to any model."""

    attachments = GenericRelation(Attachment)

    class Meta:
        abstract = True

    @property
    def photos(self) -> list:
        """Photos, main one first. Uses prefetched attachments when present."""
        photos = [a for a in self.attachments.all() if a.kind == AttachmentKind.PHOTO]
        return sorted(photos, key=lambda a: (not a.is_primary, a.created_at))

    @property
    def main_photo(self):
        photos = self.photos
        return photos[0] if photos else None


class DueScheduleMixin(models.Model):
    """
    Shared behaviour for anything with a due date: maintenance plans and
    calibration plans.

    Kept in one place so "due soon" and "overdue" mean the same thing
    everywhere, instead of each screen deciding for itself.
    """

    # Days before the due date when the warning colour kicks in.
    WARNING_DAYS = 7

    next_due_at = models.DateField("Next due", null=True, blank=True, db_index=True)
    is_active = models.BooleanField(
        "Active",
        default=True,
        help_text="Turn off to pause this schedule without deleting it.",
    )

    class Meta:
        abstract = True

    @property
    def days_until_due(self) -> int | None:
        """Days left until due. Negative means overdue."""
        if not self.next_due_at:
            return None
        return (self.next_due_at - timezone.localdate()).days

    @property
    def is_overdue(self) -> bool:
        days = self.days_until_due
        return days is not None and days < 0

    @property
    def is_due_soon(self) -> bool:
        days = self.days_until_due
        return days is not None and 0 <= days <= self.WARNING_DAYS

    @property
    def due_badge_class(self) -> str:
        if self.is_overdue:
            return "badge-danger"
        if self.is_due_soon:
            return "badge-warning"
        return "badge-success" if self.next_due_at else "badge-neutral"

    @property
    def due_display(self) -> str:
        days = self.days_until_due
        if days is None:
            return "No due date"
        if days < 0:
            return "1 day overdue" if days == -1 else f"{abs(days)} days overdue"
        if days == 0:
            return "Due today"
        if days == 1:
            return "Due tomorrow"
        return f"In {days} days"
