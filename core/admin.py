"""Admin site for foundation data."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.contrib.contenttypes.admin import GenericTabularInline

from .models import Attachment, Category, Customer, Location, Supplier, User

admin.site.site_header = "Equipment Manager"
admin.site.site_title = "Equipment Manager"
admin.site.index_title = "Data administration"

# Access is controlled by User.role, not by Django groups, so the Groups page
# would only be a second, unused place to look for permissions.
admin.site.unregister(Group)


class AttachmentInline(GenericTabularInline):
    """Attach files directly from any record's edit page."""

    model = Attachment
    extra = 0
    fields = ("file", "kind", "description")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "full_name", "employee_code", "department", "role", "is_active")
    list_filter = ("role", "is_active", "department")
    search_fields = ("username", "full_name", "employee_code", "email")
    ordering = ("full_name", "username")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Person", {"fields": ("full_name", "employee_code", "department", "phone", "email")}),
        (
            "Access",
            {
                "fields": ("role", "is_active", "is_superuser"),
                "description": "The role decides what this person can do in the application.",
            },
        ),
        ("Dates", {"fields": ("last_login", "date_joined"), "classes": ("collapse",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "full_name", "role", "password1", "password2"),
            },
        ),
    )


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "plant", "parent", "is_active")
    list_filter = ("plant", "is_active", "parent")
    list_editable = ("plant",)
    search_fields = ("code", "name")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    list_editable = ("is_active",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "product_count", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    list_editable = ("is_active",)

    @admin.display(description="Products")
    def product_count(self, obj):
        return obj.products.count()


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        "code", "name", "contact_person", "phone", "is_calibration_provider", "is_active",
    )
    list_filter = ("is_calibration_provider", "is_active")
    search_fields = ("code", "name", "contact_person", "phone")

