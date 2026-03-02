"""Entry point: python -m call_a_human_mcp  or  uvx call-a-human-mcp"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="call-a-human-mcp",
        description="MCP server for human-in-the-loop approvals via Slack, Telegram, or CLI.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport to use (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: WARNING)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify credentials by sending a test message, then exit.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    # Validate config before starting the server — fail fast with a clear message
    from call_a_human_mcp.config import Config, ConfigError

    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.check:
        _run_check(config)
        return

    from call_a_human_mcp.server import create_server

    mcp = create_server(config, host=args.host, port=args.port)

    if args.transport == "sse":
        # For SSE (persistent server), start the channel eagerly so the first
        # tool call is not delayed by connection setup.
        from call_a_human_mcp.server import _channel as ch
        if ch is not None:
            ch.start()
        mcp.run(transport="sse")
    else:
        # stdio: channel starts lazily on first tool call
        mcp.run(transport="stdio")


def _run_check(config) -> None:
    """Send a test message to verify credentials, then exit."""
    from call_a_human_mcp.request import HumanRequest

    print(f"Checking {config.channel} channel...", flush=True)

    if config.channel == "cli":
        print("CLI channel: OK (no credentials needed)")
        sys.exit(0)

    if config.channel == "slack":
        _check_slack(config)
    elif config.channel == "telegram":
        _check_telegram(config)


def _check_slack(config) -> None:
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ImportError:
        print("ERROR: slack-sdk not installed", file=sys.stderr)
        sys.exit(1)

    client = WebClient(token=config.slack_bot_token)

    # 1. Verify bot token
    try:
        identity = client.auth_test()
        print(f"  Bot token: OK (bot: @{identity['user']}, workspace: {identity['team']})")
    except Exception as exc:
        print(f"  Bot token: FAILED — {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Post a test message
    try:
        result = client.chat_postMessage(
            channel=config.slack_channel_id,
            text=":white_check_mark: *call-a-human-mcp* is connected and ready.",
        )
        print(f"  Test message: OK (channel: {config.slack_channel_id}, ts: {result['ts']})")
    except Exception as exc:
        print(f"  Test message: FAILED — {exc}", file=sys.stderr)
        print("  Check that SLACK_CHANNEL_ID is correct and the bot is invited to the channel.", file=sys.stderr)
        sys.exit(1)

    # 3. Verify Socket Mode app token (just check format — connecting is too slow for --check)
    if not config.slack_app_token.startswith("xapp-"):
        print("  App token: WARNING — SLACK_APP_TOKEN should start with 'xapp-'", file=sys.stderr)
    else:
        print(f"  App token: OK (format looks correct)")

    print("\nSlack check passed. call-a-human-mcp is ready to use.")


def _check_telegram(config) -> None:
    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed", file=sys.stderr)
        sys.exit(1)

    base = f"https://api.telegram.org/bot{config.telegram_bot_token}"

    # 1. Verify bot token
    try:
        resp = requests.get(f"{base}/getMe", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data)
        bot = data["result"]
        print(f"  Bot token: OK (bot: @{bot['username']})")
    except Exception as exc:
        print(f"  Bot token: FAILED — {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Send a test message
    try:
        resp = requests.post(
            f"{base}/sendMessage",
            json={
                "chat_id": config.telegram_chat_id,
                "text": "✅ *call-a-human-mcp* is connected and ready.",
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data)
        print(f"  Test message: OK (chat_id: {config.telegram_chat_id})")
    except Exception as exc:
        print(f"  Test message: FAILED — {exc}", file=sys.stderr)
        print("  Check that TELEGRAM_CHAT_ID is correct and you've sent the bot at least one message.", file=sys.stderr)
        sys.exit(1)

    print("\nTelegram check passed. call-a-human-mcp is ready to use.")


if __name__ == "__main__":
    main()
