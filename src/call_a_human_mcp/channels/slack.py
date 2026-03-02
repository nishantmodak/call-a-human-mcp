"""Slack channel adapter using Bolt Socket Mode."""

from __future__ import annotations

import logging
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from call_a_human_mcp.channels.base import Channel
from call_a_human_mcp.config import Config
from call_a_human_mcp.request import HumanRequest

logger = logging.getLogger(__name__)


class SlackChannel(Channel):
    """Human-in-the-loop via Slack Block Kit + Socket Mode.

    Thread safety
    -------------
    _pending_approvals and _pending_asks are dicts keyed by request_id.
    The tool handler thread adds an entry then blocks on event.wait().
    The Bolt event handler (Socket Mode background thread) reads the entry,
    sets result fields, and calls event.set().

    Because only one entry per request_id is active at a time and CPython's
    GIL protects individual dict reads/writes, no explicit lock is needed for
    the dicts. _start_lock protects the one-time initialisation of the
    Socket Mode handler.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._app = App(token=config.slack_bot_token)
        self._handler: SocketModeHandler | None = None
        self._started = False
        self._start_lock = threading.Lock()

        # request_id -> HumanRequest (active approval requests)
        self._pending_approvals: dict[str, HumanRequest] = {}

        # request_id -> HumanRequest (active ask requests)
        self._pending_asks: dict[str, HumanRequest] = {}
        # thread_ts -> request_id (reverse lookup for message events)
        self._ts_to_request_id: dict[str, str] = {}

        self._register_handlers()

    # ------------------------------------------------------------------
    # Channel interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the Socket Mode handler in a daemon thread. Idempotent."""
        with self._start_lock:
            if self._started:
                return
            self._handler = SocketModeHandler(
                self._app, self._config.slack_app_token
            )
            # Run in a daemon thread so it doesn't block the MCP server
            # and exits cleanly when the main process exits.
            t = threading.Thread(
                target=self._handler.start,
                name="slack-socket-mode",
                daemon=True,
            )
            t.start()
            self._started = True
            logger.info("Slack Socket Mode handler started.")

    def ask(self, req: HumanRequest) -> str:
        """Post a question to Slack and wait for a thread reply."""
        self.start()

        client = WebClient(token=self._config.slack_bot_token)
        blocks = self._build_ask_blocks(req)
        result = client.chat_postMessage(
            channel=self._config.slack_channel_id,
            text=f"Question from AI agent: {req.question}",
            blocks=blocks,
        )
        thread_ts: str = result["ts"]

        # Register in both lookup tables before waiting
        self._pending_asks[req.request_id] = req
        self._ts_to_request_id[thread_ts] = req.request_id
        req.metadata["thread_ts"] = thread_ts

        answered = req.event.wait(timeout=self._config.timeout)

        # Clean up lookup tables regardless of outcome
        self._pending_asks.pop(req.request_id, None)
        self._ts_to_request_id.pop(thread_ts, None)

        if not answered:
            try:
                client.chat_postMessage(
                    channel=self._config.slack_channel_id,
                    thread_ts=thread_ts,
                    text="_(Request timed out — no human response received.)_",
                )
            except Exception:
                pass
            raise TimeoutError(
                f"No reply from human within {self._config.timeout}s "
                f"(request {req.request_id})"
            )

        return req.response

    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        """Post an approval request with Approve/Deny buttons and wait."""
        self.start()

        client = WebClient(token=self._config.slack_bot_token)
        blocks = self._build_approval_blocks(req)
        result = client.chat_postMessage(
            channel=self._config.slack_channel_id,
            text=f"Approval required: {req.action}",
            blocks=blocks,
        )
        msg_ts: str = result["ts"]
        req.metadata["msg_ts"] = msg_ts

        self._pending_approvals[req.request_id] = req
        answered = req.event.wait(timeout=self._config.timeout)
        self._pending_approvals.pop(req.request_id, None)

        if not answered:
            raise TimeoutError(
                f"No approval within {self._config.timeout}s "
                f"(request {req.request_id})"
            )

        return req.approved, req.reason

    # ------------------------------------------------------------------
    # Bolt event/action handlers
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """Wire up Bolt listeners for button clicks and thread replies."""

        @self._app.action("approve_action")
        def handle_approve(ack, body, action):
            ack()
            self._handle_button(body, action, approved=True)

        @self._app.action("deny_action")
        def handle_deny(ack, body, action):
            ack()
            self._handle_button(body, action, approved=False)

        @self._app.event("message")
        def handle_message(event, say):
            """Route thread replies back to waiting ask() calls."""
            thread_ts = event.get("thread_ts")
            ts = event.get("ts")

            # Only thread replies: thread_ts is set and differs from ts
            if not thread_ts or thread_ts == ts:
                return
            # Skip bot/system messages (they have a subtype)
            if event.get("subtype"):
                return

            request_id = self._ts_to_request_id.get(thread_ts)
            if request_id is None:
                return

            req = self._pending_asks.get(request_id)
            if req is None:
                return

            req.response = event.get("text", "").strip()
            req.event.set()

    def _handle_button(self, body: dict, action: dict, *, approved: bool) -> None:
        request_id: str = action.get("value", "")
        req = self._pending_approvals.get(request_id)
        if req is None:
            logger.warning("Button click for unknown request_id: %s", request_id)
            return

        user_id = body.get("user", {}).get("id", "")
        user_name = body.get("user", {}).get("name", "unknown")
        req.approved = approved
        req.reason = user_name
        req.event.set()

        # Update the Slack message to replace buttons with decision text
        try:
            channel = body["container"]["channel_id"]
            message_ts = body["container"]["message_ts"]
            decision = "Approved" if approved else "Denied"
            WebClient(token=self._config.slack_bot_token).chat_update(
                channel=channel,
                ts=message_ts,
                text=f"{decision} by {user_name}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"*{decision}* by <@{user_id}>"
                                if user_id
                                else f"*{decision}* by {user_name}"
                            ),
                        },
                    }
                ],
            )
        except Exception as exc:
            logger.warning("Failed to update approval message: %s", exc)

    # ------------------------------------------------------------------
    # Block Kit builders
    # ------------------------------------------------------------------

    def _build_ask_blocks(self, req: HumanRequest) -> list[dict]:
        blocks: list[dict] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":speech_balloon: *Question from AI agent*\n{req.question}",
                },
            },
        ]
        if req.context:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"*Context:* {req.context}"}
                    ],
                }
            )
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"_Reply in this thread to answer. "
                            f"Request ID: `{req.request_id}`_"
                        ),
                    }
                ],
            }
        )
        return blocks

    def _build_approval_blocks(self, req: HumanRequest) -> list[dict]:
        blocks: list[dict] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":rotating_light: *AI Agent requesting approval*\n"
                        f"*Action:* {req.action}"
                    ),
                },
            },
        ]
        if req.details:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Details:*\n```{req.details}```"},
                }
            )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve_action",
                        "value": req.request_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Deny"},
                        "style": "danger",
                        "action_id": "deny_action",
                        "value": req.request_id,
                    },
                ],
            }
        )
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"_Request ID: `{req.request_id}`_"}
                ],
            }
        )
        return blocks
