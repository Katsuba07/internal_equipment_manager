"""Assets saved before Equipment.save kept identifying text in capitals get the same treatment."""

from django.db import migrations

FIELDS = ("equipment_no", "code", "asset_no", "name", "manufacturer", "model_number", "serial_number")


def to_capitals(apps, schema_editor):
    Equipment = apps.get_model("equipment", "Equipment")
    for asset in Equipment.objects.all().only("pk", *FIELDS):
        changed = {}
        for field in FIELDS:
            value = getattr(asset, field) or ""
            tidy = " ".join(value.split()).upper()
            if tidy != value:
                changed[field] = tidy
        if changed:
            Equipment.objects.filter(pk=asset.pk).update(**changed)


class Migration(migrations.Migration):

    dependencies = [
        ("equipment", "0013_equipment_labelled"),
    ]

    operations = [
        migrations.RunPython(to_capitals, migrations.RunPython.noop),
    ]
