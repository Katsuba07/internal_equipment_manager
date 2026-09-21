"""Maintenance and calibration dates are edited on the asset form."""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from calibration.models import CalibrationPlan
from core.models import Role
from core.tests import BaseFixtureMixin
from equipment.models import Equipment
from maintenance.models import MaintenancePlan


class ScheduleDateTests(BaseFixtureMixin, TestCase):
    hx = {"HTTP_HX_REQUEST": "true"}

    def data(self, **fields):
        base = {
            "code": self.equipment.code, "name": self.equipment.name,
            "category": self.category.pk, "location": self.location.pk,
            "parts-TOTAL_FORMS": "0", "parts-INITIAL_FORMS": "0",
            "parts-MIN_NUM_FORMS": "0", "parts-MAX_NUM_FORMS": "1000",
        }
        base.update(fields)
        return base

    def save(self, **fields):
        self.login(Role.MANAGER)
        return self.client.post(reverse("equipment:update", args=[self.equipment.pk]),
                                self.data(**fields), **self.hx)

    def test_calibration_dates_are_saved(self):
        self.save(is_measuring_device="on", calibration_interval_months="12",
                  calibration_last="2026-03-26", calibration_next="2027-03-20")
        plan = CalibrationPlan.objects.get(equipment=self.equipment)
        self.assertEqual(plan.last_calibrated_at, date(2026, 3, 26))
        self.assertEqual(plan.next_due_at, date(2027, 3, 20))
        self.assertTrue(plan.is_active)

    def test_next_calibration_follows_the_last_one_when_left_blank(self):
        self.save(is_measuring_device="on", calibration_interval_months="6",
                  calibration_last="2026-08-31", calibration_next="")
        plan = CalibrationPlan.objects.get(equipment=self.equipment)
        self.assertEqual(plan.next_due_at, date(2027, 2, 28))      # month end kept sensible

    def test_maintenance_dates_are_saved(self):
        self.save(maintenance_required="on", maintenance_interval_days="90",
                  maintenance_last="2026-09-01", maintenance_next="2026-12-15")
        plan = MaintenancePlan.objects.get(equipment=self.equipment, name=Equipment.SCHEDULED_PLAN_NAME)
        self.assertEqual(plan.last_done_at, date(2026, 9, 1))
        self.assertEqual(plan.next_due_at, date(2026, 12, 15))

    def test_next_maintenance_follows_the_last_one_when_left_blank(self):
        self.save(maintenance_required="on", maintenance_interval_days="30",
                  maintenance_last="2026-09-01", maintenance_next="")
        plan = MaintenancePlan.objects.get(equipment=self.equipment, name=Equipment.SCHEDULED_PLAN_NAME)
        self.assertEqual(plan.next_due_at, date(2026, 10, 1))

    def test_the_form_opens_with_the_current_dates(self):
        CalibrationPlan.objects.create(equipment=self.equipment, name="Calibration", interval_months=12,
                                       last_calibrated_at=date(2025, 3, 26), next_due_at=date(2026, 3, 26))
        self.login(Role.MANAGER)
        body = self.client.get(reverse("equipment:update", args=[self.equipment.pk]), **self.hx).content.decode()
        self.assertIn('value="2025-03-26"', body)
        self.assertIn('value="2026-03-26"', body)

    def test_a_next_date_before_the_last_one_is_refused(self):
        response = self.save(is_measuring_device="on", calibration_interval_months="12",
                             calibration_last="2026-09-01", calibration_next="2026-01-01")
        self.assertContains(response, "cannot come before the last one")
        self.assertFalse(CalibrationPlan.objects.filter(equipment=self.equipment).exists())

    def test_unticking_calibration_pauses_the_plan(self):
        plan = CalibrationPlan.objects.create(equipment=self.equipment, name="Calibration",
                                              interval_months=12, next_due_at=date(2026, 3, 26))
        self.save()          # "Requires calibration" left unticked
        plan.refresh_from_db()
        self.assertFalse(plan.is_active)

    def test_the_detail_page_shows_the_new_date(self):
        self.save(is_measuring_device="on", calibration_interval_months="12",
                  calibration_last="2026-03-26", calibration_next="2027-03-26")
        page = self.client.get(reverse("equipment:detail", args=[self.equipment.pk]))
        self.assertContains(page, "26 Mar 2027")
