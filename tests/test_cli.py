"""Tests for the crlb command line."""

from pathlib import Path

import pytest

from crlb import set_active
from crlb.cli import build_parser, main
from crlb.correction import correct, lexicon, measure
from crlb.database import build
from crlb.ocr import analyse_specimens, sample_specimens


def test_build_dispatches_to_its_module() -> None:
    """Check that the build command calls the run function of crlb.database.build."""
    assert build_parser().parse_args(["build", "m.csv", "out"]).func is build.run


def test_step_2_commands_dispatch_to_their_modules() -> None:
    """Check that lexicon, correct run, correct measure and set-active call their modules."""
    parser = build_parser()
    assert parser.parse_args(["lexicon", "db", "src.csv"]).func is lexicon.run
    assert parser.parse_args(["correct", "run", "db"]).func is correct.run
    args = parser.parse_args(["correct", "run", "db", "--sample", "XIX (4);II (1)"])
    assert [item.part for item in args.sample] == ["XIX (4)", "II (1)"]
    assert (
        parser.parse_args(["correct", "measure", "db", "s", "x.csv"]).func
        is measure.run
    )
    assert parser.parse_args(["set-active", "db", "2", "1"]).func is set_active.run


def test_ocr_subcommands_dispatch_to_their_modules() -> None:
    """Check that each ocr subcommand calls the run function of its module."""
    parser = build_parser()
    assert (
        parser.parse_args(["ocr", "sample", "in", "out"]).func is sample_specimens.run
    )
    assert parser.parse_args(["ocr", "analyse", "dir"]).func is analyse_specimens.run


def test_command_is_required() -> None:
    """Check that calling crlb without a command is an error."""
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_ocr_sample_refuses_existing_directory(tmp_path: Path) -> None:
    """Check that sampling never writes into an existing directory."""
    with pytest.raises(SystemExit, match="already exists"):
        main(["ocr", "sample", str(tmp_path), str(tmp_path)])


def test_ocr_analyse_runs_on_empty_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Check that analysing a manifest without specimens reports zero counts."""
    (tmp_path / "manifest.csv").write_text(
        ",".join(sample_specimens.MANIFEST_FIELDS) + "\n", encoding="utf-8"
    )
    main(["ocr", "analyse", str(tmp_path)])
    assert "0 corrected specimens analysed" in capsys.readouterr().out
