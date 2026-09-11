"""Tests for ``SlackChannel.start()`` — Socket Mode readiness contract.

``slack_sdk.socket_mode.builtin.SocketModeClient.is_connected`` is a method
(``def is_connected(self) -> bool``), not a ``@property``, across the
supported ``slack-sdk>=3.27.0`` range. The readiness poll in ``start()``
must therefore *call* it; truth-testing the bound method object would always
report "connected" and make the 10-second failure guard unreachable.

These tests pin the observable contract — ``start()`` succeeds when the
socket comes up, raises when it never does, and is idempotent — without
touching the network or coupling to polling call counts.

They also pin the failure->retry resource contract: ``SocketModeHandler``
constructs background ``IntervalRunner`` threads and a ``ThreadPoolExecutor``
eagerly at ``__init__`` time. A failed ``start()`` must tear that handler
down (``.close()``) and drop the channel's reference to it so a subsequent
retry on the same channel instance cannot orphan the prior handler's
background resources (the stdio server retries ``start()`` per tool call).
"""

import pytest

import call_a_human_mcp.channels.slack as slack_mod
from call_a_human_mcp.channels.slack import SlackChannel
from call_a_human_mcp.config import Config


def _make_fakes():
    """Build stand-in ``App`` / ``SocketModeHandler`` classes sharing a
    mutable ``state`` dict so tests can drive ``start()`` deterministically
    without network I/O.

    ``state["connected"]`` (bool) is what ``client.is_connected()`` returns;
    tests set it before calling ``start()``. ``handler_constructed`` /
    ``start_calls`` / ``close_calls`` counters back the idempotency and
    teardown assertions. ``state["close_raises"]`` (Exception | None), when
    set, makes the fake handler's ``close()`` raise so the teardown's
    defensive ordering (drop the reference *before* ``close()``) is
    exercised.
    """

    state: dict = {
        "connected": True,
        "start_calls": 0,
        "handler_constructed": 0,
        "close_calls": 0,
        "close_raises": None,
    }

    class FakeApp:
        def __init__(self, *args, **kwargs):
            self.token = kwargs.get("token")

        def action(self, _action_id):
            return lambda fn: fn

        def event(self, _event_type):
            return lambda fn: fn

    class FakeClient:
        auto_reconnect_enabled = True

        def is_connected(self):
            return state["connected"]

    class FakeHandler:
        def __init__(self, app, app_token):
            state["handler_constructed"] += 1
            # Real SocketModeHandler constructs self.client eagerly in
            # __init__, so the poll sees it immediately. Do the same.
            self.client = FakeClient()

        def start(self):
            # Real handler.start() blocks running the message loop on a daemon
            # thread; tests don't drive the loop, just record that it ran.
            state["start_calls"] += 1

        def close(self):
            # Real SocketModeHandler.close() shuts down the message_processor
            # IntervalRunner and the message_workers ThreadPoolExecutor that
            # were created in SocketModeClient.__init__. Tests record that
            # close() was called so the failed-start teardown is verifiable.
            state["close_calls"] += 1
            exc = state["close_raises"]
            if exc is not None:
                raise exc

    return state, FakeApp, FakeHandler


def _make_config():
    return Config(
        channel="slack",
        timeout=300,
        slack_bot_token="xoxb-fake",
        slack_app_token="xapp-1-fake",
        slack_channel_id="C123",
    )


@pytest.fixture
def slack_channel(monkeypatch):
    """A SlackChannel wired to in-memory fakes for App and SocketModeHandler.

    Returns ``(channel, state)``. Tests set ``state["connected"]`` before
    calling ``start()``.
    """
    state, FakeApp, FakeHandler = _make_fakes()
    monkeypatch.setattr(slack_mod, "App", FakeApp)
    monkeypatch.setattr(slack_mod, "SocketModeHandler", FakeHandler)
    return SlackChannel(_make_config()), state


def _stepping_monotonic(step):
    """A fake ``time.monotonic`` advancing by ``step`` each call, used to
    fast-forward the 10s readiness deadline without real wall-clock delay."""
    counter = {"n": 0}

    def _now():
        counter["n"] += 1
        return counter["n"] * step

    return _now


# ------------------------------------------------------------------
# start() — succeeds once the WebSocket reports connected
# ------------------------------------------------------------------


def test_start_succeeds_when_connected(slack_channel):
    ch, state = slack_channel
    state["connected"] = True

    ch.start()

    assert ch._started is True


# ------------------------------------------------------------------
# start() — raises when the WebSocket never connects (guard is reachable)
# ------------------------------------------------------------------


def test_start_raises_when_never_connected(monkeypatch, slack_channel):
    """The 10-second ``RuntimeError`` guard must be reachable. This fails if
    the poll truth-tests the bound ``is_connected`` method object (always
    truthy) instead of calling it: the loop would break on the first
    iteration and the guard would never fire."""
    ch, state = slack_channel
    state["connected"] = False  # socket never comes up

    # Fast-forward the deadline; no real sleeping.
    monkeypatch.setattr("time.monotonic", _stepping_monotonic(1.0))
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="Slack Socket Mode failed to connect within 10s"):
        ch.start()

    # A failed start must not be cached as started — callers may retry.
    assert ch._started is False
    # A failed start must tear down the partially-constructed handler and drop
    # the channel's reference to it so a retry cannot orphan its background
    # threads/executor. Regression for the SocketModeClient resource leak.
    assert state["close_calls"] == 1
    assert ch._handler is None


# ------------------------------------------------------------------
# start() — idempotent (documented Channel contract)
# ------------------------------------------------------------------


def test_start_is_idempotent(slack_channel):
    ch, state = slack_channel
    state["connected"] = True

    ch.start()
    ch.start()  # second call must short-circuit

    assert ch._started is True
    assert state["handler_constructed"] == 1
    assert state["start_calls"] == 1
    # A successful start must NOT close the handler (it stays live to serve
    # subsequent ask()/request_approval() calls on the same connection).
    assert state["close_calls"] == 0


# ------------------------------------------------------------------
# start() — failed start tears down the handler (no resource leak)
# ------------------------------------------------------------------


def test_failed_start_closes_handler_and_clears_reference(monkeypatch, slack_channel):
    """A failed start (10s readiness timeout) must ``close()`` the handler it
    constructed and drop ``_handler`` so the SocketModeClient's background
    IntervalRunner threads / ThreadPoolExecutor are shut down rather than
    orphaned for the process lifetime. Guards the bug where ``start()``
    raised without any teardown."""
    ch, state = slack_channel
    state["connected"] = False
    monkeypatch.setattr("time.monotonic", _stepping_monotonic(1.0))
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="failed to connect"):
        ch.start()

    assert state["handler_constructed"] == 1  # one handler was built
    assert state["close_calls"] == 1  # ...and it was torn down
    assert ch._handler is None
    assert ch._started is False


def test_success_path_does_not_close_handler(slack_channel):
    """The teardown must be scoped to the failure path only: a successful
    start keeps the handler live (the WebSocket connection is what serves
    subsequent tool calls). Guards against an over-broad fix that always
    closes the handler."""
    ch, state = slack_channel
    state["connected"] = True

    ch.start()

    assert ch._started is True
    assert state["close_calls"] == 0
    assert ch._handler is not None


# ------------------------------------------------------------------
# start() — retry after failure (the stdio per-tool-call path)
# ------------------------------------------------------------------


def test_retry_after_failure_succeeds_with_fresh_handler(monkeypatch, slack_channel):
    """The core regression: the stdio server calls ``start()`` per tool call on
    a long-lived channel singleton. A transient failure leaves ``_started``
    False (callers may retry); the *next* tool call re-enters ``start()``.
    The retried start must construct a *fresh* handler and succeed, while the
    failed handler from the first attempt was torn down — not orphaned.

    Pre-fix: the failed handler was left reachable from ``_handler`` and never
    ``close()``d; the retry overwrote ``_handler`` with a new one, orphaning
    the first handler's background threads (cumulative leak across retries).
    """
    ch, state = slack_channel
    monkeypatch.setattr("time.monotonic", _stepping_monotonic(1.0))
    monkeypatch.setattr("time.sleep", lambda _s: None)

    # First attempt: socket never comes up -> raises, handler torn down.
    state["connected"] = False
    with pytest.raises(RuntimeError, match="failed to connect"):
        ch.start()
    assert ch._started is False
    assert ch._handler is None
    assert state["handler_constructed"] == 1
    assert state["close_calls"] == 1

    # Second attempt: socket comes up -> succeeds with a fresh handler.
    state["connected"] = True
    ch.start()
    assert ch._started is True
    assert ch._handler is not None
    # A fresh handler was built for the retry (not reusing the orphaned one),
    # and the failed handler was closed exactly once.
    assert state["handler_constructed"] == 2
    assert state["close_calls"] == 1

    # Third call: idempotent no-op (handler stays the live one, no new teardown).
    ch.start()
    assert state["handler_constructed"] == 2
    assert state["close_calls"] == 1


def test_failed_start_releases_reference_before_close_raises(monkeypatch, slack_channel, caplog):
    """If ``handler.close()`` itself raises, the channel must still drop its
    reference to the handler and surface the *connect* failure (not the
    close failure) so a retry can build a fresh handler rather than reusing
    the partially-broken one. Guards the defensive ordering: ``_handler``
    is None'd *before* ``close()`` runs, and a close error is logged, not
    propagated in place of the connect-failure RuntimeError."""
    import logging

    ch, state = slack_channel
    state["connected"] = False
    state["close_raises"] = RuntimeError("close boom")
    monkeypatch.setattr("time.monotonic", _stepping_monotonic(1.0))
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with caplog.at_level(logging.WARNING, logger="call_a_human_mcp.channels.slack"):
        with pytest.raises(RuntimeError, match="failed to connect") as excinfo:
            ch.start()

    # The connect-failure RuntimeError propagates, not the "close boom" error.
    assert "close boom" not in str(excinfo.value)
    # close() was attempted (and raised)...
    assert state["close_calls"] == 1
    # ...but the reference was dropped first, so a retry is not poisoned by
    # the partially-started handler.
    assert ch._handler is None
    assert ch._started is False
    # The close failure was logged as a warning, not silently swallowed.
    assert any("Failed to close" in rec.message for rec in caplog.records)
