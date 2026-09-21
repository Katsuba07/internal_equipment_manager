"""
Load demo data modelled on a PCBA test-engineering department.

    python manage.py seed_demo
    python manage.py seed_demo --reset

The catalog covers what a TE group actually owns: ICT and FCT fixtures, test
stations and carts, bench instruments that need calibration, and the spares
that keep them running. Delete or re-password the demo accounts before the
system carries real data.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from calibration.models import CalibrationPlan, CalibrationRecord, CalibrationResult
from core.models import Category, Customer, Location, Product, Role, Supplier, User
from equipment.models import Equipment, EquipmentStatus
from incidents.models import IncidentReport, IncidentSeverity, IncidentStatus
from inventory.models import EquipmentPart, InventoryItem, ItemKind, StockTransaction, TransactionType
from maintenance.models import MaintenanceKind, MaintenancePlan, MaintenanceRecord
from systems.models import Installation, ProductProcess, SystemType
from systems.seed import seed_systems

DEMO_PASSWORD = "TestEng@2026"

DEMO_USERS = [
    ("admin", "Alex Tran", Role.ADMIN, "TE-001", "Test Engineering"),
    ("manager", "Minh Nguyen", Role.MANAGER, "TE-002", "Test Engineering"),
    ("te.khanh", "Khanh Pham", Role.TECHNICIAN, "TE-011", "Test Engineering"),
    ("te.duy", "Duy Le", Role.TECHNICIAN, "MT-007", "Maintenance"),
    ("qa.linh", "Linh Vo", Role.VIEWER, "QA-003", "Quality Assurance"),
]

CATEGORIES = [
    ("FIX-ICT", "ICT fixture"),
    ("FIX-FCT", "FCT fixture"),
    ("ICT-TESTER", "ICT tester"),
    ("CART", "Test cart"),
    ("PSU", "Power supply"),
    ("DMM", "Digital multimeter"),
    ("SCOPE", "Oscilloscope"),
    ("SRC", "Signal source"),
    ("LOAD", "Electronic load"),
    ("PROG", "Programmer"),
    ("SOLDER", "Soldering & rework"),
    ("SAFETY", "Safety tester"),
    ("ESD", "ESD control"),
    ("ENV", "Environmental chamber"),
    ("TOOL", "Hand tool"),
]

# code, name, parent, plant
LOCATIONS = [
    ("SMT", "SMT Area", None, "CTV1"),
    ("SMT-L1", "SMT Line 1", "SMT", "CTV1"),
    ("SMT-L2", "SMT Line 2", "SMT", "CTV1"),
    ("TEST", "Test Area", None, "CTV2"),
    ("ICT-RM", "ICT Room", "TEST", "CTV2"),
    ("FCT-RM", "FCT Room", "TEST", "CTV2"),
    ("REWORK", "Rework Bench", "TEST", "CTV2"),
    ("CAL-LAB", "Calibration Lab", None, "CTVN"),
    ("TE-STORE", "TE Store Room", None, "CTVN"),
]

SUPPLIERS = [
    ("SUP-001", "Keysight Technologies", False),
    ("SUP-002", "Tektronix", False),
    ("SUP-003", "Chroma ATE", False),
    ("SUP-004", "Fixture House Co., Ltd", False),
    ("SUP-005", "QUATEST 3 Calibration Centre", True),
    ("SUP-006", "Fluke Calibration Services", True),
]

# code, name, category, location, manufacturer, model, needs calibration, status.
# Which products an asset serves is no longer a field here — it comes from the
# test system set-ups the asset is given a role in.
EQUIPMENT = [
    # --- In-circuit test ---
    ("ICT-SYS-001", "In-circuit tester", "ICT-TESTER", "ICT-RM", "Keysight", "i3070 Series 5i",
     False, EquipmentStatus.IN_PRODUCTION),
    ("ICT-FIX-001", "ICT fixture — Mainboard", "FIX-ICT", "ICT-RM", "Fixture House", "ICT-4471",
     False, EquipmentStatus.IN_PRODUCTION),
    ("ICT-FIX-002", "ICT fixture — Power module", "FIX-ICT", "ICT-RM", "Fixture House", "ICT-5120",
     False, EquipmentStatus.IN_PRODUCTION),
    ("ICT-FIX-003", "ICT fixture — Sensor board", "FIX-ICT", "TE-STORE", "Fixture House", "ICT-3390",
     False, EquipmentStatus.MAINTENANCE),

    # --- Functional test ---
    ("FCT-FIX-001", "FCT fixture — Mainboard", "FIX-FCT", "FCT-RM", "Fixture House", "FCT-4471",
     False, EquipmentStatus.IN_PRODUCTION),
    ("FCT-FIX-002", "FCT fixture — Power module", "FIX-FCT", "FCT-RM", "Fixture House", "FCT-5120",
     False, EquipmentStatus.REPAIR),
    ("FCT-FIX-003", "FCT fixture — Sensor board", "FIX-FCT", "TE-STORE", "Fixture House", "FCT-3390",
     False, EquipmentStatus.AVAILABLE),

    # --- Test carts ---
    ("CART-001", "Mobile test cart — FCT debug", "CART", "FCT-RM", "In-house", "TC-01",
     False, EquipmentStatus.IN_PRODUCTION),
    ("CART-002", "Mobile test cart — line support", "CART", "SMT-L1", "In-house", "TC-01",
     False, EquipmentStatus.IN_PRODUCTION),
    ("CART-003", "Mobile test cart — spare", "CART", "TE-STORE", "In-house", "TC-02",
     False, EquipmentStatus.AVAILABLE),

    # --- Power supplies ---
    ("PSU-001", "Triple-output DC power supply", "PSU", "FCT-RM", "Keysight", "E36313A",
     True, EquipmentStatus.IN_PRODUCTION),
    ("PSU-002", "Programmable DC power supply", "PSU", "FCT-RM", "Rigol", "DP832",
     True, EquipmentStatus.IN_PRODUCTION),
    ("PSU-003", "Programmable DC power supply", "PSU", "CART-001", "Rigol", "DP832",
     True, EquipmentStatus.IN_PRODUCTION),
    ("PSU-004", "High-current DC supply", "PSU", "TEST", "TDK-Lambda", "GEN60-25",
     True, EquipmentStatus.AVAILABLE),

    # --- Multimeters ---
    ("DMM-001", "6.5-digit bench multimeter", "DMM", "CAL-LAB", "Keysight", "34465A",
     True, EquipmentStatus.IN_PRODUCTION),
    ("DMM-002", "Handheld multimeter", "DMM", "FCT-RM", "Fluke", "87V",
     True, EquipmentStatus.IN_PRODUCTION),
    ("DMM-003", "Handheld multimeter", "DMM", "SMT-L2", "Fluke", "87V",
     True, EquipmentStatus.CALIBRATION),
    ("DMM-004", "Handheld multimeter", "DMM", "REWORK", "Fluke", "17B+",
     True, EquipmentStatus.IN_PRODUCTION),

    # --- Scopes and sources ---
    ("SCP-001", "Mixed-domain oscilloscope", "SCOPE", "FCT-RM", "Tektronix", "MDO3024",
     True, EquipmentStatus.IN_PRODUCTION),
    ("SCP-002", "Digital oscilloscope", "SCOPE", "REWORK", "Keysight", "DSOX1204G",
     True, EquipmentStatus.IN_PRODUCTION),
    ("FGN-001", "Function / arbitrary waveform generator", "SRC", "FCT-RM", "Keysight", "33512B",
     True, EquipmentStatus.IN_PRODUCTION),
    ("LOD-001", "DC electronic load", "LOAD", "FCT-RM", "Chroma", "63103A",
     True, EquipmentStatus.IN_PRODUCTION),

    # --- Programming ---
    ("PRG-001", "SPI flash programmer", "PROG", "FCT-RM", "Dediprog", "SF100",
     False, EquipmentStatus.IN_PRODUCTION),
    ("PRG-002", "JTAG debug probe", "PROG", "REWORK", "SEGGER", "J-Link PLUS",
     False, EquipmentStatus.IN_PRODUCTION),

    # --- Rework and safety ---
    ("SLD-001", "Soldering station", "SOLDER", "REWORK", "JBC", "DDSE-2B",
     True, EquipmentStatus.IN_PRODUCTION),
    ("SLD-002", "Hot-air rework station", "SOLDER", "REWORK", "Hakko", "FR-810B",
     True, EquipmentStatus.IN_PRODUCTION),
    ("HIP-001", "Hipot / safety tester", "SAFETY", "FCT-RM", "Chroma", "19032",
     True, EquipmentStatus.IN_PRODUCTION),
    ("ESD-001", "Wrist strap / footwear tester", "ESD", "SMT-L1", "Desco", "19218",
     True, EquipmentStatus.IN_PRODUCTION),

    # --- Environmental and tools ---
    ("CHM-001", "Temperature & humidity chamber", "ENV", "TEST", "ESPEC", "SH-242",
     True, EquipmentStatus.IN_PRODUCTION),
    ("TRQ-001", "Torque screwdriver 0.5–3.0 Nm", "TOOL", "FCT-RM", "Tohnichi", "RTD60CN",
     True, EquipmentStatus.IN_PRODUCTION),
]

# code, name, kind, unit, on hand, reorder point, bin
STOCK = [
    ("PRB-100-3A", "Spring probe 100 mil, 3 A", ItemKind.PROBE, "pcs", 640, 200, "A1-01"),
    ("PRB-075-2A", "Spring probe 75 mil, 2 A", ItemKind.PROBE, "pcs", 120, 200, "A1-02"),
    ("PRB-RCP-100", "Probe receptacle 100 mil", ItemKind.PROBE, "pcs", 410, 150, "A1-03"),
    ("FIX-SPR-25", "Fixture compression spring 25 N", ItemKind.SPARE_PART, "pcs", 85, 40, "A2-01"),
    ("FIX-PNU-32", "Pneumatic cylinder 32 mm (fixture)", ItemKind.SPARE_PART, "pcs", 3, 2, "A2-04"),
    ("ITF-PIN-BLK", "ICT interface pin block", ItemKind.SPARE_PART, "pcs", 6, 4, "A2-05"),
    ("RLY-G6K-5V", "Signal relay G6K-2F-Y 5 VDC", ItemKind.SPARE_PART, "pcs", 8, 20, "B1-02"),
    ("CBL-DSUB25", "D-Sub 25 test cable assembly", ItemKind.CABLE, "pcs", 14, 6, "B2-01"),
    ("CBL-BAN-SET", "Banana to alligator lead set", ItemKind.CABLE, "set", 9, 5, "B2-02"),
    ("CBL-USB-B", "USB A-B cable 2 m, shielded", ItemKind.CABLE, "pcs", 22, 10, "B2-03"),
    ("FUS-5A-FF", "Fuse 5 A fast-blow 5x20 mm", ItemKind.CONSUMABLE, "pcs", 180, 50, "C1-01"),
    ("SLD-TIP-C245", "Soldering tip JBC C245-903", ItemKind.CONSUMABLE, "pcs", 5, 12, "C1-04"),
    ("SLD-WIRE-06", "Solder wire SAC305 0.6 mm", ItemKind.CONSUMABLE, "roll", 11, 5, "C1-05"),
    ("FLX-PEN", "No-clean flux pen", ItemKind.CONSUMABLE, "pcs", 24, 10, "C1-06"),
    ("IPA-1L", "Isopropyl alcohol 99.9 %, 1 L", ItemKind.CONSUMABLE, "bottle", 16, 8, "C2-01"),
    ("ESD-MAT-612", "ESD table mat 600 x 1200 mm", ItemKind.CONSUMABLE, "pcs", 7, 4, "C2-03"),
    ("ESD-CORD", "ESD wrist strap coil cord", ItemKind.CONSUMABLE, "pcs", 31, 15, "C2-04"),
    ("SPR-PSU-DP832", "Rigol DP832 — standby unit", ItemKind.SPARE_EQUIPMENT, "pcs", 1, 1, "D1-01"),
    ("SPR-PC-FCT", "FCT station industrial PC — standby", ItemKind.SPARE_EQUIPMENT, "pcs", 1, 1, "D1-02"),
]

# Each asset's own parts list: equipment code, part number, quantity, note.
# Bottom tier of a test system — part -> equipment -> product BOM.
EQUIPMENT_PARTS = [
    ("FIX-BAF1950", "PRB-075-2A", 96, "Signal nets, top plate"),
    ("FIX-BAF1950", "PRB-100-3A", 24, "Power and ground nets"),
    ("FIX-BAF1950", "PRB-RCP-100", 120, ""),
    ("FIX-BAF1950", "FIX-SPR-25", 4, "Press plate"),
    ("FIX-BAF1950", "FIX-PNU-32", 1, ""),
    ("FIX-RMMTT01-A", "PRB-075-2A", 64, ""),
    ("FIX-RMMTT01-A", "PRB-100-3A", 16, ""),
    ("FIX-RMMTT01-A", "PRB-RCP-100", 80, ""),
    ("FIX-RMMTT01-A", "FIX-SPR-25", 4, ""),
    ("FIX-KMCB011", "PRB-075-2A", 48, ""),
    ("FIX-KMCB011", "PRB-RCP-100", 48, ""),
    ("FIX-KMCB011", "FIX-SPR-25", 2, ""),
    ("ICTFIX-BAF1950", "PRB-100-3A", 412, "Bed of nails"),
    ("ICTFIX-BAF1950", "PRB-RCP-100", 412, ""),
    ("ICTFIX-BAF1950", "ITF-PIN-BLK", 2, "Tester interface"),
    ("ICT-FIX-001", "PRB-100-3A", 356, ""),
    ("ICT-FIX-001", "ITF-PIN-BLK", 2, ""),
    ("ICT-FIX-002", "PRB-100-3A", 288, ""),
    ("ICT-FIX-002", "ITF-PIN-BLK", 2, ""),
    ("ICT-FIX-003", "PRB-100-3A", 310, ""),
    ("FCT-FIX-001", "PRB-075-2A", 72, ""),
    ("FCT-FIX-001", "FIX-SPR-25", 4, ""),
    ("FCT-FIX-002", "PRB-075-2A", 58, ""),
    ("FCT-FIX-003", "PRB-075-2A", 40, ""),
    ("CTRL-001", "RLY-G6K-5V", 16, "Switching matrix"),
    ("CTRL-001", "CBL-DSUB25", 2, "To fixture"),
    ("CTRL-001", "FUS-5A-FF", 2, ""),
    ("CTRL-002", "RLY-G6K-5V", 16, ""),
    ("CTRL-002", "CBL-DSUB25", 2, ""),
    ("CTRL-003", "RLY-G6K-5V", 8, ""),
    ("CTRL-003", "CBL-DSUB25", 1, ""),
    ("CTRL-004", "RLY-G6K-5V", 8, ""),
    ("CART-001", "FUS-5A-FF", 1, "Power strip"),
    ("CART-002", "FUS-5A-FF", 1, "Power strip"),
    ("PC-001", "CBL-USB-B", 2, "DMM and PSU links"),
    ("PC-002", "CBL-USB-B", 2, ""),
    ("PC-003", "CBL-USB-B", 2, ""),
    ("DMM-001", "CBL-BAN-SET", 1, ""),
    ("DMM-002", "CBL-BAN-SET", 1, ""),
    ("PSU-001", "CBL-BAN-SET", 1, ""),
    ("PSU-002", "CBL-BAN-SET", 1, ""),
    ("SLD-001", "SLD-TIP-C245", 1, "Fitted tip"),
]

# equipment code, task, kind, interval days, offset from due (days), checklist
MAINTENANCE = [
    ("ICT-FIX-001", "Pogo pin cleaning", MaintenanceKind.CLEANING, 30, -4,
     "Blow out debris with clean dry air\nClean probe tips with IPA and lint-free swab\n"
     "Inspect tips for flux build-up and wear\nVerify no bent or stuck probes"),
    ("ICT-FIX-001", "Contact resistance check", MaintenanceKind.INSPECTION, 90, 12,
     "Measure contact resistance on 10 sample nets\nRecord values against the 200 mOhm limit\n"
     "Replace any probe above limit\nRun a known-good board to confirm"),
    ("ICT-FIX-002", "Pogo pin cleaning", MaintenanceKind.CLEANING, 30, 6,
     "Blow out debris with clean dry air\nClean probe tips with IPA\nInspect for wear"),
    ("ICT-FIX-002", "Probe replacement — high-cycle nets", MaintenanceKind.PROBE_SERVICE, 180, 41,
     "Replace probes on power and ground nets\nRecord insertion count\nVerify continuity on all replaced nets"),
    ("ICT-SYS-001", "Tester self-test and diagnostics", MaintenanceKind.SELF_TEST, 30, 2,
     "Run full system self-test\nCheck pin card diagnostics\nReview error log\nArchive results"),
    ("FCT-FIX-001", "Daily verification with golden board", MaintenanceKind.SELF_TEST, 7, 1,
     "Run golden board through full sequence\nConfirm all measurements within limits\nLog result"),
    ("FCT-FIX-001", "Test program and limits backup", MaintenanceKind.FIRMWARE, 90, 22,
     "Back up test sequence and limit files\nVerify version against release record\nStore copy on the server"),
    ("FCT-FIX-003", "Daily verification with golden board", MaintenanceKind.SELF_TEST, 7, -2,
     "Run golden board through full sequence\nConfirm all measurements within limits\nLog result"),
    ("FCT-FIX-001", "Connector and cable inspection", MaintenanceKind.INSPECTION, 30, 9,
     "Inspect UUT connectors for wear\nCheck harness for chafing\nVerify latch operation\nRe-seat all connectors"),
    ("FCT-FIX-001", "Pneumatic system check", MaintenanceKind.PREVENTIVE, 90, 33,
     "Check air pressure at 5 bar\nInspect cylinder for leaks\nLubricate guide rails\nVerify clamp timing"),
    ("FCT-FIX-002", "Connector and cable inspection", MaintenanceKind.INSPECTION, 30, -9,
     "Inspect UUT connectors for wear\nCheck harness for chafing\nVerify latch operation"),
    ("CART-001", "Cable and lead inspection", MaintenanceKind.INSPECTION, 90, 27,
     "Inspect all test leads for damage\nCheck banana plugs and clips\nVerify ESD ground bonding"),
    ("CART-002", "Cable and lead inspection", MaintenanceKind.INSPECTION, 90, 3,
     "Inspect all test leads for damage\nCheck banana plugs and clips\nVerify ESD ground bonding"),
    ("CHM-001", "Filter cleaning and door seal check", MaintenanceKind.CLEANING, 90, 15,
     "Clean intake filter\nInspect door gasket\nCheck water reservoir\nVerify drain is clear"),
    ("SLD-001", "Tip inspection and station cleaning", MaintenanceKind.PREVENTIVE, 30, 4,
     "Inspect and replace worn tips\nClean tip cleaner and tray\nCheck ESD grounding of the iron"),
]

# equipment code, scope, interval months, months until due, range, tolerance, in-house
CALIBRATION = [
    ("DMM-001", "DC voltage, DC current, resistance", 12, 4,
     "0–1000 V, 0–10 A, 0–100 MOhm", "±0.0035 % of reading", False),
    ("DMM-002", "DC voltage, continuity, resistance", 12, 7, "0–1000 V", "±0.05 % of reading", False),
    ("DMM-003", "DC voltage, continuity, resistance", 12, 0, "0–1000 V", "±0.05 % of reading", False),
    ("DMM-004", "DC voltage, continuity", 12, -1, "0–600 V", "±0.5 % of reading", False),
    ("PSU-001", "DC output voltage and current", 12, 2, "0–25 V, 0–7 A", "±0.05 % + 5 mV", False),
    ("PSU-002", "DC output voltage and current", 12, 9, "0–30 V, 0–3 A", "±0.1 % + 10 mV", False),
    ("PSU-003", "DC output voltage and current", 12, -2, "0–30 V, 0–3 A", "±0.1 % + 10 mV", False),
    ("PSU-004", "DC output voltage and current", 12, 6, "0–60 V, 0–25 A", "±0.2 % of full scale", False),
    ("SCP-001", "Vertical accuracy and timebase", 12, 5, "1 mV–10 V/div, 200 MHz", "±2 % vertical", False),
    ("SCP-002", "Vertical accuracy and timebase", 12, 11, "1 mV–5 V/div, 70 MHz", "±3 % vertical", False),
    ("FGN-001", "Frequency and output amplitude", 12, 8, "1 uHz–20 MHz", "±1 ppm frequency", False),
    ("LOD-001", "CC / CV mode accuracy", 12, 3, "0–20 A, 0–80 V", "±0.1 % + 0.1 % FS", False),
    ("HIP-001", "AC withstand voltage and leakage current", 12, 1,
     "0–5 kV AC, 0–30 mA", "±2 % of setting", False),
    ("ESD-001", "Resistance thresholds", 12, 10, "750 kOhm – 35 MOhm", "±5 %", True),
    ("CHM-001", "Temperature and humidity uniformity", 12, -1,
     "-40 to +150 °C, 20–98 %RH", "±0.5 °C, ±3 %RH", False),
    ("SLD-001", "Tip temperature", 6, 2, "100–450 °C", "±5 °C", True),
    ("SLD-002", "Air temperature", 6, 4, "100–550 °C", "±10 °C", True),
    ("TRQ-001", "Torque output", 6, -1, "0.5–3.0 Nm", "±3 % of reading", False),
]


class Command(BaseCommand):
    help = "Load demo data for a PCBA test-engineering department."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing operational data before loading.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(20260917)  # same data on every run
        today = timezone.localdate()

        if options["reset"]:
            self.stdout.write("Clearing existing data...")
            StockTransaction.objects.all().delete()
            InventoryItem.objects.all().delete()
            CalibrationRecord.objects.all().delete()
            CalibrationPlan.objects.all().delete()
            MaintenanceRecord.objects.all().delete()
            MaintenancePlan.objects.all().delete()
            IncidentReport.objects.all().delete()
            Installation.objects.all().delete()
            ProductProcess.objects.all().delete()
            SystemType.objects.all().delete()
            Equipment.objects.all().delete()
            # Products go last: set-ups reference them, and this also clears
            # the placeholder rows the old free-text migration created.
            Product.objects.all().delete()
            Customer.objects.all().delete()

        # --- People ---
        users = {}
        for username, full_name, role, code, department in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "full_name": full_name,
                    "role": role,
                    "employee_code": code,
                    "department": department,
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                if role == Role.ADMIN:
                    user.is_superuser = True
                user.save()
            users[username] = user
        self.stdout.write(self.style.SUCCESS(f"  {len(DEMO_USERS)} users"))

        admin = users["admin"]
        te = users["te.khanh"]
        maint = users["te.duy"]

        # --- Catalogs ---
        categories = {
            code: Category.objects.get_or_create(code=code, defaults={"name": name})[0]
            for code, name in CATEGORIES
        }
        locations = {}
        for code, name, parent_code, plant in LOCATIONS:
            location, created = Location.objects.get_or_create(
                code=code,
                defaults={"name": name, "parent": locations.get(parent_code), "plant": plant},
            )
            if not created and location.plant != plant:
                # Locations survive a reset, so the plant is applied to them too.
                location.plant = plant
                location.save(update_fields=["plant", "updated_at"])
            locations[code] = location
        suppliers = {
            code: Supplier.objects.get_or_create(
                code=code, defaults={"name": name, "is_calibration_provider": is_cal}
            )[0]
            for code, name, is_cal in SUPPLIERS
        }
        self.stdout.write(
            self.style.SUCCESS(
                f"  {len(categories)} categories, {len(locations)} locations, "
                f"{len(suppliers)} suppliers"
            )
        )

        # --- Equipment ---
        vendor_for = {
            "Keysight": "SUP-001", "Tektronix": "SUP-002", "Chroma": "SUP-003",
            "Fixture House": "SUP-004",
        }
        assets = {}
        for (code, name, cat, loc, maker, model, needs_cal, status) in EQUIPMENT:
            purchased = today - timedelta(days=random.randint(300, 2400))
            # Instruments that live on a cart are recorded in the cart's room;
            # which set-up they serve is a matter for the test system, not a
            # parent field on the asset.
            room = "FCT-RM" if loc.startswith("CART-") else loc
            asset, created = Equipment.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": categories[cat],
                    "location": locations[room],
                    "manufacturer": maker,
                    "model_number": model,
                    "serial_number": f"{model.replace(' ', '')[:8].upper()}-{random.randint(10000, 99999)}",
                    "year_made": purchased.year,
                    "firmware_version": random.choice(["", "", "v1.4.2", "v2.0.1", "v3.11"]),
                    "status": status,
                    "is_measuring_device": needs_cal,
                    "supplier": suppliers.get(vendor_for.get(maker, "SUP-004")),
                    "purchase_date": purchased,
                    "purchase_cost": Decimal(random.randint(400, 180000)),
                    "commissioned_date": purchased + timedelta(days=random.randint(10, 60)),
                    "warranty_until": purchased + timedelta(days=730),
                    "specifications": "",
                },
            )
            assets[code] = asset
            if created:
                asset.status_history.create(
                    from_status="",
                    to_status=asset.status,
                    changed_by=admin,
                    reason="Asset record created",
                )

        self.stdout.write(self.style.SUCCESS(f"  {len(assets)} assets"))

        # --- Maintenance plans, each with one historical log entry ---
        plan_count = 0
        for code, name, kind, interval, offset, checklist in MAINTENANCE:
            asset = assets[code]
            due = today + timedelta(days=offset)
            last_done = due - timedelta(days=interval)
            plan, created = MaintenancePlan.objects.get_or_create(
                equipment=asset,
                name=name,
                defaults={
                    "kind": kind,
                    "interval_days": interval,
                    "checklist": checklist,
                    "assignee": te if asset.category.code.startswith("FIX") else maint,
                    "last_done_at": last_done,
                    "next_due_at": due,
                    "estimated_minutes": random.choice([15, 30, 45, 60, 90]),
                    "trigger_cycles": random.choice([None, None, 5000, 10000, 25000])
                    if asset.category.code.startswith("FIX")
                    else None,
                },
            )
            if created:
                plan_count += 1
                MaintenanceRecord.objects.create(
                    equipment=asset,
                    plan=None,  # not linked, so the due date set above stands
                    kind=kind,
                    performed_at=last_done,
                    performed_by=plan.assignee,
                    work_done=f"Completed {name.lower()} per checklist. No abnormality found.",
                    result="OK",
                    downtime_minutes=random.choice([0, 0, 15, 30, 45]),
                )
        self.stdout.write(self.style.SUCCESS(f"  {plan_count} maintenance plans with history"))

        # --- Calibration plans and certificates ---
        cal_count = 0
        for code, scope, interval, months_out, cal_range, tolerance, internal in CALIBRATION:
            asset = assets[code]
            due = today + timedelta(days=int(months_out * 30.4))
            last = due - timedelta(days=int(interval * 30.4))
            provider = None if internal else suppliers[random.choice(["SUP-005", "SUP-006"])]
            plan, created = CalibrationPlan.objects.get_or_create(
                equipment=asset,
                name=scope,
                defaults={
                    "interval_months": interval,
                    "measurement_range": cal_range,
                    "tolerance": tolerance,
                    "standard_reference": "ISO 9001:2015 cl. 7.1.5 / internal procedure CAL-WI-002",
                    "is_internal": internal,
                    "provider": provider,
                    "last_calibrated_at": last,
                    "next_due_at": due,
                },
            )
            if created:
                cal_count += 1
                CalibrationRecord.objects.create(
                    equipment=asset,
                    plan=None,  # keep the due date set above
                    calibrated_at=last,
                    next_due_at=due,
                    is_internal=internal,
                    provider=provider,
                    performed_by=te,
                    certificate_number=""
                    if internal
                    else f"Q3-{last.year}-{random.randint(10000, 99999)}",
                    result=CalibrationResult.PASS,
                    deviation=random.choice(["within tolerance", "0.002 %", "0.4 °C", "1.2 %"]),
                    cost=None if internal else Decimal(random.randint(60, 480)),
                )
        self.stdout.write(self.style.SUCCESS(f"  {cal_count} calibration plans with certificates"))

        # --- Stock ---
        stock_count = 0
        plant_for_bin = {"A": "CTV2", "B": "CTV1", "C": "CTV1", "D": "CTVN"}
        for code, name, kind, unit, quantity, minimum, bin_location in STOCK:
            item, created = InventoryItem.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "kind": kind,
                    "unit": unit,
                    "min_quantity": Decimal(minimum),
                    "storage_location": bin_location,
                    "plant": plant_for_bin.get(bin_location[:1], "CTV2"),
                    "unit_price": Decimal(random.randint(1, 900)),
                    "lead_time_days": random.choice([7, 14, 21, 30, 45]),
                    "supplier": suppliers["SUP-004"],
                },
            )
            if created:
                stock_count += 1
                StockTransaction(
                    item=item,
                    transaction_type=TransactionType.IN,
                    quantity=Decimal(quantity),
                    performed_by=admin,
                    reason="Opening stock",
                ).apply()
        self.stdout.write(self.style.SUCCESS(f"  {stock_count} stock items"))

        # --- Test system set-ups ---
        summary = seed_systems(
            self.stdout, self.style, users, locations, categories, suppliers, assets
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  {summary['customers']} customers, {summary['products']} products, "
                f"{summary['processes']} product processes, {summary['sets']} sets, "
                f"{summary['fitted']} assets fitted"
            )
        )

        # --- Scheduled maintenance on the asset record ---
        rounds = {"FIX": 7, "ICT": 30, "FCT": 30, "CART": 90, "CTRL": 90, "SLD": 30, "CHM": 180, "HIP": 365}
        maintained = 0
        for asset in assets.values():
            interval = next((days for prefix, days in rounds.items() if asset.code.startswith(prefix)), None)
            if interval is None:
                continue
            asset.maintenance_required = True
            asset.maintenance_interval_days = interval
            asset.save(update_fields=["maintenance_required", "maintenance_interval_days", "updated_at"])
            asset.sync_maintenance_plan()
            maintained += 1
        self.stdout.write(self.style.SUCCESS(f"  {maintained} assets on a scheduled maintenance round"))

        # --- Parts lists on equipment ---
        items = {item.code: item for item in InventoryItem.objects.all()}
        part_lines = 0
        for asset_code, part_code, quantity, note in EQUIPMENT_PARTS:
            if asset_code not in assets or part_code not in items:
                continue
            _, created = EquipmentPart.objects.get_or_create(
                equipment=assets[asset_code],
                item=items[part_code],
                defaults={"quantity": Decimal(quantity), "notes": note},
            )
            part_lines += created
        self.stdout.write(self.style.SUCCESS(f"  {part_lines} parts-list lines on equipment"))

        # --- Open incidents ---
        incidents = [
            {
                "equipment": assets["FCT-FIX-002"],
                "title": "Intermittent continuity fail on fixture pin 45",
                "description": (
                    "FCT set #2 reports intermittent open on net VBUS_SENSE (fixture pin 45). "
                    "Fail rate approximately 1 in 8 boards. Passing boards re-test OK on set #1, "
                    "so the fault points to the fixture interface rather than the units. "
                    "Fixture taken out of production pending investigation."
                ),
                "severity": IncidentSeverity.HIGH,
                "status": IncidentStatus.IN_PROGRESS,
                "stopped_production": True,
                "affected_units": 42,
                "days_ago": 2,
            },
            {
                "equipment": assets["ICT-FIX-003"],
                "title": "High contact resistance across multiple nets",
                "description": (
                    "Routine contact resistance check found 14 nets above the 200 mOhm limit, "
                    "concentrated on the power section. Probe tips show heavy flux build-up. "
                    "Fixture pulled from the line for probe replacement."
                ),
                "severity": IncidentSeverity.MEDIUM,
                "status": IncidentStatus.ACKNOWLEDGED,
                "stopped_production": False,
                "affected_units": None,
                "days_ago": 5,
            },
            {
                "equipment": assets["DMM-004"],
                "title": "Calibration sticker expired — removed from service",
                "description": (
                    "Meter found in use at the rework bench with an expired calibration label. "
                    "Quarantined and sent for calibration. Work performed with this meter in the "
                    "last week is being reviewed."
                ),
                "severity": IncidentSeverity.CRITICAL,
                "status": IncidentStatus.NEW,
                "stopped_production": False,
                "affected_units": None,
                "days_ago": 1,
            },
        ]
        incident_count = 0
        for data in incidents:
            days_ago = data.pop("days_ago")
            reported = timezone.now() - timedelta(days=days_ago)
            _, created = IncidentReport.objects.get_or_create(
                equipment=data["equipment"],
                title=data["title"],
                defaults={
                    **data,
                    "reported_by": te,
                    "reported_at": reported,
                    "assigned_to": te if data["status"] != IncidentStatus.NEW else None,
                    "acknowledged_at": reported + timedelta(hours=1)
                    if data["status"] != IncidentStatus.NEW
                    else None,
                },
            )
            incident_count += 1 if created else 0
        self.stdout.write(self.style.SUCCESS(f"  {incident_count} open incidents"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
        self.stdout.write("")
        self.stdout.write(f"  Sign in with any account below — password: {DEMO_PASSWORD}")
        for username, full_name, role, _, department in DEMO_USERS:
            self.stdout.write(f"    {username:12s} {full_name:14s} {Role(role).label} · {department}")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING("  Remove or re-password these accounts before real use.")
        )
