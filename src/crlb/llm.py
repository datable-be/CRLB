"""The language-model interface: a model runtime, schema-constrained calls, the span and list checks, and `llm_calls`.

A runtime turns a system prompt, example turns and an input into JSON that
follows a JSON schema (constrained decoding). The checks then verify that every
span occurs in the input (up to whitespace and quote characters; the span is
then taken as written in the input) and every choice is in its list; an answer
that fails a check is rejected. Every call is stored in `llm_calls`, valid or
not, so models can be audited and compared without calling them again.
"""

import json
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

SEED = 42


@dataclass
class Completion:
    """The answer of a model: the raw text, its token counts and how long it took."""

    text: str
    tokens_in: int | None
    tokens_out: int | None
    duration_ms: int


class Runtime(Protocol):
    """A model runtime that answers in JSON following a schema."""

    def complete(
        self,
        system: str,
        turns: list[tuple[str, str]],
        user: str,
        schema: dict[str, Any],
    ) -> Completion:
        """Return the answer to user, after the example turns (user, assistant), constrained to schema."""
        ...

    def identity(self) -> dict[str, str]:
        """Return the model and runtime as recorded with a run."""
        ...


class LlamaServer:
    """A llama.cpp `llama-server` over its OpenAI-compatible HTTP API."""

    def __init__(self, url: str, timeout: float = 600) -> None:
        """Remember the server URL, e.g. http://127.0.0.1:8080."""
        self.url = url.rstrip("/")
        self.timeout = timeout

    def request(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a GET (no body) or POST request and return the JSON response."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.url + path, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def complete(
        self,
        system: str,
        turns: list[tuple[str, str]],
        user: str,
        schema: dict[str, Any],
    ) -> Completion:
        """Return the answer at temperature 0 with a fixed seed, reusing the cached prompt prefix."""
        messages = [{"role": "system", "content": system}]
        for question, answer in turns:
            messages += [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
        messages.append({"role": "user", "content": user})
        started = time.monotonic()
        response = self.request(
            "/v1/chat/completions",
            {
                "messages": messages,
                "temperature": 0,
                "seed": SEED,
                "cache_prompt": True,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": schema},
                },
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        usage = response.get("usage", {})
        return Completion(
            response["choices"][0]["message"]["content"],
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            int((time.monotonic() - started) * 1000),
        )

    def identity(self) -> dict[str, str]:
        """Return the model file and the build of the server."""
        props = self.request("/props")
        return {
            "model_path": str(props.get("model_path", "")),
            "build": str(props.get("build_info", "")),
        }


def normalise(text: str) -> str:
    """Return text with runs of whitespace as one space."""
    return " ".join(text.split())


# Quote characters a model may write in place of the typographic ones of the source
QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"', "„": '"'})


def find_span(value: str, source: str) -> str | None:
    """Return the text of the source that a span stands for, as written in the source, or None.

    Whitespace and the kind of quote characters may differ; nothing else.
    """
    folded, positions = [], []
    for k, char in enumerate(source):
        if char.isspace():
            if folded and folded[-1] != " ":
                folded.append(" ")
                positions.append(k)
            continue
        folded.append(char.translate(QUOTES))
        positions.append(k)
    wanted = normalise(value).translate(QUOTES)
    start = "".join(folded).find(wanted) if wanted else -1
    if start < 0:
        return None
    return source[positions[start] : positions[start + len(wanted) - 1] + 1]


def check(
    answer: Any,
    source: str,
    spans: list[str],
    choices: dict[str, frozenset[str]],
) -> str | None:
    """Return why an answer is rejected, or None if every span occurs in the source and every choice is in its list.

    Spans that pass are replaced in the answer by the text as written in the source.
    """
    if not isinstance(answer, dict):
        return "answer is not a JSON object"
    for name in spans:
        value = answer.get(name)
        if value is None:
            continue
        if not isinstance(value, str):
            return f"{name} is not text"
        found = find_span(value, source)
        if found is None:
            return f"{name} is not in the input: {value!r}"
        answer[name] = found
    for name, allowed in choices.items():
        value = answer.get(name)
        if value is not None and value not in allowed:
            return f"{name} is not in its list: {value!r}"
    return None


def log_call(
    conn: sqlite3.Connection,
    run_table: str,
    run_id: int,
    task: str,
    words: tuple[int, int] | None,
    input_text: str,
    completion: Completion | None,
    error: str | None,
) -> int:
    """Store one call in llm_calls and return its id."""
    call_id = conn.execute(
        "INSERT INTO llm_calls (run_table, run_id, task, first_word_id, last_word_id, input_text,"
        " output_json, valid, error, duration_ms, tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_table,
            run_id,
            task,
            words[0] if words else None,
            words[1] if words else None,
            input_text,
            completion.text if completion else None,
            int(error is None),
            error,
            completion.duration_ms if completion else 0,
            completion.tokens_in if completion else None,
            completion.tokens_out if completion else None,
        ),
    ).lastrowid
    assert call_id is not None
    return call_id
