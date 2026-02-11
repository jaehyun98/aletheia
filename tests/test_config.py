"""Tests for configuration management."""

import os

import pytest
import yaml

from aletheia.config import Config, get_config, reset_config


@pytest.fixture(autouse=True)
def _reset_global_config():
    """Reset global config before each test."""
    reset_config()
    yield
    reset_config()


@pytest.fixture
def sample_config_file(tmp_path):
    """Create a temporary config file."""
    config_data = {
        "whisper": {"model": "tiny", "device": "cpu"},
        "ollama": {
            "model": "test-model:latest",
            "base_url": "http://localhost:11434",
        },
        "filter": {
            "enabled": True,
            "action": "mask",
            "replacement": "***",
            "patterns": ["badword"],
        },
        "style": {
            "default_persona": "assistant",
            "personas": {
                "assistant": {
                    "name": "Test Assistant",
                    "prompt": "You are a test assistant.",
                }
            },
            "default_prompt": "Rewrite politely.",
        },
        "audio": {
            "sample_rate": 16000,
            "channels": 1,
        },
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)
    return config_path


class TestConfig:
    def test_load_from_file(self, sample_config_file):
        config = Config(sample_config_file)
        assert config.whisper["model"] == "tiny"
        assert config.ollama["model"] == "test-model:latest"

    def test_default_config_when_file_missing(self, tmp_path):
        config = Config(tmp_path / "nonexistent.yaml")
        assert config.whisper["model"] == "base"
        assert config.ollama["model"] == "exaone3.5:7.8b"

    def test_get_dot_notation(self, sample_config_file):
        config = Config(sample_config_file)
        assert config.get("whisper.model") == "tiny"
        assert config.get("ollama.base_url") == "http://localhost:11434"

    def test_get_returns_default_for_missing_key(self, sample_config_file):
        config = Config(sample_config_file)
        assert config.get("nonexistent.key", "fallback") == "fallback"

    def test_get_returns_default_for_partial_path(self, sample_config_file):
        config = Config(sample_config_file)
        assert config.get("whisper.nonexistent", 42) == 42

    def test_section_properties(self, sample_config_file):
        config = Config(sample_config_file)
        assert isinstance(config.whisper, dict)
        assert isinstance(config.ollama, dict)
        assert isinstance(config.filter, dict)
        assert isinstance(config.style, dict)
        assert isinstance(config.audio, dict)

    def test_filter_config(self, sample_config_file):
        config = Config(sample_config_file)
        assert config.filter["enabled"] is True
        assert config.filter["action"] == "mask"
        assert "badword" in config.filter["patterns"]

    def test_style_config(self, sample_config_file):
        config = Config(sample_config_file)
        assert config.style["default_persona"] == "assistant"
        assert "assistant" in config.style["personas"]


class TestGetConfig:
    def test_returns_singleton(self, sample_config_file):
        c1 = get_config(sample_config_file)
        c2 = get_config()
        assert c1 is c2

    def test_reset_config(self, sample_config_file):
        c1 = get_config(sample_config_file)
        reset_config()
        c2 = get_config(sample_config_file)
        assert c1 is not c2

    def test_new_path_creates_new_instance(self, sample_config_file, tmp_path):
        c1 = get_config(sample_config_file)
        c2 = get_config(tmp_path / "other.yaml")
        assert c1 is not c2


class TestEnvOverrides:
    def test_ollama_base_url_override(self, sample_config_file, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://remote:11434")
        config = Config(sample_config_file)
        assert config.ollama["base_url"] == "http://remote:11434"

    def test_ollama_model_override(self, sample_config_file, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3:8b")
        config = Config(sample_config_file)
        assert config.ollama["model"] == "llama3:8b"

    def test_whisper_model_override(self, sample_config_file, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL", "large-v3")
        config = Config(sample_config_file)
        assert config.whisper["model"] == "large-v3"

    def test_whisper_device_override(self, sample_config_file, monkeypatch):
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        config = Config(sample_config_file)
        assert config.whisper["device"] == "cuda"

    def test_env_overrides_default_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://custom:9999")
        config = Config(tmp_path / "nonexistent.yaml")
        assert config.ollama["base_url"] == "http://custom:9999"

    def test_no_override_when_env_not_set(self, sample_config_file):
        # Ensure env vars are not set
        for var in ["OLLAMA_BASE_URL", "OLLAMA_MODEL", "WHISPER_MODEL", "WHISPER_DEVICE"]:
            os.environ.pop(var, None)
        config = Config(sample_config_file)
        assert config.ollama["base_url"] == "http://localhost:11434"
        assert config.ollama["model"] == "test-model:latest"
