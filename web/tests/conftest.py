"""Fixtures of the validation interface tests: a tiny hand-made crlb.sqlite and users per role."""

import io
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.test import Client
from pytest_django.fixtures import Settings

from crlb.db import connect

WORDS = ["No.", "4", "Jan", "Smit,", "Antwerp;", "Museum"]


ROWS = """
INSERT INTO parts (part) VALUES ('XIX (4)');
INSERT INTO documents (id, run_id, path, sha256, size, part, section, text_source, page_count)
    VALUES (1, 1, 'x.pdf', '', 0, 'XIX (4)', 'main', 'born_digital', 1);
INSERT INTO pages (id, document_id, page_index, rotation, width, height, mediabox, text)
    VALUES (1, 1, 0, 0, 100, 200, '[0, 0, 100, 200]', '');
INSERT INTO correction_runs (id, started_at, step, options) VALUES (1, '', '2a', '{}');
INSERT INTO segmentation_runs (id, started_at, options) VALUES (1, '', '{}');
INSERT INTO segments (id, run_id, document_id, parent_id, kind, label, first_word_id, last_word_id, rule, confidence)
    VALUES (1, 1, 1, NULL, 'entry', '4', 1, 6, 'r', 'certain'),
           (2, 1, 1, 1, 'field', 'provenance', 3, 6, 'r', 'certain'),
           (3, 1, 1, 2, 'item', '1', 3, 6, 'r', 'certain');
INSERT INTO ro_runs (id, started_at, field, method, segmentation_run_id, options)
    VALUES (1, '', 'objects', 'rules', 1, '{}'), (2, '', 'references', 'rules', 1, '{}'),
           (3, '', 'provenance', 'rules', 1, '{}');
INSERT INTO active_runs (step, run_id, set_at)
    VALUES ('2', 1, ''), ('3', 1, ''), ('4:objects', 1, ''), ('4:references', 2, ''), ('4:provenance', 3, '');
INSERT INTO ro_objects (id, segment_id, first_word_id, last_word_id, run_id, part, crlb_number, title_value)
    VALUES (1, 1, 1, 6, 1, 'XIX (4)', '4', 'A Title');
INSERT INTO ro_collection_stays (id, object_id, segment_id, first_word_id, last_word_id, run_id, method,
    position, holder_text, collection_is_current) VALUES (1, 1, 3, 3, 6, 3, 'rules', 1, 'Jan Smit', 0);
INSERT INTO enrichment_runs (id, started_at, part_of_step, method, ro_run_ids, options)
    VALUES (1, '', '5b', 'rules', '[1, 3]', '{}');
"""


def build(path: Path) -> None:
    """Write a crlb.sqlite with one entry: an object and one provenance stage with a normalised value."""
    conn = connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(ROWS)
    for k, word in enumerate(WORDS, start=1):
        conn.execute(
            "INSERT INTO words (id, page_id, block_no, line_no, word_no, x0, y0, x1, y1, text, font, size, flags, styles)"
            " VALUES (?, 1, 0, 0, ?, ?, 10, ?, 20, ?, 'f', 10, 0, 1)",
            (k, k, k * 10, k * 10 + 8, word),
        )
        conn.execute(
            "INSERT INTO corrected_words (run_id, page_id, first_word_id, last_word_id, text, x0, y0, x1, y1)"
            " VALUES (1, 1, ?, ?, ?, 0, 0, 0, 0)",
            (k, k, word),
        )
    candidates = [
        {
            "term_id": 7,
            "vocabulary": "rkd_collections",
            "label": "Smit, Jan",
            "score": 0.9,
            "evidence": [],
        }
    ]
    conn.execute(
        "INSERT INTO normalised_values (id, run_id, table_name, row_id, column_name, value_text,"
        " normalised_value, rule, score, candidates, status) VALUES (1, 1, 'ro_collection_stays', 1,"
        " 'holder_text', 'Jan Smit', 'Smit, Jan', 'review', 0.9, ?, 'review')",
        (json.dumps(candidates),),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def crlb_db(tmp_path: Path, settings: Settings) -> Callable[[], sqlite3.Connection]:
    """Point the app at a fresh hand-made crlb.sqlite; return a function that opens it."""
    path = tmp_path / "crlb.sqlite"
    build(path)
    settings.CRLB_DB = path
    settings.PAGE_CACHE = tmp_path / "pages"

    def open_db() -> sqlite3.Connection:
        """Open the test database."""
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return open_db


@pytest.fixture
def client_as(db: None) -> Callable[..., Client]:
    """Return a function that logs in a new user with the given groups and extra permissions."""
    call_command("setup_roles", stdout=io.StringIO())

    def login(*groups: str, perms: tuple[str, ...] = ()) -> Client:
        """Create a user in these groups and return a logged-in client."""
        user = User.objects.create_user("_".join(("u", *groups, *perms)), password="pw")
        for group in groups:
            user.groups.add(Group.objects.get(name=group))
        for perm in perms:
            user.user_permissions.add(Permission.objects.get(codename=perm))
        client = Client()
        client.force_login(user)
        return client

    return login
