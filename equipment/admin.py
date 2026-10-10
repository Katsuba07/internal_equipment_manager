"""Admin site for equipment records."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from core.admin import AttachmentInline

from .deletion import delete_assets
from .models import Equipment, StatusHistory


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    can_delete = False
    fields = ("created_at", "from_status", "to_status", "changed_by", "reason")
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        # History rows come from real status changes, never typed in by hand.
        return False


@admin.register(Equipment)
class EquipmentAdmin(SimpleHistoryAdmin):
    list_display = (
        "code", "name", "category", "location", "status",
        "is_measuring_device",
    )
    list_filter = ("status", "category", "location", "is_measuring_device")
    search_fields = (
        "code", "name", "serial_number", "model_number", "manufacturer",
    )
    autocomplete_fields = ("category", "location")
    inlines = [StatusHistoryInline, AttachmentInline]
    readonly_fields = ("status_changed_at", "created_at", "updated_at")

    fieldsets = (
        ("Identification", {"fields": ("code", "name", "category", "location")}),
        (
            "Technical",
            {
                "fields": (
                    "manufacturer", "model_number", "serial_number", "year_made",
                    "specifications",
                )
            },
        ),
        (
            "Status",
            {
                "fields": ("status", "status_changed_at"),
                "description": "Changing status here does NOT record a reason. "
                "Prefer the 'Change status' action in the main application.",
            },
        ),
        ("Calibration", {"fields": ("is_measuring_device",)}),
        ("Other", {"fields": ("notes", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    # Maintenance, calibration, repair and incident logs hold the asset with
    # PROTECT, which would make the admin refuse. They go with the asset, as
    # they do from the main application.
    def get_deleted_objects(self, objs, request):
        deleted, counts, perms_needed, _protected = super().get_deleted_objects(objs, request)
        return deleted, counts, perms_needed, []

    def delete_model(self, request, obj):
        delete_assets(Equipment.objects.filter(pk=obj.pk))

    def delete_queryset(self, request, queryset):
        delete_assets(queryset)

