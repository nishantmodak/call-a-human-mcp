"""Audit log — append-only JSONL record of all human requests and outcomes.

Each line is a JSON object. Enabled by setting CALL_HUMAN_AUDIT_LOG to a
file path. Disabled (no-op) when the env var is unset or empty.

Example entry (ask_human):
    {"timestamp": "2024-03-01T12:00:00.123Z", "request_id": "abc123",
     "tool": "ask_human", "question": "Which env?", "context": "",
     "timed_out": false, "duration_ms": 4210}

Example entry (request_approval):
    {"timestamp": "2024-03-01T12:05:00.456Z", "request_id": "def456",
     "tool": "request_approval", "action": "delete db", "details": "",
     "approved": true, "reason": "alice", "timed_out": false, "duration_ms": 8700}
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AuditLog:
    """Appends JSONL entries to a file for every completed request.

    Thread-safe for concurrent writes: each write opens, appends, and
    closes the file atomically at the OS level (append mode is atomic
    on POSIX for writes smaller than PIPE_BUF, which a single JSON line
    always is).
    """

    def __init__(self, path: str) -> None:
        self._path = path or ""
        if self._path:
            # Ensure the parent directory exists at startup
            parent = os.path.dirname(os.path.abspath(self._path))
            os.makedirs(parent, exist_ok=True)
            logger.info("Audit log enabled: %s", self._path)

    @property
    def enabled(self) -> bool:
        return bool(self._path)

    def record(self, entry: dict) -> None:
        """Append one entry to the log. No-op when disabled."""
        if not self._path:
            return
        entry["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            logger.warning("Failed to write audit log entry: %s", exc)
