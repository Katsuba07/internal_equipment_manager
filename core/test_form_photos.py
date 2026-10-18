"""Photos on the edit form: several picks add up, ticked ones are deleted; schedule dates need their tick."""

import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Attachment, Role
from core.photos import save_photo
from core.test_photos import image_file
from core.tests import BaseFixtureMixin

TEMP_MEDIA = tempfile.mkdtemp(prefix="ema-test-media-")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class FormPhotoTests(BaseFixtureMixin, TestCase):
    hx = {"HTTP_HX_REQUEST": "true"}

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def data(self, **fields):
        base = {
            "code": self.equipment.code, "equipment_no": self.equipment.code, "name": self.equipment.name,
            "category": self.category.pk, "location": self.location.pk,
            "plant": "CTV2", "parts-TOTAL_FORMS": "0", "parts-INITIAL_FORMS": "0",
            "parts-MIN_NUM_FORMS": "0", "parts-MAX_NUM_FORMS": "1000",
        }
        base.update(fields)
        return base

    def test_ticked_photos_are_deleted_and_another_becomes_main(self):
        first = save_photo(self.equipment, image_file("a.png"), None)
        second = save_photo(self.equipment, image_file("b.png"), None)
        self.assertTrue(first.is_primary)
        self.login(Role.MANAGER)
        self.client.post(reverse("equipment:update", args=[self.equipment.pk]),
                         self.data(remove_photos=[str(first.pk)]), **self.hx)
        self.assertFalse(Attachment.objects.filter(pk=first.pk).exists())
        second.refresh_from_db()
        self.assertTrue(second.is_primary)

    def test_only_this_asset_s_photos_can_be_ticked_off(self):
        from equipment.models import Equipment
        other = Equipment.objects.create(code="OTHER-1", name="Other", category=self.category)
        theirs = save_photo(other, image_file(), None)
        self.login(Role.MANAGER)
        response = self.client.post(reverse("equipment:update", args=[self.equipment.pk]),
                                    self.data(remove_photos=[str(theirs.pk)]), **self.hx)
        self.assertEqual(response["Content-Type"].split(";")[0], "text/html")   # refused, form comes back
        self.assertTrue(Attachment.objects.filter(pk=theirs.pk).exists())

    def test_the_form_offers_removal_and_stacking(self):
        save_photo(self.equipment, image_file(), None)
        self.login(Role.MANAGER)
        body = self.client.get(reverse("equipment:update", args=[self.equipment.pk]), **self.hx).content.decode()
        self.assertIn('name="remove_photos"', body)
        self.assertIn("data-photo-stage", body)

    def test_schedule_fields_wait_for_their_tick(self):
        self.login(Role.MANAGER)
        body = self.client.get(reverse("equipment:update", args=[self.equipment.pk]), **self.hx).content.decode()
        self.assertIn('data-needs="id_maintenance_required"', body)
        self.assertIn('data-needs="id_is_measuring_device"', body)
