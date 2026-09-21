"""
Convert v0.3 test systems into BOMs and production runs.

A v0.3 TestSystem was both the specification and the physical rig. It splits:

* every TestSystem becomes a ProductBOM, and every slot a BOMLine; a slot that
  named an asset keeps it as the line's only compatible asset;
* every TestSystem that had equipment fitted becomes one running
  ProductionRun, and its open and closed installations move onto that run.

Nothing is deleted here — the old tables are dropped in the next migration.
"""

from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    TestSystem = apps.get_model("systems", "TestSystem")
    ProductBOM = apps.get_model("systems", "ProductBOM")
    BOMLine = apps.get_model("systems", "BOMLine")
    ProductionRun = apps.get_model("systems", "ProductionRun")
    Installation = apps.get_model("systems", "Installation")

    year = timezone.localdate().year
    run_seq = 0

    for system in TestSystem.objects.select_related("product", "system_type"):
        bom = ProductBOM.objects.create(
            product_id=system.product_id,
            system_type_id=system.system_type_id,
            name=system.name,
            is_active=system.is_active,
            notes=system.notes,
        )

        line_for_slot = {}
        for slot in system.slots.select_related("role"):
            line = BOMLine.objects.create(
                bom=bom,
                role_id=slot.role_id,
                position=slot.position,
                is_required=slot.role.is_required,
                notes=slot.notes,
            )
            if slot.equipment_id:
                line.allowed_equipment.add(slot.equipment_id)
            line_for_slot[slot.id] = line

        installations = Installation.objects.filter(test_system=system)
        if not installations.exists():
            continue

        run_seq += 1
        first = installations.order_by("installed_at").first()
        label = f"{system.product.code} · {system.system_type.code}"
        run = ProductionRun.objects.create(
            code=f"RUN-{year}-{run_seq:04d}",
            bom=bom,
            product_id=system.product_id,
            label=label,
            started_at=first.installed_at,
            started_by_id=first.installed_by_id,
            notes="Converted from a v0.3 test system.",
        )
        for installation in installations:
            installation.run = run
            installation.run_label = label
            line = line_for_slot.get(installation.slot_id)
            if line is None:
                line = next(
                    (l for l in line_for_slot.values()
                     if l.allowed_equipment.filter(id=installation.component_id).exists()),
                    None,
                )
            installation.bom_line = line
            installation.save(update_fields=["run", "run_label", "bom_line"])


class Migration(migrations.Migration):

    dependencies = [
        ("systems", "0002_bom_and_runs"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
