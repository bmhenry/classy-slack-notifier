"""LLM-based message classifier using Ollama."""

import json
import logging

import requests

from classy_slack_notifier.config import Config
from classy_slack_notifier.models import Classification, SlackMessage

logger = logging.getLogger(__name__)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "urgency": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["urgency", "reason"],
}


def _build_user_content(msg: SlackMessage) -> str:
    """Format a SlackMessage into the user-message string sent to the LLM."""
    return (
        f"Channel: {msg.channel}\n"
        f"Sender: {msg.sender}\n"
        f"DM: {'yes' if msg.is_dm else 'no'}\n"
        f"Message: {msg.text}"
    )


def _fallback(config: Config, context: str) -> Classification:
    """Return a precautionary classification when the LLM is unavailable."""
    logger.warning("LLM classifier fallback: %s", context)
    return Classification(
        urgency=config.urgency_threshold,
        reason="LLM unavailable \u2014 notifying as precaution",
    )


def classify(msg: SlackMessage, config: Config) -> Classification:
    """Classify a Slack message via Ollama and return an urgency score.

    On any communication or parsing failure the function returns a
    precautionary Classification whose urgency equals the configured
    threshold so the message is never silently dropped.
    """
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": _build_user_content(msg)},
        ],
        "format": RESPONSE_SCHEMA,
        "stream": False,
    }

    try:
        resp = requests.post(
            f"{config.ollama_url}/api/chat",
            json=body,
            timeout=config.ollama_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = json.loads(data["message"]["content"])
        urgency = int(content["urgency"])
        reason = str(content["reason"])
    except (requests.ConnectionError, requests.Timeout) as exc:
        return _fallback(config, str(exc))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _fallback(config, f"unexpected response: {exc}")

    # Clamp urgency into the valid 1-5 range.
    urgency = max(1, min(5, urgency))

    return Classification(urgency=urgency, reason=reason)
