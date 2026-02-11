# Aletheia

Voice/Text Style Transformation Pipeline with STT, filtering, and style transformation.

## Tech Stack

- Python 3.10+, hatchling build system
- STT: faster-whisper
- LLM: Ollama (default: qwen2.5:7b)
- TTS: Edge TTS
- API: FastAPI + Uvicorn
- GUI: Gradio
- Audio: sounddevice + numpy

## Project Structure

```
src/aletheia/
  config.py     - YAML config management (config.yaml)
  transcribe.py - faster-whisper STT
  filter.py     - Content filtering (regex-based)
  audio.py      - Microphone capture with VAD
  tts.py        - Edge TTS (ko/en, WSL support)
  style.py      - Ollama LLM style transformation
  pipeline.py   - Integrated pipeline (STT -> Filter -> Transform -> TTS)
  main.py       - CLI entry point
  api.py        - FastAPI REST API (persona/model CRUD)
  gui.py        - Gradio web GUI
```

## Commands

```bash
# Activate venv
source .venv/bin/activate

# Run CLI
aletheia -t "text" -p casual
aletheia --check
aletheia --list-personas

# Run API server
python -m aletheia.api --port 8000

# Run GUI
aletheia-gui
```

## Configuration

- `config.yaml` at project root
- Sections: whisper, ollama, filter, style (personas), audio, tts
- Personas are managed via config.yaml, API, or GUI
