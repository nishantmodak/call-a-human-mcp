"""Telegram channel adapter using raw Bot API + long-polling."""

from __future__ import annotations

import logging
import threading
import time

import requests

from call_a_human_mcp.channels.base import Channel
from call_a_human_mcp.config import Config
from call_a_human_mcp.request import HumanRequest

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramChannel(Channel):
    """Human-in-the-loop via Telegram Bot API.

    Long-polling model
    ------------------
    A single daemon thread runs _polling_loop(). It calls getUpdates with a
    long timeout and dispatches each update to the appropriate pending request.

    Thread safety
    -------------
    _pending_approvals and _pending_asks are protected by _pending_lock.
    _offset is only written by the polling thread.
    The tool handler adds entries (under lock) then blocks on event.wait().
    The polling thread reads entries (under lock), sets result fields, and
    calls event.set() (outside the lock, since event.set() is thread-safe).
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._token = config.telegram_bot_token
        self._chat_id = config.telegram_chat_id
        self._offset = 0
        self._started = False
        self._start_lock = threading.Lock()
        self._pending_lock = threading.Lock()

        # request_id -> HumanRequest
        self._pending_approvals: dict[str, HumanRequest] = {}
        self._pending_asks: dict[str, HumanRequest] = {}

    # ------------------------------------------------------------------
    # Channel interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the Telegram polling daemon thread. Idempotent."""
        with self._start_lock:
            if self._started:
                return
            t = threading.Thread(
                target=self._polling_loop,
                name="telegram-polling",
                daemon=True,
            )
            t.start()
            self._started = True
            logger.info("Telegram polling thread started.")

    def ask(self, req: HumanRequest) -> str:
        """Send a question to Telegram and wait for a text reply."""
        self.start()

        text = f"*Question from AI agent*\n\n{req.question}"
        if req.context:
            text += f"\n\n_Context: {req.context}_"
        text += f"\n\n_Reply to this message with your answer\\._\n`{req.request_id}`"

        result = self._api("sendMessage", {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
        })
        req.metadata["message_id"] = result["message_id"]

        with self._pending_lock:
            self._pending_asks[req.request_id] = req

        answered = req.event.wait(timeout=self._config.timeout)

        with self._pending_lock:
            self._pending_asks.pop(req.request_id, None)

        if not answered:
            raise TimeoutError(
                f"No reply from human within {self._config.timeout}s "
                f"(request {req.request_id})"
            )

        return req.response

    def request_approval(self, req: HumanRequest) -> tuple[bool, str]:
        """Send an approval request with inline keyboard and wait for click."""
        self.start()

        text = f"*Approval required*\n\n*Action:* {req.action}"
        if req.details:
            text += f"\n\n*Details:*\n```\n{req.details}\n```"

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "Approve",
                        "callback_data": f"approve:{req.request_id}",
                    },
                    {
                        "text": "Deny",
                        "callback_data": f"deny:{req.request_id}",
                    },
                ]
            ]
        }

        self._api("sendMessage", {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": keyboard,
        })

        with self._pending_lock:
            self._pending_approvals[req.request_id] = req

        answered = req.event.wait(timeout=self._config.timeout)

        with self._pending_lock:
            self._pending_approvals.pop(req.request_id, None)

        if not answered:
            raise TimeoutError(
                f"No approval within {self._config.timeout}s "
                f"(request {req.request_id})"
            )

        return req.approved, req.reason

    # ------------------------------------------------------------------
    # Polling loop (daemon thread)
    # ------------------------------------------------------------------

    def _polling_loop(self) -> None:
        logger.info("Telegram polling loop running.")
        while True:
            try:
                result = self._api("getUpdates", {
                    "offset": self._offset,
                    "timeout": 15,
                    "allowed_updates": ["message", "callback_query"],
                })
                for update in result:
                    self._offset = update["update_id"] + 1
                    self._dispatch(update)
            except Exception as exc:
                logger.warning("Telegram polling error: %s", exc)
                time.sleep(2)

    def _dispatch(self, update: dict) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
        elif "message" in update:
            self._handle_message(update["message"])

    def _handle_callback(self, cb: dict) -> None:
        data: str = cb.get("data", "")
        if ":" not in data:
            return
        action, request_id = data.split(":", 1)
        if action not in ("approve", "deny"):
            return

        with self._pending_lock:
            req = self._pending_approvals.get(request_id)

        if req is None:
            return

        req.approved = action == "approve"
        req.reason = cb.get("from", {}).get("username", "") or cb.get("from", {}).get("first_name", "")
        req.event.set()

        # Acknowledge the button press (required by Telegram)
        try:
            decision = "Approved!" if req.approved else "Denied."
            self._api("answerCallbackQuery", {
                "callback_query_id": cb["id"],
                "text": decision,
            })
            # Remove the inline keyboard from the message
            self._api("editMessageReplyMarkup", {
                "chat_id": cb["message"]["chat"]["id"],
                "message_id": cb["message"]["message_id"],
                "reply_markup": {"inline_keyboard": []},
            })
        except Exception as exc:
            logger.warning("Failed to acknowledge Telegram callback: %s", exc)

    def _handle_message(self, msg: dict) -> None:
        """Route plain-text messages to waiting ask() calls.

        Uses FIFO routing: the oldest pending ask gets the next message.
        Works correctly for stdio transport (one tool call at a time).
        """
        text = msg.get("text", "").strip()
        if not text:
            return
        # Ignore bot messages
        if msg.get("from", {}).get("is_bot"):
            return
        # Ignore messages not from the configured chat
        if str(msg.get("chat", {}).get("id", "")) != str(self._chat_id):
            return

        with self._pending_lock:
            if not self._pending_asks:
                return
            # FIFO: oldest pending ask
            req = next(iter(self._pending_asks.values()))

        req.response = text
        req.event.set()

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _api(self, method: str, params: dict | None = None) -> dict:
        url = _API_BASE.format(token=self._token, method=method)
        resp = requests.post(url, json=params or {}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data.get("result", {})
