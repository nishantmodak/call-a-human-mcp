"""Entry point: python -m call_a_human_mcp  or  uvx call-a-human-mcp"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="call-a-human-mcp",
        description="MCP server for human-in-the-loop approvals via Slack or Telegram.",
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

    from call_a_human_mcp.server import _channel, create_server

    mcp = create_server(config)

    if args.transport == "sse":
        # For SSE (persistent server), start the channel eagerly so the first
        # tool call is not delayed by connection setup.
        from call_a_human_mcp.server import _channel as ch
        if ch is not None:
            ch.start()
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        # stdio: channel starts lazily on first tool call
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
