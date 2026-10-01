"""Equipment screens."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, UpdateView
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin

from calibration.models import CalibrationPlan
from core.bulk import BulkDeleteView
from core.models import Attachment, AttachmentKind
from core.photos import remove_photos, save_photos
from maintenance.models import MaintenancePlan
from systems.models import Installation
from core.mixins import AdminRequiredMixin, CanManageMixin, CanRecordMixin
from core.modals import modal_saved, render_modal, wants_modal
from inventory.forms import EquipmentPartFormSet
from systems.services import equipment_usage

from .deletion import delete_assets, history_counts
from .filters import EquipmentFilter
from .forms import EquipmentForm, EquipmentImportForm, StatusChangeForm
from .models import Equipment, EquipmentStatus
from .services import build_template_workbook, export_equipment_to_xlsx, import_equipment_from_xlsx
from .tables import EquipmentTable


def _xlsx_response(workbook, filename: str) -> HttpResponse:
    """Wrap a workbook as a download."""
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response


class EquipmentSearchView(LoginRequiredMixin, View):
    """
    Type-ahead for picking an asset, so nobody has to scroll a list of hundreds.

    With ``?part=<id>`` the assets that carry that part on their own parts list
    are offered first, and before anything is typed they are the whole list —
    an issue almost always goes to one of them.
    """

    LIMIT = 20

    def get(self, request, *args, **kwargs):
        from inventory.models import EquipmentPart
        from systems.models import TestSet
        from systems.services import busy_map

        query = request.GET.get("q", "").strip()
        part_id = request.GET.get("part")
        category = request.GET.get("category", "")
        set_id = request.GET.get("set", "")
        listed_ids = []
        if part_id:
            listed_ids = list(
                EquipmentPart.objects.filter(item_id=part_id).values_list("equipment_id", flat=True)
            )
        # Filling a set: machines fitted in any other set are shown but marked.
        busy = {}
        if set_id.isdigit():
            busy = busy_map(exclude_set=TestSet.objects.filter(pk=set_id).first())

        assets = Equipment.objects.active().with_related()
        if category.isdigit():
            assets = assets.filter(category_id=category)
        if query:
            assets = assets.filter(
                Q(code__icontains=query)
                | Q(asset_no__icontains=query)
                | Q(name__icontains=query)
                | Q(serial_number__icontains=query)
            )
        elif listed_ids:
            # Nothing typed yet: show the obvious candidates, not the whole floor.
            assets = assets.filter(pk__in=listed_ids)

        if listed_ids:
            rank = Case(When(pk__in=listed_ids, then=Value(0)), default=Value(1), output_field=IntegerField())
        elif busy:
            rank = Case(When(pk__in=list(busy), then=Value(1)), default=Value(0), output_field=IntegerField())
        else:
            rank = Value(0, output_field=IntegerField())
        order = ("rank", "code") if query or listed_ids or busy else ("rank", "-updated_at")
        assets = assets.annotate(rank=rank).order_by(*order)

        results = [
            {
                "id": asset.pk,
                "code": asset.code,
                "name": asset.name,
                "ids": " · ".join(x for x in [asset.asset_no, asset.serial_number] if x),
                "where": " · ".join(x for x in [asset.location.name if asset.location_id else "", asset.plant_display] if x and x != "—"),
                "status": asset.get_status_display(),
                "on_list": asset.pk in listed_ids,
                "busy": busy.get(asset.pk, ""),
            }
            for asset in assets[: self.LIMIT]
        ]
        return JsonResponse({"results": results, "query": query})


class EquipmentListView(LoginRequiredMixin, SingleTableMixin, FilterView):
    """Equipment list with search, filters, sorting and paging."""

    model = Equipment
    table_class = EquipmentTable
    filterset_class = EquipmentFilter
    template_name = "equipment/equipment_list.html"
    paginate_by = 25

    def get_queryset(self):
        return Equipment.objects.with_related()

    def get_table_kwargs(self):
        # The tick boxes for "Delete selected" are for administrators only.
        if not self.request.user.is_admin:
            return {"exclude": ("select",)}
        return {}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Counts reflect the filtered result, not the whole table.
        filtered = self.filterset.qs
        context["total_count"] = filtered.count()
        context["has_filters"] = any(
            value for key, value in self.request.GET.items() if key not in {"page", "sort"}
        )
        counts = {
            row["status"]: row["count"]
            for row in filtered.values("status").annotate(count=Count("id"))
        }
        context["quick_stats"] = [
            ("In production", counts.get(EquipmentStatus.IN_PRODUCTION, 0), "success"),
            ("Down / repair",
             counts.get(EquipmentStatus.DOWN, 0) + counts.get(EquipmentStatus.REPAIR, 0),
             "danger"),
            ("Calibration", counts.get(EquipmentStatus.CALIBRATION, 0), "primary"),
        ]
        return context


class EquipmentDetailView(LoginRequiredMixin, DetailView):
    """Full record for one asset, including its status timeline."""

    model = Equipment
    template_name = "equipment/equipment_detail.html"
    context_object_name = "equipment"

    def get_queryset(self):
        return Equipment.objects.with_related().prefetch_related(
            "status_history__changed_by", "attachments", "parts__item"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_history"] = self.object.status_history.all()[:50]
        context["calibration_plans"] = self.object.calibration_plans.filter(is_active=True)
        context["maintenance_plans"] = self.object.maintenance_plans.filter(is_active=True)
        # Where this asset is used and where it physically sits — the cross-use
        # answer from the component's own side.
        context["usage"] = equipment_usage(self.object)
        # Spare parts that were issued to this asset — the other half of the
        # traceability the parts list gives.
        context["part_issues"] = self.object.part_issues.filter(
            transaction_type="OUT"
        ).select_related("item", "performed_by")[:20]
        return context


class PartsFormsetMixin:
    """The asset form carries the asset's own parts list (part + quantity)."""

    def get_parts_formset(self):
        instance = self.object if getattr(self, "object", None) else Equipment()
        return EquipmentPartFormSet(
            self.request.POST or None, instance=instance, prefix="parts"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("parts_formset", self.get_parts_formset())
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if self.kwargs.get("pk") else None
        form = self.get_form()
        parts = self.get_parts_formset()
        if form.is_valid() and parts.is_valid():
            with transaction.atomic():
                response = self.form_valid(form)
                parts.instance = self.object
                parts.save()
            return response
        return self.render_to_response(
            self.get_context_data(form=form, parts_formset=parts)
        )


class EquipmentPreviewView(LoginRequiredMixin, DetailView):
    """
    The quick-look drawer on the equipment list: photo, key facts, where it is
    fitted, what is due. Opened on its own (not by the list), it goes to the
    full page instead.
    """

    model = Equipment
    template_name = "equipment/_preview.html"
    context_object_name = "equipment"

    def get_queryset(self):
        return Equipment.objects.with_related().prefetch_related("attachments", "parts__item")

    def get(self, request, *args, **kwargs):
        if request.headers.get("HX-Request") != "true":
            return redirect("equipment:detail", pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        asset = self.object
        context["installation"] = asset.current_installation
        context["calibration"] = asset.calibration_plans.filter(is_active=True).order_by("next_due_at").first()
        context["maintenance"] = asset.maintenance_plans.filter(is_active=True).order_by("next_due_at").first()
        context["open_incidents"] = asset.incidents.open().count()
        return context


class EquipmentCreateView(CanManageMixin, PartsFormsetMixin, CreateView):
    model = Equipment
    form_class = EquipmentForm
    template_name = "equipment/equipment_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        form.save_schedules(self.object)
        remove_photos(self.object, form.cleaned_data.get("remove_photos"))
        save_photos(self.object, form.cleaned_data.get("photos"), self.request.user)
        remove_photos(self.object, form.cleaned_data.get("remove_nameplate_photos"), kind=AttachmentKind.NAMEPLATE)
        save_photos(self.object, form.cleaned_data.get("nameplate_photos"), self.request.user, kind=AttachmentKind.NAMEPLATE)
        # Every asset starts its timeline with an opening entry, so the
        # history never begins mid-story.
        self.object.status_history.create(
            from_status="",
            to_status=self.object.status,
            changed_by=self.request.user,
            reason="Asset record created",
        )
        messages.success(self.request, f"Created {self.object.code}.")
        return response


class EquipmentUpdateView(CanManageMixin, PartsFormsetMixin, UpdateView):
    model = Equipment
    form_class = EquipmentForm
    template_name = "equipment/equipment_form.html"

    def get_template_names(self):
        # Opened from the Edit button it is a dialog; opened directly, a page.
        # Either way the same form, and validation errors stay where they are.
        if wants_modal(self.request):
            return ["equipment/_edit_modal.html"]
        return super().get_template_names()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        form.save_schedules(self.object)
        remove_photos(self.object, form.cleaned_data.get("remove_photos"))
        save_photos(self.object, form.cleaned_data.get("photos"), self.request.user)
        remove_photos(self.object, form.cleaned_data.get("remove_nameplate_photos"), kind=AttachmentKind.NAMEPLATE)
        save_photos(self.object, form.cleaned_data.get("nameplate_photos"), self.request.user, kind=AttachmentKind.NAMEPLATE)
        messages.success(self.request, f"Saved changes to {self.object.code}.")
        if wants_modal(self.request):
            return modal_saved()
        return response


class EquipmentDeleteView(AdminRequiredMixin, DeleteView):
    model = Equipment
    template_name = "equipment/equipment_confirm_delete.html"
    success_url = reverse_lazy("equipment:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Show what would be lost before the button is pressed.
        context["related_counts"] = {
            "Maintenance logs": self.object.maintenance_records.count(),
            "Repair jobs": self.object.repair_records.count(),
            "Incident reports": self.object.incidents.count(),
            "Calibration records": self.object.calibration_records.count(),
            "Status history": self.object.status_history.count(),
            "Fitting records (where it was fitted)": self.object.installations.count(),
        }
        return context

    def form_valid(self, form):
        code = self.object.code
        # Logs hold the asset with PROTECT; delete_assets removes them first,
        # as this page promises.
        delete_assets(Equipment.objects.filter(pk=self.object.pk))
        messages.success(self.request, f"Deleted {code}.")
        return redirect(self.success_url)


class EquipmentBulkDeleteView(BulkDeleteView):
    """Delete the assets ticked on the list, with everything recorded against them."""

    model = Equipment
    noun = "asset"
    list_url_name = "equipment:list"

    def summary(self, items):
        ids = list(items.values_list("pk", flat=True))
        counts = {
            "Photos and files": Attachment.objects.filter(
                content_type=ContentType.objects.get_for_model(Equipment), object_id__in=ids
            ).count(),
            "Maintenance plans": MaintenancePlan.objects.filter(equipment_id__in=ids).count(),
            "Calibration plans": CalibrationPlan.objects.filter(equipment_id__in=ids).count(),
            "Fittings in equipment sets": Installation.objects.filter(component_id__in=ids).count(),
        }
        counts.update(history_counts(ids))
        return counts

    def perform(self, items):
        return delete_assets(items)


class EquipmentStatusChangeView(CanRecordMixin, FormView):
    """Move an asset to a new status, recording who and why."""

    form_class = StatusChangeForm
    template_name = "equipment/status_change.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.equipment = get_object_or_404(Equipment, pk=kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["equipment"] = self.equipment
        kwargs["request"] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["equipment"] = self.equipment
        return context

    def as_modal(self, form):
        return render_modal(
            self.request, form,
            title=f"Change status — {self.equipment.code}",
            subtitle=f"{self.equipment.name} · now “{self.equipment.get_status_display()}”",
            action=self.request.path, submit="Save status",
            note="Every change is kept with the date and who made it. In production is set by fitting the asset to a product in production.",
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
        self.equipment.change_status(
            new_status=form.cleaned_data["status"],
            user=self.request.user,
            reason=form.cleaned_data["reason"],
            note=form.cleaned_data.get("note", ""),
        )
        # Back to Available while still fitted to a running product means back
        # on the line: the rule moves it to In production, with its own entry.
        self.equipment.refresh_production_status(self.request.user)
        messages.success(
            self.request,
            f"{self.equipment.code} is now “{self.equipment.get_status_display()}”.",
        )
        if wants_modal(self.request):
            return modal_saved()
        return redirect(self.equipment.get_absolute_url())


class EquipmentImportView(CanManageMixin, FormView):
    """Bulk-load equipment from a spreadsheet."""

    form_class = EquipmentImportForm
    template_name = "equipment/equipment_import.html"
    success_url = reverse_lazy("equipment:list")

    def form_valid(self, form):
        result = import_equipment_from_xlsx(
            form.cleaned_data["file"],
            user=self.request.user,
            update_existing=form.cleaned_data["update_existing"],
        )

        if result.has_errors:
            # Nothing is written when there are errors — fix and re-upload.
            messages.error(
                self.request,
                f"Import cancelled: the file has {len(result.errors)} problem(s). "
                "No data was written.",
            )
            return self.render_to_response(
                self.get_context_data(form=form, errors=result.errors[:50])
            )

        parts = []
        if result.created:
            parts.append(f"{result.created} added")
        if result.updated:
            parts.append(f"{result.updated} updated")
        if result.skipped:
            parts.append(f"{result.skipped} skipped (ID already exists)")
        messages.success(
            self.request,
            "Import finished: " + (", ".join(parts) if parts else "no rows found") + ".",
        )
        return super().form_valid(form)


@login_required
def equipment_import_template(request):
    """Download the import template, pre-filled with existing catalog codes."""
    return _xlsx_response(build_template_workbook(), "equipment-import-template.xlsx")


@login_required
def equipment_export(request):
    """Export the list exactly as currently filtered."""
    filterset = EquipmentFilter(request.GET, queryset=Equipment.objects.with_related())
    workbook = export_equipment_to_xlsx(filterset.qs)
    filename = f"equipment-{timezone.localdate():%Y%m%d}.xlsx"
    return _xlsx_response(workbook, filename)
