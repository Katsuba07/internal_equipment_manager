"""Forms for equipment records."""

from datetime import timedelta

from django import forms

from core.forms import DateInput, PhotosField, RequestFormMixin, offer_photo_removal, photos_to_remove_field
from core.models import Category

from .models import Equipment


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
    # Saving a measuring instrument without calibration, or without its dates,
    # takes a yes: from the page's own question (app.js), or — should that not
    # run — by ticking this when the form comes back with the warning.
    calibration_confirmed = forms.BooleanField(required=False, label="Save it this way anyway")

    class Meta:
        model = Equipment
        fields = [
            "category", "equipment_no", "manufacturer", "model_number", "name", "serial_number",
            "plant", "status", "labelled", "code", "asset_no", "specifications",
            "maintenance_required", "maintenance_interval_days",
            "is_measuring_device", "notes",
        ]
        widgets = {
            "specifications": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "code": forms.TextInput(attrs={"placeholder": "e.g. 70-000148"}),
            "equipment_no": forms.TextInput(attrs={"placeholder": "e.g. DMM-0001"}),
            "asset_no": forms.TextInput(attrs={"placeholder": "e.g. 103220100359"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only offer catalogs that are still in use, so retired entries
        # cannot be picked by accident.
        self.fields["equipment_no"].required = True
        self.fields["equipment_no"].error_messages["required"] = "Give the asset its Equipment No (for example DMM-0001)."
        self.fields["code"].required = False
        # Left out of a post, the status stays as it is (In use for a new asset).
        self.fields["status"].required = False
        # Every asset belongs to a plant.
        self.fields["plant"].required = True
        self.fields["plant"].error_messages["required"] = "Choose the plant the asset belongs to."
        # The name follows Manufacturer + Model (see [data-auto-name] in
        # app.js); typed over by hand, it is kept as typed.
        self.fields["name"].required = False
        self.fields["name"].widget.attrs.update({
            "data-auto-name": "", "placeholder": "Filled in from Manufacturer + Model",
        })
        # An asset whose name is still its Manufacturer + Model keeps following
        # them when they are edited; a name typed by hand is left alone.
        if self.instance.pk:
            made = " ".join(x for x in (self.instance.manufacturer, self.instance.model_number) if x)
            if made and " ".join(self.instance.name.split()).upper() == " ".join(made.split()).upper():
                self.fields["name"].widget.attrs["data-made"] = self.instance.name
        # Shown in capitals as typed; saved in capitals (Equipment.save).
        for name in Equipment.UPPER_FIELDS:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs["class"] = (widget.attrs.get("class", "") + " text-upper").strip()
        self.fields["category"].queryset = Category.objects.active()
        # Types that need calibration: picking one ticks "Requires calibration",
        # and saving one unticked, or ticked with no dates, asks first (app.js).
        self.fields["category"].widget.attrs["data-calibration-types"] = ",".join(
            str(pk) for pk in Category.objects.filter(needs_calibration=True).values_list("pk", flat=True)
        )
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
        # The ZT Code goes on the QR label, so normalise case and stray spaces.
        value = self.cleaned_data.get("code", "").strip().upper()
        if value:
            taken = Equipment.objects.exclude(pk=self.instance.pk).filter(code=value).first()
            if taken:
                raise forms.ValidationError(f"ZT Code {value} is already on {taken.ident}.")
        return value

    def clean_equipment_no(self):
        """The asset's key: required, and one asset per number."""
        value = Equipment.normalise_equipment_no(self.cleaned_data.get("equipment_no", ""))
        if not value:
            raise forms.ValidationError("Give the asset its Equipment No (for example DMM-0001).")
        taken = Equipment.objects.exclude(pk=self.instance.pk).filter(equipment_no=value).first()
        if taken:
            # Often two people took the same suggested number at once: say
            # which one is free now (the photos sent with the form are kept).
            category = self.cleaned_data.get("category")
            free = Equipment.equipment_no_counter(category)["next"] if category else ""
            hint = f" The next free number is {free}." if free else ""
            raise forms.ValidationError(f"Equipment No {value} is already on {taken.name} — saved just before you.{hint}")
        return value

    def clean_status(self):
        return self.cleaned_data.get("status") or self.instance.status or Equipment._meta.get_field("status").default

    # Stand-ins typed when a nameplate has no serial: several assets may share them.
    NO_SERIAL = {"NA", "N/A", "N.A", "-", "--", "NONE", "NIL", "0", "NO S/N", "UNKNOWN"}

    def clean_serial_number(self):
        """One asset per serial number: a repeat is usually a barcode scanned in its place."""
        value = " ".join(self.cleaned_data.get("serial_number", "").split()).upper()
        if not value or value in self.NO_SERIAL:
            return value
        if self.instance.pk and self.instance.serial_number.upper() == value:
            return value      # already its S/N: a repeat on record is fixed on purpose, not on every edit
        taken = list(Equipment.objects.exclude(pk=self.instance.pk).filter(serial_number__iexact=value)[:3])
        if taken:
            names = ", ".join(f"{asset.ident} ({asset.name})" for asset in taken)
            raise forms.ValidationError(
                f"S/N {value} is already on {names}. Check the nameplate: a product barcode "
                "is sometimes read in place of the serial number."
            )
        return value

    def clean_asset_no(self):
        value = " ".join(self.cleaned_data.get("asset_no", "").split()).upper()
        if value:
            taken = Equipment.objects.exclude(pk=self.instance.pk).filter(asset_no=value).first()
            if taken:
                raise forms.ValidationError(f"Asset No. {value} is already on {taken.ident}.")
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
        if not cleaned.get("name"):
            name = " ".join(x for x in (cleaned.get("manufacturer", "").strip(), cleaned.get("model_number", "").strip()) if x)
            if name:
                cleaned["name"] = name
            else:
                self.add_error("name", "Give a name, or a Manufacturer and Model to make one from.")
        if cleaned.get("maintenance_required") and not cleaned.get("maintenance_interval_days"):
            self.add_error("maintenance_interval_days", "Choose how often this asset is maintained.")
        for last_field, next_field in (("maintenance_last", "maintenance_next"),
                                       ("calibration_last", "calibration_next")):
            last, due = cleaned.get(last_field), cleaned.get(next_field)
            if last and due and due < last:
                self.add_error(next_field, "The next one cannot come before the last one.")
        question = self.calibration_question(cleaned)
        if question and not cleaned.get("calibration_confirmed"):
            self.add_error("calibration_confirmed", question)
        return cleaned

    @staticmethod
    def calibration_question(cleaned) -> str:
        """What has to be confirmed before saving, if anything (the page asks the same)."""
        category = cleaned.get("category")
        if category and category.needs_calibration and not cleaned.get("is_measuring_device"):
            return (f"{category.name} normally needs calibration, but Requires calibration is not ticked. "
                    "Tick it, or confirm it really needs none.")
        if cleaned.get("is_measuring_device") and not cleaned.get("calibration_last") and not cleaned.get("calibration_next"):
            return ("No calibration dates are filled in: the asset will show Calibration date unknown and must "
                    "not be used for measuring until it is calibrated. Fill in the dates, or confirm.")
        return ""
