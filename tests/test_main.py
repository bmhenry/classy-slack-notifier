"""Tests for the main entry point and message-handling pipeline."""

import signal
from unittest.mock import MagicMock, patch

import pytest

from classy_slack_notifier.config import Config
from classy_slack_notifier.main import _parse_args, handle_message, main
from classy_slack_notifier.models import (
    Classification,
    FilterAction,
    FilterResult,
    SlackMessage,
)


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


# ── Argument parsing ──────────────────────────────────────────────


class TestParseArgs:
    def test_defaults(self):
        args = _parse_args([])
        assert args.config is None
        assert args.log_level == "INFO"

    def test_config_flag(self):
        args = _parse_args(["--config", "/tmp/my.yaml"])
        assert args.config == "/tmp/my.yaml"

    def test_log_level_flag(self):
        args = _parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_invalid_log_level(self):
        with pytest.raises(SystemExit):
            _parse_args(["--log-level", "TRACE"])


# ── Pipeline: handle_message ──────────────────────────────────────


class TestHandleMessageSkip:
    """Messages that match a SKIP rule should not trigger classify or notify."""

    @patch("classy_slack_notifier.main.notify")
    @patch("classy_slack_notifier.main.classify")
    @patch("classy_slack_notifier.main.pre_filter")
    def test_skip_calls_nothing(self, mock_filter, mock_classify, mock_notify):
        mock_filter.return_value = FilterResult(
            action=FilterAction.SKIP, rule="self"
        )
        listener = MagicMock()
        listener.parse_event.return_value = make_msg()
        config = make_config()

        handle_message(
            {}, MagicMock(), listener=listener, config=config, bot_user_id="U_BOT"
        )

        mock_classify.assert_not_called()
        mock_notify.assert_not_called()

    @patch("classy_slack_notifier.main.notify")
    @patch("classy_slack_notifier.main.classify")
    @patch("classy_slack_notifier.main.pre_filter")
    def test_unparseable_event_returns_early(
        self, mock_filter, mock_classify, mock_notify
    ):
        listener = MagicMock()
        listener.parse_event.return_value = None
        config = make_config()

        handle_message(
            {}, MagicMock(), listener=listener, config=config, bot_user_id="U_BOT"
        )

        mock_filter.assert_not_called()
        mock_classify.assert_not_called()
        mock_notify.assert_not_called()


class TestHandleMessageForceNotify:
    """Messages that match FORCE_NOTIFY should call notify without classify."""

    @patch("classy_slack_notifier.main.notify")
    @patch("classy_slack_notifier.main.classify")
    @patch("classy_slack_notifier.main.pre_filter")
    def test_force_notify_calls_notify_not_classify(
        self, mock_filter, mock_classify, mock_notify
    ):
        mock_filter.return_value = FilterResult(
            action=FilterAction.FORCE_NOTIFY, rule="dms"
        )
        listener = MagicMock()
        msg = make_msg(is_dm=True)
        listener.parse_event.return_value = msg
        config = make_config()

        handle_message(
            {}, MagicMock(), listener=listener, config=config, bot_user_id="U_BOT"
        )

        mock_classify.assert_not_called()
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args
        assert call_kwargs[0][0] is msg
        assert "dms" in call_kwargs[1]["reason"] or "dms" in call_kwargs[0][1]


class TestHandleMessageClassifyAboveThreshold:
    """Messages classified with urgency >= threshold should trigger notify."""

    @patch("classy_slack_notifier.main.notify")
    @patch("classy_slack_notifier.main.classify")
    @patch("classy_slack_notifier.main.pre_filter")
    def test_classify_above_threshold_notifies(
        self, mock_filter, mock_classify, mock_notify
    ):
        mock_filter.return_value = FilterResult(
            action=FilterAction.CLASSIFY, rule="default"
        )
        mock_classify.return_value = Classification(
            urgency=4, reason="Looks urgent"
        )
        listener = MagicMock()
        msg = make_msg()
        listener.parse_event.return_value = msg
        config = make_config(urgency_threshold=3)

        handle_message(
            {}, MagicMock(), listener=listener, config=config, bot_user_id="U_BOT"
        )

        mock_classify.assert_called_once_with(msg, config)
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args
        assert call_kwargs[1]["urgency"] == 4
        assert call_kwargs[1]["reason"] == "Looks urgent"

    @patch("classy_slack_notifier.main.notify")
    @patch("classy_slack_notifier.main.classify")
    @patch("classy_slack_notifier.main.pre_filter")
    def test_classify_at_threshold_notifies(
        self, mock_filter, mock_classify, mock_notify
    ):
        mock_filter.return_value = FilterResult(
            action=FilterAction.CLASSIFY, rule="default"
        )
        mock_classify.return_value = Classification(
            urgency=3, reason="Moderate"
        )
        listener = MagicMock()
        listener.parse_event.return_value = make_msg()
        config = make_config(urgency_threshold=3)

        handle_message(
            {}, MagicMock(), listener=listener, config=config, bot_user_id="U_BOT"
        )

        mock_notify.assert_called_once()


class TestHandleMessageClassifyBelowThreshold:
    """Messages classified with urgency < threshold should NOT trigger notify."""

    @patch("classy_slack_notifier.main.notify")
    @patch("classy_slack_notifier.main.classify")
    @patch("classy_slack_notifier.main.pre_filter")
    def test_classify_below_threshold_no_notify(
        self, mock_filter, mock_classify, mock_notify
    ):
        mock_filter.return_value = FilterResult(
            action=FilterAction.CLASSIFY, rule="default"
        )
        mock_classify.return_value = Classification(
            urgency=1, reason="Just chatter"
        )
        listener = MagicMock()
        listener.parse_event.return_value = make_msg()
        config = make_config(urgency_threshold=3)

        handle_message(
            {}, MagicMock(), listener=listener, config=config, bot_user_id="U_BOT"
        )

        mock_classify.assert_called_once()
        mock_notify.assert_not_called()

    @patch("classy_slack_notifier.main.notify")
    @patch("classy_slack_notifier.main.classify")
    @patch("classy_slack_notifier.main.pre_filter")
    def test_classify_one_below_threshold_no_notify(
        self, mock_filter, mock_classify, mock_notify
    ):
        mock_filter.return_value = FilterResult(
            action=FilterAction.CLASSIFY, rule="default"
        )
        mock_classify.return_value = Classification(
            urgency=2, reason="Low priority"
        )
        listener = MagicMock()
        listener.parse_event.return_value = make_msg()
        config = make_config(urgency_threshold=3)

        handle_message(
            {}, MagicMock(), listener=listener, config=config, bot_user_id="U_BOT"
        )

        mock_notify.assert_not_called()


# ── Signal handling ───────────────────────────────────────────────


class TestSignalHandling:
    """Verify that SIGTERM triggers graceful shutdown."""

    @patch("classy_slack_notifier.main.SlackListener")
    @patch("classy_slack_notifier.main.load_config")
    def test_sigterm_closes_listener(self, mock_load_config, mock_listener_cls):
        mock_load_config.return_value = make_config()
        mock_listener = MagicMock()
        mock_listener.bot_user_id = "U_BOT"
        mock_listener.app = MagicMock()
        mock_listener_cls.return_value = mock_listener

        # Make start() send SIGTERM to itself so the handler fires.
        import os

        def send_sigterm():
            os.kill(os.getpid(), signal.SIGTERM)

        mock_listener.start.side_effect = send_sigterm

        main(["--config", "/dev/null"])

        mock_listener.close.assert_called_once()


# ── main() startup ────────────────────────────────────────────────


class TestMainStartup:
    @patch("classy_slack_notifier.main.SlackListener")
    @patch("classy_slack_notifier.main.load_config")
    def test_main_loads_config_and_starts(self, mock_load_config, mock_listener_cls):
        mock_load_config.return_value = make_config()
        mock_listener = MagicMock()
        mock_listener.bot_user_id = "U_BOT"
        mock_listener.app = MagicMock()
        mock_listener_cls.return_value = mock_listener

        main(["--config", "/dev/null"])

        mock_load_config.assert_called_once_with("/dev/null")
        mock_listener.start.assert_called_once()

    @patch("classy_slack_notifier.main.load_config")
    def test_main_exits_on_missing_config(self, mock_load_config):
        mock_load_config.side_effect = FileNotFoundError("/no/such/file")
        with pytest.raises(SystemExit) as exc_info:
            main(["--config", "/no/such/file"])
        assert exc_info.value.code == 1

    @patch("classy_slack_notifier.main.load_config")
    def test_main_exits_on_invalid_config(self, mock_load_config):
        mock_load_config.side_effect = ValueError("bad threshold")
        with pytest.raises(SystemExit) as exc_info:
            main(["--config", "/dev/null"])
        assert exc_info.value.code == 1
