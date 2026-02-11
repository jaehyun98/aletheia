# Aletheia

Voice/Text Style Transformation Pipeline with STT, filtering, and style transformation.

## Features

- **Speech-to-Text (STT)**: Transcribe audio using Faster-Whisper
- **Content Filtering**: Filter inappropriate content with customizable patterns
- **Style Transformation**: Transform text style using Ollama LLM with persona presets
- **Text-to-Speech (TTS)**: Generate speech output using Edge TTS
- **Multiple Interfaces**: CLI, REST API, and Web GUI

## Installation

```bash
# Install from source
pip install -e .

# Or install dependencies directly
pip install -r requirements.txt
```

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) running locally
- PortAudio for microphone support (Linux: `sudo apt install portaudio19-dev`)

## Usage

### CLI

```bash
# Text input -> Text output
aletheia -t "Hello, how are you?" -p casual

# Audio input -> Audio output
aletheia -i audio -o audio

# Check service status
aletheia --check

# List available personas
aletheia --list-personas

# Continuous mode
aletheia -i audio -o both --loop
```

### Web GUI

```bash
aletheia-gui
# Open http://localhost:7860
```

### REST API

```bash
python -m aletheia.api
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

## Configuration

Edit `config.yaml` to customize:

- **whisper**: STT model settings (model size, device)
- **ollama**: LLM settings (model, base URL)
- **filter**: Content filtering (patterns, action)
- **style**: Persona presets and default prompts
- **audio**: Audio capture settings
- **tts**: Text-to-speech settings

## Personas

Pre-configured persona presets:

| Key | Name | Description |
|-----|------|-------------|
| assistant | Friendly Assistant | Polite and professional |
| casual | Casual Friend | Relaxed and friendly |
| professional | Business Professional | Formal and concise |
| teacher | Patient Teacher | Simple explanations |
| comedian | Witty Comedian | Humorous responses |

Add custom personas in `config.yaml` or via the GUI.

## License

MIT
