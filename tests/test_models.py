"""Tests for the shared data models."""

from classy_slack_notifier.models import (
    Classification,
    FilterAction,
    FilterResult,
    SlackMessage,
)


class TestFilterAction:
    def test_enum_members(self):
        assert FilterAction.SKIP.value == "skip"
        assert FilterAction.CLASSIFY.value == "classify"
        assert FilterAction.FORCE_NOTIFY.value == "force_notify"

    def test_all_members_present(self):
        members = {member.name for member in FilterAction}
        assert members == {"SKIP", "CLASSIFY", "FORCE_NOTIFY"}

    def test_lookup_by_value(self):
        assert FilterAction("skip") is FilterAction.SKIP
        assert FilterAction("classify") is FilterAction.CLASSIFY
        assert FilterAction("force_notify") is FilterAction.FORCE_NOTIFY


class TestSlackMessage:
    def test_instantiation_with_all_fields(self):
        msg = SlackMessage(
            channel="#general",
            channel_id="C123",
            sender="alice",
            sender_id="U456",
            text="hello world",
            thread_ts="1234567890.123456",
            is_dm=True,
            is_mention=True,
            is_bot=True,
        )
        assert msg.channel == "#general"
        assert msg.channel_id == "C123"
        assert msg.sender == "alice"
        assert msg.sender_id == "U456"
        assert msg.text == "hello world"
        assert msg.thread_ts == "1234567890.123456"
        assert msg.is_dm is True
        assert msg.is_mention is True
        assert msg.is_bot is True

    def test_default_values(self):
        msg = SlackMessage(
            channel="#general",
            channel_id="C123",
            sender="alice",
            sender_id="U456",
            text="hello",
        )
        assert msg.thread_ts is None
        assert msg.is_dm is False
        assert msg.is_mention is False
        assert msg.is_bot is False

    def test_required_fields_only(self):
        msg = SlackMessage(
            channel="random",
            channel_id="C789",
            sender="bob",
            sender_id="U012",
            text="",
        )
        assert msg.channel == "random"
        assert msg.text == ""


class TestClassification:
    def test_instantiation(self):
        c = Classification(urgency=3, reason="Needs attention soon")
        assert c.urgency == 3
        assert c.reason == "Needs attention soon"

    def test_boundary_urgency_values(self):
        low = Classification(urgency=1, reason="noise")
        high = Classification(urgency=5, reason="critical outage")
        assert low.urgency == 1
        assert high.urgency == 5


class TestFilterResult:
    def test_instantiation(self):
        result = FilterResult(action=FilterAction.SKIP, rule="self")
        assert result.action is FilterAction.SKIP
        assert result.rule == "self"

    def test_each_action_type(self):
        skip = FilterResult(action=FilterAction.SKIP, rule="bots")
        classify = FilterResult(action=FilterAction.CLASSIFY, rule="default")
        force = FilterResult(action=FilterAction.FORCE_NOTIFY, rule="mentions")

        assert skip.action is FilterAction.SKIP
        assert classify.action is FilterAction.CLASSIFY
        assert force.action is FilterAction.FORCE_NOTIFY

    def test_descriptive_rule_strings(self):
        result = FilterResult(
            action=FilterAction.FORCE_NOTIFY,
            rule="keyword:production down",
        )
        assert result.rule == "keyword:production down"
