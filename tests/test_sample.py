"""Tests for parsing the --sample option."""

import argparse

import pytest

from crlb.sample import SampleItem, parse_sample, sample_parts


def test_parse_parts_and_entries() -> None:
    """Items are a part with an optional catalogue number, separated by ';'."""
    assert parse_sample("XIX (4)/22; II (1)") == [
        SampleItem("XIX (4)", "22"),
        SampleItem("II (1)", None),
    ]
    assert sample_parts(parse_sample("XIX (4)/22;XIX (4)/23")) == {"XIX (4)"}
    assert sample_parts(None) is None


@pytest.mark.parametrize("spec", ["", "XIX (4);", "XIX (4)/", "/22"])
def test_malformed_items_are_refused(spec: str) -> None:
    """Empty items, an empty number and a missing part are errors."""
    with pytest.raises(argparse.ArgumentTypeError):
        parse_sample(spec)
