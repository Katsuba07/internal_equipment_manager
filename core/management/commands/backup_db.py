"""
Back up the database and attachments.

    python manage.py backup_db --dest "\\\\fileserver\\Backup\\EMA"

Uses SQLite's own backup API rather than copying the file, because while the
system is running in WAL mode a plain file copy can capture a snapshot that
is missing recent writes.
"""

import sqlite3
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Back up the database and uploaded files to a target folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dest", required=True, help=r"Target folder, e.g. \\fileserver\Backup\EMA"
        )
        parser.add_argument(
            "--keep", type=int, default=30, help="How many recent backups to keep (default 30)."
        )
        parser.add_argument(
            "--skip-uploads", action="store_true", help="Back up the database only."
        )
        parser.add_argument(
            "--with-documents", action="store_true",
            help="Also archive the product documents (large; they are kept on SharePoint anyway).",
        )

    def handle(self, *args, **options):
        destination = Path(options["dest"])
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise CommandError(
                f"Cannot create or reach the backup folder '{destination}'.\n"
                f"Details: {error}\n"
                "If this is a network share, check that the server account can write to it."
            )

        stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
        source_db = Path(settings.DATABASES["default"]["NAME"])
        if not source_db.exists():
            raise CommandError(f"No database found at {source_db}.")

        # --- Database ---
        target_db = destination / f"ema-{stamp}.sqlite3"
        self.stdout.write(f"Backing up database to {target_db.name}")
        source = target = None
        try:
            source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
            target = sqlite3.connect(target_db)
            source.backup(target)
            # Fold the WAL into the main file and switch the copy back to
            # rollback journalling, so the backup is exactly ONE file with no
            # -wal sidecar to forget when restoring.
            target.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            target.execute("PRAGMA journal_mode=DELETE;")
        except sqlite3.Error as error:
            raise CommandError(f"Database backup failed: {error}")
        finally:
            # Connections must be closed or SQLite leaves -wal and -shm behind.
            for connection in (target, source):
                if connection is not None:
                    connection.close()

        size_mb = target_db.stat().st_size / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f"  saved ({size_mb:.1f} MB)"))

        # --- Attachments ---
        uploads = Path(settings.MEDIA_ROOT)
        if not options["skip_uploads"] and uploads.exists() and any(uploads.rglob("*")):
            target_zip = destination / f"uploads-{stamp}.zip"
            self.stdout.write(f"Archiving attachments to {target_zip.name}")
            with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                for file_path in uploads.rglob("*"):
                    relative = file_path.relative_to(uploads)
                    # Product documents are hundreds of MB and SharePoint holds
                    # the originals; they are left out unless asked for.
                    if relative.parts[:1] == ("documents",) and not options["with_documents"]:
                        continue
                    if file_path.is_file():
                        archive.write(file_path, relative)
            size_mb = target_zip.stat().st_size / 1024 / 1024
            self.stdout.write(self.style.SUCCESS(f"  archived ({size_mb:.1f} MB)"))

        # --- Verify the copy we just made ---
        # A backup nobody has ever opened is not yet known to be a backup.
        self.stdout.write("Verifying the backup...")
        check = None
        try:
            check = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
            result = check.execute("PRAGMA integrity_check;").fetchone()[0]
            asset_count = check.execute("SELECT COUNT(*) FROM equipment_equipment;").fetchone()[0]
        except sqlite3.Error as error:
            raise CommandError(f"Could not open the backup just written: {error}")
        finally:
            if check is not None:
                check.close()

        if result != "ok":
            raise CommandError(f"Backup is corrupt: {result}")
        self.stdout.write(self.style.SUCCESS(f"  verified — {asset_count} assets present"))

        # --- Prune old copies ---
        keep = options["keep"]
        for pattern in ("ema-*.sqlite3", "uploads-*.zip"):
            backups = sorted(destination.glob(pattern), reverse=True)
            for old in backups[keep:]:
                old.unlink(missing_ok=True)
                self.stdout.write(f"  removed old backup: {old.name}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Done. Backups are in {destination}"))
