# call-a-human-mcp

Your AI agent is about to delete the production database. Do you want it to just go ahead?

**call-a-human-mcp** is an MCP server that gives any AI agent a pause button — it can ask you a question or request your approval before taking action, and it won't proceed until you respond.

```
Claude:  request_approval("Drop table users_backup — 2.1GB, irreversible")

Slack:   ⚠️  AI Agent requesting approval
         Action: Drop table users_backup — 2.1GB, irreversible
         [Approve]  [Deny]
                              ← you click Deny
Claude:  "Understood, skipping the deletion."
```

Works with Claude Desktop, Cursor, Windsurf, and any MCP-compatible agent. Notifications via Slack, Telegram, or macOS system dialogs.

Two tools:

| Tool | When to use | Returns |
|------|-------------|---------|
| `ask_human(question, context?)` | Need information only a human can provide | `str` — human's text reply |
| `request_approval(action, details?)` | Before any irreversible action | `{"approved": bool, "reason": str}` |

The tool call **blocks** until you respond (or the timeout expires).

**More:** [Use cases](docs/use-cases.md) · [Slack permissions](docs/slack-permissions.md) · [Troubleshooting](docs/troubleshooting.md) · [Discord](https://discord.gg/kuRmPQzs28)

---

## 5-minute quick start

Pick the path that matches your setup:

| Channel | Best for | Tested |
|---------|----------|--------|
| [CLI (macOS dialogs)](#option-a-cli-macos-dialogs) | macOS, no accounts needed | ✅ Tested |
| [Slack](#option-c-slack) | Teams, Approve/Deny buttons | ✅ Tested |
| [Telegram](#option-b-telegram) | Personal use, phone notifications | ⚠️ Lightly tested |

---

## Option A: CLI (macOS dialogs)

No Slack or Telegram account needed. Works with Claude Desktop on macOS via native system dialogs.

**1. Clone and install:**

```bash
git clone https://github.com/nishantmodak/call-a-human-mcp
cd call-a-human-mcp
uv sync
```

**2. Verify it works:**

```bash
CALL_HUMAN_CHANNEL=cli uv run call-a-human-mcp --check
```

Expected output:
```
Checking cli channel...
CLI channel: OK (no credentials needed)
```

**3. Add to Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "call-a-human": {
      "command": "/Users/yourname/.local/bin/uv",
      "args": ["--directory", "/path/to/call-a-human-mcp", "run", "call-a-human-mcp"],
      "env": {
        "CALL_HUMAN_CHANNEL": "cli"
      }
    }
  }
}
```

> **Use the full path to `uv`**, not just `uv`. Claude Desktop launches with a restricted PATH that won't find `uv` in `~/.local/bin`. Run `which uv` to get your full path.

**4. Restart Claude Desktop** (quit fully — Cmd+Q — then reopen).

**What you'll see:**

When Claude calls `ask_human`, a native macOS dialog appears:

```
┌─────────────────────────────────────────────────────┐
│  Claude is asking:                                  │
│  Which database environment should I target?        │
│                                                     │
│  [  Reply here...                                 ] │
│                              [Cancel]  [OK]         │
└─────────────────────────────────────────────────────┘
```

When Claude calls `request_approval`, a dialog with Approve/Deny options appears. Claude blocks until you respond.

> **On Linux/Windows or CI?** No interactive fallback exists without a terminal. Use Telegram or Slack instead.

---

## Option B: Telegram

> ⚠️ **Not extensively tested.** The implementation follows the Telegram Bot API spec and basic flows work, but edge cases may exist. Feedback welcome.

Best for personal use — instant phone notifications, buttons work in the Telegram app.

**1. Create a bot:**

- Message [@BotFather](https://t.me/BotFather) → `/newbot` → follow prompts → copy the token

**2. Find your chat ID:**

Send any message to your new bot, then run:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool | grep '"id"' | head -1
```

The number is your chat ID (negative for groups, e.g. `-100123456789`).

**3. Verify credentials:**

```bash
CALL_HUMAN_CHANNEL=telegram \
TELEGRAM_BOT_TOKEN=<token> \
TELEGRAM_CHAT_ID=<chat_id> \
uv run call-a-human-mcp --check
```

Expected output:
```
Checking telegram channel...
  Bot token: OK (bot: @your_bot_username)
  Test message: OK (chat_id: -100123456789)

Telegram check passed. call-a-human-mcp is ready to use.
```

A test message also appears in your Telegram chat. If it doesn't, recheck the token and chat ID.

**4. Add to Claude Desktop:**

```json
{
  "mcpServers": {
    "call-a-human": {
      "command": "/Users/yourname/.local/bin/uv",
      "args": ["--directory", "/path/to/call-a-human-mcp", "run", "call-a-human-mcp"],
      "env": {
        "CALL_HUMAN_CHANNEL": "telegram",
        "TELEGRAM_BOT_TOKEN": "123456:ABC-your-token",
        "TELEGRAM_CHAT_ID": "-100123456789"
      }
    }
  }
}
```

**5. Restart Claude Desktop** (Cmd+Q → reopen).

**What you'll see:**

When Claude calls `ask_human`, a message appears in your Telegram chat:

```
🤔 Claude is asking:
Which database environment should I target?

Context: Running migration job started at 14:32.

Reply to this message with your answer.
```

Reply directly to the message. Claude receives your reply and continues.

When Claude calls `request_approval`, you get Approve/Deny buttons:

```
⚠️ Approval requested:
Deploy api-service v2.4.1 to production

Details: Replaces v2.3.8. 12 pods will restart.

[ ✅ Approve ]  [ ❌ Deny ]
```

Tap a button — Claude immediately receives the result.

---

## Option C: Slack

Best for teams — Approve/Deny buttons, messages stay in your team's channel.

> **Full permissions reference:** [docs/slack-permissions.md](docs/slack-permissions.md)

**1. Create a Slack app:**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it (e.g. `call-a-human`) and pick your workspace → **Create App**

**Enable Socket Mode:**

3. Sidebar → **Socket Mode** → toggle on
4. Generate an App-Level Token with scope `connections:write` → copy as `SLACK_APP_TOKEN` (`xapp-…`)

**Add bot scopes:**

5. Sidebar → **OAuth & Permissions** → **Bot Token Scopes** → Add:
   `chat:write`, `channels:history` (add `groups:history` for private channels)

**Enable Events:**

6. Sidebar → **Event Subscriptions** → toggle on → **Subscribe to bot events** → Add `message.channels` (and/or `message.groups`)

**Enable Interactivity:**

7. Sidebar → **Interactivity & Shortcuts** → toggle on → Save

**Install and get tokens:**

8. Sidebar → **Install App** → **Install to Workspace** → Allow
9. Copy the **Bot User OAuth Token** as `SLACK_BOT_TOKEN` (`xoxb-…`)

**Find your channel ID:**

10. Right-click the channel in Slack → **Copy link** → the last segment is the ID (e.g. `C1234567890`)
11. Invite the bot: type `/invite @call-a-human` in the channel

**2. Verify credentials:**

```bash
CALL_HUMAN_CHANNEL=slack \
SLACK_BOT_TOKEN=xoxb-... \
SLACK_APP_TOKEN=xapp-... \
SLACK_CHANNEL_ID=C... \
uv run call-a-human-mcp --check
```

Expected output:
```
Checking slack channel...
  Bot token: OK (bot: @call-a-human, workspace: YourWorkspace)
  App token: OK (format looks correct)
  Test message: OK (channel: C1234567890, ts: 1234567890.123456)
  Socket Mode: OK (WebSocket connection established)

Slack check passed. call-a-human-mcp is ready to use.
```

All four checks must pass. If Socket Mode fails, ensure it is enabled in your Slack app and the app token is correct.

**3. Add to Claude Desktop:**

```json
{
  "mcpServers": {
    "call-a-human": {
      "command": "/Users/yourname/.local/bin/uv",
      "args": ["--directory", "/path/to/call-a-human-mcp", "run", "call-a-human-mcp"],
      "env": {
        "CALL_HUMAN_CHANNEL": "slack",
        "SLACK_BOT_TOKEN": "xoxb-your-bot-token",
        "SLACK_APP_TOKEN": "xapp-your-app-token",
        "SLACK_CHANNEL_ID": "C1234567890"
      }
    }
  }
}
```

**4. Restart Claude Desktop** (Cmd+Q → reopen).

**What you'll see:**

When Claude calls `ask_human`, a message appears in your Slack channel:

```
🤔 Claude is asking:
Which database environment should I target?

Context: Running migration job started at 14:32.
Reply in this thread ↓
```

Reply in the thread — Claude receives your text reply and continues.

When Claude calls `request_approval`, you get interactive buttons:

```
⚠️ Approval requested
Action: Deploy api-service v2.4.1 to production
Details: Replaces v2.3.8. 12 pods will restart.

[✅ Approve]  [❌ Deny]
```

Click a button — Claude immediately receives the result and the message updates to show your decision.

---

## Other MCP clients

### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "call-a-human": {
      "command": "uv",
      "args": ["--directory", "/path/to/call-a-human-mcp", "run", "call-a-human-mcp"],
      "env": {
        "CALL_HUMAN_CHANNEL": "telegram",
        "TELEGRAM_BOT_TOKEN": "...",
        "TELEGRAM_CHAT_ID": "..."
      }
    }
  }
}
```

Or connect to a running SSE server:

```json
{
  "mcpServers": {
    "call-a-human": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "call-a-human": {
      "serverUrl": "http://localhost:8000/sse"
    }
  }
}
```

Start the SSE server first:

```bash
CALL_HUMAN_CHANNEL=slack ... call-a-human-mcp --transport sse --host 0.0.0.0 --port 8000
```

---

## Running as a persistent SSE server

> **Security note:** The SSE transport has no built-in authentication. Protect it with a reverse proxy (nginx, Caddy) or firewall rules — anyone who can reach the port can send messages to your Slack/Telegram channel.

For self-hosted deployments or clients that connect over HTTP:

```bash
export CALL_HUMAN_CHANNEL=slack
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export SLACK_CHANNEL_ID=C...

call-a-human-mcp --transport sse --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
cp .env.example .env   # fill in your credentials
docker compose up -d
```

Audit logs are written to `./logs/audit.jsonl` on the host.

---

## Getting Claude to call these tools automatically

The MCP server already tells Claude when to use the tools, but the most reliable way to make Claude call them *proactively* — without you explicitly asking — is to add a custom system prompt in your AI client.

The key principle (learned from production use): **tell Claude to call the tools directly — not to ask you whether to call them.** The approval happens in Slack/Telegram. Claude's job is just to trigger it.

### Claude Desktop

Go to **Settings → Custom Instructions** and add:

```
You have access to request_approval and ask_human tools via the call-a-human MCP server.

Call request_approval BEFORE any irreversible action: deleting files, sending
messages, making purchases, modifying production systems, running destructive
commands. Do NOT ask "should I proceed?" — just call the tool and wait.
Only continue if you receive {"approved": true}.

Call ask_human when you are unsure about preferences, file paths, credentials,
or any ambiguous decision. Never guess — ask.
```

This makes the behavior consistent across all conversations, without needing to remind Claude each time.

### Cursor / Windsurf

Add a `.cursorrules` file (Cursor) or equivalent to your project:

```
Before any irreversible action, call the request_approval MCP tool directly —
do not ask the user whether to call it. Wait for {"approved": true} before proceeding.
When unsure about preferences or credentials, call ask_human instead of guessing.
```

---

## Trying tools interactively (without an AI agent)

Use the MCP Inspector to call tools directly:

```bash
CALL_HUMAN_CHANNEL=cli uv run mcp dev src/call_a_human_mcp/server.py
```

The browser UI lets you call `ask_human` and `request_approval` manually and inspect the responses.

---

## All configuration options

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CALL_HUMAN_CHANNEL` | Yes | — | `cli`, `slack`, or `telegram` |
| `CALL_HUMAN_TIMEOUT` | No | `300` | Seconds to wait before auto-denying |
| `CALL_HUMAN_AUDIT_LOG` | No | — | Path to JSONL audit log file |
| `SLACK_BOT_TOKEN` | Slack only | — | Bot OAuth token (`xoxb-…`) |
| `SLACK_APP_TOKEN` | Slack only | — | Socket Mode app token (`xapp-…`) |
| `SLACK_CHANNEL_ID` | Slack only | — | Channel to post into (`C…`) |
| `TELEGRAM_BOT_TOKEN` | Telegram only | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Telegram only | — | Chat/group ID to post into |

Copy `.env.example` to `.env` and fill in your values.

---

## Audit log

Set `CALL_HUMAN_AUDIT_LOG` to enable append-only JSONL logging:

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
AI agent (Claude)              call-a-human-mcp           Human (Slack/Telegram/macOS)
─────────────────              ────────────────           ────────────────────────────
request_approval(             block on                   sees message with
  "delete database")   ──►    threading.Event    ──►     Approve / Deny buttons
                                                          │
                                                          │ clicks Approve
                                                          ▼
{"approved": true,    ◄──    event.set()         ◄──    button/dialog handler fires
 "reason": "alice"}
```

The MCP tool handler blocks on a `threading.Event`. A background daemon thread (Slack Socket Mode, Telegram long-poll, or macOS dialog subprocess) fires `event.set()` when the human responds.

---

## Development

```bash
git clone https://github.com/nishantmodak/call-a-human-mcp
cd call-a-human-mcp
uv sync --extra dev

uv run --extra dev pytest -v
uv run --extra dev ruff check src tests
```

---

## Extending with a new channel

1. Create `src/call_a_human_mcp/channels/sms.py` subclassing `Channel`
2. Implement `start()`, `ask()`, and `request_approval()`
3. Add `"sms"` to `config.py` validation with its required env vars
4. Add a factory branch in `server.py`'s `create_server()`
5. Add `--check` support in `__main__.py`'s `_run_check()`

No changes to the MCP tool definitions needed.

---

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for solutions to common issues:

- Claude Desktop "Failed to spawn process" → use full path to `uv`
- Slack thread replies not received → private channel needs extra permissions
- `message.groups` not showing in Slack event list → add `groups:read` scope first
- Claude doesn't call tools automatically → add a custom system prompt

---

## Community

Questions, ideas, or just want to share how you're using it? [Join the Discord](https://discord.gg/kuRmPQzs28).

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
