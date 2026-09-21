"""Tests for how the next maintenance due date is calculated."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Category, Location, Role, User
from equipment.models import Equipment
from maintenance.models import MaintenancePlan, MaintenanceRecord


class MaintenanceScheduleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="tech", password="x", full_name="Khanh Pham", role=Role.TECHNICIAN
        )
        cls.equipment = Equipment.objects.create(
            code="ICT-FIX-001",
            name="ICT fixture — Mainboard",
            category=Category.objects.create(code="FIX-ICT", name="ICT fixture"),
            location=Location.objects.create(code="ICT-RM", name="ICT Room"),
        )

    def test_new_plan_gets_due_date_from_today(self):
        plan = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Pogo pin cleaning", interval_days=30
        )
        self.assertEqual(plan.next_due_at, timezone.localdate() + timedelta(days=30))

    def test_new_plan_with_last_done_counts_from_that_date(self):
        last = timezone.localdate() - timedelta(days=10)
        plan = MaintenancePlan.objects.create(
            equipment=self.equipment,
            name="Contact resistance check",
            interval_days=30,
            last_done_at=last,
        )
        self.assertEqual(plan.next_due_at, last + timedelta(days=30))

    def test_recording_maintenance_moves_the_due_date(self):
        """Once logged, the task must stop showing as overdue."""
        last = timezone.localdate() - timedelta(days=40)
        plan = MaintenancePlan.objects.create(
            equipment=self.equipment,
            name="Probe replacement",
            interval_days=30,
            last_done_at=last,
        )
        self.assertTrue(plan.is_overdue)

        today = timezone.localdate()
        MaintenanceRecord.objects.create(
            equipment=self.equipment,
            plan=plan,
            performed_at=today,
            performed_by=self.user,
            work_done="Replaced probes on power nets",
        )

        plan.refresh_from_db()
        self.assertEqual(plan.last_done_at, today)
        self.assertEqual(plan.next_due_at, today + timedelta(days=30))
        self.assertFalse(plan.is_overdue)

    def test_record_without_plan_does_not_crash(self):
        """Unplanned work is still loggable."""
        record = MaintenanceRecord.objects.create(
            equipment=self.equipment,
            performed_at=timezone.localdate(),
            performed_by=self.user,
            work_done="Ad-hoc probe cleaning after flux spill",
        )
        self.assertIsNone(record.plan)

    def test_due_display_wording(self):
        today = timezone.localdate()
        overdue = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Overdue task", interval_days=30,
            next_due_at=today - timedelta(days=5),
        )
        due_today = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Today task", interval_days=30, next_due_at=today,
        )
        tomorrow = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Tomorrow task", interval_days=30,
            next_due_at=today + timedelta(days=1),
        )
        upcoming = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Upcoming task", interval_days=30,
            next_due_at=today + timedelta(days=3),
        )

        self.assertEqual(overdue.due_display, "5 days overdue")
        self.assertEqual(due_today.due_display, "Due today")
        self.assertEqual(tomorrow.due_display, "Due tomorrow")
        self.assertEqual(upcoming.due_display, "In 3 days")

        self.assertTrue(overdue.is_overdue)
        self.assertTrue(due_today.is_due_soon)
        self.assertTrue(upcoming.is_due_soon)

    def test_checklist_items_are_split_by_line(self):
        plan = MaintenancePlan.objects.create(
            equipment=self.equipment,
            name="Inspection",
            interval_days=7,
            checklist="Blow out debris\n\nClean probe tips\n  Inspect for wear  ",
        )
        self.assertEqual(
            plan.checklist_items,
            ["Blow out debris", "Clean probe tips", "Inspect for wear"],
        )
