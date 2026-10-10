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
    path("products/process/<int:pk>/roles/", views.ProcessRolesView.as_view(), name="process_roles"),
    path("products/process/<int:pk>/setup/", views.ProcessSetupView.as_view(), name="process_setup"),
    path("products/process/<int:pk>/copy-template/", views.CopyTemplateView.as_view(), name="process_copy_template"),
    path("products/process/<int:pk>/add-set/", views.AddSetView.as_view(), name="set_add"),
    path("products/set/<int:pk>/edit/", views.SetEditView.as_view(), name="set_edit"),
    # Golden samples of a process (dialogs opened from the process panel)
    path("products/process/<int:pk>/golden/new/", views.GoldenSampleCreateView.as_view(), name="golden_create"),
    path("products/process/<int:pk>/golden/required/", views.GoldenRequirementView.as_view(), name="golden_required"),
    path("products/golden/<int:pk>/edit/", views.GoldenSampleUpdateView.as_view(), name="golden_edit"),
    path("products/golden/<int:pk>/delete/", views.GoldenSampleDeleteView.as_view(), name="golden_delete"),
    # One-click delete (confirmation page)
    path("products/product/<int:pk>/delete/", views.ProductDeleteView.as_view(), name="product_delete"),
    path("products/process/<int:pk>/delete/", views.ProcessDeleteView.as_view(), name="process_delete"),
    path("products/set/<int:pk>/delete/", views.SetDeleteView.as_view(), name="set_delete"),
]
