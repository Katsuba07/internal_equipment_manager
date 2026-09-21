"""The Computime register import takes Test Engineering's assets only, with no location."""

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from equipment.models import Equipment


def row(code, department, plant="CTV2", asset_no="", serial="", equipment_no=""):
    return {
        "zt_code": code, "asset_no": asset_no, "serial_no": serial, "equipment_no": equipment_no,
        "name": f"Asset {code}", "category": "Machine",
        "department": department, "manufacturer": plant, "status": "In Service",
        "pm_interval": "12 Months", "photos": [],
    }


class ComputimeImportTests(TestCase):
    def run_import(self, rows, *args):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "assets.json").write_text(json.dumps(rows), encoding="utf-8")
            out = StringIO()
            call_command("import_computime", "--source", folder, "--commit", *args, stdout=out)
            return out.getvalue()

    def test_only_test_engineering_by_default(self):
        self.run_import([row("70-1", "TE"), row("70-2", "ME"), row("70-3", "QC"), row("70-4", "te")])
        self.assertEqual(sorted(Equipment.objects.values_list("code", flat=True)), ["70-1", "70-4"])

    def test_location_left_empty_plant_kept(self):
        self.run_import([row("70-1", "TE", plant="CTV1")])
        asset = Equipment.objects.get(code="70-1")
        self.assertIsNone(asset.location)
        self.assertEqual(asset.plant, "CTV1")
        self.assertEqual(asset.manufacturer, "")      # CTV1 was the plant, not the maker

    def test_the_warehouse_spelling_still_gives_the_plant(self):
        self.run_import([row("70-1", "TE", plant="CTV2 WH")])
        asset = Equipment.objects.get(code="70-1")
        self.assertEqual(asset.plant, "CTV2")
        self.assertEqual(asset.manufacturer, "")

    def test_three_identifiers_land_in_their_own_fields(self):
        self.run_import([
            row("70-1", "TE", asset_no="103220100359", serial="41415453WS", equipment_no="CTV20200073"),
            row("70-2", "TE", asset_no="GET190523"),          # a serial typed into the wrong box
            row("70-3", "TE", equipment_no="VOM#010"),        # not the internal format
        ])
        a = Equipment.objects.get(code="CTV20200073")
        self.assertEqual((a.asset_no, a.serial_number), ("103220100359", "41415453WS"))
        self.assertIn("Computime ZT code: 70-1", a.notes)
        b = Equipment.objects.get(code="70-2")
        self.assertEqual(b.asset_no, "")
        self.assertTrue(Equipment.objects.filter(code="70-3").exists())

    def test_running_again_finds_the_same_asset(self):
        rows = [row("70-1", "TE", asset_no="103220100359", equipment_no="CTV20200073")]
        self.run_import(rows)
        self.run_import(rows)
        self.assertEqual(Equipment.objects.count(), 1)

    def test_an_id_typed_by_hand_is_not_replaced_by_the_placeholder(self):
        self.run_import([row("70-1", "TE", asset_no="103220100359")])
        Equipment.objects.filter(code="70-1").update(code="VOM#1")
        self.run_import([row("70-1", "TE", asset_no="103220100359")])
        self.assertEqual(list(Equipment.objects.values_list("code", flat=True)), ["VOM#1"])

    def test_every_department_on_request(self):
        self.run_import([row("70-1", "TE"), row("70-2", "ME")], "--department", "all")
        self.assertEqual(Equipment.objects.count(), 2)
