"""Tests for the pre-filter rules engine."""

import pytest

from classy_slack_notifier.config import Config
from classy_slack_notifier.filters import pre_filter
from classy_slack_notifier.models import FilterAction, SlackMessage

BOT_USER_ID = "U_BOT"


def make_msg(**overrides) -> SlackMessage:
    """Create a SlackMessage with sensible defaults, overriding specific fields."""
    defaults = dict(
        channel="#general",
        channel_id="C123",
        sender="alice",
        sender_id="U_ALICE",
        text="hello world",
    )
    defaults.update(overrides)
    return SlackMessage(**defaults)


def make_config(**overrides) -> Config:
    """Create a Config with defaults, overriding specific fields."""
    config = Config()
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


# ── Individual rule tests ──────────────────────────────────────────


class TestSelfRule:
    def test_self_message_default_skip(self):
        msg = make_msg(sender_id=BOT_USER_ID)
        result = pre_filter(msg, make_config(), BOT_USER_ID)
        assert result.action is FilterAction.SKIP
        assert result.rule == "self"

    def test_self_message_configured_classify(self):
        rules = dict(Config().rules)
        rules["self"] = FilterAction.CLASSIFY
        msg = make_msg(sender_id=BOT_USER_ID)
        result = pre_filter(msg, make_config(rules=rules), BOT_USER_ID)
        assert result.action is FilterAction.CLASSIFY
        assert result.rule == "self"


class TestBotsRule:
    def test_bot_message_default_skip(self):
        msg = make_msg(is_bot=True)
        result = pre_filter(msg, make_config(), BOT_USER_ID)
        assert result.action is FilterAction.SKIP
        assert result.rule == "bots"

    def test_bot_message_configured_classify(self):
        rules = dict(Config().rules)
        rules["bots"] = FilterAction.CLASSIFY
        msg = make_msg(is_bot=True)
        result = pre_filter(msg, make_config(rules=rules), BOT_USER_ID)
        assert result.action is FilterAction.CLASSIFY
        assert result.rule == "bots"


class TestKeywordsRule:
    def test_substring_match(self):
        keywords = [{"pattern": "production down", "action": FilterAction.FORCE_NOTIFY}]
        msg = make_msg(text="Alert: production down in us-east-1")
        result = pre_filter(msg, make_config(keywords=keywords), BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY
        assert result.rule == "keyword:production down"

    def test_substring_case_insensitive(self):
        keywords = [{"pattern": "production down", "action": FilterAction.FORCE_NOTIFY}]
        msg = make_msg(text="PRODUCTION DOWN!!!")
        result = pre_filter(msg, make_config(keywords=keywords), BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY

    def test_regex_match(self):
        keywords = [{"pattern": "regex:P[0-1] incident", "action": FilterAction.FORCE_NOTIFY}]
        msg = make_msg(text="New P0 incident declared")
        result = pre_filter(msg, make_config(keywords=keywords), BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY
        assert result.rule == "keyword:regex:P[0-1] incident"

    def test_regex_case_insensitive(self):
        keywords = [{"pattern": "regex:p[0-1] incident", "action": FilterAction.FORCE_NOTIFY}]
        msg = make_msg(text="New P0 INCIDENT declared")
        result = pre_filter(msg, make_config(keywords=keywords), BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY

    def test_no_keyword_match(self):
        keywords = [{"pattern": "production down", "action": FilterAction.FORCE_NOTIFY}]
        msg = make_msg(text="Just a normal message")
        result = pre_filter(msg, make_config(keywords=keywords), BOT_USER_ID)
        # Should fall through to default, not keyword
        assert result.rule == "default"

    def test_first_keyword_wins(self):
        keywords = [
            {"pattern": "urgent", "action": FilterAction.FORCE_NOTIFY},
            {"pattern": "urgent", "action": FilterAction.SKIP},
        ]
        msg = make_msg(text="This is urgent")
        result = pre_filter(msg, make_config(keywords=keywords), BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY

    def test_keyword_skip_action(self):
        keywords = [{"pattern": "standup reminder", "action": FilterAction.SKIP}]
        msg = make_msg(text="standup reminder: please post your updates")
        result = pre_filter(msg, make_config(keywords=keywords), BOT_USER_ID)
        assert result.action is FilterAction.SKIP
        assert result.rule == "keyword:standup reminder"


class TestMentionsRule:
    def test_mention_default_force_notify(self):
        msg = make_msg(is_mention=True)
        result = pre_filter(msg, make_config(), BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY
        assert result.rule == "mentions"

    def test_mention_configured_classify(self):
        rules = dict(Config().rules)
        rules["mentions"] = FilterAction.CLASSIFY
        msg = make_msg(is_mention=True)
        result = pre_filter(msg, make_config(rules=rules), BOT_USER_ID)
        assert result.action is FilterAction.CLASSIFY
        assert result.rule == "mentions"


class TestDmsRule:
    def test_dm_default_force_notify(self):
        msg = make_msg(is_dm=True)
        result = pre_filter(msg, make_config(), BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY
        assert result.rule == "dms"

    def test_dm_configured_skip(self):
        rules = dict(Config().rules)
        rules["dms"] = FilterAction.SKIP
        msg = make_msg(is_dm=True)
        result = pre_filter(msg, make_config(rules=rules), BOT_USER_ID)
        assert result.action is FilterAction.SKIP
        assert result.rule == "dms"


class TestChannelsRule:
    def test_channel_match(self):
        channels = {"#incidents": FilterAction.FORCE_NOTIFY}
        msg = make_msg(channel="#incidents")
        result = pre_filter(msg, make_config(channels=channels), BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY
        assert result.rule == "channel:#incidents"

    def test_channel_skip(self):
        channels = {"#random": FilterAction.SKIP}
        msg = make_msg(channel="#random")
        result = pre_filter(msg, make_config(channels=channels), BOT_USER_ID)
        assert result.action is FilterAction.SKIP
        assert result.rule == "channel:#random"

    def test_channel_not_in_map_falls_through(self):
        channels = {"#incidents": FilterAction.FORCE_NOTIFY}
        msg = make_msg(channel="#general")
        result = pre_filter(msg, make_config(channels=channels), BOT_USER_ID)
        assert result.rule == "default"


class TestDefaultRule:
    def test_default_classify(self):
        msg = make_msg()
        result = pre_filter(msg, make_config(), BOT_USER_ID)
        assert result.action is FilterAction.CLASSIFY
        assert result.rule == "default"

    def test_default_configured_skip(self):
        rules = dict(Config().rules)
        rules["default"] = FilterAction.SKIP
        msg = make_msg()
        result = pre_filter(msg, make_config(rules=rules), BOT_USER_ID)
        assert result.action is FilterAction.SKIP
        assert result.rule == "default"


# ── Evaluation order tests (first-match-wins) ─────────────────────


class TestEvaluationOrder:
    def test_bot_skip_prevents_keyword_match(self):
        """A bot message with a matching keyword: bots=skip should win."""
        keywords = [{"pattern": "production down", "action": FilterAction.FORCE_NOTIFY}]
        msg = make_msg(is_bot=True, text="production down")
        config = make_config(keywords=keywords)
        result = pre_filter(msg, config, BOT_USER_ID)
        assert result.action is FilterAction.SKIP
        assert result.rule == "bots"

    def test_bot_classify_allows_keyword_match(self):
        """A bot with bots=classify: keyword SHOULD be reached and win."""
        rules = dict(Config().rules)
        rules["bots"] = FilterAction.CLASSIFY
        keywords = [{"pattern": "production down", "action": FilterAction.FORCE_NOTIFY}]
        msg = make_msg(is_bot=True, text="production down")
        config = make_config(rules=rules, keywords=keywords)
        result = pre_filter(msg, config, BOT_USER_ID)
        # Bots rule fires first with CLASSIFY, so bots rule wins
        assert result.rule == "bots"
        assert result.action is FilterAction.CLASSIFY

    def test_dm_wins_over_channel_rule(self):
        """A DM that also matches a channel rule: DM should win."""
        channels = {"#general": FilterAction.SKIP}
        msg = make_msg(is_dm=True, channel="#general")
        config = make_config(channels=channels)
        result = pre_filter(msg, config, BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY
        assert result.rule == "dms"

    def test_mention_wins_over_dm(self):
        """A message that is both a mention and a DM: mention should win (checked first)."""
        msg = make_msg(is_mention=True, is_dm=True)
        # Even if dms is skip, mentions comes first
        rules = dict(Config().rules)
        rules["dms"] = FilterAction.SKIP
        config = make_config(rules=rules)
        result = pre_filter(msg, config, BOT_USER_ID)
        assert result.rule == "mentions"

    def test_keyword_wins_over_mention(self):
        """A message with both a keyword match and a mention: keyword should win."""
        keywords = [{"pattern": "urgent", "action": FilterAction.SKIP}]
        msg = make_msg(is_mention=True, text="This is urgent")
        config = make_config(keywords=keywords)
        result = pre_filter(msg, config, BOT_USER_ID)
        assert result.action is FilterAction.SKIP
        assert result.rule == "keyword:urgent"

    def test_keyword_wins_over_channel(self):
        """A keyword match in a channel with a channel rule: keyword should win."""
        keywords = [{"pattern": "fire", "action": FilterAction.FORCE_NOTIFY}]
        channels = {"#random": FilterAction.SKIP}
        msg = make_msg(channel="#random", text="fire in the building!")
        config = make_config(keywords=keywords, channels=channels)
        result = pre_filter(msg, config, BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY
        assert result.rule == "keyword:fire"

    def test_self_wins_over_everything(self):
        """Self message that is also a DM with keyword match: self rule wins."""
        keywords = [{"pattern": "urgent", "action": FilterAction.FORCE_NOTIFY}]
        msg = make_msg(
            sender_id=BOT_USER_ID,
            is_dm=True,
            is_mention=True,
            text="This is urgent",
        )
        config = make_config(keywords=keywords)
        result = pre_filter(msg, config, BOT_USER_ID)
        assert result.rule == "self"

    def test_channel_wins_over_default(self):
        """A message in a mapped channel: channel rule wins over default."""
        channels = {"#incidents": FilterAction.FORCE_NOTIFY}
        msg = make_msg(channel="#incidents")
        config = make_config(channels=channels)
        result = pre_filter(msg, config, BOT_USER_ID)
        assert result.action is FilterAction.FORCE_NOTIFY
        assert result.rule == "channel:#incidents"
