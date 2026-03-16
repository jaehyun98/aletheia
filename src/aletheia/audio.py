"""Audio capture module with Voice Activity Detection."""

import io
import queue
import wave
from typing import Generator

import numpy as np
import sounddevice as sd

from .config import get_config


class AudioCapture:
    """Captures audio from microphone with VAD-based recording."""

    def __init__(self):
        config = get_config()
        self.sample_rate = config.audio.get("sample_rate", 16000)
        self.channels = config.audio.get("channels", 1)
        self.silence_threshold = config.audio.get("silence_threshold", 0.01)
        self.silence_duration = config.audio.get("silence_duration", 1.5)
        self.max_duration = config.audio.get("max_duration", 30)
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: dict,
        status: sd.CallbackFlags,
    ) -> None:
        """Callback for audio stream."""
        if status:
            print(f"Audio status: {status}")
        self._audio_queue.put(indata.copy())

    def record_until_silence(self) -> bytes:
        """Record audio until silence is detected or max duration reached."""
        audio_chunks: list[np.ndarray] = []
        silence_samples = 0
        silence_threshold_samples = int(self.silence_duration * self.sample_rate)
        max_samples = int(self.max_duration * self.sample_rate)
        total_samples = 0
        started_speaking = False

        print("Listening... (speak now)")

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=np.float32,
            callback=self._audio_callback,
            blocksize=1024,
        ):
            while total_samples < max_samples:
                try:
                    chunk = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                audio_chunks.append(chunk)
                total_samples += len(chunk)

                # Check if this chunk contains speech
                amplitude = np.abs(chunk).mean()
                is_silence = amplitude < self.silence_threshold

                if not is_silence:
                    started_speaking = True
                    silence_samples = 0
                elif started_speaking:
                    silence_samples += len(chunk)
                    if silence_samples >= silence_threshold_samples:
                        print("Silence detected, stopping recording.")
                        break

        if not audio_chunks:
            return b""

        # Concatenate all chunks
        audio_data = np.concatenate(audio_chunks, axis=0)

        # Convert to WAV bytes
        return self._to_wav_bytes(audio_data)

    def _to_wav_bytes(self, audio_data: np.ndarray) -> bytes:
        """Convert numpy audio data to WAV bytes."""
        # Normalize and convert to int16
        audio_data = audio_data.flatten()
        audio_int16 = (audio_data * 32767).astype(np.int16)

        # Write to WAV buffer
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int16.tobytes())

        return buffer.getvalue()

    def record_stream(self) -> Generator[bytes, None, None]:
        """Stream audio chunks for real-time processing."""
        print("Streaming audio... (Ctrl+C to stop)")

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=np.float32,
            callback=self._audio_callback,
            blocksize=4096,
        ):
            try:
                while True:
                    try:
                        chunk = self._audio_queue.get(timeout=0.1)
                        yield self._to_wav_bytes(chunk)
                    except queue.Empty:
                        continue
            except KeyboardInterrupt:
                print("\nStopping audio stream.")


def load_audio_file(file_path: str) -> bytes:
    """Load an audio file and return as bytes."""
    with open(file_path, "rb") as f:
        return f.read()
