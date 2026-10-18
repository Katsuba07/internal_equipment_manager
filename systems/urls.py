"""Products page routes."""

from django.urls import path

from . import documents, views

app_name = "systems"

urlpatterns = [
    path("products/", views.ProductsView.as_view(), name="products"),
    path("documents/check/", documents.DocumentSyncView.as_view(), name="document_sync"),
    path("documents/<int:pk>/open/", documents.DocumentOpenView.as_view(), name="document_open"),
    path("products/product/<int:pk>/documents/", documents.DocumentUploadView.as_view(), name="document_upload"),
    # Panels (htmx; open the full page when visited directly)
    path("products/set/<int:pk>/", views.SetPanelView.as_view(), name="set_panel"),
    path("products/product/<int:pk>/", views.ProductPanelView.as_view(), name="product_panel"),
    path("products/process/<int:pk>/", views.ProcessPanelView.as_view(), name="process_panel"),
    # Changes
    path("products/new/", views.ProductFormView.as_view(), name="product_create"),
    path("products/product/<int:pk>/edit/", views.ProductFormView.as_view(), name="product_edit"),
    path("products/product/<int:pk>/toggle/", views.ProductToggleView.as_view(), name="product_toggle"),
    path("products/product/<int:pk>/add-process/", views.AddProcessView.as_view(), name="process_add"),
    path("products/process/<int:pk>/move/<str:direction>/", views.MoveProcessView.as_view(), name="process_move"),
    path("products/product/<int:pk>/reorder/", views.ReorderProcessesView.as_view(), name="process_reorder"),
    # Golden samples of a process (dialogs opened from the process panel)
    path("products/process/<int:pk>/golden/new/", views.GoldenSampleCreateView.as_view(), name="golden_create"),
    path("products/process/<int:pk>/golden/required/", views.GoldenRequirementView.as_view(), name="golden_required"),
    path("products/golden/<int:pk>/edit/", views.GoldenSampleUpdateView.as_view(), name="golden_edit"),
    path("products/golden/<int:pk>/delete/", views.GoldenSampleDeleteView.as_view(), name="golden_delete"),
    # Stations: equipment shared by every product run there
    path("products/stations/", views.StationListView.as_view(), name="stations"),
    path("products/stations/new/", views.StationFormView.as_view(), name="station_create"),
    path("products/stations/<int:pk>/", views.StationDetailView.as_view(), name="station_detail"),
    path("products/stations/<int:pk>/preview/", views.StationPreviewView.as_view(), name="station_preview"),
    path("products/stations/<int:pk>/add-model/", views.StationAddModelView.as_view(), name="station_add_model"),
    path("products/stations/<int:pk>/remove/<int:set_pk>/", views.StationRemoveModelView.as_view(), name="station_remove_model"),
    path("products/stations/<int:pk>/models/<int:set_pk>/", views.StationModelEditView.as_view(), name="station_model_edit"),
    path("products/stations/<int:pk>/models/<int:set_pk>/run/", views.StationChangeoverView.as_view(), name="station_changeover"),
    path("products/stations/<int:pk>/edit/", views.StationFormView.as_view(), name="station_edit"),
    path("products/stations/<int:pk>/delete/", views.StationDeleteView.as_view(), name="station_delete"),
    # One-click delete (confirmation page)
    path("products/product/<int:pk>/delete/", views.ProductDeleteView.as_view(), name="product_delete"),
    path("products/process/<int:pk>/delete/", views.ProcessDeleteView.as_view(), name="process_delete"),
    path("products/set/<int:pk>/delete/", views.SetDeleteView.as_view(), name="set_delete"),
]
