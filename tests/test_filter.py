"""Tests for content filtering."""


import pytest
import yaml

from aletheia.config import reset_config


@pytest.fixture(autouse=True)
def _reset_global_config():
    """Reset global config before each test."""
    reset_config()
    yield
    reset_config()


def _make_config(tmp_path, filter_config):
    """Helper to create a config file with specific filter settings."""
    config_data = {
        "whisper": {"model": "base", "device": "auto"},
        "ollama": {"model": "test:latest", "base_url": "http://localhost:11434"},
        "filter": filter_config,
        "style": {"default_prompt": "test"},
        "audio": {"sample_rate": 16000, "channels": 1},
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)
    return config_path


class TestContentFilter:
    def test_mask_action(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": True,
            "action": "mask",
            "replacement": "***",
            "patterns": ["fuck", "shit"],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        result, words = f.filter("what the fuck is this shit")
        assert "fuck" not in result
        assert "shit" not in result
        assert "****" in result  # "fuck" -> 4 asterisks
        assert len(words) == 2

    def test_remove_action(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": True,
            "action": "remove",
            "replacement": "***",
            "patterns": ["badword"],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        result, words = f.filter("this is a badword test")
        assert "badword" not in result
        assert words == ["badword"]

    def test_replace_action(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": True,
            "action": "replace",
            "replacement": "[FILTERED]",
            "patterns": ["badword"],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        result, words = f.filter("this is a badword test")
        assert "[FILTERED]" in result
        assert "badword" not in result

    def test_disabled_filter(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": False,
            "action": "mask",
            "replacement": "***",
            "patterns": ["badword"],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        result, words = f.filter("this is a badword test")
        assert "badword" in result
        assert words == []

    def test_empty_text(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": True,
            "action": "mask",
            "replacement": "***",
            "patterns": ["badword"],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        result, words = f.filter("")
        assert result == ""
        assert words == []

    def test_case_insensitive(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": True,
            "action": "mask",
            "replacement": "***",
            "patterns": ["badword"],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        result, words = f.filter("This is BADWORD and BadWord")
        assert "BADWORD" not in result
        assert "BadWord" not in result
        assert len(words) == 2

    def test_add_pattern(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": True,
            "action": "mask",
            "replacement": "***",
            "patterns": [],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        result, words = f.filter("newbad word")
        assert words == []

        f.add_pattern("newbad")
        result, words = f.filter("newbad word")
        assert "newbad" not in result
        assert len(words) == 1

    def test_remove_pattern(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": True,
            "action": "mask",
            "replacement": "***",
            "patterns": ["badword"],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        f.remove_pattern("badword")
        result, words = f.filter("this is a badword test")
        assert "badword" in result
        assert words == []

    def test_check_method(self, tmp_path):
        from aletheia.config import get_config
        config_path = _make_config(tmp_path, {
            "enabled": True,
            "action": "mask",
            "replacement": "***",
            "patterns": ["badword"],
        })
        get_config(config_path)

        from aletheia.filter import ContentFilter
        f = ContentFilter()
        assert f.check("contains badword") is True
        assert f.check("clean text") is False
        assert f.check("") is False
