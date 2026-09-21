# Operations Guide — Equipment Manager

For whoever runs and looks after the system. No programming knowledge assumed.

---

## Contents

1. [How the system works](#1-how-the-system-works)
2. [First-time setup](#2-first-time-setup)
3. [Starting and stopping](#3-starting-and-stopping)
4. [Run as a Windows service](#4-run-as-a-windows-service)
5. [Backups](#5-backups)
6. [Restoring after a failure](#6-restoring-after-a-failure)
7. [Users and roles](#7-users-and-roles)
7b. [Plants (CTV1, CTV2, CTVN)](#7b-plants-ctv1-ctv2-ctvn)
7c. [Scheduled maintenance](#7c-scheduled-maintenance)
8. [Importing your asset list](#8-importing-your-asset-list)
9. [The Products page](#9-the-products-page)
9b. [Spare parts and parts lists](#9b-spare-parts-and-parts-lists)
10. [Common problems](#10-common-problems)
11. [Access from outside the plant](#11-access-from-outside-the-plant)

---

## 1. How the system works

This is a **website running on your own network**, not software installed on each PC.

```
   [SERVER — one PC that stays on]
   Runs the application, holds all the data
                │
                │  plant LAN
    ┌───────────┼───────────┬──────────────┐
    │           │           │              │
  TE office   Manager    Technician's   Line PC
    PC          PC         phone
```

Everyone else just opens a browser (Chrome, Edge) and goes to the server's address. Nothing to install.

### Three things worth remembering

> **1. The server PC must stay on.** Turn it off and nobody can reach the system.
>
> **2. All data lives in the `data\` folder on the server.** Lose that folder and you lose everything, which is why section 5 exists.
>
> **3. Never put `data\` on a mapped network drive.** SQLite relies on file locking that is not reliable over SMB, and **the database can be corrupted**. A network share is for holding *backups*, nothing else.

---

## 2. First-time setup

Do this **once**, on the PC that will be the server.

### Step 1 — Install Python

1. Go to https://www.python.org/downloads/ and download the latest release.
2. Run the installer. **On the first screen, tick "Add python.exe to PATH".**
   Skipping this is the single most common cause of the next steps failing.
3. Click "Install Now" and wait.

### Step 2 — Copy the project to the server

Copy the whole project folder to a permanent location on a **local disk**, for example `D:\EMA`.
Avoid Desktop and Downloads — those get cleaned out.

### Step 3 — Run the setup script

1. Open the `scripts` folder.
2. Right-click **`install.ps1`** → **Run with PowerShell**.
   *Choose "Run as administrator" so it can open the firewall port for you.*
3. Wait a few minutes. It stops to ask for an administrator account.
4. Enter a username, email (optional) and password.
   **Nothing appears while you type the password — that is normal.** Type it and press Enter.

If Windows says *running scripts is disabled*, open PowerShell and run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Answer `Y`, then run the script again.

### Step 4 — Set the role on that account

1. Start the system (section 3) and sign in with the account you just created.
2. Go to **Admin site** (top-right menu) → **Users**.
3. Open your account, find **Access**, set **Role = Administrator**, and save.

---

## 3. Starting and stopping

### Start

Right-click **`scripts\run-server.ps1`** → **Run with PowerShell**.

A console window appears showing the address. **Leave it open.**

### Where to go

| From | Address |
|---|---|
| The server itself | `http://localhost:8000` |
| Any other machine on the network | `http://<server-ip>:8000` |

The script prints the IP address on start-up. To find it again, run `ipconfig` on the server and look for **IPv4 Address**.

> **Tip:** put a desktop shortcut to that address on the PCs in the test area so nobody has to type it.

### Stop

Press **Ctrl + C** in the console window, or close it.

---

## 4. Run as a Windows service

The method in section 3 has a drawback: after a reboot or power cut, someone has to start it by hand. Registering it as a **Windows service** solves that.

### Install NSSM (once)

1. Download NSSM from https://nssm.cc/download (latest release).
2. Unzip it, open the `win64` folder, and copy `nssm.exe` into `C:\Windows\System32`.

### Register the service

Open PowerShell **as Administrator**, replacing `D:\EMA` with your real path:

```powershell
nssm install EquipmentManager "D:\EMA\.venv\Scripts\waitress-serve.exe"
nssm set EquipmentManager AppParameters "--listen=0.0.0.0:8000 --threads=8 config.wsgi:application"
nssm set EquipmentManager AppDirectory "D:\EMA"
nssm set EquipmentManager AppEnvironmentExtra "DJANGO_SETTINGS_MODULE=config.settings"
nssm set EquipmentManager Start SERVICE_AUTO_START
nssm set EquipmentManager AppStdout "D:\EMA\data\service.log"
nssm set EquipmentManager AppStderr "D:\EMA\data\service.log"
nssm start EquipmentManager
```

### The check people skip

**Reboot the server**, wait two minutes, then open the system from another machine.
This is the step that catches a service which did not actually come back on its own.

### Service commands

```powershell
nssm status  EquipmentManager    # is it running?
nssm restart EquipmentManager    # after an update
nssm stop    EquipmentManager
nssm remove  EquipmentManager confirm
```

---

## 5. Backups

**This is the most important section here.** Disks fail.

### Run a backup by hand

```powershell
.\scripts\backup.ps1 -Destination "\\fileserver\Backup\EMA"
```

It writes a consistent copy of the database, zips the attachments, **opens the copy to confirm it is readable**, then deletes anything older than the retention limit (30 by default).

### Schedule it nightly

1. Open **Task Scheduler**.
2. Choose **Create Task** (not "Create Basic Task").
3. **General** tab: name it `Equipment Manager backup`, select **Run whether user is logged on or not**.
4. **Triggers** → **New**: Daily, at **22:00** (outside working hours).
5. **Actions** → **New**:
   - Program/script: `powershell.exe`
   - Add arguments:
     ```
     -NoProfile -ExecutionPolicy Bypass -File "D:\EMA\scripts\backup.ps1" -Destination "\\fileserver\Backup\EMA"
     ```
6. Click OK and enter your Windows password when prompted.

### Check it a week later

Open the backup folder and confirm there are **seven files with different dates**. A scheduled job runs silently; without this check you can find out months later that it stopped working on day two.

---

## 6. Restoring after a failure

1. Stop the system: `nssm stop EquipmentManager` (or close the console window).
2. In the server's `data\` folder, rename the current `ema.sqlite3` to `ema-broken.sqlite3`.
   *Do not delete it — some data may still be recoverable.*
3. Copy the backup you want (for example `ema-20260917-220000.sqlite3`) into `data\` and **rename it to `ema.sqlite3`**.
4. If you also need the attachments, unzip the matching `uploads-*.zip` into `data\uploads\`.
5. Start the system again and check the data.

> Anything entered after the backup was taken is gone. That is why the schedule is daily.

---

## 7. Users and roles

Go to **Admin site** → **Users** (administrators only).

### The four roles

| Role | Can do |
|---|---|
| **Administrator** | Everything, including managing users and deleting records |
| **Manager** | View everything, add and edit equipment, plan schedules, export |
| **Technician** | Log maintenance, repairs and calibration, report incidents, change asset status |
| **Viewer** | View and export only |

Give people the **lowest role that still lets them do their job**. Someone who only looks things up should be a Viewer.

### Adding someone

Admin site → Users → **Add** (top right) → fill in username, full name, role and password.

### When someone leaves

**Do not delete the account** — that erases the trail of what they recorded.
Open the account and **untick "Active"** instead. They can no longer sign in, and the history stays intact.

---

## 7b. Plants (CTV1, CTV2, CTVN)

Each **location** belongs to a plant (Admin site > Locations > Plant). An asset
takes the plant of the location it sits in, so moving it between plants is just
a change of location. **Spare parts** carry their own plant, because each store
holds its own stock.

Where it shows:

- **Equipment** and **Spare parts** lists: a Plant column and a plant filter.
- **Products**: the filter at the top shows only the sets on that plant's lines.
- **Overview**: a "By plant" line under the equipment tiles.

---

## 7c. Scheduled maintenance

On the asset form, tick **Maintenance required** and choose how often: 1 week,
1 month, 3 months, 6 months or 1 year.

- Saving creates (or updates) one plan called **Scheduled maintenance** for that
  asset, with the next date set from today, and it appears in the Maintenance
  list on the Overview page and on the asset page.
- Changing the interval moves the next date; unticking stops the round but keeps
  the record, so the history is not lost.
- Extra plans entered separately (a quarterly deep clean, say) are never touched
  by this tick.

---

## 8. Importing your asset list

### Prepare first

Create the catalogs in **Admin site**, because the spreadsheet refers to them by code:

- **Categories** — e.g. `FIX-ICT` / ICT fixture, `PSU` / Power supply
- **Locations** — e.g. `FCT-RM` / FCT Room
- **Suppliers** (optional)

### The steps

1. Go to **Equipment** → **Import**.
2. Click **Download template**. It comes with a *Reference* sheet listing every category, location and supplier code already in the system — no need to look them up.
3. Fill in the **Equipment** sheet. Columns with a **red header** are required. **Delete the example row** before uploading.
4. Upload the file and click **Import**.

> The whole file is validated **before anything is written**. If any row is wrong, nothing is imported and you get a list of problems with row numbers. Fix the spreadsheet and upload again — there is no risk of a half-finished import.

---

## 9. The Products page

One page shows every product by customer, the processes it goes through, and
the equipment in use at each one right now.

```
Customer > Product (RMMTT01) > Process (PROG, ICT, FCT ...) > Set #1, #2 > equipment in use
```

### Reading it

- Customers are groups you can fold. Only products **in production** are shown;
  tick **Include products not in production** to see the rest.
- Each process shows its sets. A green dot means the set is ready; red means a
  required role is empty, an asset is down, or a calibration has lapsed (hover
  for the reason).
- Click a **set** to open its details on the right: each role, the asset in it,
  the asset's parts with stock, and what is wrong if it is not ready.
- Click a **process code** to see or edit its roles; click a **product code** for
  its route.

### Changing things (all in the panel on the right)

| To ... | Do |
|---|---|
| Fit, change or remove equipment | Open the set > **Edit** > choose per role ("none" removes) > **Save** |
| Add a second set of a process | Open the process > **Add set** |
| Change what a process needs (e.g. add a scanner) | Open the process > pick an equipment type per row (**Add row** for more) > **Save roles**. Two of the same type are named automatically, e.g. Power supply 1 and 2 |
| Add or reorder processes | Open the product > **Add process**. To reorder, drag a process box by its name and drop it before or after another (on a phone or tablet, use the arrows in the product panel) |
| Mark a product in / out of production | Open the product > **Start** / **Stop** |
| Add a product | **New product** (top right): tick its processes; each gets its template roles and set #1 |

Every dropdown has **+ New** to create a missing customer, process, line,
category or asset without leaving the page (managers and administrators).
Technicians can change equipment on a set; managers also edit products,
processes and roles; administrators can delete.

Assets fitted in another set are greyed out in the dropdown; remove them there
first. The database will not let one asset sit in two sets.

### Process templates

**Admin site > Processes** holds the process list (PROG, ICT, FCT, Burn-in,
Hipot ...) and each one's starting roles. A template is copied when the process
is added to a product; changing it later does not alter products already set up.

### The "Still in use" tick

Products and parts have a **Still in use** tick on their edit form (not when
creating). Untick to retire something you want to keep in history: it
disappears from dropdowns. Delete it instead if it was a mistake.

### Deleting

Deleting a product, a process or a set is **one click** (administrators). The
confirmation page lists what goes and which assets are released. Equipment is
never deleted this way; each asset keeps its fitting history.

---

## 9b. Spare parts and parts lists

A test system has three tiers:

```
spare parts (probes, springs, relays)  ->  equipment (fixture, control box)  ->  BAF1950 FCT
```

### Step 1 — Build the spare parts list

**Spare parts → New part**: part number, description, type, unit, reorder point
and bin. Enter **Opening stock** once; after that the balance only changes
through **Receive**, **Issue** or a stocktake on the part page, so every change
has a date, a person and a reason. **Receive** and **Issue** open a small input
window over the page — fill it in, press **Record**, and the page updates where
you were. An **Issue** also asks which asset the part is going on: type a few
letters of the code or the name instead of hunting through a list — the assets
that carry this part on their own parts list are offered first, before anything
is typed. What was issued then shows on the part's history and on the asset's
own page. The same goes for **Change status** on an asset. Nothing is saved
until you press the button, and **Cancel** or `Esc` closes the window.

### Step 2 — Give each asset its parts list

Open the asset → **Edit** → **Parts**. Pick a part and enter the quantity, for
example `PRB-075-2A` × 96 on fixture `FIX-BAF1950`. **Add part row** adds more
lines; tick **Remove** to drop one. Each part appears once per asset — put the
total on one line.

Declaring parts does not take anything out of stock. When you actually replace
probes, record an **Issue** on the part.

### Where it shows

| Page | Shows |
|---|---|
| Asset page → **Parts** | What the asset is built with, and stock on hand for each part |
| Part page → **Used on equipment** | Every asset that carries this part and the total fitted |
| Products page → set panel | Each asset in the set with its parts and stock (click "n parts") |

Deleting a part (administrators, one click) also removes it from every parts list
and deletes its stock movements. The equipment is not touched.

---

## 9b2. Quick look from a list

On **Equipment** and **Spare parts**, clicking a row opens a panel on the right
with the photo, the main facts and the buttons you need — for an asset: where it
is fitted, calibration and maintenance due, open incidents and its parts; for a
part: stock, bin, supplier, last movement and which assets use it.

- Click another row to switch, **Esc** or **×** to close.
- **Open** goes to the full page. Ctrl+click on a row's code still opens the
  full page in a new tab.

---

## 9c. Photos

Every asset and spare part page has a **Photos** card.

- **Upload:** choose one or more image files (JPG, PNG) and press **Upload**.
  Large photos are shrunk automatically. Technicians and above can upload.
- **Main photo:** the first photo becomes the main one (star). Press the empty
  star under another photo to make it the main one.
- **View:** click a photo to open it large; click again to close.
- **Delete:** the bin icon under a photo (managers and administrators).

The main photo of each asset also shows beside it in a set's details on the
Products page, so the right unit can be recognised on the line.

Photos are stored in `data\uploads\` and are included in the nightly backup
(`uploads-*.zip`). They can only be opened by someone signed in.

---

## 10. Common problems

| Symptom | Cause and fix |
|---|---|
| Works on the server, not from other PCs | Firewall is blocking port 8000. Run `install.ps1` as Administrator, or add the rule manually in Windows Defender Firewall. |
| Nobody can reach it | The system is not running. Check `nssm status EquipmentManager`, or start `run-server.ps1`. |
| Worked yesterday, not today | The server's IP address changed. Ask IT for a **static IP** so it stops happening. |
| Page loads but looks unstyled | Static files were not collected. Run `.\.venv\Scripts\python.exe manage.py collectstatic --noinput` |
| "database is locked" errors | Sustained concurrent writing. Rare at this scale; if it becomes frequent, it is time to move to PostgreSQL. |
| Forgotten administrator password | On the server: `.\.venv\Scripts\python.exe manage.py changepassword <username>` |
| "Currently fitted in ..." when saving a set | Working as intended: the asset is in another set. Remove it there first. |
| A process template change does not show on a product | Templates are copied once. Edit the product's own role list on the process panel. |
| PowerShell refuses to run a script | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again. |

**Error log:** `data\ema.log` on the server records system errors. When asking for help, include the last few dozen lines.

---

## 11. Access from outside the plant

To reach the system from home or over mobile data, **do not forward a port on the router** — that is the fastest route to being attacked.

Two safe options:

1. **Cloudflare Tunnel** (free, recommended) — install `cloudflared` on the server; it creates an outbound tunnel with no inbound ports opened.
2. **Company VPN** — simplest if one already exists.

Once it is reachable from the internet, you **must** update `.env` on the server:

```
EMA_DEBUG=False
EMA_ALLOWED_HOSTS=ema.company.com
EMA_CSRF_TRUSTED_ORIGINS=https://ema.company.com
EMA_BEHIND_HTTPS_PROXY=True
```

Restart the service afterwards, and review everyone's passwords — once the system is on the internet, a weak password becomes a real exposure.

## Product documents (SharePoint)

The documents stay on SharePoint, in the TE folder
(`CTV3/MP lines Prepare Setup CTVN CTV3/TE` on the CTV site). OneDrive, signed
in with a company account on the server, syncs that folder to
`C:\Users\tobydo-ctv2\Computime Limited\CTV - TE`; `.env` points the app at it
with `EMA_DOCS_ROOT`.

- **Add or replace a document** on SharePoint (or from a product's Documents
  card in the app, managers only). The Documents page picks the change up by
  itself within two minutes, or at once with **Check now**.
- **Folder layout** decides everything: `<product folder>/<type folder>/<file>`.
  A product folder may name several products (`KMCB111-121-141`); type folders
  are TI, Test Spec (or Testing Specification), Schematic, BOM, Firmware,
  PCBA Drawing. A new product folder becomes a new product.
- **Opening** a document goes to SharePoint, so SharePoint's own permissions
  decide who can read it.
- **If OneDrive stops** (signed out, server rebuilt): the list stays as it was
  and files still open on SharePoint; sign OneDrive in again, sync the TE
  folder, check `EMA_DOCS_ROOT`, then run `python manage.py sync_documents`.
- Deleting a file on SharePoint removes it from the app on the next check. The
  app itself never deletes files on SharePoint.
