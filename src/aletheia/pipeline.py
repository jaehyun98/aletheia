"""Integrated pipeline combining all components."""

from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from .config import Config, get_config
from .filter import ContentFilter
from .style import StyleTransformer
from .transcribe import Transcriber
from .tts import TextToSpeech

# Audio imports are optional (requires PortAudio)
try:
    from .audio import AudioCapture, load_audio_file
    AUDIO_AVAILABLE = True
except OSError:
    AUDIO_AVAILABLE = False
    AudioCapture = None
    load_audio_file = None


def detect_text_language(text: str) -> str:
    """Detect language from text using Unicode character ranges.

    Returns 'ko' if Korean characters are present, otherwise 'en'.
    """
    for ch in text:
        if '\uAC00' <= ch <= '\uD7A3' or '\u3131' <= ch <= '\u318E':
            return "ko"
    return "en"


@dataclass
class PipelineResult:
    """Result from pipeline processing."""

    original_text: str
    filtered_text: str
    transformed_text: str
    filtered_words: list[str]
    language: str | None = None


class AletheiaPipeline:
    """Main pipeline integrating audio capture, STT, filtering, and style transformation."""

    def __init__(self, config_path: str | Path | None = None):
        if config_path:
            get_config(config_path)

        self.audio_capture = AudioCapture() if AUDIO_AVAILABLE else None
        self.transcriber = Transcriber()
        self.content_filter = ContentFilter()
        self.style_transformer = StyleTransformer()
        self.tts = TextToSpeech()

    def process_audio(
        self,
        audio_data: bytes,
        style_prompt: str | None = None,
        persona: str | None = None,
        skip_filter: bool = False,
        skip_transform: bool = False,
        speak: bool = False,
    ) -> PipelineResult:
        """Process audio data through the full pipeline.

        Args:
            audio_data: WAV audio bytes
            style_prompt: Custom style prompt for transformation
            persona: Custom persona (system prompt) for LLM
            skip_filter: Skip content filtering step
            skip_transform: Skip style transformation step
            speak: Speak the transformed text using TTS

        Returns:
            PipelineResult with all processing stages
        """
        # Step 1: Transcribe
        original_text, detected_lang = self.transcriber.transcribe(audio_data)
        print(f"Transcribed: {original_text}")

        # Step 2: Filter
        if skip_filter:
            filtered_text = original_text
            filtered_words = []
        else:
            filtered_text, filtered_words = self.content_filter.filter(original_text)
            if filtered_words:
                print(f"Filtered words: {filtered_words}")

        # Step 3: Transform
        if skip_transform:
            transformed_text = filtered_text
        else:
            print("Transforming style...")
            transformed_text = self.style_transformer.transform(
                filtered_text, style_prompt, persona, language=detected_lang
            )

        result = PipelineResult(
            original_text=original_text,
            filtered_text=filtered_text,
            transformed_text=transformed_text,
            filtered_words=filtered_words,
            language=detected_lang,
        )

        # Step 4: Speak (optional)
        if speak and transformed_text:
            self.tts.speak(transformed_text)

        return result

    def process_file(
        self,
        file_path: str | Path,
        style_prompt: str | None = None,
        persona: str | None = None,
        skip_filter: bool = False,
        skip_transform: bool = False,
        speak: bool = False,
    ) -> PipelineResult:
        """Process an audio file through the pipeline.

        Args:
            file_path: Path to audio file
            style_prompt: Custom style prompt for transformation
            persona: Custom persona (system prompt) for LLM
            skip_filter: Skip content filtering step
            skip_transform: Skip style transformation step
            speak: Speak the transformed text using TTS

        Returns:
            PipelineResult with all processing stages
        """
        file_path = Path(file_path)

        # Step 1: Transcribe directly from file (avoids temp-file roundtrip)
        original_text, detected_lang = self.transcriber.transcribe_file(file_path)
        print(f"Transcribed: {original_text}")

        # Step 2: Filter
        if skip_filter:
            filtered_text = original_text
            filtered_words = []
        else:
            filtered_text, filtered_words = self.content_filter.filter(original_text)
            if filtered_words:
                print(f"Filtered words: {filtered_words}")

        # Step 3: Transform
        if skip_transform:
            transformed_text = filtered_text
        else:
            print("Transforming style...")
            transformed_text = self.style_transformer.transform(
                filtered_text, style_prompt, persona, language=detected_lang
            )

        result = PipelineResult(
            original_text=original_text,
            filtered_text=filtered_text,
            transformed_text=transformed_text,
            filtered_words=filtered_words,
            language=detected_lang,
        )

        # Step 4: Speak (optional)
        if speak and transformed_text:
            self.tts.speak(transformed_text)

        return result

    def process_text(
        self,
        text: str,
        style_prompt: str | None = None,
        persona: str | None = None,
        skip_filter: bool = False,
        skip_transform: bool = False,
        speak: bool = False,
    ) -> PipelineResult:
        """Process text through filter and transformation (no STT).

        Args:
            text: Input text
            style_prompt: Custom style prompt for transformation
            persona: Custom persona (system prompt) for LLM
            skip_filter: Skip content filtering step
            skip_transform: Skip style transformation step
            speak: Speak the transformed text using TTS

        Returns:
            PipelineResult with processing stages
        """
        # Step 1: Filter
        if skip_filter:
            filtered_text = text
            filtered_words = []
        else:
            filtered_text, filtered_words = self.content_filter.filter(text)

        # Detect language from text
        detected_lang = detect_text_language(filtered_text)

        # Step 2: Transform
        if skip_transform:
            transformed_text = filtered_text
        else:
            transformed_text = self.style_transformer.transform(
                filtered_text, style_prompt, persona, language=detected_lang
            )

        result = PipelineResult(
            original_text=text,
            filtered_text=filtered_text,
            transformed_text=transformed_text,
            filtered_words=filtered_words,
            language=detected_lang,
        )

        # Step 3: Speak (optional)
        if speak and transformed_text:
            self.tts.speak(transformed_text)

        return result

    def process_microphone(
        self,
        style_prompt: str | None = None,
        persona: str | None = None,
        skip_filter: bool = False,
        skip_transform: bool = False,
        speak: bool = False,
    ) -> PipelineResult:
        """Record from microphone and process through the pipeline.

        Args:
            style_prompt: Custom style prompt for transformation
            persona: Custom persona (system prompt) for LLM
            skip_filter: Skip content filtering step
            skip_transform: Skip style transformation step
            speak: Speak the transformed text using TTS

        Returns:
            PipelineResult with all processing stages
        """
        if self.audio_capture is None:
            raise RuntimeError("Audio support not available. Install PortAudio: sudo apt install portaudio19-dev")
        audio_data = self.audio_capture.record_until_silence()
        if not audio_data:
            return PipelineResult(
                original_text="",
                filtered_text="",
                transformed_text="",
                filtered_words=[],
            )

        return self.process_audio(
            audio_data,
            style_prompt=style_prompt,
            persona=persona,
            skip_filter=skip_filter,
            skip_transform=skip_transform,
            speak=speak,
        )

    def process_stream(
        self,
        text: str,
        style_prompt: str | None = None,
        persona: str | None = None,
        skip_filter: bool = False,
    ) -> Generator[str, None, None]:
        """Process text with streaming transformation output.

        Args:
            text: Input text
            style_prompt: Custom style prompt
            persona: Custom persona (system prompt) for LLM
            skip_filter: Skip content filtering

        Yields:
            Chunks of transformed text
        """
        if skip_filter:
            filtered_text = text
        else:
            filtered_text, _ = self.content_filter.filter(text)

        detected_lang = detect_text_language(filtered_text)
        yield from self.style_transformer.transform_stream(filtered_text, style_prompt, persona, language=detected_lang)

    def check_services(self) -> dict[str, bool]:
        """Check if all required services are available.

        Returns:
            Dictionary with service status
        """
        return {
            "ollama": self.style_transformer.check_connection(),
        }
