"""
Admin for the process catalog and each process's starting role template.

Products, their processes and equipment sets are managed on the Products page
(/products/), so they are deliberately not registered here.
"""

import uuid

from django import forms
from django.contrib import admin
from django.db import transaction

from core.models import Category

from .models import SystemType, SystemTypeRole


class TemplateRoleForm(forms.ModelForm):
    """A template role is an equipment type, like a product's roles."""

    category = forms.ModelChoiceField(
        queryset=Category.objects.none(), label="Role (equipment type)"
    )

    class Meta:
        model = SystemTypeRole
        fields = ("position", "category", "is_required")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.active()
        if self.instance.pk:
            self.fields["category"].initial = self.instance.allowed_categories.first()


class SystemTypeRoleInline(admin.TabularInline):
    """Edit a process's role template right where the process is defined."""

    model = SystemTypeRole
    form = TemplateRoleForm
    extra = 1
    verbose_name = "Template role"
    verbose_name_plural = "Template roles (copied to a product when the process is added)"
    ordering = ("position", "id")


def name_template_roles(process: SystemType):
    """Same rule as a product's roles: named after the type, numbered if repeated."""
    roles = list(process.roles.prefetch_related("allowed_categories").order_by("position", "id"))
    cats = {role.pk: role.allowed_categories.first() for role in roles}
    totals, seen, names = {}, {}, {}
    for cat in cats.values():
        if cat:
            totals[cat.pk] = totals.get(cat.pk, 0) + 1
    for role in roles:
        cat = cats[role.pk]
        if cat is None:
            names[role.pk] = role.name
            continue
        seen[cat.pk] = seen.get(cat.pk, 0) + 1
        names[role.pk] = f"{cat.name} {seen[cat.pk]}" if totals[cat.pk] > 1 else cat.name
    changed = [role for role in roles if role.name != names[role.pk]]
    for role in changed:
        SystemTypeRole.objects.filter(pk=role.pk).update(name=f"~{role.pk}")
    for role in changed:
        SystemTypeRole.objects.filter(pk=role.pk).update(name=names[role.pk])


@admin.register(SystemType)
class SystemTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "position", "role_count", "product_count", "is_active")
    list_editable = ("position",)
    fields = ("code", "name", "position", "description", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    inlines = [SystemTypeRoleInline]

    @admin.display(description="Roles")
    def role_count(self, obj):
        return obj.roles.count()

    @admin.display(description="Products")
    def product_count(self, obj):
        return obj.product_processes.count()

    @transaction.atomic
    def save_formset(self, request, form, formset, change):
        formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for role_form in formset.forms:
            if role_form in formset.deleted_forms or not role_form.has_changed():
                continue
            role = role_form.instance
            role.system_type = form.instance
            if not role.pk:
                role.name = f"~{uuid.uuid4().hex[:12]}"   # unique until named below
            role.save()
            role.allowed_categories.set([role_form.cleaned_data["category"]])
        name_template_roles(form.instance)
