"""The LLM task `provenance_stage`: one provenance stage to its parts, as spans of the stage and choices from the RO lists.

The prompt is `prompts/provenance_stage.md` (in git); the examples, which
contain CRLB text, are a JSON file in `data/prompts/` (outside git). The JSON
schema is built from the RO value lists, so the choices cannot drift from
them. An answer becomes a `provenance.Stage`; its dates are parsed by rules.
"""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from crlb import llm
from crlb.extraction import vocabularies
from crlb.extraction.provenance import Stage
from crlb.extraction.source import Node

TASK = "provenance_stage"
PROMPT = files("crlb.extraction") / "prompts" / f"{TASK}.md"
EXAMPLES = Path("data/prompts/provenance_stage_examples.json")
SPANS = [
    "holder",
    "place",
    "date",
    "organiser",
    "lot",
    "consignor",
    "buyer",
    "price",
    "note",
]
LISTS = {
    "transfer_method": "transfer_method",
    "collection_type": "collection_type",
    "currency": "currencies",
}
SALE_WORDS = re.compile(r"\b(?:(?:his|her|their)\s+)?sale\b", re.IGNORECASE)


def choices() -> dict[str, frozenset[str]]:
    """Return the allowed values of each choice field."""
    return {name: vocabularies.labels(values) for name, values in LISTS.items()}


def schema() -> dict[str, Any]:
    """Return the JSON schema of an answer."""
    nullable = {"type": ["string", "null"]}
    properties: dict[str, Any] = {
        "kind": {"enum": ["collection", "auction", "other"]},
        **{name: nullable for name in SPANS},
        **{
            name: {"enum": [*sorted(allowed), None]}
            for name, allowed in choices().items()
        },
        "uncertain": {"type": "boolean"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def question(previous: str | None, stage: str) -> str:
    """Return the user message for one stage."""
    return f"Previous stage: {previous or '(none)'}\nStage: {stage}"


@dataclass
class Prompt:
    """The system prompt, the example turns and the schema of the task, with their hash."""

    system: str
    turns: list[tuple[str, str]]
    schema: dict[str, Any]
    sha: str


def load_prompt(examples_path: Path = EXAMPLES) -> Prompt:
    """Return the prompt with its examples; refuse examples that fail the checks themselves."""
    system = PROMPT.read_text(encoding="utf-8")
    examples = json.loads(examples_path.read_text(encoding="utf-8"))
    turns = []
    for example in examples:
        error = check(example["answer"], example["stage"])
        if error:
            raise SystemExit(f"example {example['stage']!r} fails the checks: {error}")
        turns.append(
            (
                question(example["previous"], example["stage"]),
                json.dumps(example["answer"], ensure_ascii=False),
            )
        )
    task_schema = schema()
    sha = hashlib.sha256(
        json.dumps(
            [system, turns, task_schema], ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    return Prompt(system, turns, task_schema, sha)


def check(answer: Any, stage: str) -> str | None:
    """Return why an answer is rejected, or None: the shared span and list checks, plus a holder for a collection."""
    error = llm.check(answer, stage, SPANS, choices())
    if error is not None:
        return error
    if answer.get("kind") not in ("collection", "auction", "other"):
        return f"kind is not in its list: {answer.get('kind')!r}"
    if answer["kind"] == "collection" and not answer.get("holder"):
        return "collection without a holder"
    return error


def to_stage(answer: dict[str, Any], stage: str) -> Stage | None:
    """Return the stage of a valid answer; None for a stage that is no holder or sale."""
    notes = [answer["note"]] if answer.get("note") else []
    uncertain = bool(answer.get("uncertain"))
    if answer["kind"] == "collection":
        return Stage(
            "collection",
            uncertain,
            holder=answer["holder"],
            place=answer.get("place"),
            date_text=answer.get("date"),
            entry_method=answer.get("transfer_method"),
            collection_type=answer.get("collection_type"),
            notes=notes,
        )
    if answer["kind"] == "auction":
        label = SALE_WORDS.search(stage)
        return Stage(
            "auction",
            uncertain,
            place=answer.get("place"),
            date_text=answer.get("date"),
            label=label.group(0) if label else None,
            organiser=answer.get("organiser"),
            lot=answer.get("lot"),
            consignor=answer.get("consignor"),
            buyer=answer.get("buyer"),
            price_amount=answer.get("price"),
            currency=answer.get("currency"),
            notes=notes,
        )
    return None


@dataclass
class Answer:
    """The outcome of one call: the stage (None for 'other' or a rejected answer) and whether it was valid."""

    stage: Stage | None
    valid: bool
    kind: str | None


def ask(
    conn: sqlite3.Connection,
    runtime: llm.Runtime,
    prompt: Prompt,
    run_id: int,
    item: Node,
    previous: str | None,
) -> Answer:
    """Ask the model for one stage, check and log the answer, and return it."""
    stage_text = item.text.strip()
    user = question(previous, stage_text)
    completion = runtime.complete(prompt.system, prompt.turns, user, prompt.schema)
    try:
        answer = json.loads(completion.text)
    except json.JSONDecodeError as error:
        answer, problem = None, f"not JSON: {error}"
    else:
        problem = check(answer, stage_text)
    llm.log_call(
        conn,
        "ro_runs",
        run_id,
        TASK,
        (item.first, item.last),
        user,
        completion,
        problem,
    )
    if problem is not None or answer is None:
        return Answer(None, False, None)
    return Answer(to_stage(answer, stage_text), True, answer["kind"])
