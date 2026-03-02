# Use Cases

Real-world scenarios where call-a-human-mcp adds a safety layer or unlocks capabilities that would otherwise require constant human supervision.

---

## 1. Preventing accidental data loss

**Without it:** An AI agent tasked with "clean up old files" silently deletes 3 years of logs.

**With it:**

```
AI: request_approval("Delete 847 log files older than 90 days", "Path: /var/log/app/, Total size: 4.2GB")

Slack: ⚠️ AI Agent requesting approval
       Action: Delete 847 log files older than 90 days
       Details: Path: /var/log/app/, Total size: 4.2GB
       [Approve] [Deny]
```

The agent blocks until you click. One Deny and the files stay.

---

## 2. Safe deployments to production

**Without it:** An AI DevOps assistant deploys to production when it can't tell if you're on a feature branch or main.

**With it:**

```
AI: request_approval("Deploy api-service v2.4.1 to production", "Replaces v2.3.8. 12 pods will restart. ETA: 3 min downtime.")
```

You get a Telegram notification. Approve from your phone while on the train.

---

## 3. Filling in credentials the AI doesn't have

**Without it:** Claude guesses at an API key or env var name and fails silently.

**With it:**

```
AI: ask_human("What is the DATABASE_URL for the staging environment?",
              "I need to run the migration script against staging.")
```

You reply with the value in the Slack thread. It never touches your environment files, never gets stored in the conversation history beyond the session.

---

## 4. Personalising AI behaviour on first use

**Without it:** Every AI coding assistant defaults to its own style — tabs vs spaces, testing framework, file structure.

**With it (on first run of a new project):**

```
AI: ask_human("What test framework should I use for this project?",
              "I see Python files but no existing tests.")
```

You reply `pytest`. It uses pytest for the entire conversation. No config files needed.

---

## 5. Sending messages on your behalf

**Without it:** An AI email assistant sends a client email with the wrong tone.

**With it:**

```
AI: request_approval(
    "Send email to client@example.com",
    "Subject: Project update\n\nHi Sarah,\n\nJust wanted to let you know..."
)
```

You read the draft in Slack, click Approve only if it looks right.

---

## 6. Knowing when to escalate vs proceed

**Without it:** An AI support bot either handles everything (some things it shouldn't) or escalates everything (defeats the purpose).

**With it:** The agent uses `request_approval` for edge cases — refund requests over a threshold, account deletions, billing changes — while handling routine queries autonomously. You define what "high stakes" means via your system prompt.

---

## 7. Breaking ambiguity without going back to the user mid-task

A long-running agent task hits an ambiguous choice mid-execution:

```
AI: ask_human(
    "The staging database has 2 schemas that match: 'users_v2' and 'users_legacy'. Which should I migrate?",
    "Running migration job started at 14:32. Both schemas are non-empty."
)
```

The task pauses, you answer in Slack, it continues. No need to restart the whole job.

---

## 8. Audit trail for regulated environments

Every `ask_human` and `request_approval` call is logged to JSONL with timestamp, question/action, response, and duration:

```bash
CALL_HUMAN_AUDIT_LOG=./logs/audit.jsonl call-a-human-mcp
```

Useful for compliance teams who need to show that a human approved every production change.
