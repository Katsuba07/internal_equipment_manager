"""
Small forms that open in a dialog instead of a page of their own.

A button with ``data-modal-form="<url>"`` fetches the form (see app.js), posts
it back, and reloads the page when it saves. The same URL opened directly still
renders the full page, so links and bookmarks keep working.
"""

from django.http import JsonResponse
from django.shortcuts import render


def wants_modal(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def render_modal(request, form, *, title: str, action: str, submit: str, note: str = "", subtitle: str = ""):
    return render(request, "core/_modal_form.html", {
        "form": form, "modal_title": title, "modal_action": action,
        "modal_submit": submit, "modal_note": note, "modal_subtitle": subtitle,
    })


def modal_saved(message: str = "") -> JsonResponse:
    """Tell the page to reload; the message is already in the message queue."""
    return JsonResponse({"reload": True, "message": message})
