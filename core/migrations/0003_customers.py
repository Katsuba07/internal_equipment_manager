"""
Customers become a catalog; products point to one and get an "In production" switch.

The old free-text customer is kept: each distinct value becomes a Customer.
"""

import re

import django.db.models.deletion
from django.db import migrations, models


def text_to_customers(apps, schema_editor):
    Customer = apps.get_model("core", "Customer")
    Product = apps.get_model("core", "Product")
    by_name = {}
    for product in Product.objects.exclude(customer_name=""):
        name = product.customer_name.strip()
        if name not in by_name:
            code = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:30] or "CUST"
            base, n = code, 2
            while Customer.objects.filter(code=code).exists():
                code = f"{base[:27]}-{n}"
                n += 1
            by_name[name] = Customer.objects.create(code=code, name=name)
        product.customer = by_name[name]
        product.save(update_fields=["customer"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_product"),
    ]

    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated at")),
                ("code", models.CharField(max_length=30, unique=True, verbose_name="Code")),
                ("name", models.CharField(max_length=150, verbose_name="Name")),
                ("description", models.TextField(blank=True, verbose_name="Description")),
                ("is_active", models.BooleanField(default=True, verbose_name="Active")),
            ],
            options={
                "verbose_name": "Customer",
                "verbose_name_plural": "Customers",
                "ordering": ["name"],
            },
        ),
        migrations.RenameField("product", "customer", "customer_name"),
        migrations.AddField(
            model_name="product",
            name="customer",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="products", to="core.customer", verbose_name="Customer",
            ),
        ),
        migrations.RunPython(text_to_customers, migrations.RunPython.noop),
        migrations.RemoveField("product", "customer_name"),
        migrations.AddField(
            model_name="product",
            name="in_production",
            field=models.BooleanField(
                default=False,
                help_text="Switched by hand. The products page shows these first.",
                verbose_name="In production",
            ),
        ),
    ]
