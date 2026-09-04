"""Regression tests: audit log records non-timeout channel failures.

Bug (introduced in 28e24e2): ``server.py``'s ``ask_human`` / ``request_approval``
only audited the success branch and the ``except TimeoutError`` branch. Any other
exception from ``channel.start()`` / ``channel.ask()`` / ``channel.request_approval()``
propagated past both ``_audit.record(...)`` calls, leaving the request silently
dropped from the audit log — contradicting ``audit.py``'s docstring promise of an
"append-only JSONL record of all human requests and outcomes".

Fix: ``channel.start()`` moved inside the ``try`` and a catch-all ``except Exception``
branch records an error outcome (with the exception's type name) and re-raises.

These tests guard the audited error path against regression. The success path is
already covered by ``test_audit.py::test_audit_log_from_server`` and the timeout
raise-wrapping by ``test_server.py``; they are not duplicated here.
"""

import json

import pytest
import requests

import call_a_human_mcp.server as server_module
from call_a_human_mcp.config import Config
from call_a_human_mcp.server import ask_human, create_server, request_approval
from tests.conftest import ErrorChannel, StartErrorChannel

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_server_singletons():
    """Restore the module-level channel/audit singletons after each test."""
    orig_channel = server_module._channel
    orig_audit = server_module._audit
    yield
    server_module._channel = orig_channel
    server_module._audit = orig_audit


def _wire(audit_path, monkeypatch, channel):
    """Set up a real path-backed AuditLog and install ``channel`` as the singleton."""
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "cli")
    monkeypatch.setenv("CALL_HUMAN_AUDIT_LOG", audit_path)
    create_server(Config.from_env())
    server_module._channel = channel
    return server_module._channel


def _entries(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ------------------------------------------------------------------
# Non-TimeoutError from channel.ask / channel.request_approval is audited
# ------------------------------------------------------------------


async def test_ask_human_error_is_audited(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    ch = ErrorChannel(RuntimeError("slack chat_postMessage failed"))
    _wire(str(audit_path), monkeypatch, ch)

    with pytest.raises(RuntimeError, match="slack chat_postMessage failed"):
        await ask_human(question="hello?")

    entries = _entries(audit_path)
    assert len(entries) == 1  # exactly one entry — no duplicate success entry
    e = entries[0]
    assert e["tool"] == "ask_human"
    assert e["question"] == "hello?"
    assert e["timed_out"] is False
    assert e["error"] == "RuntimeError"
    assert isinstance(e["duration_ms"], int)
    assert "timestamp" in e
    assert "request_id" in e
    # start() must still have been called (now inside the try)
    assert ch.start_calls == 1


async def test_request_approval_error_is_audited(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    _wire(str(audit_path), monkeypatch, ErrorChannel())

    with pytest.raises(RuntimeError):
        await request_approval(action="delete db", details="prod")

    entries = _entries(audit_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "request_approval"
    assert e["action"] == "delete db"
    assert e["details"] == "prod"
    assert e["approved"] is False
    assert e["reason"] == ""
    assert e["timed_out"] is False
    assert e["error"] == "RuntimeError"
    assert isinstance(e["duration_ms"], int)


async def test_error_preserves_original_exception_type(tmp_path, monkeypatch):
    """The catch-all re-raises the original exception, it does not wrap it.

    Guards against a future change wrapping the error as RuntimeError instead of
    bare ``raise`` (which would hide the underlying channel failure type).
    """
    audit_path = tmp_path / "audit.jsonl"

    class CustomDeliveryError(Exception):
        pass

    _wire(str(audit_path), monkeypatch, ErrorChannel(CustomDeliveryError("delivery 502")))

    with pytest.raises(CustomDeliveryError, match="delivery 502"):
        await ask_human(question="still works?")

    entries = _entries(audit_path)
    assert len(entries) == 1
    assert entries[0]["error"] == "CustomDeliveryError"


# ------------------------------------------------------------------
# channel.start() failure is audited (start() is now inside the try)
# ------------------------------------------------------------------


async def test_ask_human_start_error_is_audited(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    ch = StartErrorChannel(RuntimeError("Slack Socket Mode failed to connect within 10s"))
    _wire(str(audit_path), monkeypatch, ch)

    with pytest.raises(RuntimeError, match="failed to connect"):
        await ask_human(question="hello?")

    entries = _entries(audit_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "ask_human"
    assert e["question"] == "hello?"
    assert e["timed_out"] is False
    assert e["error"] == "RuntimeError"


async def test_request_approval_start_error_is_audited(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    ch = StartErrorChannel(RuntimeError("connect failed"))
    _wire(str(audit_path), monkeypatch, ch)

    with pytest.raises(RuntimeError, match="connect failed"):
        await request_approval(action="deploy")

    entries = _entries(audit_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "request_approval"
    assert e["approved"] is False
    assert e["timed_out"] is False
    assert e["error"] == "RuntimeError"


# ------------------------------------------------------------------
# Ordering: TimeoutError is matched before the catch-all
# ------------------------------------------------------------------


async def test_timeout_subclass_is_treated_as_timeout_not_error(tmp_path, monkeypatch):
    """A subclass of TimeoutError is recorded as timed_out (not as an error).

    Guards the ordering of the ``except`` clauses: ``except TimeoutError`` must
    precede ``except Exception`` so timeouts keep their existing audit shape and
    RuntimeError wrapping rather than being captured by the catch-all.
    """
    audit_path = tmp_path / "audit.jsonl"

    class MyTimeout(TimeoutError):
        pass

    _wire(str(audit_path), monkeypatch, ErrorChannel(MyTimeout("custom timeout")))

    with pytest.raises(RuntimeError, match="custom timeout"):
        await ask_human(question="q")

    entries = _entries(audit_path)
    assert len(entries) == 1
    assert entries[0]["timed_out"] is True
    assert "error" not in entries[0]


# ------------------------------------------------------------------
# Disabled audit log: error path must still raise, no file, no crash
# ------------------------------------------------------------------


async def test_error_path_raises_and_is_noop_when_audit_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "cli")
    monkeypatch.delenv("CALL_HUMAN_AUDIT_LOG", raising=False)
    create_server(Config.from_env())
    server_module._channel = ErrorChannel(RuntimeError("delivery failed"))

    with pytest.raises(RuntimeError, match="delivery failed"):
        await ask_human(question="q")

    # no audit file should exist; the no-op AuditLog must not crash on .record()
    assert not (tmp_path / "audit.jsonl").exists()


# ------------------------------------------------------------------
# End-to-end with the real channel adapters (mocked transport)
# ------------------------------------------------------------------


class _FakeSlackApp:
    """Stand-in for slack_bolt.App that performs no token validation."""

    def __init__(self, *args, **kwargs):
        pass

    def action(self, *args, **kwargs):
        def deco(fn):
            return fn

        return deco

    def event(self, *args, **kwargs):
        def deco(fn):
            return fn

        return deco


class _FakeSlackClient:
    def __init__(self, *args, **kwargs):
        pass

    def chat_postMessage(self, *args, **kwargs):
        from slack_sdk.errors import SlackApiError

        raise SlackApiError(
            message="channel_not_found", response={"ok": False, "error": "channel_not_found"}
        )


async def test_slack_apierror_is_audited(tmp_path, monkeypatch):
    """A SlackApiError from chat_postMessage is recorded, not silently dropped."""
    from slack_sdk.errors import SlackApiError

    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "slack")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-fake")
    monkeypatch.setenv("SLACK_CHANNEL_ID", "C123")
    monkeypatch.setenv("CALL_HUMAN_AUDIT_LOG", str(audit_path))

    monkeypatch.setattr("call_a_human_mcp.channels.slack.App", _FakeSlackApp)
    monkeypatch.setattr("call_a_human_mcp.channels.slack.WebClient", _FakeSlackClient)

    config = Config.from_env()
    create_server(config)
    server_module._channel._started = True  # skip Socket Mode connect so start() is a no-op

    with pytest.raises(SlackApiError):
        await ask_human(question="ship it?")

    entries = _entries(audit_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "ask_human"
    assert e["error"] == "SlackApiError"
    assert e["timed_out"] is False


class _FakeHTTPResponse:
    def raise_for_status(self):
        raise requests.HTTPError("502 Bad Gateway")

    def json(self):
        return {}


async def test_telegram_httperror_is_audited(tmp_path, monkeypatch):
    """An HTTPError from Telegram's _api() is recorded, not silently dropped."""
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("CALL_HUMAN_AUDIT_LOG", str(audit_path))

    config = Config.from_env()
    create_server(config)
    from call_a_human_mcp.channels.telegram import TelegramChannel

    ch = TelegramChannel(config)
    ch._started = True  # skip polling daemon so start() is a no-op
    server_module._channel = ch
    monkeypatch.setattr(
        "call_a_human_mcp.channels.telegram.requests.post", lambda *a, **k: _FakeHTTPResponse()
    )

    with pytest.raises(requests.HTTPError):
        await ask_human(question="ship it?")

    entries = _entries(audit_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "ask_human"
    assert e["error"] == "HTTPError"
    assert e["timed_out"] is False
