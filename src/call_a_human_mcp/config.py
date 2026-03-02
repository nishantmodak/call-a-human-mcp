"""Read configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when required environment variables are missing or invalid."""


@dataclass(frozen=True)
class Config:
    channel: str        # "slack" | "telegram"
    timeout: int        # seconds to wait for a human response

    # Slack
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channel_id: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        channel = os.environ.get("CALL_HUMAN_CHANNEL", "").lower().strip()
        if channel not in ("slack", "telegram"):
            raise ConfigError(
                "CALL_HUMAN_CHANNEL must be 'slack' or 'telegram'. "
                f"Got: {channel!r}"
            )

        try:
            timeout = int(os.environ.get("CALL_HUMAN_TIMEOUT", "300"))
        except ValueError:
            raise ConfigError("CALL_HUMAN_TIMEOUT must be an integer number of seconds.")

        if channel == "slack":
            for var in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_ID"):
                if not os.environ.get(var):
                    raise ConfigError(f"{var} is required when CALL_HUMAN_CHANNEL=slack")
            return cls(
                channel=channel,
                timeout=timeout,
                slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
                slack_app_token=os.environ["SLACK_APP_TOKEN"],
                slack_channel_id=os.environ["SLACK_CHANNEL_ID"],
            )

        # telegram
        for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            if not os.environ.get(var):
                raise ConfigError(f"{var} is required when CALL_HUMAN_CHANNEL=telegram")
        return cls(
            channel=channel,
            timeout=timeout,
            telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
            telegram_chat_id=os.environ["TELEGRAM_CHAT_ID"],
        )
