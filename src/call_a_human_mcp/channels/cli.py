"""CLI channel — reads/writes directly to the terminal via /dev/tty.

Works correctly alongside stdio MCP transport because it bypasses the
stdin/stdout pipes that the MCP protocol uses. Falls back to sys.stderr
(output) and sys.stdin (input) when /dev/tty is unavailable (e.g. CI,
Windows without a console).

Best used with:
  CALL_HUMAN_CHANNEL=cli call-a-human-mcp --transport sse
or during development with:
  CALL_HUMAN_CHANNEL=cli mcp dev src/call_a_human_mcp/server.py
"""

from __future__ import annotations

import sys

from call_a_human_mcp.channels.base import Channel
from call_a_human_mcp.request import HumanRequest

_SEP = "=" * 60


def _tty_write(text: str) -> None:
    """Write to the terminal even when stdout/stderr are redirected."""
    try:
        with open("/dev/tty", "w") as f:
            f.write(text)
            f.flush()
    except OSError:
        sys.stderr.write(text)
        sys.stderr.flush()


def _tty_read() -> str:
    """Read a line from the terminal even when stdin is redirected."""
    try:
        with open("/dev/tty") as f:
            return f.readline().strip()
    except OSError:
        return sys.stdin.readline().strip()


class CLIChannel(Channel):
    """Human-in-the-loop via the terminal.

    Prints requests to /dev/tty and reads responses from /dev/tty,
    so it works even when stdin/stdout are wired to the MCP protocol.
    No background threads needed — all I/O is synchronous.
    """

    def start(self) -> None:
        pass  # no background threads needed

    def ask(self, req: HumanRequest) -> str:
        _tty_write(f"\n{_SEP}\n")
        _tty_write("QUESTION FROM AI AGENT\n")
        _tty_write(f"{_SEP}\n")
        _tty_write(f"{req.question}\n")
        if req.context:
            _tty_write(f"\nContext: {req.context}\n")
        _tty_write(f"{_SEP}\n")
        _tty_write("Your answer: ")

        try:
            answer = _tty_read()
        except (EOFError, KeyboardInterrupt):
            raise TimeoutError("No answer provided (interrupted).")

        if not answer:
            raise TimeoutError("No answer provided (empty input).")

        return answer

    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        _tty_write(f"\n{_SEP}\n")
        _tty_write("APPROVAL REQUIRED\n")
        _tty_write(f"{_SEP}\n")
        _tty_write(f"Action: {req.action}\n")
        if req.details:
            _tty_write(f"\nDetails:\n{req.details}\n")
        _tty_write(f"{_SEP}\n")
        _tty_write("Approve? [y/N]: ")

        try:
            answer = _tty_read().lower()
        except (EOFError, KeyboardInterrupt):
            _tty_write("\nDenied (interrupted).\n")
            return False, ""

        approved = answer.lower() in ("y", "yes")
        _tty_write(("Approved.\n" if approved else "Denied.\n") + "\n")
        return approved, ""
