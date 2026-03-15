"""Text-to-Speech module using Edge TTS."""

import asyncio
import tempfile
from pathlib import Path

import edge_tts

from .config import get_config


class TextToSpeech:
    """Converts text to speech using Microsoft Edge TTS."""

    # Korean voices
    KOREAN_VOICES = {
        "female": "ko-KR-SunHiNeural",
        "male": "ko-KR-InJoonNeural",
    }

    # English voices
    ENGLISH_VOICES = {
        "female": "en-US-JennyNeural",
        "male": "en-US-GuyNeural",
    }

    def __init__(self, voice: str | None = None, language: str = "ko"):
        config = get_config()
        tts_config = config.get("tts", {})

        self.language = tts_config.get("language", language)
        self.voice_type = tts_config.get("voice_type", "female")
        self.rate = tts_config.get("rate", "+0%")
        self.volume = tts_config.get("volume", "+0%")

        if voice:
            self.voice = voice
        elif self.language == "ko":
            self.voice = self.KOREAN_VOICES.get(self.voice_type, self.KOREAN_VOICES["female"])
        else:
            self.voice = self.ENGLISH_VOICES.get(self.voice_type, self.ENGLISH_VOICES["female"])

    async def _synthesize(self, text: str) -> bytes:
        """Synthesize text to audio bytes."""
        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=self.rate,
            volume=self.volume,
        )

        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]

        return audio_data

    def synthesize(self, text: str) -> bytes:
        """Synthesize text to MP3 audio bytes.

        Args:
            text: Text to convert to speech

        Returns:
            MP3 audio data as bytes
        """
        if not text.strip():
            return b""

        return asyncio.run(self._synthesize(text))

    def synthesize_to_file(self, text: str, output_path: str | Path) -> Path:
        """Synthesize text and save to file.

        Args:
            text: Text to convert to speech
            output_path: Path to save audio file

        Returns:
            Path to saved file
        """
        audio_data = self.synthesize(text)
        output_path = Path(output_path)

        with open(output_path, "wb") as f:
            f.write(audio_data)

        return output_path

    def speak(self, text: str) -> None:
        """Synthesize and play text immediately.

        Args:
            text: Text to speak
        """
        if not text.strip():
            return

        audio_data = self.synthesize(text)

        # Save to temp file and play
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        try:
            self._play_audio(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _play_audio(self, file_path: str) -> None:
        """Play audio file using available player."""
        import platform
        import subprocess
        import shutil

        system = platform.system()

        # Windows native
        if system == "Windows":
            try:
                import winsound
                # winsound only supports .wav; for .mp3 use start command
                if file_path.lower().endswith(".wav"):
                    winsound.PlaySound(file_path, winsound.SND_FILENAME)
                    return
            except Exception:
                pass
            # Fallback: open with default media player
            try:
                subprocess.run(
                    ["cmd", "/c", "start", "/wait", "", file_path],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception:
                pass
            print(f"Warning: Could not play audio. File saved to {file_path}")
            return

        # Linux / macOS
        players = [
            ["mpv", "--no-video", file_path],
            ["ffplay", "-nodisp", "-autoexit", file_path],
            ["aplay", file_path],
            ["paplay", file_path],
        ]

        for player_cmd in players:
            if shutil.which(player_cmd[0]):
                try:
                    subprocess.run(
                        player_cmd,
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except subprocess.CalledProcessError:
                    continue

        # WSL: Try using Windows to play audio
        try:
            with open("/proc/version") as f:
                if "microsoft" in f.read().lower():
                    result = subprocess.run(
                        ["wslpath", "-w", file_path],
                        capture_output=True, text=True,
                    )
                    win_path = result.stdout.strip()
                    subprocess.run(
                        ["cmd.exe", "/c", "start", "/wait", "", win_path],
                        capture_output=True,
                    )
                    return
        except (FileNotFoundError, OSError):
            pass

        print(f"Warning: No audio player found. Audio saved to {file_path}")

    @classmethod
    def list_voices(cls, language: str = "ko") -> list[str]:
        """List available voices for a language."""

        async def _list():
            voices = await edge_tts.list_voices()
            return [v["ShortName"] for v in voices if v["Locale"].startswith(language)]

        return asyncio.run(_list())
