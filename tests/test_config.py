"""Tests for configuration loading and validation."""

import logging

import pytest
import yaml

from classy_slack_notifier.config import (
    DEFAULT_SYSTEM_PROMPT,
    Config,
    load_config,
)
from classy_slack_notifier.models import FilterAction


class TestConfigDefaults:
    def test_default_config_values(self):
        config = Config()
        assert config.model == "llama3.2:3b"
        assert config.ollama_url == "http://localhost:11434"
        assert config.ollama_timeout == 3
        assert config.urgency_threshold == 3
        assert config.system_prompt == DEFAULT_SYSTEM_PROMPT
        assert config.notification_timeout == 10

    def test_default_rules(self):
        config = Config()
        assert config.rules["self"] is FilterAction.SKIP
        assert config.rules["bots"] is FilterAction.SKIP
        assert config.rules["mentions"] is FilterAction.FORCE_NOTIFY
        assert config.rules["dms"] is FilterAction.FORCE_NOTIFY
        assert config.rules["default"] is FilterAction.CLASSIFY

    def test_default_channels_empty(self):
        config = Config()
        assert config.channels == {}

    def test_default_keywords_empty(self):
        config = Config()
        assert config.keywords == []


class TestLoadConfigValid:
    def test_load_full_config(self, tmp_path):
        config_data = {
            "model": "llama3.1:8b",
            "ollama_url": "http://myhost:11434",
            "ollama_timeout": 5,
            "urgency_threshold": 4,
            "system_prompt": "Custom prompt",
            "rules": {
                "self": "skip",
                "bots": "classify",
                "mentions": "force_notify",
                "dms": "classify",
                "default": "skip",
            },
            "channels": {
                "#incidents": "force_notify",
                "#random": "skip",
            },
            "keywords": [
                {"pattern": "production down", "action": "force_notify"},
                {"pattern": "regex:P[0-1]", "action": "force_notify"},
            ],
            "notification_timeout": 20,
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(str(config_file))

        assert config.model == "llama3.1:8b"
        assert config.ollama_url == "http://myhost:11434"
        assert config.ollama_timeout == 5
        assert config.urgency_threshold == 4
        assert config.system_prompt == "Custom prompt"
        assert config.rules["bots"] is FilterAction.CLASSIFY
        assert config.rules["dms"] is FilterAction.CLASSIFY
        assert config.rules["default"] is FilterAction.SKIP
        assert config.channels["#incidents"] is FilterAction.FORCE_NOTIFY
        assert config.channels["#random"] is FilterAction.SKIP
        assert len(config.keywords) == 2
        assert config.keywords[0]["pattern"] == "production down"
        assert config.keywords[0]["action"] is FilterAction.FORCE_NOTIFY
        assert config.notification_timeout == 20

    def test_defaults_applied_for_missing_fields(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"urgency_threshold": 2}))

        config = load_config(str(config_file))

        assert config.model == "llama3.2:3b"
        assert config.ollama_url == "http://localhost:11434"
        assert config.ollama_timeout == 3
        assert config.system_prompt == DEFAULT_SYSTEM_PROMPT
        assert config.rules["self"] is FilterAction.SKIP
        assert config.rules["default"] is FilterAction.CLASSIFY
        assert config.channels == {}
        assert config.keywords == []
        assert config.notification_timeout == 10
        assert config.urgency_threshold == 2

    def test_partial_rules_merged_with_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"rules": {"bots": "classify"}}))

        config = load_config(str(config_file))

        # Overridden
        assert config.rules["bots"] is FilterAction.CLASSIFY
        # Defaults preserved
        assert config.rules["self"] is FilterAction.SKIP
        assert config.rules["mentions"] is FilterAction.FORCE_NOTIFY
        assert config.rules["dms"] is FilterAction.FORCE_NOTIFY
        assert config.rules["default"] is FilterAction.CLASSIFY

    def test_empty_config_file(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        config = load_config(str(config_file))

        # All defaults
        assert config.model == "llama3.2:3b"
        assert config.urgency_threshold == 3

    def test_config_path_from_env_var(self, tmp_path, monkeypatch):
        config_file = tmp_path / "env_config.yaml"
        config_file.write_text(yaml.dump({"model": "from-env"}))
        monkeypatch.setenv("CLASSY_CONFIG_PATH", str(config_file))

        config = load_config()

        assert config.model == "from-env"

    def test_explicit_path_overrides_env_var(self, tmp_path, monkeypatch):
        env_file = tmp_path / "env_config.yaml"
        env_file.write_text(yaml.dump({"model": "from-env"}))
        monkeypatch.setenv("CLASSY_CONFIG_PATH", str(env_file))

        explicit_file = tmp_path / "explicit.yaml"
        explicit_file.write_text(yaml.dump({"model": "from-arg"}))

        config = load_config(str(explicit_file))

        assert config.model == "from-arg"

    def test_urgency_threshold_boundary_values(self, tmp_path):
        for value in (1, 5):
            config_file = tmp_path / "config.yaml"
            config_file.write_text(yaml.dump({"urgency_threshold": value}))
            config = load_config(str(config_file))
            assert config.urgency_threshold == value


class TestLoadConfigValidationErrors:
    def test_invalid_action_in_rules(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"rules": {"bots": "invalid_action"}}))

        with pytest.raises(ValueError, match="Invalid action 'invalid_action' in rules.bots"):
            load_config(str(config_file))

    def test_invalid_action_in_channels(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"channels": {"#general": "bad_value"}})
        )

        with pytest.raises(ValueError, match="Invalid action 'bad_value' in channels.#general"):
            load_config(str(config_file))

    def test_invalid_action_in_keywords(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"keywords": [{"pattern": "test", "action": "nope"}]})
        )

        with pytest.raises(ValueError, match="Invalid action 'nope'"):
            load_config(str(config_file))

    def test_urgency_threshold_too_low(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"urgency_threshold": 0}))

        with pytest.raises(ValueError, match="urgency_threshold must be between 1 and 5"):
            load_config(str(config_file))

    def test_urgency_threshold_too_high(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"urgency_threshold": 6}))

        with pytest.raises(ValueError, match="urgency_threshold must be between 1 and 5"):
            load_config(str(config_file))

    def test_keyword_missing_pattern(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"keywords": [{"action": "skip"}]})
        )

        with pytest.raises(ValueError, match="keywords\\[0\\] is missing required field 'pattern'"):
            load_config(str(config_file))

    def test_keyword_missing_action(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"keywords": [{"pattern": "test"}]})
        )

        with pytest.raises(ValueError, match="keywords\\[0\\] is missing required field 'action'"):
            load_config(str(config_file))

    def test_ollama_timeout_zero(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"ollama_timeout": 0}))

        with pytest.raises(ValueError, match="ollama_timeout must be positive"):
            load_config(str(config_file))

    def test_ollama_timeout_negative(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"ollama_timeout": -1}))

        with pytest.raises(ValueError, match="ollama_timeout must be positive"):
            load_config(str(config_file))

    def test_config_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_rules_not_a_mapping(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"rules": "not_a_dict"}))

        with pytest.raises(ValueError, match="'rules' must be a mapping"):
            load_config(str(config_file))

    def test_channels_not_a_mapping(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"channels": ["not", "a", "dict"]}))

        with pytest.raises(ValueError, match="'channels' must be a mapping"):
            load_config(str(config_file))

    def test_keywords_not_a_list(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"keywords": "not_a_list"}))

        with pytest.raises(ValueError, match="'keywords' must be a list"):
            load_config(str(config_file))


class TestUnknownKeys:
    def test_unknown_top_level_key_logs_warning(self, tmp_path, caplog):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"unknown_field": "value"}))

        with caplog.at_level(logging.WARNING):
            config = load_config(str(config_file))

        assert "Unknown config key 'unknown_field'" in caplog.text
        # Config should still load successfully
        assert config.model == "llama3.2:3b"

    def test_multiple_unknown_keys_each_warned(self, tmp_path, caplog):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"foo": 1, "bar": 2}))

        with caplog.at_level(logging.WARNING):
            load_config(str(config_file))

        assert "Unknown config key 'foo'" in caplog.text
        assert "Unknown config key 'bar'" in caplog.text
