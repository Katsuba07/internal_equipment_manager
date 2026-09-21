"""Forms for spare parts, stock movements and equipment parts lists."""

from decimal import Decimal

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.urls import reverse

from core.forms import PhotosField, offer_photo_removal, photos_to_remove_field, retire_field
from core.models import Supplier
from equipment.models import Equipment

from .models import EquipmentPart, InventoryItem, ItemKind, StockTransaction, TransactionType


class PartForm(forms.ModelForm):
    """Create or edit a stocked part. The balance only changes through movements."""

    photos = PhotosField(help_text="On a phone: take a picture or pick from the gallery. Tap again to add more; × takes one out before saving.")
    remove_photos = photos_to_remove_field()

    opening_stock = forms.DecimalField(
        label="Opening stock",
        min_value=0,
        required=False,
        help_text="Quantity on the shelf today. Recorded as the first receipt.",
    )

    class Meta:
        model = InventoryItem
        fields = [
            "code", "name", "kind", "unit", "specification", "manufacturer_part",
            "min_quantity", "plant", "storage_location", "supplier", "unit_price",
            "lead_time_days", "is_active", "notes",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "e.g. PRB-100-3A"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.active()
        offer_photo_removal(self)
        if self.instance.pk:
            del self.fields["opening_stock"]
        retire_field(self, "part")

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class EquipmentPicker(forms.Widget):
    """
    A search box instead of a dropdown.

    The floor has hundreds of assets; a <select> of that size is a scroll hunt.
    This types to search (see ``data-picker`` in app.js) and offers the assets
    that carry this part first.
    """

    # Widget templates are loaded by the form renderer, which only searches
    # the apps' own template folders — hence inventory/templates/, not the
    # project-wide templates/ used by every page.
    template_name = "inventory/widgets/equipment_picker.html"

    def __init__(self, attrs=None, source_url: str = ""):
        super().__init__(attrs)
        self.source_url = source_url

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["source_url"] = self.source_url
        context["chosen"] = Equipment.objects.filter(pk=value).first() if value else None
        return context


class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockTransaction
        fields = ["transaction_type", "quantity", "equipment", "reason", "note"]
        widgets = {
            "reason": forms.TextInput(attrs={"placeholder": "e.g. Replaced worn probes on FIX-BAF1950"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, part=None, **kwargs):
        super().__init__(*args, **kwargs)
        source = reverse("equipment:search")
        if part is not None:
            source = f"{source}?part={part.pk}"
        field = self.fields["equipment"]
        field.queryset = Equipment.objects.active()
        field.widget = EquipmentPicker(source_url=source)
        field.required = False          # only an issue needs a destination
        field.label = "Issue to"
        field.help_text = "The asset the part is going on. Assets that list this part come first."

    def clean(self):
        data = super().clean()
        if data.get("transaction_type") == TransactionType.OUT:
            if not data.get("equipment"):
                self.add_error("equipment", "Choose the asset this part is going to.")
        else:
            # A receipt or a stocktake has no destination.
            data["equipment"] = None
        return data

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity is None or quantity < 0:
            raise forms.ValidationError("Quantity must be positive.")
        if quantity == 0 and self.data.get("transaction_type") != TransactionType.ADJUST:
            raise forms.ValidationError("Quantity must be more than zero.")
        return quantity


class EquipmentPartForm(forms.ModelForm):
    class Meta:
        model = EquipmentPart
        fields = ["item", "quantity", "notes"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"min": "0", "step": "any", "style": "max-width:7rem"}),
            "notes": forms.TextInput(attrs={"placeholder": "Optional"}),
            "item": forms.Select(attrs={"data-qa-kind": "part", "style": "width:100%"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = InventoryItem.objects.filter(
            is_active=True
        ).exclude(kind=ItemKind.SPARE_EQUIPMENT)
        self.fields["item"].empty_label = "— choose a part —"
        self.fields["quantity"].initial = Decimal("1")
        if self.instance.pk:
            # Show 96, not 96.00.
            self.initial["quantity"] = f"{self.instance.quantity:f}".rstrip("0").rstrip(".")

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Must be more than zero.")
        return quantity


class BaseEquipmentPartFormSet(BaseInlineFormSet):
    def get_unique_error_message(self, unique_check):
        return "A part is listed twice — put the total quantity on one line."


EquipmentPartFormSet = inlineformset_factory(
    Equipment,
    EquipmentPart,
    form=EquipmentPartForm,
    formset=BaseEquipmentPartFormSet,
    extra=3,
    can_delete=True,
)
