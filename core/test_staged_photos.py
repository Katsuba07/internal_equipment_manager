"""Photos sent ahead of the form: kept through a failed save, attached on a good one."""

import os
import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Attachment, Role
from core.photos import STAGE_DIR
from core.test_photos import image_file
from core.tests import BaseFixtureMixin
from equipment.models import Equipment

TEMP_MEDIA = tempfile.mkdtemp(prefix="ema-test-staged-")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class StagedPhotoTests(BaseFixtureMixin, TestCase):
    hx = {"HTTP_HX_REQUEST": "true"}

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def stage(self, name="a.png"):
        response = self.client.post(reverse("photo_stage"), {"photo": image_file(name)})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["token"]

    def new_asset(self, number, **fields):
        data = {
            "equipment_no": number, "category": self.category.pk, "manufacturer": "Keysight", "model_number": "34461A",
            "plant": "CTV2", "parts-TOTAL_FORMS": "0", "parts-INITIAL_FORMS": "0", "parts-MIN_NUM_FORMS": "0", "parts-MAX_NUM_FORMS": "1000",
        }
        data.update(fields)
        return self.client.post(reverse("equipment:create"), data)

    def test_a_photo_sent_ahead_is_attached_on_save_and_the_spare_copy_goes(self):
        self.login(Role.MANAGER)
        token = self.stage()
        self.assertTrue(os.path.exists(os.path.join(TEMP_MEDIA, STAGE_DIR, token)))
        self.new_asset("DMM-0101", photos__staged=token)
        asset = Equipment.objects.get(equipment_no="DMM-0101")
        self.assertEqual(len(asset.photos), 1)
        self.assertFalse(os.path.exists(os.path.join(TEMP_MEDIA, STAGE_DIR, token)))

    def test_photos_survive_a_save_refused_for_a_taken_number(self):
        self.login(Role.MANAGER)
        Equipment.objects.create(equipment_no="DMM-0102", name="FIRST", category=self.category)
        token = self.stage()
        nameplate = self.stage("plate.png")
        page = self.new_asset("DMM-0102", photos__staged=token, nameplate_photos__staged=nameplate).content.decode()
        self.assertIn("already on FIRST", page)
        self.assertIn("next free number", page)
        # The returned form still carries both photos, shown and ready to send again.
        self.assertIn(f'name="photos__staged" value="{token}"', page)
        self.assertIn(f'name="nameplate_photos__staged" value="{nameplate}"', page)
        self.assertIn(reverse("photo_staged", args=[token]), page)
        self.new_asset("DMM-0103", photos__staged=token, nameplate_photos__staged=nameplate)
        asset = Equipment.objects.get(equipment_no="DMM-0103")
        self.assertEqual((len(asset.photos), len(asset.nameplate_photos)), (1, 1))

    def test_the_staged_picture_can_be_shown_again(self):
        self.login(Role.MANAGER)
        token = self.stage()
        response = self.client.get(reverse("photo_staged", args=[token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("photo_staged", args=["0" * 32])).status_code, 404)

    def test_something_that_is_not_a_picture_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.login(Role.MANAGER)
        response = self.client.post(reverse("photo_stage"), {"photo": SimpleUploadedFile("x.png", b"not an image")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("not an image", response.json()["error"])

    def test_a_viewer_cannot_send_photos(self):
        self.login(Role.VIEWER)
        response = self.client.post(reverse("photo_stage"), {"photo": image_file()})
        self.assertNotEqual(response.status_code, 200)

    def test_the_photo_page_takes_photos_sent_ahead(self):
        self.login(Role.TECHNICIAN)
        token = self.stage()
        self.client.post(reverse("photo_upload", args=["equipment", "equipment", self.equipment.pk]),
                         {"photos__staged": token})
        self.assertEqual(Attachment.objects.filter(object_id=self.equipment.pk).count(), 1)


class CapitalsAndNameTests(BaseFixtureMixin, TestCase):
    def test_identifying_text_is_kept_in_capitals(self):
        asset = Equipment.objects.create(
            equipment_no="dmm-0200", name="bench  meter", manufacturer="Keysight", model_number="34461a",
            serial_number="my123", category=self.category,
        )
        asset.refresh_from_db()
        self.assertEqual((asset.equipment_no, asset.name, asset.manufacturer, asset.model_number, asset.serial_number),
                         ("DMM-0200", "BENCH METER", "KEYSIGHT", "34461A", "MY123"))

    def test_a_name_made_from_make_and_model_follows_them_on_the_edit_form(self):
        made = Equipment.objects.create(equipment_no="DMM-0201", name="KEYSIGHT 34461A", manufacturer="Keysight",
                                        model_number="34461A", category=self.category)
        typed = Equipment.objects.create(equipment_no="DMM-0202", name="BENCH METER LINE 2", manufacturer="Keysight",
                                         model_number="34461A", category=self.category)
        self.login(Role.MANAGER)
        page = self.client.get(reverse("equipment:update", args=[made.pk])).content.decode()
        self.assertIn('data-made="KEYSIGHT 34461A"', page)
        self.assertIn("text-upper", page)
        page = self.client.get(reverse("equipment:update", args=[typed.pk])).content.decode()
        self.assertNotIn("data-made=", page)
