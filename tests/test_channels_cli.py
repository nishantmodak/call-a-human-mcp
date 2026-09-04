"""Tests for the CLI channel."""

import pytest

from call_a_human_mcp.channels.cli import CLIChannel, _macos_ask
from call_a_human_mcp.request import HumanRequest


@pytest.fixture
def channel():
    return CLIChannel()


# ------------------------------------------------------------------
# start
# ------------------------------------------------------------------

def test_start_is_noop(channel):
    channel.start()
    channel.start()  # idempotent — no error


# ------------------------------------------------------------------
# /dev/tty path (tty available)
# ------------------------------------------------------------------

def test_ask_returns_input(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: True)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: "blue")
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    req = HumanRequest(question="What colour?")
    assert channel.ask(req) == "blue"


def test_ask_empty_input_raises_timeout(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: True)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: "")
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    with pytest.raises(TimeoutError):
        channel.ask(HumanRequest(question="What colour?"))


def test_ask_keyboard_interrupt_raises_timeout(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: True)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    with pytest.raises(TimeoutError):
        channel.ask(HumanRequest(question="interrupted?"))


def test_request_approval_yes(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: True)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: "y")
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    approved, _ = channel.request_approval(HumanRequest(action="delete file"))
    assert approved is True


def test_request_approval_no(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: True)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: "n")
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    approved, _ = channel.request_approval(HumanRequest(action="delete file"))
    assert approved is False


@pytest.mark.parametrize("answer", ["y", "yes", "Y", "YES"])
def test_request_approval_truthy_answers(channel, monkeypatch, answer):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: True)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: answer)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    approved, _ = channel.request_approval(HumanRequest(action="do thing"))
    assert approved is True


def test_request_approval_keyboard_interrupt(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: True)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    approved, _ = channel.request_approval(HumanRequest(action="do thing"))
    assert approved is False


# ------------------------------------------------------------------
# macOS dialog path (no tty, macOS available)
# ------------------------------------------------------------------

def test_ask_uses_macos_dialog_when_no_tty(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: False)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._macos_available", lambda: True)
    monkeypatch.setattr(
        "call_a_human_mcp.channels.cli._macos_ask",
        lambda q, c: "via dialog",
    )
    assert channel.ask(HumanRequest(question="Which env?")) == "via dialog"


def test_request_approval_uses_macos_dialog_when_no_tty(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: False)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._macos_available", lambda: True)
    monkeypatch.setattr(
        "call_a_human_mcp.channels.cli._macos_approve",
        lambda a, d: (True, ""),
    )
    approved, _ = channel.request_approval(HumanRequest(action="deploy"))
    assert approved is True


# ------------------------------------------------------------------
# macOS dialog path — _macos_ask osascript stdout handling
# ------------------------------------------------------------------


class _FakeCompletedProcess:
    """Minimal stand-in for subprocess.CompletedProcess used by _macos_ask."""

    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def _fake_osascript(monkeypatch, *, stdout: str = "", returncode: int = 0):
    """Patch the cli module's subprocess.run seam. Returns captured argv list."""
    captured: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        captured.append(list(cmd))
        return _FakeCompletedProcess(stdout=stdout, returncode=returncode)

    monkeypatch.setattr("call_a_human_mcp.channels.cli.subprocess.run", _run)
    return captured


def test_macos_ask_preserves_answer_with_comma_and_space(monkeypatch):
    _fake_osascript(monkeypatch, stdout="Use staging, but skip migrations")
    assert _macos_ask("Which env?", "") == "Use staging, but skip migrations"


def test_macos_ask_returns_stdout_verbatim_without_splitting(monkeypatch):
    raw = "button returned:OK, text returned:Use staging, but skip migrations"
    _fake_osascript(monkeypatch, stdout=raw)
    assert _macos_ask("Which env?", "") == raw


def test_macos_ask_script_extracts_text_returned_field(monkeypatch):
    captured = _fake_osascript(monkeypatch, stdout="yes")
    _macos_ask("Any thoughts?", "")
    script = captured[-1][2]
    assert script.startswith("text returned of (display dialog ")
    assert "button returned" not in script


# ------------------------------------------------------------------
# No tty, no macOS — raises clear TimeoutError
# ------------------------------------------------------------------

def test_ask_no_tty_no_macos_raises(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: False)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._macos_available", lambda: False)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    with pytest.raises(TimeoutError, match="No terminal available"):
        channel.ask(HumanRequest(question="hello?"))


def test_request_approval_no_tty_no_macos_raises(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._has_tty", lambda: False)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._macos_available", lambda: False)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    with pytest.raises(TimeoutError, match="No terminal available"):
        channel.request_approval(HumanRequest(action="deploy"))
