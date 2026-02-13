"""Tests for the desktop notification sender."""

from classy_slack_notifier.config import Config
from classy_slack_notifier.models import SlackMessage
from classy_slack_notifier.notifier import notify


def make_msg(**overrides) -> SlackMessage:
    """Create a SlackMessage with sensible defaults, overriding specific fields."""
    defaults = dict(
        channel="general",
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


# ── Urgency mapping tests ─────────────────────────────────────────


class TestUrgencyMapping:
    def test_critical_urgency(self, mocker):
        """Urgency 4 should map to --urgency=critical."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg(channel="incidents")
        notify(msg, reason="Server on fire", urgency=4, config=make_config())

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "--urgency=critical" in args

    def test_urgency_5_is_critical(self, mocker):
        """Urgency 5 should also map to --urgency=critical."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg()
        notify(msg, reason="Critical issue", urgency=5, config=make_config())

        args = mock_run.call_args[0][0]
        assert "--urgency=critical" in args

    def test_low_urgency_1(self, mocker):
        """Urgency 1 should map to --urgency=low."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg()
        notify(msg, reason="Routine update", urgency=1, config=make_config())

        args = mock_run.call_args[0][0]
        assert "--urgency=low" in args

    def test_low_urgency_2(self, mocker):
        """Urgency 2 should map to --urgency=low."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg()
        notify(msg, reason="Informational", urgency=2, config=make_config())

        args = mock_run.call_args[0][0]
        assert "--urgency=low" in args

    def test_normal_urgency_3(self, mocker):
        """Urgency 3 should map to --urgency=normal."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg()
        notify(msg, reason="Needs attention", urgency=3, config=make_config())

        args = mock_run.call_args[0][0]
        assert "--urgency=normal" in args

    def test_force_notify_no_urgency(self, mocker):
        """Force-notify (urgency=None) should map to --urgency=normal."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg()
        notify(msg, reason="Force-notified by rule", urgency=None, config=make_config())

        args = mock_run.call_args[0][0]
        assert "--urgency=normal" in args


# ── Title formatting tests ─────────────────────────────────────────


class TestTitleFormatting:
    def test_channel_message_title(self, mocker):
        """Channel messages should use 'Slack: #channel' title format."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg(channel="incidents")
        notify(msg, reason="Alert", urgency=4, config=make_config())

        args = mock_run.call_args[0][0]
        assert "Slack: #incidents" in args

    def test_dm_title(self, mocker):
        """DMs should use 'Slack: DM from @sender' title format."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg(sender="bob", is_dm=True)
        notify(msg, reason="Direct message", urgency=None, config=make_config())

        args = mock_run.call_args[0][0]
        assert "Slack: DM from @bob" in args


# ── Body and truncation tests ─────────────────────────────────────


class TestBodyContent:
    def test_body_contains_reason(self, mocker):
        """The body should contain the reason string."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg(text="Some message")
        notify(msg, reason="Matched keyword", urgency=3, config=make_config())

        args = mock_run.call_args[0][0]
        body = args[4]  # title is args[3], body is args[4]
        assert "Matched keyword" in body
        assert "Some message" in body

    def test_text_truncation_at_200_chars(self, mocker):
        """Message text longer than 200 characters should be truncated."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        long_text = "A" * 300
        msg = make_msg(text=long_text)
        notify(msg, reason="Test reason", urgency=3, config=make_config())

        args = mock_run.call_args[0][0]
        body = args[4]
        # Body should start with exactly 200 A's, not 300
        assert body.startswith("A" * 200)
        assert "A" * 201 not in body
        assert "Test reason" in body


# ── Timeout calculation tests ──────────────────────────────────────


class TestTimeoutCalculation:
    def test_default_timeout(self, mocker):
        """Default timeout of 10s should become 10000ms."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg()
        notify(msg, reason="Test", urgency=3, config=make_config())

        args = mock_run.call_args[0][0]
        assert "--expire-time=10000" in args

    def test_custom_timeout(self, mocker):
        """Custom timeout of 5s should become 5000ms."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg()
        notify(msg, reason="Test", urgency=3, config=make_config(notification_timeout=5))

        args = mock_run.call_args[0][0]
        assert "--expire-time=5000" in args


# ── Full command structure test ────────────────────────────────────


class TestCommandStructure:
    def test_full_notify_send_command(self, mocker):
        """Verify the complete structure of the notify-send command."""
        mock_run = mocker.patch("classy_slack_notifier.notifier.subprocess.run")
        msg = make_msg(channel="alerts", text="Disk usage at 95%")
        notify(msg, reason="High urgency classification", urgency=4, config=make_config())

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "notify-send"
        assert args[1] == "--urgency=critical"
        assert args[2] == "--expire-time=10000"
        assert args[3] == "Slack: #alerts"
        assert args[4] == "Disk usage at 95%\n\nHigh urgency classification"
