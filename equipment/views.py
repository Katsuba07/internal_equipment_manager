"""Equipment screens."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin

from calibration.models import CalibrationPlan
from core.bulk import BulkDeleteView
from core.models import Attachment, AttachmentKind, Category
from core.photos import remove_photos, save_photos
from maintenance.models import MaintenancePlan
from systems.models import Installation
from core.mixins import AdminRequiredMixin, CanManageMixin, CanRecordMixin
from core.modals import modal_saved, wants_modal
from inventory.forms import EquipmentPartFormSet
from systems.services import equipment_usage

from .deletion import delete_assets, history_counts
from .filters import EquipmentFilter
from .forms import EquipmentForm
from .labels import LabelPrintError, LabelSize, build_zpl, send_to_printer
from .models import STATUS_BADGE_CLASS, Equipment, EquipmentStatus
from .register import build_register
from .xlsx_images import save_workbook
from .tables import EquipmentTable, labelled_toggle


def _xlsx_response(workbook, filename: str) -> HttpResponse:
    """Wrap a workbook as a download."""
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    save_workbook(workbook, response)       # with any in-cell photos
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
        station_id = request.GET.get("station", "")
        models_of = request.GET.get("models_of", "")      # a model being added to that station
        listed_ids = []
        if part_id:
            listed_ids = list(
                EquipmentPart.objects.filter(item_id=part_id).values_list("equipment_id", flat=True)
            )
        # Filling a set: machines fitted in any other set are shown but marked.
        busy = {}
        if set_id.isdigit():
            busy = busy_map(exclude_set=TestSet.objects.filter(pk=set_id).first())
        elif models_of.isdigit():
            from systems.models import Station

            busy = busy_map(models_of=Station.objects.filter(pk=models_of).first())
        elif station_id.isdigit() or station_id == "new":
            from systems.models import Station

            busy = busy_map(exclude_station=Station.objects.filter(pk=station_id if station_id.isdigit() else 0).first())

        assets = Equipment.objects.active().with_related()
        if category.isdigit():
            assets = assets.filter(category_id=category)
        if query:
            assets = assets.filter(
                Q(code__icontains=query)
                | Q(equipment_no__icontains=query)
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
                "code": asset.ident,
                "name": asset.name,
                "ids": " · ".join(x for x in [asset.equipment_no, asset.asset_no, asset.serial_number] if x),
                "where": asset.plant_display if asset.plant else "",
                "status": asset.get_status_display(),
                "on_list": asset.pk in listed_ids,
                "busy": busy.get(asset.pk, ""),
            }
            for asset in assets[: self.LIMIT]
        ]
        return JsonResponse({"results": results, "query": query})


class EquipmentNextNoView(LoginRequiredMixin, View):
    """The last and next Equipment No of a type, shown beside the field while an asset is entered."""

    def get(self, request):
        category = Category.objects.filter(pk=request.GET.get("category") or 0).first()
        if category is None:
            return JsonResponse({"next": "", "last": ""})
        return JsonResponse(Equipment.equipment_no_counter(category))


class EquipmentListView(LoginRequiredMixin, SingleTableMixin, FilterView):
    """Equipment list with search, filters and sorting — every asset on one page."""

    model = Equipment
    table_class = EquipmentTable
    filterset_class = EquipmentFilter
    template_name = "equipment/equipment_list.html"
    table_pagination = False

    def get_queryset(self):
        return Equipment.objects.with_related().with_product_codes().prefetch_related("calibration_plans")

    # Table column -> the filter shown in that column's header.
    HEADER_FILTERS = {
        "serial_number": "serial", "category": "category", "plant": "plant",
        "status": "status", "labelled": "labelled",
        "is_measuring_device": "is_measuring_device",
    }

    def get_table_kwargs(self):
        # Everyone ticks assets to print their labels; only administrators
        # also get "Delete selected" (see the list page).
        return {}

    def get_table(self, **kwargs):
        table = super().get_table(**kwargs)
        form = self.filterset.form
        for column, name in self.HEADER_FILTERS.items():
            field = form[name]
            # The header is outside the <form>; form="..." ties the control to it.
            field.field.widget.attrs.update({"form": "list-filter", "class": "th-filter", "aria-label": f"Filter by {field.label}"})
            table.columns[column].header_filter = field
        return table

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
            (label, counts.get(value, 0), STATUS_BADGE_CLASS[value].removeprefix("badge-"))
            for value, label in EquipmentStatus.choices
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
        context["maintenance_records"] = self.object.maintenance_records.select_related(
            "plan", "performed_by"
        )[:20]
        # Where this asset is used and where it physically sits — the cross-use
        # answer from the component's own side.
        context["usage"] = equipment_usage(self.object)
        # Spare parts that were issued to this asset — the other half of the
        # traceability the parts list gives.
        context["part_issues"] = self.object.part_issues.filter(
            transaction_type="OUT"
        ).select_related("item", "performed_by")[:20]
        return context


def _label_context(assets, repeat: bool) -> dict:
    """What the label page needs: each asset with its QR code drawn, and the label stock."""
    import qrcode
    import qrcode.image.svg

    items = []
    for asset in assets:
        image = qrcode.make(asset.label_qr_url, image_factory=qrcode.image.svg.SvgPathImage, border=0)
        items.append({"equipment": asset, "qr_svg": image.to_string(encoding="unicode")})
    return {
        "items": items,
        "repeat": repeat,
        "company": settings.EMA_LABEL_COMPANY,
        "label_size": {**settings.EMA_LABEL_SIZE, "dx": 0, "dy": 0, "font": 0},
        "printer": settings.EMA_LABEL_PRINTER,
    }


MAX_LABELS = 500


def _assets_from_ids(request):
    ids = [value for value in request.GET.get("ids", "").split(",") if value.isdigit()][:MAX_LABELS]
    found = {asset.pk: asset for asset in Equipment.objects.filter(pk__in=ids)}
    return [found[int(pk)] for pk in dict.fromkeys(ids) if int(pk) in found]      # in the order ticked


@method_decorator(xframe_options_sameorigin, name="dispatch")
class EquipmentLabelView(LoginRequiredMixin, View):
    """
    The asset's label, sized for the label printer (the size is adjustable on
    the page). Shown in a pop-up over the asset page, so it may be framed by
    this site (and only this site).
    """

    def get(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        context = _label_context([equipment], repeat=True)
        context.update({"title": f"Label {equipment.ident}", "equipment": equipment,
                        "zpl_url": reverse("equipment:label_zpl", args=[pk])})
        return render(request, "equipment/label.html", context)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class EquipmentLabelsView(LoginRequiredMixin, View):
    """The labels of the assets ticked on the list, one after another across the roll."""

    def get(self, request):
        assets = _assets_from_ids(request)
        if not assets:
            return HttpResponse("Tick the assets to print first.", status=400)
        context = _label_context(assets, repeat=False)
        context.update({
            "title": f"{len(assets)} labels",
            "zpl_url": f"{reverse('equipment:labels_zpl')}?ids={','.join(str(a.pk) for a in assets)}",
        })
        return render(request, "equipment/label.html", context)


class EquipmentLabelZplView(LoginRequiredMixin, View):
    """The asset's label in ZPL, for the page to pass to a printer on the user's own computer."""

    def get(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        return HttpResponse(
            build_zpl(equipment, LabelSize.from_values(request.GET)), content_type="text/plain; charset=utf-8"
        )


class EquipmentLabelsZplView(LoginRequiredMixin, View):
    """Several assets' labels in ZPL, in order, filling the roll across."""

    def get(self, request):
        assets = _assets_from_ids(request)
        if not assets:
            return HttpResponse("No assets.", status=400)
        return HttpResponse(
            build_zpl(assets, LabelSize.from_values(request.GET)), content_type="text/plain; charset=utf-8"
        )


class EquipmentLabelPrintView(CanRecordMixin, View):
    """Send the asset's label straight to the Zebra printer, as ZPL."""

    def post(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        zpl = build_zpl(equipment, LabelSize.from_values(request.POST))
        try:
            send_to_printer(zpl, title=f"EMA label {equipment.ident}")
        except LabelPrintError as error:
            return JsonResponse({"ok": False, "message": str(error)}, status=502)
        marked = mark_labelled([equipment])
        return JsonResponse({"ok": True, "ids": marked,
                             "message": f"Sent to {settings.EMA_LABEL_PRINTER} — marked as labelled."})


def mark_labelled(assets) -> list[int]:
    """Tick "labelled" on assets whose label has just printed; returns their ids."""
    for asset in assets:
        if not asset.labelled:
            asset.labelled = True
            asset._change_reason = "Label printed"
            asset.save(update_fields=["labelled", "updated_at"])
    return [asset.pk for asset in assets]


class EquipmentMarkLabelledView(CanRecordMixin, View):
    """
    The label page reports a print the printer accepted (through Zebra Browser
    Print, on the user's computer): tick those assets as labelled.
    """

    def post(self, request):
        ids = [value for value in request.POST.get("ids", "").split(",") if value.isdigit()][:MAX_LABELS]
        marked = mark_labelled(list(Equipment.objects.filter(pk__in=ids)))
        return JsonResponse({"ok": True, "ids": marked})


class EquipmentLabelledView(CanRecordMixin, View):
    """Tick or untick "label is on the asset" from the list; answers with the tick box."""

    def post(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        labelled = request.POST.get("labelled") == "1"
        if equipment.labelled != labelled:
            equipment.labelled = labelled
            equipment._change_reason = "Label ticked" if labelled else "Label unticked"
            equipment.save(update_fields=["labelled", "updated_at"])
        return HttpResponse(labelled_toggle(equipment, can_change=True))


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
        # A model's own machine may serve several models of one station: list them all.
        fittings = asset.open_fittings_now
        context["fittings"] = [f for f in fittings if f.test_set_id]
        context["fit_station"] = next((f.test_set.station for f in context["fittings"] if f.test_set.station_id), None)
        context["fit_mounted"] = any(f.test_set.is_running for f in context["fittings"])
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
        # Status is picked on the form; a change still gets its history row.
        was = Equipment.objects.filter(pk=form.instance.pk).values_list("status", flat=True).first()
        if was != form.instance.status:
            form.instance.status_changed_at = timezone.now()
        response = super().form_valid(form)
        if was != self.object.status:
            self.object.status_history.create(
                from_status=was or "", to_status=self.object.status,
                changed_by=self.request.user, reason="Changed on the asset form",
            )
        form.save_schedules(self.object)
        remove_photos(self.object, form.cleaned_data.get("remove_photos"))
        save_photos(self.object, form.cleaned_data.get("photos"), self.request.user)
        remove_photos(self.object, form.cleaned_data.get("remove_nameplate_photos"), kind=AttachmentKind.NAMEPLATE)
        save_photos(self.object, form.cleaned_data.get("nameplate_photos"), self.request.user, kind=AttachmentKind.NAMEPLATE)
        messages.success(self.request, f"Saved changes to {self.object.ident}.")
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


@login_required
def equipment_export(request):
    """Export the list exactly as currently filtered."""
    filterset = EquipmentFilter(request.GET, queryset=Equipment.objects.with_related())
    form = filterset.form
    used = []
    if form.is_valid():
        for name, value in form.cleaned_data.items():
            if value not in (None, "", [], False) and name in form.fields:
                choice = dict(form.fields[name].choices).get(value, value) if hasattr(form.fields[name], "choices") else value
                used.append(f"{form.fields[name].label}: {choice}")
    workbook = build_register(filterset.qs, filters_text="filtered by " + ", ".join(map(str, used)) if used else "")
    filename = f"equipment-register-{timezone.localdate():%Y%m%d}.xlsx"
    return _xlsx_response(workbook, filename)
