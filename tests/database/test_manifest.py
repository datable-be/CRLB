"""Tests for reading and checking the manifests."""

from collections.abc import Callable
from pathlib import Path

import pytest

from crlb.database.manifest import PartRow, read_documents, read_parts, validate

PARTS = [PartRow("XIX (4)", None, None, None)]


def test_valid_manifest_has_no_problems(corpus: Path) -> None:
    """The fixture manifest is valid, and empty cells and years are converted."""
    documents = read_documents(corpus / "data_manifest" / "documents.csv")
    parts = read_parts(corpus / "data_manifest" / "parts.csv")
    assert documents[0].volume is None
    assert parts[0].year == 2016
    assert validate(documents, parts, corpus) == []


def test_missing_file_is_a_problem(tmp_path: Path, write_documents: Callable) -> None:
    """A row whose file does not exist is reported."""
    documents = write_documents({"path": "missing.pdf"})
    assert validate(documents, PARTS, tmp_path) == ["missing.pdf: file not found"]


def test_duplicate_path_is_a_problem(tmp_path: Path, write_documents: Callable) -> None:
    """A path listed twice is reported."""
    (tmp_path / "a.pdf").touch()
    documents = write_documents({"path": "a.pdf"}, {"path": "a.pdf"})
    assert validate(documents, PARTS, tmp_path) == ["a.pdf: listed 2 times"]


def test_dangling_excerpt_of_is_a_problem(
    tmp_path: Path, write_documents: Callable
) -> None:
    """excerpt_of must refer to another row of the manifest."""
    (tmp_path / "a.pdf").touch()
    documents = write_documents({"path": "a.pdf", "excerpt_of": "b.pdf"})
    assert validate(documents, PARTS, tmp_path) == [
        "a.pdf: excerpt_of 'b.pdf' is not another row"
    ]


def test_unknown_part_and_values_are_problems(
    tmp_path: Path, write_documents: Callable
) -> None:
    """A part missing from parts.csv and an invalid section or text source are reported."""
    (tmp_path / "a.pdf").touch()
    documents = write_documents(
        {"path": "a.pdf", "part": "XX", "section": "body", "text_source": "scan"}
    )
    assert len(validate(documents, PARTS, tmp_path)) == 3


def test_wrong_columns_are_refused(tmp_path: Path) -> None:
    """A manifest with other columns than expected is refused."""
    (tmp_path / "documents.csv").write_text("path,part\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="expected columns"):
        read_documents(tmp_path / "documents.csv")
