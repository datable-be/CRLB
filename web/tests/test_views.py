"""Tests for the pages and the review decisions of the validation interface."""

import sqlite3
from collections.abc import Callable

import pytest
from django.test import Client

Open = Callable[[], sqlite3.Connection]
Login = Callable[..., Client]

ENTRY = "/entry/XIX (4)/4/"


def post(client: Client, **fields: str) -> int:
    """Post a decision on the test entry and return the status code."""
    data = {"part": "XIX (4)", "number": "4", **fields}
    return client.post("/review/", data).status_code


def reviews(open_db: Open) -> list[tuple[str, str, str | None]]:
    """Return the stored decisions as (table, action, column)."""
    with open_db() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT table_name, action, column_name FROM reviews ORDER BY id"
            )
        ]


@pytest.mark.django_db
def test_pages_need_login(crlb_db: Open) -> None:
    """Without login, every page redirects to the login page."""
    for url in ("/", ENTRY):
        response = Client().get(url)
        assert response.status_code == 302 and "/login/" in response["Location"]


def test_entry_list_and_page(crlb_db: Open, client_as: Login) -> None:
    """A viewer sees the entry in the list and its records, without review buttons."""
    client = client_as("Viewer")
    assert "A Title" in client.get("/").content.decode()
    page = client.get(ENTRY).content.decode()
    assert "Jan Smit" in page and "Smit, Jan" in page
    assert 'value="accept"' not in page and 'name="comment" placeholder' not in page


def test_viewer_cannot_post(crlb_db: Open, client_as: Login) -> None:
    """A viewer can neither review nor remark."""
    client = client_as("Viewer")
    assert post(client, table="ro_collection_stays", row_id="1", action="accept") == 403
    assert (
        post(
            client,
            table="ro_collection_stays",
            row_id="1",
            action="comment",
            comment="x",
        )
        == 403
    )
    assert reviews(crlb_db) == []


def test_commenter_can_only_remark(crlb_db: Open, client_as: Login) -> None:
    """A commenter adds remarks but cannot accept."""
    client = client_as("Commenter")
    assert (
        post(
            client,
            table="ro_collection_stays",
            row_id="1",
            action="comment",
            comment="check",
        )
        == 302
    )
    assert post(client, table="ro_collection_stays", row_id="1", action="accept") == 403
    assert reviews(crlb_db) == [("ro_collection_stays", "comment", None)]


def test_section_permission(crlb_db: Open, client_as: Login) -> None:
    """A provenance-only reviewer can correct provenance but not an object field."""
    client = client_as(perms=("review_provenance",))
    assert (
        post(
            client,
            table="ro_objects",
            row_id="1",
            action="correct",
            column="title_value",
            value="X",
        )
        == 403
    )
    assert post(client, table="ro_collection_stays", row_id="1", action="reject") == 302
    with crlb_db() as conn:
        assert (
            conn.execute("SELECT status FROM ro_collection_stays").fetchone()[0]
            == "rejected"
        )


def test_correction_and_effective_value(crlb_db: Open, client_as: Login) -> None:
    """A correction is stored, sets the status and shows as the effective value."""
    client = client_as("Reviewer")
    status = post(
        client,
        table="ro_collection_stays",
        row_id="1",
        action="correct",
        column="holder_text",
        value="Jan Smits",
    )
    assert status == 302
    page = client.get(ENTRY).content.decode()
    assert 'title="extracted: Jan Smit">Jan Smits</span>' in page
    with crlb_db() as conn:
        assert (
            conn.execute("SELECT status FROM ro_collection_stays").fetchone()[0]
            == "corrected"
        )


def test_non_editable_column_is_refused(crlb_db: Open, client_as: Login) -> None:
    """Correcting an id or run column gives a 400 and stores nothing."""
    client = client_as("Reviewer")
    assert (
        post(
            client,
            table="ro_collection_stays",
            row_id="1",
            action="correct",
            column="run_id",
            value="9",
        )
        == 400
    )
    assert post(client, table="segments", row_id="1", action="accept") == 400
    assert reviews(crlb_db) == []


def test_choose_candidate(crlb_db: Open, client_as: Login) -> None:
    """Choosing a candidate corrects the normalised value to its label."""
    client = client_as("Reviewer")
    status = post(
        client,
        table="normalised_values",
        row_id="1",
        action="correct",
        column="normalised_value",
        value="Smit, Jan (RKD)",
        comment="candidate: rkd_collections term 7",
    )
    assert status == 302
    with crlb_db() as conn:
        row = conn.execute("SELECT new_value, comment FROM reviews").fetchone()
        assert tuple(row) == ("Smit, Jan (RKD)", "candidate: rkd_collections term 7")
        assert (
            conn.execute("SELECT status FROM normalised_values").fetchone()[0]
            == "corrected"
        )
