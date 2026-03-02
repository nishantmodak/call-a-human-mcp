"""Shared dataclass for pending human requests."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HumanRequest:
    """Represents a single pending request awaiting a human response.

    Created by the MCP tool handler and passed to the channel adapter.
    The adapter fills in the response fields then calls event.set() to
    unblock the tool handler.
    """

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # Set by the tool handler before passing to the adapter
    question: str = ""
    context: str = ""
    action: str = ""    # for request_approval only
    details: str = ""   # for request_approval only

    # Written by the adapter, read by the tool handler after event fires
    response: str = ""      # human's text reply (ask_human)
    approved: bool = False  # (request_approval)
    reason: str = ""        # human's name or explanation (request_approval)

    # Synchronisation — adapter calls event.set() when done
    event: threading.Event = field(default_factory=threading.Event)

    # Extra metadata adapters may attach (e.g. Slack thread_ts)
    metadata: dict[str, Any] = field(default_factory=dict)
