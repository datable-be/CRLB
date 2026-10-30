"""Tests for the LLM interface and the provenance_stage task, with a stub in place of the model."""

import json
import sqlite3
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from crlb import llm
from crlb.extraction import llm_provenance, provenance
from crlb.extraction.source import Node

STAGE = "by descent to Jonathan Richardson Junior (1694– 1771), London;"
BLANK = {
    "kind": None,
    "holder": None,
    "place": None,
    "date": None,
    "organiser": None,
    "lot": None,
    "consignor": None,
    "buyer": None,
    "price": None,
    "note": None,
    "transfer_method": None,
    "collection_type": None,
    "currency": None,
    "uncertain": False,
}


class Stub:
    """A runtime that returns fixed answers and records the questions."""

    def __init__(self, *answers: dict[str, Any] | str) -> None:
        """Remember the answers to return, in order."""
        self.answers = list(answers)
        self.questions: list[str] = []

    def complete(
        self,
        system: str,
        turns: list[tuple[str, str]],
        user: str,
        schema: dict[str, Any],
    ) -> llm.Completion:
        """Return the next answer."""
        self.questions.append(user)
        answer = self.answers.pop(0)
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return llm.Completion(text, 10, 5, 3)

    def identity(self) -> dict[str, str]:
        """Return a fixed identity."""
        return {"model_path": "/m/stub.gguf", "build": "b0"}


def answer(**values: Any) -> dict[str, Any]:
    """Return a full answer with the given values."""
    return {**BLANK, **values}


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Return an in-memory database with the shared tables."""
    connection = sqlite3.connect(":memory:")
    connection.executescript((files("crlb") / "schema" / "01_text.sql").read_text())
    return connection


@pytest.fixture
def prompt(tmp_path: Path) -> llm_provenance.Prompt:
    """Return the task prompt with one example."""
    examples = tmp_path / "examples.json"
    examples.write_text(
        json.dumps(
            [
                {
                    "previous": None,
                    "stage": "unknown.",
                    "answer": answer(kind="other"),
                }
            ]
        )
    )
    return llm_provenance.load_prompt(examples)


def test_check_accepts_spans_and_choices() -> None:
    """An answer whose spans occur in the stage and whose choices are in their lists passes."""
    good = answer(
        kind="collection",
        holder="Jonathan Richardson Junior (1694– 1771)",
        place="London",
        transfer_method="inheritance",
    )
    assert llm_provenance.check(good, STAGE) is None


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"kind": "collection", "holder": "Jonathan Richardson"}, None),
        (
            {"kind": "collection", "holder": "J. Richardson Jr"},
            "holder is not in the input",
        ),
        (
            {"kind": "collection", "holder": "London", "transfer_method": "descent"},
            "transfer_method is not in its list",
        ),
        ({"kind": "collection"}, "collection without a holder"),
        ({"kind": "sale"}, "kind is not in its list"),
    ],
)
def test_check_rejects(values: dict[str, Any], error: str | None) -> None:
    """A span that is not in the stage, a choice outside its list, or a collection without holder is rejected."""
    found = llm_provenance.check(answer(**values), STAGE)
    assert (found is None) if error is None else (found or "").startswith(error)


def test_ask_logs_and_converts(
    conn: sqlite3.Connection, prompt: llm_provenance.Prompt
) -> None:
    """A valid answer becomes a stage, a rejected one does not; both are logged."""
    stub = Stub(
        answer(
            kind="collection",
            holder="Jonathan Richardson Junior (1694– 1771)",
            place="London",
        ),
        answer(kind="collection", holder="Somebody Else"),
        "not json",
    )
    item = Node(1, "item", "2", 10, 19, None, STAGE)
    good = llm_provenance.ask(
        conn, stub, prompt, 7, item, "Jonathan Richardson Senior;"
    )
    assert good.valid and good.stage is not None
    assert (good.stage.holder, good.stage.place) == (
        "Jonathan Richardson Junior (1694– 1771)",
        "London",
    )
    assert "Previous stage: Jonathan Richardson Senior;" in stub.questions[0]
    bad = llm_provenance.ask(conn, stub, prompt, 7, item, None)
    assert not bad.valid and bad.stage is None
    broken = llm_provenance.ask(conn, stub, prompt, 7, item, None)
    assert not broken.valid
    rows = conn.execute(
        "SELECT run_id, task, first_word_id, valid, substr(error, 1, 6) FROM llm_calls ORDER BY id"
    ).fetchall()
    assert rows == [
        (7, "provenance_stage", 10, 1, None),
        (7, "provenance_stage", 10, 0, "holder"),
        (7, "provenance_stage", 10, 0, "not JS"),
    ]


def test_auction_answer_takes_the_sale_words_from_the_stage() -> None:
    """The auction label is the sale words as written in the stage."""
    stage = "sold by Burchard’s heirs at sale, New York (Christie’s), 11 January 2011, lot 276."
    found = llm_provenance.to_stage(
        answer(kind="auction", place="New York", organiser="Christie’s", lot="276"),
        stage,
    )
    assert found is not None and (found.kind, found.label, found.lot) == (
        "auction",
        "sale",
        "276",
    )


def test_examples_must_pass_the_checks(tmp_path: Path) -> None:
    """An example whose answer is not in its stage is refused."""
    examples = tmp_path / "examples.json"
    examples.write_text(
        json.dumps(
            [
                {
                    "previous": None,
                    "stage": "unknown.",
                    "answer": answer(kind="collection", holder="X"),
                }
            ]
        )
    )
    with pytest.raises(SystemExit, match="fails the checks"):
        llm_provenance.load_prompt(examples)


def test_chain_gives_the_model_only_what_rules_leave() -> None:
    """The model is asked only for stages that rules do not parse, and its stages are marked as LLM."""
    items = [
        Node(1, "item", "1", 10, 19, None, "Albert Fonson;"),
        Node(2, "item", "2", 20, 29, None, STAGE),
    ]
    asked = []

    def model(index: int) -> provenance.Stage:
        """Record the question and return a stage."""
        asked.append(index)
        return provenance.Stage(
            "collection", holder="Jonathan Richardson Junior (1694– 1771)"
        )

    chain = provenance.build_chain(items, None, model)
    assert asked == [1]
    assert [row.method for row in chain] == ["rules", "llm"]


def test_spans_are_taken_as_written_in_the_source() -> None:
    """A span with other quotes or spaces passes and is replaced by the text of the source."""
    stage = "purchased from the latter’s estate,  between 1689 and 1691;"
    found = answer(
        kind="collection", holder="the latter's estate", date="between 1689 and 1691"
    )
    assert llm_provenance.check(found, stage) is None
    assert found["holder"] == "the latter’s estate"
    assert llm.find_span("estate, between", stage) == "estate,  between"
    assert llm.find_span("the latter estate", stage) is None
