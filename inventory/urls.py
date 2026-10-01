"""Spare parts routes."""

from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.PartListView.as_view(), name="parts"),
    path("new/", views.PartCreateView.as_view(), name="part_create"),
    path("bulk-delete/", views.PartBulkDeleteView.as_view(), name="part_bulk_delete"),
    path("<int:pk>/", views.PartDetailView.as_view(), name="part_detail"),
    path("<int:pk>/preview/", views.PartPreviewView.as_view(), name="part_preview"),
    path("<int:pk>/edit/", views.PartUpdateView.as_view(), name="part_update"),
    path("<int:pk>/stock/", views.StockMovementView.as_view(), name="part_stock"),
    path("<int:pk>/delete/", views.PartDeleteView.as_view(), name="part_delete"),
    path("movements/<int:pk>/edit/", views.StockMovementUpdateView.as_view(), name="movement_edit"),
    path("movements/<int:pk>/delete/", views.StockMovementDeleteView.as_view(), name="movement_delete"),
]
