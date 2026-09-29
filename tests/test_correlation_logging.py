from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.main import app

REQUEST_ID = re.compile(r"^req-[0-9a-f]{8}$")


def _post_chats(requests: list[tuple[dict, dict]]) -> list[httpx.Response]:
    async def send() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return [await client.post("/chat", json=body, headers=headers) for body, headers in requests]

    return asyncio.run(send())


def _body(user: str, session: str, message: str = "Explain observability") -> dict:
    return {"user_id": user, "session_id": session, "feature": "qa", "message": message}


def test_generates_request_id_when_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")
    (response,) = _post_chats([(_body("u1", "s1"), {})])

    request_id = response.headers["x-request-id"]
    assert REQUEST_ID.match(request_id)
    assert response.json()["correlation_id"] == request_id
    assert int(response.headers["x-response-time-ms"]) >= 0


def test_propagates_valid_request_id_and_rejects_invalid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")
    valid, invalid = _post_chats(
        [
            (_body("u1", "s1"), {"x-request-id": "req-0badcafe"}),
            (_body("u1", "s1"), {"x-request-id": "evil\nfake-log-line"}),
        ]
    )

    assert valid.headers["x-request-id"] == "req-0badcafe"
    assert REQUEST_ID.match(invalid.headers["x-request-id"])


def test_logs_are_enriched_scrubbed_and_do_not_leak_context(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    first, second = _post_chats(
        [
            (_body("alice", "s-alice", "My email is alice@example.com"), {}),
            (_body("bob", "s-bob"), {}),
        ]
    )

    raw = log_path.read_text(encoding="utf-8")
    assert "alice@example.com" not in raw
    events = [json.loads(line) for line in raw.splitlines()]
    by_request = {first.headers["x-request-id"]: "s-alice", second.headers["x-request-id"]: "s-bob"}
    assert len(by_request) == 2

    for event in events:
        assert event["correlation_id"] in by_request
        assert event["session_id"] == by_request[event["correlation_id"]]
        for field in ("user_id_hash", "feature", "model", "env"):
            assert event[field]
        assert event["user_id_hash"] not in ("alice", "bob")
