"""In production means fitted to a set of a product that is in production."""

from django.test import TestCase
from django.urls import reverse

from core.models import Role
from equipment.models import EquipmentStatus as S
from systems.models import Installation
from systems.tests import Fixture


class ProductionStatusTests(Fixture, TestCase):
    def fit(self, asset, product, label="DMM"):
        test_set = self.make_set(self.make_step(product=product))
        return Installation.fit(asset, test_set, self.role(test_set, label), self.users[Role.MANAGER])

    def status(self, asset):
        asset.refresh_from_db()
        return asset.status

    def test_fitting_to_a_running_product_puts_it_in_production(self):
        self.fit(self.dmm1, self.rmmtt01)
        self.assertEqual(self.status(self.dmm1), S.IN_PRODUCTION)
        entry = self.dmm1.status_history.first()
        self.assertIn("which is in production", entry.reason)

    def test_fitting_to_an_idle_product_changes_nothing(self):
        self.fit(self.dmm1, self.baf0850)
        self.assertEqual(self.status(self.dmm1), S.AVAILABLE)

    def test_removing_it_makes_it_available_again(self):
        fitting = self.fit(self.dmm1, self.rmmtt01)
        fitting.release(self.users[Role.MANAGER])
        self.assertEqual(self.status(self.dmm1), S.AVAILABLE)

    def test_stopping_and_starting_the_product_moves_its_equipment(self):
        self.fit(self.dmm1, self.rmmtt01)
        self.login(Role.MANAGER)
        self.client.post(reverse("systems:product_toggle", args=[self.rmmtt01.pk]))
        self.assertEqual(self.status(self.dmm1), S.AVAILABLE)
        self.client.post(reverse("systems:product_toggle", args=[self.rmmtt01.pk]))
        self.assertEqual(self.status(self.dmm1), S.IN_PRODUCTION)
        self.assertEqual(self.dmm1.status_history.first().changed_by, self.users[Role.MANAGER])

    def test_a_person_s_status_is_not_overridden(self):
        self.dmm1.change_status(S.REPAIR, None)
        self.fit(self.dmm1, self.rmmtt01)
        self.assertEqual(self.status(self.dmm1), S.REPAIR)

    def test_back_from_repair_while_fitted_means_back_in_production(self):
        self.fit(self.dmm1, self.rmmtt01)
        self.dmm1.refresh_from_db()
        self.dmm1.change_status(S.REPAIR, None)
        self.login(Role.TECHNICIAN)
        self.client.post(reverse("equipment:status_change", args=[self.dmm1.pk]), {"status": S.AVAILABLE})
        self.assertEqual(self.status(self.dmm1), S.IN_PRODUCTION)

    def test_in_production_is_not_offered_to_a_loose_asset(self):
        self.login(Role.TECHNICIAN)
        body = self.client.get(reverse("equipment:status_change", args=[self.dmm2.pk])).content.decode()
        self.assertNotIn('value="IN_PRODUCTION"', body)
        self.client.post(reverse("equipment:status_change", args=[self.dmm2.pk]), {"status": S.IN_PRODUCTION})
        self.assertEqual(self.status(self.dmm2), S.AVAILABLE)
