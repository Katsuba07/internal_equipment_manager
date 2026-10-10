"""Tests for how the next maintenance due date is calculated, and the views."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Category, Location, Role, User
from core.tests import BaseFixtureMixin
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


class MaintenancePlanViewTests(BaseFixtureMixin, TestCase):
    def test_manager_can_create_a_plan(self):
        self.login(Role.MANAGER)
        url = reverse("maintenance:plan_create", args=[self.equipment.pk])
        response = self.client.post(url, {
            "name": "Weekly probe cleaning", "kind": "PREVENTIVE", "interval_days": "7",
        })
        self.assertRedirects(response, self.equipment.get_absolute_url())
        plan = MaintenancePlan.objects.get(name="Weekly probe cleaning")
        self.assertEqual(plan.equipment, self.equipment)
        self.assertEqual(plan.next_due_at, timezone.localdate() + timedelta(days=7))

    def test_technician_cannot_create_a_plan(self):
        self.login(Role.TECHNICIAN)
        url = reverse("maintenance:plan_create", args=[self.equipment.pk])
        response = self.client.post(url, {"name": "x", "interval_days": "7"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MaintenancePlan.objects.exists())

    def test_manager_can_edit_and_pause_a_plan(self):
        plan = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Quarterly check", interval_days=90,
        )
        self.login(Role.MANAGER)
        url = reverse("maintenance:plan_edit", args=[plan.pk])
        response = self.client.post(url, {
            "name": "Quarterly check", "kind": "PREVENTIVE", "interval_days": "90",
        })
        self.assertRedirects(response, self.equipment.get_absolute_url())
        plan.refresh_from_db()
        self.assertFalse(plan.is_active)  # is_active omitted from POST data = unticked

    def test_admin_can_delete_a_plan_without_deleting_its_logs(self):
        plan = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Annual overhaul", interval_days=365,
        )
        MaintenanceRecord.objects.create(
            equipment=self.equipment, plan=plan, performed_at=timezone.localdate(),
            work_done="Full teardown and rebuild",
        )
        self.login(Role.ADMIN)
        response = self.client.post(reverse("maintenance:plan_delete", args=[plan.pk]))
        self.assertRedirects(response, self.equipment.get_absolute_url())
        self.assertFalse(MaintenancePlan.objects.filter(pk=plan.pk).exists())
        record = MaintenanceRecord.objects.get()
        self.assertIsNone(record.plan)

    def test_manager_cannot_delete_a_plan(self):
        plan = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Annual overhaul", interval_days=365,
        )
        self.login(Role.MANAGER)
        response = self.client.post(reverse("maintenance:plan_delete", args=[plan.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(MaintenancePlan.objects.filter(pk=plan.pk).exists())


class MaintenanceRecordViewTests(BaseFixtureMixin, TestCase):
    def setUp(self):
        self.plan = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Pogo pin cleaning", interval_days=30,
            last_done_at=timezone.localdate() - timedelta(days=40),
        )

    def test_technician_can_log_maintenance_against_a_plan(self):
        self.login(Role.TECHNICIAN)
        url = reverse("maintenance:record_create", args=[self.equipment.pk])
        today = timezone.localdate()
        response = self.client.post(url, {
            "plan": self.plan.pk, "kind": "PREVENTIVE", "performed_at": today.isoformat(),
            "work_done": "Cleaned and inspected all pogo pins", "result": "OK",
            "downtime_minutes": "15",
        })
        self.assertRedirects(response, self.equipment.get_absolute_url())
        record = MaintenanceRecord.objects.get()
        self.assertEqual(record.equipment, self.equipment)
        self.assertEqual(record.plan, self.plan)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.next_due_at, today + timedelta(days=30))

    def test_technician_can_log_unplanned_maintenance(self):
        self.login(Role.TECHNICIAN)
        url = reverse("maintenance:record_create", args=[self.equipment.pk])
        response = self.client.post(url, {
            "kind": "OTHER", "performed_at": timezone.localdate().isoformat(),
            "work_done": "Ad-hoc fix after a jam", "result": "OK",
        })
        self.assertRedirects(response, self.equipment.get_absolute_url())
        record = MaintenanceRecord.objects.get()
        self.assertIsNone(record.plan)

    def test_viewer_cannot_log_maintenance(self):
        self.login(Role.VIEWER)
        url = reverse("maintenance:record_create", args=[self.equipment.pk])
        response = self.client.post(url, {
            "kind": "OTHER", "performed_at": timezone.localdate().isoformat(),
            "work_done": "x", "result": "OK",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MaintenanceRecord.objects.exists())

    def test_plan_picker_only_offers_this_equipment_s_active_plans(self):
        other_equipment = Equipment.objects.create(
            code="ICT-FIX-002", name="Other fixture", category=self.category, location=self.location,
        )
        other_plan = MaintenancePlan.objects.create(
            equipment=other_equipment, name="Other plan", interval_days=30,
        )
        paused_plan = MaintenancePlan.objects.create(
            equipment=self.equipment, name="Paused plan", interval_days=30, is_active=False,
        )
        self.login(Role.TECHNICIAN)
        url = reverse("maintenance:record_create", args=[self.equipment.pk])
        response = self.client.get(url)
        offered = list(response.context["form"].fields["plan"].queryset)
        self.assertIn(self.plan, offered)
        self.assertNotIn(other_plan, offered)
        self.assertNotIn(paused_plan, offered)

    def test_record_detail_page_renders_with_photos_card(self):
        record = MaintenanceRecord.objects.create(
            equipment=self.equipment, plan=self.plan, performed_at=timezone.localdate(),
            work_done="Cleaned pogo pins", performed_by=self.users[Role.TECHNICIAN],
        )
        self.login(Role.VIEWER)
        response = self.client.get(record.get_absolute_url())
        self.assertContains(response, "Cleaned pogo pins")
        self.assertContains(response, "Photos")
