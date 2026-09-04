"""Regression test for the `--check` Slack Socket Mode failure path.

Step 4 of ``_check_slack`` runs ``_start_and_signal`` in a background daemon
thread and waits up to 10s for it to signal success. Its ``except`` block
previously referenced an undefined ``logger`` and raised ``NameError`` instead
of logging the connection error, killing the thread without emitting the debug
log. This test drives the real ``_check_slack`` with stubbed Slack SDK classes
and a synchronous thread to guard against that regression.
"""

import logging
import threading

import pytest

from call_a_human_mcp.config import Config


class _FakeWebClient:
    """Stands in for ``slack_sdk.WebClient``; steps 1 and 3 succeed."""

    def __init__(self, token=None):
        self.token = token

    def auth_test(self):
        return {"user": "checkbot", "team": "TestWorkspace"}

    def chat_postMessage(self, **kwargs):
        return {"ts": "1700000000.000100"}


class _FakeApp:
    """Stands in for ``slack_bolt.App``."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _RaisingSocketModeHandler:
    """Stands in for ``SocketModeHandler`` whose ``connect()`` raises."""

    def __init__(self, app, app_token):
        self.app = app
        self.app_token = app_token

    def connect(self):
        raise RuntimeError("socket_mode_unavailable")


class _SyncThread:
    """Runs the target callable synchronously in the current thread."""

    def __init__(self, target=None, **kwargs):
        self.target = target

    def start(self):
        self.target()

    def join(self, timeout=None):
        pass


@pytest.fixture
def slack_env(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "slack")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-fake-but-well-formed")
    monkeypatch.setenv("SLACK_CHANNEL_ID", "C123456")
    return Config.from_env()


@pytest.fixture(autouse=True)
def _sync_threading(monkeypatch):
    """Run ``threading.Thread`` targets synchronously for deterministic tests."""
    monkeypatch.setattr(threading, "Thread", _SyncThread)


def test_socket_mode_failure_logs_without_nameerror(slack_env, monkeypatch, caplog):
    """On a Socket Mode connect failure, the except block logs (no NameError).

    The failure path must emit the debug record on the ``call_a_human_mcp.check``
    logger — not raise ``NameError`` — and still fall through to the 10s-timeout
    exit-1 behaviour.
    """
    from call_a_human_mcp import __main__ as main_module

    monkeypatch.setattr("slack_sdk.WebClient", _FakeWebClient)
    monkeypatch.setattr("slack_bolt.App", _FakeApp)
    monkeypatch.setattr(
        "slack_bolt.adapter.socket_mode.SocketModeHandler", _RaisingSocketModeHandler
    )
    # On the failure path `connected` is never set; avoid the real 10s wait.
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: False)

    caplog.set_level(logging.DEBUG, logger="call_a_human_mcp.check")

    with pytest.raises(SystemExit) as excinfo:
        main_module._check_slack(slack_env)
    assert excinfo.value.code == 1

    # The except block ran logger.debug(...) rather than raising NameError.
    debug_records = [r for r in caplog.records if r.name == "call_a_human_mcp.check"]
    assert len(debug_records) == 1
    assert debug_records[0].levelno == logging.DEBUG
    assert "Socket Mode connect error" in debug_records[0].getMessage()
    assert "socket_mode_unavailable" in debug_records[0].getMessage()
