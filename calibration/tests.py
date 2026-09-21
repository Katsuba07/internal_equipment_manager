"""Tests for calibration due-date arithmetic."""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from calibration.models import CalibrationPlan, CalibrationRecord, CalibrationResult, add_months
from core.models import Category, Location, Role, User
from equipment.models import Equipment


class AddMonthsTests(TestCase):
    """Adding months must survive month ends and leap years."""

    def test_simple_addition(self):
        self.assertEqual(add_months(date(2026, 1, 15), 6), date(2026, 7, 15))

    def test_crossing_year_boundary(self):
        self.assertEqual(add_months(date(2026, 10, 20), 12), date(2027, 10, 20))
        self.assertEqual(add_months(date(2026, 12, 5), 1), date(2027, 1, 5))

    def test_day_is_clamped_to_end_of_shorter_month(self):
        # 31 Jan + 1 month: February has no 31st
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2026, 3, 31), 1), date(2026, 4, 30))

    def test_leap_year(self):
        self.assertEqual(add_months(date(2028, 1, 31), 1), date(2028, 2, 29))


class CalibrationPlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="tech", password="x", full_name="Khanh Pham", role=Role.TECHNICIAN
        )
        cls.equipment = Equipment.objects.create(
            code="DMM-001",
            name="6.5-digit bench multimeter",
            category=Category.objects.create(code="DMM", name="Digital multimeter"),
            location=Location.objects.create(code="CAL-LAB", name="Calibration Lab"),
            is_measuring_device=True,
        )

    def test_new_plan_calculates_due_date(self):
        plan = CalibrationPlan.objects.create(
            equipment=self.equipment,
            name="DC voltage",
            interval_months=12,
            last_calibrated_at=date(2026, 3, 10),
        )
        self.assertEqual(plan.next_due_at, date(2027, 3, 10))

    def test_recording_calibration_updates_the_plan(self):
        plan = CalibrationPlan.objects.create(
            equipment=self.equipment,
            name="DC voltage",
            interval_months=12,
            last_calibrated_at=date(2025, 1, 10),
        )
        self.assertTrue(plan.is_overdue)

        CalibrationRecord.objects.create(
            equipment=self.equipment,
            plan=plan,
            calibrated_at=timezone.localdate(),
            performed_by=self.user,
            result=CalibrationResult.PASS,
            certificate_number="Q3-2026-18422",
        )

        plan.refresh_from_db()
        self.assertEqual(plan.last_calibrated_at, timezone.localdate())
        self.assertEqual(plan.next_due_at, add_months(timezone.localdate(), 12))
        self.assertFalse(plan.is_overdue)

    def test_certificate_due_date_wins_over_configured_interval(self):
        """
        The date printed on the certificate is the auditable one.

        A laboratory can issue a shorter validity than the interval configured
        here; when it does, the system must follow the certificate.
        """
        plan = CalibrationPlan.objects.create(
            equipment=self.equipment, name="DC voltage", interval_months=12
        )
        certificate_due = date(2027, 1, 31)

        CalibrationRecord.objects.create(
            equipment=self.equipment,
            plan=plan,
            calibrated_at=date(2026, 7, 31),
            next_due_at=certificate_due,
            performed_by=self.user,
            result=CalibrationResult.ADJUSTED,
        )

        plan.refresh_from_db()
        self.assertEqual(plan.next_due_at, certificate_due)

    def test_overdue_instrument_is_flagged(self):
        plan = CalibrationPlan.objects.create(
            equipment=self.equipment,
            name="DC voltage",
            interval_months=12,
            next_due_at=timezone.localdate() - timedelta(days=30),
        )
        self.assertTrue(plan.is_overdue)
        self.assertEqual(plan.due_badge_class, "badge-danger")
        self.assertIn("overdue", plan.due_display)
