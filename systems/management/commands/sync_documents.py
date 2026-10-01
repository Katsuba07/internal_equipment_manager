"""
Bring the product documents in line with the SharePoint TE folder.

The folder is synced to this server by OneDrive (``EMA_DOCS_ROOT``). The
Products page does this by itself every couple of minutes; run it by hand
after a big change. ``--drop-local-copies`` deletes files the app kept itself
before it read SharePoint directly.

    manage.py sync_documents
    manage.py sync_documents --drop-local-copies
"""

from django.core.management.base import BaseCommand, CommandError

from systems.doc_sync import docs_root, sync_documents
from systems.models import ProductDocument


class Command(BaseCommand):
    help = "Re-read the synced SharePoint folder of product documents."

    def add_arguments(self, parser):
        parser.add_argument("--drop-local-copies", action="store_true",
                            help="Delete files the app stored itself before it used SharePoint.")

    def handle(self, *args, **options):
        if docs_root() is None:
            raise CommandError(
                "EMA_DOCS_ROOT is not set to a folder that exists. Sync the TE folder with "
                "OneDrive, then put its path in .env as EMA_DOCS_ROOT."
            )
        result = sync_documents()
        self.stdout.write(self.style.SUCCESS(f"Synced: {result}"))
        for problem in result.errors[:10]:
            self.stdout.write(f"  {problem}")
        if options["drop_local_copies"]:
            dropped = 0
            for doc in ProductDocument.objects.exclude(file=""):
                doc.file.storage.delete(doc.file.name)
                doc.file = ""
                doc.save(update_fields=["file", "updated_at"])
                dropped += 1
            self.stdout.write(self.style.SUCCESS(f"Removed {dropped} local copies; SharePoint has the files."))
