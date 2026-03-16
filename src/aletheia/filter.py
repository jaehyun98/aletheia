"""Content filtering for inappropriate expressions."""

import re
from typing import Literal

from .config import get_config


class ContentFilter:
    """Filters inappropriate content from text."""

    def __init__(self):
        config = get_config()
        filter_config = config.filter
        self.enabled = filter_config.get("enabled", True)
        self.action: Literal["mask", "remove", "replace"] = filter_config.get(
            "action", "mask"
        )
        self.replacement = filter_config.get("replacement", "***")
        self.patterns: list[str] = filter_config.get("patterns", [])
        self._compiled_patterns: list[re.Pattern] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficient matching."""
        self._compiled_patterns = []
        for pattern in self.patterns:
            try:
                # Escape special regex characters and make case-insensitive
                escaped = re.escape(pattern)
                self._compiled_patterns.append(
                    re.compile(escaped, re.IGNORECASE | re.UNICODE)
                )
            except re.error:
                print(f"Warning: Invalid filter pattern: {pattern}")

    def filter(self, text: str) -> tuple[str, list[str]]:
        """Filter inappropriate content from text.

        Args:
            text: Input text to filter

        Returns:
            Tuple of (filtered_text, list_of_filtered_words)
        """
        if not self.enabled or not text:
            return text, []

        filtered_words: list[str] = []
        result = text

        for pattern in self._compiled_patterns:
            matches = pattern.findall(result)
            if matches:
                filtered_words.extend(matches)

                if self.action == "mask":
                    # Replace with asterisks matching length
                    result = pattern.sub(
                        lambda m: "*" * len(m.group(0)), result
                    )
                elif self.action == "remove":
                    result = pattern.sub("", result)
                elif self.action == "replace":
                    result = pattern.sub(self.replacement, result)

        # Clean up multiple spaces
        result = re.sub(r"\s+", " ", result).strip()

        return result, filtered_words

    def add_pattern(self, pattern: str) -> None:
        """Add a new filter pattern."""
        if pattern not in self.patterns:
            self.patterns.append(pattern)
            try:
                escaped = re.escape(pattern)
                self._compiled_patterns.append(
                    re.compile(escaped, re.IGNORECASE | re.UNICODE)
                )
            except re.error:
                print(f"Warning: Invalid filter pattern: {pattern}")

    def remove_pattern(self, pattern: str) -> None:
        """Remove a filter pattern."""
        if pattern in self.patterns:
            idx = self.patterns.index(pattern)
            self.patterns.pop(idx)
            self._compiled_patterns.pop(idx)

    def check(self, text: str) -> bool:
        """Check if text contains any filtered content.

        Returns:
            True if text contains filtered content
        """
        if not self.enabled or not text:
            return False

        for pattern in self._compiled_patterns:
            if pattern.search(text):
                return True
        return False
