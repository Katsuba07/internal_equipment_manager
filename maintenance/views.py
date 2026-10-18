"""Maintenance plans and the work logged against them — reached from an asset's detail page."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import CreateView, DetailView, UpdateView

from core.mixins import AdminRequiredMixin, CanManageMixin, CanRecordMixin
from core.modals import modal_saved, render_modal, wants_modal
from core.photos import save_photos
from equipment.models import Equipment

from .forms import MaintenancePlanForm, MaintenanceRecordForm
from .models import MaintenancePlan, MaintenanceRecord


class MaintenancePlanCreateView(CanManageMixin, CreateView):
    model = MaintenancePlan
    form_class = MaintenancePlanForm
    template_name = "maintenance/plan_form.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.equipment = get_object_or_404(Equipment, pk=kwargs["equipment_pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["equipment"] = self.equipment
        return context

    def as_modal(self, form):
        return render_modal(
            self.request, form,
            title=f"New maintenance plan — {self.equipment.ident}",
            subtitle=self.equipment.name,
            action=self.request.get_full_path(), submit="Create",
        )

    def get(self, request, *args, **kwargs):
        if wants_modal(request):
            return self.as_modal(self.get_form())
        return super().get(request, *args, **kwargs)

    def form_invalid(self, form):
        if wants_modal(self.request):
            return self.as_modal(form)
        return super().form_invalid(form)

    def form_valid(self, form):
        form.instance.equipment = self.equipment
        response = super().form_valid(form)
        messages.success(self.request, f"Added plan — {self.object.name}.")
        if wants_modal(self.request):
            return modal_saved()
        return response

    def get_success_url(self):
        return self.equipment.get_absolute_url()


class MaintenancePlanUpdateView(CanManageMixin, UpdateView):
    """Also where a plan is paused or resumed — see ``is_active`` on the form."""

    model = MaintenancePlan
    form_class = MaintenancePlanForm
    template_name = "maintenance/plan_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["equipment"] = self.object.equipment
        context["editing"] = True
        return context

    def as_modal(self, form):
        equipment = self.object.equipment
        return render_modal(
            self.request, form,
            title=f"Edit plan — {equipment.ident}",
            subtitle=self.object.name,
            action=self.request.get_full_path(), submit="Save",
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if wants_modal(request):
            return self.as_modal(self.get_form())
        return super().get(request, *args, **kwargs)

    def form_invalid(self, form):
        if wants_modal(self.request):
            return self.as_modal(form)
        return super().form_invalid(form)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Saved plan — {self.object.name}.")
        if wants_modal(self.request):
            return modal_saved()
        return response

    def get_success_url(self):
        return self.object.equipment.get_absolute_url()


class MaintenancePlanDeleteView(AdminRequiredMixin, View):
    """Delete a plan entered by mistake. Its past logs are kept, just unlinked."""

    def get(self, request, pk):
        plan = get_object_or_404(MaintenancePlan, pk=pk)
        records = plan.records.count()
        return render(request, "systems/confirm_delete.html", {
            "object": plan,
            "kind": "Maintenance plan",
            "summary": {
                "removed": [("Maintenance logs (kept, no longer linked to this plan)", records)] if records else [],
                "released": [],
            },
            "cancel_url": plan.equipment.get_absolute_url(),
        })

    def post(self, request, pk):
        plan = get_object_or_404(MaintenancePlan, pk=pk)
        equipment = plan.equipment
        name = plan.name
        plan.delete()
        messages.success(request, f"Deleted plan — {name}.")
        return redirect(equipment.get_absolute_url())


class MaintenanceRecordCreateView(CanRecordMixin, CreateView):
    """Log work performed — against a plan (rolls its due date forward) or unplanned."""

    model = MaintenanceRecord
    form_class = MaintenanceRecordForm
    template_name = "maintenance/record_form.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.equipment = get_object_or_404(Equipment, pk=kwargs["equipment_pk"])

    def get_initial(self):
        return {"plan": self.request.GET.get("plan")}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["equipment"] = self.equipment
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["equipment"] = self.equipment
        return context

    def as_modal(self, form):
        return render_modal(
            self.request, form,
            title=f"Log maintenance — {self.equipment.ident}",
            subtitle=self.equipment.name,
            action=self.request.get_full_path(), submit="Log",
        )

    def get(self, request, *args, **kwargs):
        if wants_modal(request):
            return self.as_modal(self.get_form())
        return super().get(request, *args, **kwargs)

    def form_invalid(self, form):
        if wants_modal(self.request):
            return self.as_modal(form)
        return super().form_invalid(form)

    def form_valid(self, form):
        form.instance.equipment = self.equipment
        form.instance.performed_by = self.request.user
        response = super().form_valid(form)
        save_photos(self.object, form.cleaned_data.get("photos"), self.request.user)
        messages.success(self.request, f"Logged maintenance for {self.equipment.ident}.")
        if wants_modal(self.request):
            return modal_saved()
        return response

    def get_success_url(self):
        return self.equipment.get_absolute_url()


class MaintenanceRecordDetailView(LoginRequiredMixin, DetailView):
    queryset = MaintenanceRecord.objects.select_related(
        "equipment", "plan", "performed_by"
    ).prefetch_related("attachments")
    template_name = "maintenance/record_detail.html"
    context_object_name = "record"
