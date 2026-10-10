"""Forms for maintenance plans and the work logged against them."""

from django import forms

from core.forms import DateInput, PhotosField, retire_field

from .models import MaintenancePlan, MaintenanceRecord


class MaintenancePlanForm(forms.ModelForm):
    """Create or edit a recurring task. Equipment is set by the view."""

    class Meta:
        model = MaintenancePlan
        fields = [
            "name", "kind", "description", "checklist", "interval_days",
            "trigger_cycles", "estimated_minutes", "assignee", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Pogo pin cleaning"}),
            "description": forms.Textarea(attrs={"rows": 2}),
            "checklist": forms.Textarea(attrs={"rows": 4, "placeholder": "One item per line"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        retire_field(self, "plan")


class MaintenanceRecordForm(forms.ModelForm):
    """Log maintenance actually performed — against a plan, or unplanned."""

    photos = PhotosField()

    class Meta:
        model = MaintenanceRecord
        fields = [
            "plan", "kind", "performed_at", "work_done", "checklist_result",
            "result", "downtime_minutes", "cost", "notes",
        ]
        widgets = {
            "performed_at": DateInput(),
            "work_done": forms.Textarea(attrs={"rows": 3}),
            "checklist_result": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, equipment, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["plan"]
        field.queryset = equipment.maintenance_plans.filter(is_active=True)
        field.required = False
        field.empty_label = "— unplanned —"
        field.label = "Against plan"
        # The model defaults this to 0; don't force typing it for a quick log.
        self.fields["downtime_minutes"].required = False

    def clean_downtime_minutes(self):
        return self.cleaned_data.get("downtime_minutes") or 0
