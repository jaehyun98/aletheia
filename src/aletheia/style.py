"""Style transformation using Ollama LLM."""

from typing import Generator

import ollama

from .config import get_config


class StyleTransformer:
    """Transforms text style using Ollama LLM."""

    def __init__(self):
        config = get_config()
        ollama_config = config.ollama
        self.model = ollama_config.get("model", "qwen2.5:7b")
        self.base_url = ollama_config.get("base_url", "http://localhost:11434")

        # Load persona presets
        self.personas = config.style.get("personas", {})
        self.default_persona_key = config.style.get("default_persona", "")

        # Get default persona from preset or legacy config
        if self.default_persona_key and self.default_persona_key in self.personas:
            self.persona = self.personas[self.default_persona_key].get("prompt", "")
        else:
            self.persona = config.style.get("persona", "")

        self.default_prompt = config.style.get(
            "default_prompt",
            "다음 텍스트를 정중하고 친절한 톤으로 다시 작성해주세요.",
        )
        self.no_think = ollama_config.get("no_think", False)
        self._client: ollama.Client | None = None

    def get_persona(self, persona_key: str | None = None) -> str:
        """Get persona prompt by key or return default."""
        if not persona_key:
            return self.persona

        # Check if it's a preset key
        if persona_key in self.personas:
            return self.personas[persona_key].get("prompt", "")

        # Otherwise treat it as a custom persona prompt
        return persona_key

    def list_personas(self) -> dict[str, str]:
        """List available persona presets.

        Returns:
            Dictionary of {key: name} for available presets
        """
        return {key: info.get("name", key) for key, info in self.personas.items()}

    def list_models(self) -> list[str]:
        """List available Ollama models.

        Returns:
            List of model names
        """
        try:
            client = self._get_client()
            models = client.list()
            return [m["model"] for m in models.get("models", [])]
        except Exception:
            return []

    def get_current_model(self) -> str:
        """Get current model name."""
        return self.model

    def set_model(self, model: str):
        """Set the current model.

        Args:
            model: Model name to use
        """
        self.model = model

    def _get_client(self) -> ollama.Client:
        """Get or create Ollama client."""
        if self._client is None:
            self._client = ollama.Client(host=self.base_url)
        return self._client

    def _build_messages(
        self, text: str, style_prompt: str | None = None, persona: str | None = None
    ) -> list[dict]:
        """Build chat messages with optional persona.

        Args:
            text: Input text to process
            style_prompt: Custom style prompt
            persona: Persona key (preset name) or custom persona prompt
        """
        messages = []

        # Get persona prompt (handles both preset keys and custom prompts)
        active_persona = self.get_persona(persona) if persona else self.persona
        if active_persona and active_persona.strip():
            messages.append({"role": "system", "content": active_persona.strip()})

        # Add few-shot examples if available
        persona_key = persona or self.default_persona_key
        if persona_key and persona_key in self.personas:
            examples = self.personas[persona_key].get("examples", [])
            for ex in examples:
                if "input" in ex and "output" in ex:
                    messages.append({"role": "user", "content": ex["input"]})
                    messages.append({"role": "assistant", "content": ex["output"]})

        # Add user message
        # If persona is set but no custom style prompt, use a simpler instruction
        if active_persona and not style_prompt:
            prompt = "다음 텍스트에 자연스럽게 응답해주세요. 추가 설명 없이 응답만 출력하세요."
        else:
            prompt = style_prompt or self.default_prompt

        full_prompt = f"{prompt}\n\n원본 텍스트: {text}"
        if self.no_think:
            full_prompt += " /no_think"
        messages.append({"role": "user", "content": full_prompt})

        return messages

    def transform(
        self, text: str, style_prompt: str | None = None, persona: str | None = None
    ) -> str:
        """Transform text style using LLM.

        Args:
            text: Input text to transform
            style_prompt: Custom style prompt. Uses default if None.
            persona: Custom persona (system prompt). Uses config if None.

        Returns:
            Transformed text
        """
        if not text.strip():
            return text

        client = self._get_client()
        response = client.chat(
            model=self.model,
            messages=self._build_messages(text, style_prompt, persona),
        )

        return response["message"]["content"].strip()

    def transform_stream(
        self, text: str, style_prompt: str | None = None, persona: str | None = None
    ) -> Generator[str, None, None]:
        """Transform text style with streaming output.

        Args:
            text: Input text to transform
            style_prompt: Custom style prompt. Uses default if None.
            persona: Custom persona (system prompt). Uses config if None.

        Yields:
            Chunks of transformed text
        """
        if not text.strip():
            yield text
            return

        client = self._get_client()
        stream = client.chat(
            model=self.model,
            messages=self._build_messages(text, style_prompt, persona),
            stream=True,
        )

        for chunk in stream:
            content = chunk["message"]["content"]
            if content:
                yield content

    def check_connection(self) -> bool:
        """Check if Ollama server is accessible and model is available."""
        try:
            client = self._get_client()
            models = client.list()
            available_models = [m["model"] for m in models.get("models", [])]

            # Check if our model is available (handle tags like :latest)
            model_base = self.model.split(":")[0]
            for available in available_models:
                if available.startswith(model_base):
                    return True

            print(f"Warning: Model '{self.model}' not found. Available: {available_models}")
            print(f"Run: ollama pull {self.model}")
            return False
        except Exception as e:
            print(f"Error connecting to Ollama: {e}")
            print(f"Make sure Ollama is running at {self.base_url}")
            return False
