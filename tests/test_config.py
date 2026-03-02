"""Tests for Config.from_env()."""

import pytest

from call_a_human_mcp.config import Config, ConfigError


def test_missing_channel(monkeypatch):
    monkeypatch.delenv("CALL_HUMAN_CHANNEL", raising=False)
    with pytest.raises(ConfigError, match="CALL_HUMAN_CHANNEL"):
        Config.from_env()


def test_invalid_channel(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "pigeon")
    with pytest.raises(ConfigError, match="CALL_HUMAN_CHANNEL"):
        Config.from_env()


def test_cli_channel(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "cli")
    monkeypatch.setenv("CALL_HUMAN_TIMEOUT", "60")
    config = Config.from_env()
    assert config.channel == "cli"
    assert config.timeout == 60


def test_cli_channel_default_timeout(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "cli")
    monkeypatch.delenv("CALL_HUMAN_TIMEOUT", raising=False)
    config = Config.from_env()
    assert config.timeout == 300


def test_invalid_timeout(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "cli")
    monkeypatch.setenv("CALL_HUMAN_TIMEOUT", "not-a-number")
    with pytest.raises(ConfigError, match="CALL_HUMAN_TIMEOUT"):
        Config.from_env()


def test_slack_missing_bot_token(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "slack")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_CHANNEL_ID", raising=False)
    with pytest.raises(ConfigError, match="SLACK_BOT_TOKEN"):
        Config.from_env()


def test_slack_missing_app_token(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "slack")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_CHANNEL_ID", raising=False)
    with pytest.raises(ConfigError, match="SLACK_APP_TOKEN"):
        Config.from_env()


def test_slack_all_vars(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "slack")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-fake")
    monkeypatch.setenv("SLACK_CHANNEL_ID", "C123")
    config = Config.from_env()
    assert config.channel == "slack"
    assert config.slack_bot_token == "xoxb-fake"
    assert config.slack_channel_id == "C123"


def test_telegram_missing_bot_token(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "telegram")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        Config.from_env()


def test_telegram_all_vars(monkeypatch):
    monkeypatch.setenv("CALL_HUMAN_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123")
    config = Config.from_env()
    assert config.channel == "telegram"
    assert config.telegram_bot_token == "123:fake"
    assert config.telegram_chat_id == "-100123"
