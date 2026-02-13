"""Slack event listener using Socket Mode.

Connects to Slack via the bolt framework and converts raw events into
SlackMessage dataclass instances for downstream processing.
"""

from __future__ import annotations

import collections
import logging
import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from classy_slack_notifier.models import SlackMessage

logger = logging.getLogger(__name__)

# Event subtypes that carry no useful message content.
_IGNORED_SUBTYPES = frozenset({
    "channel_join",
    "channel_leave",
    "channel_topic",
    "channel_purpose",
    "channel_name",
    "channel_archive",
    "channel_unarchive",
    "group_join",
    "group_leave",
    "group_topic",
    "group_purpose",
    "group_name",
    "group_archive",
    "group_unarchive",
})


class SlackListener:
    """Wraps a Slack Bolt ``App`` with Socket Mode for real-time events.

    Responsibilities
    ----------------
    * Connects to Slack and retrieves the bot's own user ID.
    * Converts raw ``message`` event dicts into :class:`SlackMessage` objects.
    * De-duplicates events using a bounded deque.
    * Caches channel and user name look-ups in memory.
    """

    def __init__(self) -> None:
        bot_token = os.environ["SLACK_BOT_TOKEN"]
        app_token = os.environ["SLACK_APP_TOKEN"]

        self._app = App(token=bot_token)
        self._handler = SocketModeHandler(self._app, app_token)

        # Retrieve the bot's own user ID so we can detect self-messages and
        # mentions later.
        auth_response = self._app.client.auth_test()
        self._bot_user_id: str = auth_response["user_id"]
        logger.info("Bot user ID resolved: %s", self._bot_user_id)

        # Deduplication: keep the last 1 000 event identifiers.
        self._seen_events: collections.deque[str] = collections.deque(maxlen=1000)

        # Simple in-memory caches (no TTL for v1).
        self._channel_cache: dict[str, str] = {}
        self._user_cache: dict[str, str] = {}

    # -- public properties / helpers -----------------------------------------

    @property
    def bot_user_id(self) -> str:
        """The Slack user ID of the bot itself."""
        return self._bot_user_id

    @property
    def app(self) -> App:
        """The underlying ``slack_bolt.App`` instance."""
        return self._app

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Start the Socket Mode handler (blocking)."""
        logger.info("Starting Socket Mode handler")
        self._handler.start()

    def close(self) -> None:
        """Shut down the Socket Mode handler gracefully."""
        logger.info("Closing Socket Mode handler")
        self._handler.close()

    # -- event parsing -------------------------------------------------------

    def parse_event(self, event: dict, client) -> SlackMessage | None:
        """Convert a raw Slack ``message`` event into a :class:`SlackMessage`.

        Returns ``None`` when the event should be silently dropped (duplicate,
        irrelevant subtype, or missing required fields).

        Parameters
        ----------
        event:
            The ``event`` dict delivered by the Slack Events API.
        client:
            A ``slack_sdk.web.client.WebClient`` instance (provided by bolt
            event handlers).
        """

        # -- deduplication ---------------------------------------------------
        event_id = event.get("client_msg_id") or event.get("ts")
        if event_id is None:
            logger.debug("Event has no client_msg_id or ts; dropping")
            return None

        if event_id in self._seen_events:
            logger.debug("Duplicate event %s; dropping", event_id)
            return None

        self._seen_events.append(event_id)

        # -- filter irrelevant subtypes --------------------------------------
        subtype = event.get("subtype")
        if subtype is not None and subtype in _IGNORED_SUBTYPES:
            logger.debug("Ignored subtype %s; dropping", subtype)
            return None

        # -- required fields -------------------------------------------------
        channel_id = event.get("channel")
        sender_id = event.get("user")

        if not channel_id:
            logger.debug("Event missing 'channel'; dropping")
            return None

        # bot_message subtypes may lack a "user" field; that is acceptable
        # only when we can still identify it as a bot.
        if not sender_id:
            if event.get("bot_id") is not None or subtype == "bot_message":
                sender_id = event.get("bot_id", "unknown_bot")
            else:
                logger.debug("Event missing 'user'; dropping")
                return None

        # -- resolve names (cached) ------------------------------------------
        channel_name = self._resolve_channel(channel_id, client, event)
        sender_name = self._resolve_user(sender_id, client)

        # -- build SlackMessage ----------------------------------------------
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")
        channel_type = event.get("channel_type", "")
        is_dm = channel_type in ("im", "mpim")
        is_mention = f"<@{self._bot_user_id}>" in text
        is_bot = event.get("bot_id") is not None or subtype == "bot_message"

        return SlackMessage(
            channel=channel_name,
            channel_id=channel_id,
            sender=sender_name,
            sender_id=sender_id,
            text=text,
            thread_ts=thread_ts,
            is_dm=is_dm,
            is_mention=is_mention,
            is_bot=is_bot,
        )

    # -- private helpers -----------------------------------------------------

    def _resolve_channel(self, channel_id: str, client, event: dict) -> str:
        """Return a human-readable channel name, using cache when possible."""

        if channel_id in self._channel_cache:
            return self._channel_cache[channel_id]

        logger.debug("Channel cache miss for %s", channel_id)

        # DMs don't have a meaningful name; short-circuit.
        channel_type = event.get("channel_type", "")
        if channel_type in ("im", "mpim"):
            self._channel_cache[channel_id] = "DM"
            return "DM"

        try:
            info = client.conversations_info(channel=channel_id)
            name = info["channel"]["name"]
        except Exception:
            logger.warning(
                "Failed to resolve channel name for %s; using ID", channel_id
            )
            name = channel_id

        self._channel_cache[channel_id] = name
        return name

    def _resolve_user(self, user_id: str, client) -> str:
        """Return a human-readable user name, using cache when possible."""

        if user_id in self._user_cache:
            return self._user_cache[user_id]

        logger.debug("User cache miss for %s", user_id)

        try:
            info = client.users_info(user=user_id)
            profile = info["user"].get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or info["user"].get("real_name")
                or user_id
            )
        except Exception:
            logger.warning(
                "Failed to resolve user name for %s; using ID", user_id
            )
            name = user_id

        self._user_cache[user_id] = name
        return name
