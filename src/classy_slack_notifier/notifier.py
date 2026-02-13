"""Desktop notification sender using libnotify (notify-send)."""

import logging
import subprocess

from classy_slack_notifier.config import Config
from classy_slack_notifier.models import SlackMessage

logger = logging.getLogger(__name__)


def _urgency_level(urgency: int | None) -> str:
    """Map a 1-5 urgency score to a libnotify urgency level.

    Returns "low", "normal", or "critical".
    If urgency is None (force-notify case), returns "normal".
    """
    if urgency is None:
        return "normal"
    if urgency <= 2:
        return "low"
    if urgency <= 3:
        return "normal"
    return "critical"


def notify(
    msg: SlackMessage,
    reason: str,
    urgency: int | None = None,
    *,
    config: Config,
) -> None:
    """Send a desktop notification for a Slack message.

    Args:
        msg: The Slack message that triggered the notification.
        reason: Human-readable explanation of why this notification was sent.
        urgency: Urgency score (1-5) from classification, or None for force-notify.
        config: Application configuration (used for notification_timeout).
    """
    # Build title
    if msg.is_dm:
        title = f"Slack: DM from @{msg.sender}"
    else:
        title = f"Slack: #{msg.channel}"

    # Build body: truncated message text + reason
    body = f"{msg.text[:200]}\n\n{reason}"

    # Map urgency to libnotify level
    level = _urgency_level(urgency)

    # Convert timeout from seconds to milliseconds
    ms = config.notification_timeout * 1000

    subprocess.run(
        ["notify-send", f"--urgency={level}", f"--expire-time={ms}", title, body],
    )

    logger.info(
        "Notification sent: title=%r urgency=%s expire=%dms",
        title,
        level,
        ms,
    )
