"""Tests for the audit log."""

import json
import os

import pytest

from call_a_human_mcp.audit import AuditLog


def test_disabled_when_no_path():
    log = AuditLog("")
    assert not log.enabled


def test_enabled_when_path_set(tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    assert log.enabled


def test_record_writes_jsonl(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLog(path)
    log.record({"tool": "ask_human", "question": "Who?", "timed_out": False, "duration_ms": 100})
    log.record({"tool": "request_approval", "action": "delete", "approved": True, "duration_ms": 200})

    with open(path) as f:
        lines = f.readlines()

    assert len(lines) == 2
    entry1 = json.loads(lines[0])
    assert entry1["tool"] == "ask_human"
    assert entry1["question"] == "Who?"
    assert "timestamp" in entry1

    entry2 = json.loads(lines[1])
    assert entry2["approved"] is True


def test_record_noop_when_disabled():
    log = AuditLog("")
    log.record({"tool": "ask_human"})  # should not raise


def test_record_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "audit.jsonl")
    log = AuditLog(path)
    log.record({"tool": "ask_human", "duration_ms": 1})
    assert os.path.exists(path)


def test_timestamp_is_utc_iso(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLog(path)
    log.record({"tool": "ask_human", "duration_ms": 1})

    with open(path) as f:
        entry = json.loads(f.read())

    ts = entry["timestamp"]
    assert ts.endswith("Z")
    assert "T" in ts


def test_audit_log_from_server(tmp_path, monkeypatch):
    """Integration: server.py wires audit log into tool calls."""
    import call_a_human_mcp.server as server_module
    from call_a_human_mcp.config import Config
    from call_a_human_mcp.server import ask_human, create_server, request_approval
    from tests.conftest import ImmediateChannel

    audit_path = str(tmp_path / "audit.jsonl")
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "cli")
    monkeypatch.setenv("CALL_HUMAN_AUDIT_LOG", audit_path)

    config = Config.from_env()
    create_server(config)
    server_module._channel = ImmediateChannel(ask_response="blue", approved=True)

    ask_human(question="Favourite colour?", context="picking a theme")
    request_approval(action="deploy to prod", details="v1.2.3")

    with open(audit_path) as f:
        lines = f.readlines()

    assert len(lines) == 2
    e1 = json.loads(lines[0])
    assert e1["tool"] == "ask_human"
    assert e1["question"] == "Favourite colour?"
    assert e1["timed_out"] is False
    assert isinstance(e1["duration_ms"], int)

    e2 = json.loads(lines[1])
    assert e2["tool"] == "request_approval"
    assert e2["action"] == "deploy to prod"
    assert e2["approved"] is True
    assert e2["timed_out"] is False
