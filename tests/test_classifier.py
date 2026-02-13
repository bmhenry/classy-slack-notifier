"""Tests for the LLM classifier module."""

import json

import pytest
import requests

from classy_slack_notifier.config import Config
from classy_slack_notifier.llm_classifier import classify
from classy_slack_notifier.models import Classification, SlackMessage


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


def _ollama_response(urgency: int, reason: str) -> dict:
    """Build a fake Ollama /api/chat JSON response."""
    return {
        "message": {
            "role": "assistant",
            "content": json.dumps({"urgency": urgency, "reason": reason}),
        },
    }


# ── Successful classification ──────────────────────────────────────


class TestSuccessfulClassification:
    def test_returns_correct_urgency_and_reason(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = _ollama_response(4, "deploy is broken")
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        result = classify(make_msg(), make_config())

        assert result == Classification(urgency=4, reason="deploy is broken")

    def test_sends_correct_request_body(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = _ollama_response(2, "routine")
        mock_resp.raise_for_status = mocker.Mock()
        mock_post = mocker.patch(
            "classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp
        )

        msg = make_msg(channel="#incidents", sender="bob", is_dm=True, text="server on fire")
        config = make_config(model="custom-model", ollama_url="http://myhost:1234", ollama_timeout=7)

        classify(msg, config)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "http://myhost:1234/api/chat"
        assert call_kwargs[1]["timeout"] == 7

        body = call_kwargs[1]["json"]
        assert body["model"] == "custom-model"
        assert body["stream"] is False
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["role"] == "user"

        user_content = body["messages"][1]["content"]
        assert "Channel: #incidents" in user_content
        assert "Sender: bob" in user_content
        assert "DM: yes" in user_content
        assert "Message: server on fire" in user_content

    def test_dm_field_shows_no_when_not_dm(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = _ollama_response(1, "noise")
        mock_resp.raise_for_status = mocker.Mock()
        mock_post = mocker.patch(
            "classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp
        )

        classify(make_msg(is_dm=False), make_config())

        user_content = mock_post.call_args[1]["json"]["messages"][1]["content"]
        assert "DM: no" in user_content


# ── Urgency clamping ───────────────────────────────────────────────


class TestUrgencyClamping:
    def test_urgency_below_minimum_clamped_to_1(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = _ollama_response(0, "very low")
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        result = classify(make_msg(), make_config())

        assert result.urgency == 1

    def test_negative_urgency_clamped_to_1(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = _ollama_response(-3, "way below")
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        result = classify(make_msg(), make_config())

        assert result.urgency == 1

    def test_urgency_above_maximum_clamped_to_5(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = _ollama_response(7, "off the charts")
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        result = classify(make_msg(), make_config())

        assert result.urgency == 5

    def test_urgency_at_boundaries_unchanged(self, mocker):
        for val in (1, 5):
            mock_resp = mocker.Mock()
            mock_resp.json.return_value = _ollama_response(val, "boundary")
            mock_resp.raise_for_status = mocker.Mock()
            mocker.patch(
                "classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp
            )

            result = classify(make_msg(), make_config())
            assert result.urgency == val


# ── Fallback on errors ─────────────────────────────────────────────


class TestFallbackOnErrors:
    def test_timeout_returns_fallback(self, mocker):
        mocker.patch(
            "classy_slack_notifier.llm_classifier.requests.post",
            side_effect=requests.Timeout("timed out"),
        )

        result = classify(make_msg(), make_config(urgency_threshold=3))

        assert result.urgency == 3
        assert "LLM unavailable" in result.reason

    def test_connection_error_returns_fallback(self, mocker):
        mocker.patch(
            "classy_slack_notifier.llm_classifier.requests.post",
            side_effect=requests.ConnectionError("refused"),
        )

        result = classify(make_msg(), make_config(urgency_threshold=4))

        assert result.urgency == 4
        assert "LLM unavailable" in result.reason

    def test_fallback_uses_configured_threshold(self, mocker):
        mocker.patch(
            "classy_slack_notifier.llm_classifier.requests.post",
            side_effect=requests.Timeout(),
        )

        result = classify(make_msg(), make_config(urgency_threshold=5))
        assert result.urgency == 5

        result = classify(make_msg(), make_config(urgency_threshold=1))
        assert result.urgency == 1

    def test_malformed_json_returns_fallback(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {
            "message": {"content": "this is not valid json {{{"}
        }
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        result = classify(make_msg(), make_config(urgency_threshold=3))

        assert result.urgency == 3
        assert "LLM unavailable" in result.reason

    def test_missing_urgency_field_returns_fallback(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {
            "message": {"content": json.dumps({"reason": "no urgency here"})}
        }
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        result = classify(make_msg(), make_config(urgency_threshold=3))

        assert result.urgency == 3
        assert "LLM unavailable" in result.reason

    def test_missing_reason_field_returns_fallback(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {
            "message": {"content": json.dumps({"urgency": 4})}
        }
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        result = classify(make_msg(), make_config(urgency_threshold=3))

        # missing "reason" key => KeyError => fallback
        assert result.urgency == 3
        assert "LLM unavailable" in result.reason

    def test_missing_message_key_returns_fallback(self, mocker):
        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"unexpected": "structure"}
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        result = classify(make_msg(), make_config(urgency_threshold=2))

        assert result.urgency == 2
        assert "LLM unavailable" in result.reason


# ── Logging ────────────────────────────────────────────────────────


class TestLogging:
    def test_timeout_logs_warning(self, mocker, caplog):
        import logging

        mocker.patch(
            "classy_slack_notifier.llm_classifier.requests.post",
            side_effect=requests.Timeout("connect timed out"),
        )

        with caplog.at_level(logging.WARNING):
            classify(make_msg(), make_config())

        assert "LLM classifier fallback" in caplog.text

    def test_malformed_response_logs_warning(self, mocker, caplog):
        import logging

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"message": {"content": "not json"}}
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("classy_slack_notifier.llm_classifier.requests.post", return_value=mock_resp)

        with caplog.at_level(logging.WARNING):
            classify(make_msg(), make_config())

        assert "LLM classifier fallback" in caplog.text
