"""Product documents kept on SharePoint and read through the OneDrive-synced folder."""

import shutil
import tempfile
from io import StringIO
from pathlib import Path
from urllib.parse import quote

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Customer, Product, Role
from core.tests import BaseFixtureMixin
from systems.doc_sync import product_codes, sync_documents
from systems.models import DocumentSection, ProductDocument

FOLDER = "/sites/CTV/Shared Documents/CTV3/MP lines Prepare Setup CTVN CTV3/TE"
SITE = "https://computimehk.sharepoint.com"


class DocumentTests(BaseFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Customer.objects.create(code="KRAIN", name="K-Rain")
        Customer.objects.create(code="BAF", name="BAF")

    def setUp(self):
        cache.clear()
        self.root = Path(tempfile.mkdtemp(prefix="ema-te-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        settings = override_settings(EMA_DOCS_ROOT=self.root, EMA_DOCS_SHAREPOINT_SITE=SITE,
                                     EMA_DOCS_SHAREPOINT_FOLDER=FOLDER)
        settings.enable()
        self.addCleanup(settings.disable)
        for path, content in {
            "KMCB111-121-141/TI/TI-KMCB111-001.pdf": b"%PDF ti",
            "BAF1950/BOM/F04RBAF1950.xlsx": b"bom",
            "BAF1950/Testing Specification/BAF1950 test spec.pdf": b"%PDF spec",
            "Packing List.xlsx": b"general",
            "BAF1950/BOM/~$F04RBAF1950.xlsx": b"office lock file",
        }.items():
            self.write(path, content)
        (self.root / "RMMCT01").mkdir()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    # --- reading the synced folder ----------------------------------------------

    def test_folders_become_products_and_files_documents(self):
        result = sync_documents()
        self.assertEqual(result.created, 4)                                  # the lock file is ignored
        self.assertEqual(
            sorted(Product.objects.values_list("code", flat=True)),
            ["BAF1950", "KMCB111", "KMCB121", "KMCB141", "RMMCT01"],
        )
        ti = ProductDocument.objects.get(file_name="TI-KMCB111-001.pdf")
        self.assertEqual(ti.section, DocumentSection.TI)
        self.assertEqual(sorted(ti.products.values_list("code", flat=True)), ["KMCB111", "KMCB121", "KMCB141"])
        self.assertEqual(Product.objects.get(code="KMCB121").customer.code, "KRAIN")
        self.assertEqual(ti.source, f"{FOLDER}/KMCB111-121-141/TI/TI-KMCB111-001.pdf")
        self.assertFalse(ti.file)                                          # no copy kept by the app

    def test_changes_on_sharepoint_follow_by_themselves(self):
        sync_documents()
        self.write("BAF1950/BOM/F04RBAF1950.xlsx", b"bom, revised and longer")
        self.write("BAF1950/Firmware/v2.hex", b":00")
        (self.root / "Packing List.xlsx").unlink()
        result = sync_documents()
        self.assertEqual((result.created, result.updated, result.removed), (1, 1, 1))
        self.assertFalse(ProductDocument.objects.filter(file_name="Packing List.xlsx").exists())
        self.assertEqual(ProductDocument.objects.get(file_name="v2.hex").section, DocumentSection.FIRMWARE)

    def test_products_found_on_the_share_are_made_at_ctv2(self):
        sync_documents()
        self.assertEqual(set(Product.objects.values_list("plant", flat=True)), {"CTV2"})

    def test_split_codes(self):
        self.assertEqual(product_codes("KMCV041-042-141"), ["KMCV041", "KMCV042", "KMCV141"])
        self.assertEqual(product_codes("BAF7350-BAF7450"), ["BAF7350", "BAF7450"])

    def test_the_page_checks_again_once_a_while_has_passed(self):
        self.login(Role.VIEWER)
        self.client.get(reverse("systems:products"))
        self.assertEqual(ProductDocument.objects.count(), 4)
        self.write("BAF1950/TI/new.pdf", b"%PDF")
        self.client.get(reverse("systems:products"))                         # too soon: not re-read
        self.assertEqual(ProductDocument.objects.count(), 4)
        self.client.post(reverse("systems:document_sync"), {"next": reverse("systems:products")})
        self.assertEqual(ProductDocument.objects.count(), 5)

    # --- opening on SharePoint --------------------------------------------------

    def test_opening_goes_to_sharepoint(self):
        sync_documents()
        doc = ProductDocument.objects.get(file_name="BAF1950 test spec.pdf")
        self.login(Role.VIEWER)
        response = self.client.get(reverse("systems:document_open", args=[doc.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], SITE + quote(doc.source) + "?web=1")
        response = self.client.get(reverse("systems:document_open", args=[doc.pk]) + "?download=1")
        self.assertTrue(response["Location"].startswith(SITE + "/sites/CTV/_layouts/15/download.aspx?SourceUrl="))

    def test_searching_products_finds_them_by_document_name(self):
        sync_documents()
        self.login(Role.VIEWER)
        body = self.client.get(reverse("systems:products"), {"show": "all", "q": "TI-KMCB111"}).content.decode()
        for code in ("KMCB111", "KMCB121", "KMCB141"):
            self.assertIn(code, body)
        self.assertNotIn(f'href="?product={Product.objects.get(code="BAF1950").pk}"', body)
        self.assertIn("documents from", body)

    def test_a_search_by_document_name_still_counts_every_document(self):
        from systems.services import products_overview

        sync_documents()
        self.write("BAF1950/TI/TI-BAF1950.pdf", b"%PDF")
        sync_documents()
        rows = [row for group in products_overview(show_all=True, query="test spec") for row in group.products]
        self.assertEqual([row["product"].code for row in rows], ["BAF1950"])
        self.assertEqual(rows[0]["product"].doc_count, 3)

    def test_the_product_shows_its_documents_in_tabs_by_type(self):
        sync_documents()
        product = Product.objects.get(code="BAF1950")
        self.login(Role.VIEWER)
        body = self.client.get(reverse("systems:product_panel", args=[product.pk]),
                               HTTP_HX_REQUEST="true").content.decode()
        self.assertIn('data-tab="TEST_SPEC"', body)
        self.assertIn('data-tab="BOM"', body)
        self.assertNotIn('data-tab="FIRMWARE"', body)                         # no firmware: no tab
        self.assertIn("BAF1950 test spec.pdf", body)

    def test_signing_in_is_required(self):
        sync_documents()
        doc = ProductDocument.objects.first()
        self.assertIn("/login/", self.client.get(reverse("systems:document_open", args=[doc.pk]))["Location"])
        self.assertIn("/login/", self.client.get(reverse("systems:products"))["Location"])

    # --- adding from the app ----------------------------------------------------

    def test_a_manager_adds_a_file_into_the_product_s_own_folder(self):
        sync_documents()
        product = Product.objects.get(code="BAF1950")
        self.login(Role.MANAGER)
        self.client.post(reverse("systems:document_upload", args=[product.pk]), {
            "section": DocumentSection.TEST_SPEC,
            "files": [SimpleUploadedFile("BAF1950 spec rev B.pdf", b"%PDF new")],
        })
        # the spelling already on the share is reused
        self.assertEqual((self.root / "BAF1950/Testing Specification/BAF1950 spec rev B.pdf").read_bytes(), b"%PDF new")
        doc = ProductDocument.objects.get(file_name="BAF1950 spec rev B.pdf")
        self.assertEqual(doc.section, DocumentSection.TEST_SPEC)
        self.assertEqual(doc.uploaded_by, self.users[Role.MANAGER])

    def test_the_same_name_replaces_the_file(self):
        sync_documents()
        product = Product.objects.get(code="BAF1950")
        self.login(Role.MANAGER)
        self.client.post(reverse("systems:document_upload", args=[product.pk]), {
            "section": DocumentSection.BOM, "files": [SimpleUploadedFile("F04RBAF1950.xlsx", b"new bom")],
        })
        self.assertEqual((self.root / "BAF1950/BOM/F04RBAF1950.xlsx").read_bytes(), b"new bom")
        self.assertEqual(ProductDocument.objects.filter(file_name="F04RBAF1950.xlsx").count(), 1)

    def test_a_product_without_papers_gets_its_own_folder(self):
        sync_documents()
        product = Product.objects.get(code="RMMCT01")
        self.login(Role.MANAGER)
        self.client.post(reverse("systems:document_upload", args=[product.pk]), {
            "section": DocumentSection.TI, "files": [SimpleUploadedFile("TI-RMMCT01.pdf", b"%PDF")],
        })
        self.assertTrue((self.root / "RMMCT01/TI/TI-RMMCT01.pdf").exists())

    def test_technicians_cannot_add(self):
        sync_documents()
        product = Product.objects.get(code="BAF1950")
        self.login(Role.TECHNICIAN)
        self.client.post(reverse("systems:document_upload", args=[product.pk]), {
            "section": DocumentSection.TI, "files": [SimpleUploadedFile("x.pdf", b"%PDF")],
        })
        self.assertFalse((self.root / "BAF1950/TI/x.pdf").exists())

    def test_the_product_panel_lists_its_documents_and_the_upload(self):
        sync_documents()
        product = Product.objects.get(code="BAF1950")
        self.login(Role.MANAGER)
        body = self.client.get(reverse("systems:product_panel", args=[product.pk]),
                               HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("BAF1950 test spec.pdf", body)
        self.assertIn("Add to SharePoint", body)

    def test_the_command_reports_when_nothing_is_synced(self):
        with override_settings(EMA_DOCS_ROOT=None):
            with self.assertRaises(Exception):
                call_command("sync_documents", stdout=StringIO())
        out = StringIO()
        call_command("sync_documents", stdout=out)
        self.assertIn("Synced: 4 new", out.getvalue())
