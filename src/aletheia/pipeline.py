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
        original_text = self.transcriber.transcribe(audio_data)
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
                filtered_text, style_prompt, persona
            )

        result = PipelineResult(
            original_text=original_text,
            filtered_text=filtered_text,
            transformed_text=transformed_text,
            filtered_words=filtered_words,
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
        if not AUDIO_AVAILABLE or load_audio_file is None:
            raise RuntimeError("Audio support not available. Install PortAudio: sudo apt install portaudio19-dev")
        audio_data = load_audio_file(str(file_path))
        return self.process_audio(
            audio_data,
            style_prompt=style_prompt,
            persona=persona,
            skip_filter=skip_filter,
            skip_transform=skip_transform,
            speak=speak,
        )

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

        # Step 2: Transform
        if skip_transform:
            transformed_text = filtered_text
        else:
            transformed_text = self.style_transformer.transform(
                filtered_text, style_prompt, persona
            )

        result = PipelineResult(
            original_text=text,
            filtered_text=filtered_text,
            transformed_text=transformed_text,
            filtered_words=filtered_words,
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

        yield from self.style_transformer.transform_stream(filtered_text, style_prompt, persona)

    def check_services(self) -> dict[str, bool]:
        """Check if all required services are available.

        Returns:
            Dictionary with service status
        """
        return {
            "ollama": self.style_transformer.check_connection(),
        }
