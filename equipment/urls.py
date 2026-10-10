"""Equipment routes."""

from django.urls import path

from . import views

app_name = "equipment"

urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="list"),
    path("new/", views.EquipmentCreateView.as_view(), name="create"),
    path("search/", views.EquipmentSearchView.as_view(), name="search"),
    path("bulk-delete/", views.EquipmentBulkDeleteView.as_view(), name="bulk_delete"),
    path("import/", views.EquipmentImportView.as_view(), name="import"),
    path("import/template/", views.equipment_import_template, name="import_template"),
    path("export/", views.equipment_export, name="export"),
    path("<int:pk>/", views.EquipmentDetailView.as_view(), name="detail"),
    path("<int:pk>/label/", views.EquipmentLabelView.as_view(), name="label"),
    path("<int:pk>/label/print/", views.EquipmentLabelPrintView.as_view(), name="label_print"),
    path("<int:pk>/preview/", views.EquipmentPreviewView.as_view(), name="preview"),
    path("<int:pk>/edit/", views.EquipmentUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.EquipmentDeleteView.as_view(), name="delete"),
    path("<int:pk>/status/", views.EquipmentStatusChangeView.as_view(), name="status_change"),
]
