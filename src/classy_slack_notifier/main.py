"""Entry point and message-handling pipeline for classy-slack-notifier."""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from classy_slack_notifier.config import load_config
from classy_slack_notifier.filters import pre_filter
from classy_slack_notifier.llm_classifier import classify
from classy_slack_notifier.models import FilterAction
from classy_slack_notifier.notifier import notify
from classy_slack_notifier.slack_listener import SlackListener

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="classy-slack-notifier",
        description="Monitor Slack messages and send smart desktop notifications.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to config YAML (default: ~/.config/classy-slack-notifier/config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    return parser.parse_args(argv)


def handle_message(event, client, *, listener: SlackListener, config, bot_user_id: str) -> None:
    """Process a single Slack message event through the full pipeline.

    Steps: parse → pre_filter → (skip | force_notify | classify → threshold) → notify.
    """
    msg = listener.parse_event(event, client)
    if msg is None:
        return

    result = pre_filter(msg, config, bot_user_id)

    if result.action == FilterAction.SKIP:
        logger.debug(
            "Skipped (%s): %s / %s", result.rule, msg.channel, msg.sender
        )
        return

    if result.action == FilterAction.FORCE_NOTIFY:
        notify(msg, reason=f"Matched rule: {result.rule}", config=config)
        logger.info(
            "Force-notified (%s): %s / %s", result.rule, msg.channel, msg.sender
        )
        return

    # CLASSIFY path
    classification = classify(msg, config)
    logger.info(
        "Classified (%s): %s / %s -> urgency=%d reason=%s",
        result.rule,
        msg.channel,
        msg.sender,
        classification.urgency,
        classification.reason,
    )

    if classification.urgency >= config.urgency_threshold:
        notify(
            msg,
            reason=classification.reason,
            urgency=classification.urgency,
            config=config,
        )


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        level=getattr(logging, args.log_level),
    )

    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        logger.error("Config file not found: %s", exc)
        sys.exit(1)
    except ValueError as exc:
        logger.error("Invalid configuration: %s", exc)
        sys.exit(1)

    logger.info("Configuration loaded successfully")

    listener = SlackListener()
    bot_user_id = listener.bot_user_id

    # Register the message handler on the Slack app.
    @listener.app.event("message")
    def _on_message(event, client):
        handle_message(
            event, client, listener=listener, config=config, bot_user_id=bot_user_id
        )

    # Graceful shutdown on SIGTERM / SIGINT.
    def _shutdown(signum, _frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down", sig_name)
        listener.close()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Starting classy-slack-notifier")
    listener.start()
