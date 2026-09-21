"""Adding a set and filling it in with search boxes — within a technician's reach."""

from django.test import TestCase
from django.urls import reverse

from core.models import Product, Role
from systems.models import Installation, TestSet
from systems.tests import Fixture


class SetFillingTests(Fixture, TestCase):
    hx = {"HTTP_HX_REQUEST": "true"}

    def setUp(self):
        self.step = self.make_step()
        self.set1 = TestSet.objects.create(product_process=self.step, number=1, line=self.room)

    def test_a_technician_adds_a_set_and_lands_on_its_tab(self):
        self.login(Role.TECHNICIAN)
        response = self.client.post(reverse("systems:set_add", args=[self.step.pk]), **self.hx)
        new = TestSet.objects.get(product_process=self.step, number=2)
        url = reverse("systems:products") + f"?process={self.step.pk}&tab={new.pk}"
        self.assertEqual(response["HX-Redirect"], url)
        page = self.client.get(url).content.decode()
        self.assertIn("Machine in set #2", page)
        self.assertIn("data-picker", page)
        self.assertIn(f"category={self.cart_cat.pk}", page)        # each box offers its own kind
        self.assertNotIn('name="roles-0-category"', page)          # a technician does not retype roles

    def test_a_viewer_cannot_add_a_set(self):
        self.login(Role.VIEWER)
        self.client.post(reverse("systems:set_add", args=[self.step.pk]), **self.hx)
        self.assertFalse(TestSet.objects.filter(product_process=self.step, number=2).exists())

    def test_search_offers_only_the_role_s_kind_and_marks_busy_machines(self):
        Installation.fit(self.dmm1, self.set1, self.role(self.set1, "DMM"), self.users[Role.MANAGER])
        set2 = TestSet.objects.create(product_process=self.step, number=2)
        self.login(Role.TECHNICIAN)
        rows = self.client.get(reverse("equipment:search"),
                               {"category": self.dmm_cat.pk, "set": set2.pk}).json()["results"]
        codes = [r["code"] for r in rows]
        self.assertEqual(sorted(codes), ["DMM-001", "DMM-002"])        # multimeters only
        self.assertEqual(codes[0], "DMM-002")                           # the free one first
        busy = {r["code"]: r["busy"] for r in rows}
        self.assertIn("#1", busy["DMM-001"])
        self.assertEqual(busy["DMM-002"], "")

    def test_search_finds_a_machine_by_asset_no_or_serial(self):
        self.dmm2.asset_no, self.dmm2.serial_number = "103220100359", "41415453WS"
        self.dmm2.save()
        self.login(Role.TECHNICIAN)
        for typed in ("1032201003", "41415453"):
            rows = self.client.get(reverse("equipment:search"), {"q": typed}).json()["results"]
            self.assertEqual([r["code"] for r in rows], ["DMM-002"])

    def test_a_technician_saves_the_set(self):
        self.login(Role.TECHNICIAN)
        role = self.role(self.set1, "DMM")
        self.client.post(reverse("systems:set_edit", args=[self.set1.pk]),
                         {"line": self.room.pk, f"role_{role.pk}": self.dmm2.pk}, **self.hx)
        self.assertTrue(self.set1.open_installations().filter(component=self.dmm2).exists())

    def test_a_product_needs_no_name(self):
        self.login(Role.MANAGER)
        self.client.post(reverse("systems:product_create"),
                         {"code": "BAF1950", "customer": self.baf.pk, "is_active": "on"}, **self.hx)
        product = Product.objects.get(code="BAF1950")
        self.assertEqual(product.name, "")
        panel = self.client.get(reverse("systems:product_panel", args=[product.pk]), **self.hx).content.decode()
        self.assertNotIn("BAF · ", panel)


class OneFrameTests(Fixture, TestCase):
    """Roles and the machines in them, chosen together in the process frame."""

    hx = {"HTTP_HX_REQUEST": "true"}

    def setUp(self):
        self.step = self.make_step()
        self.set1 = TestSet.objects.create(product_process=self.step, number=1, line=self.room)
        self.set2 = TestSet.objects.create(product_process=self.step, number=2)

    def frame_data(self, rows, extra=None):
        """rows: [(role or None, category, asset or None, required, delete)]"""
        data = {
            "roles-TOTAL_FORMS": str(len(rows)), "roles-INITIAL_FORMS": str(sum(1 for r in rows if r[0])),
            "roles-MIN_NUM_FORMS": "0", "roles-MAX_NUM_FORMS": "1000", "set-line": self.room.pk,
        }
        for i, (role, category, asset, required, delete) in enumerate(rows):
            if role:
                data[f"roles-{i}-id"] = role.pk
            data[f"roles-{i}-category"] = category.pk
            data[f"roles-{i}-equipment"] = asset.pk if asset else ""
            if required:
                data[f"roles-{i}-is_required"] = "on"
            if delete:
                data[f"roles-{i}-DELETE"] = "on"
        data.update(extra or {})
        return data

    def existing_rows(self, **assets):
        return [(r, r.category, assets.get(r.category.code), True, False) for r in self.step.roles.all()]

    def save(self, rows, tab=None):
        url = reverse("systems:process_setup", args=[self.step.pk]) + (f"?tab={tab.pk}" if tab else "")
        return self.client.post(url, self.frame_data(rows), **self.hx)

    def test_a_manager_adds_a_role_and_its_machine_in_one_save(self):
        from core.models import Category
        from equipment.models import Equipment
        psu_cat = Category.objects.create(code="PSU", name="Power supply")
        psu = Equipment.objects.create(code="PSU-001", name="Bench PSU", category=psu_cat, location=self.room)
        self.login(Role.MANAGER)
        rows = self.existing_rows(DMM=self.dmm1) + [(None, psu_cat, psu, True, False)]
        response = self.save(rows, tab=self.set1)
        self.assertEqual(response.status_code, 204)
        new_role = self.step.roles.get(category=psu_cat)
        fitted = {i.role_id: i.component for i in self.set1.open_installations()}
        self.assertEqual(fitted[new_role.pk], psu)
        self.assertEqual(fitted[self.role(self.set1, "DMM").pk], self.dmm1)

    def test_the_tab_decides_which_set_gets_the_machines(self):
        self.login(Role.TECHNICIAN)
        self.save(self.existing_rows(DMM=self.dmm2), tab=self.set2)
        self.assertTrue(self.set2.open_installations().filter(component=self.dmm2).exists())
        self.assertFalse(self.set1.open_installations().exists())
        page = self.client.get(reverse("systems:process_panel", args=[self.step.pk]) + f"?tab={self.set2.pk}", **self.hx).content.decode()
        self.assertIn("DMM-002", page)
        self.assertIn("Machine in set #2", page)

    def test_a_technician_cannot_change_the_roles(self):
        self.login(Role.TECHNICIAN)
        rows = [(r, self.fix_cat, None, True, True) for r in self.step.roles.all()]   # try to retype and delete
        self.save(rows, tab=self.set1)
        self.assertEqual(
            sorted(self.step.roles.values_list("category__code", flat=True)), ["CART", "DMM", "FIX"],
        )

    def test_removing_a_role_frees_its_machine(self):
        dmm_role = self.role(self.set1, "DMM")
        Installation.fit(self.dmm1, self.set1, dmm_role, self.users[Role.MANAGER])
        self.login(Role.MANAGER)
        rows = [(r, r.category, self.dmm1 if r == dmm_role else None, True, r == dmm_role)
                for r in self.step.roles.all()]
        self.save(rows, tab=self.set1)
        self.assertFalse(self.step.roles.filter(pk=dmm_role.pk).exists())
        self.assertFalse(Installation.objects.filter(component=self.dmm1, removed_at__isnull=True).exists())

    def test_one_machine_in_two_roles_is_refused_in_the_frame(self):
        from core.models import Category
        self.login(Role.MANAGER)
        rows = self.existing_rows(DMM=self.dmm1) + [(None, self.dmm_cat, self.dmm1, True, False)]
        response = self.save(rows, tab=self.set1)
        self.assertContains(response, "The same asset is chosen for two roles")
        self.assertFalse(self.set1.open_installations().exists())
