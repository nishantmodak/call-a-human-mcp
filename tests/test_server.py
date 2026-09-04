"""Tests for FastMCP tool handlers using mock channels."""

import asyncio
import threading
import time

import pytest

import call_a_human_mcp.server as server_module
from call_a_human_mcp.config import Config
from call_a_human_mcp.server import ask_human, create_server, request_approval
from tests.conftest import BlockingChannel, ImmediateChannel, TimeoutChannel


@pytest.fixture(autouse=True)
def reset_channel():
    """Reset the module-level channel singleton between tests."""
    original = server_module._channel
    yield
    server_module._channel = original


def _set_channel(ch):
    server_module._channel = ch


# ------------------------------------------------------------------
# ask_human (direct handler call)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_human_returns_response():
    _set_channel(ImmediateChannel(ask_response="blue"))
    result = await ask_human(question="What colour?")
    assert result == "blue"


@pytest.mark.asyncio
async def test_ask_human_passes_context():
    ch = ImmediateChannel(ask_response="yes")
    _set_channel(ch)
    await ask_human(question="OK?", context="some context")
    assert ch.ask_calls[0].context == "some context"


@pytest.mark.asyncio
async def test_ask_human_timeout_raises_runtime_error():
    _set_channel(TimeoutChannel())
    with pytest.raises(RuntimeError, match="simulated timeout"):
        await ask_human(question="Will you timeout?")


@pytest.mark.asyncio
async def test_ask_human_no_channel_raises(monkeypatch):
    server_module._channel = None
    monkeypatch.delenv("CALL_HUMAN_CHANNEL", raising=False)
    with pytest.raises(RuntimeError, match="CALL_HUMAN_CHANNEL"):
        await ask_human(question="hello")


# ------------------------------------------------------------------
# request_approval (direct handler call)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_approval_approved():
    _set_channel(ImmediateChannel(approved=True))
    result = await request_approval(action="delete all data")
    assert result == {"approved": True, "reason": "tester"}


@pytest.mark.asyncio
async def test_request_approval_denied():
    _set_channel(ImmediateChannel(approved=False))
    result = await request_approval(action="send email blast")
    assert result["approved"] is False


@pytest.mark.asyncio
async def test_request_approval_passes_details():
    ch = ImmediateChannel()
    _set_channel(ch)
    await request_approval(action="restart server", details="prod-api-01")
    assert ch.approval_calls[0].details == "prod-api-01"


@pytest.mark.asyncio
async def test_request_approval_timeout_raises_runtime_error():
    _set_channel(TimeoutChannel())
    with pytest.raises(RuntimeError, match="simulated timeout"):
        await request_approval(action="nuke database")


@pytest.mark.asyncio
async def test_request_approval_no_channel_raises(monkeypatch):
    server_module._channel = None
    monkeypatch.delenv("CALL_HUMAN_CHANNEL", raising=False)
    with pytest.raises(RuntimeError, match="CALL_HUMAN_CHANNEL"):
        await request_approval(action="something")


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


# ------------------------------------------------------------------
# FastMCP dispatch path (call_tool) — happy path & shapes
#
# The tests above call the handlers directly. These go through the real
# FastMCP.call_tool -> Tool.run -> call_fn_with_arg_validation dispatch path
# that the SSE/stdio transports use, which is where the event-loop-blocking
# bug lived.
# ------------------------------------------------------------------


def _content_text(result):
    """Extract concatenated text from an mcp.call_tool result.

    call_tool returns either (content_blocks, structured_dict) for scalar
    returns or just content_blocks for dict returns; normalise both.
    """
    content = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(block, "text", "") for block in content)


@pytest.mark.asyncio
async def test_ask_human_dispatch_returns_response():
    _set_channel(ImmediateChannel(ask_response="blue"))
    result = await server_module.mcp.call_tool("ask_human", {"question": "What colour?"})
    assert "blue" in _content_text(result)


@pytest.mark.asyncio
async def test_request_approval_dispatch_returns_decision():
    _set_channel(ImmediateChannel(approved=True))
    result = await server_module.mcp.call_tool("request_approval", {"action": "deploy to prod"})
    assert '"approved"' in _content_text(result)
    assert "true" in _content_text(result).lower()


@pytest.mark.asyncio
async def test_ask_human_dispatch_propagates_timeout_as_tool_error():
    _set_channel(TimeoutChannel())
    # FastMCP wraps handler exceptions in ToolError ("Error executing tool ...").
    with pytest.raises(Exception, match="simulated timeout"):
        await server_module.mcp.call_tool("ask_human", {"question": "hi"})


@pytest.mark.asyncio
async def test_request_approval_dispatch_propagates_timeout_as_tool_error():
    _set_channel(TimeoutChannel())
    with pytest.raises(Exception, match="simulated timeout"):
        await server_module.mcp.call_tool("request_approval", {"action": "something"})


# ------------------------------------------------------------------
# Event-loop non-blocking guarantees (the actual bug fix)
#
# Pre-fix: ask_human/request_approval were sync handlers FastMCP ran inline
# on the event-loop thread, so a blocking threading.Event.wait() froze the
# whole loop. Post-fix: the handlers are async and offload the blocking
# channel calls to anyio worker threads, so the loop stays free.
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_human_does_not_block_event_loop():
    """A trivial async task scheduled while ask_human waits on a human must
    complete promptly. Pre-fix, the sync handler froze the loop inside
    ask()'s threading.Event.wait(), so the sentinel couldn't run until the
    human-wait returned (~delay seconds later).
    """
    _set_channel(BlockingChannel(delay=0.5))

    start = time.monotonic()
    sentinel_done = {}

    async def sentinel():
        # A small async sleep — only progresses if the event loop is free.
        await asyncio.sleep(0.02)
        sentinel_done["at"] = time.monotonic() - start

    # tool_task is created first so it starts running first (FIFO ready queue).
    # With the buggy sync handler it would block the loop for ~0.5s before the
    # sentinel could even start. With the async + offloaded handler the loop
    # stays free.
    tool_task = asyncio.create_task(server_module.mcp.call_tool("ask_human", {"question": "hi"}))
    sentinel_task = asyncio.create_task(sentinel())

    await sentinel_task
    assert sentinel_done["at"] < 0.35, (
        f"event loop was blocked: sentinel took {sentinel_done['at']:.2f}s "
        f"(expected <<0.5s); the sync handler likely froze the loop"
    )

    await tool_task


@pytest.mark.asyncio
async def test_request_approval_does_not_block_event_loop():
    """Same guarantee as above for request_approval."""
    _set_channel(BlockingChannel(delay=0.5))

    start = time.monotonic()
    sentinel_done = {}

    async def sentinel():
        await asyncio.sleep(0.02)
        sentinel_done["at"] = time.monotonic() - start

    tool_task = asyncio.create_task(
        server_module.mcp.call_tool("request_approval", {"action": "deploy"})
    )
    sentinel_task = asyncio.create_task(sentinel())

    await sentinel_task
    assert sentinel_done["at"] < 0.35, (
        f"event loop was blocked: sentinel took {sentinel_done['at']:.2f}s"
    )

    await tool_task


@pytest.mark.asyncio
async def test_ask_human_blocking_call_runs_on_worker_thread():
    """The blocking channel.ask() must be offloaded to an anyio worker
    thread, not run on the event-loop (Main) thread."""
    ch = BlockingChannel(delay=0.1)
    _set_channel(ch)

    await server_module.mcp.call_tool("ask_human", {"question": "hi"})

    assert ch.ask_call_threads, "ask() was never called"
    loop_thread = threading.current_thread().name
    assert ch.ask_call_threads[0] != loop_thread, (
        f"ask() ran on the event-loop thread ({loop_thread}); "
        "it must be offloaded to a worker thread"
    )
    assert "worker" in ch.ask_call_threads[0].lower(), (
        f"ask() ran on {ch.ask_call_threads[0]!r}; expected an anyio worker thread"
    )
    assert ch.start_call_threads, "start() was never called"
    assert ch.start_call_threads[0] != loop_thread, (
        f"start() ran on the event-loop thread ({loop_thread}); "
        "it must be offloaded to a worker thread"
    )


@pytest.mark.asyncio
async def test_request_approval_blocking_call_runs_on_worker_thread():
    ch = BlockingChannel(delay=0.1)
    _set_channel(ch)

    await server_module.mcp.call_tool("request_approval", {"action": "deploy"})

    loop_thread = threading.current_thread().name
    assert ch.approval_call_threads, "request_approval() was never called"
    assert ch.approval_call_threads[0] != loop_thread, (
        f"request_approval() ran on the event-loop thread ({loop_thread})"
    )
    assert "worker" in ch.approval_call_threads[0].lower(), (
        f"request_approval() ran on {ch.approval_call_threads[0]!r}; "
        "expected an anyio worker thread"
    )


@pytest.mark.asyncio
async def test_concurrent_ask_and_approval_run_in_parallel():
    """A blocking ask_human must not block a concurrent request_approval on
    the shared loop (the multi-client SSE scenario from the bug report)."""
    _set_channel(BlockingChannel(delay=0.4))

    start = time.monotonic()
    t1 = asyncio.create_task(server_module.mcp.call_tool("ask_human", {"question": "q1"}))
    t2 = asyncio.create_task(server_module.mcp.call_tool("request_approval", {"action": "a1"}))
    await asyncio.gather(t1, t2)
    elapsed = time.monotonic() - start

    assert elapsed < 0.7, f"mixed concurrent calls appear serialized (took {elapsed:.2f}s)"
