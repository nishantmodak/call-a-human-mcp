"""FastMCP server — ask_human and request_approval tools."""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.server.fastmcp import FastMCP

from call_a_human_mcp.channels.base import Channel
from call_a_human_mcp.config import Config, ConfigError
from call_a_human_mcp.request import HumanRequest

logger = logging.getLogger(__name__)

# Module-level singleton set by create_server()
_channel: Channel | None = None

mcp = FastMCP(
    name="call-a-human",
    instructions=(
        "Use ask_human when you need a free-form answer from a human — "
        "for preferences, clarifications, or ambiguous decisions. "
        "Use request_approval before taking any irreversible or high-stakes action."
    ),
)


def _get_channel() -> Channel:
    if _channel is None:
        raise RuntimeError(
            "Channel not initialised. Call create_server() before invoking MCP tools."
        )
    return _channel


@mcp.tool()
def ask_human(
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
    # Lazily start the channel background thread on first tool call
    channel.start()
    try:
        return channel.ask(req)
    except TimeoutError as exc:
        raise RuntimeError(str(exc)) from exc


@mcp.tool()
def request_approval(
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
    # Lazily start the channel background thread on first tool call
    channel.start()
    try:
        approved, reason = channel.request_approval(req)
        return {"approved": approved, "reason": reason}
    except TimeoutError as exc:
        raise RuntimeError(str(exc)) from exc


def create_server(config: Config) -> FastMCP:
    """Initialise the channel singleton and return the FastMCP instance."""
    global _channel

    if config.channel == "slack":
        from call_a_human_mcp.channels.slack import SlackChannel
        _channel = SlackChannel(config)
    elif config.channel == "telegram":
        from call_a_human_mcp.channels.telegram import TelegramChannel
        _channel = TelegramChannel(config)
    else:
        raise ConfigError(f"Unknown channel: {config.channel!r}")

    return mcp
