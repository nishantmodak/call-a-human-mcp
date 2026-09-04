"""FastMCP server — ask_human and request_approval tools."""

from __future__ import annotations

import logging
import time
from typing import Annotated

import anyio
from mcp.server.fastmcp import FastMCP

from call_a_human_mcp.audit import AuditLog
from call_a_human_mcp.channels.base import Channel
from call_a_human_mcp.config import Config, ConfigError
from call_a_human_mcp.request import HumanRequest

logger = logging.getLogger(__name__)

# Module-level singletons set by create_server()
_channel: Channel | None = None
_audit: AuditLog = AuditLog("")  # no-op until create_server() sets a real path

mcp = FastMCP(
    name="call-a-human",
    instructions=(
        "You have two human-in-the-loop tools. Use them proactively — do NOT ask "
        "the user whether to call them, just call them and let the human respond "
        "via Slack, Telegram, or dialog.\n\n"
        "call request_approval BEFORE any irreversible or high-stakes action: "
        "deleting files or data, sending messages or emails, making purchases, "
        "modifying production systems, running destructive commands, or anything "
        "that cannot be easily undone. Never say 'Should I proceed?' — call the "
        "tool and wait. Do not execute the action until you receive "
        "{\"approved\": true}.\n\n"
        "call ask_human when you are unsure about user preferences, credentials, "
        "file paths, or any ambiguous decision — never guess. The human's reply "
        "comes back as text you can use directly."
    ),
)


def _get_channel() -> Channel:
    global _channel
    if _channel is None:
        # Auto-initialize from env when imported directly (e.g. `mcp dev server.py`).
        # In that workflow __main__.py is never run, so create_server() is never called.
        import os
        if os.environ.get("CALL_HUMAN_CHANNEL"):
            create_server(Config.from_env())
        else:
            raise RuntimeError(
                "CALL_HUMAN_CHANNEL is not set. "
                "Add it to your environment or MCP client config."
            )
    return _channel  # type: ignore[return-value]


@mcp.tool()
async def ask_human(
    question: Annotated[str, "The question to ask the human"],
    context: Annotated[str, "Optional background context to help the human answer"] = "",
) -> str:
    """Ask the human a free-form question and wait for their text reply.

    Use this when you need information only a human can provide: a preference,
    a clarification, credentials, or a decision on an ambiguous situation.
    The tool blocks until the human replies or the timeout expires.
    """
    req = HumanRequest(question=question, context=context)
    channel = _get_channel()
    # Offload the (potentially blocking, up to ~10s on Slack) connection setup
    # so the shared event loop stays responsive for other clients.
    await anyio.to_thread.run_sync(channel.start)

    started = time.monotonic()
    try:
        # ask() blocks on threading.Event.wait() for up to CALL_HUMAN_TIMEOUT.
        # Run it on a worker thread so the event loop (and every other SSE
        # connection sharing it) keeps making progress while we wait.
        response = await anyio.to_thread.run_sync(channel.ask, req)
    except TimeoutError as exc:
        _audit.record({
            "request_id": req.request_id,
            "tool": "ask_human",
            "question": question,
            "context": context,
            "timed_out": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
        })
        raise RuntimeError(str(exc)) from exc

    _audit.record({
        "request_id": req.request_id,
        "tool": "ask_human",
        "question": question,
        "context": context,
        "timed_out": False,
        "duration_ms": int((time.monotonic() - started) * 1000),
    })
    return response


@mcp.tool()
async def request_approval(
    action: Annotated[str, "Short description of the action that needs approval"],
    details: Annotated[str, "Additional details such as parameters, file paths, or impact"] = "",
) -> dict:
    """Ask the human to approve or deny a proposed action before executing it.

    Call this before any irreversible or high-stakes action (deleting data,
    sending messages, modifying production systems, spending money, etc.).
    The tool blocks until the human approves/denies or the timeout expires.

    Returns {"approved": bool, "reason": str} where reason is the human's
    username or name if available.
    """
    req = HumanRequest(action=action, details=details)
    channel = _get_channel()
    # Offload the (potentially blocking, up to ~10s on Slack) connection setup
    # so the shared event loop stays responsive for other clients.
    await anyio.to_thread.run_sync(channel.start)

    started = time.monotonic()
    try:
        # request_approval() blocks on threading.Event.wait() for up to
        # CALL_HUMAN_TIMEOUT. Run it on a worker thread so the event loop (and
        # every other SSE connection sharing it) keeps making progress.
        approved, reason = await anyio.to_thread.run_sync(channel.request_approval, req)
    except TimeoutError as exc:
        _audit.record({
            "request_id": req.request_id,
            "tool": "request_approval",
            "action": action,
            "details": details,
            "approved": False,
            "reason": "",
            "timed_out": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
        })
        raise RuntimeError(str(exc)) from exc

    _audit.record({
        "request_id": req.request_id,
        "tool": "request_approval",
        "action": action,
        "details": details,
        "approved": approved,
        "reason": reason,
        "timed_out": False,
        "duration_ms": int((time.monotonic() - started) * 1000),
    })
    return {"approved": approved, "reason": reason}


def create_server(config: Config, host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    """Initialise the channel and audit log singletons, return the FastMCP instance."""
    global _channel, _audit, mcp

    _audit = AuditLog(config.audit_log)
    mcp.settings.host = host
    mcp.settings.port = port

    if config.channel == "cli":
        from call_a_human_mcp.channels.cli import CLIChannel
        _channel = CLIChannel()
    elif config.channel == "slack":
        from call_a_human_mcp.channels.slack import SlackChannel
        _channel = SlackChannel(config)
    elif config.channel == "telegram":
        from call_a_human_mcp.channels.telegram import TelegramChannel
        _channel = TelegramChannel(config)
    else:
        raise ConfigError(f"Unknown channel: {config.channel!r}")

    return mcp
