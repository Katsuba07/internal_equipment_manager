"""Forms for equipment records."""

from datetime import timedelta

from django import forms

from core.forms import DateInput, PhotosField, RequestFormMixin, offer_photo_removal, photos_to_remove_field
from core.models import Category, Location, Supplier

from .models import Equipment, EquipmentStatus


class EquipmentForm(RequestFormMixin, forms.ModelForm):
    """Create and edit an asset."""

    # The dates live on the asset's maintenance and calibration plans, not on
    # the asset; they are edited here all the same, since that is where people
    # look for them (see save_schedules).
    photos = PhotosField()
    remove_photos = photos_to_remove_field()
    nameplate_photos = PhotosField(label="Add nameplate / marking photos")
    remove_nameplate_photos = photos_to_remove_field()
    maintenance_last = forms.DateField(label="Last maintenance", required=False, widget=DateInput())
    maintenance_next = forms.DateField(
        label="Next maintenance due", required=False,
        widget=DateInput(attrs={"data-next-from": "id_maintenance_last",
                                "data-interval": "id_maintenance_interval_days", "data-unit": "days"}),
    )
    calibration_interval_months = forms.IntegerField(
        label="Calibration every (months)", required=False, min_value=1, max_value=120, initial=12,
    )
    calibration_last = forms.DateField(label="Last calibrated", required=False, widget=DateInput())
    calibration_next = forms.DateField(
        label="Next calibration due", required=False,
        widget=DateInput(attrs={"data-next-from": "id_calibration_last",
                                "data-interval": "id_calibration_interval_months", "data-unit": "months"}),
        help_text="The date on the calibration sticker.",
    )

    class Meta:
        model = Equipment
        fields = [
            "code", "asset_no", "serial_number", "name", "category", "plant", "location",
            "manufacturer", "model_number", "year_made", "country_of_origin", "condition",
            "firmware_version", "specifications", "voltage", "power_watt", "dimensions",
            "supplier", "purchase_date", "purchase_cost",
            "commissioned_date", "warranty_until",
            "maintenance_required", "maintenance_interval_days",
            "is_measuring_device", "notes",
        ]
        widgets = {
            "purchase_date": DateInput(),
            "commissioned_date": DateInput(),
            "warranty_until": DateInput(),
            "specifications": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "code": forms.TextInput(attrs={"placeholder": "e.g. CTV20200077"}),
            "asset_no": forms.TextInput(attrs={"placeholder": "e.g. 103220100359"}),
            "voltage": forms.TextInput(attrs={"placeholder": "e.g. AC220V"}),
            "dimensions": forms.TextInput(attrs={"placeholder": "e.g. 105 × 65 × 160"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only offer catalogs that are still in use, so retired entries
        # cannot be picked by accident.
        self.fields["category"].queryset = Category.objects.active()
        self.fields["location"].queryset = Location.objects.active()
        self.fields["location"].empty_label = "— not set yet —"
        self.fields["supplier"].queryset = Supplier.objects.active()
        self.fields["supplier"].required = False
        self._load_schedules()
        offer_photo_removal(self)
        offer_photo_removal(self, field="remove_nameplate_photos", attr="nameplate_photos")
        # Interval and dates only open once the tick says the schedule applies
        # (see [data-needs] in app.js); left shut, they are not sent at all.
        for tick, fields in (
            ("id_maintenance_required", ("maintenance_interval_days", "maintenance_last", "maintenance_next")),
            ("id_is_measuring_device", ("calibration_interval_months", "calibration_last", "calibration_next")),
        ):
            for name in fields:
                self.fields[name].widget.attrs["data-needs"] = tick

    def clean_code(self):
        # The ID goes on the QR label, so normalise case and stray spaces.
        return self.cleaned_data["code"].strip().upper()

    def clean_asset_no(self):
        value = " ".join(self.cleaned_data.get("asset_no", "").split()).upper()
        if value:
            taken = Equipment.objects.exclude(pk=self.instance.pk).filter(asset_no=value).first()
            if taken:
                raise forms.ValidationError(f"Asset No. {value} is already on {taken.code}.")
        return value

    # --- Maintenance and calibration dates -------------------------------

    def _load_schedules(self):
        asset = self.instance
        if not asset.pk:
            return
        plan = asset.maintenance_plans.filter(name=Equipment.SCHEDULED_PLAN_NAME).first()
        if plan:
            self.initial.setdefault("maintenance_last", plan.last_done_at)
            self.initial.setdefault("maintenance_next", plan.next_due_at)
        calibration = self.calibration_plan(asset)
        if calibration:
            self.initial.setdefault("calibration_interval_months", calibration.interval_months)
            self.initial.setdefault("calibration_last", calibration.last_calibrated_at)
            self.initial.setdefault("calibration_next", calibration.next_due_at)

    @staticmethod
    def calibration_plan(asset):
        """The plan the asset's calibration dates belong to: the soonest active one."""
        return (
            asset.calibration_plans.filter(is_active=True).order_by("next_due_at").first()
            or asset.calibration_plans.order_by("-updated_at").first()
        )

    def save_schedules(self, asset):
        """Write the dates to the plans. Call after the asset is saved."""
        data = self.cleaned_data

        plan = asset.sync_maintenance_plan()
        if plan and plan.is_active:
            last, due = data.get("maintenance_last"), data.get("maintenance_next")
            if last and not due:
                due = last + timedelta(days=plan.interval_days)
            if (last, due) != (plan.last_done_at, plan.next_due_at) and (last or due):
                plan.last_done_at = last
                plan.next_due_at = due or plan.next_due_at
                plan.save(update_fields=["last_done_at", "next_due_at", "updated_at"])

        from calibration.models import CalibrationPlan, add_months

        calibration = self.calibration_plan(asset)
        if not asset.is_measuring_device:
            if calibration and calibration.is_active:
                calibration.is_active = False
                calibration.save(update_fields=["is_active", "updated_at"])
            return
        months = data.get("calibration_interval_months") or 12
        last, due = data.get("calibration_last"), data.get("calibration_next")
        if last and not due:
            due = add_months(last, months)
        if calibration is None:
            CalibrationPlan.objects.create(
                equipment=asset, name="Calibration", interval_months=months,
                last_calibrated_at=last, next_due_at=due, is_active=True,
            )
            return
        calibration.is_active = True
        calibration.interval_months = months
        calibration.last_calibrated_at = last
        calibration.next_due_at = due
        calibration.save()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("maintenance_required") and not cleaned.get("maintenance_interval_days"):
            self.add_error("maintenance_interval_days", "Choose how often this asset is maintained.")
        for last_field, next_field in (("maintenance_last", "maintenance_next"),
                                       ("calibration_last", "calibration_next")):
            last, due = cleaned.get(last_field), cleaned.get(next_field)
            if last and due and due < last:
                self.add_error(next_field, "The next one cannot come before the last one.")
        purchase = cleaned.get("purchase_date")
        commissioned = cleaned.get("commissioned_date")
        warranty = cleaned.get("warranty_until")

        if purchase and commissioned and commissioned < purchase:
            self.add_error(
                "commissioned_date", "In-service date cannot precede the purchase date."
            )
        if purchase and warranty and warranty < purchase:
            self.add_error("warranty_until", "Warranty cannot end before the purchase date.")
        return cleaned


class StatusChangeForm(RequestFormMixin, forms.Form):
    """
    Move an asset to a new status.

    Kept separate from EquipmentForm so every status change lands in the
    history with who and when — that is what makes status auditable. The
    reason is welcome but optional.

    "In production" is not offered unless the asset is fitted to a product in
    production: that status follows the Products page, not a person's pick.
    """

    status = forms.ChoiceField(label="New status", choices=EquipmentStatus.choices)
    reason = forms.CharField(
        label="Reason",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Optional — e.g. Sent to vendor for repair"}),
    )
    note = forms.CharField(
        label="Details", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, equipment: Equipment | None = None, **kwargs):
        self.equipment = equipment
        self.running = None
        super().__init__(*args, **kwargs)
        if equipment:
            # Drop the current status so it cannot be re-selected, and In
            # production unless the asset is fitted to a running product.
            self.running = equipment.running_fitting()
            self.fields["status"].choices = [
                (value, label)
                for value, label in EquipmentStatus.choices
                if value != equipment.status
                and (value != EquipmentStatus.IN_PRODUCTION or self.running)
            ]

    def clean_status(self):
        status = self.cleaned_data["status"]
        if status == EquipmentStatus.IN_PRODUCTION and self.equipment and not self.running:
            raise forms.ValidationError(
                "Only equipment fitted to a product in production is In production. "
                "Fit it into an equipment set on the Products page."
            )
        return status


class EquipmentImportForm(forms.Form):
    """Bulk-load assets from a spreadsheet."""

    file = forms.FileField(label="Excel file (.xlsx)")
    update_existing = forms.BooleanField(
        label="Update assets that already exist (matched on Equipment ID)",
        required=False,
        help_text="Leave unticked and rows with an existing ID are skipped instead of overwritten.",
    )

    def clean_file(self):
        file = self.cleaned_data["file"]
        if not file.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(
                "Only .xlsx files are accepted. If you have a .xls or .csv, "
                "open it in Excel and use Save As → .xlsx."
            )
        return file
