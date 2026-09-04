"""Tests for ``SlackChannel.start()`` — Socket Mode readiness contract.

``slack_sdk.socket_mode.builtin.SocketModeClient.is_connected`` is a method
(``def is_connected(self) -> bool``), not a ``@property``, across the
supported ``slack-sdk>=3.27.0`` range. The readiness poll in ``start()``
must therefore *call* it; truth-testing the bound method object would always
report "connected" and make the 10-second failure guard unreachable.

These tests pin the observable contract — ``start()`` succeeds when the
socket comes up, raises when it never does, and is idempotent — without
touching the network or coupling to polling call counts.
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
    tests set it before calling ``start()``. ``handler``/``start`` counters
    back the idempotency assertion.
    """

    state: dict = {
        "connected": True,
        "start_calls": 0,
        "handler_constructed": 0,
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
