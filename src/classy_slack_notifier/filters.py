"""Pre-LLM rules engine for message filtering."""

import logging
import re

from classy_slack_notifier.config import Config
from classy_slack_notifier.models import FilterResult, SlackMessage

logger = logging.getLogger(__name__)


def pre_filter(msg: SlackMessage, config: Config, bot_user_id: str) -> FilterResult:
    """Apply rules-based pre-filter to a Slack message.

    Evaluation order (first match wins):
      1. self       — message from the bot's own user
      2. bots       — message from a bot user
      3. keywords   — first matching keyword pattern
      4. mentions   — message contains an @mention of the bot
      5. dms        — direct message
      6. channels   — per-channel rule from config
      7. default    — fallback rule

    Args:
        msg: The parsed Slack message.
        config: The loaded application config.
        bot_user_id: The bot's own Slack user ID (e.g. "U12345").

    Returns:
        A FilterResult with the action to take and which rule matched.
    """
    # 1. Self
    if msg.sender_id == bot_user_id:
        return FilterResult(action=config.rules["self"], rule="self")

    # 2. Bots
    if msg.is_bot:
        return FilterResult(action=config.rules["bots"], rule="bots")

    # 3. Keywords
    for kw in config.keywords:
        pattern = kw["pattern"]
        if pattern.startswith("regex:"):
            regex = pattern[len("regex:"):]
            if re.search(regex, msg.text, re.IGNORECASE):
                return FilterResult(action=kw["action"], rule=f"keyword:{pattern}")
        else:
            if pattern.lower() in msg.text.lower():
                return FilterResult(action=kw["action"], rule=f"keyword:{pattern}")

    # 4. Mentions
    if msg.is_mention:
        return FilterResult(action=config.rules["mentions"], rule="mentions")

    # 5. DMs
    if msg.is_dm:
        return FilterResult(action=config.rules["dms"], rule="dms")

    # 6. Channels
    if msg.channel in config.channels:
        return FilterResult(
            action=config.channels[msg.channel], rule=f"channel:{msg.channel}"
        )

    # 7. Default
    return FilterResult(action=config.rules["default"], rule="default")
