# Equipment Manager (EMA)

An in-house web application for a PCBA test-engineering department: asset
records, **products by customer with each process's equipment sets**, maintenance, repairs,
incidents, spares, and calibration of measuring equipment — with the history an
audit will ask for.

**Current release: 0.9.4.** See the [roadmap](#roadmap) below.

> Installing or running it? Read **[OPERATIONS-GUIDE.md](OPERATIONS-GUIDE.md)** —
> written for the person operating the system, no programming assumed.
> This file is for whoever (or whatever) changes the code.

---

## Stack

| Piece | Choice | Why |
|---|---|---|
| Framework | Django 5.2 LTS | Supported to April 2028; auth, permissions, migrations and an admin site out of the box |
| Python | 3.12+ (tested on 3.14) | |
| Database | SQLite in WAL mode | No database server to run; a backup is one file |
| Front end | Hand-written CSS design system + HTMX | **No build step** — no Node, no npm, no bundler |
| Forms / tables / filters | crispy-forms, django-tables2, django-filter | Removes repetition across the nine modules |
| History | django-simple-history | Change trail for audit evidence |
| Spreadsheets | openpyxl | Asset list import and export |
| Serving | Waitress + WhiteNoise | Runs well on Windows with no nginx or IIS |

### Decisions worth knowing before you change things

- **No CSS framework.** `static/css/app.css` is the whole design system, driven by
  CSS custom properties on `:root`. Light and dark themes are both defined there;
  re-theming means editing the token block and nothing else. The stylesheet also
  styles the Bootstrap class names crispy-forms emits (`.form-control`,
  `.form-select`, `.form-check`), which is why those names appear in it.
- **One number controls the size of everything.** The interface is laid out in
  `rem`, so `html { font-size }` at the top of `app.css` scales every panel,
  control and table together. It is set to `13px` for the dense, classic look
  this tool needs; raise it towards the `16px` browser default for a roomier
  interface without touching anything else.
- **System fonts, on purpose.** `Segoe UI` and `Consolas` are what Windows
  already has, which is what makes the application look native rather than like
  a web page — and it removes two font downloads.
- **Static files use `CompressedStaticFilesStorage`, deliberately not the
  `Manifest` variant.** The manifest version requires a successful
  `collectstatic` before the site will serve at all, and forgetting it turns
  every page into a 500. Trade-off: no content-hash cache busting, covered by
  `WHITENOISE_MAX_AGE`.
- **`manage.py` forces the console to UTF-8.** Windows Command Prompt defaults to
  cp1252 and aborts commands mid-run with `UnicodeEncodeError`.
- **PDF export will use a print stylesheet, not WeasyPrint.** WeasyPrint needs GTK
  libraries on Windows — a classic install dead end. The print rules are already
  in `app.css`.
- **SQLite must stay on a local disk.** File locking over SMB is not reliable and
  can corrupt the database.
- **An asset has no single parent.** It is fitted to at most one role of one
  equipment set at a time (`Installation`, enforced by a partial unique
  constraint); closed rows are its history. The old single-parent foreign key
  was removed in 0.3 because it could not express cross-used equipment.
- **A plant is a property of the location (0.7).** `core.Plant` lists CTV1,
  CTV2 and CTVN; `Location.plant` carries it and `Equipment.plant` reads through,
  so moving an asset moves its plant with it. Spare parts hold their own plant,
  because stock is kept per store.
- **The asset form owns the routine maintenance round.** `maintenance_required`
  plus an interval keeps one `MaintenancePlan` named "Scheduled maintenance" in
  step (`Equipment.sync_maintenance_plan`); extra plans entered by hand are left
  alone, and unticking deactivates rather than deletes.
- **Photos are attachments of kind PHOTO (0.6.6).** `core/photos.py` checks each
  upload with Pillow, turns it upright, stores a 1600 px JPEG plus a 360 px
  thumbnail, and deletes the files with the row. Everything under `data/uploads`
  is served by `serve_upload`, to signed-in users only, in every environment.
- **No production runs, no compatibility lists (0.6).** A product has an
  ordered list of processes; each process has its own role list (copied from the
  process template, then edited per product) and one or more sets. A set holds
  the equipment in use *now*. Deleting a product, process or set is one action:
  fitted assets are released, never deleted.

---

## Layout

```
config/          Django settings, URLs, WSGI
core/            Users, roles, shared catalogs, attachments, dashboard
  ├─ mixins.py         View-layer permission checks
  ├─ models.py         User, Location, Category, Supplier, Attachment, DueScheduleMixin
  ├─ tables.py         BaseTable, BadgeColumn — reused by every module
  └─ management/commands/
       ├─ seed_demo.py    PCBA test-engineering demo data
       └─ backup_db.py    Self-verifying backup
equipment/       Asset records, status and status history
systems/         Products page: processes per product, roles, equipment sets
  ├─ models.py         SystemType (process), SystemTypeRole (template), ProductProcess, ProcessRole, TestSet, Installation
  ├─ services.py       Set readiness, products overview, set changes, one-click delete
  └─ seed.py           Demo customers (Rheem, BAF, BRNA, K-Rain), routes and sets
maintenance/     Maintenance schedules and logs
incidents/       Incident reports
repairs/         Repair and replacement jobs
inventory/       Spare parts, stock movements, each asset's parts list (EquipmentPart)
calibration/     Calibration schedules and certificates
reports/         Exports, QR labels, statistics (later release)
templates/       base.html plus per-app templates
static/          app.css, app.js, htmx, icon font, web fonts — no CDN
data/            ema.sqlite3 + uploads/ + ema.log  (not in version control)
scripts/         Windows setup, run and backup scripts
```

**Every module's data model already exists**, including the ones without their own
screens yet. Since 0.4 the Django admin is trimmed to equipment, catalogs
(categories, locations, suppliers, system types with their roles) and users;
the other modules get their own screens in later releases, and their data still
feeds the dashboard.

---

## Getting started

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # then generate EMA_SECRET_KEY, set EMA_DEBUG=True
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Open http://localhost:8000

### Demo accounts (password `TestEng@2026`)

| Username | Role | Department |
|---|---|---|
| `admin` | Administrator | Test Engineering |
| `manager` | Manager | Test Engineering |
| `te.khanh` | Technician | Test Engineering |
| `te.duy` | Technician | Maintenance |
| `qa.linh` | Viewer | Quality Assurance |

### How products and their equipment are modelled

```
Customer (Rheem, BAF, BRNA, K-Rain)
 └─ Product (RMMTT01 ...)             in_production: switched by hand
     └─ ProductProcess (PROG > ICT > FCT > BURNIN > HIPOT, per product)
         ├─ ProcessRole               what a set here is made of (10 for one FCT, 4 for another)
         └─ TestSet #1, #2 ...        physical sets, each on a line
             └─ Installation > Equipment > EquipmentPart > InventoryItem
                (one role)      (fixture)   (qty)           (probe)
```

`SystemType` is the process catalog; its roles are only a template copied when
a process is added to a product. A role *is* an equipment type (`ProcessRole.category`);
its name follows the type and is numbered when a type repeats (`name_roles()`:
Power supply 1, Power supply 2). A test system is the name of a set, never an asset. `evaluate_set(set)` reports per role: ready,
nothing fitted, wrong kind of asset, or unusable (down, in repair, calibration
lapsed). `apply_set_changes()` makes a set hold exactly the chosen assets in one
transaction. Declaring a part on an asset does not move stock; the balance only
changes through `StockTransaction.apply()`.

The products page (`/products/`) groups products by customer, shows only those in
production unless asked, and lists each process's sets with the equipment in use.
Clicking a set, process or product opens a panel on the right (htmx); every panel
also has its own URL (`?set=`, `?process=`, `?product=`).

The demo set is modelled on a real TE inventory: ICT and FCT fixtures and
stations, mobile test carts, bench power supplies, DMMs, scopes, a function
generator, an electronic load, flash and JTAG programmers, soldering and rework
stations, a hipot tester, an ESD tester, a thermal chamber and a torque
screwdriver — plus the pogo pins, probes, relays and cables that keep them
running. Delete or re-password these accounts before real use.

### Tests

```powershell
.\.venv\Scripts\python.exe manage.py test
```

82 tests, concentrated on what is easy to get wrong: due-date arithmetic for
maintenance and calibration, stock deduction, status transitions, spreadsheet
import, **the one-component-one-place constraint**, and **permission
enforcement against direct URL access**.

---

## Conventions

- **Every view that writes data carries a permission mixin** from `core/mixins.py`
  (`CanRecordMixin`, `CanManageMixin`, `AdminRequiredMixin`). Hiding a button is
  decoration, not security — and there must be a test proving the URL is blocked.
  See `core/tests.py`.
- **Change asset status through `Equipment.change_status()`**, never by assigning
  `equipment.status`. A direct assignment loses the history row.
- **Change stock through `StockTransaction.apply()`**, never by editing
  `quantity_on_hand`. That is what keeps the balance and the movement history in
  agreement.
- **Fit and release components through `Installation.fit()` and `.release()`**,
  never by creating rows by hand. A partial unique constraint allows only one
  open installation per component; going through these methods turns that into a
  readable message instead of an integrity error.
- **Badge colours come from the model**, as a `*_badge_class` property returning a
  CSS class such as `badge-danger`. Tables and templates read that property, so
  the palette changes in one place.
- **User-facing wording lives in `verbose_name` and `choices`.** Screens and the
  admin both read from there; do not restate labels in templates.
- Heavier logic belongs in the app's `services.py`, not in views.

---

## Roadmap

| Release | Scope | Status |
|---|---|---|
| 0.1 | Foundation, sign-in, four roles, asset records, status history, Excel import/export, backups | Done |
| 0.2 | English throughout, PCBA test-engineering data model and demo set, new design system with dark mode | Done |
| 0.3 | Test system set-ups per product code, role templates, cross-use tracking, readiness check | Done |
| 0.4 | BOM split from production runs, one-click delete with release, trimmed admin | Done |
| 0.5 | Spare parts screens, stock receipts/issues, parts list with quantities on every asset | Done |
| 0.5.1 | "+ New" pop-ups beside dropdowns (`core/quickadd.py`), stock shown as highlighted cells | Done |
| 0.5.2 | Browser review with Playwright CLI: phone overflow, pop-up ids, wording fixes | Done |
| **0.6** | One Products page by customer: processes per product, per-product roles, sets #1/#2, detail panel with in-place editing; runs and compatibility lists removed | **Done** |
| 0.6.1 | Roles chosen from a dropdown of equipment types (auto-named, numbered when repeated); "Test system" category renamed ICT tester, FCT stations removed as assets | Done |
| 0.6.2 | Products page shows each route as a flow of process boxes; sets list their equipment one per line, problems in red, empty roles named | Done |
| 0.6.3 | Reorder a product's processes by drag and drop on the products page (managers; arrows remain for touch screens) | Done |
| 0.6.4 | Overview rebuilt around the line: products in production with each set green/red and what stops it; to-do lists say which set an asset sits in; fleet and recent activity (incl. fit/remove) below | Done |
| 0.6.5 | Spare parts list: a Status column with coloured tags (In stock, Low stock, Out of stock, Inactive) instead of highlighted cells | Done |
| 0.6.6 | Photos for equipment and spare parts (main + extra, auto-shrunk, thumbnails, lightbox), shown on detail pages and beside each asset in a set; uploads served to signed-in users only | Done |
| 0.6.7 | Quick-look drawer: clicking a row on the equipment or spare parts list shows photo, key facts and actions without leaving the list | Done |
| **0.7** | Three plants (CTV1/CTV2/CTVN) on locations, parts and every list; scheduled maintenance from the asset form; Overview as a dashboard (equipment and spare parts tiles, due windows, plant split); larger photos | **Done** |
| 0.7.1 | Overview trimmed to what needs acting on (no fleet bar, no stock value, no due table); products not in production shown apart and quietly | Done |
| 0.7.2 | Status change, receive and issue open an input dialog on the page instead of a separate form page | Done |
| 0.7.3 | An issue names the asset it goes to, picked with a search box (the assets that list the part come first) and shown on both the part and the asset | Done |
| 0.7.4 | Deleting made findable: a Delete button on asset and part pages and in the quick-look drawer, tick rows on the lists to delete several at once, spare parts in the admin site, the Administrator role gets full admin permissions, assets with maintenance or calibration history can be deleted | Done |
| 0.7.5 | Edit asset and Edit part open in a wide dialog over the page (the parts list and + New work inside it, + New stacks on top without losing what was typed); the same URLs still open as full pages | Done |
| 0.7.6 | Location is optional ("Not set" until someone fills it in); the plant is kept on the asset itself and follows the location when one is chosen; the Computime import is Test Engineering only | Done |
| 0.7.7 | The company asset number (12 digits, e.g. 103220100359) is the asset code where it is known, 70-... otherwise; an S/N column on the equipment list that managers type into directly (Enter saves, Tab moves down), a pencil to retype the asset code, and an S/N missing filter | Done |
| 0.7.8 | Maintenance and calibration dates (last done, next due, calibration interval) are edited on the asset form; the next date is worked out from the last one and the interval, and can be typed over | Done |
| **0.8** | Three identifiers: Equipment ID (internal, e.g. CTV20200077), Asset No. (finance, e.g. 103220100359) and S/N; photos picked on the create and edit forms (camera or gallery on a phone); the reason for a status change is optional; In production only for equipment fitted to a product in production, kept in step automatically; no editing in the lists | **Done** |
| 0.8.1 | Schedule dates open only once their tick is set; photo after photo can be taken and each dropped before saving, saved photos deleted from the edit form; a product needs no name; technicians add a set and fill it in straight away, one search box per role (Equipment ID, Asset No. or S/N), free machines first, busy ones greyed out | Done |
| 0.8.2 | One frame per process: set tabs, and each row is a role with the machine fitted to it in the chosen set — roles (managers) and machines (technicians too) saved together; Add set opens its tab | Done |
| **0.9** | Product documents from the TE share on SharePoint (test instructions, specs, schematics, BOMs, firmware, drawings): a Documents page to search and download them, and a Documents card on each product; `import_documents` loads a crawl, one product per model code; routine backups leave the documents out (`--with-documents` to include them) | **Done** |
| 0.9.1 | Documents stay on SharePoint: the app reads the TE folder synced by OneDrive (`EMA_DOCS_ROOT`) and follows it by itself, opens and downloads files on SharePoint (its permissions apply), and managers add or replace files from a product, which OneDrive uploads; `sync_documents` replaces `import_documents` | Done |
| 0.9.2 | Products carry a plant (all existing ones set to CTV2); the Products page gets search (code, name or document name), customer and plant filters, and In production / All products tabs, with idle products on one compact line; the separate Documents page is gone: a product's documents open in tabs by type (TI, Test Spec, Schematic, BOM, Firmware …) with a link to its SharePoint folder | Done |
| 0.9.3 | Products page: a click anywhere on a product's row opens it; the detail panel is wider and can be widened to the full page (remembered); a Back button returns to the previous panel (product, process, set) or from a form | Done |
| 0.9.4 | Recent activity covers every log: equipment and spare parts added, edited (with the fields changed) or deleted, status changes, stock received/issued/counted, fitting, maintenance, calibration, incidents and documents added; the Overview panel shows 40 rows and scrolls, and an Activity page (See all) lists the latest 300 with a filter by kind | Done |
| 0.8 | Maintenance log screens and calendar view | |
| 0.8 | Incident reports and repair jobs, permission-checked attachments | |
| 0.9 | Calibration screens, certificate attachments, QR labels, phone-friendly logging | |
| 1.0 | Email reminders, MTBF/MTTR statistics, audit log viewer | |

---

## When to move to PostgreSQL

SQLite comfortably handles a single plant — a few thousand assets and up to
roughly 20 concurrent users. Reconsider when:

- `database is locked` errors start appearing regularly
- more than about 30 people use it at once
- several plants need to share one system

Switching means changing `DATABASES` in `config/settings.py` and re-running the
migrations against the new database. No domain code changes.
