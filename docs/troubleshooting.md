# Troubleshooting

Common issues and fixes when setting up call-a-human-mcp.

---

## Claude Desktop: "Failed to spawn process: No such file or directory"

**Symptom:** The MCP server never loads. Claude Desktop logs show `Failed to spawn process`.

**Cause:** Claude Desktop launches with a restricted `PATH` that doesn't include `~/.local/bin` (where `uv` typically lives on macOS).

**Fix:** Use the full path to `uv` in your config:

```json
{
  "mcpServers": {
    "call-a-human": {
      "command": "/Users/yourname/.local/bin/uv",
      ...
    }
  }
}
```

Find your full path with:

```bash
which uv
```

---

## Slack: Thread reply not received — times out after 300s

**Symptom:** The question appears in Slack, you reply in the thread, but Claude never gets the answer and eventually times out.

**Most common cause: Private channel missing permissions**

Private Slack channels (🔒) require different scopes and event subscriptions than public ones.

Check your Slack app has ALL of:

| What | Where to add |
|------|-------------|
| `groups:history` scope | OAuth & Permissions → Bot Token Scopes |
| `groups:read` scope | OAuth & Permissions → Bot Token Scopes |
| `message.groups` event | Event Subscriptions → Subscribe to bot events |

After adding scopes, you **must reinstall the app** (Install App → Reinstall to Workspace).

> `message.groups` only appears in the event list after `groups:read` is added.

**Other causes:**

- Bot not invited to channel → run `/invite @your-bot-name` in the channel
- `message.channels` missing → needed for public channels
- Event Subscriptions not toggled on → check the toggle is enabled
- Socket Mode not enabled → check Basic Information → Socket Mode

Run `--check` to verify Socket Mode is connected:

```bash
CALL_HUMAN_CHANNEL=slack \
SLACK_BOT_TOKEN=xoxb-... \
SLACK_APP_TOKEN=xapp-... \
SLACK_CHANNEL_ID=C... \
call-a-human-mcp --check
```

All four checks should pass: Bot token, App token, Test message, Socket Mode.

---

## Slack: "channel_not_found" error

**Cause:** The bot isn't a member of the channel.

**Fix:** Invite the bot in Slack:

```
/invite @your-bot-name
```

---

## Slack: `message.groups` not showing in Event Subscriptions

Slack hides `message.groups` until you have `groups:read` OAuth scope.

1. Add `groups:read` under **OAuth & Permissions → Bot Token Scopes**
2. Reinstall the app
3. Go back to **Event Subscriptions** — `message.groups` will now appear

---

## Claude doesn't call the tools automatically

The MCP server sends instructions to Claude, but Claude may still not call the tools proactively. The most reliable fix is a **custom system prompt** in your AI client.

See [Getting Claude to call these tools automatically](../README.md#getting-claude-to-call-these-tools-automatically) in the README.

---

## CLI channel: No dialog appears on macOS

**Cause:** The `osascript` dialog is sandboxed and may be blocked by macOS security settings.

**Fix:** Go to **System Settings → Privacy & Security → Automation** and ensure the terminal or Claude Desktop app has permission to control Script Editor.

Alternatively, switch to Slack or Telegram for Claude Desktop use.

---

## Telegram: No response received

- Make sure you've sent at least one message to the bot before using it — Telegram requires an initial message to open a chat
- Verify your `TELEGRAM_CHAT_ID` is correct (negative number for groups, e.g. `-100123456789`)
- Run `--check` to confirm credentials and test message delivery:

```bash
CALL_HUMAN_CHANNEL=telegram \
TELEGRAM_BOT_TOKEN=... \
TELEGRAM_CHAT_ID=... \
call-a-human-mcp --check
```

---

## Timeout is too short / too long

Default is 300 seconds (5 minutes). Adjust with:

```bash
CALL_HUMAN_TIMEOUT=600  # 10 minutes
```

---

## Where are the logs?

**Claude Desktop MCP logs:**

```bash
tail -f ~/Library/Logs/Claude/mcp-server-call-a-human.log
```

**Server stderr with debug logging** (run from command line):

```bash
CALL_HUMAN_CHANNEL=slack ... call-a-human-mcp --log-level DEBUG
```

**Audit log** (if configured):

```bash
tail -f ./logs/audit.jsonl | python3 -m json.tool
```
