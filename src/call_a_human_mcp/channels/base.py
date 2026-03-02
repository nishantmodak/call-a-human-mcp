"""Abstract base class for notification channels."""

from __future__ import annotations

from abc import ABC, abstractmethod

from call_a_human_mcp.request import HumanRequest


class Channel(ABC):
    """Every notification channel implements this interface.

    Contract:
    - start() initialises background threads/connections. Must be idempotent.
    - ask() delivers the question to the human and blocks until a text reply
      arrives or the timeout expires.
    - request_approval() presents Approve/Deny affordances and blocks until
      clicked or the timeout expires.

    Both ask() and request_approval() raise TimeoutError on timeout.

    To add a new channel (SMS, email, voice):
    1. Create a new file in channels/ that subclasses Channel.
    2. Implement start(), ask(), and request_approval().
    3. Add its name to config.py validation and its env vars.
    4. Add a factory branch in server.py's create_server().
    """

    @abstractmethod
    def start(self) -> None:
        """Start background threads/connections. Idempotent."""

    @abstractmethod
    def ask(self, req: HumanRequest) -> str:
        """Post the question; block until the human replies.

        Returns the human's text reply.
        Raises TimeoutError if the configured timeout expires.
        """

    @abstractmethod
    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        """Post the approval request; block until the human clicks.

        Returns (approved: bool, reason: str).
        Raises TimeoutError if the configured timeout expires.
        """
