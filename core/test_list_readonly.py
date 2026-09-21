"""The equipment list is for reading: changes go through Edit, never the list itself."""

from django.test import TestCase
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch

from core.models import Role
from core.tests import BaseFixtureMixin
from equipment.models import Equipment


class ReadOnlyListTests(BaseFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other = Equipment.objects.create(
            code="70-000005", name="Digital multimeter", category=cls.category,
            location=cls.location, serial_number="41415452WS",
        )

    def test_the_s_n_column_is_shown_but_not_editable(self):
        self.login(Role.ADMIN)
        body = self.client.get(reverse("equipment:list")).content.decode()
        self.assertIn("41415452WS", body)
        self.assertNotIn("data-inline", body)
        self.assertNotIn("cell-pencil", body)

    def test_there_is_no_way_to_save_from_the_list(self):
        with self.assertRaises(NoReverseMatch):
            reverse("equipment:inline_edit", args=[self.other.pk])

    def test_filter_for_missing_serial_numbers(self):
        self.login(Role.VIEWER)
        body = self.client.get(reverse("equipment:list") + "?serial=missing").content.decode()
        self.assertIn(self.equipment.code, body)
        self.assertNotIn("70-000005", body)
