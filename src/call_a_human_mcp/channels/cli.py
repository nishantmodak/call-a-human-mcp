"""CLI channel — reads/writes directly to the terminal via /dev/tty.

Works correctly alongside stdio MCP transport because it bypasses the
stdin/stdout pipes that the MCP protocol uses.

Fallback chain when /dev/tty is unavailable (e.g. backgrounded process
launched by Claude Desktop, CI, Windows, Docker without an attached TTY):

  1. macOS native dialog via osascript — pops a system dialog visible even
     when the process has no terminal. Works with Claude Desktop on macOS.
  2. sys.stderr / sys.stdin — last resort; prompts go to the log and input
     is not possible interactively. Times out or raises.

Best used with:
  CALL_HUMAN_CHANNEL=cli call-a-human-mcp --transport sse
or during development with:
  CALL_HUMAN_CHANNEL=cli mcp dev src/call_a_human_mcp/server.py
"""

from __future__ import annotations

import subprocess
import sys

from call_a_human_mcp.channels.base import Channel
from call_a_human_mcp.request import HumanRequest

_SEP = "=" * 60


# ---------------------------------------------------------------------------
# Terminal I/O helpers
# ---------------------------------------------------------------------------

def _has_tty() -> bool:
    try:
        with open("/dev/tty") as f:
            return f.readable()
    except OSError:
        return False


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


# ---------------------------------------------------------------------------
# macOS native dialog helpers (osascript)
# ---------------------------------------------------------------------------

def _macos_available() -> bool:
    """Return True if we can use osascript (macOS only)."""
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(["which", "osascript"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _macos_ask(question: str, context: str) -> str:
    """Show a macOS input dialog and return the user's text."""
    prompt = question
    if context:
        prompt = f"{question}\n\nContext: {context}"
    script = f'display dialog {_quote(prompt)} default answer "" with title "AI Agent Question"'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # User clicked Cancel
        raise TimeoutError("No answer provided (dialog cancelled).")
    # osascript returns "button returned:OK, text returned:answer"
    for part in result.stdout.strip().split(", "):
        if part.startswith("text returned:"):
            return part[len("text returned:"):]
    return ""


def _macos_approve(action: str, details: str) -> tuple[bool, str]:
    """Show a macOS approval dialog with Approve/Deny buttons."""
    body = f"Action: {action}"
    if details:
        body += f"\n\nDetails: {details}"
    script = (
        f'display dialog {_quote(body)} '
        f'buttons {{"Deny", "Approve"}} '
        f'default button "Approve" '
        f'cancel button "Deny" '
        f'with title "AI Agent Approval Required"'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    # osascript exits 0 on Approve, non-zero on Deny/Cancel
    approved = result.returncode == 0
    return approved, ""


def _quote(text: str) -> str:
    """Escape a string for embedding in an AppleScript literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class CLIChannel(Channel):
    """Human-in-the-loop via the terminal (or macOS native dialogs).

    Resolution order:
      1. /dev/tty  — when a real terminal is attached (mcp dev, SSE mode)
      2. osascript — when running as a backgrounded process on macOS
                     (Claude Desktop stdio mode)
      3. stderr    — last resort; prompts go to the log
    """

    def start(self) -> None:
        pass  # no background threads needed

    def ask(self, req: HumanRequest) -> str:
        if _has_tty():
            return self._tty_ask(req)
        if _macos_available():
            return _macos_ask(req.question, req.context)
        # Last resort — prompt goes to stderr, no interactive input possible
        _tty_write(f"\n[call-a-human-mcp] QUESTION: {req.question}\n")
        raise TimeoutError(
            "No terminal available. Use Slack or Telegram for Claude Desktop, "
            "or run with --transport sse in a terminal window."
        )

    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        if _has_tty():
            return self._tty_approve(req)
        if _macos_available():
            return _macos_approve(req.action, req.details)
        _tty_write(f"\n[call-a-human-mcp] APPROVAL NEEDED: {req.action}\n")
        raise TimeoutError(
            "No terminal available. Use Slack or Telegram for Claude Desktop, "
            "or run with --transport sse in a terminal window."
        )

    # ------------------------------------------------------------------
    # /dev/tty implementation
    # ------------------------------------------------------------------

    def _tty_ask(self, req: HumanRequest) -> str:
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

    def _tty_approve(self, req: HumanRequest) -> tuple[bool, str]:
        _tty_write(f"\n{_SEP}\n")
        _tty_write("APPROVAL REQUIRED\n")
        _tty_write(f"{_SEP}\n")
        _tty_write(f"Action: {req.action}\n")
        if req.details:
            _tty_write(f"\nDetails:\n{req.details}\n")
        _tty_write(f"{_SEP}\n")
        _tty_write("Approve? [y/N]: ")

        try:
            answer = _tty_read()
        except (EOFError, KeyboardInterrupt):
            _tty_write("\nDenied (interrupted).\n")
            return False, ""

        approved = answer.lower() in ("y", "yes")
        _tty_write(("Approved.\n" if approved else "Denied.\n") + "\n")
        return approved, ""
