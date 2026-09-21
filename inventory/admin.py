"""Admin site for spare parts."""

from django.contrib import admin

from .models import InventoryItem


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "quantity_on_hand", "unit", "min_quantity", "plant", "is_active")
    list_filter = ("kind", "plant", "is_active")
    search_fields = ("code", "name", "manufacturer_part", "specification")
    autocomplete_fields = ("supplier",)
    # The balance only changes through stock movements in the main application.
    readonly_fields = ("quantity_on_hand", "created_at", "updated_at")
