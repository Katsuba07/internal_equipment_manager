"""
"+ New" next to a dropdown: a small pop-up form that creates the missing
entry and hands it back to the dropdown, without leaving the page.

GET  /quick-add/<kind>/  -> the form (HTML fragment shown in a dialog)
POST /quick-add/<kind>/  -> {"id", "label"} when saved, or the form with errors
"""

from decimal import Decimal

from django import forms
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views import View

from .mixins import CanManageMixin
from .models import Category, Customer, Location, Product, Supplier


def _upper(value: str) -> str:
    return value.strip().upper()


class CodeUpperMixin:
    def clean_code(self):
        return _upper(self.cleaned_data["code"])


class ProductQuickForm(CodeUpperMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["customer", "code", "plant", "name", "revision", "in_production"]
        widgets = {"code": forms.TextInput(attrs={"placeholder": "e.g. BAF1950"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.active()


class CustomerQuickForm(CodeUpperMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["code", "name"]
        widgets = {"code": forms.TextInput(attrs={"placeholder": "e.g. RHEEM"})}


class LocationQuickForm(CodeUpperMixin, forms.ModelForm):
    class Meta:
        model = Location
        fields = ["code", "name", "plant", "parent"]
        widgets = {"code": forms.TextInput(attrs={"placeholder": "e.g. FCT-L3"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = Location.objects.active()


class CategoryQuickForm(CodeUpperMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["code", "name"]
        widgets = {"code": forms.TextInput(attrs={"placeholder": "e.g. PSU"})}


class SupplierQuickForm(CodeUpperMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["code", "name", "contact_person", "phone", "email"]


class RolePickerWidget(forms.Textarea):
    """
    The textarea itself, plus a dropdown of equipment types above it.

    Picking one from the dropdown appends its code as a new line, so people
    choose from a list instead of having to know the exact codes by heart.
    The textarea stays live underneath — typing, reordering or deleting
    lines by hand still works exactly as before (see data-role-picker in
    app.js).
    """

    def render(self, name, value, attrs=None, renderer=None):
        attrs = dict(attrs or {})
        attrs["data-role-picker-textarea"] = ""
        textarea_html = super().render(name, value, attrs, renderer)
        options = "".join(
            f'<option value="{escape(code)}">{escape(code)} — {escape(cat_name)}</option>'
            for code, cat_name in Category.objects.active().order_by("code").values_list("code", "name")
        )
        return mark_safe(
            '<div data-role-picker>'
            '<select class="form-select mb-1" data-role-picker-select>'
            f'<option value="">+ Add an equipment type…</option>{options}'
            "</select>"
            f"{textarea_html}"
            "</div>"
        )


class SystemTypeQuickForm(CodeUpperMixin, forms.ModelForm):
    roles = forms.CharField(
        label="Roles",
        widget=RolePickerWidget(attrs={
            "rows": 7,
            "placeholder": "CART\nCTRL\nFIX-FCT\nPC\nMON\nDMM\nPSU",
        }),
        help_text=(
            "Pick from the dropdown, or type codes directly — one per line, in order "
            "(the same code twice gives two roles, e.g. PSU 1 and PSU 2). Each product "
            "can change its own list later."
        ),
    )

    class Meta:
        from systems.models import SystemType

        model = SystemType
        fields = ["code", "name"]
        widgets = {"code": forms.TextInput(attrs={"placeholder": "e.g. FCT"})}
        labels = {"code": "Process code"}

    def clean_roles(self):
        """Each line is an equipment-type code ("Fixture: FIX-FCT" is also read)."""
        categories = []
        for raw in self.cleaned_data["roles"].splitlines():
            code = _upper(raw.rpartition(":")[2])
            if not code:
                continue
            category = Category.objects.filter(code=code).first()
            if category is None:
                raise forms.ValidationError(f"No equipment type with code {code}.")
            categories.append(category)
        if not categories:
            raise forms.ValidationError("List at least one equipment type.")
        return categories

    def save(self, commit=True):
        from systems.models import SystemTypeRole

        system_type = super().save()
        totals = {}
        for category in self.cleaned_data["roles"]:
            totals[category.pk] = totals.get(category.pk, 0) + 1
        seen = {}
        for position, category in enumerate(self.cleaned_data["roles"], start=1):
            seen[category.pk] = seen.get(category.pk, 0) + 1
            name = category.name if totals[category.pk] == 1 else f"{category.name} {seen[category.pk]}"
            role = SystemTypeRole.objects.create(
                system_type=system_type, name=name, position=position, is_required=True
            )
            role.allowed_categories.add(category)
        return system_type


class EquipmentQuickForm(CodeUpperMixin, forms.ModelForm):
    class Meta:
        from equipment.models import Equipment

        model = Equipment
        fields = ["code", "name", "category", "location", "manufacturer", "model_number", "serial_number"]
        widgets = {"code": forms.TextInput(attrs={"placeholder": "e.g. CART-005"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.active()
        self.fields["location"].queryset = Location.objects.active()

    def save(self, commit=True):
        asset = super().save()
        # Same opening entry as the full asset form, so the timeline starts cleanly.
        asset.status_history.create(
            from_status="", to_status=asset.status,
            changed_by=self.user, reason="Asset record created",
        )
        return asset


class PartQuickForm(CodeUpperMixin, forms.ModelForm):
    opening_stock = forms.DecimalField(label="Opening stock", min_value=0, required=False)

    class Meta:
        from inventory.models import InventoryItem

        model = InventoryItem
        fields = ["code", "name", "kind", "unit", "min_quantity", "storage_location"]
        widgets = {"code": forms.TextInput(attrs={"placeholder": "e.g. PRB-100-3A"})}

    def save(self, commit=True):
        from inventory.models import StockTransaction, TransactionType

        part = super().save()
        opening = self.cleaned_data.get("opening_stock")
        if opening:
            StockTransaction(
                item=part, transaction_type=TransactionType.IN, quantity=Decimal(opening),
                performed_by=self.user, reason="Opening stock",
            ).apply()
        return part


KINDS = {
    "product": ("New product", ProductQuickForm),
    "customer": ("New customer", CustomerQuickForm),
    "systemtype": ("New process", SystemTypeQuickForm),
    "location": ("New location / line", LocationQuickForm),
    "category": ("New category", CategoryQuickForm),
    "supplier": ("New supplier", SupplierQuickForm),
    "equipment": ("New asset", EquipmentQuickForm),
    "part": ("New spare part", PartQuickForm),
}

# The pop-up sits on top of a page that has its own form; its own ids must
# not collide with that form's (both would otherwise be "id_code", ...).
AUTO_ID = "qa_%s"

# Fields that may be pre-filled from the query string, e.g. the category of
# the role whose "+ New" was pressed.
PREFILL = {"category", "location", "kind"}


class QuickAddView(CanManageMixin, View):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if kwargs["kind"] not in KINDS:
            raise Http404("Unknown kind")
        self.title, self.form_class = KINDS[kwargs["kind"]]

    def render_form(self, form):
        return render(self.request, "core/quick_add.html", {
            "form": form, "title": self.title, "kind": self.kwargs["kind"],
        })

    def get(self, request, kind):
        initial = {k: v for k, v in request.GET.items() if k in PREFILL}
        return self.render_form(self.form_class(initial=initial, auto_id=AUTO_ID))

    def post(self, request, kind):
        form = self.form_class(request.POST, auto_id=AUTO_ID)
        form.user = request.user
        if not form.is_valid():
            return self.render_form(form)
        with transaction.atomic():
            obj = form.save()
        return JsonResponse({"id": obj.pk, "label": str(obj)})
