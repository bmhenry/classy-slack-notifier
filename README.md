# classy-slack-notifier

A lightweight Linux daemon that monitors Slack messages via Socket Mode, classifies their urgency using a local LLM (Ollama), and delivers desktop notifications for messages that meet a configurable urgency threshold. Reduces notification fatigue while ensuring critical messages are never missed.

## How it works

```
Slack message → Pre-filter (rules) → LLM classification (Ollama) → Desktop notification
```

Messages are evaluated through a rules-based pre-filter first. Depending on the rule, a message is either **skipped** silently, **force-notified** immediately, or **classified** by a local LLM for urgency scoring. Only classified messages that meet the urgency threshold produce a notification.

## Requirements

- Python 3.11+
- Linux with `notify-send` (libnotify)
- [Ollama](https://ollama.ai/) running locally
- A Slack app with Socket Mode enabled

## Installation

```bash
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```

## Slack app setup

Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps) with:

1. **Socket Mode** enabled (generates an app-level token `xapp-...`)
2. **Bot token scopes:** `channels:history`, `groups:history`, `im:history`, `mpim:history`, `users:read`, `channels:read`, `groups:read`
3. **Event subscriptions:** `message.channels`, `message.groups`, `message.im`, `message.mpim`
4. Install the app to your workspace to get a bot token (`xoxb-...`)

## Configuration

### Slack tokens

Store tokens in `~/.config/classy-slack-notifier/env`:

```
SLACK_APP_TOKEN=xapp-...
SLACK_BOT_TOKEN=xoxb-...
```

### Application config

Copy the example config and edit it:

```bash
mkdir -p ~/.config/classy-slack-notifier
cp config.example.yaml ~/.config/classy-slack-notifier/config.yaml
```

The config file controls LLM settings, filter rules, and notification behavior. See `config.example.yaml` for the full schema with comments.

Config path resolution order:
1. `--config` CLI argument
2. `CLASSY_CONFIG_PATH` environment variable
3. `~/.config/classy-slack-notifier/config.yaml`

### Filter rules

Every message category is configurable with three actions: `skip`, `classify`, or `force_notify`.

| Category | What it matches | Default |
|---|---|---|
| `self` | Your own messages | `skip` |
| `bots` | Bot messages | `skip` |
| `mentions` | Messages @mentioning you | `force_notify` |
| `dms` | Direct messages | `force_notify` |
| `default` | Everything else | `classify` |

Per-channel and keyword-based rules are also supported. See `config.example.yaml` for examples.

## Usage

```bash
# Run directly
classy-slack-notifier

# Or via Python module
python -m classy_slack_notifier

# With options
classy-slack-notifier --config /path/to/config.yaml --log-level DEBUG
```

Make sure `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set in your environment (or loaded via the env file with systemd).

## Running as a systemd user service

```bash
mkdir -p ~/.config/systemd/user
cp systemd/classy-slack-notifier.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable classy-slack-notifier
systemctl --user start classy-slack-notifier
```

View logs:

```bash
journalctl --user -u classy-slack-notifier -f
```

## Development

Run tests:

```bash
pip install -e ".[dev]"
pytest
```
