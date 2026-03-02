"""Shared test fixtures."""

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


@pytest.fixture
def immediate_channel():
    return ImmediateChannel()


@pytest.fixture
def timeout_channel():
    return TimeoutChannel()
