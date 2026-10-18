"""
Admin for the process catalog.

Products, their processes, stations and equipment sets are managed on the
Stations and Products pages, so they are deliberately not registered here.
"""

from django.contrib import admin

from .models import SystemType


@admin.register(SystemType)
class SystemTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "position", "station_count", "product_count", "is_active")
    list_editable = ("position",)
    fields = ("code", "name", "position", "description", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")

    @admin.display(description="Stations")
    def station_count(self, obj):
        return obj.stations.count()

    @admin.display(description="Products")
    def product_count(self, obj):
        return obj.product_processes.count()
