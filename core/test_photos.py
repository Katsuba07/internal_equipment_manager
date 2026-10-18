"""Photos of equipment and spare parts: upload, shrink, main photo, delete, serving."""

import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.models import Attachment, Role
from core.tests import BaseFixtureMixin
from inventory.models import InventoryItem

TEMP_MEDIA = tempfile.mkdtemp(prefix="ema-test-media-")


def image_file(name="photo.png", size=(2400, 1200), color="red", fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class PhotoTests(BaseFixtureMixin, TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def upload(self, obj_url, *files):
        return self.client.post(obj_url, {"photos": list(files)})

    def equipment_url(self):
        return reverse("photo_upload", args=["equipment", "equipment", self.equipment.pk])

    def test_upload_shrinks_makes_thumbnail_and_first_is_main(self):
        self.login(Role.TECHNICIAN)
        response = self.upload(self.equipment_url(), image_file("a.png"), image_file("b.png", color="blue"))
        self.assertRedirects(response, self.equipment.get_absolute_url() + "#photos", fetch_redirect_response=False)
        photos = self.equipment.photos
        self.assertEqual(len(photos), 2)
        self.assertTrue(photos[0].is_primary)
        self.assertFalse(photos[1].is_primary)
        with Image.open(photos[0].file.path) as big, Image.open(photos[0].thumbnail.path) as thumb:
            self.assertEqual(max(big.size), 1600)
            self.assertEqual(max(thumb.size), 360)
            self.assertEqual(big.format, "JPEG")

    def test_not_an_image_is_refused(self):
        self.login(Role.TECHNICIAN)
        bad = SimpleUploadedFile("notes.png", b"not really an image", content_type="image/png")
        response = self.upload(self.equipment_url(), bad)
        self.assertFalse(Attachment.objects.exists())
        self.assertRedirects(response, self.equipment.get_absolute_url() + "#photos", fetch_redirect_response=False)

    def test_make_main_and_delete_promotes_the_next(self):
        self.login(Role.MANAGER)
        self.upload(self.equipment_url(), image_file("a.png"), image_file("b.png"))
        first, second = self.equipment.photos
        self.client.post(reverse("photo_primary", args=[second.pk]))
        self.assertEqual(self.equipment.photos[0].pk, second.pk)
        path = Path(second.file.path)
        self.client.post(reverse("photo_delete", args=[second.pk]))
        self.assertFalse(path.exists())                 # the file goes with it
        self.assertEqual([p.pk for p in self.equipment.photos], [first.pk])
        self.assertTrue(self.equipment.photos[0].is_primary)

    def test_spare_part_photos_show_on_part_page(self):
        part = InventoryItem.objects.create(code="PRB-1", name="Probe")
        self.login(Role.TECHNICIAN)
        self.upload(reverse("photo_upload", args=["inventory", "inventoryitem", part.pk]), image_file())
        self.assertEqual(len(part.photos), 1)
        self.login(Role.VIEWER)
        self.assertContains(self.client.get(part.get_absolute_url()), part.photos[0].file.url)

    def test_equipment_page_and_set_panel_show_the_photo(self):
        from systems.models import Installation, ProductProcess, SystemType, TestSet
        from core.models import Product

        self.login(Role.TECHNICIAN)
        self.upload(self.equipment_url(), image_file())
        photo = self.equipment.photos[0]
        self.login(Role.VIEWER)
        self.assertContains(self.client.get(self.equipment.get_absolute_url()), photo.file.url)

        step = ProductProcess.objects.create(
            product=Product.objects.create(code="P1", name="P1"),
            process=SystemType.objects.create(code="ICT", name="ICT"),
        )
        from systems.models import Station

        station = Station.objects.create(code="ICT-01", process=step.process)
        role = station.slots.create(category=self.category, position=1)
        test_set = TestSet.objects.create(product_process=step, number=1, station=station)
        Installation.fit(self.equipment, test_set, role, self.users[Role.ADMIN])
        panel = self.client.get(reverse("systems:set_panel", args=[test_set.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(panel, photo.thumbnail.url)

    def test_viewer_cannot_upload_or_delete(self):
        self.login(Role.VIEWER)
        self.upload(self.equipment_url(), image_file())
        self.assertFalse(Attachment.objects.exists())
        self.login(Role.TECHNICIAN)
        self.upload(self.equipment_url(), image_file())
        photo = Attachment.objects.get()
        self.client.post(reverse("photo_delete", args=[photo.pk]))   # technicians do not delete
        self.assertTrue(Attachment.objects.filter(pk=photo.pk).exists())

    def test_uploads_are_served_only_to_signed_in_users(self):
        self.login(Role.TECHNICIAN)
        self.upload(self.equipment_url(), image_file())
        url = self.equipment.photos[0].file.url
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_deleting_the_equipment_removes_its_photo_files(self):
        self.login(Role.TECHNICIAN)
        self.upload(self.equipment_url(), image_file())
        path = Path(self.equipment.photos[0].file.path)
        self.equipment.delete()
        self.assertFalse(path.exists())

    # --- nameplate photos: a second, separate slot -------------------------

    def nameplate_url(self):
        return reverse("nameplate_upload", args=["equipment", "equipment", self.equipment.pk])

    def test_nameplate_photos_are_kept_apart_from_general_photos(self):
        self.login(Role.TECHNICIAN)
        self.upload(self.equipment_url(), image_file("a.png"))
        self.upload(self.nameplate_url(), image_file("b.png", color="blue"))
        self.assertEqual(len(self.equipment.photos), 1)
        self.assertEqual(len(self.equipment.nameplate_photos), 1)
        self.assertNotEqual(self.equipment.photos[0].pk, self.equipment.nameplate_photos[0].pk)

    def test_nameplate_upload_redirects_to_its_own_anchor(self):
        self.login(Role.TECHNICIAN)
        response = self.upload(self.nameplate_url(), image_file())
        self.assertRedirects(response, self.equipment.get_absolute_url() + "#nameplate", fetch_redirect_response=False)

    def test_make_main_and_delete_a_nameplate_photo_only_touches_nameplate_photos(self):
        self.login(Role.MANAGER)
        self.upload(self.equipment_url(), image_file("g.png"))          # a general photo, untouched below
        general = self.equipment.photos[0]
        self.upload(self.nameplate_url(), image_file("a.png"), image_file("b.png"))
        first, second = self.equipment.nameplate_photos
        self.client.post(reverse("photo_primary", args=[second.pk]))
        self.assertEqual(self.equipment.nameplate_photos[0].pk, second.pk)
        self.client.post(reverse("photo_delete", args=[second.pk]))
        self.assertEqual([p.pk for p in self.equipment.nameplate_photos], [first.pk])
        self.assertTrue(self.equipment.nameplate_photos[0].is_primary)
        self.assertEqual([p.pk for p in self.equipment.photos], [general.pk])   # unaffected

    def test_equipment_detail_page_shows_the_nameplate_card(self):
        self.login(Role.VIEWER)
        body = self.client.get(self.equipment.get_absolute_url()).content.decode()
        self.assertIn('id="nameplate"', body)
        self.assertIn("No nameplate photo yet.", body)

    def test_the_edit_form_offers_a_nameplate_photo_field(self):
        self.login(Role.MANAGER)
        body = self.client.get(reverse("equipment:update", args=[self.equipment.pk]),
                               HTTP_HX_REQUEST="true").content.decode()
        self.assertIn('name="nameplate_photos"', body)

    def test_removing_a_nameplate_photo_on_the_edit_form_does_not_remove_general_photos(self):
        self.login(Role.MANAGER)
        self.upload(self.equipment_url(), image_file("g.png"))
        self.upload(self.nameplate_url(), image_file("n.png"))
        nameplate = self.equipment.nameplate_photos[0]
        self.client.post(reverse("equipment:update", args=[self.equipment.pk]), {
            "code": self.equipment.code, "equipment_no": self.equipment.code, "name": self.equipment.name, "category": self.category.pk,
            "remove_nameplate_photos": [str(nameplate.pk)],
            "plant": "CTV2", "parts-TOTAL_FORMS": "0", "parts-INITIAL_FORMS": "0",
        })
        self.assertEqual(len(self.equipment.nameplate_photos), 0)
        self.assertEqual(len(self.equipment.photos), 1)
