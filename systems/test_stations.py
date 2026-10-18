"""Stations: machines every model run there shares, and slots each model fills itself."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from calibration.models import CalibrationPlan
from core.models import Category, Product, Role, User
from equipment.models import Equipment, EquipmentStatus
from systems.models import Installation, ProductProcess, Station, StationSlot, SystemType, TestSet
from systems.services import apply_set_changes, evaluate_set, products_overview

PASSWORD = "test-pass-2026"


class StationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user(username="mgr", password=PASSWORD, full_name="Mai Le", role=Role.MANAGER)
        cls.fct = SystemType.objects.create(code="FCT", name="Functional test")
        cls.ict = SystemType.objects.create(code="ICT", name="In-circuit test")
        cats = {code: Category.objects.create(code=code, name=code) for code in ("PC", "DMM", "FIX")}
        cls.fix_cat = cats["FIX"]
        cls.pc = Equipment.objects.create(code="70-000001", name="Test PC", category=cats["PC"])
        cls.dmm = Equipment.objects.create(code="70-000002", name="DMM", category=cats["DMM"])
        cls.fix_a = Equipment.objects.create(code="70-000003", name="Fixture A", category=cats["FIX"])
        cls.fix_b = Equipment.objects.create(code="70-000004", name="Fixture B", category=cats["FIX"])
        cls.steps = {}
        for code in ("KMCM104", "KMCM108"):
            product = Product.objects.create(code=code)
            cls.steps[code] = ProductProcess.objects.create(product=product, process=cls.fct)

    def setUp(self):
        self.station = Station.objects.create(code="BAF-FCT-01", process=self.fct)
        self.slot = StationSlot.objects.create(station=self.station, category=self.fix_cat, position=1)
        self.station.set_equipment([self.pc, self.dmm], self.manager)
        self.sets = {}
        for code, fixture in (("KMCM104", self.fix_a), ("KMCM108", self.fix_b)):
            test_set = TestSet.objects.create(product_process=self.steps[code], number=1, station=self.station)
            Installation.fit(fixture, test_set, self.slot, self.manager)
            self.sets[code] = test_set

    def lines(self, test_set):
        return {line.role.name: line for line in evaluate_set(test_set).lines}

    def test_a_model_is_ready_with_the_shared_machines_and_its_own_fixture(self):
        for code, fixture in (("KMCM104", self.fix_a), ("KMCM108", self.fix_b)):
            self.assertTrue(evaluate_set(self.sets[code]).is_ready, code)
            lines = self.lines(self.sets[code])
            self.assertEqual(lines["PC"].equipment, self.pc)
            self.assertTrue(lines["PC"].from_station)
            self.assertEqual(lines["FIX"].equipment, fixture)
            self.assertFalse(lines["FIX"].from_station)

    def test_an_empty_required_slot_means_not_ready(self):
        newcomer = ProductProcess.objects.create(product=Product.objects.create(code="KMCM111"), process=self.fct)
        test_set = TestSet.objects.create(product_process=newcomer, number=1, station=self.station)
        readiness = evaluate_set(test_set)
        self.assertFalse(readiness.is_ready)
        self.assertEqual(readiness.blocking[0].role.name, "FIX")

    def test_shared_equipment_is_used_for_every_product_on_the_station(self):
        self.assertEqual(self.pc.product_codes, ["KMCM104", "KMCM108"])
        self.assertEqual(self.fix_a.product_codes, ["KMCM104"])

    def test_any_overdue_shared_machine_stops_every_model_on_the_station(self):
        CalibrationPlan.objects.create(
            equipment=self.dmm, name="Calibration", interval_months=12,
            next_due_at=timezone.localdate() - timedelta(days=3),
        )
        groups = products_overview(show_all=True)
        readiness = [entry["readiness"] for g in groups for p in g.products for s in p["steps"] for entry in s["sets"]]
        self.assertEqual(len(readiness), 2)
        self.assertTrue(all(not r.is_ready for r in readiness))
        self.assertTrue(all(r.blocking[0].role.name == "DMM" for r in readiness))

    def test_swapping_a_fixture_in_its_slot(self):
        spare = Equipment.objects.create(code="70-000009", name="Fixture C", category=self.fix_cat)
        test_set = self.sets["KMCM104"]
        apply_set_changes(test_set, {self.slot.pk: spare}, self.manager)
        self.assertEqual(self.lines(test_set)["FIX"].equipment, spare)
        self.assertFalse(Installation.objects.filter(component=self.fix_a, removed_at__isnull=True).exists())

    def test_a_machine_is_at_one_place_only(self):
        with self.assertRaises(ValidationError):
            Installation.fit(self.pc, self.sets["KMCM104"], self.slot, self.manager)     # shared already
        other = Station.objects.create(code="BAF-FCT-02", process=self.fct)
        with self.assertRaises(ValidationError):
            other.set_equipment([self.fix_a], self.manager)

    def test_running_a_product_leaves_the_status_alone(self):
        # Status is set by hand now (In use / Spare / Broken), never by the line.
        product = self.sets["KMCM104"].product
        product.in_production = True
        product.save(user=self.manager)
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.status, EquipmentStatus.IN_USE)

    def slot_data(self, *rows, initial=0):
        data = {"slots-TOTAL_FORMS": str(len(rows)), "slots-INITIAL_FORMS": str(initial),
                "slots-MIN_NUM_FORMS": "0", "slots-MAX_NUM_FORMS": "1000"}
        for index, row in enumerate(rows):
            data.update({f"slots-{index}-{key}": value for key, value in row.items()})
        return data

    def test_station_form_saves_machines_and_slots(self):
        self.client.login(username="mgr", password=PASSWORD)
        listing = self.client.get(reverse("systems:stations"))
        self.assertContains(listing, "BAF-FCT-01")
        self.assertContains(listing, "70-000001")
        data = {"code": "baf-fct-02", "process": self.fct.pk, "asset": [""]}
        data.update(self.slot_data({"category": self.fix_cat.pk, "is_required": "on"}))
        response = self.client.post(reverse("systems:station_create"), data)
        created = Station.objects.get(code="BAF-FCT-02")
        self.assertRedirects(response, reverse("systems:station_detail", args=[created.pk]), fetch_redirect_response=False)
        self.assertEqual(list(created.slots.values_list("category__code", flat=True)), ["FIX"])
        # Take the DMM off BAF-FCT-01, keep its slot.
        data = {"code": "BAF-FCT-01", "process": self.fct.pk, "asset": [str(self.pc.pk), ""]}
        data.update(self.slot_data({"id": self.slot.pk, "category": self.fix_cat.pk, "is_required": "on"}, initial=1))
        self.client.post(reverse("systems:station_edit", args=[self.station.pk]), data)
        held = list(self.station.open_installations().values_list("component_id", flat=True))
        self.assertEqual(held, [self.pc.pk])
        self.assertTrue(self.station.slots.exists())

    def test_removing_a_slot_frees_the_fixtures_in_it(self):
        self.client.login(username="mgr", password=PASSWORD)
        data = {"code": "BAF-FCT-01", "process": self.fct.pk, "asset": [str(self.pc.pk), str(self.dmm.pk)]}
        data.update(self.slot_data({"id": self.slot.pk, "category": self.fix_cat.pk, "DELETE": "on"}, initial=1))
        self.client.post(reverse("systems:station_edit", args=[self.station.pk]), data)
        self.assertFalse(self.station.slots.exists())
        self.assertFalse(Installation.objects.filter(component=self.fix_a, removed_at__isnull=True).exists())

    def test_the_model_editor_has_one_box_per_slot(self):
        self.client.login(username="mgr", password=PASSWORD)
        test_set = self.sets["KMCM104"]
        url = reverse("systems:station_model_edit", args=[self.station.pk, test_set.pk])
        body = self.client.get(url).content.decode()
        self.assertIn(f'name="slot_{self.slot.pk}"', body)
        self.assertIn("70-000003", body)              # the model's own fixture
        self.assertIn("70-000001", body)              # the shared PC, listed for reference
        spare = Equipment.objects.create(code="70-000010", name="Fixture D", category=self.fix_cat)
        response = self.client.post(url, {f"slot_{self.slot.pk}": spare.pk})
        self.assertRedirects(response, reverse("systems:station_detail", args=[self.station.pk]), fetch_redirect_response=False)
        self.assertEqual(self.lines(test_set)["FIX"].equipment, spare)

    def test_add_a_model_from_the_station(self):
        """A new product with its fixture, in one dialog: its FCT step and set are made, on this station."""
        self.client.login(username="mgr", password=PASSWORD)
        newcomer = Product.objects.create(code="KMCM111")
        fixture = Equipment.objects.create(code="70-000020", name="Fixture C", category=self.fix_cat)
        url = reverse("systems:station_add_model", args=[self.station.pk])
        dialog = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("KMCM111", dialog)                                 # offered
        self.assertIn(f'name="slot_{self.slot.pk}"', dialog)             # its fixture is chosen right here
        response = self.client.post(url, {"product": newcomer.pk, f"slot_{self.slot.pk}": fixture.pk},
                                    HTTP_HX_REQUEST="true")
        self.assertEqual(response.json()["reload"], True)
        test_set = TestSet.objects.get(product_process__product=newcomer)
        self.assertEqual([i.component for i in test_set.open_installations()], [fixture])
        self.assertEqual(test_set.station, self.station)
        self.assertEqual(test_set.product_process.process, self.fct)
        self.assertIn("KMCM111", self.pc.product_codes)

    def test_an_existing_set_joins_the_station_instead_of_a_new_one(self):
        self.client.login(username="mgr", password=PASSWORD)
        loose = self.sets["KMCM104"]
        loose.station = None
        loose.save()
        self.client.post(reverse("systems:station_add_model", args=[self.station.pk]), {"product": loose.product.pk})
        loose.refresh_from_db()
        self.assertEqual(loose.station, self.station)
        self.assertEqual(loose.product_process.sets.count(), 1)

    def test_detail_page_lists_models_and_removing_one_keeps_its_fixture(self):
        self.client.login(username="mgr", password=PASSWORD)
        body = self.client.get(reverse("systems:station_detail", args=[self.station.pk])).content.decode()
        for text in ("KMCM104", "KMCM108", "70-000003", "70-000004", "Ready"):
            self.assertIn(text, body)
        test_set = self.sets["KMCM108"]
        self.client.post(reverse("systems:station_remove_model", args=[self.station.pk, test_set.pk]))
        test_set.refresh_from_db()
        self.assertIsNone(test_set.station)
        self.assertEqual(test_set.open_installations().get().component, self.fix_b)
        self.assertEqual(self.pc.product_codes, ["KMCM104"])

    def test_only_managers_add_or_remove_models(self):
        User.objects.create_user(username="tech", password=PASSWORD, full_name="Tu Tran", role=Role.TECHNICIAN)
        self.client.login(username="tech", password=PASSWORD)
        newcomer = Product.objects.create(code="KMCM200")
        self.client.post(reverse("systems:station_add_model", args=[self.station.pk]), {"product": newcomer.pk})
        self.assertFalse(TestSet.objects.filter(product_process__product=newcomer).exists())

    def test_list_rows_open_a_preview_and_the_preview_names_the_machines(self):
        self.client.login(username="mgr", password=PASSWORD)
        url = reverse("systems:station_preview", args=[self.station.pk])
        self.assertContains(self.client.get(reverse("systems:stations")), f'data-preview-url="{url}"')
        drawer = self.client.get(url, HTTP_HX_REQUEST="true")
        for text in ("BAF-FCT-01", "70-000001", "TEST PC", "KMCM104", "KMCM108", "Open"):
            self.assertContains(drawer, text)
        self.assertRedirects(self.client.get(url), reverse("systems:station_detail", args=[self.station.pk]))

    def test_detail_shows_what_tells_a_machine_apart(self):
        self.pc.serial_number = "SN-PC-77"
        self.pc.equipment_no = "TEPC-001"
        self.pc.save()
        self.client.login(username="mgr", password=PASSWORD)
        body = self.client.get(reverse("systems:station_detail", args=[self.station.pk])).content.decode()
        for text in ("SN-PC-77", "TEPC-001", 'class="machine-photo', "FIXTURE A"):
            self.assertIn(text, body)

    def test_the_products_page_no_longer_declares_roles(self):
        self.client.login(username="mgr", password=PASSWORD)
        step = self.steps["KMCM104"]
        panel = self.client.get(reverse("systems:process_panel", args=[step.pk]), HTTP_HX_REQUEST="true").content.decode()
        self.assertNotIn("roles-TOTAL_FORMS", panel)
        self.assertIn("BAF-FCT-01", panel)

    def test_station_list_filters_by_customer_process_line_and_search(self):
        from core.models import Customer, Location

        baf = Customer.objects.create(code="BAF", name="BAF")
        line2 = Location.objects.create(code="L2", name="Line 2")
        self.station.customer, self.station.line = baf, line2
        self.station.save()
        Station.objects.create(code="RHEEM-ICT-01", process=self.ict)
        self.client.login(username="mgr", password=PASSWORD)
        url = reverse("systems:stations")
        page = self.client.get(url).content.decode()
        self.assertIn('<select name="customer" form="list-filter"', page)
        self.assertIn('<select name="process" form="list-filter"', page)
        for params, expected, absent in (
            ({"customer": baf.pk}, "BAF-FCT-01", "RHEEM-ICT-01"),
            ({"process": self.ict.pk}, "RHEEM-ICT-01", "BAF-FCT-01"),
            ({"line": line2.pk}, "BAF-FCT-01", "RHEEM-ICT-01"),
            ({"q": "70-000001"}, "BAF-FCT-01", "RHEEM-ICT-01"),       # by a machine on it
            ({"q": "kmcm108"}, "BAF-FCT-01", "RHEEM-ICT-01"),         # by a model run on it
        ):
            with self.subTest(params=params):
                body = self.client.get(url, params).content.decode()
                self.assertIn(expected, body)
                self.assertNotIn(f">{absent}<", body)

    def test_a_customer_station_offers_only_that_customer_s_models(self):
        from core.models import Customer

        baf, rheem = Customer.objects.create(code="BAF", name="BAF"), Customer.objects.create(code="RHEEM", name="Rheem")
        Product.objects.create(code="BAF9999", customer=baf)
        Product.objects.create(code="RMM9999", customer=rheem)
        self.station.customer = baf
        self.station.save()
        self.client.login(username="mgr", password=PASSWORD)
        body = self.client.get(reverse("systems:station_add_model", args=[self.station.pk]),
                               HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("BAF9999", body)
        self.assertNotIn("RMM9999", body)

    def test_the_model_panel_shows_each_process_s_station_fixture_and_golden_samples(self):
        from systems.models import GoldenSample

        step = self.steps["KMCM104"]
        GoldenSample.objects.create(product_process=step, code="GS-OK-01")
        self.client.login(username="mgr", password=PASSWORD)
        panel = self.client.get(reverse("systems:product_panel", args=[step.product.pk]), HTTP_HX_REQUEST="true").content.decode()
        for text in ("FCT", "BAF-FCT-01", "70-000003", "FIXTURE A", "Ready", "GS-OK-01", "OK 1/1"):
            self.assertIn(text, panel)


class StationDialogTests(TestCase):
    """The station form opens in a dialog like the asset form, with as many shared machines as wanted."""

    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user(username="mgr", password=PASSWORD, full_name="Mai Le", role=Role.MANAGER)
        cls.fct = SystemType.objects.create(code="FCT", name="Functional test")
        kind = Category.objects.create(code="PSU", name="Power supply")
        cls.assets = [Equipment.objects.create(equipment_no=f"PSU-000{n}", name=f"PSU {n}", category=kind)
                      for n in range(1, 6)]
        cls.station = Station.objects.create(code="BAF-FCT-01", process=cls.fct)

    def post(self, url, assets, **extra):
        data = {"code": "BAF-FCT-01", "process": self.fct.pk,
                "slots-TOTAL_FORMS": "0", "slots-INITIAL_FORMS": "0", "slots-MIN_NUM_FORMS": "0",
                "slots-MAX_NUM_FORMS": "1000", "asset": [str(a.pk) for a in assets]}
        return self.client.post(url, data, **extra)

    def test_edit_opens_as_a_dialog_with_add_and_remove(self):
        self.client.login(username="mgr", password=PASSWORD)
        url = reverse("systems:station_edit", args=[self.station.pk])
        fragment = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        self.assertNotIn("<html", fragment)
        self.assertIn("Edit station", fragment)
        self.assertIn('data-row-add="station-assets"', fragment)
        self.assertIn('id="station-assets-empty"', fragment)
        page = self.client.get(reverse("systems:station_detail", args=[self.station.pk])).content.decode()
        self.assertIn(f'data-modal-form="{url}"', page)

    def test_any_number_of_shared_machines_and_taking_them_out(self):
        self.client.login(username="mgr", password=PASSWORD)
        url = reverse("systems:station_edit", args=[self.station.pk])
        response = self.post(url, self.assets, HTTP_HX_REQUEST="true")
        self.assertEqual(response.json()["reload"], True)
        self.assertEqual(self.station.open_installations().count(), 5)
        self.post(url, self.assets[:2], HTTP_HX_REQUEST="true")
        self.assertEqual(sorted(i.component.equipment_no for i in self.station.open_installations()),
                         ["PSU-0001", "PSU-0002"])


class StationCapitalsTests(TestCase):
    def test_code_and_notes_are_kept_in_capitals(self):
        station = Station.objects.create(code=" baf-fct-03 ", notes="spare  bench",
                                         process=SystemType.objects.create(code="FCT", name="Functional test"))
        station.refresh_from_db()
        self.assertEqual((station.code, station.notes), ("BAF-FCT-03", "SPARE BENCH"))


class RunningModelTests(TestCase):
    """A station runs one model at a time: its own machines are the mounted ones; a changeover is logged."""

    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user(username="mgr", password=PASSWORD, full_name="Mai Le", role=Role.MANAGER)
        cls.tech = User.objects.create_user(username="tech", password=PASSWORD, full_name="Khanh Pham", role=Role.TECHNICIAN)
        cls.fct = SystemType.objects.create(code="FCT", name="Functional test")
        cls.fix_cat = Category.objects.create(code="FX", name="Fixture")
        cls.fixtures = {code: Equipment.objects.create(equipment_no=f"FX-{n:04d}", name=f"{code} fixture",
                                                       category=cls.fix_cat)
                        for n, code in enumerate(("BAF7350", "BAF6450"), start=1)}
        cls.products = {code: Product.objects.create(code=code) for code in cls.fixtures}

    def setUp(self):
        self.station = Station.objects.create(code="BAF-FCT-01", process=self.fct)
        self.slot = StationSlot.objects.create(station=self.station, category=self.fix_cat)
        self.client.login(username="mgr", password=PASSWORD)
        for code, fixture in self.fixtures.items():
            self.client.post(reverse("systems:station_add_model", args=[self.station.pk]),
                             {"product": self.products[code].pk, f"slot_{self.slot.pk}": fixture.pk})
        self.station.refresh_from_db()
        self.sets = {s.product.code: s for s in self.station.test_sets.all()}

    def test_the_first_model_added_is_the_one_running(self):
        self.assertEqual(self.station.running_set, self.sets["BAF7350"])
        self.assertTrue(self.sets["BAF7350"].is_running)
        self.assertFalse(self.sets["BAF6450"].is_running)

    def test_only_the_running_model_s_fixture_shows_as_mounted(self):
        body = self.client.get(reverse("systems:station_detail", args=[self.station.pk])).content.decode()
        now = body.split("On the station now")[1].split("Models and their own machines")[0]
        self.assertIn("FX-0001", now)                     # BAF7350's fixture: on the station
        self.assertNotIn("FX-0002", now)                  # BAF6450's: kept aside
        self.assertIn("Kept aside", body)
        self.assertIn("(mounted)", self.fixtures["BAF7350"].current_installation.where)
        self.assertIn("(kept aside)", self.fixtures["BAF6450"].current_installation.where)

    def test_a_changeover_swaps_the_mounted_fixture_and_is_logged(self):
        self.client.login(username="tech", password=PASSWORD)
        self.client.post(reverse("systems:station_changeover", args=[self.station.pk, self.sets["BAF6450"].pk]))
        self.station.refresh_from_db()
        self.assertEqual(self.station.running_set, self.sets["BAF6450"])
        entry = self.station.changeovers.first()
        self.assertEqual((entry.from_label, entry.to_label), (str(self.sets["BAF7350"]), str(self.sets["BAF6450"])))
        self.assertEqual(entry.changed_by.username, "tech")
        body = self.client.get(reverse("systems:station_detail", args=[self.station.pk])).content.decode()
        now = body.split("On the station now")[1].split("Models and their own machines")[0]
        self.assertIn("FX-0002", now)
        self.assertNotIn("FX-0001", now)

    def test_taking_the_running_model_off_leaves_none_running(self):
        self.client.post(reverse("systems:station_remove_model", args=[self.station.pk, self.sets["BAF7350"].pk]))
        self.station.refresh_from_db()
        self.assertIsNone(self.station.running_set)
        self.assertEqual(self.station.changeovers.first().to_label, "")

    def test_the_model_s_machines_are_edited_in_a_dialog(self):
        url = reverse("systems:station_model_edit", args=[self.station.pk, self.sets["BAF6450"].pk])
        fragment = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        self.assertNotIn("<html", fragment)
        self.assertIn("BAF6450", fragment)


class StationFormModelsTests(TestCase):
    """The station form also adds models, chooses their own machines and the running one, in one save."""

    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user(username="mgr", password=PASSWORD, full_name="Mai Le", role=Role.MANAGER)
        cls.fct = SystemType.objects.create(code="FCT", name="Functional test")
        cls.fix_cat = Category.objects.create(code="FX", name="Fixture")
        cls.fixture = Equipment.objects.create(equipment_no="FX-0001", name="SHARED FIXTURE", category=cls.fix_cat)
        cls.products = [Product.objects.create(code=c) for c in ("BAF7350", "BAF6450")]

    def setUp(self):
        self.station = Station.objects.create(code="BAF-FCT-01", process=self.fct)
        self.slot = StationSlot.objects.create(station=self.station, category=self.fix_cat)
        self.client.login(username="mgr", password=PASSWORD)
        self.url = reverse("systems:station_edit", args=[self.station.pk])

    def post(self, **extra):
        data = {"code": "BAF-FCT-01", "process": self.fct.pk,
                "slots-TOTAL_FORMS": "1", "slots-INITIAL_FORMS": "1", "slots-MIN_NUM_FORMS": "0",
                "slots-MAX_NUM_FORMS": "1000", "slots-0-id": self.slot.pk, "slots-0-category": self.fix_cat.pk,
                "slots-0-is_required": "on"}
        data.update(extra)
        return self.client.post(self.url, data, HTTP_HX_REQUEST="true")

    def test_the_form_offers_models_with_their_machines(self):
        body = self.client.get(self.url, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("Models and their own machines", body)
        self.assertIn('id="station-models-empty"', body)
        self.assertIn(f'name="new___n___slot_{self.slot.pk}"', body)
        self.assertIn(f"models_of={self.station.pk}", body)

    def test_two_models_added_sharing_one_fixture_and_one_running(self):
        a, b = self.products
        slot = f"_slot_{self.slot.pk}"
        response = self.post(**{"new_n1_product": a.pk, f"new_n1{slot}": self.fixture.pk,
                                "new_n2_product": b.pk, f"new_n2{slot}": self.fixture.pk, "running": "new_n2"})
        self.assertEqual(response.json()["reload"], True)
        self.station.refresh_from_db()
        self.assertEqual(self.station.test_sets.count(), 2)
        self.assertEqual(self.station.running_set.product.code, "BAF6450")
        self.assertEqual(len(self.fixture.open_fittings_now), 2)          # one fixture, both models
        self.assertIn("(mounted)", self.fixture.where_fitted)

    def test_existing_models_change_machines_switch_and_come_off(self):
        a, b = self.products
        slot = f"_slot_{self.slot.pk}"
        self.post(**{"new_n1_product": a.pk, "new_n2_product": b.pk})
        sets = {s.product.code: s for s in self.station.test_sets.all()}
        self.post(**{f"set_{sets['BAF7350'].pk}{slot}": self.fixture.pk, f"set_{sets['BAF6450'].pk}{slot}": "",
                     "running": str(sets["BAF6450"].pk), f"set_{sets['BAF7350'].pk}_remove": ""})
        self.station.refresh_from_db()
        self.assertEqual(self.station.running_set, sets["BAF6450"])
        self.assertEqual([f.test_set for f in self.fixture.open_fittings_now], [sets["BAF7350"]])
        self.post(**{f"set_{sets['BAF6450'].pk}_remove": "on", "running": str(sets["BAF6450"].pk)})
        self.station.refresh_from_db()
        self.assertEqual(self.station.test_sets.count(), 1)
        self.assertEqual(self.station.running_set, sets["BAF7350"])     # the one left runs

    def test_a_new_station_goes_straight_on_to_its_models(self):
        response = self.client.post(reverse("systems:station_create"), {
            "code": "baf-fct-02", "process": self.fct.pk,
            "slots-TOTAL_FORMS": "1", "slots-INITIAL_FORMS": "0", "slots-MIN_NUM_FORMS": "0",
            "slots-MAX_NUM_FORMS": "1000", "slots-0-category": self.fix_cat.pk, "slots-0-is_required": "on",
        }, HTTP_HX_REQUEST="true")
        body = response.content.decode()
        created = Station.objects.get(code="BAF-FCT-02")
        self.assertIn("Now add its models", body)
        self.assertIn(f'action="{reverse("systems:station_edit", args=[created.pk])}"', body)
        self.assertIn("Models and their own machines", body)
