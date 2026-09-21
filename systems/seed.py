"""
Demo data for the products page: customers, products, their processes, the
roles at each process and the equipment sets.

Kept beside the models rather than inside the core seed command, because this
is the part most likely to be replaced wholesale once real routes and sets are
entered. The awkward cases show on the first screen: one FCT with ten roles and
another with four, a process run on two sets, a set with an instrument out of
calibration, a set missing a component, and products not in production.
"""

from core.models import Category, Customer, Product
from equipment.models import Equipment

from .models import Installation, ProcessRole, ProductProcess, SystemType, SystemTypeRole, TestSet

CUSTOMERS = [("RHEEM", "Rheem"), ("BAF", "BAF"), ("BRNA", "BRNA"), ("KRAIN", "K-Rain")]

# Process catalog, in route order, with its starting role template.
PROCESSES = [
    ("PROG", "Programming", [("Programmer", "PROG")]),
    ("ICT", "In-circuit test", [
        ("ICT tester", "ICT-TESTER"), ("Fixture", "FIX-ICT"), ("PC", "PC"), ("Monitor", "MON"),
    ]),
    ("FCT", "Functional test", [
        ("Test Cart", "CART"), ("Control box", "CTRL"), ("Fixture", "FIX-FCT"),
        ("PC", "PC"), ("Monitor", "MON"), ("DMM", "DMM"), ("PSU", "PSU"),
    ]),
    ("BURNIN", "Burn-in", [("Chamber", "ENV"), ("Electronic load", "LOAD"), ("PSU", "PSU")]),
    ("HIPOT", "Hipot / safety", [("Hipot tester", "SAFETY")]),
]

# customer, code, name, revision, in production, route
PRODUCTS = [
    ("RHEEM", "RMMTT01", "Water heater control board", "Rev B", True, ["PROG", "ICT", "FCT", "BURNIN", "HIPOT"]),
    ("RHEEM", "TMMTD01", "Thermostat display board", "Rev A", True, ["PROG", "FCT"]),
    ("BAF", "BAF1950", "Mainboard", "Rev C", True, ["PROG", "ICT", "FCT", "HIPOT"]),
    ("BAF", "BAF0850", "Power board", "Rev A", False, ["ICT", "FCT"]),
    ("BRNA", "BRNA941", "Motor driver board", "Rev D", True, ["ICT", "FCT", "BURNIN"]),
    ("KRAIN", "KMCB011", "Irrigation controller main board", "Rev C", True, ["PROG", "FCT"]),
    ("KRAIN", "KMCB021", "Irrigation controller expansion board", "Rev A", False, ["PROG", "FCT"]),
]

# Products whose role list differs from the process template.
CUSTOM_ROLES = {
    # A demanding FCT: ten sub-equipments.
    ("RMMTT01", "FCT"): [
        ("Test Cart", "CART"), ("Control box", "CTRL"), ("Fixture", "FIX-FCT"), ("PC", "PC"),
        ("Monitor", "MON"), ("DMM", "DMM"), ("PSU", "PSU"), ("Oscilloscope", "SCOPE"),
        ("Function generator", "SRC"), ("Electronic load", "LOAD"),
    ],
    # A bench FCT: four.
    ("KMCB011", "FCT"): [("Fixture", "FIX-FCT"), ("PC", "PC"), ("DMM", "DMM"), ("PSU", "PSU")],
    ("KMCB021", "FCT"): [("Fixture", "FIX-FCT"), ("PC", "PC"), ("DMM", "DMM"), ("PSU", "PSU")],
}

# (product, process, set number, line, {role: asset}). A role left out stays empty.
SETS = [
    ("RMMTT01", "PROG", 1, "SMT-L1", {"Programmer": "PRG-001"}),
    ("RMMTT01", "ICT", 1, "ICT-RM", {"ICT tester": "ICT-SYS-001", "Fixture": "ICTFIX-RMMTT01", "PC": "PC-003", "Monitor": "MON-003"}),
    ("RMMTT01", "FCT", 1, "FCT-RM", {
        "Test Cart": "CART-001", "Control box": "CTRL-001", "Fixture": "FIX-RMMTT01-A", "PC": "PC-001",
        "Monitor": "MON-001", "DMM": "DMM-002", "PSU": "PSU-001", "Oscilloscope": "SCP-001",
        "Function generator": "FGN-001", "Electronic load": "LOD-001",
    }),
    ("RMMTT01", "FCT", 2, "FCT-RM", {
        "Test Cart": "CART-002", "Control box": "CTRL-002", "Fixture": "FIX-RMMTT01-B", "PC": "PC-002",
        "Monitor": "MON-002", "DMM": "DMM-005", "PSU": "PSU-002", "Oscilloscope": "SCP-002",
        "Function generator": "FGN-002", "Electronic load": "LOD-002",
    }),
    ("RMMTT01", "BURNIN", 1, "TEST", {"Chamber": "CHM-001", "Electronic load": "LOD-003", "PSU": "PSU-005"}),
    ("RMMTT01", "HIPOT", 1, "FCT-RM", {"Hipot tester": "HIP-001"}),
    ("TMMTD01", "PROG", 1, "SMT-L1", {"Programmer": "PRG-002"}),
    # Instrument out of calibration: DMM-004.
    ("TMMTD01", "FCT", 1, "SMT-L2", {
        "Test Cart": "CART-003", "Control box": "CTRL-003", "Fixture": "FIX-TMMTD01", "PC": "PC-004",
        "Monitor": "MON-004", "DMM": "DMM-004", "PSU": "PSU-003",
    }),
    ("BAF1950", "PROG", 1, "SMT-L1", {"Programmer": "PRG-003"}),
    ("BAF1950", "ICT", 1, "ICT-RM", {"ICT tester": "ICT-SYS-002", "Fixture": "ICTFIX-BAF1950", "PC": "PC-005", "Monitor": "MON-005"}),
    ("BAF1950", "FCT", 1, "FCT-RM", {
        "Test Cart": "CART-004", "Control box": "CTRL-004", "Fixture": "FIX-BAF1950", "PC": "PC-006",
        "Monitor": "MON-006", "DMM": "DMM-001", "PSU": "PSU-004",
    }),
    ("BAF1950", "HIPOT", 1, "FCT-RM", {"Hipot tester": "HIP-002"}),
    ("BAF0850", "ICT", 1, "ICT-RM", {}),
    ("BAF0850", "FCT", 1, "FCT-RM", {}),
    ("BRNA941", "ICT", 1, "ICT-RM", {"ICT tester": "ICT-SYS-003", "Fixture": "ICTFIX-BRNA941", "PC": "PC-007", "Monitor": "MON-007"}),
    # Missing component: no PSU free for it yet.
    ("BRNA941", "FCT", 1, "SMT-L2", {
        "Test Cart": "CART-005", "Control box": "CTRL-005", "Fixture": "FIX-BRNA941", "PC": "PC-008",
        "Monitor": "MON-008", "DMM": "DMM-006",
    }),
    ("BRNA941", "BURNIN", 1, "TEST", {"Chamber": "CHM-002", "Electronic load": "LOD-004", "PSU": "PSU-006"}),
    ("KMCB011", "PROG", 1, "SMT-L1", {"Programmer": "PRG-004"}),
    ("KMCB011", "FCT", 1, "FCT-RM", {"Fixture": "FIX-KMCB011", "PC": "PC-009", "DMM": "DMM-007", "PSU": "PSU-007"}),
    ("KMCB021", "PROG", 1, "SMT-L1", {}),
    ("KMCB021", "FCT", 1, "FCT-RM", {}),
]

EXTRA_CATEGORIES = [("CTRL", "Control box"), ("PC", "Industrial PC"), ("MON", "Monitor")]

# Assets the sets need beyond the general instrument pool: code, name, category, location, maker, model.
EXTRA_EQUIPMENT = [
    ("CART-004", "Mobile test cart", "CART", "FCT-RM", "In-house", "TC-02"),
    ("CART-005", "Mobile test cart", "CART", "SMT-L2", "In-house", "TC-02"),
    *[(f"CTRL-00{i}", "FCT control box", "CTRL", "FCT-RM", "In-house", "CB-GEN3") for i in range(1, 6)],
    *[(f"PC-00{i}", "Industrial PC", "PC", "FCT-RM", "Advantech", "IPC-610") for i in range(1, 10)],
    *[(f"MON-00{i}", "24-inch monitor", "MON", "FCT-RM", "Dell", "P2422H") for i in range(1, 9)],
    ("ICT-SYS-002", "In-circuit tester", "ICT-TESTER", "ICT-RM", "Keysight", "i3070 Series 5i"),
    ("ICT-SYS-003", "In-circuit tester", "ICT-TESTER", "ICT-RM", "Teradyne", "TestStation LH"),
    ("ICTFIX-RMMTT01", "ICT fixture — RMMTT01", "FIX-ICT", "ICT-RM", "Fixture House", "ICT-RM01"),
    ("ICTFIX-BAF1950", "ICT fixture — BAF1950", "FIX-ICT", "ICT-RM", "Fixture House", "ICT-1950"),
    ("ICTFIX-BRNA941", "ICT fixture — BRNA941", "FIX-ICT", "ICT-RM", "Fixture House", "ICT-941"),
    ("FIX-RMMTT01-A", "FCT fixture — RMMTT01 (A)", "FIX-FCT", "FCT-RM", "Fixture House", "FCT-RM01"),
    ("FIX-RMMTT01-B", "FCT fixture — RMMTT01 (B)", "FIX-FCT", "FCT-RM", "Fixture House", "FCT-RM01"),
    ("FIX-TMMTD01", "FCT fixture — TMMTD01", "FIX-FCT", "SMT-L2", "Fixture House", "FCT-TD01"),
    ("FIX-BAF1950", "FCT fixture — BAF1950", "FIX-FCT", "FCT-RM", "Fixture House", "FCT-1950"),
    ("FIX-BRNA941", "FCT fixture — BRNA941", "FIX-FCT", "SMT-L2", "Fixture House", "FCT-941"),
    ("FIX-KMCB011", "FCT fixture — KMCB011", "FIX-FCT", "FCT-RM", "Fixture House", "FCT-KM11"),
    ("PRG-003", "SPI flash programmer", "PROG", "SMT-L1", "Dediprog", "SF100"),
    ("PRG-004", "Universal programmer", "PROG", "SMT-L1", "Xeltek", "SuperPro 6100N"),
    ("DMM-005", "Handheld multimeter", "DMM", "FCT-RM", "Fluke", "87V"),
    ("DMM-006", "Handheld multimeter", "DMM", "SMT-L2", "Fluke", "87V"),
    ("DMM-007", "Bench multimeter", "DMM", "FCT-RM", "Keysight", "34461A"),
    *[(f"PSU-00{i}", "Programmable DC power supply", "PSU", "FCT-RM", "Rigol", "DP832") for i in range(5, 9)],
    ("FGN-002", "Function generator", "SRC", "FCT-RM", "Rigol", "DG1022Z"),
    ("LOD-002", "DC electronic load", "LOAD", "FCT-RM", "Chroma", "63103A"),
    ("LOD-003", "DC electronic load", "LOAD", "TEST", "Chroma", "63108A"),
    ("LOD-004", "DC electronic load", "LOAD", "TEST", "Itech", "IT8512A+"),
    ("CHM-002", "Burn-in chamber", "ENV", "TEST", "ESPEC", "PH-202"),
    ("HIP-002", "Hipot / safety tester", "SAFETY", "FCT-RM", "Kikusui", "TOS5302"),
]


def seed_systems(stdout, style, users, locations, categories, suppliers, assets):
    """Build customers, products, processes, roles, sets and installations."""
    technician = users["te.khanh"]

    for code, name in EXTRA_CATEGORIES:
        categories.setdefault(code, Category.objects.get_or_create(code=code, defaults={"name": name})[0])

    for code, name, category_code, location_code, maker, model in EXTRA_EQUIPMENT:
        if code in assets:
            continue
        assets[code] = Equipment.objects.get_or_create(
            code=code,
            defaults={
                "name": name, "category": categories[category_code],
                "location": locations[location_code], "manufacturer": maker,
                "model_number": model, "status": "IN_PRODUCTION",
                "supplier": suppliers.get("SUP-004"),
            },
        )[0]

    customers = {
        code: Customer.objects.get_or_create(code=code, defaults={"name": name})[0]
        for code, name in CUSTOMERS
    }

    processes = {}
    for position, (code, name, roles) in enumerate(PROCESSES, start=1):
        process = SystemType.objects.get_or_create(code=code, defaults={"name": name, "position": position})[0]
        processes[code] = process
        for order, (_label, category_code) in enumerate(roles, start=1):
            category = categories[category_code]
            template, created = SystemTypeRole.objects.get_or_create(
                system_type=process, name=category.name, defaults={"position": order},
            )
            if created:
                template.allowed_categories.add(category)

    steps = {}
    products = {}
    for customer_code, code, name, revision, in_production, route in PRODUCTS:
        product = Product.objects.get_or_create(
            code=code,
            defaults={"name": name, "revision": revision, "customer": customers[customer_code],
                      "in_production": in_production},
        )[0]
        products[code] = product
        for position, process_code in enumerate(route, start=1):
            step, created = ProductProcess.objects.get_or_create(
                product=product, process=processes[process_code], defaults={"position": position},
            )
            steps[(code, process_code)] = step
            if not created:
                continue
            custom = CUSTOM_ROLES.get((code, process_code))
            if custom:
                for order, (_label, category_code) in enumerate(custom, start=1):
                    ProcessRole.objects.create(
                        product_process=step, name=f"~{order}", position=order,
                        category=categories[category_code],
                    )
                step.name_roles()
            else:
                step.copy_template()

    fitted = 0
    set_count = 0
    for product_code, process_code, number, line_code, picks in SETS:
        step = steps[(product_code, process_code)]
        test_set, _ = TestSet.objects.get_or_create(
            product_process=step, number=number, defaults={"line": locations.get(line_code)},
        )
        set_count += 1
        # The picks above use readable labels; roles are found by equipment type.
        labels = dict(CUSTOM_ROLES.get((product_code, process_code))
                      or next(r for c, _, r in PROCESSES if c == process_code))
        free_roles = list(step.roles.select_related("category"))
        for label, asset_code in picks.items():
            asset = assets.get(asset_code)
            role = next((r for r in free_roles if r.category and r.category.code == labels.get(label)), None)
            if asset is None or role is None:
                continue
            free_roles.remove(role)
            if Installation.objects.filter(component=asset, removed_at__isnull=True).exists():
                continue
            Installation.fit(asset, test_set, role, technician, reason="Set up")
            fitted += 1

    return {
        "customers": len(customers),
        "products": len(products),
        "processes": len(steps),
        "sets": set_count,
        "fitted": fitted,
    }
