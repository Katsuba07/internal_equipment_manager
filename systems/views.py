"""
The products page: customers → products → processes → sets, with a detail
panel on the right.

The panel is filled by htmx. Every panel URL also works on its own: opened
without htmx it redirects to the full page with that panel selected, so links
can be bookmarked and shared. After a change the page is reloaded with the same
panel open, so the list on the left always shows what was just saved.
"""

import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from core.mixins import AdminRequiredMixin, CanManageMixin, CanRecordMixin
from core.modals import modal_saved, render_modal, wants_modal
from core.models import Customer, Location, Plant, Product
from core.photos import remove_photos, save_photos
from equipment.models import Equipment

from .forms import (
    AddProcessForm,
    GoldenRequirementForm,
    GoldenSampleForm,
    ProductForm,
    StationForm,
    StationSlotFormSet,
)
from .doc_sync import docs_root, folder_url, last_synced, maybe_sync
from .models import DocumentSection, GoldenSample, Installation, ProductProcess, Station, SystemType, TestSet
from .services import (
    apply_set_changes,
    busy_map,
    delete_with_release,
    deletion_summary,
    evaluate_set,
    filtered_products,
    products_overview,
    set_detail,
    unusable_reason,
)

PLANT = "products_plant"


def page_url(kind: str = "", pk=None) -> str:
    url = reverse("systems:products")
    return f"{url}?{kind}={pk}" if kind else url


def is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def go(request, url: str):
    """After a change: reload the whole page (htmx) or redirect (plain form)."""
    if is_htmx(request):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


# ------------------------------------------------------------------ the page


class ProductsView(LoginRequiredMixin, View):
    """The one page. ``?set=`` / ``?product=`` / ``?process=`` open a panel."""

    def get(self, request):
        # Every product is listed, running ones first; "production" narrows it.
        production = request.GET.get("production", "")
        if production not in ("yes", "no"):
            production = ""
        if "plant" in request.GET:
            request.session[PLANT] = request.GET["plant"]
        plant = request.session.get(PLANT, "")

        panel = None
        for kind, view in (("set", set_panel), ("product", product_panel), ("process", process_panel)):
            pk = request.GET.get(kind)
            if pk and pk.isdigit():
                panel = view(request, int(pk), as_context=True)
                break
        if request.GET.get("new") == "product" and request.user.can_manage:
            panel = {"template": "systems/panels/product_form.html", "form": ProductForm()}

        maybe_sync()                    # documents follow SharePoint
        query = request.GET.get("q", "").strip()
        customer = request.GET.get("customer", "")
        matching = filtered_products(plant, query, customer)
        context = {
            "groups": products_overview(show_all=True, plant=plant, query=query, customer=customer, production=production),
            "production": production,
            "plant": plant,
            "plants": Plant.choices,
            "query": query,
            "customer": customer,
            "customers": Customer.objects.active().order_by("name"),
            "count_production": matching.filter(in_production=True).count(),
            "count_all": matching.count(),
            "documents_synced": docs_root() is not None,
            "documents_checked": last_synced(),
            "sharepoint_folder": folder_url(),
            "panel": panel,
            "selected": {k: request.GET.get(k) for k in ("set", "product", "process")},
        }
        # The panel's own variables sit next to the page's, as they do when
        # the panel is fetched on its own by htmx.
        context.update(panel or {})
        return render(request, "systems/products.html", context)


# ------------------------------------------------------------------ panels (read)


def _panel(request, context, as_context):
    if as_context:
        return context
    if not is_htmx(request):
        return None
    return render(request, context["template"], context)


def set_panel(request, pk, as_context=False):
    test_set = get_object_or_404(
        TestSet.objects.select_related("product_process__product__customer", "product_process__process", "line"),
        pk=pk,
    )
    context = {"template": "systems/panels/set.html", **set_detail(test_set)}
    return _panel(request, context, as_context)


def product_panel(request, pk, as_context=False):
    product = get_object_or_404(Product.objects.select_related("customer"), pk=pk)
    steps = []
    for step in product.processes.select_related("process").prefetch_related(
        "sets__line", "sets__station", "golden_samples"
    ):
        sets = []
        for test_set in step.sets.all():
            readiness = evaluate_set(test_set)
            own = [line for line in readiness.lines if not line.from_station]
            shared = [line for line in readiness.lines if line.from_station]
            sets.append({"set": test_set, "readiness": readiness, "own": own, "shared": shared})
        steps.append({"step": step, "sets": sets, "golden": step.golden_status()})
    context = {
        "template": "systems/panels/product.html",
        "product": product,
        "steps": steps,
        "add_form": AddProcessForm(product=product),
        "document_groups": document_groups(product),
        "product_folder_url": product_folder_url(product),
        "document_sections": DocumentSection.choices,
        "documents_synced": docs_root() is not None,
    }
    return _panel(request, context, as_context)


# Tab labels, short enough for a row of tabs.
SECTION_TABS = {
    DocumentSection.TI: "TI", DocumentSection.TEST_SPEC: "Test Spec", DocumentSection.SCHEMATIC: "Schematic",
    DocumentSection.BOM: "BOM", DocumentSection.FIRMWARE: "Firmware",
    DocumentSection.PCBA_DRAWING: "PCBA Drawing", DocumentSection.OTHER: "Other",
}


def document_groups(product):
    """The product's documents, one tab per type, in the usual reading order."""
    maybe_sync()
    docs = list(product.documents.order_by("file_name"))
    return [
        {"section": value, "tab": SECTION_TABS[value], "label": label,
         "docs": [d for d in docs if d.section == value]}
        for value, label in DocumentSection.choices
        if any(d.section == value for d in docs)
    ]


def product_folder_url(product) -> str:
    """The product's folder on SharePoint (the whole TE folder when it has none yet)."""
    folder = product.documents.exclude(folder="").values_list("folder", flat=True).first()
    return folder_url(folder.split("/")[0] if folder else "")


def process_panel(request, pk, as_context=False):
    step = get_object_or_404(
        ProductProcess.objects.select_related("product", "process"), pk=pk
    )
    set_rows = []
    for test_set in step.sets.select_related("station", "line").order_by("number"):
        readiness = evaluate_set(test_set)
        own = [line for line in readiness.lines if line.equipment and not line.from_station]
        set_rows.append({"set": test_set, "readiness": readiness, "own": own})
    context = {
        "template": "systems/panels/process.html",
        "step": step,
        "set_rows": set_rows,
        "golden": step.golden_status(),
    }
    return _panel(request, context, as_context)


class PanelView(LoginRequiredMixin, View):
    panel = None
    kind = ""

    def get(self, request, pk):
        response = type(self).panel(request, pk)
        return response or redirect(page_url(self.kind, pk))


class SetPanelView(PanelView):
    panel = staticmethod(set_panel)
    kind = "set"


class ProductPanelView(PanelView):
    panel = staticmethod(product_panel)
    kind = "product"


class ProcessPanelView(PanelView):
    panel = staticmethod(process_panel)
    kind = "process"


# ------------------------------------------------------------------ product


class ProductFormView(CanManageMixin, View):
    """New product (with its first processes) or edit an existing one."""

    template = "systems/panels/product_form.html"

    def get_object(self):
        pk = self.kwargs.get("pk")
        return get_object_or_404(Product, pk=pk) if pk else None

    def get(self, request, pk=None):
        product = self.get_object()
        if not is_htmx(request):
            return redirect(page_url("product", pk) if product else page_url("new", "product"))
        return render(request, self.template, {"form": ProductForm(instance=product), "product": product})

    def post(self, request, pk=None):
        product = self.get_object()
        form = ProductForm(request.POST, instance=product)
        if not form.is_valid():
            return render(request, self.template, {"form": form, "product": product})
        with transaction.atomic():
            product = form.save()
            for process in form.cleaned_data.get("processes") or []:
                add_process(product, process)
        messages.success(request, f"Saved {product.code}.")
        return go(request, page_url("product", product.pk))


def add_process(product, process):
    """Append a process to a product's route. Its sets come from stations ("Add model")."""
    last = product.processes.order_by("-position").values_list("position", flat=True).first()
    return ProductProcess.objects.create(product=product, process=process, position=(last or 0) + 1)


class ProductToggleView(CanManageMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.in_production = not product.in_production
        product.save(update_fields=["in_production", "updated_at"], user=request.user)
        state = "in production" if product.in_production else "not in production"
        messages.success(request, f"{product.code} is now {state}.")
        return go(request, page_url("product", pk))


class AddProcessView(CanManageMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        form = AddProcessForm(request.POST, product=product)
        if form.is_valid():
            step = add_process(product, form.cleaned_data["process"])
            messages.success(request, f"Added {step.process.code} to {product.code}.")
            return go(request, page_url("process", step.pk))
        messages.error(request, "Choose a process that this product does not have yet.")
        return go(request, page_url("product", pk))


@transaction.atomic
def save_route(steps):
    """Number a product's processes in the given order."""
    for position, step in enumerate(steps, start=1):
        if step.position != position:
            step.position = position
            step.save(update_fields=["position", "updated_at"])


class MoveProcessView(CanManageMixin, View):
    """Swap a process with its neighbour in the product's route (the arrow buttons)."""

    def post(self, request, pk, direction):
        step = get_object_or_404(ProductProcess, pk=pk)
        steps = list(step.product.processes.order_by("position", "id"))
        index = steps.index(step)
        other = index - 1 if direction == "up" else index + 1
        if 0 <= other < len(steps):
            steps[index], steps[other] = steps[other], steps[index]
            save_route(steps)
        return go(request, page_url("product", step.product_id))


class ReorderProcessesView(CanManageMixin, View):
    """
    Save a whole new route order after a drag and drop on the products page.

    Expects ``order`` = the product's process ids, comma-separated, in the new
    order. Anything else (missing, extra or foreign ids) is refused unchanged.
    """

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        steps = {step.pk: step for step in product.processes.all()}
        try:
            order = [int(x) for x in request.POST.get("order", "").split(",") if x.strip()]
        except ValueError:
            return HttpResponseBadRequest("Bad order")
        if sorted(order) != sorted(steps):
            return HttpResponseBadRequest("The order must list each process of this product once.")
        save_route([steps[i] for i in order])
        return HttpResponse(status=204)


# ------------------------------------------------------------------ golden samples


class GoldenDialogView(CanManageMixin, View):
    """
    A golden-sample form: a dialog from the process panel, a small page when
    opened directly. Saving returns to the process panel either way.
    """

    title = ""
    submit = "Save"

    def get_step(self):
        return get_object_or_404(
            ProductProcess.objects.select_related("product", "process"), pk=self.kwargs["pk"]
        )

    def get_form(self, data=None, files=None):
        raise NotImplementedError

    def saved(self, form) -> str:
        """Save and return the message to show."""
        raise NotImplementedError

    def respond(self, form):
        if wants_modal(self.request):
            return render_modal(
                self.request, form, title=f"{self.title}: {self.step}",
                action=self.request.get_full_path(), submit=self.submit,
            )
        return render(self.request, "systems/golden_form.html", {
            "form": form, "step": self.step, "title": self.title, "submit": self.submit,
            "back_url": page_url("process", self.step.pk),
        })

    def get(self, request, pk):
        self.step = self.get_step()
        return self.respond(self.get_form())

    def post(self, request, pk):
        self.step = self.get_step()
        form = self.get_form(request.POST, request.FILES)
        if not form.is_valid():
            return self.respond(form)
        messages.success(request, self.saved(form))
        if wants_modal(request):
            return modal_saved()
        return redirect(page_url("process", self.step.pk))


class GoldenSampleCreateView(GoldenDialogView):
    title = "New golden sample"
    submit = "Add"

    def get_form(self, data=None, files=None):
        return GoldenSampleForm(data, files, product_process=self.step)

    def saved(self, form):
        sample = form.save(commit=False)
        sample.product_process = self.step
        sample.save()
        save_photos(sample, form.cleaned_data.get("photos"), self.request.user)
        return f"Added golden sample {sample.code} to {self.step}."


class GoldenSampleUpdateView(GoldenDialogView):
    title = "Edit golden sample"

    def get_step(self):
        self.sample = get_object_or_404(
            GoldenSample.objects.select_related("product_process__product", "product_process__process"),
            pk=self.kwargs["pk"],
        )
        return self.sample.product_process

    def get_form(self, data=None, files=None):
        return GoldenSampleForm(data, files, instance=self.sample)

    def saved(self, form):
        sample = form.save()
        remove_photos(sample, form.cleaned_data.get("remove_photos"))
        save_photos(sample, form.cleaned_data.get("photos"), self.request.user)
        return f"Saved golden sample {sample.code}."


class GoldenRequirementView(GoldenDialogView):
    title = "Golden samples required"

    def get_form(self, data=None, files=None):
        return GoldenRequirementForm(data, instance=self.step)

    def saved(self, form):
        step = form.save()
        return f"{step} now needs {step.golden_ok_required} OK and {step.golden_ng_required} NG."


class GoldenSampleDeleteView(AdminRequiredMixin, View):
    """For a sample entered by mistake; one lost or scrapped keeps its record through Status."""

    def get_sample(self, pk):
        return get_object_or_404(GoldenSample.objects.select_related("product_process__product"), pk=pk)

    def get(self, request, pk):
        sample = self.get_sample(pk)
        return render(request, "systems/confirm_delete.html", {
            "object": sample, "kind": "Golden sample",
            "summary": {"removed": [], "released": []},
            "cancel_url": page_url("process", sample.product_process_id),
        })

    def post(self, request, pk):
        sample = self.get_sample(pk)
        label, target = str(sample), page_url("process", sample.product_process_id)
        sample.delete()
        messages.success(request, f"Deleted golden sample {label}.")
        return redirect(target)


# ------------------------------------------------------------------ one-click delete


class ConfirmDeleteView(AdminRequiredMixin, View):
    """One confirmation page, one click. Equipment is released, never deleted."""

    model = None
    kind = ""

    def get_object(self):
        return get_object_or_404(self.model, pk=self.kwargs["pk"])

    def back_url(self, obj):
        return page_url()

    def get(self, request, pk):
        obj = self.get_object()
        return render(request, "systems/confirm_delete.html", {
            "object": obj, "kind": self.kind, "summary": deletion_summary(obj),
            "cancel_url": self.cancel_url(obj),
        })

    def post(self, request, pk):
        obj = self.get_object()
        label, target = str(obj), self.back_url(obj)
        delete_with_release(obj, request.user)
        messages.success(request, f"Deleted {self.kind.lower()} {label}.")
        return redirect(target)


class ProductDeleteView(ConfirmDeleteView):
    model = Product
    kind = "Product"

    def cancel_url(self, obj):
        return page_url("product", obj.pk)


class ProcessDeleteView(ConfirmDeleteView):
    model = ProductProcess
    kind = "Process"

    def cancel_url(self, obj):
        return page_url("process", obj.pk)

    def back_url(self, obj):
        return page_url("product", obj.product_id)


class SetDeleteView(ConfirmDeleteView):
    model = TestSet
    kind = "Set"

    def cancel_url(self, obj):
        return page_url("set", obj.pk)

    def back_url(self, obj):
        return page_url("process", obj.product_process_id)


# ------------------------------------------------------------------ stations


def station_models(station) -> list[dict]:
    """
    Each product set run on a station, with its own machines and whether it is
    ready. The running one comes first: its machines are the ones mounted.
    """
    rows = []
    sets = station.test_sets.select_related("product_process__product__customer", "product_process__process", "line")
    for test_set in sets.order_by("product_process__product__code", "number"):
        readiness = evaluate_set(test_set)
        own = [line for line in readiness.lines if line.equipment and not line.from_station]
        rows.append({"set": test_set, "readiness": readiness, "own": own,
                     "running": test_set.pk == station.running_set_id})
    rows.sort(key=lambda row: not row["running"])
    return rows


class StationListView(LoginRequiredMixin, View):
    """
    The floor, station by station: what each holds and which products run on
    it. This is where test equipment is laid out; products come in through
    "Add model" on a station.
    """

    def get(self, request):
        stations = Station.objects.select_related("process", "line", "customer").prefetch_related(
            Prefetch("installations", queryset=Installation.objects.filter(removed_at__isnull=True)
                     .select_related("component__category"), to_attr="held"),
        )
        query = request.GET.get("q", "").strip()
        if query:
            # A station by its name, a machine on it, or a model run on it.
            stations = stations.filter(
                Q(code__icontains=query) | Q(notes__icontains=query)
                | Q(installations__removed_at__isnull=True, installations__component__code__icontains=query)
                | Q(installations__removed_at__isnull=True, installations__component__name__icontains=query)
                | Q(test_sets__product_process__product__code__icontains=query)
            ).distinct()
        for name in ("customer", "process", "line"):
            value = request.GET.get(name, "")
            if value.isdigit():
                stations = stations.filter(**{f"{name}_id": value})
        if request.GET.get("export"):
            return station_export(stations)
        stations = list(stations.order_by("customer__name", "process__position", "code"))
        for station in stations:
            station.models = station_models(station)
            station.ready_count = sum(row["readiness"].is_ready for row in station.models)
        return render(request, "systems/stations.html", {
            "stations": stations,
            "total": Station.objects.count(),
            "has_filters": any(request.GET.get(k) for k in ("q", "customer", "process", "line")),
            "customers": Customer.objects.filter(stations__isnull=False).distinct().order_by("name"),
            "processes": SystemType.objects.filter(stations__isnull=False).distinct().order_by("position"),
            "lines": Location.objects.filter(stations__isnull=False).distinct().order_by("name"),
        })


def machine_card(asset) -> dict:
    """What a person needs to recognise a machine at a glance, and whether it can be used."""
    calibration = min(
        (p for p in asset.calibration_plans.all() if p.is_active), key=lambda p: p.next_due_at, default=None
    )
    maintenance = min(
        (p for p in asset.maintenance_plans.all() if p.is_active), key=lambda p: p.next_due_at, default=None
    )
    return {
        "asset": asset, "photo": asset.main_photo, "problem": unusable_reason(asset),
        "calibration": calibration, "maintenance": maintenance,
    }


def station_context(station) -> dict:
    installs = (
        station.open_installations()
        .select_related("component__category", "component__location")
        .prefetch_related("component__calibration_plans", "component__maintenance_plans", "component__attachments")
    )
    models = station_models(station)
    running = next((row for row in models if row["running"]), None)
    mounted = []
    if running:
        # The running model's own machines are on the station too, beside the shared ones.
        own = (
            Equipment.objects.filter(pk__in=[line.equipment.pk for line in running["own"]])
            .select_related("category")
            .prefetch_related("calibration_plans", "maintenance_plans", "attachments")
        )
        mounted = [dict(machine_card(asset), model=running["set"].product.code) for asset in own]
    held = [machine_card(inst.component) for inst in installs]
    return {
        "station": station,
        "held": held,
        "mounted": mounted,
        "on_station_count": len(held) + len(mounted),
        "running": running,
        "models": models,
        "changeovers": station.changeovers.select_related("changed_by")[:8],
    }


def station_export(stations):
    """The equipment register for these stations: their machines and their models' machines."""
    from django.utils import timezone

    from equipment.register import build_register
    from equipment.xlsx_images import save_workbook

    ids = list(stations.values_list("pk", flat=True))
    assets = Equipment.objects.filter(
        Q(installations__station_id__in=ids) | Q(installations__test_set__station_id__in=ids),
        installations__removed_at__isnull=True,
    ).distinct()
    workbook = build_register(assets, Station.objects.filter(pk__in=ids), filters_text=f"{len(ids)} station(s)")
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="stations-register-{timezone.localdate():%Y%m%d}.xlsx"'
    save_workbook(workbook, response)       # with the in-cell photos
    return response


class StationDetailView(LoginRequiredMixin, View):
    """One station: its shared machines, and every model run on it with its own fixture."""

    def get(self, request, pk):
        station = get_object_or_404(Station.objects.select_related("process", "line"), pk=pk)
        return render(request, "systems/station_detail.html", station_context(station))


class StationPreviewView(LoginRequiredMixin, View):
    """The quick-look drawer on the stations list; opened on its own, it goes to the full page."""

    def get(self, request, pk):
        if request.headers.get("HX-Request") != "true":
            return redirect("systems:station_detail", pk=pk)
        station = get_object_or_404(Station.objects.select_related("process", "line"), pk=pk)
        return render(request, "systems/_station_preview.html", station_context(station))


class StationModelDialogMixin:
    """
    The dialog for one model's own machines on a station: one search box per
    slot (its fixture, a load box...). Adding a model picks the product in the
    same dialog, so its fixture is chosen right away.
    """

    template = "systems/_station_model_modal.html"
    page_template = "systems/station_model_edit.html"

    def slot_rows(self, station, test_set=None, posted=None):
        own = {}
        if test_set is not None:
            own = {inst.slot_id: inst.component for inst in test_set.open_installations().select_related("component")}
        wanted = [str(v) for v in (posted or {}).values() if str(v).isdigit()]
        found = {str(a.pk): a for a in Equipment.objects.filter(pk__in=wanted)}
        search = reverse("equipment:search")
        rows = []
        for slot in station.slots.select_related("category"):
            chosen = found.get(str(posted.get(slot.pk) or "")) if posted is not None else own.get(slot.pk)
            scope = f"set={test_set.pk}&" if test_set else f"models_of={station.pk}&"
            rows.append({
                "slot": slot, "name": f"slot_{slot.pk}", "input_id": f"id_slot_{slot.pk}", "chosen": chosen,
                "source": f"{search}?{scope}category={slot.category_id}",
                "empty_text": f"No {slot.category.name} registered yet.",
            })
        return rows

    def posted_slots(self, request, station):
        slot_ids = set(station.slots.values_list("id", flat=True))
        return {
            int(key[5:]): value for key, value in request.POST.items()
            if key.startswith("slot_") and key[5:].isdigit() and int(key[5:]) in slot_ids
        }

    def show(self, request, station, test_set=None, posted=None, error="", products=None, product=None):
        shared = station.open_installations().select_related("component__category")
        context = {
            "station": station, "test_set": test_set, "rows": self.slot_rows(station, test_set, posted),
            "shared": [inst.component for inst in shared], "error": error,
            "products": products, "chosen_product": product,
        }
        return render(request, self.template if wants_modal(request) or test_set is None else self.page_template, context)

    def done(self, request, station, message):
        messages.success(request, message)
        if wants_modal(request):
            return modal_saved()
        return redirect("systems:station_detail", pk=station.pk)


def addable_products(station):
    """Products that may be added to a station: not on it yet, and its customer's when it has one."""
    on_station = station.test_sets.values_list("product_process__product_id", flat=True)
    products = Product.objects.exclude(pk__in=on_station).order_by("code")
    if station.customer_id:
        products = products.filter(customer_id=station.customer_id)    # a customer's station runs its models
    return products


def put_on_station(product, station):
    """
    The product's set at the station's process, now on the station: the first
    set not on a station yet, or a new one (the process is added to the
    product's route when missing).
    """
    step = product.processes.filter(process=station.process).first() or add_process(product, station.process)
    test_set = step.sets.filter(station__isnull=True).order_by("number").first()
    if test_set is None:
        test_set = TestSet.objects.create(product_process=step, number=step.next_set_number())
    test_set.station = station
    if station.line_id and not test_set.line_id:
        test_set.line_id = station.line_id
    test_set.save()
    return test_set


class StationAddModelView(CanManageMixin, StationModelDialogMixin, View):
    """
    Run a product on a station, with its own machines chosen in the same
    dialog. The product's set at the station's process is used (the first one
    not on a station yet), or one is made, adding the process to the product's
    route when it is missing. The first model on a station starts as the
    running one.
    """

    def addable(self, station):
        return addable_products(station)

    def get(self, request, pk):
        station = get_object_or_404(Station.objects.select_related("process"), pk=pk)
        return self.show(request, station, products=self.addable(station))

    @transaction.atomic
    def post(self, request, pk):
        station = get_object_or_404(Station.objects.select_related("process", "line"), pk=pk)
        products = self.addable(station)
        product = products.filter(pk=request.POST.get("product") or 0).first()
        posted = self.posted_slots(request, station)
        if product is None:
            return self.show(request, station, posted=posted, products=products, error="Choose the model to add.")
        test_set = put_on_station(product, station)
        picks = {sid: (Equipment.objects.filter(pk=v).first() if v else None) for sid, v in posted.items()}
        try:
            with transaction.atomic():
                apply_set_changes(test_set, picks, request.user)
        except (ValidationError, IntegrityError) as error:
            transaction.set_rollback(True)
            message = error.messages[0] if isinstance(error, ValidationError) else str(error)
            return self.show(request, station, posted=posted, products=products, product=product, error=message)
        if station.running_set_id is None:
            station.changeover(test_set, request.user, note="First model on the station")
        return self.done(request, station, f"{product.code} now runs on {station}.")


class StationRemoveModelView(CanManageMixin, View):
    """Stop running a product set on a station; the set keeps its own machines."""

    def post(self, request, pk, set_pk):
        test_set = get_object_or_404(TestSet, pk=set_pk, station_id=pk)
        station = test_set.station
        if station.running_set_id == test_set.pk:
            station.changeover(None, request.user, note=f"{test_set} taken off the station")
        test_set.station = None
        test_set.save(update_fields=["station", "updated_at"])
        messages.success(request, f"{test_set} no longer runs on this station.")
        return redirect("systems:station_detail", pk=pk)


class StationFormView(CanManageMixin, View):
    """
    New station, or edit one, all in one form: its name, process and line, the
    machines it shares, what each model must bring itself (its slots), and the
    models run on it with their own machines and which one runs now.
    """

    BLANK_ROWS = 1          # one empty search box; "Add machine" adds more
    NEW_MODEL = re.compile(r"^new_([A-Za-z0-9]+)_product$")

    def get_station(self):
        pk = self.kwargs.get("pk")
        return get_object_or_404(Station, pk=pk) if pk else Station()

    # --- the models section ---

    def model_rows(self, station, posted=None):
        """(rows for its models, rows for models being added, pickers for a new row)."""
        if not station.pk:
            return [], [], []
        slots = list(station.slots.select_related("category"))
        search = reverse("equipment:search")
        wanted = [v for k, v in (posted or {}).items() if "_slot_" in k and str(v).isdigit()]
        found = {str(a.pk): a for a in Equipment.objects.filter(pk__in=wanted)}

        def pickers(prefix, scope, own=None):
            out = []
            for slot in slots:
                name = f"{prefix}_slot_{slot.pk}"
                chosen = found.get(str(posted.get(name) or "")) if posted is not None else (own or {}).get(slot.pk)
                out.append({"slot": slot, "name": name, "input_id": f"id_{name}", "chosen": chosen,
                            "source": f"{search}?{scope}&category={slot.category_id}",
                            "empty_text": f"No {slot.category.name} registered yet."})
            return out

        running_now = (posted or {}).get("running") if posted is not None else str(station.running_set_id or "")
        rows = []
        for test_set in station.test_sets.select_related("product_process__product").order_by(
                "product_process__product__code", "number"):
            own = {i.slot_id: i.component for i in test_set.open_installations().select_related("component")}
            prefix = f"set_{test_set.pk}"
            rows.append({
                "set": test_set, "prefix": prefix, "pickers": pickers(prefix, f"set={test_set.pk}", own),
                "running": running_now == str(test_set.pk),
                "remove": bool(posted and posted.get(f"{prefix}_remove")),
            })
        added = []
        for key in (posted or {}):
            match = self.NEW_MODEL.match(key)
            if match:
                prefix = f"new_{match.group(1)}"
                added.append({"prefix": prefix, "product": str(posted.get(key) or ""),
                              "pickers": pickers(prefix, f"models_of={station.pk}"),
                              "running": running_now == prefix})
        template = pickers("new___n__", f"models_of={station.pk}")
        return rows, added, template

    def render_form(self, request, station, form, slots, assets, error="", posted=None, notice=""):
        source = f"{reverse('equipment:search')}?station={station.pk or 'new'}"
        rows = [{"chosen": asset, "input_id": f"id_asset_{index}"} for index, asset in enumerate(assets)]
        rows += [{"chosen": None, "input_id": f"id_asset_{len(assets) + n}"} for n in range(self.BLANK_ROWS)]
        model_rows, added_rows, new_pickers = self.model_rows(station, posted)
        # Opened from a button it is a dialog, like the asset form; opened directly, a page.
        template = "systems/_station_modal.html" if wants_modal(request) else "systems/station_form.html"
        return render(request, template, {
            "station": station, "form": form, "slots": slots, "rows": rows, "source": source, "error": error,
            "model_rows": model_rows, "added_rows": added_rows, "new_pickers": new_pickers,
            "addable": addable_products(station) if station.pk else [], "notice": notice,
        })

    def save_models(self, request, station):
        """Apply the models section: removals, each model's own machines, new models, the running one."""
        post = request.POST
        slot_ids = set(station.slots.values_list("id", flat=True))

        def picks_for(prefix):
            picks = {}
            for slot_id in slot_ids:
                key = f"{prefix}_slot_{slot_id}"
                if key in post:
                    value = post.get(key)
                    picks[slot_id] = Equipment.objects.filter(pk=value).first() if value.isdigit() else None
            return picks

        changes, by_prefix = [], {}
        for test_set in list(station.test_sets.all()):
            prefix = f"set_{test_set.pk}"
            if post.get(f"{prefix}_remove"):
                if station.running_set_id == test_set.pk:
                    station.changeover(None, request.user, note=f"{test_set} taken off the station")
                test_set.station = None
                test_set.save(update_fields=["station", "updated_at"])
                changes.append(f"{test_set.product.code} taken off")
                continue
            by_prefix[str(test_set.pk)] = test_set
            changes += apply_set_changes(test_set, picks_for(prefix), request.user)
        for key in post:
            match = self.NEW_MODEL.match(key)
            if not match or not post.get(key):
                continue
            product = addable_products(station).filter(pk=post.get(key)).first()
            if product is None:
                raise ValidationError("A model chosen to add is not available for this station.")
            prefix = f"new_{match.group(1)}"
            test_set = put_on_station(product, station)
            by_prefix[prefix] = test_set
            changes += [f"{product.code} added"] + apply_set_changes(test_set, picks_for(prefix), request.user)
        wanted = by_prefix.get(post.get("running", ""))
        if wanted is None and station.running_set_id is None and by_prefix:
            wanted = next(iter(by_prefix.values()))          # a station with models runs one of them
        if wanted is not None and wanted.pk != station.running_set_id:
            station.refresh_from_db(fields=["running_set", "running_since"])
            station.changeover(wanted, request.user)
            changes.append(f"now running {wanted.product.code}")
        return changes

    def get(self, request, pk=None):
        station = self.get_station()
        held = [inst.component for inst in station.open_installations().select_related("component")] if station.pk else []
        slots = StationSlotFormSet(instance=station, prefix="slots")
        return self.render_form(request, station, StationForm(instance=station), slots, held)

    def post(self, request, pk=None):
        station = self.get_station()
        is_new = station.pk is None
        form = StationForm(request.POST, instance=station)
        slots = StationSlotFormSet(request.POST, instance=station, prefix="slots")
        ids = [value for value in request.POST.getlist("asset") if value.isdigit()]
        found = {str(asset.pk): asset for asset in Equipment.objects.filter(pk__in=ids)}
        assets = list({value: found[value] for value in ids if value in found}.values())   # keep order, drop repeats
        posted = request.POST.dict()
        if not (form.is_valid() and slots.is_valid()):
            return self.render_form(request, station, form, slots, assets, posted=posted)
        try:
            with transaction.atomic():
                station = form.save()
                slots.instance = station
                for slot_form in slots.deleted_forms:
                    # A slot on its way out frees the machines sitting in it.
                    if slot_form.instance.pk:
                        for fitting in slot_form.instance.installations.filter(removed_at__isnull=True):
                            fitting.release(request.user, reason=f"Slot {slot_form.instance.name} removed from {station}")
                slots.save()
                changes = station.set_equipment(assets, request.user)
                changes += self.save_models(request, station)
        except (ValidationError, IntegrityError) as error:
            message = error.messages[0] if isinstance(error, ValidationError) else str(error)
            station = self.get_station()
            return self.render_form(request, station, form, slots, assets, message, posted=posted)
        if is_new and wants_modal(request):
            # A new station's slots exist now: the same dialog goes straight on to
            # its models and their own machines.
            station.refresh_from_db()
            held = [inst.component for inst in station.open_installations().select_related("component")]
            return self.render_form(
                request, station, StationForm(instance=station), StationSlotFormSet(instance=station, prefix="slots"),
                held, notice=f"Station {station} created. Now add its models and their own machines, then save.",
            )
        messages.success(request, f"Station {station} saved" + (f": {', '.join(changes)}." if changes else "."))
        if wants_modal(request):
            return modal_saved()
        return redirect("systems:station_detail", pk=station.pk)


class StationDeleteView(AdminRequiredMixin, View):
    """Delete a station: its machines are released, its sets keep their own."""

    def get(self, request, pk):
        station = get_object_or_404(Station, pk=pk)
        return render(request, "systems/confirm_delete.html", {
            "object": station, "kind": "Station",
            "summary": {"removed": [("Sets that run on it (they keep their own machines)", station.test_sets.count())],
                        "released": list(station.open_installations().select_related("component"))},
            "cancel_url": reverse("systems:station_edit", args=[pk]),
        })

    def post(self, request, pk):
        station = get_object_or_404(Station, pk=pk)
        label = str(station)
        station.delete(user=request.user)
        messages.success(request, f"Deleted station {label}.")
        return redirect("systems:stations")


class StationModelEditView(CanRecordMixin, StationModelDialogMixin, View):
    """The machines one model brings to a station (its fixture...), in a dialog."""

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.station = get_object_or_404(Station.objects.select_related("process"), pk=kwargs["pk"])
        self.test_set = get_object_or_404(
            TestSet.objects.select_related("product_process__product", "product_process__process"),
            pk=kwargs["set_pk"], station=self.station,
        )

    def get(self, request, pk, set_pk):
        return self.show(request, self.station, self.test_set)

    def post(self, request, pk, set_pk):
        posted = self.posted_slots(request, self.station)
        picks = {sid: (Equipment.objects.filter(pk=v).first() if v else None) for sid, v in posted.items()}
        try:
            changes = apply_set_changes(self.test_set, picks, request.user)
        except (ValidationError, IntegrityError) as error:
            message = error.messages[0] if isinstance(error, ValidationError) else str(error)
            return self.show(request, self.station, self.test_set, posted, message)
        return self.done(request, self.station, f"{self.test_set} saved" + (f": {', '.join(changes)}." if changes else "."))


class StationChangeoverView(CanRecordMixin, View):
    """Set up another model on the station: its own machines become the mounted ones."""

    def post(self, request, pk, set_pk):
        station = get_object_or_404(Station, pk=pk)
        test_set = get_object_or_404(TestSet.objects.select_related("product_process__product"), pk=set_pk, station=station)
        if station.changeover(test_set, request.user, note=request.POST.get("note", "")[:255]):
            mounted = ", ".join(inst.component.ident for inst in test_set.open_installations().select_related("component"))
            messages.success(request, f"{station} now runs {test_set.product.code}"
                                      + (f": mount {mounted}." if mounted else "."))
        return redirect("systems:station_detail", pk=pk)


