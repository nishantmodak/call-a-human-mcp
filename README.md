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

No accounts needed. The channel picks the best available interaction method automatically:

| Environment | How you see the prompt |
|-------------|----------------------|
| Terminal (mcp dev, SSE mode) | Prints to `/dev/tty`, reads your input |
| Claude Desktop on macOS | Native system dialog (via `osascript`) |
| CI / Docker / Windows | `TimeoutError` with a clear message — use Slack or Telegram instead |

**Terminal prompt:**
```
============================================================
APPROVAL REQUIRED
============================================================
Action: delete the staging database
Details: db-staging-01 on RDS
============================================================
Approve? [y/N]:
```

**macOS dialog (Claude Desktop):**

A native macOS dialog pops up even when the process has no terminal — your answer goes directly back to the AI agent.

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

### CLI (macOS native dialogs)

On macOS, the CLI channel automatically falls back to native system dialogs when no terminal is attached — which is exactly what happens when Claude Desktop launches the server as a subprocess.

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

A macOS dialog pops up when Claude calls `ask_human` or `request_approval`. No Slack or Telegram account needed.

> **Not on macOS?** Use Slack or Telegram instead — the CLI channel has no interactive fallback on Windows or Linux without a terminal.

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

## Docker

```bash
cp .env.example .env   # fill in your credentials
docker compose up -d
```

The SSE server starts on `http://localhost:8000/sse`. Audit logs are written to `./logs/audit.jsonl` on the host.

To build and run manually:

```bash
docker build -t call-a-human-mcp .
docker run -p 8000:8000 --env-file .env call-a-human-mcp
```

## Audit log

Set `CALL_HUMAN_AUDIT_LOG` to a file path to enable append-only JSONL logging of every request and response:

```bash
CALL_HUMAN_AUDIT_LOG=./logs/audit.jsonl call-a-human-mcp
```

Each line is a JSON object:

```jsonc
// ask_human
{"timestamp":"2024-03-01T12:00:00.123Z","request_id":"abc123","tool":"ask_human","question":"Which env?","context":"","timed_out":false,"duration_ms":4210}

// request_approval
{"timestamp":"2024-03-01T12:05:00.456Z","request_id":"def456","tool":"request_approval","action":"delete db","details":"","approved":true,"reason":"alice","timed_out":false,"duration_ms":8700}
```

Tail and pretty-print live:

```bash
tail -f logs/audit.jsonl | python3 -m json.tool
```

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
