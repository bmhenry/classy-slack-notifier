# classy-slack-notifier: Design Document

## Overview

A lightweight Linux daemon that monitors Slack messages via Socket Mode, classifies their urgency using a local LLM (Ollama), and delivers desktop notifications for messages that meet a configurable urgency threshold. The goal is to reduce notification fatigue while ensuring critical messages are never missed.

## High-Level Architecture

```
Slack (Socket Mode via slack-bolt)
        |
        v
  Python Daemon Service
        |
        v
  Pre-Filter (rules-based)
        |
        +--> SKIP: drop silently
        +--> FORCE-NOTIFY: notify immediately, bypass LLM
        +--> CLASSIFY:
                |
                v
          Ollama /api/chat (localhost:11434)
                |
                v
          Urgency Score + Reason (structured JSON)
                |
                v
          Threshold Check
                |
                v
          libnotify (notify-send) desktop notification
```

## Project Structure

```
classy-slack-notifier/
├── ai_docs/
│   └── design.md                 # this document
├── config.example.yaml           # example configuration with comments
├── pyproject.toml                # project metadata, dependencies, entry point
├── src/
│   └── classy_slack_notifier/
│       ├── __init__.py
│       ├── main.py               # entry point, daemon loop, signal handling
│       ├── slack_listener.py     # Socket Mode connection + event dispatch
│       ├── llm_classifier.py     # Ollama /api/chat calls, prompt construction
│       ├── notifier.py           # notify-send / D-Bus desktop notifications
│       ├── filters.py            # pre-LLM rules (skip / force / classify)
│       ├── models.py             # SlackMessage, Classification, FilterResult
│       └── config.py             # config loading + validation
├── tests/
│   ├── test_filters.py
│   ├── test_classifier.py
│   └── test_notifier.py
└── systemd/
    └── classy-slack-notifier.service
```

## Component Design

### 1. Data Models (`models.py`)

Shared data structures used across all components. Using dataclasses to keep dependencies minimal.

```python
from dataclasses import dataclass
from enum import Enum

class FilterAction(Enum):
    SKIP = "skip"
    CLASSIFY = "classify"
    FORCE_NOTIFY = "force_notify"

@dataclass
class SlackMessage:
    channel: str          # channel name or ID
    channel_id: str       # raw channel ID
    sender: str           # display name or user ID
    sender_id: str        # raw user ID
    text: str             # message body
    thread_ts: str | None = None
    is_dm: bool = False
    is_mention: bool = False  # true if the bot user or configured user is @mentioned

@dataclass
class Classification:
    urgency: int          # 1-5 scale
    reason: str           # brief explanation from the LLM

@dataclass
class FilterResult:
    action: FilterAction
    rule: str             # which rule triggered, for logging
                          # e.g. "self", "bots", "keyword:production down",
                          # "mentions", "dms", "channel:#random", "default"
```

### 2. Configuration (`config.py`)

Loads and validates a YAML config file. See the "Configuration" section below for the full schema. Responsible for:

- Loading `config.yaml` from a configurable path (default: `~/.config/classy-slack-notifier/config.yaml`)
- Validating required fields and value ranges
- Providing sensible defaults for optional fields

### 3. Pre-Filter (`filters.py`)

A fast, rules-based layer that runs before any LLM call. Takes a `SlackMessage` and the loaded config, returns a `FilterResult` (action + which rule matched).

**Three possible outcomes:**

| Outcome | Action |
|---|---|
| `SKIP` | Drop silently, no LLM call, no notification |
| `FORCE_NOTIFY` | Notify immediately, bypass LLM entirely |
| `CLASSIFY` | Forward to Ollama for urgency scoring |

**Every message category is configurable.** The user chooses which action (`skip`, `classify`, or `force_notify`) applies to each category. There are two kinds of rules:

**Category rules** — apply to a class of messages based on source or context:

| Category | What it matches | Default action |
|---|---|---|
| `self` | Messages sent by the authenticated user | `skip` |
| `bots` | Messages sent by bot users | `skip` |
| `mentions` | Messages containing a direct @mention of the configured user | `force_notify` |
| `dms` | Direct messages (1:1 and group DMs) | `force_notify` |

**Targeted rules** — apply to specific channels or content patterns:

| Rule type | What it matches | Default action |
|---|---|---|
| `channels` | Messages in a specific named channel | (per-channel, user-defined) |
| `keywords` | Messages matching a substring or regex pattern | (per-keyword, user-defined) |

**Evaluation order (first match wins):**

```
1. self         →  rules.self action        (default: skip)
2. bots         →  rules.bots action        (default: skip)
3. keywords     →  first matching keyword's action
4. mentions     →  rules.mentions action     (default: force_notify)
5. dms          →  rules.dms action          (default: force_notify)
6. channels     →  per-channel action from channels map
7. (no match)   →  rules.default action      (default: classify)
```

The order is designed around the principle that **more specific signals win over ambient context**:

- **Self and bots** (steps 1-2) are checked first because these are source-level filters. There's no point evaluating content rules for messages from sources you've explicitly filtered.
- **Keywords and mentions** (steps 3-4) are content-specific signals that override channel-level rules. If someone says "production down" in a channel you'd normally skip, the keyword should still win — that's an intentional, specific trigger.
- **DMs** (step 5) come next. A DM is a direct communication to the user, making it more targeted than a channel message, so it takes priority over channel rules.
- **Channels** (step 6) are the broadest container-level rule.
- **Default** (step 7) catches everything that didn't match any rule.

**Example: how conflicts resolve.** A bot posts "production down" in #random:
- Step 1 (self): not from self, continue
- Step 2 (bots): message is from a bot. If `rules.bots` is `skip` (default), the message is **skipped** — bot filtering wins. If the user has changed `rules.bots` to `classify`, continue to step 3.
- Step 3 (keywords): "production down" matches a keyword rule set to `force_notify` — message is **force-notified**.

This means a user who wants bot messages to be keyword-scannable can set `bots: classify` (or `bots: force_notify`), and keyword rules will still apply. A user who wants bots silenced entirely keeps the default `bots: skip` and they're filtered before keywords are ever checked.

### 4. LLM Classifier (`llm_classifier.py`)

Calls Ollama's `/api/chat` endpoint to classify message urgency.

**Key design decisions:**

- **Use `/api/chat`** (not `/api/generate`) for system prompt support and more consistent structured output.
- **Use `stream: false`** — we need the complete JSON response at once; streaming adds parsing complexity for no benefit.
- **Use schema-validated `format` parameter** (Ollama 0.5+) to guarantee valid, well-shaped JSON responses. This eliminates the need for retry-on-bad-JSON logic.
- **Keep context minimal** — send only the message text, sender, channel name, and whether it's a DM. No conversation history.

**Ollama API request shape:**

```json
{
  "model": "llama3.2:3b",
  "messages": [
    {
      "role": "system",
      "content": "<system prompt: triage instructions, urgency scale definitions>"
    },
    {
      "role": "user",
      "content": "Channel: #engineering\nSender: @alice\nDM: no\nMessage: Production is down, need help NOW"
    }
  ],
  "format": {
    "type": "object",
    "properties": {
      "urgency": { "type": "integer" },
      "reason": { "type": "string" }
    },
    "required": ["urgency", "reason"]
  },
  "stream": false
}
```

The `format` schema guarantees the model returns `{"urgency": <int>, "reason": "<string>"}`. The prompt still needs to define what each urgency level means (the schema enforces shape, not semantic correctness), but we no longer need defensive JSON parsing.

**System prompt** (configurable via config file):

```
You are a Slack notification triage assistant. Classify the urgency of the
following message on a scale of 1-5:

1 - Noise: automated messages, routine updates, social chatter
2 - Low: informational, no action needed soon
3 - Medium: relevant to your work, may need attention within hours
4 - High: needs your attention soon, action required
5 - Critical: immediate action required, outage, security incident, or direct request for urgent help

Respond with a JSON object containing "urgency" (integer 1-5) and "reason" (brief explanation).
```

**Timeout and fallback:**

- HTTP timeout of 3 seconds for the Ollama call.
- If Ollama is unreachable, returns an error, or exceeds the timeout: **default to notifying** the user. A false positive is far better than a missed critical message.
- Log all fallback activations at `WARNING` level for debugging.

**Validation:**

- After parsing the JSON response, clamp `urgency` to the 1-5 range. If the model returns 0 or 6, coerce it to the nearest bound.

### 5. Notifier (`notifier.py`)

Sends desktop notifications via `notify-send` (libnotify CLI). This is the simplest reliable approach for Linux systems.

**Notification content:**

- **Summary/title:** `Slack: #channel-name` (or `Slack: DM from @sender`)
- **Body:** Truncated message text (first ~200 chars) + urgency reason
- **Urgency hint:** Maps the 1-5 urgency scale to libnotify's three urgency levels (`low`, `normal`, `critical`) for appropriate visual treatment by the desktop environment

**Urgency mapping:**

| Score | libnotify urgency |
|---|---|
| 1-2 | low |
| 3 | normal |
| 4-5 | critical |

Note: scores of 1-2 will typically be below the notification threshold anyway, but this mapping is used for force-notify cases and ensures the DE renders high-urgency notifications prominently.

**Implementation:** Subprocess call to `notify-send` with appropriate flags. Avoids pulling in GObject/GLib Python bindings as a dependency for this single use case.

### 6. Slack Listener (`slack_listener.py`)

Uses `slack-bolt` with Socket Mode. Handles:

- Establishing and maintaining the WebSocket connection to Slack
- Subscribing to relevant event types: `message.channels`, `message.groups`, `message.im`, `message.mpim`
- Extracting relevant fields from raw event payloads into `SlackMessage` objects
- **Event deduplication:** Maintains a bounded set (`collections.deque(maxlen=1000)`) of recently seen `envelope_id` values to discard duplicate deliveries (common during reconnects)
- Resolving channel IDs to names and user IDs to display names (with caching)

**Slack App requirements:**

- Socket Mode enabled
- App-level token (`xapp-...`) for the Socket Mode connection
- Bot token (`xoxb-...`) for API calls (resolving names, etc.)
- Event subscriptions: `message.channels`, `message.groups`, `message.im`, `message.mpim`
- Bot scopes: `channels:history`, `groups:history`, `im:history`, `mpim:history`, `users:read`, `channels:read`, `groups:read`

### 7. Main / Daemon (`main.py`)

The entry point and orchestration loop. Responsibilities:

- Load config
- Initialize components (Slack listener, classifier, notifier)
- Wire up the message handling pipeline: event -> dedup -> filter -> classify/force -> threshold check -> notify
- Handle graceful shutdown on SIGTERM/SIGINT
- Top-level error handling and logging setup

**Message handling pipeline (pseudocode):**

```python
def handle_message(event, say):
    msg = parse_slack_event(event)
    if msg is None:
        return  # unparseable or irrelevant event type

    if is_duplicate(msg):
        return

    result = pre_filter(msg, config)

    if result.action == FilterAction.SKIP:
        logger.debug(f"Skipped ({result.rule}): {msg.channel} / {msg.sender}")
        return

    if result.action == FilterAction.FORCE_NOTIFY:
        notify(msg, reason=f"Matched rule: {result.rule}")
        logger.info(f"Force-notified ({result.rule}): {msg.channel} / {msg.sender}")
        return

    # result.action == FilterAction.CLASSIFY
    classification = classify(msg)
    logger.info(
        f"Classified ({result.rule}): {msg.channel} / {msg.sender} "
        f"-> urgency={classification.urgency} reason={classification.reason}"
    )

    if classification.urgency >= config.urgency_threshold:
        notify(msg, reason=classification.reason)
```

## Configuration

**File location:** `~/.config/classy-slack-notifier/config.yaml` (overridable via `--config` CLI flag or `CLASSY_CONFIG_PATH` env var).

**Full schema:**

```yaml
# ──────────────────────────────────────────────
# Ollama settings
# ──────────────────────────────────────────────
model: "llama3.2:3b"                # Ollama model to use for classification
ollama_url: "http://localhost:11434" # Ollama API base URL
ollama_timeout: 3                   # seconds; if exceeded, fall back to notify

# ──────────────────────────────────────────────
# Classification settings
# ──────────────────────────────────────────────
urgency_threshold: 3                # notify if urgency >= this value (1-5)
system_prompt: |                    # optional override for the LLM system prompt
  You are a Slack notification triage assistant...

# ──────────────────────────────────────────────
# Category rules
# ──────────────────────────────────────────────
# Each category maps to an action: skip, classify, or force_notify.
# These control the pre-filter behavior for broad message categories.
# Evaluation order is fixed (see "Pre-Filter" in design doc).
rules:
  self: skip                        # messages you sent yourself
  bots: skip                        # messages from bot users
  mentions: force_notify            # messages where you are @mentioned
  dms: force_notify                 # direct messages (1:1 and group DMs)
  default: classify                 # fallback for messages matching no rule

# ──────────────────────────────────────────────
# Channel rules
# ──────────────────────────────────────────────
# Per-channel overrides. Map channel names to actions.
# Channels not listed here fall through to the default rule.
channels:
  "#incidents": force_notify
  "#oncall": force_notify
  "#random": skip
  "#social": skip
  "#standup-bot": skip

# ──────────────────────────────────────────────
# Keyword rules
# ──────────────────────────────────────────────
# Content-based overrides. Each entry has a pattern and an action.
# Patterns are matched case-insensitively as substrings by default.
# Prefix with "regex:" for regex matching.
# Evaluated in order — first match wins.
keywords:
  - pattern: "production down"
    action: force_notify
  - pattern: "pager"
    action: force_notify
  - pattern: "regex:P[0-1] incident"
    action: force_notify
  - pattern: "standup reminder"
    action: skip

# ──────────────────────────────────────────────
# Notification display
# ──────────────────────────────────────────────
notification_timeout: 10            # seconds before auto-dismiss (0 = persistent)
```

**Config validation rules:**

- `rules` values must be one of `skip`, `classify`, `force_notify`.
- `channels` values must follow the same constraint.
- `keywords` entries must each have `pattern` (string) and `action` (one of the three actions).
- `urgency_threshold` must be an integer in range 1-5.
- `ollama_timeout` must be a positive number.
- Unknown keys are ignored with a logged warning (forward compatibility).

## Dependency Summary

```
slack-bolt          # Slack Socket Mode SDK
slack-sdk           # underlying Slack API client (pulled in by slack-bolt)
requests            # HTTP client for Ollama API calls
pyyaml              # config file parsing
```

Intentionally minimal. No async frameworks, no heavy ML libraries, no ORM. The `requests` library is used for Ollama calls since it's simple and well-understood; `httpx` or `aiohttp` are options if we move to async later.

## Logging

All logging goes to stdout/stderr, which systemd's journal captures automatically.

**Log levels:**

| Level | What gets logged |
|---|---|
| `DEBUG` | Skipped messages, raw Ollama responses, config loading details |
| `INFO` | Every classification decision (channel, sender, urgency, action taken), startup/shutdown |
| `WARNING` | Ollama timeouts/errors triggering fallback, config issues |
| `ERROR` | Slack connection failures, unrecoverable errors |

Default log level: `INFO` (configurable via config file or `--log-level` CLI flag).

## systemd Integration

```ini
[Unit]
Description=Classy Slack Notifier
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m classy_slack_notifier
Restart=on-failure
RestartSec=5
EnvironmentFile=%h/.config/classy-slack-notifier/env

[Install]
WantedBy=default.target
```

Slack tokens are stored in `~/.config/classy-slack-notifier/env` (not in the config YAML) to keep secrets separate from configuration:

```
SLACK_APP_TOKEN=xapp-...
SLACK_BOT_TOKEN=xoxb-...
```

## Error Handling and Resilience

| Scenario | Behavior |
|---|---|
| Ollama unreachable | Log warning, notify user (fail-open) |
| Ollama response timeout (>3s) | Same as unreachable |
| Ollama returns invalid JSON | Should not happen with `format` schema; if it does, log error, notify user |
| Ollama returns urgency outside 1-5 | Clamp to nearest bound |
| Slack connection drops | `slack-bolt` handles automatic reconnection |
| Duplicate Slack event | Dropped silently via envelope_id dedup |
| Config file missing | Exit with clear error message |
| Config file invalid | Exit with clear error message pointing to the bad field |

## Deferred for Future Versions

These are explicitly out of scope for v1 but are natural extensions:

- **Thread awareness** — sending conversation history for context-aware classification. Adds significant complexity (fetching thread replies, managing context windows, higher latency).
- **Message batching** — grouping messages that arrive within a short window and classifying them together. Only needed if Ollama latency becomes a problem under high traffic.
- **Notification actions** — "Open in Slack" buttons via D-Bus notification actions. Nice UX improvement but not essential.
- **Async rewrite** — moving to `AsyncApp` from slack-bolt and `aiohttp`/`httpx` for Ollama calls. Worth considering if synchronous blocking becomes a bottleneck.
- **Per-channel urgency thresholds** — e.g., threshold of 2 for #incidents but 4 for #general. Adds config complexity.
- **Web UI / stats dashboard** — classification metrics, false positive/negative tracking. Significant scope increase.

## Latency Budget

| Step | Expected time |
|---|---|
| Slack event delivery | ~50-100ms |
| Pre-filter evaluation | <1ms |
| Ollama classification (3B model, CPU) | ~200-500ms |
| notify-send dispatch | <50ms |
| **Total (classified path)** | **~300-650ms** |
| **Total (force-notify path)** | **~50-150ms** |

This is well within acceptable limits for desktop notifications.
