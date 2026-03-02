# call-a-human-mcp

An MCP server that lets AI agents pause and ask a human for input or approval — via Slack, Telegram, or your terminal.

Inspired by the human-in-the-loop feature in [mithai](https://github.com/nishantmodak/mithai).

---

## What it does

Any MCP-compatible AI agent (Claude Desktop, Cursor, Windsurf, etc.) can call two tools:

| Tool | When to use | Returns |
|------|-------------|---------|
| `ask_human(question, context?)` | Need information only a human can provide | `str` — human's text reply |
| `request_approval(action, details?)` | Before any irreversible action | `{"approved": bool, "reason": str}` |

The tool call **blocks** until the human responds (or the timeout expires).

### CLI (fastest to try)

No accounts needed. Prints to your terminal and reads your input.

```
============================================================
APPROVAL REQUIRED
============================================================
Action: delete the staging database
Details: db-staging-01 on RDS
============================================================
Approve? [y/N]:
```

> **How it works with stdio transport**: MCP's stdio transport owns `stdin`/`stdout` for its protocol messages. The CLI channel bypasses this by reading and writing directly to `/dev/tty` (the controlling terminal), so prompts appear in your terminal without interfering with the MCP wire protocol. Falls back to `stderr`/`stdin` when `/dev/tty` is unavailable (Windows, CI, Docker containers without an attached TTY — in those cases use Slack or Telegram instead).

### Slack

`ask_human` — Posts a message, waits for a **thread reply**:

![Slack ask_human](https://placeholder/slack-ask.png)

`request_approval` — Posts a message with **Approve / Deny** buttons:

![Slack request_approval](https://placeholder/slack-approval.png)

### Telegram

`ask_human` — Sends a message, waits for the next text reply.

`request_approval` — Sends a message with **Approve / Deny** inline keyboard buttons.

---

## Installation

### With uvx (zero-install, recommended)

```bash
uvx call-a-human-mcp
```

### With uv

```bash
uv tool install call-a-human-mcp
call-a-human-mcp
```

### From source

```bash
git clone https://github.com/nishantmodak/call-a-human-mcp
cd call-a-human-mcp
uv sync
uv run call-a-human-mcp
```

---

## Configuration

All configuration is via environment variables.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CALL_HUMAN_CHANNEL` | Yes | — | `cli`, `slack`, or `telegram` |
| `CALL_HUMAN_TIMEOUT` | No | `300` | Seconds to wait before auto-denying |
| `SLACK_BOT_TOKEN` | Slack only | — | Bot OAuth token (`xoxb-…`) |
| `SLACK_APP_TOKEN` | Slack only | — | App-level Socket Mode token (`xapp-…`) |
| `SLACK_CHANNEL_ID` | Slack only | — | Channel to post into (`C…`) |
| `TELEGRAM_BOT_TOKEN` | Telegram only | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Telegram only | — | Chat/group ID to post into |

### Slack app requirements

Your Slack app needs:
- **Bot scopes**: `chat:write`, `channels:history`, `groups:history`
- **Event subscriptions**: `message.channels` or `message.groups` (for `ask_human` thread replies)
- **Interactivity** enabled (for Approve/Deny buttons)
- **Socket Mode** enabled with an App-Level Token (`connections:write` scope)

---

## Quick start with the CLI channel

The fastest way to try it — no Slack or Telegram account needed:

```bash
CALL_HUMAN_CHANNEL=cli uv run call-a-human-mcp --transport sse --port 8000
```

Then add it to your MCP client pointed at `http://localhost:8000/sse`. Any `ask_human` or `request_approval` call will prompt you directly in the terminal.

## Trying tools interactively with `mcp dev`

Use the MCP Inspector to call tools without an AI agent:

```bash
# Install mcp CLI if you haven't
uv tool install mcp

# Run the dev inspector (opens a browser UI)
CALL_HUMAN_CHANNEL=cli mcp dev src/call_a_human_mcp/server.py
```

The Inspector lets you call `ask_human` and `request_approval` directly and see the JSON responses. The CLI channel handles the prompts in your terminal.

---

## Claude Desktop configuration

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

### CLI (terminal prompts)

```json
{
  "mcpServers": {
    "call-a-human": {
      "command": "uvx",
      "args": ["call-a-human-mcp"],
      "env": {
        "CALL_HUMAN_CHANNEL": "cli"
      }
    }
  }
}
```

Approvals appear in the terminal where Claude Desktop is running (or in Console.app on macOS).

### Slack

```json
{
  "mcpServers": {
    "call-a-human": {
      "command": "uvx",
      "args": ["call-a-human-mcp"],
      "env": {
        "CALL_HUMAN_CHANNEL": "slack",
        "SLACK_BOT_TOKEN": "xoxb-your-bot-token",
        "SLACK_APP_TOKEN": "xapp-your-app-token",
        "SLACK_CHANNEL_ID": "C1234567890",
        "CALL_HUMAN_TIMEOUT": "300"
      }
    }
  }
}
```

### Telegram

```json
{
  "mcpServers": {
    "call-a-human": {
      "command": "uvx",
      "args": ["call-a-human-mcp"],
      "env": {
        "CALL_HUMAN_CHANNEL": "telegram",
        "TELEGRAM_BOT_TOKEN": "123456:ABC-your-bot-token",
        "TELEGRAM_CHAT_ID": "-100123456789",
        "CALL_HUMAN_TIMEOUT": "300"
      }
    }
  }
}
```

---

## Running as a persistent SSE server

For MCP clients that connect over HTTP (Cursor, Windsurf, remote agents):

```bash
export CALL_HUMAN_CHANNEL=slack
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export SLACK_CHANNEL_ID=C...

call-a-human-mcp --transport sse --host 0.0.0.0 --port 8000
```

Connect your MCP client to `http://localhost:8000/sse`.

---

## How it works

```
AI agent (Claude)              call-a-human-mcp           Human (Slack/Telegram)
─────────────────              ────────────────           ──────────────────────
request_approval(             block on                   sees message with
  "delete database")   ──►    threading.Event    ──►     Approve / Deny buttons
                                                          │
                                                          │ clicks Approve
                                                          ▼
{"approved": true,    ◄──    event.set()         ◄──    button handler fires
 "reason": "alice"}
```

**Thread model**: The MCP tool handler blocks on a `threading.Event`. A background daemon thread (Slack Socket Mode handler or Telegram long-poll loop) receives the human's response, writes it to the shared `HumanRequest` object, then calls `event.set()` to unblock the tool handler.

---

## Development

```bash
git clone https://github.com/nishantmodak/call-a-human-mcp
cd call-a-human-mcp
uv sync --extra dev

# Run tests
uv run --extra dev pytest -v

# Lint
uv run --extra dev ruff check src tests
```

---

## Extending with a new channel

Adding SMS, email, or voice calls later requires only:

1. Create `src/call_a_human_mcp/channels/sms.py` subclassing `Channel`
2. Implement `start()`, `ask()`, and `request_approval()`
3. Add `"sms"` to `config.py` validation with its required env vars
4. Add a factory branch in `server.py`'s `create_server()`

No changes to the MCP tool definitions needed.

---

## License

MIT
