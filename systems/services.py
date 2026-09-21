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
    Installation,
    ProcessRole,
    ProductDocument,
    ProductProcess,
    SlotState,
    TestSet,
)


def unusable_reason(equipment: Equipment) -> str:
    """Why this asset cannot be relied on right now, or an empty string."""
    if equipment.status in UNAVAILABLE_STATUSES:
        return equipment.get_status_display()
    for plan in equipment.calibration_plans.all():
        if plan.is_active and plan.is_overdue:
            return f"Calibration {plan.due_display.lower()}"
    return ""


# ------------------------------------------------------------------ readiness


@dataclass
class RoleStatus:
    """The verdict for one role of one set."""

    role: ProcessRole
    state: str
    detail: str = ""
    installation: Installation | None = None

    @property
    def equipment(self):
        return self.installation.component if self.installation else None

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
            return "No roles"
        if self.is_ready:
            return "Ready"
        count = len(self.blocking)
        return f"{count} issue{'s' if count != 1 else ''}"

    @property
    def summary(self) -> str:
        if not self.lines:
            return "No roles declared for this process yet"
        problems = self.blocking
        if not problems:
            return "Every required role fitted and usable"
        first = problems[0]
        rest = len(problems) - 1
        text = f"{first.role.name}: {first.detail or first.state_label}"
        return f"{text} (+{rest} more)" if rest else text


def evaluate_set(test_set: TestSet, roles=None, installations=None) -> SetReadiness:
    """
    Check each role of a set against what is fitted to it.

    ``roles`` and ``installations`` may be passed in when the caller has
    already loaded them for many sets at once (the overview page).
    """
    if roles is None:
        roles = list(test_set.product_process.roles.select_related("category"))
    if installations is None:
        installations = list(
            test_set.open_installations().select_related("component__category")
            .prefetch_related("component__calibration_plans")
        )
    by_role = {inst.role_id: inst for inst in installations}

    lines = []
    for role in roles:
        installation = by_role.get(role.id)
        if installation is None:
            state = SlotState.EMPTY if role.is_required else SlotState.OPTIONAL_EMPTY
            lines.append(RoleStatus(role, state))
            continue
        asset = installation.component
        if not role.accepts(asset):
            lines.append(RoleStatus(
                role, SlotState.WRONG_CATEGORY,
                f"{asset.category.name}, needs {role.category.name}", installation,
            ))
            continue
        reason = unusable_reason(asset)
        if reason:
            lines.append(RoleStatus(role, SlotState.UNUSABLE, reason, installation))
            continue
        lines.append(RoleStatus(role, SlotState.READY, "", installation))
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


def products_overview(show_all: bool = False, plant: str = "", query: str = "", customer: str = "") -> list[CustomerGroup]:
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
                    Prefetch("roles", queryset=ProcessRole.objects.select_related("category")),
                    Prefetch("sets", queryset=TestSet.objects.select_related("line").order_by("number")),
                ),
            )
        )
        .order_by("code")
    )
    open_installs = {}
    for inst in (
        Installation.objects.filter(removed_at__isnull=True, test_set__isnull=False)
        .select_related("component__category")
        .prefetch_related("component__calibration_plans")
    ):
        open_installs.setdefault(inst.test_set_id, []).append(inst)

    groups: dict = {}
    totals: dict = {}
    for product in products:
        key = product.customer_id or 0
        totals[key] = totals.get(key, 0) + 1
        if not (show_all or product.in_production):
            continue
        steps = []
        for step in product.processes.all():
            roles = list(step.roles.all())
            role_order = {role.id: index for index, role in enumerate(roles)}
            sets = []
            for test_set in step.sets.all():
                installs = sorted(
                    open_installs.get(test_set.id, []),
                    key=lambda inst: role_order.get(inst.role_id, 999),
                )
                sets.append({
                    "set": test_set,
                    "installations": installs,
                    "readiness": evaluate_set(test_set, roles, installs),
                })
            steps.append({"step": step, "sets": sets})
        groups.setdefault(key, (product.customer, []))[1].append({"product": product, "steps": steps})

    for _customer, items in groups.values():
        items.sort(key=lambda item: (not item["product"].in_production, item["product"].code))
    result = [CustomerGroup(customer, items, totals[key]) for key, (customer, items) in groups.items()]
    result.sort(key=lambda g: (g.customer is None, g.name.lower()))
    return result


def set_detail(test_set: TestSet) -> dict:
    """Everything the right-hand panel shows for one set."""
    installs = list(
        test_set.open_installations()
        .select_related("component__category", "component__location")
        .prefetch_related("component__calibration_plans", "component__parts__item", "component__attachments")
    )
    readiness = evaluate_set(test_set, installations=installs)
    return {"test_set": test_set, "readiness": readiness}


# ------------------------------------------------------------------ changes


@transaction.atomic
def apply_set_changes(test_set: TestSet, picks: dict, user) -> list[str]:
    """
    Make a set hold exactly the chosen assets.

    ``picks`` maps role id -> Equipment or None. Roles not in ``picks`` are left
    alone. Removals happen before fits so assets can move between roles of the
    same set. Returns a short list of what changed.
    """
    chosen = [asset.id for asset in picks.values() if asset is not None]
    if len(chosen) != len(set(chosen)):
        raise ValidationError("The same asset is chosen for two roles.")

    roles = {role.id: role for role in test_set.product_process.roles.all()}
    current = {inst.role_id: inst for inst in test_set.open_installations().select_related("component")}
    changes = []
    for role_id, asset in picks.items():
        inst = current.get(role_id)
        if inst and (asset is None or inst.component_id != asset.id):
            inst.release(user, reason="Changed on the products page")
            changes.append(f"removed {inst.component.code}")
    for role_id, asset in picks.items():
        inst = current.get(role_id)
        if asset is not None and not (inst and inst.component_id == asset.id):
            Installation.fit(asset, test_set, roles[role_id], user, reason="Fitted on the products page")
            changes.append(f"fitted {asset.code}")
    return changes


def busy_map(exclude_set: TestSet | None = None) -> dict:
    """asset id -> where it is fitted, for every asset fitted somewhere."""
    qs = Installation.objects.filter(removed_at__isnull=True).select_related(
        "test_set__product_process__product", "test_set__product_process__process"
    )
    if exclude_set is not None:
        qs = qs.exclude(test_set=exclude_set)
    return {inst.component_id: inst.where for inst in qs}


# ------------------------------------------------------------------ deletion


def deletion_summary(obj) -> dict:
    """What deleting a product, process or set takes with it. Assets are only released."""
    if isinstance(obj, Product):
        sets = TestSet.objects.filter(product_process__product=obj)
        removed = [
            ("Processes", obj.processes.count()),
            ("Roles", ProcessRole.objects.filter(product_process__product=obj).count()),
            ("Equipment sets", sets.count()),
        ]
    elif isinstance(obj, ProductProcess):
        sets = obj.sets.all()
        removed = [("Roles", obj.roles.count()), ("Equipment sets", sets.count())]
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
            "role", "installed_by", "removed_by",
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
    rows, issues = [], []
    ready = total = 0
    for group in products_overview(show_all=False):
        for item in group.products:
            product, pills, bad = item["product"], [], False
            for step in item["steps"]:
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
        "sets_total": total,
        "sets_ready": ready,
        "sets_bad": total - ready,
        "product_count": len(rows),
    }
