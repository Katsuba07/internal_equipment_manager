"""
The products page: customers → products → processes → sets, with a detail
panel on the right.

The panel is filled by htmx. Every panel URL also works on its own: opened
without htmx it redirects to the full page with that panel selected, so links
can be bookmarked and shared. After a change the page is reloaded with the same
panel open, so the list on the left always shows what was just saved.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from core.mixins import AdminRequiredMixin, CanManageMixin, CanRecordMixin
from core.modals import modal_saved, render_modal, wants_modal
from core.models import Customer, Plant, Product
from core.photos import remove_photos, save_photos
from equipment.models import Equipment

from .forms import (
    AddProcessForm,
    GoldenRequirementForm,
    GoldenSampleForm,
    ProductForm,
    RoleFormSet,
    RoleSetupFormSet,
    SetLineForm,
)
from .doc_sync import docs_root, folder_url, last_synced, maybe_sync
from .models import DocumentSection, GoldenSample, ProductProcess, TestSet
from .services import (
    apply_set_changes,
    busy_map,
    delete_with_release,
    deletion_summary,
    evaluate_set,
    filtered_products,
    products_overview,
    set_detail,
)

SHOW_ALL = "products_show_all"
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
        if "show" in request.GET:
            request.session[SHOW_ALL] = request.GET["show"] == "all"
        show_all = request.session.get(SHOW_ALL, False)
        if "plant" in request.GET:
            request.session[PLANT] = request.GET["plant"]
        plant = request.session.get(PLANT, "")

        panel = None
        for kind, view in (("set", set_panel), ("product", product_panel), ("process", process_panel)):
            pk = request.GET.get(kind)
            if pk and pk.isdigit():
                panel = view(request, int(pk), as_context=True)
                break
        edit_pk = request.GET.get("set_edit", "")
        if edit_pk.isdigit() and request.user.can_record:
            editor = SetEditView()
            editor.setup(request, pk=int(edit_pk))
            panel = editor.context(SetLineForm(instance=editor.test_set))
        if request.GET.get("new") == "product" and request.user.can_manage:
            panel = {"template": "systems/panels/product_form.html", "form": ProductForm()}

        maybe_sync()                    # documents follow SharePoint
        query = request.GET.get("q", "").strip()
        customer = request.GET.get("customer", "")
        matching = filtered_products(plant, query, customer)
        context = {
            "groups": products_overview(show_all=show_all, plant=plant, query=query, customer=customer),
            "show_all": show_all,
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
        "sets__line", "roles", "golden_samples"
    ):
        steps.append({
            "step": step,
            "sets": [{"set": s, "readiness": evaluate_set(s)} for s in step.sets.all()],
            "golden": step.golden_status(),
        })
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


def process_panel(request, pk, as_context=False, formset=None, line_form=None, error="", tab=None):
    step = get_object_or_404(
        ProductProcess.objects.select_related("product", "process"), pk=pk
    )
    sets = list(step.sets.select_related("line"))
    wanted = str(tab or request.GET.get("tab", ""))
    active = next((s for s in sets if str(s.pk) == wanted), sets[0] if sets else None)
    context = {
        "template": "systems/panels/process.html",
        "step": step,
        "sets": sets,
        "active_set": active,
        "formset": formset or RoleSetupFormSet(
            instance=step, prefix="roles", test_set=active, can_manage=request.user.can_manage,
        ),
        "line_form": line_form or (SetLineForm(instance=active, prefix="set") if active else None),
        "error": error,
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


# ------------------------------------------------------------------ set: fit / remove


class SetEditView(CanRecordMixin, View):
    """
    Choose the asset for every role of a set, and its line, in one save.

    Each role is a search box (Equipment ID, Asset No. or S/N) offering only
    that role's kind of equipment, free ones first — a technician types what is
    printed on the machine instead of scrolling a list of fifty.
    """

    template = "systems/panels/set_edit.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.test_set = get_object_or_404(
            TestSet.objects.select_related("product_process__product", "product_process__process", "line"),
            pk=kwargs["pk"],
        )

    def rows(self, picks=None):
        """One row per role, with the asset chosen for it (if any)."""
        current = {i.role_id: i.component for i in self.test_set.open_installations().select_related("component")}
        chosen_ids = {rid: v for rid, v in (picks or {}).items()}
        wanted = [v for v in chosen_ids.values() if v]
        by_id = {str(a.pk): a for a in Equipment.objects.filter(pk__in=[w for w in wanted if str(w).isdigit()])}
        search = reverse("equipment:search")
        rows = []
        for role in self.test_set.product_process.roles.select_related("category"):
            if picks is not None:
                value = chosen_ids.get(role.id) or ""
                chosen = by_id.get(str(value))
            else:
                chosen = current.get(role.id)
            rows.append({
                "role": role, "chosen": chosen,
                "name": f"role_{role.id}", "input_id": f"id_role_{role.id}",
                # Only this role's kind of equipment; busy ones marked against this set.
                "source": f"{search}?set={self.test_set.pk}&category={role.category_id or ''}",
                "empty_text": (f"No {role.category.name} registered yet." if role.category_id else ""),
            })
        return rows

    def context(self, line_form, picks=None, error=""):
        return {
            "template": self.template,
            "test_set": self.test_set, "line_form": line_form,
            "rows": self.rows(picks), "error": error,
            "is_new": not self.test_set.open_installations().exists() and picks is None,
        }

    def render_form(self, request, line_form, picks=None, error=""):
        return render(request, self.template, self.context(line_form, picks, error))

    def get(self, request, pk):
        if not is_htmx(request):
            return redirect(page_url("set", pk))
        return self.render_form(request, SetLineForm(instance=self.test_set))

    def post(self, request, pk):
        line_form = SetLineForm(request.POST, instance=self.test_set)
        role_ids = set(self.test_set.product_process.roles.values_list("id", flat=True))
        raw = {
            int(key[5:]): value for key, value in request.POST.items()
            if key.startswith("role_") and key[5:].isdigit() and int(key[5:]) in role_ids
        }
        picks = {rid: (Equipment.objects.filter(pk=v).first() if v else None) for rid, v in raw.items()}
        if not line_form.is_valid():
            return self.render_form(request, line_form, raw)
        try:
            with transaction.atomic():
                line_form.save()
                changes = apply_set_changes(self.test_set, picks, request.user)
        except (ValidationError, IntegrityError) as error:
            message = error.messages[0] if isinstance(error, ValidationError) else str(error)
            return self.render_form(request, line_form, raw, message)
        messages.success(
            request, f"{self.test_set} saved" + (f": {', '.join(changes)}." if changes else ".")
        )
        return go(request, page_url("set", pk))


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
    """Append a process to a product's route with its template roles and set #1."""
    last = product.processes.order_by("-position").values_list("position", flat=True).first()
    step = ProductProcess.objects.create(product=product, process=process, position=(last or 0) + 1)
    step.copy_template()
    TestSet.objects.create(product_process=step, number=1)
    return step


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


# ------------------------------------------------------------------ process: roles, sets


class ProcessRolesView(CanManageMixin, View):
    def post(self, request, pk):
        step = get_object_or_404(ProductProcess, pk=pk)
        formset = RoleFormSet(request.POST, instance=step, prefix="roles")
        if not formset.is_valid():
            context = process_panel(request, pk, as_context=True, formset=formset)
            return render(request, context["template"], context)
        with transaction.atomic():
            formset.save()
        messages.success(request, f"Saved the roles of {step}.")
        return go(request, page_url("process", pk))


class ProcessSetupView(CanRecordMixin, View):
    """
    Save the process frame in one go: the roles (managers) and the asset in
    each role of the chosen set (technicians too).
    """

    def post(self, request, pk):
        step = get_object_or_404(ProductProcess, pk=pk)
        test_set = step.sets.filter(pk=request.GET.get("tab") or 0).first() or step.sets.first()
        can_manage = request.user.can_manage
        formset = RoleSetupFormSet(
            request.POST, instance=step, prefix="roles", test_set=test_set, can_manage=can_manage,
        )
        line_form = SetLineForm(request.POST, instance=test_set, prefix="set") if test_set else None
        tab = test_set.pk if test_set else None

        def again(error=""):
            context = process_panel(request, pk, as_context=True, formset=formset,
                                    line_form=line_form, error=error, tab=tab)
            return render(request, context["template"], context)

        if not formset.is_valid() or (line_form and not line_form.is_valid()):
            return again()
        try:
            with transaction.atomic():
                if can_manage:
                    # A role on its way out frees whatever sits in it first.
                    for form in formset.deleted_forms:
                        if form.instance.pk:
                            for fitting in form.instance.installations.filter(removed_at__isnull=True):
                                fitting.release(request.user, reason=f"Role {form.instance.name} removed")
                    formset.save()
                changes = []
                if test_set is not None:
                    line_form.save()
                    changes = apply_set_changes(test_set, formset.picks(), request.user)
        except (ValidationError, IntegrityError) as error:
            return again(error.messages[0] if isinstance(error, ValidationError) else str(error))
        where = f"{test_set}" if test_set else f"{step}"
        messages.success(request, f"{where} saved" + (f": {', '.join(changes)}." if changes else "."))
        url = page_url("process", pk) + (f"&tab={tab}" if tab else "")
        return go(request, url)


class CopyTemplateView(CanManageMixin, View):
    def post(self, request, pk):
        step = get_object_or_404(ProductProcess, pk=pk)
        step.copy_template()
        return go(request, page_url("process", pk))


class AddSetView(CanRecordMixin, View):
    """Add a set and open it straight away for its equipment to be chosen."""

    def post(self, request, pk):
        step = get_object_or_404(ProductProcess, pk=pk)
        test_set = TestSet.objects.create(product_process=step, number=step.next_set_number())
        messages.success(request, f"Added {test_set}. Type the equipment ID, asset no. or S/N for each role.")
        return go(request, page_url("process", step.pk) + f"&tab={test_set.pk}")


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
