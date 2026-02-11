"""Tests for the pipeline module (unit tests with mocked dependencies)."""

from unittest.mock import patch

import pytest
import yaml

from aletheia.config import get_config, reset_config


@pytest.fixture(autouse=True)
def _reset_global_config():
    """Reset global config before each test."""
    reset_config()
    yield
    reset_config()


def _make_config(tmp_path):
    """Create a config file for pipeline testing."""
    config_data = {
        "whisper": {"model": "base", "device": "auto"},
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
        "audio": {"sample_rate": 16000, "channels": 1},
        "tts": {"language": "ko", "voice_type": "female", "rate": "+0%", "volume": "+0%"},
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)
    return config_path


@patch("aletheia.pipeline.TextToSpeech")
@patch("aletheia.pipeline.StyleTransformer")
@patch("aletheia.pipeline.Transcriber")
@patch("aletheia.pipeline.ContentFilter")
class TestPipelineProcessText:
    def test_full_pipeline(self, MockFilter, MockTranscriber, MockStyle, MockTTS, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        mock_filter = MockFilter.return_value
        mock_filter.filter.return_value = ("clean text", ["badword"])
        mock_style = MockStyle.return_value
        mock_style.transform.return_value = "polite clean text"

        from aletheia.pipeline import AletheiaPipeline
        pipeline = AletheiaPipeline()
        result = pipeline.process_text("this has badword in it")

        assert result.original_text == "this has badword in it"
        assert result.filtered_text == "clean text"
        assert result.transformed_text == "polite clean text"
        assert result.filtered_words == ["badword"]

    def test_skip_filter(self, MockFilter, MockTranscriber, MockStyle, MockTTS, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        mock_style = MockStyle.return_value
        mock_style.transform.return_value = "transformed"

        from aletheia.pipeline import AletheiaPipeline
        pipeline = AletheiaPipeline()
        result = pipeline.process_text("raw text", skip_filter=True)

        assert result.filtered_text == "raw text"
        assert result.filtered_words == []
        mock_style.transform.assert_called_once()

    def test_skip_transform(self, MockFilter, MockTranscriber, MockStyle, MockTTS, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        mock_filter = MockFilter.return_value
        mock_filter.filter.return_value = ("filtered", [])

        from aletheia.pipeline import AletheiaPipeline
        pipeline = AletheiaPipeline()
        result = pipeline.process_text("input text", skip_transform=True)

        assert result.transformed_text == "filtered"
        MockStyle.return_value.transform.assert_not_called()

    def test_skip_both(self, MockFilter, MockTranscriber, MockStyle, MockTTS, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.pipeline import AletheiaPipeline
        pipeline = AletheiaPipeline()
        result = pipeline.process_text("hello", skip_filter=True, skip_transform=True)

        assert result.original_text == "hello"
        assert result.filtered_text == "hello"
        assert result.transformed_text == "hello"
        assert result.filtered_words == []


@patch("aletheia.pipeline.TextToSpeech")
@patch("aletheia.pipeline.StyleTransformer")
@patch("aletheia.pipeline.Transcriber")
@patch("aletheia.pipeline.ContentFilter")
class TestPipelineCheckServices:
    def test_check_services(self, MockFilter, MockTranscriber, MockStyle, MockTTS, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        MockStyle.return_value.check_connection.return_value = True

        from aletheia.pipeline import AletheiaPipeline
        pipeline = AletheiaPipeline()
        status = pipeline.check_services()
        assert status["ollama"] is True

    def test_check_services_failure(self, MockFilter, MockTranscriber, MockStyle, MockTTS, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        MockStyle.return_value.check_connection.return_value = False

        from aletheia.pipeline import AletheiaPipeline
        pipeline = AletheiaPipeline()
        status = pipeline.check_services()
        assert status["ollama"] is False
