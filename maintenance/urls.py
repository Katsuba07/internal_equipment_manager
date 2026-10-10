"""Maintenance routes — all reached from an asset's own detail page."""

from django.urls import path

from . import views

app_name = "maintenance"

urlpatterns = [
    path("<int:equipment_pk>/plan/new/", views.MaintenancePlanCreateView.as_view(), name="plan_create"),
    path("plan/<int:pk>/edit/", views.MaintenancePlanUpdateView.as_view(), name="plan_edit"),
    path("plan/<int:pk>/delete/", views.MaintenancePlanDeleteView.as_view(), name="plan_delete"),
    path("<int:equipment_pk>/record/new/", views.MaintenanceRecordCreateView.as_view(), name="record_create"),
    path("record/<int:pk>/", views.MaintenanceRecordDetailView.as_view(), name="record_detail"),
]
