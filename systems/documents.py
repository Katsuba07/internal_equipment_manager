"""
Product documents: open them, add new ones, check SharePoint for changes.
They are listed on each product (Products page), in tabs by type.

The files live on SharePoint (the TE folder). OneDrive syncs that folder to
this server and ``doc_sync`` reads it, so the list here follows SharePoint by
itself; opening a document goes to SharePoint, where its permissions apply.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from core.mixins import CanManageMixin
from core.models import Product

from .doc_sync import docs_root, store_upload, sync_documents
from .models import DocumentSection, ProductDocument


class DocumentSyncView(LoginRequiredMixin, View):
    """"Check now": re-read the synced folder straight away."""

    def post(self, request):
        result = sync_documents()
        if result is None:
            messages.error(request, "The SharePoint folder is not synced to this server yet.")
        else:
            messages.success(request, f"Checked SharePoint: {result}.")
        target = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            target = reverse("systems:products")
        return redirect(target)


class DocumentOpenView(LoginRequiredMixin, View):
    """Send the reader to the file on SharePoint. ``?download=1`` downloads it instead."""

    def get(self, request, pk):
        doc = get_object_or_404(ProductDocument, pk=pk)
        if doc.source:
            return redirect(doc.download_url if request.GET.get("download") == "1" else doc.open_url)
        # A record from before the app used SharePoint, with its own copy.
        if doc.file and doc.file.storage.exists(doc.file.name):
            return FileResponse(doc.file.open("rb"), as_attachment=True, filename=doc.file_name)
        raise Http404("This document has no file.")


class DocumentUploadView(CanManageMixin, View):
    """Add or replace documents of a product; they go to its folder on SharePoint."""

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        back = reverse("systems:products") + f"?product={product.pk}"
        section = request.POST.get("section")
        uploads = request.FILES.getlist("files")
        if section not in DocumentSection.values or not uploads:
            messages.error(request, "Choose a type and at least one file.")
            return redirect(back)
        if docs_root() is None:
            messages.error(request, "The SharePoint folder is not synced to this server yet.")
            return redirect(back)
        names = [store_upload(product, section, upload, request.user).file_name for upload in uploads]
        messages.success(
            request,
            f"Added to SharePoint: {', '.join(names)}. OneDrive uploads them within a minute.",
        )
        return redirect(back)
