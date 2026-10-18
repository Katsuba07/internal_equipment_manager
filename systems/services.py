"""
Set readiness, the products overview and one-click deletion.

Kept out of the models and views so the rules can be tested on their own and
the page queries stay in one place.
"""

from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q

from core.models import Product
from equipment.models import UNAVAILABLE_STATUSES, Equipment

from .models import (
    SLOT_STATE_BADGE,
    GoldenSample,
    Installation,
    ProductDocument,
    ProductProcess,
    SlotState,
    Station,
    StationSlot,
    TestSet,
)


def unusable_reason(equipment: Equipment) -> str:
    """Why this asset cannot be relied on right now, or an empty string."""
    if equipment.status in UNAVAILABLE_STATUSES:
        return equipment.get_status_display()
    if equipment.calibration_date_unknown:
        return "Calibration date unknown"
    for plan in equipment.calibration_plans.all():
        if plan.is_active and plan.is_overdue:
            return f"Calibration {plan.due_display.lower()}"
    for plan in equipment.maintenance_plans.all():
        if plan.is_active and plan.is_overdue:
            return f"Maintenance {plan.due_display.lower()}"
    return ""


# ------------------------------------------------------------------ readiness


@dataclass(frozen=True)
class Need:
    """
    One line of a set's check: a shared machine of the station, or a slot the
    model fills itself. ``name``/``is_required``/``category`` read like a slot.
    """

    name: str
    is_required: bool = True
    category: object = None
    slot: object = None


@dataclass
class RoleStatus:
    """The verdict for one line of one set: a shared machine, or one of the model's slots."""

    role: Need
    state: str
    detail: str = ""
    installation: Installation | None = None

    @property
    def equipment(self):
        return self.installation.component if self.installation else None

    @property
    def from_station(self) -> bool:
        """A machine the station shares, rather than one the model brought itself."""
        return bool(self.installation and self.installation.station_id)

    @property
    def is_blocking(self) -> bool:
        return self.state in {SlotState.EMPTY, SlotState.WRONG_CATEGORY, SlotState.UNUSABLE}

    @property
    def badge_class(self) -> str:
        return SLOT_STATE_BADGE.get(self.state, "badge-neutral")

    @property
    def state_label(self) -> str:
        return SlotState(self.state).label


@dataclass
class SetReadiness:
    test_set: TestSet
    lines: list[RoleStatus] = field(default_factory=list)

    @property
    def blocking(self) -> list[RoleStatus]:
        return [status for status in self.lines if status.is_blocking]

    @property
    def is_ready(self) -> bool:
        return bool(self.lines) and not self.blocking

    @property
    def badge_class(self) -> str:
        if not self.lines:
            return "badge-neutral"
        return "badge-success" if self.is_ready else "badge-danger"

    @property
    def dot_class(self) -> str:
        return self.badge_class.replace("badge-", "dot-")

    @property
    def label(self) -> str:
        if not self.lines:
            return "No station" if not self.test_set.station_id else "Nothing on it"
        if self.is_ready:
            return "Ready"
        count = len(self.blocking)
        return f"{count} issue{'s' if count != 1 else ''}"

    @property
    def summary(self) -> str:
        if not self.lines:
            if not self.test_set.station_id:
                return "Not run on any station yet"
            return "The station has no machines and no slots yet"
        problems = self.blocking
        if not problems:
            return "Every machine in place and usable"
        first = problems[0]
        rest = len(problems) - 1
        text = f"{first.role.name}: {first.detail or first.state_label}"
        return f"{text} (+{rest} more)" if rest else text


def _with_plans(queryset):
    return queryset.select_related("component__category").prefetch_related(
        "component__calibration_plans", "component__maintenance_plans"
    )


def _check(need, installation) -> RoleStatus:
    asset = installation.component
    if need.category is not None and asset.category_id != need.category.pk:
        return RoleStatus(need, SlotState.WRONG_CATEGORY,
                          f"{asset.category.name}, needs {need.category.name}", installation)
    reason = unusable_reason(asset)
    if reason:
        return RoleStatus(need, SlotState.UNUSABLE, reason, installation)
    return RoleStatus(need, SlotState.READY, "", installation)


def evaluate_set(test_set: TestSet, station_installations=None, installations=None, slots=None) -> SetReadiness:
    """
    Whether a model's set can run: every machine its station shares must be
    usable, and every slot of the station filled by the model with a usable
    machine of the right kind.

    The three lists may be passed in when the caller has already loaded them
    for many sets (the overview page).
    """
    if not test_set.station_id:
        return SetReadiness(test_set, [])
    station = test_set.station
    if station_installations is None:
        station_installations = list(_with_plans(station.open_installations()))
    if installations is None:
        installations = list(_with_plans(test_set.open_installations()))
    if slots is None:
        slots = list(station.slots.select_related("category"))

    lines = [
        _check(Need(inst.component.category.name, True, inst.component.category), inst)
        for inst in station_installations
    ]
    by_slot = {inst.slot_id: inst for inst in installations if inst.slot_id}
    for slot in slots:
        need = Need(slot.name, slot.is_required, slot.category, slot)
        installation = by_slot.get(slot.pk)
        if installation is None:
            state = SlotState.EMPTY if slot.is_required else SlotState.OPTIONAL_EMPTY
            lines.append(RoleStatus(need, state))
        else:
            lines.append(_check(need, installation))
    # A machine fitted to the set without a slot (older records) still counts.
    for inst in installations:
        if not inst.slot_id:
            lines.append(_check(Need(inst.component.category.name, True, None), inst))
    return SetReadiness(test_set, lines)


# ------------------------------------------------------------------ overview


@dataclass
class CustomerGroup:
    customer: object
    products: list
    total: int

    @property
    def name(self) -> str:
        return self.customer.name if self.customer else "No customer"

    @property
    def key(self) -> str:
        return f"c{self.customer.pk}" if self.customer else "c0"


def filtered_products(plant: str = "", query: str = "", customer: str = ""):
    """Products matching the page's filters. The search also looks in document names."""
    products = Product.objects.all()
    if plant:
        products = products.filter(plant=plant)
    if customer:
        products = products.filter(customer__code=customer)
    if query:
        # By id, so a document-name match does not narrow the documents counted later.
        by_document = ProductDocument.objects.filter(file_name__icontains=query).values("products")
        products = products.filter(
            Q(code__icontains=query) | Q(name__icontains=query) | Q(pk__in=by_document)
        )
    return products


def products_overview(show_all: bool = False, plant: str = "", query: str = "", customer: str = "",
                      production: str = "") -> list[CustomerGroup]:
    """
    Every customer with its products, each product with its processes and, for
    each process, its sets and the equipment fitted in them now.

    Loaded in a handful of queries whatever the number of products.
    """
    products = (
        filtered_products(plant, query, customer)
        .select_related("customer")
        .annotate(doc_count=Count("documents", distinct=True))
        .prefetch_related(
            Prefetch(
                "processes",
                queryset=ProductProcess.objects.select_related("process").prefetch_related(
                    Prefetch("sets", queryset=TestSet.objects.select_related("line", "station").order_by("number")),
                    "golden_samples",
                ),
            )
        )
        .order_by("code")
    )
    open_installs, station_installs = {}, {}
    for inst in _with_plans(Installation.objects.filter(removed_at__isnull=True)):
        if inst.test_set_id:
            open_installs.setdefault(inst.test_set_id, []).append(inst)
        elif inst.station_id:
            station_installs.setdefault(inst.station_id, []).append(inst)
    station_slots = {}
    for slot in StationSlot.objects.select_related("category"):
        station_slots.setdefault(slot.station_id, []).append(slot)

    groups: dict = {}
    totals: dict = {}
    for product in products:
        key = product.customer_id or 0
        totals[key] = totals.get(key, 0) + 1
        if not (show_all or product.in_production):
            continue
        # The Production filter: "yes" running only, "no" idle only.
        if production == "yes" and not product.in_production or production == "no" and product.in_production:
            continue
        steps = []
        for step in product.processes.all():
            sets = []
            for test_set in step.sets.all():
                installs = open_installs.get(test_set.id, [])
                sets.append({
                    "set": test_set,
                    "installations": installs,
                    "readiness": evaluate_set(
                        test_set, station_installs.get(test_set.station_id, []), installs,
                        station_slots.get(test_set.station_id, []),
                    ),
                })
            steps.append({"step": step, "sets": sets, "golden": step.golden_status()})
        groups.setdefault(key, (product.customer, []))[1].append({"product": product, "steps": steps})

    for _customer, items in groups.values():
        items.sort(key=lambda item: (not item["product"].in_production, item["product"].code))
    result = [CustomerGroup(customer, items, totals[key]) for key, (customer, items) in groups.items()]
    result.sort(key=lambda g: (g.customer is None, g.name.lower()))
    return result


def set_detail(test_set: TestSet) -> dict:
    """Everything the right-hand panel shows for one set."""
    def load(queryset):
        return list(
            queryset.select_related("component__category", "component__location").prefetch_related(
                "component__calibration_plans", "component__maintenance_plans",
                "component__parts__item", "component__attachments",
            )
        )

    installs = load(test_set.open_installations())
    station = load(test_set.station.open_installations()) if test_set.station_id else []
    readiness = evaluate_set(test_set, station_installations=station, installations=installs)
    return {"test_set": test_set, "readiness": readiness}


# ------------------------------------------------------------------ changes


@transaction.atomic
def apply_set_changes(test_set: TestSet, picks: dict, user) -> list[str]:
    """
    Make a model's set hold exactly the chosen machines in its station's slots.

    ``picks`` maps slot id -> Equipment or None. Slots not in ``picks`` are
    left alone. Removals happen before fits so a machine can move between
    slots of the same set. Returns a short list of what changed.
    """
    chosen = [asset.id for asset in picks.values() if asset is not None]
    if len(chosen) != len(set(chosen)):
        raise ValidationError("The same asset is chosen for two slots.")

    slots = {slot.pk: slot for slot in test_set.station.slots.select_related("category")} if test_set.station_id else {}
    current = {inst.slot_id: inst for inst in test_set.open_installations().select_related("component") if inst.slot_id}
    changes = []
    for slot_id, asset in picks.items():
        inst = current.get(slot_id)
        if inst and (asset is None or inst.component_id != asset.id):
            inst.release(user, reason=f"Changed on station {test_set.station}")
            changes.append(f"removed {inst.component.ident}")
    for slot_id, asset in picks.items():
        inst = current.get(slot_id)
        if asset is not None and not (inst and inst.component_id == asset.id):
            Installation.fit(asset, test_set, slots[slot_id], user, reason=f"Fitted on station {test_set.station}")
            changes.append(f"fitted {asset.ident}")
    return changes


def busy_map(exclude_set: TestSet | None = None, exclude_station: Station | None = None,
             models_of: Station | None = None) -> dict:
    """
    asset id -> where it is fitted, for every asset fitted somewhere. Filling
    a set, its own station's equipment is not "busy": it is there to be used,
    and neither are the other models' own machines there (a fixture may serve
    several). ``models_of`` is the same for a model not added yet.
    """
    qs = Installation.objects.filter(removed_at__isnull=True).select_related(
        "test_set__product_process__product", "test_set__product_process__process", "station"
    )
    if exclude_set is not None:
        qs = qs.exclude(test_set=exclude_set)
        if exclude_set.station_id:
            qs = qs.exclude(station_id=exclude_set.station_id).exclude(test_set__station_id=exclude_set.station_id)
    if models_of is not None:
        qs = qs.exclude(station=models_of).exclude(test_set__station=models_of)
    if exclude_station is not None:
        qs = qs.exclude(station=exclude_station)
    return {inst.component_id: inst.where for inst in qs}


# ------------------------------------------------------------------ deletion


def deletion_summary(obj) -> dict:
    """What deleting a product, process or set takes with it. Assets are only released."""
    if isinstance(obj, Product):
        sets = TestSet.objects.filter(product_process__product=obj)
        removed = [
            ("Processes", obj.processes.count()),
            ("Equipment sets", sets.count()),
            ("Golden samples", GoldenSample.objects.filter(product_process__product=obj).count()),
        ]
    elif isinstance(obj, ProductProcess):
        sets = obj.sets.all()
        removed = [
            ("Equipment sets", sets.count()),
            ("Golden samples", obj.golden_samples.count()),
        ]
    elif isinstance(obj, TestSet):
        sets = TestSet.objects.filter(pk=obj.pk)
        removed = []
    else:
        raise TypeError(f"No deletion summary for {type(obj).__name__}")
    released = Installation.objects.filter(test_set__in=sets, removed_at__isnull=True)
    return {
        "removed": [(label, count) for label, count in removed if count],
        "released": list(released.select_related("component")),
    }


@transaction.atomic
def delete_with_release(obj, user):
    """Delete a product, process or set in one step, releasing its equipment first."""
    if isinstance(obj, Product):
        sets = TestSet.objects.filter(product_process__product=obj)
    elif isinstance(obj, ProductProcess):
        sets = obj.sets.all()
    else:
        sets = TestSet.objects.filter(pk=obj.pk)
    for test_set in sets:
        test_set.delete(user=user)
    if not isinstance(obj, TestSet):
        obj.delete()


# ------------------------------------------------------------------ per asset


def equipment_usage(equipment: Equipment) -> dict:
    """Where one asset is fitted now, and where it has been."""
    history = list(
        Installation.objects.select_related(
            "test_set__product_process__product", "test_set__product_process__process",
            "role", "station", "installed_by", "removed_by",
        )
        .filter(component=equipment)
        .order_by("-installed_at")[:20]
    )
    current = next((inst for inst in history if inst.is_open), None)
    return {"current_installation": current, "history": history}


# ------------------------------------------------------------------ overview page


def line_status() -> dict:
    """
    The top of the Overview page: every product in production with the state of
    each of its sets, and the list of what is wrong, worst first.
    """
    rows, issues, golden_warnings = [], [], []
    ready = total = 0
    for group in products_overview(show_all=False):
        for item in group.products:
            product, pills, bad = item["product"], [], False
            for step in item["steps"]:
                # Golden samples are a warning beside the line, never a blocker.
                for warning in step["golden"].warnings:
                    golden_warnings.append({"step": step["step"], "text": warning})
                for entry in step["sets"]:
                    readiness = entry["readiness"]
                    total += 1
                    ready += readiness.is_ready
                    bad = bad or not readiness.is_ready
                    label = step["step"].process.code
                    if len(step["sets"]) > 1:
                        label += f" #{entry['set'].number}"
                    pills.append({"set": entry["set"], "label": label, "readiness": readiness})
                    for line in readiness.blocking:
                        issues.append({"product": product, "set": entry["set"], "line": line})
            rows.append({"product": product, "customer": group.name, "pills": pills, "bad": bad})
    rows.sort(key=lambda row: (not row["bad"], row["customer"].lower(), row["product"].code))
    return {
        "rows": rows,
        "issues": issues,
        "golden_warnings": golden_warnings,
        "sets_total": total,
        "sets_ready": ready,
        "sets_bad": total - ready,
        "product_count": len(rows),
    }
