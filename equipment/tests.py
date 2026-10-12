"""Equipment tests: status changes and spreadsheet import/export."""

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook
from PIL import Image as PILImage

from core.models import Category, Location, Role, User
from core.photos import save_photo
from equipment.models import Equipment, EquipmentStatus
from equipment.services import HEADERS, export_equipment_to_xlsx, import_equipment_from_xlsx

PASSWORD = "test-pass-2026"
BLANKS = [""] * (len(HEADERS) - 4)
EXPORT_TEMP_MEDIA = tempfile.mkdtemp(prefix="ema-test-export-media-")


def photo_file(color="red"):
    buffer = io.BytesIO()
    PILImage.new("RGB", (800, 600), color).save(buffer, format="PNG")
    return SimpleUploadedFile("asset.png", buffer.getvalue(), content_type="image/png")


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

    def test_import_creates_equipment(self):
        file = make_workbook([
            ["FCT-FIX-014", "FCT fixture — BAF1950", "FIX-FCT", "FCT-RM",
             "Fixture House", "FCT-014", "SN-2024-0142", 2024, "In production",
             "", "128 test points", "Primary fixture line 2"],
        ])
        result = import_equipment_from_xlsx(file, self.user)

        self.assertFalse(result.has_errors, result.errors)
        self.assertEqual(result.created, 1)

        asset = Equipment.objects.get(code="FCT-FIX-014")
        self.assertEqual(asset.name, "FCT fixture — BAF1950")
        # "In production" in a spreadsheet is not taken on trust: only a
        # fitting to a running product makes an asset In production.
        self.assertEqual(asset.status, EquipmentStatus.AVAILABLE)
        self.assertEqual(asset.manufacturer, "Fixture House")
        self.assertEqual(asset.specifications, "128 test points")

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

    def test_invalid_year_is_reported(self):
        row = ["FCT-FIX-001", "Fixture", "FIX-FCT", "FCT-RM"] + BLANKS
        row[HEADERS.index("Year")] = "last year"
        result = import_equipment_from_xlsx(make_workbook([row]), self.user)
        self.assertTrue(result.has_errors)
        self.assertIn("Year", result.errors[0])

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
                "parts-TOTAL_FORMS": "0",
                "parts-INITIAL_FORMS": "0",
            },
        )
        self.assertEqual(response.status_code, 302)
        asset = Equipment.objects.get(code="ICT-FIX-007")  # normalised to upper case
        self.assertEqual(asset.status_history.count(), 1)
        self.assertEqual(asset.status_history.first().reason, "Asset record created")


@override_settings(MEDIA_ROOT=EXPORT_TEMP_MEDIA)
class ExportWithPhotosTests(TestCase):
    """The .xlsx export drops each asset's main photo into its row."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(EXPORT_TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        category = Category.objects.create(code="TESTER", name="Test system")
        self.with_photo = Equipment.objects.create(
            code="FCT-STN-001", name="Has a photo", category=category
        )
        self.without_photo = Equipment.objects.create(
            code="FCT-STN-002", name="No photo yet", category=category
        )
        save_photo(self.with_photo, photo_file(), None)

    def test_export_embeds_the_main_photo(self):
        workbook = export_equipment_to_xlsx(Equipment.objects.order_by("code"))
        sheet = workbook.active
        self.assertEqual(sheet.cell(row=1, column=1).value, "Photo")
        self.assertEqual(sheet.cell(row=1, column=2).value, "ZT Code")
        self.assertEqual(sheet.cell(row=1, column=3).value, "Equipment No")
        self.assertEqual(len(sheet._images), 1)
        self.assertEqual(sheet._images[0].anchor, "A2")  # row 2 == FCT-STN-001

    def test_export_without_a_photo_does_not_crash(self):
        workbook = export_equipment_to_xlsx(Equipment.objects.filter(pk=self.without_photo.pk))
        sheet = workbook.active
        self.assertEqual(len(sheet._images), 0)

    def test_export_leaves_out_the_retired_columns(self):
        workbook = export_equipment_to_xlsx(Equipment.objects.filter(pk=self.with_photo.pk))
        headers = [cell.value for cell in workbook.active[1]]
        for gone in ("Firmware version", "Purchase date", "Purchase cost (USD)", "Warranty until", "Supplier"):
            with self.subTest(column=gone):
                self.assertNotIn(gone, headers)
        self.assertEqual(headers[-3:], ["Needs calibration", "Specifications", "Notes"])


class ZtCodeAndLabelTests(TestCase):
    """ZT Code is the key, Equipment No sits beside it, and the label carries both."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="viewer", password=PASSWORD, full_name="Linh Vo", role=Role.VIEWER
        )
        User.objects.create_user(
            username="tech", password=PASSWORD, full_name="Minh Tran", role=Role.TECHNICIAN
        )
        category = Category.objects.create(code="DMM", name="Digital multimeter")
        cls.dmm = Equipment.objects.create(
            code="70-000148", equipment_no="DMM-001", name="KEYSIGHT 34461A",
            category=category, serial_number="MY57224741",
        )
        cls.old = Equipment.objects.create(code="CTV20200077", name="Old style", category=category)

    def setUp(self):
        self.client.login(username="viewer", password=PASSWORD)

    def test_label_shows_the_four_lines_and_the_qr_link(self):
        response = self.client.get(reverse("equipment:label", args=[self.dmm.pk]))
        for text in ("COMPUTIME VIETNAM", "DMM-001", "KEYSIGHT 34461A", "70-000148", "MY57224741", "<svg"):
            self.assertContains(response, text)
        self.assertEqual(
            self.dmm.label_qr_url,
            "https://computime.datafill.com/AssetManagement_VN?Param=70-000148&Task=AssetNo",
        )

    def test_zebra_label_holds_one_copy_per_label_across_the_roll(self):
        from equipment.labels import LabelSize, build_zpl

        zpl = build_zpl(self.dmm, LabelSize(w=45, h=25, cols=2))
        self.assertTrue(zpl.startswith("^XA") and zpl.rstrip().endswith("^XZ"))
        self.assertIn("^PW1063", zpl)              # 90 mm across at 300 dpi
        self.assertEqual(zpl.count("^GFA"), 2)      # the QR code, drawn as a graphic
        for text in ("COMPUTIME VIETNAM", "DMM-001", "KEYSIGHT 34461A", "MY57224741"):
            self.assertEqual(zpl.count(text), 2, text)

    def test_zebra_label_cuts_a_long_name_and_escapes_printer_commands(self):
        from equipment.labels import LabelSize, build_zpl

        self.dmm.name = "A^B " + "very long name " * 10
        zpl = build_zpl(self.dmm, LabelSize(w=45, h=25))
        self.assertIn("A\\5EB", zpl)
        self.assertNotIn("A^B", zpl)
        self.assertNotIn("very long name very long name very long name", zpl)

    def test_zebra_label_text_size_can_be_chosen(self):
        from equipment.labels import LabelSize, build_zpl

        automatic = build_zpl(self.dmm, LabelSize.from_values({"w": "45", "h": "25", "font": "0"}))
        small = build_zpl(self.dmm, LabelSize.from_values({"w": "45", "h": "25", "font": "2"}))
        self.assertIn("^A0N,29,29^FDEQ No:", automatic)
        self.assertIn("^A0N,24,24^FDEQ No:", small)     # 2 mm at 300 dpi

    def test_label_zpl_is_served_for_a_printer_on_the_users_computer(self):
        response = self.client.get(
            reverse("equipment:label_zpl", args=[self.dmm.pk]) + "?w=45&h=25&cols=1&font=2"
        )
        body = response.content.decode()
        self.assertTrue(body.startswith("^XA"))
        self.assertIn("^PW531", body)
        self.assertIn("KEYSIGHT 34461A", body)

    def test_label_page_offers_the_server_printer_only_when_one_is_set(self):
        url = reverse("equipment:label", args=[self.dmm.pk])
        self.client.login(username="tech", password=PASSWORD)
        self.assertNotContains(self.client.get(url), 'id="zebra-print"')
        with self.settings(EMA_LABEL_PRINTER="ZDesigner ZT510-300dpi ZPL"):
            self.assertContains(self.client.get(url), 'id="zebra-print"')
        self.assertContains(self.client.get(url), 'id="local-print"')

    def test_print_label_sends_the_posted_size_to_the_printer(self):
        from unittest import mock

        self.client.login(username="tech", password=PASSWORD)
        with mock.patch("equipment.views.send_to_printer") as send:
            response = self.client.post(
                reverse("equipment:label_print", args=[self.dmm.pk]),
                {"w": "50", "h": "25", "cols": "1", "gap": "0", "dx": "nonsense"},
            )
        self.assertEqual(response.json()["ok"], True)
        self.assertIn("^PW591", send.call_args.args[0])   # one 50 mm label

    def test_print_label_reports_a_printer_that_cannot_be_reached(self):
        from unittest import mock

        from equipment.labels import LabelPrintError

        self.client.login(username="tech", password=PASSWORD)
        with mock.patch("equipment.views.send_to_printer", side_effect=LabelPrintError("Printer is off.")):
            response = self.client.post(reverse("equipment:label_print", args=[self.dmm.pk]))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["message"], "Printer is off.")

    def test_search_finds_an_asset_by_its_equipment_no(self):
        body = self.client.get(reverse("equipment:list") + "?q=dmm-001").content.decode()
        self.assertIn("70-000148", body)
        self.assertNotIn("CTV20200077", body)

    def test_two_assets_cannot_share_an_equipment_no_but_blank_is_fine(self):
        from django.core.exceptions import ValidationError

        clash = Equipment(code="70-000149", equipment_no="DMM-001", name="x", category=self.dmm.category)
        with self.assertRaises(ValidationError):
            clash.full_clean()
        Equipment.objects.create(code="70-000150", name="No number yet", category=self.dmm.category)
        self.assertEqual(Equipment.objects.filter(equipment_no="").count(), 2)

    def test_a_retired_ctv_id_is_flagged_as_pending(self):
        self.assertTrue(self.old.zt_code_pending)
        self.assertFalse(self.dmm.zt_code_pending)
        self.assertContains(self.client.get(self.old.get_absolute_url()), "ZT Code pending")
        self.assertNotContains(self.client.get(self.dmm.get_absolute_url()), "ZT Code pending")
