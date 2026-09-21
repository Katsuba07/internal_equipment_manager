"""Equipment tests: status changes and spreadsheet import."""

import io

from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from core.models import Category, Location, Role, Supplier, User
from equipment.models import Equipment, EquipmentStatus
from equipment.services import HEADERS, import_equipment_from_xlsx

PASSWORD = "test-pass-2026"
BLANKS = [""] * (len(HEADERS) - 4)


def make_workbook(rows: list[list]) -> io.BytesIO:
    """Build an in-memory workbook using the real column headers."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


class StatusChangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="tech", password=PASSWORD, full_name="Khanh Pham", role=Role.TECHNICIAN
        )
        cls.equipment = Equipment.objects.create(
            code="FCT-STN-001",
            name="FCT station 1",
            category=Category.objects.create(code="TESTER", name="Test system"),
            location=Location.objects.create(code="FCT-RM", name="FCT Room"),
            status=EquipmentStatus.IN_PRODUCTION,
        )

    def test_change_status_records_history(self):
        entry = self.equipment.change_status(
            EquipmentStatus.REPAIR, self.user, reason="Intermittent fail on pin 45"
        )
        self.equipment.refresh_from_db()

        self.assertEqual(self.equipment.status, EquipmentStatus.REPAIR)
        self.assertEqual(entry.from_status, EquipmentStatus.IN_PRODUCTION)
        self.assertEqual(entry.to_status, EquipmentStatus.REPAIR)
        self.assertEqual(entry.changed_by, self.user)
        self.assertEqual(entry.reason, "Intermittent fail on pin 45")
        self.assertEqual(self.equipment.status_history.count(), 1)

    def test_changing_to_same_status_does_nothing(self):
        """Avoid junk entries when the same status is picked twice."""
        result = self.equipment.change_status(
            EquipmentStatus.IN_PRODUCTION, self.user, reason="No change"
        )
        self.assertIsNone(result)
        self.assertEqual(self.equipment.status_history.count(), 0)

    def test_status_change_through_view(self):
        self.client.login(username="tech", password=PASSWORD)
        response = self.client.post(
            reverse("equipment:status_change", args=[self.equipment.pk]),
            {"status": EquipmentStatus.MAINTENANCE, "reason": "Scheduled probe service", "note": ""},
        )
        self.assertRedirects(response, self.equipment.get_absolute_url())
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, EquipmentStatus.MAINTENANCE)
        self.assertEqual(
            self.equipment.status_history.first().reason, "Scheduled probe service"
        )

    def test_availability_flag(self):
        self.assertTrue(self.equipment.is_available)
        self.equipment.change_status(EquipmentStatus.DOWN, self.user, reason="Fixture fault")
        self.assertFalse(self.equipment.is_available)


class ExcelImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="manager", password=PASSWORD, full_name="Minh Nguyen", role=Role.MANAGER
        )
        Category.objects.create(code="FIX-FCT", name="FCT fixture")
        Location.objects.create(code="FCT-RM", name="FCT Room")
        Supplier.objects.create(code="SUP-004", name="Fixture House Co., Ltd")

    def test_import_creates_equipment(self):
        file = make_workbook([
            ["FCT-FIX-014", "FCT fixture — BAF1950", "FIX-FCT", "FCT-RM",
             "Fixture House", "FCT-014", "SN-2024-0142", 2024,
             "v2.1.0", "In production",
             "2024-03-15", "8500.00", "2024-04-01", "2026-04-01",
             "SUP-004", "", "128 test points", "Primary fixture line 2"],
        ])
        result = import_equipment_from_xlsx(file, self.user)

        self.assertFalse(result.has_errors, result.errors)
        self.assertEqual(result.created, 1)

        asset = Equipment.objects.get(code="FCT-FIX-014")
        self.assertEqual(asset.name, "FCT fixture — BAF1950")
        # "In production" in a spreadsheet is not taken on trust: only a
        # fitting to a running product makes an asset In production.
        self.assertEqual(asset.status, EquipmentStatus.AVAILABLE)
        self.assertEqual(asset.firmware_version, "v2.1.0")
        self.assertEqual(asset.purchase_date.isoformat(), "2024-03-15")
        self.assertEqual(str(asset.purchase_cost), "8500.00")
        self.assertEqual(asset.supplier.code, "SUP-004")

    def test_lowercase_code_is_normalised_to_uppercase(self):
        file = make_workbook([["fct-fix-009", "FCT fixture", "FIX-FCT", "FCT-RM"] + BLANKS])
        result = import_equipment_from_xlsx(file, self.user)
        self.assertFalse(result.has_errors, result.errors)
        self.assertTrue(Equipment.objects.filter(code="FCT-FIX-009").exists())

    def test_location_may_be_left_blank(self):
        # Assets can be registered before anyone has said where they stand.
        file = make_workbook([["FCT-FIX-020", "FCT fixture", "FIX-FCT", ""] + BLANKS])
        result = import_equipment_from_xlsx(file, self.user)
        self.assertFalse(result.has_errors, result.errors)
        self.assertIsNone(Equipment.objects.get(code="FCT-FIX-020").location)

    def test_an_unknown_location_is_still_an_error(self):
        file = make_workbook([["FCT-FIX-021", "FCT fixture", "FIX-FCT", "NOWHERE"] + BLANKS])
        result = import_equipment_from_xlsx(file, self.user)
        self.assertTrue(result.has_errors)

    def test_calibration_flag(self):
        row = ["DMM-009", "Handheld multimeter", "FIX-FCT", "FCT-RM"] + BLANKS
        row[HEADERS.index("Needs calibration (x)")] = "x"
        result = import_equipment_from_xlsx(make_workbook([row]), self.user)
        self.assertFalse(result.has_errors, result.errors)
        self.assertTrue(Equipment.objects.get(code="DMM-009").is_measuring_device)

    def test_unknown_category_is_reported_and_nothing_is_saved(self):
        file = make_workbook([
            ["FCT-FIX-001", "Valid row", "FIX-FCT", "FCT-RM"] + BLANKS,
            ["FCT-FIX-002", "Bad category", "NO-SUCH", "FCT-RM"] + BLANKS,
        ])
        result = import_equipment_from_xlsx(file, self.user)

        self.assertTrue(result.has_errors)
        self.assertIn("NO-SUCH", result.errors[0])
        # The whole file is rejected — even the valid row is not written.
        self.assertEqual(Equipment.objects.count(), 0)

    def test_duplicate_code_inside_file_is_rejected(self):
        file = make_workbook([
            ["FCT-FIX-001", "First", "FIX-FCT", "FCT-RM"] + BLANKS,
            ["FCT-FIX-001", "Second", "FIX-FCT", "FCT-RM"] + BLANKS,
        ])
        result = import_equipment_from_xlsx(file, self.user)
        self.assertTrue(result.has_errors)
        self.assertIn("twice", result.errors[0])

    def test_existing_code_is_skipped_unless_update_requested(self):
        Equipment.objects.create(
            code="FCT-FIX-001",
            name="Old name",
            category=Category.objects.get(code="FIX-FCT"),
            location=Location.objects.get(code="FCT-RM"),
        )
        rows = [["FCT-FIX-001", "New name", "FIX-FCT", "FCT-RM"] + BLANKS]

        result = import_equipment_from_xlsx(make_workbook(rows), self.user)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(Equipment.objects.get(code="FCT-FIX-001").name, "Old name")

        result = import_equipment_from_xlsx(make_workbook(rows), self.user, update_existing=True)
        self.assertEqual(result.updated, 1)
        self.assertEqual(Equipment.objects.get(code="FCT-FIX-001").name, "New name")

    def test_missing_required_column_is_reported(self):
        workbook = Workbook()
        workbook.active.append(["Asset ID", "Name"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)

        result = import_equipment_from_xlsx(buffer, self.user)
        self.assertTrue(result.has_errors)
        self.assertIn("Missing required columns", result.errors[0])

    def test_invalid_date_is_reported(self):
        row = ["FCT-FIX-001", "Fixture", "FIX-FCT", "FCT-RM"] + BLANKS
        row[HEADERS.index("Purchase date")] = "next tuesday"
        result = import_equipment_from_xlsx(make_workbook([row]), self.user)
        self.assertTrue(result.has_errors)
        self.assertIn("Purchase date", result.errors[0])

    def test_empty_rows_are_ignored(self):
        file = make_workbook([
            ["FCT-FIX-001", "Fixture", "FIX-FCT", "FCT-RM"] + BLANKS,
            [None] * len(HEADERS),
        ])
        result = import_equipment_from_xlsx(file, self.user)
        self.assertFalse(result.has_errors, result.errors)
        self.assertEqual(result.created, 1)


class EquipmentFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(code="FIX-ICT", name="ICT fixture")
        cls.location = Location.objects.create(code="ICT-RM", name="ICT Room")
        User.objects.create_user(
            username="manager", password=PASSWORD, full_name="Minh Nguyen", role=Role.MANAGER
        )

    def test_create_equipment_adds_opening_history_entry(self):
        self.client.login(username="manager", password=PASSWORD)
        response = self.client.post(
            reverse("equipment:create"),
            {
                "code": "ict-fix-007",
                "name": "ICT fixture — Sensor board",
                "category": self.category.pk,
                "location": self.location.pk,
                "year_made": "",
                "purchase_cost": "",
                "parts-TOTAL_FORMS": "0",
                "parts-INITIAL_FORMS": "0",
            },
        )
        self.assertEqual(response.status_code, 302)
        asset = Equipment.objects.get(code="ICT-FIX-007")  # normalised to upper case
        self.assertEqual(asset.status_history.count(), 1)
        self.assertEqual(asset.status_history.first().reason, "Asset record created")

    def test_commissioned_date_before_purchase_date_is_rejected(self):
        from equipment.forms import EquipmentForm

        form = EquipmentForm(data={
            "code": "ICT-FIX-001",
            "name": "Fixture",
            "category": self.category.pk,
            "location": self.location.pk,
            "purchase_date": "2024-05-01",
            "commissioned_date": "2024-01-01",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("commissioned_date", form.errors)
