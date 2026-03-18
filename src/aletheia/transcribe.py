"""Speech-to-Text transcription using faster-whisper."""

import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

from .config import get_config


class Transcriber:
    """Transcribes audio to text using faster-whisper."""

    def __init__(self):
        config = get_config()
        self.model_name = config.whisper.get("model", "base")
        self.device = config.whisper.get("device", "auto")
        self._model: WhisperModel | None = None

    def _get_device(self) -> tuple[str, str]:
        """Determine the device and compute type to use."""
        if self.device == "auto":
            try:
                import torch

                if torch.cuda.is_available():
                    return "cuda", "float16"
            except ImportError:
                pass
            return "cpu", "int8"
        elif self.device == "cuda":
            return "cuda", "float16"
        else:
            return "cpu", "int8"

    def _load_model(self) -> WhisperModel:
        """Load the Whisper model lazily."""
        if self._model is None:
            device, compute_type = self._get_device()
            print(f"Loading Whisper model '{self.model_name}' on {device}...")
            self._model = WhisperModel(
                self.model_name, device=device, compute_type=compute_type
            )
        return self._model

    def transcribe(self, audio_data: bytes, language: str | None = None) -> tuple[str, str | None]:
        """Transcribe audio bytes to text.

        Args:
            audio_data: WAV audio data as bytes
            language: Language code (e.g., 'ko', 'en'). Auto-detected if None.

        Returns:
            Tuple of (transcribed text, detected language code or None)
        """
        model = self._load_model()

        # Write audio to temporary file (faster-whisper requires file path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        try:
            segments, info = model.transcribe(
                tmp_path,
                language=language,
                beam_size=5,
                vad_filter=True,
            )

            # Combine all segments
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())

            text = " ".join(text_parts)
            detected = info.language if info.language else None

            if detected:
                print(f"Detected language: {detected} (probability: {info.language_probability:.2f})")

            return text, detected
        finally:
            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)

    def transcribe_file(self, file_path: str | Path, language: str | None = None) -> tuple[str, str | None]:
        """Transcribe an audio file to text.

        Args:
            file_path: Path to the audio file
            language: Language code (e.g., 'ko', 'en'). Auto-detected if None.

        Returns:
            Tuple of (transcribed text, detected language code or None)
        """
        model = self._load_model()

        segments, info = model.transcribe(
            str(file_path),
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())

        text = " ".join(text_parts)
        detected = info.language if info.language else None

        if detected:
            print(f"Detected language: {detected} (probability: {info.language_probability:.2f})")

        return text, detected
