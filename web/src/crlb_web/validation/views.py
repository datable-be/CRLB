"""Views of the validation interface: the entry list, the entry page, page images and review decisions."""

import sqlite3
from contextlib import closing
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.http import (
    FileResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.http.response import HttpResponseBase
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from crlb import db
from crlb import review as crlb_review
from crlb.extraction.review import DPI
from crlb_web.validation import entry as data
from crlb_web.validation.models import SECTIONS


def current_user(request: HttpRequest) -> User | AnonymousUser:
    """Return the user that the authentication middleware set on the request."""
    return request.user  # ty: ignore[unresolved-attribute]


def permissions(request: HttpRequest) -> dict[str, object]:
    """Return what the user may do: add remarks, and review which sections."""
    user = current_user(request)
    return {
        "can_remark": user.has_perm("validation.remark"),
        "can_review": sorted(
            {s for s in SECTIONS.values() if user.has_perm(f"validation.review_{s}")}
        ),
    }


def entries(request: HttpRequest) -> HttpResponse:
    """Show the entries of the active runs with their review progress."""
    with closing(data.connect()) as conn:
        rows = data.entry_list(conn)
    return render(request, "validation/entries.html", {"entries": rows})


def entry(request: HttpRequest, part: str, number: str) -> HttpResponse:
    """Show the review page of one entry."""
    with closing(data.connect()) as conn:
        context = data.entry_page(conn, part, number)
    context |= permissions(request)
    return render(request, "validation/entry.html", context)


def page_image(
    request: HttpRequest, document_id: int, page_index: int
) -> HttpResponseBase:
    """Return a PDF page as PNG, rendered once from pdfs.sqlite and then served from the cache."""
    path = settings.PAGE_CACHE / f"{document_id}_{page_index}.png"
    if not path.exists():
        conn = data.connect()
        try:
            db.attach_pdfs(conn, settings.CRLB_PDFS)
            pdf = db.open_pdf(conn, document_id)
            if not 0 <= page_index < len(pdf):
                return HttpResponseBadRequest("no such page")
            png = pdf[page_index].get_pixmap(dpi=DPI, annots=False).tobytes("png")
        finally:
            conn.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(png)
        tmp.replace(path)
    return FileResponse(path.open("rb"), content_type="image/png")


@require_POST
def review(request: HttpRequest) -> HttpResponseBase:
    """Store a decision on a row: accept, reject or correct (per section) or a remark, then go back to the row."""
    table = request.POST.get("table", "")
    action = request.POST.get("action", "")
    section = SECTIONS.get(table)
    try:
        row_id = int(request.POST.get("row_id", ""))
    except ValueError:
        return HttpResponseBadRequest("no row")
    if section is None:
        return HttpResponseBadRequest("this table cannot be reviewed")
    needed = "remark" if action == "comment" else f"review_{section}"
    if not current_user(request).has_perm(f"validation.{needed}"):
        return HttpResponseForbidden("you may not do this")
    column = request.POST.get("column") or None
    conn = data.connect()
    try:
        crlb_review.record(
            conn,
            table,
            row_id,
            action,
            current_user(request).get_username(),
            column,
            request.POST.get("value", "").strip(),
            request.POST.get("comment", "").strip() or None,
        )
    except ValueError as invalid:
        return HttpResponseBadRequest(str(invalid))
    except sqlite3.OperationalError:
        return HttpResponse("the database is busy; try again", status=503)
    finally:
        conn.close()
    part, number = request.POST.get("part", ""), request.POST.get("number", "")
    if not part:
        return redirect("entries")
    url = reverse("entry", args=[part, number])
    return redirect(f"{url}#{quote(f'row-{table}-{row_id}')}")
