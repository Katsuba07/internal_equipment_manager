"""Equipment routes."""

from django.urls import path

from . import views

app_name = "equipment"

urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="list"),
    path("new/", views.EquipmentCreateView.as_view(), name="create"),
    path("search/", views.EquipmentSearchView.as_view(), name="search"),
    path("next-no/", views.EquipmentNextNoView.as_view(), name="next_no"),
    path("labels/", views.EquipmentLabelsView.as_view(), name="labels"),
    path("labels/zpl/", views.EquipmentLabelsZplView.as_view(), name="labels_zpl"),
    path("labels/printed/", views.EquipmentMarkLabelledView.as_view(), name="mark_labelled"),
    path("bulk-delete/", views.EquipmentBulkDeleteView.as_view(), name="bulk_delete"),
    path("export/", views.equipment_export, name="export"),
    path("<int:pk>/", views.EquipmentDetailView.as_view(), name="detail"),
    path("<int:pk>/label/", views.EquipmentLabelView.as_view(), name="label"),
    path("<int:pk>/label/print/", views.EquipmentLabelPrintView.as_view(), name="label_print"),
    path("<int:pk>/label/zpl/", views.EquipmentLabelZplView.as_view(), name="label_zpl"),
    path("<int:pk>/labelled/", views.EquipmentLabelledView.as_view(), name="labelled"),
    path("<int:pk>/preview/", views.EquipmentPreviewView.as_view(), name="preview"),
    path("<int:pk>/edit/", views.EquipmentUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.EquipmentDeleteView.as_view(), name="delete"),
]
