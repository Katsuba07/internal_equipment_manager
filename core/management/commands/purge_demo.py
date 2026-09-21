"""
Remove the demo data, keeping the real register.

What goes: every asset that did not come from Computime (their codes all start
with ``70-``), every stocked spare part, and everything hanging off them —
parts lists, stock movements, maintenance and calibration plans and records,
status history, fittings. Catalog entries (category, location, supplier) go too
once nothing uses them any more.

What stays: the Computime assets and their photos, the customers, product codes,
processes and equipment sets (the sets simply end up empty), and every user.

Dry run unless ``--commit``:

    manage.py purge_demo
    manage.py purge_demo --commit
"""

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Attachment, Category, Location, Supplier
from equipment.models import Equipment
from inventory.models import InventoryItem

# Assets imported from Computime carry this prefix; everything else is demo.
KEEP_PREFIX = "70-"

# Records that point at an asset with PROTECT, so they have to go first.
PROTECTED_BY_ASSET = [
    "repairs.RepairRecord",
    "incidents.IncidentReport",
    "maintenance.MaintenanceRecord",
    "calibration.CalibrationRecord",
]


class Command(BaseCommand):
    help = "Delete the demo assets and spare parts (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Actually delete. Without it, nothing changes.")
        parser.add_argument("--prefix", default=KEEP_PREFIX,
                            help=f"Asset codes to keep (default {KEEP_PREFIX}).")

    def handle(self, *args, **options):
        prefix = options["prefix"]
        demo_assets = Equipment.objects.exclude(code__startswith=prefix)
        parts = InventoryItem.objects.all()

        self.stdout.write(f"Assets to delete: {demo_assets.count()} "
                          f"(keeping {Equipment.objects.filter(code__startswith=prefix).count()} "
                          f"with code {prefix}…)")
        self.stdout.write(f"Spare parts to delete: {parts.count()}")

        with transaction.atomic():
            # Attachments use a generic relation, so they are not cascaded.
            asset_type = ContentType.objects.get_for_model(Equipment)
            part_type = ContentType.objects.get_for_model(InventoryItem)
            files = Attachment.objects.filter(
                content_type=asset_type, object_id__in=list(demo_assets.values_list("pk", flat=True))
            ) | Attachment.objects.filter(
                content_type=part_type, object_id__in=list(parts.values_list("pk", flat=True))
            )
            self.stdout.write(f"Attachments to delete: {files.count()}")
            for attachment in files:
                attachment.delete()      # its post_delete signal removes the file

            # Logs that protect the asset row have to be removed first.
            asset_ids = list(demo_assets.values_list("pk", flat=True))
            for label in PROTECTED_BY_ASSET:
                model = apps.get_model(label)
                rows = model.objects.filter(equipment_id__in=asset_ids)
                count = rows.count()
                if count:
                    self.stdout.write(f"{label}: {count}")
                    rows.delete()

            removed_assets = demo_assets.delete()
            removed_parts = parts.delete()

            # Catalog rows nothing points at any more.
            # A category may still name a role in a product's process, which we
            # are keeping — those must stay.
            empty_categories = Category.objects.filter(
                equipments__isnull=True, process_roles__isnull=True, system_roles__isnull=True
            )
            empty_locations = Location.objects.filter(
                equipments__isnull=True, children__isnull=True
            )
            empty_suppliers = Supplier.objects.filter(
                equipments__isnull=True, inventory_items__isnull=True
            )
            counts = (empty_categories.count(), empty_locations.count(), empty_suppliers.count())
            self.stdout.write(
                f"Unused catalog rows: {counts[0]} categories, {counts[1]} locations, "
                f"{counts[2]} suppliers"
            )
            empty_categories.delete()
            empty_locations.delete()
            empty_suppliers.delete()

            self.stdout.write(f"Rows removed with the assets: {dict(removed_assets[1])}")
            self.stdout.write(f"Rows removed with the parts: {dict(removed_parts[1])}")

            if not options["commit"]:
                transaction.set_rollback(True)

        left = Equipment.objects.count()
        mode = "DELETED" if options["commit"] else "DRY RUN — nothing was deleted"
        self.stdout.write(self.style.SUCCESS(f"{mode}. Assets now: {left}"))
