"""
Delete several records at once from a list page.

Ticking rows on the equipment or spare parts list and pressing "Delete selected"
leads here: a confirm page that names every record and what goes with it, then
one POST that deletes them all. Administrators only.
"""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from .mixins import AdminRequiredMixin

# Enough to recognise the selection without turning the page into a wall.
SHOWN = 60


class BulkDeleteView(AdminRequiredMixin, View):
    model = None
    noun = "record"            # singular, lower case
    list_url_name = ""
    template_name = "core/bulk_delete.html"

    def selected(self, request):
        raw = request.POST.get("ids") or request.GET.get("ids", "")
        ids = [int(part) for part in raw.split(",") if part.strip().isdigit()]
        return self.model.objects.filter(pk__in=ids).order_by("code")

    def summary(self, items) -> dict[str, int]:
        """What goes along with the selection, as label -> count."""
        return {}

    def perform(self, items) -> int:
        return items.delete()[1].get(self.model._meta.label, 0)

    def plural(self, count: int) -> str:
        return self.noun if count == 1 else f"{self.noun}s"

    def get(self, request):
        items = self.selected(request)
        count = items.count()
        if not count:
            messages.info(request, f"No {self.noun}s were selected.")
            return redirect(self.list_url_name)
        return render(request, self.template_name, {
            "items": items[:SHOWN],
            "count": count,
            "more": max(count - SHOWN, 0),
            "noun": self.plural(count),
            "summary": {label: n for label, n in self.summary(items).items() if n},
            "ids": ",".join(str(pk) for pk in items.values_list("pk", flat=True)),
            "cancel_url": reverse(self.list_url_name),
        })

    def post(self, request):
        items = self.selected(request)
        count = self.perform(items)
        messages.success(request, f"Deleted {count} {self.plural(count)}.")
        return redirect(self.list_url_name)
