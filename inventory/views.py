"""Spare parts: list, record, stock movements, one-click delete."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from core.bulk import BulkDeleteView
from core.mixins import AdminRequiredMixin, CanManageMixin, CanRecordMixin
from core.modals import modal_saved, render_modal, wants_modal
from core.models import Plant
from core.photos import remove_photos, save_photos

from .forms import PartForm, StockMovementForm
from .models import EquipmentPart, InventoryItem, ItemKind, StockTransaction, TransactionType


class PartListView(LoginRequiredMixin, ListView):
    """Every stocked part, with search, type filter and a low-stock toggle."""

    template_name = "inventory/part_list.html"
    context_object_name = "parts"
    paginate_by = 50

    def get_queryset(self):
        qs = InventoryItem.objects.annotate(
            used_on=Count("used_in", distinct=True),
            fitted_qty=Sum("used_in__quantity"),
        ).order_by("code")
        params = self.request.GET
        if q := params.get("q", "").strip():
            qs = qs.filter(
                Q(code__icontains=q) | Q(name__icontains=q)
                | Q(manufacturer_part__icontains=q) | Q(specification__icontains=q)
            )
        if plant := params.get("plant"):
            qs = qs.filter(plant=plant)
        if kind := params.get("kind"):
            qs = qs.filter(kind=kind)
        if params.get("low"):
            qs = qs.filter(is_active=True, quantity_on_hand__lte=F("min_quantity"))
        if not params.get("inactive"):
            qs = qs.filter(is_active=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["kinds"] = ItemKind.choices
        context["plants"] = Plant.choices
        context["low_count"] = InventoryItem.objects.below_minimum().count()
        context["total_count"] = self.object_list.count()
        context["has_filters"] = any(
            v for k, v in self.request.GET.items() if k != "page"
        )
        return context


class PartDetailView(LoginRequiredMixin, DetailView):
    queryset = InventoryItem.objects.prefetch_related("attachments")
    template_name = "inventory/part_detail.html"
    context_object_name = "part"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        used_in = self.object.used_in.select_related("equipment__location").order_by("equipment__code")
        context["used_in"] = used_in
        context["fitted_total"] = sum((line.quantity for line in used_in), 0)
        context["movements"] = self.object.transactions.select_related("performed_by", "equipment")[:30]
        return context


class PartPreviewView(LoginRequiredMixin, DetailView):
    """Quick-look drawer on the spare parts list; the full page when opened directly."""

    queryset = InventoryItem.objects.select_related("supplier").prefetch_related("attachments")
    template_name = "inventory/_preview.html"
    context_object_name = "part"

    def get(self, request, *args, **kwargs):
        if request.headers.get("HX-Request") != "true":
            return redirect("inventory:part_detail", pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        used_in = list(self.object.used_in.select_related("equipment").order_by("equipment__code"))
        context["used_in"] = used_in
        context["fitted_total"] = sum((line.quantity for line in used_in), 0)
        context["last_movement"] = self.object.transactions.select_related("performed_by").first()
        return context


class PartCreateView(CanManageMixin, CreateView):
    model = InventoryItem
    form_class = PartForm
    template_name = "inventory/part_form.html"

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            opening = form.cleaned_data.get("opening_stock")
            if opening:
                StockTransaction(
                    item=self.object,
                    transaction_type=TransactionType.IN,
                    quantity=opening,
                    performed_by=self.request.user,
                    reason="Opening stock",
                ).apply()
            save_photos(self.object, form.cleaned_data.get("photos"), self.request.user)
        messages.success(self.request, f"Created part {self.object.code}.")
        return response


class PartUpdateView(CanManageMixin, UpdateView):
    model = InventoryItem
    form_class = PartForm
    template_name = "inventory/part_form.html"

    def get_template_names(self):
        # A dialog from the Edit button, the full page when opened directly.
        if wants_modal(self.request):
            return ["inventory/_part_edit_modal.html"]
        return super().get_template_names()

    def form_valid(self, form):
        response = super().form_valid(form)
        remove_photos(self.object, form.cleaned_data.get("remove_photos"))
        save_photos(self.object, form.cleaned_data.get("photos"), self.request.user)
        messages.success(self.request, f"Saved {self.object.code}.")
        if wants_modal(self.request):
            return modal_saved()
        return response


class StockMovementView(CanRecordMixin, FormView):
    """Receipt, issue or stocktake — the only way the balance changes."""

    form_class = StockMovementForm
    template_name = "inventory/stock_movement.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.part = get_object_or_404(InventoryItem, pk=kwargs["pk"])

    def get_initial(self):
        return {"transaction_type": self.request.GET.get("type", TransactionType.IN)}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["part"] = self.part          # the picker offers this part's assets first
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["part"] = self.part
        return context

    def as_modal(self, form):
        kind = {"IN": "Receive", "OUT": "Issue"}.get(self.request.GET.get("type"), "Stock movement")
        return render_modal(
            self.request, form,
            title=f"{kind} — {self.part.code}",
            subtitle=f"{self.part.name} · {self.part.quantity_on_hand:g} {self.part.unit} on hand",
            action=self.request.get_full_path(), submit="Record",
            note="An issue needs the asset it goes to. For a stocktake, enter the counted quantity — it replaces the balance.",
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
        movement = form.save(commit=False)
        movement.item = self.part
        movement.performed_by = self.request.user
        try:
            movement.apply()
        except ValidationError as error:
            form.add_error("quantity", error.messages[0])
            return self.form_invalid(form)
        target = f" to {movement.equipment.code}" if movement.equipment_id else ""
        messages.success(
            self.request,
            f"{movement.get_transaction_type_display()}{target} recorded — "
            f"{self.part.code} now {movement.quantity_after.normalize():f} {self.part.unit}.",
        )
        if wants_modal(self.request):
            return modal_saved()
        return redirect(self.part.get_absolute_url())


class PartDeleteView(AdminRequiredMixin, View):
    """One click: the part, its movements and its place in every parts list."""

    def get(self, request, pk):
        part = get_object_or_404(InventoryItem, pk=pk)
        removed = [
            ("Parts-list lines on equipment", part.used_in.count()),
            ("Stock movements", part.transactions.count()),
        ]
        return render(request, "systems/confirm_delete.html", {
            "object": part,
            "kind": "Part",
            "summary": {"removed": [(l, c) for l, c in removed if c], "released": []},
            "cancel_url": part.get_absolute_url(),
        })

    def post(self, request, pk):
        part = get_object_or_404(InventoryItem, pk=pk)
        code = part.code
        with transaction.atomic():
            part.delete()
        messages.success(request, f"Deleted part {code}.")
        return redirect(reverse("inventory:parts"))


class PartBulkDeleteView(BulkDeleteView):
    """Delete the parts ticked on the list, with their movements and parts-list lines."""

    model = InventoryItem
    noun = "part"
    list_url_name = "inventory:parts"

    def summary(self, items):
        ids = list(items.values_list("pk", flat=True))
        return {
            "Stock movements": StockTransaction.objects.filter(item_id__in=ids).count(),
            "Parts-list lines on equipment": EquipmentPart.objects.filter(item_id__in=ids).count(),
            "Photos": sum(len(item.photos) for item in items),
        }

    def perform(self, items):
        count = 0
        with transaction.atomic():
            for item in items:
                item.delete()       # one by one so photo files are removed too
                count += 1
        return count
