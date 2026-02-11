"""Configuration management for Aletheia."""

from pathlib import Path
from typing import Any

import yaml


def _find_config_path() -> Path:
    """Find the config file path."""
    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        return cwd_config
    return Path(__file__).parent.parent.parent / "config.yaml"


CONFIG_PATH = _find_config_path()


class Config:
    """Configuration manager that loads settings from YAML file."""

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            # Try current directory first, then package directory
            cwd_config = Path.cwd() / "config.yaml"
            if cwd_config.exists():
                config_path = cwd_config
            else:
                # Fallback to package root (for installed packages)
                config_path = Path(__file__).parent.parent.parent / "config.yaml"
        self.config_path = Path(config_path)
        self._config: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load configuration from YAML file."""
        if self.config_path.exists():
            with open(self.config_path, encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = self._default_config()

    def _default_config(self) -> dict[str, Any]:
        """Return default configuration."""
        return {
            "whisper": {
                "model": "base",
                "device": "auto",
            },
            "ollama": {
                "model": "qwen2.5:7b",
                "base_url": "http://localhost:11434",
            },
            "filter": {
                "enabled": True,
                "action": "mask",
                "replacement": "***",
                "patterns": [],
            },
            "style": {
                "default_prompt": "다음 텍스트를 정중하고 친절한 톤으로 다시 작성해주세요.",
            },
            "audio": {
                "sample_rate": 16000,
                "channels": 1,
                "silence_threshold": 0.01,
                "silence_duration": 1.5,
                "max_duration": 30,
            },
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by dot-notation key."""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    @property
    def whisper(self) -> dict[str, Any]:
        """Get Whisper configuration."""
        return self._config.get("whisper", {})

    @property
    def ollama(self) -> dict[str, Any]:
        """Get Ollama configuration."""
        return self._config.get("ollama", {})

    @property
    def filter(self) -> dict[str, Any]:
        """Get filter configuration."""
        return self._config.get("filter", {})

    @property
    def style(self) -> dict[str, Any]:
        """Get style configuration."""
        return self._config.get("style", {})

    @property
    def audio(self) -> dict[str, Any]:
        """Get audio configuration."""
        return self._config.get("audio", {})


# Global config instance
_config: Config | None = None


def get_config(config_path: str | Path | None = None) -> Config:
    """Get or create the global configuration instance."""
    global _config
    if _config is None or config_path is not None:
        _config = Config(config_path)
    return _config


def reset_config() -> None:
    """Reset the global configuration instance to force reload."""
    global _config
    _config = None


# Add cache_clear method to get_config for compatibility
get_config.cache_clear = reset_config
