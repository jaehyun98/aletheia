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
- Printing: PowerShell + .NET System.Drawing (Windows)

## Project Structure

```
src/aletheia/
  config.py     - YAML config management (config.yaml), thread-safe singleton
  transcribe.py - faster-whisper STT
  filter.py     - Content filtering (regex-based)
  audio.py      - Microphone capture with VAD
  tts.py        - Edge TTS (ko/en, WSL support)
  style.py      - Ollama LLM style transformation (language-aware prompts)
  pipeline.py   - Integrated pipeline (STT -> Filter -> Transform -> TTS)
  main.py       - CLI entry point (text/audio/watch modes)
  api.py        - FastAPI REST API (persona/model CRUD)
  gui.py        - Gradio web GUI (transform, personas, settings, watch, print)
  watch.py      - Folder watcher for TouchDesigner integration
  printing.py   - Windows printer integration (PowerShell, positioned text)
```

## Commands

```bash
# Activate venv
source .venv/bin/activate

# Run CLI
aletheia -t "text" -p casual
aletheia --check
aletheia --list-personas

# Run CLI watch mode
aletheia --watch
aletheia --watch --input-dir ./in --output-dir ./out

# Run API server
python -m aletheia.api --port 8000

# Run GUI
aletheia-gui
```

## Configuration

- `config.yaml` at project root (gitignored, local settings)
- `config.example.yaml` — template for new environments
- Sections: whisper, ollama, filter, style (personas), audio, tts, watch, printing

### Key config sections

- **whisper**: model size, device (auto/cpu/cuda)
- **ollama**: model, base_url, no_think, generation params (temperature, top_p, top_k, repeat_penalty, max_tokens)
- **filter**: enabled, action (mask/remove/replace), patterns
- **style**: default_persona, personas (key → {name, prompt, examples}), default_prompt
- **watch**: input_dir, output_dir, poll_interval
- **printing**: auto_print, printer_name, paper_size, landscape, font_size_ko/en, font_name_ko/en, margin_lr, layout (offset_pct, separator)
- **audio**: sample_rate, channels, silence_threshold, silence_duration, max_duration
- **tts**: language, voice_type, rate, volume

## Watch Mode (TouchDesigner Integration)

- Monitors input directory for WAV/MP3 files
- Processes through pipeline sequentially (STT → Filter → Transform)
- Writes result text to output directory
- Moves processed files to `input/done/`
- Auto-print support with positioned layout (input + output on same page)
- **Backup system**: saves input/output text pairs to `output/backup/input/NNNN.txt` and `output/backup/output/NNNN.txt` (4-digit zero-padded index, resumes on restart)

## Printing

- Windows printers via PowerShell + .NET System.Drawing
- Positioned text: input block + output block at configurable Y% positions
- Bilingual font support (Korean/English separate fonts and sizes)
- Paper sizes: A3, A4, A5, A6, Letter, Legal, B4/B5 (JIS)
- Landscape/portrait orientation
- PowerShell string values are escaped via `_ps_escape()` to prevent injection

## Architecture Notes

- `config.py`: global singleton protected by `threading.Lock` for thread safety between GUI main thread and watch worker thread
- `watch.py`: backup writes are isolated in try/except so failures don't block main processing flow
- `tts.py`: audio streaming uses list+join pattern for O(n) byte concatenation
- GUI has no audio output generation (TTS playback removed from GUI)
- CLI still supports `--output audio` via pipeline TTS
