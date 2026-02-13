"""Configuration loading and validation for classy-slack-notifier."""

import logging
import os
from dataclasses import dataclass, field

import yaml

from classy_slack_notifier.models import FilterAction

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """\
You are a Slack notification triage assistant. Classify the urgency of the
following message on a scale of 1-5:

1 - Noise: automated messages, routine updates, social chatter
2 - Low: informational, no action needed soon
3 - Medium: relevant to your work, may need attention within hours
4 - High: needs your attention soon, action required
5 - Critical: immediate action required, outage, security incident, or direct request for urgent help

Respond with a JSON object containing "urgency" (integer 1-5) and "reason" (brief explanation).
"""

KNOWN_KEYS = {
    "model",
    "ollama_url",
    "ollama_timeout",
    "urgency_threshold",
    "system_prompt",
    "rules",
    "channels",
    "keywords",
    "notification_timeout",
}

DEFAULT_RULES = {
    "self": FilterAction.SKIP,
    "bots": FilterAction.SKIP,
    "mentions": FilterAction.FORCE_NOTIFY,
    "dms": FilterAction.FORCE_NOTIFY,
    "default": FilterAction.CLASSIFY,
}

VALID_RULE_KEYS = {"self", "bots", "mentions", "dms", "default"}


@dataclass
class Config:
    model: str = "llama3.2:3b"
    ollama_url: str = "http://localhost:11434"
    ollama_timeout: int = 3
    urgency_threshold: int = 3
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    rules: dict[str, FilterAction] = field(default_factory=lambda: dict(DEFAULT_RULES))
    channels: dict[str, FilterAction] = field(default_factory=dict)
    keywords: list[dict] = field(default_factory=list)
    notification_timeout: int = 10


def _parse_action(value: str, field_name: str) -> FilterAction:
    """Parse a string into a FilterAction, raising ValueError on invalid input."""
    try:
        return FilterAction(value)
    except ValueError:
        valid = ", ".join(a.value for a in FilterAction)
        raise ValueError(
            f"Invalid action '{value}' in {field_name}. "
            f"Must be one of: {valid}"
        )


def _validate_config(config: Config) -> None:
    """Validate config values, raising ValueError on invalid fields."""
    # Validate urgency_threshold
    if not isinstance(config.urgency_threshold, int):
        raise ValueError(
            f"urgency_threshold must be an integer, got {type(config.urgency_threshold).__name__}"
        )
    if not 1 <= config.urgency_threshold <= 5:
        raise ValueError(
            f"urgency_threshold must be between 1 and 5, got {config.urgency_threshold}"
        )

    # Validate ollama_timeout
    if not isinstance(config.ollama_timeout, (int, float)):
        raise ValueError(
            f"ollama_timeout must be a number, got {type(config.ollama_timeout).__name__}"
        )
    if config.ollama_timeout <= 0:
        raise ValueError(
            f"ollama_timeout must be positive, got {config.ollama_timeout}"
        )

    # Validate keywords
    for i, kw in enumerate(config.keywords):
        if "pattern" not in kw:
            raise ValueError(f"keywords[{i}] is missing required field 'pattern'")
        if "action" not in kw:
            raise ValueError(f"keywords[{i}] is missing required field 'action'")
        if not isinstance(kw["pattern"], str):
            raise ValueError(f"keywords[{i}].pattern must be a string")


def load_config(path: str | None = None) -> Config:
    """Load configuration from a YAML file.

    Config path resolution order:
    1. Explicit path argument
    2. CLASSY_CONFIG_PATH environment variable
    3. ~/.config/classy-slack-notifier/config.yaml
    """
    if path is None:
        path = os.environ.get("CLASSY_CONFIG_PATH")
    if path is None:
        path = os.path.expanduser("~/.config/classy-slack-notifier/config.yaml")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a YAML mapping, got {type(raw).__name__}")

    # Warn about unknown keys
    for key in raw:
        if key not in KNOWN_KEYS:
            logger.warning("Unknown config key '%s' — ignoring", key)

    config = Config()

    # Simple scalar fields
    if "model" in raw:
        config.model = str(raw["model"])
    if "ollama_url" in raw:
        config.ollama_url = str(raw["ollama_url"])
    if "ollama_timeout" in raw:
        config.ollama_timeout = raw["ollama_timeout"]
    if "urgency_threshold" in raw:
        config.urgency_threshold = raw["urgency_threshold"]
    if "system_prompt" in raw:
        config.system_prompt = str(raw["system_prompt"])
    if "notification_timeout" in raw:
        config.notification_timeout = raw["notification_timeout"]

    # Rules: merge with defaults
    if "rules" in raw:
        raw_rules = raw["rules"]
        if not isinstance(raw_rules, dict):
            raise ValueError("'rules' must be a mapping")
        for key, value in raw_rules.items():
            if key not in VALID_RULE_KEYS:
                logger.warning("Unknown rule key '%s' — ignoring", key)
                continue
            config.rules[key] = _parse_action(value, f"rules.{key}")

    # Channels
    if "channels" in raw:
        raw_channels = raw["channels"]
        if not isinstance(raw_channels, dict):
            raise ValueError("'channels' must be a mapping")
        for channel_name, value in raw_channels.items():
            config.channels[channel_name] = _parse_action(
                value, f"channels.{channel_name}"
            )

    # Keywords
    if "keywords" in raw:
        raw_keywords = raw["keywords"]
        if not isinstance(raw_keywords, list):
            raise ValueError("'keywords' must be a list")
        for i, entry in enumerate(raw_keywords):
            if not isinstance(entry, dict):
                raise ValueError(f"keywords[{i}] must be a mapping")
            if "action" in entry:
                parsed_action = _parse_action(entry["action"], f"keywords[{i}].action")
                entry = dict(entry)  # copy to avoid mutating input
                entry["action"] = parsed_action
            config.keywords.append(entry)

    _validate_config(config)

    return config
