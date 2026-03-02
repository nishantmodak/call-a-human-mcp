# Slack Permissions Reference

Complete list of OAuth scopes and event subscriptions required to run call-a-human-mcp with Slack.

---

## OAuth Scopes (Bot Token)

Add these under **OAuth & Permissions → Bot Token Scopes**:

| Scope | Required for |
|-------|-------------|
| `chat:write` | Posting questions and approval requests to the channel |
| `chat:write.customize` | Customising the bot display name on messages |
| `channels:history` | Reading message history in **public** channels |
| `groups:history` | Reading message history in **private** channels |
| `groups:read` | Listing private channel members; also unlocks `message.groups` in the Event Subscriptions UI |
| `reactions:read` | (Optional) Reading emoji reactions |

> If you only use a **public** channel, you can skip `groups:history` and `groups:read`.
> If you only use a **private** channel, `channels:history` is not strictly required but harmless to include.

---

## Event Subscriptions (Bot Events)

Enable **Event Subscriptions** then add these under **Subscribe to bot events**:

| Event | Required for |
|-------|-------------|
| `message.channels` | Receiving thread replies in **public** channels (for `ask_human`) |
| `message.groups` | Receiving thread replies in **private** channels (for `ask_human`) |

> `message.groups` only appears in the Slack UI after `groups:read` is added to Bot Token Scopes.

Button clicks (Approve / Deny for `request_approval`) arrive via Socket Mode interactivity — no additional event subscription needed.

---

## App-Level Token

Generate one under **Basic Information → App-Level Tokens** with the scope:

| Scope | Required for |
|-------|-------------|
| `connections:write` | Socket Mode WebSocket connection |

The token starts with `xapp-`.

---

## Interactivity

Enable under **Interactivity & Shortcuts** (toggle on, save). Required for Approve/Deny button clicks.

---

## Socket Mode

Enable under **Socket Mode** (toggle on). Required for receiving events and button clicks without a public HTTP endpoint.

---

## Summary checklist

- [ ] Socket Mode: **on**
- [ ] Interactivity: **on**
- [ ] Event Subscriptions: **on**
- [ ] Bot events: `message.channels` and/or `message.groups` (depending on channel type)
- [ ] Bot Token Scopes: `chat:write`, `chat:write.customize`, `channels:history`, `groups:history`, `groups:read`
- [ ] App-Level Token with `connections:write`
- [ ] Bot reinstalled after any scope change
- [ ] Bot invited to the target channel (`/invite @your-bot-name`)

---

## How to tell if your channel is public or private

- **Public** channels: name appears without a lock icon in Slack. Use `message.channels` event.
- **Private** channels: name appears with a 🔒 lock icon. Use `message.groups` event + `groups:history` + `groups:read` scopes.

When in doubt, add all scopes and both events — there is no downside to having both.
