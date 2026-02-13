"""Tests for the Slack event listener / parser."""

from unittest.mock import MagicMock, patch

import pytest

from classy_slack_notifier.slack_listener import SlackListener

BOT_USER_ID = "U_BOT_123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client():
    """Return a mock Slack ``WebClient`` with standard stubs."""
    client = MagicMock()
    client.conversations_info.return_value = {
        "channel": {"name": "general"},
    }
    client.users_info.return_value = {
        "user": {
            "profile": {"display_name": "Alice", "real_name": "Alice Smith"},
            "real_name": "Alice Smith",
        },
    }
    return client


def _make_event(**overrides) -> dict:
    """Return a minimal valid message event dict, with overrides."""
    base = {
        "type": "message",
        "channel": "C_CHAN_1",
        "user": "U_ALICE",
        "text": "hello world",
        "ts": "1700000000.000001",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def listener():
    """Create a ``SlackListener`` with Slack API calls fully mocked."""
    with (
        patch("classy_slack_notifier.slack_listener.App") as MockApp,
        patch("classy_slack_notifier.slack_listener.SocketModeHandler"),
        patch.dict(
            "os.environ",
            {"SLACK_BOT_TOKEN": "xoxb-fake", "SLACK_APP_TOKEN": "xapp-fake"},
        ),
    ):
        # Make auth_test return the bot user ID.
        mock_app_instance = MockApp.return_value
        mock_app_instance.client.auth_test.return_value = {
            "user_id": BOT_USER_ID,
        }
        sl = SlackListener()
    return sl


# ---------------------------------------------------------------------------
# Basic event parsing
# ---------------------------------------------------------------------------


class TestParseEvent:
    def test_basic_event(self, listener):
        client = _make_client()
        event = _make_event()

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.channel == "general"
        assert msg.channel_id == "C_CHAN_1"
        assert msg.sender == "Alice"
        assert msg.sender_id == "U_ALICE"
        assert msg.text == "hello world"
        assert msg.thread_ts is None
        assert msg.is_dm is False
        assert msg.is_mention is False
        assert msg.is_bot is False

    def test_thread_ts_preserved(self, listener):
        client = _make_client()
        event = _make_event(thread_ts="1700000000.000000")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.thread_ts == "1700000000.000000"


# ---------------------------------------------------------------------------
# DM detection
# ---------------------------------------------------------------------------


class TestDmDetection:
    def test_im_channel_type(self, listener):
        client = _make_client()
        event = _make_event(channel_type="im")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_dm is True
        assert msg.channel == "DM"

    def test_mpim_channel_type(self, listener):
        client = _make_client()
        event = _make_event(channel_type="mpim")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_dm is True
        assert msg.channel == "DM"

    def test_non_dm_channel_type(self, listener):
        client = _make_client()
        event = _make_event(channel_type="channel")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_dm is False


# ---------------------------------------------------------------------------
# Mention detection
# ---------------------------------------------------------------------------


class TestMentionDetection:
    def test_mention_detected(self, listener):
        client = _make_client()
        event = _make_event(text=f"Hey <@{BOT_USER_ID}> can you help?")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_mention is True

    def test_no_mention(self, listener):
        client = _make_client()
        event = _make_event(text="No mention here")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_mention is False

    def test_other_user_mention_is_not_self_mention(self, listener):
        client = _make_client()
        event = _make_event(text="Hey <@U_OTHER> look at this")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_mention is False


# ---------------------------------------------------------------------------
# Bot detection
# ---------------------------------------------------------------------------


class TestBotDetection:
    def test_bot_id_present(self, listener):
        client = _make_client()
        event = _make_event(bot_id="B_BOT_1")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_bot is True

    def test_bot_message_subtype(self, listener):
        client = _make_client()
        # bot_message events may lack a "user" field but have bot_id
        event = _make_event(subtype="bot_message", bot_id="B_BOT_2")
        event.pop("user", None)

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_bot is True

    def test_not_a_bot(self, listener):
        client = _make_client()
        event = _make_event()

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.is_bot is False


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_duplicate_by_ts(self, listener):
        client = _make_client()
        event = _make_event(ts="1700000000.999999")

        first = listener.parse_event(event, client)
        second = listener.parse_event(event, client)

        assert first is not None
        assert second is None

    def test_duplicate_by_client_msg_id(self, listener):
        client = _make_client()
        event = _make_event(client_msg_id="msg-abc-123")

        first = listener.parse_event(event, client)
        second = listener.parse_event(event, client)

        assert first is not None
        assert second is None

    def test_different_events_not_deduped(self, listener):
        client = _make_client()
        event_a = _make_event(ts="1700000000.000001")
        event_b = _make_event(ts="1700000000.000002")

        first = listener.parse_event(event_a, client)
        second = listener.parse_event(event_b, client)

        assert first is not None
        assert second is not None


# ---------------------------------------------------------------------------
# Unparseable / missing-field events
# ---------------------------------------------------------------------------


class TestUnparseableEvents:
    def test_missing_user_returns_none(self, listener):
        client = _make_client()
        event = _make_event()
        del event["user"]

        msg = listener.parse_event(event, client)

        assert msg is None

    def test_missing_channel_returns_none(self, listener):
        client = _make_client()
        event = _make_event()
        del event["channel"]

        msg = listener.parse_event(event, client)

        assert msg is None

    def test_missing_ts_and_client_msg_id_returns_none(self, listener):
        client = _make_client()
        event = _make_event()
        del event["ts"]
        # Ensure client_msg_id is also absent (it is by default).

        msg = listener.parse_event(event, client)

        assert msg is None


# ---------------------------------------------------------------------------
# Ignored subtypes
# ---------------------------------------------------------------------------


class TestIgnoredSubtypes:
    @pytest.mark.parametrize(
        "subtype",
        [
            "channel_join",
            "channel_leave",
            "channel_topic",
            "channel_purpose",
            "channel_name",
            "channel_archive",
            "channel_unarchive",
            "group_join",
            "group_leave",
        ],
    )
    def test_irrelevant_subtype_returns_none(self, listener, subtype):
        client = _make_client()
        # Give each a unique ts so dedup doesn't interfere.
        event = _make_event(subtype=subtype, ts=f"170000000{hash(subtype)}.000001")

        msg = listener.parse_event(event, client)

        assert msg is None


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------


class TestChannelNameCaching:
    def test_conversations_info_called_once(self, listener):
        client = _make_client()
        event_a = _make_event(ts="1700000000.000001")
        event_b = _make_event(ts="1700000000.000002")

        listener.parse_event(event_a, client)
        listener.parse_event(event_b, client)

        # Both events use the same channel ID; conversations_info should be
        # called exactly once.
        client.conversations_info.assert_called_once_with(channel="C_CHAN_1")

    def test_different_channels_both_resolved(self, listener):
        client = _make_client()
        client.conversations_info.side_effect = [
            {"channel": {"name": "general"}},
            {"channel": {"name": "random"}},
        ]
        event_a = _make_event(ts="1700000000.000001", channel="C_CHAN_1")
        event_b = _make_event(ts="1700000000.000002", channel="C_CHAN_2")

        msg_a = listener.parse_event(event_a, client)
        msg_b = listener.parse_event(event_b, client)

        assert msg_a.channel == "general"
        assert msg_b.channel == "random"
        assert client.conversations_info.call_count == 2


class TestUserNameCaching:
    def test_users_info_called_once(self, listener):
        client = _make_client()
        event_a = _make_event(ts="1700000000.000001")
        event_b = _make_event(ts="1700000000.000002")

        listener.parse_event(event_a, client)
        listener.parse_event(event_b, client)

        # Both events use the same sender; users_info should be called once.
        client.users_info.assert_called_once_with(user="U_ALICE")

    def test_different_users_both_resolved(self, listener):
        client = _make_client()
        client.users_info.side_effect = [
            {
                "user": {
                    "profile": {"display_name": "Alice", "real_name": "Alice Smith"},
                    "real_name": "Alice Smith",
                },
            },
            {
                "user": {
                    "profile": {"display_name": "Bob", "real_name": "Bob Jones"},
                    "real_name": "Bob Jones",
                },
            },
        ]
        event_a = _make_event(ts="1700000000.000001", user="U_ALICE")
        event_b = _make_event(ts="1700000000.000002", user="U_BOB")

        msg_a = listener.parse_event(event_a, client)
        msg_b = listener.parse_event(event_b, client)

        assert msg_a.sender == "Alice"
        assert msg_b.sender == "Bob"
        assert client.users_info.call_count == 2


# ---------------------------------------------------------------------------
# SlackListener construction
# ---------------------------------------------------------------------------


class TestSlackListenerInit:
    def test_bot_user_id_set(self, listener):
        assert listener.bot_user_id == BOT_USER_ID

    def test_app_property(self, listener):
        assert listener.app is not None

    def test_missing_env_vars_raises(self):
        """SlackListener should raise if tokens are not set."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(KeyError):
                SlackListener()


# ---------------------------------------------------------------------------
# Lifecycle methods
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_delegates(self, listener):
        listener._handler = MagicMock()
        listener.start()
        listener._handler.start.assert_called_once()

    def test_close_delegates(self, listener):
        listener._handler = MagicMock()
        listener.close()
        listener._handler.close.assert_called_once()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_text(self, listener):
        client = _make_client()
        event = _make_event(text="")

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.text == ""

    def test_missing_text_defaults_empty(self, listener):
        client = _make_client()
        event = _make_event()
        del event["text"]

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.text == ""

    def test_conversations_info_failure_falls_back_to_id(self, listener):
        client = _make_client()
        client.conversations_info.side_effect = Exception("API error")
        event = _make_event()

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.channel == "C_CHAN_1"

    def test_users_info_failure_falls_back_to_id(self, listener):
        client = _make_client()
        client.users_info.side_effect = Exception("API error")
        event = _make_event()

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.sender == "U_ALICE"

    def test_user_with_only_real_name(self, listener):
        """When display_name is empty, fall back to real_name."""
        client = _make_client()
        client.users_info.return_value = {
            "user": {
                "profile": {"display_name": "", "real_name": "Charlie Root"},
                "real_name": "Charlie Root",
            },
        }
        event = _make_event()

        msg = listener.parse_event(event, client)

        assert msg is not None
        assert msg.sender == "Charlie Root"

    def test_dm_channel_not_resolved_via_api(self, listener):
        """DM channels should get 'DM' without calling conversations_info."""
        client = _make_client()
        event = _make_event(channel_type="im")

        listener.parse_event(event, client)

        client.conversations_info.assert_not_called()
