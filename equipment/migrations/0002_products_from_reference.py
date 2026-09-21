"""
Turn the free-text product reference into real Product records.

Runs before the field is dropped in the next migration, so nothing that was
typed into it is lost. Values are taken as written and de-duplicated
case-insensitively; anything else about the product is filled in afterwards by
hand, which is unavoidable since free text carries no revision or customer.
"""

from django.db import migrations


def create_products_from_references(apps, schema_editor):
    Equipment = apps.get_model("equipment", "Equipment")
    Product = apps.get_model("core", "Product")

    seen = {product.code.upper() for product in Product.objects.all()}
    references = (
        Equipment.objects.exclude(product_reference="")
        .values_list("product_reference", flat=True)
        .distinct()
    )

    for reference in references:
        code = (reference or "").strip()
        if not code or code.upper() in seen:
            continue
        seen.add(code.upper())
        Product.objects.create(
            code=code[:30],
            name=code[:150],
            description=(
                "Imported from the old free-text product reference. "
                "Check the code, revision and customer."
            ),
            is_active=True,
        )


def remove_imported_products(apps, schema_editor):
    """Reverse step: drop only the rows this migration could have created."""
    Product = apps.get_model("core", "Product")
    Product.objects.filter(
        description__startswith="Imported from the old free-text product reference."
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("equipment", "0001_initial"),
        ("core", "0002_product"),
    ]

    operations = [
        migrations.RunPython(create_products_from_references, remove_imported_products),
    ]
