"""Regression tests: audit log records every human-request outcome.

This file guards the audit-log completeness promise from ``audit.py`` ("an
append-only JSONL record of all human requests and outcomes") against two
gaps where a request silently produced no audit row:

1. Non-timeout channel failures (introduced in 28e24e2). ``ask_human`` /
   ``request_approval`` only audited the success and ``except TimeoutError``
   branches, so any other exception from ``channel.start()`` / ``channel.ask()``
   / ``channel.request_approval()`` propagated past every ``_audit.record(...)``.
   Fix: ``channel.start()`` moved inside the ``try`` plus an ``except Exception``
   catch-all that records an error outcome and re-raises.

2. Cancellation mid-flight (introduced in e564fa0). Converting the handlers from
   sync ``def`` to ``async def`` that offloads blocking channel calls via
   ``await anyio.to_thread.run_sync(...)`` introduced the first cancellable
   checkpoint. ``asyncio.CancelledError`` is a ``BaseException`` (not
   ``Exception``), so neither ``except TimeoutError`` nor ``except Exception``
   caught it — a request already posted to a human (Slack/Telegram) left zero
   audit rows. Fix: an ``except anyio.get_cancelled_exc_class()`` branch (placed
   before ``except Exception``) records a ``cancelled: true`` outcome and
   re-raises so the MCP cancel scope stays correct.

The success path is already covered by ``test_audit.py::test_audit_log_from_server``
and the timeout raise-wrapping by ``test_server.py``; they are not duplicated here.
"""

import asyncio
import json
import threading

import pytest
import requests

import call_a_human_mcp.server as server_module
from call_a_human_mcp.channels.base import Channel
from call_a_human_mcp.config import Config
from call_a_human_mcp.request import HumanRequest
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


# ------------------------------------------------------------------
# Cancellation mid-flight is audited
#
# Bug (introduced in e564fa0): converting ask_human / request_approval to
# async handlers with `await anyio.to_thread.run_sync(...)` created the first
# cancellable checkpoint inside the handlers. asyncio.CancelledError is a
# BaseException (not Exception), so `except Exception` cannot catch it — a
# request already posted to a human (Slack/Telegram) left ZERO audit rows.
# Fix: `except anyio.get_cancelled_exc_class()` before `except Exception`
# records a `cancelled: true` outcome and re-raises.
# ------------------------------------------------------------------


class _CancelChannel(Channel):
    """Channel that parks ask()/request_approval() on the request's own
    threading.Event so a test can cancel the handler mid-flight.

    Signals ``parked`` the instant a blocking call is entered, so tests cancel
    deterministically (no fixed ``asyncio.sleep`` races). Stores every pending
    request so the test can set its event afterwards to unblock (and let exit)
    the orphaned worker thread that anyio keeps running after cancellation.
    """

    def __init__(self):
        self.parked = threading.Event()
        self.pending: list[HumanRequest] = []

    def start(self) -> None:
        pass

    def ask(self, req: HumanRequest) -> str:
        self.pending.append(req)
        self.parked.set()
        req.event.wait(timeout=30)
        return "late"

    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        self.pending.append(req)
        self.parked.set()
        req.event.wait(timeout=30)
        return True, "tester"


def _release(channel: _CancelChannel) -> None:
    """Unblock every orphaned worker thread left behind by a cancelled call."""
    for req in channel.pending:
        req.event.set()


async def _await_parked(channel: _CancelChannel, timeout: float = 2.0) -> bool:
    """Wait for the channel's ``parked`` flag while yielding to the event loop.

    ``ask_human`` / ``request_approval`` only reach their blocking checkpoint
    when the loop keeps running their ``await anyio.to_thread.run_sync(...)``
    offloads. A *synchronous* ``threading.Event.wait()`` would freeze the loop
    and deadlock the handler, so poll the flag with brief async sleeps instead.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not channel.parked.is_set():
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.01)
    return True


async def test_ask_human_cancelled_is_audited(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    ch = _CancelChannel()
    _wire(str(audit_path), monkeypatch, ch)

    task = asyncio.create_task(ask_human(question="where to deploy?", context="migration"))
    assert await _await_parked(ch, timeout=2), "ask() never parked on the blocking wait"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _release(ch)

    entries = _entries(audit_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "ask_human"
    assert e["question"] == "where to deploy?"
    assert e["context"] == "migration"
    assert e["cancelled"] is True
    assert e["timed_out"] is False
    assert "error" not in e
    assert "request_id" in e
    assert "timestamp" in e
    assert isinstance(e["duration_ms"], int) and e["duration_ms"] >= 0


async def test_request_approval_cancelled_is_audited(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    ch = _CancelChannel()
    _wire(str(audit_path), monkeypatch, ch)

    task = asyncio.create_task(
        request_approval(action="delete prod db", details="postgres cluster")
    )
    assert await _await_parked(ch, timeout=2), (
        "request_approval() never parked on the blocking wait"
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _release(ch)

    entries = _entries(audit_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "request_approval"
    assert e["action"] == "delete prod db"
    assert e["details"] == "postgres cluster"
    assert e["cancelled"] is True
    assert e["approved"] is False
    assert e["reason"] == ""
    assert e["timed_out"] is False
    assert "error" not in e
    assert isinstance(e["duration_ms"], int) and e["duration_ms"] >= 0


async def test_cancelled_re_raises_without_wrapping_ask_human(tmp_path, monkeypatch):
    """Cancellation must propagate verbatim as CancelledError — not be swallowed
    or wrapped in RuntimeError — so the MCP cancel scope and anyio cleanup stay
    correct."""
    audit_path = tmp_path / "audit.jsonl"
    ch = _CancelChannel()
    _wire(str(audit_path), monkeypatch, ch)

    task = asyncio.create_task(ask_human(question="q"))
    assert await _await_parked(ch, timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _release(ch)


async def test_cancelled_dispatch_path_audited_ask_human(tmp_path, monkeypatch):
    """The fix must fire through the real FastMCP.call_tool dispatch path, not
    only on the bare handler coroutine — that's the path the
    notifications/cancelled JSON-RPC notification takes via RequestResponder.cancel
    -> CancelScope.cancel()."""
    audit_path = tmp_path / "audit.jsonl"
    ch = _CancelChannel()
    _wire(str(audit_path), monkeypatch, ch)

    task = asyncio.create_task(server_module.mcp.call_tool("ask_human", {"question": "ship it?"}))
    assert await _await_parked(ch, timeout=2), "handler never reached the blocking checkpoint"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _release(ch)

    entries = _entries(audit_path)
    assert len(entries) == 1
    assert entries[0]["tool"] == "ask_human"
    assert entries[0]["question"] == "ship it?"
    assert entries[0]["cancelled"] is True


async def test_cancelled_during_start_checkpoint_is_audited(tmp_path, monkeypatch):
    """Cancellation may land at the first await (the channel.start offload),
    before ask()/request_approval() is ever reached. That outcome must still be
    audited as cancelled — start() is inside the try, so its checkpoint is
    covered by the same except clause."""

    class _StartHangs(Channel):
        def __init__(self):
            self.start_gate = threading.Event()
            self.pending: list[HumanRequest] = []

        def start(self) -> None:
            self.start_gate.wait(timeout=30)

        def ask(self, req: HumanRequest) -> str:
            self.pending.append(req)
            req.event.wait(timeout=30)
            return "late"

        def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
            self.pending.append(req)
            req.event.wait(timeout=30)
            return True, "tester"

    audit_path = tmp_path / "audit.jsonl"
    ch = _StartHangs()
    _wire(str(audit_path), monkeypatch, ch)

    task = asyncio.create_task(ask_human(question="q"))
    # Let the start() offload enter the worker thread's blocking wait.
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    ch.start_gate.set()  # release the parked start() worker thread
    for req in ch.pending:
        req.event.set()

    entries = _entries(audit_path)
    assert len(entries) == 1
    assert entries[0]["cancelled"] is True
    assert entries[0]["tool"] == "ask_human"


# ------------------------------------------------------------------
# AnyIO CancelScope regression — the real MCP cancellation path
#
# MCP's RequestResponder.cancel() cancels an AnyIO CancelScope, which is
# the actual path taken by notifications/cancelled. The tests above use
# asyncio.Task.cancel() (direct CancelledError injection), which bypasses
# the shielding behaviour of anyio.to_thread.run_sync with the default
# abandon_on_cancel=False: that default causes run_sync to wait for the
# thread to finish before propagating cancellation, so the except branch
# would only fire after the worker returns — recording a normal success
# outcome for the cancelled request. With abandon_on_cancel=True the scope
# cancellation is observed immediately. These tests exercise that path.
# ------------------------------------------------------------------


async def test_ask_human_cancel_scope_is_audited(tmp_path, monkeypatch):
    """AnyIO CancelScope cancellation (the real MCP path) must produce a
    cancelled=true audit entry — not a normal success entry."""
    import anyio

    audit_path = tmp_path / "audit.jsonl"
    ch = _CancelChannel()
    _wire(str(audit_path), monkeypatch, ch)

    # Drive via anyio CancelScope — the same cancellation mechanism MCP's
    # RequestResponder.cancel() uses via anyio.CancelScope.cancel().
    with anyio.CancelScope() as scope:
        async def _cancel_after_parked():
            parked = await _await_parked(ch, timeout=2)
            assert parked, "ask() never reached the blocking checkpoint"
            scope.cancel()

        async with anyio.create_task_group() as tg:
            tg.start_soon(_cancel_after_parked)
            try:
                await ask_human(question="cancel-scope-q?", context="ctx")
            except BaseException:
                pass  # cancelled — already handled by scope

    _release(ch)

    entries = _entries(audit_path)
    assert len(entries) == 1, (
        f"Expected 1 audit entry (cancelled), got {len(entries)}: {entries}"
    )
    e = entries[0]
    assert e["tool"] == "ask_human"
    assert e["question"] == "cancel-scope-q?"
    assert e["context"] == "ctx"
    assert e["cancelled"] is True, (
        "Expected cancelled=true but got: " + str(e)
    )
    assert e["timed_out"] is False
    assert "error" not in e


async def test_request_approval_cancel_scope_is_audited(tmp_path, monkeypatch):
    """AnyIO CancelScope cancellation must produce a cancelled=true audit entry
    for request_approval — not an approved=true success entry."""
    import anyio

    audit_path = tmp_path / "audit.jsonl"
    ch = _CancelChannel()
    _wire(str(audit_path), monkeypatch, ch)

    async def _inner():
        with anyio.CancelScope() as scope:
            async def _cancel_after_parked():
                parked = await _await_parked(ch, timeout=2)
                assert parked, "request_approval() never reached the blocking checkpoint"
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(_cancel_after_parked)
                try:
                    await request_approval(action="cancel-scope-action", details="d")
                except BaseException:
                    pass  # cancelled — already handled by scope

    await _inner()
    _release(ch)

    entries = _entries(audit_path)
    assert len(entries) == 1, (
        f"Expected 1 audit entry (cancelled), got {len(entries)}: {entries}"
    )
    e = entries[0]
    assert e["tool"] == "request_approval"
    assert e["action"] == "cancel-scope-action"
    assert e["details"] == "d"
    assert e["cancelled"] is True, (
        "Expected cancelled=true but got: " + str(e)
    )
    assert e["approved"] is False
    assert e["timed_out"] is False
    assert "error" not in e
