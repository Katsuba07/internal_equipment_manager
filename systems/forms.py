"""Forms for the products page: products, their processes, roles and sets."""

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.urls import reverse
from django.utils import timezone

from calibration.models import add_months
from core.forms import DateInput, PhotosField, offer_photo_removal, photos_to_remove_field, retire_field
from core.models import Category, Customer, Location, Product
from equipment.models import Equipment

from .models import GoldenKind, GoldenSample, ProcessRole, ProductProcess, SystemType, TestSet


class ProductForm(forms.ModelForm):
    processes = forms.ModelMultipleChoiceField(
        queryset=SystemType.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Processes that need equipment",
    )

    class Meta:
        model = Product
        fields = ["customer", "code", "plant", "name", "revision", "in_production", "description", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "e.g. RMMTT01"}),
            "name": forms.TextInput(attrs={"placeholder": "Optional — products go by their model code"}),
            "description": forms.Textarea(attrs={"rows": 2}),
            "customer": forms.Select(attrs={"data-qa-kind": "customer"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.active()
        self.fields["customer"].empty_label = "— choose —"
        retire_field(self, "product")
        if self.instance.pk:
            # The route is edited step by step on the product panel.
            del self.fields["processes"]
        else:
            self.fields["processes"].queryset = SystemType.objects.active()

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class AddProcessForm(forms.Form):
    process = forms.ModelChoiceField(queryset=SystemType.objects.none(), label="Add process")

    def __init__(self, *args, product: Product, **kwargs):
        super().__init__(*args, **kwargs)
        taken = product.processes.values_list("process_id", flat=True)
        field = self.fields["process"]
        field.queryset = SystemType.objects.active().exclude(pk__in=taken)
        field.empty_label = "— choose —"
        field.widget.attrs["data-qa-kind"] = "systemtype"


class RoleForm(forms.ModelForm):
    """A role is just the type of equipment a set needs; its name follows."""

    class Meta:
        model = ProcessRole
        fields = ["category", "is_required"]
        widgets = {
            "category": forms.Select(attrs={"data-qa-kind": "category", "style": "width:100%"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["category"]
        field.queryset = Category.objects.active()
        field.required = True
        field.empty_label = "— choose equipment type —"
        field.label = "Role (equipment type)"


class BaseRoleFormSet(BaseInlineFormSet):
    def save(self, commit=True):
        """Save the rows and number them in the order they are shown."""
        saved = super().save(commit=False)
        for obj in self.deleted_objects:
            obj.delete()
        position = 0
        for form in self.forms:
            if form in self.deleted_forms or (not form.instance.pk and not form.has_changed()):
                continue
            position += 1
            form.instance.product_process = self.instance
            form.instance.position = position
            if not form.instance.pk:
                form.instance.name = f"~new{position}"   # unique until named below
            form.instance.save()
        self.instance.name_roles()
        return saved


RoleFormSet = inlineformset_factory(
    ProductProcess, ProcessRole, form=RoleForm, formset=BaseRoleFormSet,
    extra=2, can_delete=True,
)


class RoleSetupForm(RoleForm):
    """One row of the process frame: the role, and the asset fitted to it in the chosen set."""

    equipment = forms.ModelChoiceField(
        queryset=Equipment.objects.active(), required=False, widget=forms.HiddenInput,
    )


class BaseRoleSetupFormSet(BaseRoleFormSet):
    """
    Roles and equipment in one frame. ``test_set`` is the set whose equipment
    is shown; ``can_manage`` decides whether the roles themselves can change —
    a technician fits equipment to the roles a manager laid down.
    """

    def __init__(self, *args, test_set=None, can_manage=False, **kwargs):
        self.test_set = test_set
        self.can_manage = can_manage
        super().__init__(*args, **kwargs)
        self._fitted = {}
        if test_set is not None:
            self._fitted = {i.role_id: i.component for i in test_set.open_installations().select_related("component")}
        for form in self.forms:
            self._decorate(form)

    @property
    def empty_form(self):
        # Django builds a fresh blank row on every access; dress each one.
        return self._decorate(super().empty_form)

    def _decorate(self, form):
        """The search box of a row: what it holds, and which machines it offers."""
        role = form.instance
        chosen = self._fitted.get(role.pk) if role.pk else None
        if chosen and not form.is_bound:
            form.initial["equipment"] = chosen.pk
        form.chosen_asset = chosen
        set_part = f"set={self.test_set.pk}&" if self.test_set is not None else ""
        form.picker_source = f"{reverse('equipment:search')}?{set_part}category={role.category_id or ''}"
        form.picker_empty = f"No {role.category.name} registered yet." if role.category_id else ""
        if not self.can_manage:
            for name in ("category", "is_required"):
                form.fields[name].disabled = True
        return form

    def picks(self) -> dict:
        """role id -> asset chosen for it (or None), for the rows that remain."""
        chosen = {}
        for form in self.forms:
            if form in self.deleted_forms or not form.instance.pk:
                continue
            chosen[form.instance.pk] = form.cleaned_data.get("equipment")
        return chosen


RoleSetupFormSet = inlineformset_factory(
    ProductProcess, ProcessRole, form=RoleSetupForm, formset=BaseRoleSetupFormSet,
    extra=1, can_delete=True,
)


class SetLineForm(forms.ModelForm):
    class Meta:
        model = TestSet
        fields = ["line", "notes"]
        widgets = {"line": forms.Select(attrs={"data-qa-kind": "location"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["line"].queryset = Location.objects.active()
        self.fields["line"].empty_label = "— not set —"


class GoldenSampleForm(forms.ModelForm):
    """One reference board of a process. The process is set by the view."""

    remove_photos = photos_to_remove_field()
    photos = PhotosField()

    class Meta:
        model = GoldenSample
        fields = [
            "code", "kind", "expected_defect", "storage_location",
            "valid_from", "interval_months", "valid_until", "status", "notes",
        ]
        widgets = {
            # Only an NG sample has a defect to name (see [data-shown-when] in app.js).
            "expected_defect": forms.TextInput(attrs={"data-shown-when": "id_kind=NG"}),
            "valid_from": DateInput(),
            # Refilled as the start date or the interval changes; can be typed over.
            "valid_until": DateInput(attrs={
                "data-next-from": "id_valid_from", "data-interval": "id_interval_months", "data-unit": "months",
            }),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, product_process=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.product_process = product_process or self.instance.product_process
        if not self.instance.pk:
            self.fields["valid_from"].initial = timezone.localdate
        self.fields["interval_months"].widget.attrs["min"] = 1
        # The labels say enough; this form carries no hints under its fields.
        for field in self.fields.values():
            field.help_text = ""
        offer_photo_removal(self)
        if not self.fields["remove_photos"].choices:
            del self.fields["remove_photos"]

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        clash = GoldenSample.objects.filter(product_process=self.product_process, code=code)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"{self.product_process} already has a sample {code}.")
        return code

    def clean(self):
        data = super().clean()
        if data.get("kind") == GoldenKind.NG and not data.get("expected_defect"):
            self.add_error("expected_defect", "Say what an NG sample must fail on.")
        if data.get("kind") == GoldenKind.OK:
            data["expected_defect"] = ""
        start, months, until = data.get("valid_from"), data.get("interval_months"), data.get("valid_until")
        if months and not start:
            self.add_error("valid_from", "Give the date the interval starts from.")
        if start and months and not until:
            data["valid_until"] = add_months(start, months)
        elif start and until and until < start:
            self.add_error("valid_until", "This is before the date the sample is applied from.")
        return data


class GoldenRequirementForm(forms.ModelForm):
    """How many usable OK and NG samples the process should hold."""

    class Meta:
        model = ProductProcess
        fields = ["golden_ok_required", "golden_ng_required"]
