"""Tests for style transformer (unit tests with mocked Ollama)."""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from aletheia.config import get_config, reset_config


@pytest.fixture(autouse=True)
def _reset_global_config():
    """Reset global config before each test."""
    reset_config()
    yield
    reset_config()


def _make_config(tmp_path, **overrides):
    """Create a config file for testing."""
    config_data = {
        "whisper": {"model": "base", "device": "auto"},
        "ollama": {
            "model": "test-model:latest",
            "base_url": "http://localhost:11434",
        },
        "filter": {"enabled": False, "action": "mask", "replacement": "***", "patterns": []},
        "style": {
            "default_persona": "assistant",
            "personas": {
                "assistant": {
                    "name": "Test Assistant",
                    "prompt": "You are a helpful assistant.",
                },
                "casual": {
                    "name": "Casual Friend",
                    "prompt": "You are a casual friend.",
                },
            },
            "default_prompt": "Rewrite politely.",
        },
        "audio": {"sample_rate": 16000, "channels": 1},
    }
    config_data.update(overrides)
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)
    return config_path


class TestStyleTransformer:
    def test_init_loads_config(self, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        assert st.model == "test-model:latest"
        assert st.base_url == "http://localhost:11434"

    def test_list_personas(self, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        personas = st.list_personas()
        assert "assistant" in personas
        assert "casual" in personas
        assert personas["assistant"] == "Test Assistant"

    def test_get_persona_by_key(self, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        assert "helpful assistant" in st.get_persona("assistant")
        assert "casual friend" in st.get_persona("casual")

    def test_get_persona_custom_string(self, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        custom = "You are a pirate."
        assert st.get_persona(custom) == custom

    def test_get_current_model(self, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        assert st.get_current_model() == "test-model:latest"

    def test_set_model(self, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        st.set_model("new-model:7b")
        assert st.get_current_model() == "new-model:7b"

    @patch("aletheia.style.ollama.Client")
    def test_transform(self, mock_client_cls, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "Transformed text"}
        }
        mock_client_cls.return_value = mock_client

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        result = st.transform("hello world")
        assert result == "Transformed text"
        mock_client.chat.assert_called_once()

    @patch("aletheia.style.ollama.Client")
    def test_transform_empty_text(self, mock_client_cls, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        result = st.transform("   ")
        assert result == "   "
        mock_client_cls.return_value.chat.assert_not_called()

    @patch("aletheia.style.ollama.Client")
    def test_transform_stream(self, mock_client_cls, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        chunks = [
            {"message": {"content": "Hello"}},
            {"message": {"content": " world"}},
        ]
        mock_client = MagicMock()
        mock_client.chat.return_value = iter(chunks)
        mock_client_cls.return_value = mock_client

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        result = list(st.transform_stream("test input"))
        assert result == ["Hello", " world"]

    @patch("aletheia.style.ollama.Client")
    def test_check_connection_success(self, mock_client_cls, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        mock_client = MagicMock()
        mock_client.list.return_value = {
            "models": [{"model": "test-model:latest"}]
        }
        mock_client_cls.return_value = mock_client

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        assert st.check_connection() is True

    @patch("aletheia.style.ollama.Client")
    def test_check_connection_model_missing(self, mock_client_cls, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        mock_client = MagicMock()
        mock_client.list.return_value = {
            "models": [{"model": "other-model:latest"}]
        }
        mock_client_cls.return_value = mock_client

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        assert st.check_connection() is False

    @patch("aletheia.style.ollama.Client")
    def test_check_connection_error(self, mock_client_cls, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        mock_client = MagicMock()
        mock_client.list.side_effect = Exception("Connection refused")
        mock_client_cls.return_value = mock_client

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        assert st.check_connection() is False

    def test_build_messages_with_persona(self, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        messages = st._build_messages("hello", persona="assistant")
        assert messages[0]["role"] == "system"
        assert "helpful assistant" in messages[0]["content"]
        assert messages[1]["role"] == "user"

    def test_build_messages_with_custom_prompt(self, tmp_path):
        config_path = _make_config(tmp_path)
        get_config(config_path)

        from aletheia.style import StyleTransformer
        st = StyleTransformer()
        messages = st._build_messages("hello", style_prompt="Be formal.")
        user_msg = messages[-1]["content"]
        assert "Be formal." in user_msg
        assert "hello" in user_msg
