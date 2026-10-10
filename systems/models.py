"""
Test systems: which processes a product runs through, and what equipment is
fitted at each one right now.

    Product ── ProductProcess (ICT, FCT, ... in order)
                 ├─ ProcessRole     what a set at this process is made of
                 └─ TestSet #1, #2  the physical sets, each on a line
                      └─ Installation  asset fitted to one role of one set

``SystemType`` is the catalog of processes; its roles are only a starting
template copied into a product's process, which is then edited freely (one
product's FCT needs ten sub-equipments, another's four).

Only one open installation may exist per asset — the database enforces it — so
the same instrument can never be claimed by two sets at once. Closed
installations are kept as the asset's fitting history.
"""

from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from core.models import AttachmentMixin, NamedCatalog, TimeStampedModel


class SystemType(NamedCatalog):
    """A process that needs equipment — Programming, ICT, FCT, Burn-in, Hipot."""

    position = models.PositiveIntegerField(
        "Order", default=0, help_text="Where it usually sits in a product's route."
    )

    class Meta:
        verbose_name = "Process"
        verbose_name_plural = "Processes"
        ordering = ["position", "code"]


class SystemTypeRole(TimeStampedModel):
    """
    One role of a process's starting template (Test Cart, Fixture, DMM ...).

    Copied into a product's process when the process is added; editing the
    template later does not change products already set up.
    """

    system_type = models.ForeignKey(
        SystemType, verbose_name="Process", on_delete=models.CASCADE, related_name="roles"
    )
    name = models.CharField(
        "Role", max_length=100, help_text="For example: Test Cart, Control box, Fixture, PSU."
    )
    position = models.PositiveIntegerField("Order", default=0)
    is_required = models.BooleanField("Required", default=True)
    allowed_categories = models.ManyToManyField(
        "core.Category",
        verbose_name="Equipment category",
        blank=True,
        related_name="system_roles",
        help_text="The first one is copied to products. Leave empty for any.",
    )
    notes = models.CharField("Notes", max_length=255, blank=True)

    class Meta:
        verbose_name = "Template role"
        verbose_name_plural = "Template roles"
        ordering = ["system_type__code", "position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["system_type", "name"], name="unique_role_name_per_system_type"
            )
        ]

    def __str__(self) -> str:
        return f"{self.system_type.code} · {self.name}"


class SlotState(models.TextChoices):
    """Outcome of checking one role of one set."""

    READY = "READY", "Ready"
    EMPTY = "EMPTY", "Nothing fitted"
    WRONG_CATEGORY = "WRONG_CATEGORY", "Wrong kind of asset"
    UNUSABLE = "UNUSABLE", "Asset not usable"
    OPTIONAL_EMPTY = "OPTIONAL_EMPTY", "Optional, nothing fitted"


SLOT_STATE_BADGE = {
    SlotState.READY: "badge-success",
    SlotState.EMPTY: "badge-danger",
    SlotState.WRONG_CATEGORY: "badge-danger",
    SlotState.UNUSABLE: "badge-danger",
    SlotState.OPTIONAL_EMPTY: "badge-neutral",
}


class ProductProcess(TimeStampedModel):
    """One step of a product's route that needs equipment, e.g. BAF1950 · FCT."""

    product = models.ForeignKey(
        "core.Product", verbose_name="Product", on_delete=models.CASCADE,
        related_name="processes",
    )
    process = models.ForeignKey(
        SystemType, verbose_name="Process", on_delete=models.CASCADE,
        related_name="product_processes",
    )
    position = models.PositiveIntegerField("Order", default=0)
    notes = models.CharField("Notes", max_length=255, blank=True)
    # How many usable golden samples this process should hold. Zero means the
    # process declares nothing, so it never warns.
    golden_ok_required = models.PositiveSmallIntegerField("OK samples required", default=0)
    golden_ng_required = models.PositiveSmallIntegerField("NG samples required", default=0)

    class Meta:
        verbose_name = "Product process"
        verbose_name_plural = "Product processes"
        ordering = ["product__code", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "process"], name="one_process_step_per_product"
            )
        ]

    def __str__(self) -> str:
        return f"{self.product.code} · {self.process.code}"

    def copy_template(self):
        """Start the role list from the process's template (only when empty)."""
        if self.roles.exists():
            return
        for template in self.process.roles.prefetch_related("allowed_categories"):
            category = template.allowed_categories.first()
            ProcessRole.objects.create(
                product_process=self,
                # Temporary, unique; name_roles() gives the real name below.
                name=f"~t{template.pk}" if category else template.name,
                category=category,
                position=template.position,
                is_required=template.is_required,
            )
        self.name_roles()

    @transaction.atomic
    def name_roles(self):
        """
        A role is named after its equipment type; two of the same type are
        numbered (Power supply 1, Power supply 2) in the order shown.
        """
        roles = list(self.roles.select_related("category").order_by("position", "id"))
        totals, seen, names = {}, {}, {}
        for role in roles:
            if role.category_id:
                totals[role.category_id] = totals.get(role.category_id, 0) + 1
        for role in roles:
            if not role.category_id:
                names[role.pk] = role.name
                continue
            seen[role.category_id] = seen.get(role.category_id, 0) + 1
            base = role.category.name
            names[role.pk] = f"{base} {seen[role.category_id]}" if totals[role.category_id] > 1 else base
        changed = [role for role in roles if role.name != names[role.pk]]
        # Two passes so a swap of names never trips the unique constraint.
        for role in changed:
            ProcessRole.objects.filter(pk=role.pk).update(name=f"~{role.pk}")
        for role in changed:
            ProcessRole.objects.filter(pk=role.pk).update(name=names[role.pk])

    def next_set_number(self) -> int:
        last = self.sets.order_by("-number").values_list("number", flat=True).first()
        return (last or 0) + 1

    def golden_status(self) -> "GoldenSummary":
        """
        Usable golden samples against what the process requires, and what to
        chase. A warning only: it never changes whether a set is ready.
        """
        samples = list(self.golden_samples.all())      # honours a prefetch
        usable = [s for s in samples if s.is_usable]
        summary = GoldenSummary(
            samples=samples,
            ok_usable=sum(s.kind == GoldenKind.OK for s in usable),
            ng_usable=sum(s.kind == GoldenKind.NG for s in usable),
            ok_required=self.golden_ok_required,
            ng_required=self.golden_ng_required,
        )
        for label, have, need in (
            ("OK", summary.ok_usable, summary.ok_required),
            ("NG", summary.ng_usable, summary.ng_required),
        ):
            if have < need:
                missing = need - have
                summary.warnings.append(f"{missing} {label} sample{'s' if missing != 1 else ''} missing")
        for sample in samples:
            if sample.status != GoldenStatus.ACTIVE:
                continue
            if sample.is_expired or sample.expires_soon:
                summary.warnings.append(f"{sample.code} {sample.validity_display.lower()}")
        return summary


@dataclass
class GoldenSummary:
    """Golden samples of one product process, counted against its requirement."""

    samples: list
    ok_usable: int = 0
    ng_usable: int = 0
    ok_required: int = 0
    ng_required: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def has_warning(self) -> bool:
        return bool(self.warnings)

    @property
    def first_warning(self) -> str:
        return self.warnings[0] if self.warnings else ""


class ProcessRole(TimeStampedModel):
    """
    One sub-equipment a set at this process needs, given by its equipment type
    (ICT fixture, DMM, Power supply 2 ...). The name follows the type; see
    ``ProductProcess.name_roles``.
    """

    product_process = models.ForeignKey(
        ProductProcess, verbose_name="Process", on_delete=models.CASCADE, related_name="roles"
    )
    name = models.CharField("Role", max_length=100)
    category = models.ForeignKey(
        "core.Category", verbose_name="Equipment type", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="process_roles",
        help_text="Only this kind of asset is offered.",
    )
    position = models.PositiveIntegerField("Order", default=0)
    is_required = models.BooleanField("Required", default=True)

    class Meta:
        verbose_name = "Process role"
        verbose_name_plural = "Process roles"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product_process", "name"], name="unique_role_name_per_product_process"
            )
        ]

    def __str__(self) -> str:
        return self.name

    def accepts(self, equipment) -> bool:
        return self.category_id is None or equipment.category_id == self.category_id


class TestSet(TimeStampedModel):
    """A physical set at one process of one product: BAF1950 · FCT #2, on a line."""

    product_process = models.ForeignKey(
        ProductProcess, verbose_name="Process", on_delete=models.CASCADE, related_name="sets"
    )
    number = models.PositiveSmallIntegerField("Set number", default=1)
    line = models.ForeignKey(
        "core.Location", verbose_name="Line / location", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="test_sets",
    )
    notes = models.CharField("Notes", max_length=255, blank=True)

    class Meta:
        verbose_name = "Equipment set"
        verbose_name_plural = "Equipment sets"
        ordering = ["product_process__product__code", "product_process__position", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["product_process", "number"], name="unique_set_number_per_process"
            )
        ]

    def __str__(self) -> str:
        return f"{self.product_process} #{self.number}"

    @property
    def product(self):
        return self.product_process.product

    def open_installations(self):
        return self.installations.filter(removed_at__isnull=True)

    @transaction.atomic
    def release_all(self, user, reason: str = ""):
        for installation in self.open_installations():
            installation.release(user, reason)

    @transaction.atomic
    def delete(self, *args, user=None, **kwargs):
        """Free the equipment first; the assets keep their fitting history."""
        self.release_all(user, reason=f"{self} removed")
        self.installations.update(set_label=str(self))
        return super().delete(*args, **kwargs)


class Installation(TimeStampedModel):
    """
    An asset fitted to one role of one set; closed rows are its history.

    ``set_label`` keeps a readable snapshot so the history still reads well
    after the set, its process or its product has been deleted.
    """

    component = models.ForeignKey(
        "equipment.Equipment", verbose_name="Asset", on_delete=models.CASCADE,
        related_name="installations",
    )
    test_set = models.ForeignKey(
        TestSet, verbose_name="Set", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="installations",
    )
    role = models.ForeignKey(
        ProcessRole, verbose_name="Role", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="installations",
    )
    set_label = models.CharField("Set (snapshot)", max_length=200, blank=True)

    installed_at = models.DateTimeField("Fitted at", default=timezone.now)
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Fitted by", on_delete=models.SET_NULL,
        null=True, related_name="installations_made",
    )
    removed_at = models.DateTimeField("Removed at", null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Removed by", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="installations_removed",
    )
    reason = models.CharField("Reason", max_length=255, blank=True)
    notes = models.TextField("Notes", blank=True)

    class Meta:
        verbose_name = "Installation"
        verbose_name_plural = "Installations"
        ordering = ["-installed_at"]
        indexes = [
            models.Index(fields=["component", "-installed_at"]),
            models.Index(fields=["test_set", "-installed_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["component"],
                condition=Q(removed_at__isnull=True),
                name="one_open_installation_per_component",
            ),
            models.UniqueConstraint(
                fields=["test_set", "role"],
                condition=Q(removed_at__isnull=True),
                name="one_open_installation_per_role",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.component.code} in {self.where}"

    @property
    def where(self) -> str:
        return str(self.test_set) if self.test_set_id else (self.set_label or "removed set")

    @property
    def is_open(self) -> bool:
        return self.removed_at is None

    @classmethod
    @transaction.atomic
    def fit(cls, component, test_set, role, user, reason: str = ""):
        """
        Fit an asset to one role of a set.

        Refuses with a readable reason when the role belongs to another process,
        the asset is the wrong kind, the role already holds another asset, or
        the asset is fitted in another set.
        """
        if role.product_process_id != test_set.product_process_id:
            raise ValidationError(f"{role.name} is not a role of {test_set}.")
        if not role.accepts(component):
            raise ValidationError(
                f"{component.code} is a {component.category.name}; "
                f"{role.name} needs a {role.category.name}."
            )
        occupied = cls.objects.filter(
            test_set=test_set, role=role, removed_at__isnull=True
        ).exclude(component=component).select_related("component").first()
        if occupied:
            raise ValidationError(
                f"{role.name} of {test_set} already holds {occupied.component.code}; remove it first."
            )
        open_now = cls.objects.filter(component=component, removed_at__isnull=True).first()
        if open_now:
            if open_now.test_set_id == test_set.id and open_now.role_id == role.id:
                return open_now
            raise ValidationError(
                f"{component.code} is currently fitted in {open_now.where}. Remove it there first."
            )
        installation = cls.objects.create(
            component=component,
            test_set=test_set,
            role=role,
            set_label=str(test_set),
            installed_by=user if getattr(user, "is_authenticated", False) else None,
            reason=reason,
        )
        component.refresh_production_status(user)
        return installation

    @transaction.atomic
    def release(self, user, reason: str = ""):
        """Close this installation so the asset is free to be fitted again."""
        if not self.is_open:
            return self
        self.removed_at = timezone.now()
        self.removed_by = user if getattr(user, "is_authenticated", False) else None
        if reason:
            self.reason = reason
        self.save(update_fields=["removed_at", "removed_by", "reason", "updated_at"])
        self.component.refresh_production_status(user)
        return self


# ------------------------------------------------------------------ golden samples


class GoldenKind(models.TextChoices):
    OK = "OK", "OK (pass)"
    NG = "NG", "NG (fail)"


class GoldenStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "In use"
    DAMAGED = "DAMAGED", "Damaged"
    LOST = "LOST", "Lost"
    REPLACED = "REPLACED", "Replaced"


class GoldenSample(AttachmentMixin, TimeStampedModel):
    """
    A reference board kept for one process of one product: a known-good one
    the station must pass, or a known-bad one it must fail.
    """

    # Days before ``valid_until`` when the warning starts.
    WARNING_DAYS = 30

    product_process = models.ForeignKey(
        ProductProcess, verbose_name="Process", on_delete=models.CASCADE,
        related_name="golden_samples",
    )
    code = models.CharField("Sample ID / serial", max_length=80)
    kind = models.CharField("Type", max_length=2, choices=GoldenKind.choices, default=GoldenKind.OK)
    expected_defect = models.CharField(
        "Expected defect", max_length=200, blank=True,
        help_text="For an NG sample: what the station must fail it on.",
    )
    storage_location = models.CharField("Kept at", max_length=120, blank=True)
    valid_until = models.DateField(
        "Valid until", null=True, blank=True, help_text="Leave empty if it does not expire.",
    )
    status = models.CharField(
        "Status", max_length=10, choices=GoldenStatus.choices, default=GoldenStatus.ACTIVE,
    )
    notes = models.TextField("Notes", blank=True)

    class Meta:
        verbose_name = "Golden sample"
        verbose_name_plural = "Golden samples"
        ordering = ["-kind", "code"]     # OK first, then NG
        constraints = [
            models.UniqueConstraint(
                fields=["product_process", "code"], name="unique_golden_code_per_process"
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.get_kind_display()})"

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return f"{reverse('systems:products')}?process={self.product_process_id}"

    @property
    def days_left(self) -> int | None:
        if not self.valid_until:
            return None
        return (self.valid_until - timezone.localdate()).days

    @property
    def is_expired(self) -> bool:
        days = self.days_left
        return days is not None and days < 0

    @property
    def expires_soon(self) -> bool:
        days = self.days_left
        return days is not None and 0 <= days <= self.WARNING_DAYS

    @property
    def is_usable(self) -> bool:
        return self.status == GoldenStatus.ACTIVE and not self.is_expired

    @property
    def validity_display(self) -> str:
        days = self.days_left
        if days is None:
            return "No expiry"
        if days < 0:
            return f"Expired {-days} day{'s' if days != -1 else ''} ago"
        if days == 0:
            return "Expires today"
        if days <= self.WARNING_DAYS:
            return f"Expires in {days} day{'s' if days != 1 else ''}"
        return f"Valid until {self.valid_until:%d %b %Y}"

    @property
    def validity_badge_class(self) -> str:
        if self.is_expired:
            return "badge-danger"
        if self.expires_soon:
            return "badge-warning"
        return "badge-neutral" if self.valid_until is None else "badge-success"

    @property
    def status_badge_class(self) -> str:
        return "badge-success" if self.status == GoldenStatus.ACTIVE else "badge-muted"


# ------------------------------------------------------------------ documents


class DocumentSection(models.TextChoices):
    """The kinds of document kept per product, as the TE share files them."""

    TI = "TI", "Test instruction (TI)"
    TEST_SPEC = "TEST_SPEC", "Test specification"
    SCHEMATIC = "SCHEMATIC", "Schematic"
    BOM = "BOM", "BOM"
    FIRMWARE = "FIRMWARE", "Firmware"
    PCBA_DRAWING = "PCBA_DRAWING", "PCBA drawing"
    OTHER = "OTHER", "Other"


def document_upload_path(instance: "ProductDocument", filename: str) -> str:
    """documents/<random><ext>: the real name stays in ``file_name``."""
    import os
    import uuid

    return f"documents/{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()[:10]}"


class ProductDocument(TimeStampedModel):
    """
    A file that belongs to one or more products: test instruction, test spec,
    schematic, BOM, firmware, drawing. Several products can share one file —
    the TE share keeps KMCB111, KMCB121 and KMCB141 in one folder — and a file
    with no product (a packing list for the whole line) is kept as general.
    """

    products = models.ManyToManyField(
        "core.Product", verbose_name="Products", related_name="documents", blank=True,
    )
    section = models.CharField(
        "Type", max_length=20, choices=DocumentSection.choices, default=DocumentSection.OTHER, db_index=True,
    )
    file_name = models.CharField("File name", max_length=255)
    # Left empty now: the file lives on SharePoint (see doc_sync). Only kept for
    # records made before the app used the synced folder.
    file = models.FileField("File", upload_to=document_upload_path, max_length=500, blank=True)
    size_bytes = models.PositiveBigIntegerField("Size (bytes)", default=0)
    folder = models.CharField("Folder", max_length=300, blank=True, help_text="Where it sat on the share.")
    source = models.CharField(
        "Source", max_length=600, blank=True,
        help_text="Its path on SharePoint; a later import updates the same record.",
    )
    source_modified = models.DateTimeField("Last changed at the source", null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Added by", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="product_documents",
    )

    class Meta:
        verbose_name = "Product document"
        verbose_name_plural = "Product documents"
        ordering = ["section", "file_name"]
        constraints = [
            models.UniqueConstraint(fields=["source"], condition=~Q(source=""), name="document_source_unique"),
        ]

    def __str__(self) -> str:
        return self.file_name

    @property
    def extension(self) -> str:
        return self.file_name.rsplit(".", 1)[-1].lower() if "." in self.file_name else ""

    @property
    def open_url(self) -> str:
        """Open it on SharePoint (in the browser for PDF and Office files)."""
        from .doc_sync import open_url

        return open_url(self)

    @property
    def download_url(self) -> str:
        from .doc_sync import download_url

        return download_url(self)

    @property
    def viewable(self) -> bool:
        """Opens in the browser rather than downloading."""
        return self.extension in {"pdf", "png", "jpg", "jpeg", "txt"}

    @property
    def size_display(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    @property
    def icon(self) -> str:
        return {
            "pdf": "bi-file-earmark-pdf", "doc": "bi-file-earmark-word", "docx": "bi-file-earmark-word",
            "odt": "bi-file-earmark-word", "xls": "bi-file-earmark-excel", "xlsx": "bi-file-earmark-excel",
            "xlsm": "bi-file-earmark-excel", "zip": "bi-file-earmark-zip", "txt": "bi-file-earmark-text",
        }.get(self.extension, "bi-file-earmark-binary")


@receiver(post_delete, sender=ProductDocument)
def remove_document_file(sender, instance, **kwargs):
    """A deleted document takes its file with it."""
    if instance.file and instance.file.name:
        instance.file.storage.delete(instance.file.name)
