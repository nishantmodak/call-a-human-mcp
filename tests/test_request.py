"""Tests for HumanRequest dataclass."""

import threading

from call_a_human_mcp.request import HumanRequest


def test_default_request_id():
    r1 = HumanRequest()
    r2 = HumanRequest()
    assert r1.request_id != r2.request_id
    assert len(r1.request_id) == 32  # uuid4 hex


def test_event_is_threading_event():
    req = HumanRequest()
    assert isinstance(req.event, threading.Event)
    assert not req.event.is_set()


def test_event_not_shared_between_instances():
    r1 = HumanRequest()
    r2 = HumanRequest()
    r1.event.set()
    assert not r2.event.is_set()


def test_metadata_not_shared_between_instances():
    r1 = HumanRequest()
    r2 = HumanRequest()
    r1.metadata["key"] = "value"
    assert "key" not in r2.metadata


def test_fields():
    req = HumanRequest(
        question="What colour?",
        context="Picking a UI theme",
        action="deploy",
        details="to production",
    )
    assert req.question == "What colour?"
    assert req.context == "Picking a UI theme"
    assert req.action == "deploy"
    assert req.details == "to production"
    assert req.response == ""
    assert req.approved is False
    assert req.reason == ""
