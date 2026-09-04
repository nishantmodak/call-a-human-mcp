"""Shared test fixtures."""

import threading

import pytest

from call_a_human_mcp.channels.base import Channel
from call_a_human_mcp.request import HumanRequest


class ImmediateChannel(Channel):
    """A mock channel that resolves requests immediately with preset answers.

    Use this in tests to avoid network I/O and blocking waits.
    """

    def __init__(self, ask_response: str = "test answer", approved: bool = True):
        self.ask_response = ask_response
        self.approved = approved
        self.started = False
        self.ask_calls: list[HumanRequest] = []
        self.approval_calls: list[HumanRequest] = []

    def start(self) -> None:
        self.started = True

    def ask(self, req: HumanRequest) -> str:
        self.ask_calls.append(req)
        return self.ask_response

    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        self.approval_calls.append(req)
        return self.approved, "tester"


class TimeoutChannel(Channel):
    """A mock channel that always times out."""

    def start(self) -> None:
        pass

    def ask(self, req: HumanRequest) -> str:
        raise TimeoutError("simulated timeout")

    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        raise TimeoutError("simulated timeout")


class BlockingChannel(Channel):
    """A mock channel that blocks ask()/request_approval() on a threading.Event.

    Models the real channel behaviour that waits for a human reply: each call
    blocks the *worker thread* it runs on for up to ``delay`` seconds (the event
    is never set, so it times out after ``delay`` and then returns a answer).

    Records the name of the thread each blocking method runs on so tests can
    confirm the blocking wait was offloaded to a worker thread rather than
    running on the event loop thread.
    """

    def __init__(
        self,
        delay: float = 0.5,
        ask_response: str = "late-answer",
        approved: bool = True,
    ):
        self.delay = delay
        self.ask_response = ask_response
        self.approved = approved
        self.started = False
        self.start_call_threads: list[str] = []
        self.ask_call_threads: list[str] = []
        self.approval_call_threads: list[str] = []

    def start(self) -> None:
        self.started = True
        self.start_call_threads.append(threading.current_thread().name)

    def ask(self, req: HumanRequest) -> str:
        self.ask_call_threads.append(threading.current_thread().name)
        req.event.wait(timeout=self.delay)
        return self.ask_response

    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        self.approval_call_threads.append(threading.current_thread().name)
        req.event.wait(timeout=self.delay)
        return self.approved, "tester"


@pytest.fixture
def immediate_channel():
    return ImmediateChannel()


@pytest.fixture
def timeout_channel():
    return TimeoutChannel()
