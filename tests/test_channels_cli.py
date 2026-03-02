"""Tests for the CLI channel."""

import pytest

from call_a_human_mcp.channels.cli import CLIChannel
from call_a_human_mcp.request import HumanRequest


@pytest.fixture
def channel():
    return CLIChannel()


def test_start_is_noop(channel):
    channel.start()
    channel.start()  # idempotent — no error


def test_ask_returns_input(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: "blue")
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    req = HumanRequest(question="What colour?")
    result = channel.ask(req)
    assert result == "blue"


def test_ask_empty_input_raises_timeout(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: "")
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    req = HumanRequest(question="What colour?")
    with pytest.raises(TimeoutError):
        channel.ask(req)


def test_ask_keyboard_interrupt_raises_timeout(channel, monkeypatch):
    def _raise():
        raise KeyboardInterrupt

    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", _raise)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    req = HumanRequest(question="interrupted?")
    with pytest.raises(TimeoutError):
        channel.ask(req)


def test_request_approval_yes(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: "y")
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    req = HumanRequest(action="delete file")
    approved, reason = channel.request_approval(req)
    assert approved is True


def test_request_approval_no(channel, monkeypatch):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: "n")
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    req = HumanRequest(action="delete file")
    approved, reason = channel.request_approval(req)
    assert approved is False


@pytest.mark.parametrize("answer", ["y", "yes", "Y", "YES"])
def test_request_approval_truthy_answers(channel, monkeypatch, answer):
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", lambda: answer)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    req = HumanRequest(action="do thing")
    approved, _ = channel.request_approval(req)
    assert approved is True


def test_request_approval_keyboard_interrupt(channel, monkeypatch):
    def _raise():
        raise KeyboardInterrupt

    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_read", _raise)
    monkeypatch.setattr("call_a_human_mcp.channels.cli._tty_write", lambda _: None)
    req = HumanRequest(action="do thing")
    approved, _ = channel.request_approval(req)
    assert approved is False
