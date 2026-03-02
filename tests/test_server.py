"""Tests for FastMCP tool handlers using mock channels."""

import pytest

import call_a_human_mcp.server as server_module
from call_a_human_mcp.config import Config
from call_a_human_mcp.server import ask_human, create_server, request_approval
from tests.conftest import ImmediateChannel, TimeoutChannel


@pytest.fixture(autouse=True)
def reset_channel():
    """Reset the module-level channel singleton between tests."""
    original = server_module._channel
    yield
    server_module._channel = original


def _set_channel(ch):
    server_module._channel = ch


# ------------------------------------------------------------------
# ask_human
# ------------------------------------------------------------------


def test_ask_human_returns_response():
    _set_channel(ImmediateChannel(ask_response="blue"))
    result = ask_human(question="What colour?")
    assert result == "blue"


def test_ask_human_passes_context():
    ch = ImmediateChannel(ask_response="yes")
    _set_channel(ch)
    ask_human(question="OK?", context="some context")
    assert ch.ask_calls[0].context == "some context"


def test_ask_human_timeout_raises_runtime_error():
    _set_channel(TimeoutChannel())
    with pytest.raises(RuntimeError, match="simulated timeout"):
        ask_human(question="Will you timeout?")


def test_ask_human_no_channel_raises(monkeypatch):
    server_module._channel = None
    monkeypatch.delenv("CALL_HUMAN_CHANNEL", raising=False)
    with pytest.raises(RuntimeError, match="CALL_HUMAN_CHANNEL"):
        ask_human(question="hello")


# ------------------------------------------------------------------
# request_approval
# ------------------------------------------------------------------


def test_request_approval_approved():
    _set_channel(ImmediateChannel(approved=True))
    result = request_approval(action="delete all data")
    assert result == {"approved": True, "reason": "tester"}


def test_request_approval_denied():
    _set_channel(ImmediateChannel(approved=False))
    result = request_approval(action="send email blast")
    assert result["approved"] is False


def test_request_approval_passes_details():
    ch = ImmediateChannel()
    _set_channel(ch)
    request_approval(action="restart server", details="prod-api-01")
    assert ch.approval_calls[0].details == "prod-api-01"


def test_request_approval_timeout_raises_runtime_error():
    _set_channel(TimeoutChannel())
    with pytest.raises(RuntimeError, match="simulated timeout"):
        request_approval(action="nuke database")


def test_request_approval_no_channel_raises(monkeypatch):
    server_module._channel = None
    monkeypatch.delenv("CALL_HUMAN_CHANNEL", raising=False)
    with pytest.raises(RuntimeError, match="CALL_HUMAN_CHANNEL"):
        request_approval(action="something")


# ------------------------------------------------------------------
# create_server
# ------------------------------------------------------------------


def test_create_server_cli(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "cli")
    config = Config.from_env()
    mcp = create_server(config)
    assert mcp.name == "call-a-human"
    from call_a_human_mcp.channels.cli import CLIChannel
    assert isinstance(server_module._channel, CLIChannel)


def test_create_server_returns_fastmcp_instance(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "cli")
    config = Config.from_env()
    from mcp.server.fastmcp import FastMCP
    mcp = create_server(config)
    assert isinstance(mcp, FastMCP)
