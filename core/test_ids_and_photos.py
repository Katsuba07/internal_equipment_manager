"""Equipment ID, Asset No. and S/N as three identifiers; photos picked on the edit forms."""

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from core.models import Role
from core.test_photos import image_file
from core.tests import BaseFixtureMixin
from equipment.models import Equipment
from equipment.services import import_equipment_from_xlsx
from inventory.models import InventoryItem

TEMP_MEDIA = tempfile.mkdtemp(prefix="ema-test-media-")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class IdsAndPhotosTests(BaseFixtureMixin, TestCase):
    hx = {"HTTP_HX_REQUEST": "true"}

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def data(self, **fields):
        base = {
            "code": self.equipment.code, "name": self.equipment.name,
            "category": self.category.pk, "location": self.location.pk,
            "parts-TOTAL_FORMS": "0", "parts-INITIAL_FORMS": "0",
            "parts-MIN_NUM_FORMS": "0", "parts-MAX_NUM_FORMS": "1000",
        }
        base.update(fields)
        return base

    def edit(self, **fields):
        self.login(Role.MANAGER)
        return self.client.post(reverse("equipment:update", args=[self.equipment.pk]),
                                self.data(**fields), **self.hx)

    # --- identifiers -----------------------------------------------------

    def test_the_three_identifiers_are_saved_separately(self):
        self.edit(code="ctv20200077", asset_no="103220100359", serial_number="41415453WS")
        self.equipment.refresh_from_db()
        self.assertEqual(
            (self.equipment.code, self.equipment.asset_no, self.equipment.serial_number),
            ("CTV20200077", "103220100359", "41415453WS"),
        )

    def test_an_asset_number_cannot_be_used_twice(self):
        Equipment.objects.create(code="CTV20200001", name="Other", category=self.category,
                                 asset_no="103220100359")
        response = self.edit(asset_no="103220100359")
        self.assertContains(response, "already on CTV20200001")

    def test_the_list_shows_all_three_and_search_finds_the_asset_number(self):
        self.edit(asset_no="103220100359", serial_number="41415453WS")
        self.login(Role.VIEWER)
        body = self.client.get(reverse("equipment:list") + "?q=1032201003").content.decode()
        for text in ("ZT Code", "Equipment No", "Asset No.", "S/N", "103220100359", "41415453WS", self.equipment.code):
            self.assertIn(text, body)

    def test_old_spreadsheets_with_asset_id_still_load(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Asset ID", "Name", "Category code", "Asset No."])
        sheet.append(["CTV20200099", "Bench PSU", self.category.code, "103220100600"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        result = import_equipment_from_xlsx(buffer, self.users[Role.MANAGER])
        self.assertFalse(result.has_errors, result.errors)
        self.assertEqual(Equipment.objects.get(code="CTV20200099").asset_no, "103220100600")

    # --- photos ------------------------------------------------------------

    def test_photos_picked_in_the_edit_dialog_are_attached(self):
        response = self.edit(photos=[image_file("front.png"), image_file("label.jpg", fmt="JPEG")])
        self.assertEqual(response.json()["reload"], True)
        photos = self.equipment.photos
        self.assertEqual(len(photos), 2)
        self.assertEqual(sum(1 for p in photos if p.is_primary), 1)

    def test_a_file_that_is_not_a_picture_stops_the_save(self):
        bad = SimpleUploadedFile("notes.png", b"not really an image", content_type="image/png")
        response = self.edit(name="Renamed", photos=[bad])
        self.assertContains(response, "is not an image")
        self.equipment.refresh_from_db()
        self.assertNotEqual(self.equipment.name, "Renamed")
        self.assertEqual(len(self.equipment.photos), 0)

    def test_a_new_asset_can_come_with_its_photo(self):
        self.login(Role.MANAGER)
        data = self.data(code="CTV20200123", name="New fixture", photos=[image_file()])
        self.client.post(reverse("equipment:create"), data)
        self.assertEqual(len(Equipment.objects.get(code="CTV20200123").photos), 1)

    def test_the_picker_offers_camera_or_gallery_on_a_phone(self):
        self.login(Role.MANAGER)
        body = self.client.get(reverse("equipment:update", args=[self.equipment.pk]), **self.hx).content.decode()
        self.assertIn('accept="image/*"', body)
        self.assertIn("multiple", body)
        self.assertNotIn("capture=", body)          # would force the camera
        self.assertIn('enctype="multipart/form-data"', body)

    def test_a_part_edit_can_add_photos(self):
        part = InventoryItem.objects.create(code="PRB-1", name="Probe", unit="pcs")
        self.login(Role.MANAGER)
        self.client.post(reverse("inventory:part_update", args=[part.pk]), {
            "code": "PRB-1", "name": "Probe", "kind": "PROBE", "unit": "pcs",
            "min_quantity": "0", "is_active": "on", "photos": [image_file()],
        }, **self.hx)
        self.assertEqual(len(part.photos), 1)
