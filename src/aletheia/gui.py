"""Gradio web GUI for Aletheia."""

import logging
import sys
import tempfile
import time
from pathlib import Path

# Suppress noisy Windows asyncio connection-reset warnings
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

import gradio as gr
import yaml

from .config import get_config, CONFIG_PATH
from .pipeline import AletheiaPipeline
from .printing import list_windows_printers, list_windows_fonts, PAPER_SIZES
from .watch import FolderWatcher

logger = logging.getLogger(__name__)

# Global pipeline instance
pipeline: AletheiaPipeline | None = None

# Global watcher instance for GUI control
_watcher: FolderWatcher | None = None
_watcher_log_since: float = 0.0


def get_pipeline() -> AletheiaPipeline:
    """Get or create pipeline instance."""
    global pipeline
    if pipeline is None:
        pipeline = AletheiaPipeline()
    return pipeline


def reload_pipeline():
    """Reload pipeline to pick up config changes."""
    global pipeline
    pipeline = None
    get_config.cache_clear() if hasattr(get_config, 'cache_clear') else None
    return get_pipeline()


def get_persona_choices() -> list[tuple[str, str]]:
    """Get persona choices for dropdown."""
    p = get_pipeline()
    personas = p.style_transformer.list_personas()
    choices = [(f"{name} ({key})", key) for key, name in personas.items()]
    choices.append(("Custom", "custom"))
    return choices


def load_config() -> dict:
    """Load config from file."""
    config_path = CONFIG_PATH
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(config: dict):
    """Save config to file."""
    config_path = CONFIG_PATH
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_personas_list() -> list[list[str]]:
    """Get personas as list for dataframe."""
    config = load_config()
    personas = config.get("style", {}).get("personas", {})
    default_key = config.get("style", {}).get("default_persona", "")

    result = []
    for key, info in personas.items():
        name = info.get("name", key)
        prompt = info.get("prompt", "").strip()
        is_default = "*" if key == default_key else ""
        result.append([key, name, prompt[:50] + "..." if len(prompt) > 50 else prompt, is_default])
    return result


def get_persona_keys() -> list[str]:
    """Get list of persona keys."""
    config = load_config()
    personas = config.get("style", {}).get("personas", {})
    return list(personas.keys())


def load_persona_for_edit(key: str) -> tuple[str, str, str, bool]:
    """Load persona details for editing."""
    if not key:
        return "", "", "", False

    config = load_config()
    personas = config.get("style", {}).get("personas", {})
    default_key = config.get("style", {}).get("default_persona", "")

    if key in personas:
        info = personas[key]
        return key, info.get("name", ""), info.get("prompt", ""), key == default_key
    return "", "", "", False


def save_persona(key: str, name: str, prompt: str, is_default: bool) -> str:
    """Save or update a persona."""
    if not key.strip():
        return "[Error] Key is required"
    if not name.strip():
        return "[Error] Name is required"
    if not prompt.strip():
        return "[Error] Prompt is required"

    key = key.strip().lower().replace(" ", "_")

    config = load_config()
    if "style" not in config:
        config["style"] = {}
    if "personas" not in config["style"]:
        config["style"]["personas"] = {}

    config["style"]["personas"][key] = {
        "name": name.strip(),
        "prompt": prompt.strip()
    }

    if is_default:
        config["style"]["default_persona"] = key

    save_config(config)
    reload_pipeline()

    return f"[OK] '{name}' saved"


def delete_persona(key: str) -> str:
    """Delete a persona."""
    if not key:
        return "[Error] Select a persona to delete"

    config = load_config()
    personas = config.get("style", {}).get("personas", {})

    if key not in personas:
        return f"[Error] '{key}' not found"

    name = personas[key].get("name", key)
    del config["style"]["personas"][key]

    # If deleted persona was default, clear default
    if config.get("style", {}).get("default_persona") == key:
        config["style"]["default_persona"] = ""

    save_config(config)
    reload_pipeline()

    return f"[OK] '{name}' deleted"


def process_text_input(
    text: str,
    persona_choice: str,
    custom_persona: str,
    style_prompt: str,
    skip_filter: bool,
    output_audio: bool,
) -> tuple[str, str, str | None]:
    """Process text input through pipeline."""
    if not text.strip():
        return "", "", None

    p = get_pipeline()
    persona = custom_persona if persona_choice == "custom" else persona_choice

    result = p.process_text(
        text,
        style_prompt=style_prompt if style_prompt.strip() else None,
        persona=persona if persona else None,
        skip_filter=skip_filter,
        skip_transform=False,
        speak=False,
    )

    audio_path = None
    if output_audio and result.transformed_text:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            audio_data = p.tts.synthesize(result.transformed_text)
            f.write(audio_data)
            audio_path = f.name

    return result.original_text, result.transformed_text, audio_path


def process_audio_input(
    audio_path: str,
    persona_choice: str,
    custom_persona: str,
    style_prompt: str,
    skip_filter: bool,
    output_audio: bool,
) -> tuple[str, str, str | None]:
    """Process audio input through pipeline."""
    if not audio_path:
        return "", "", None

    p = get_pipeline()
    persona = custom_persona if persona_choice == "custom" else persona_choice

    result = p.process_file(
        audio_path,
        style_prompt=style_prompt if style_prompt.strip() else None,
        persona=persona if persona else None,
        skip_filter=skip_filter,
        skip_transform=False,
        speak=False,
    )

    out_audio_path = None
    if output_audio and result.transformed_text:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            audio_data = p.tts.synthesize(result.transformed_text)
            f.write(audio_data)
            out_audio_path = f.name

    return result.original_text, result.transformed_text, out_audio_path


def check_services() -> str:
    """Check service status."""
    p = get_pipeline()
    status = p.check_services()
    lines = []
    for service, available in status.items():
        icon = "[OK]" if available else "[FAIL]"
        lines.append(f"{icon} {service}")
    return "\n".join(lines)


def get_ollama_models() -> list[str]:
    """Get list of available Ollama models."""
    p = get_pipeline()
    return p.style_transformer.list_models()


def get_current_model() -> str:
    """Get current Ollama model."""
    p = get_pipeline()
    return p.style_transformer.get_current_model()


def set_ollama_model(model: str) -> str:
    """Set Ollama model and save to config."""
    if not model:
        return "[Error] Select a model"

    config = load_config()
    if "ollama" not in config:
        config["ollama"] = {}
    config["ollama"]["model"] = model
    save_config(config)

    p = get_pipeline()
    p.style_transformer.set_model(model)

    return f"[OK] Model changed: {model}"


# Popular models for easy selection
POPULAR_MODELS = [
    ("llama3.2:3b", "Llama 3.2 3B - Fast and light"),
    ("llama3.2:1b", "Llama 3.2 1B - Lightest"),
    ("qwen2.5:7b", "Qwen 2.5 7B - Good for Korean"),
    ("qwen2.5:3b", "Qwen 2.5 3B - Korean, light"),
    ("qwen2.5:1.5b", "Qwen 2.5 1.5B - Korean, lightest"),
    ("gemma2:9b", "Gemma 2 9B - Google, balanced"),
    ("gemma2:2b", "Gemma 2 2B - Google, light"),
    ("mistral:7b", "Mistral 7B - Fast and smart"),
    ("phi3:mini", "Phi-3 Mini - MS, light"),
]


def load_watch_config() -> tuple[str, str, float]:
    """Load watch mode settings from config."""
    config = load_config()
    watch = config.get("watch", {})
    return (
        watch.get("input_dir", "./input"),
        watch.get("output_dir", "./output"),
        watch.get("poll_interval", 0.5),
    )


def save_watch_config(input_dir: str, output_dir: str, poll_interval: float) -> str:
    """Save watch mode settings to config."""
    if not input_dir.strip():
        return "[Error] Input directory is required"
    if not output_dir.strip():
        return "[Error] Output directory is required"

    config = load_config()
    config["watch"] = {
        "input_dir": input_dir.strip(),
        "output_dir": output_dir.strip(),
        "poll_interval": float(poll_interval),
    }
    save_config(config)
    return f"[OK] Watch paths saved (input: {input_dir.strip()}, output: {output_dir.strip()})"


def load_print_config() -> tuple[bool, str, str, bool, int, str]:
    """Load printing settings from config."""
    config = load_config()
    printing = config.get("printing", {})
    return (
        printing.get("auto_print", False),
        printing.get("printer_name", ""),
        printing.get("paper_size", "A4"),
        printing.get("landscape", False),
        printing.get("font_size", 12),
        printing.get("font_name", "Malgun Gothic"),
    )


def save_print_config(
    auto_print: bool, printer_name: str, paper_size: str,
    landscape: bool = False, font_size: int = 12,
    font_name: str = "Malgun Gothic",
) -> str:
    """Save printing settings to config."""
    config = load_config()
    config["printing"] = {
        "auto_print": bool(auto_print),
        "printer_name": printer_name.strip() if printer_name else "",
        "paper_size": paper_size.strip() if paper_size else "A4",
        "landscape": bool(landscape),
        "font_size": int(font_size),
        "font_name": font_name.strip() if font_name else "Malgun Gothic",
    }
    save_config(config)
    state = "ON" if auto_print else "OFF"
    orient = "Landscape" if landscape else "Portrait"
    return f"[OK] Print settings saved (auto_print: {state}, printer: {printer_name or 'none'}, paper: {paper_size or 'A4'}, {orient}, {font_name} {font_size}pt)"


def toggle_no_think(enabled: bool) -> str:
    """Toggle no_think option and save to config."""
    config = load_config()
    if "ollama" not in config:
        config["ollama"] = {}
    config["ollama"]["no_think"] = enabled
    save_config(config)

    p = get_pipeline()
    p.style_transformer.no_think = enabled

    state = "ON" if enabled else "OFF"
    return f"[OK] no_think: {state}"


def pull_ollama_model(model_name: str, progress=gr.Progress()) -> str:
    """Pull/download an Ollama model."""
    import ollama

    if not model_name or not model_name.strip():
        return "[Error] Enter a model name"

    model_name = model_name.strip()

    try:
        progress(0, desc=f"Downloading '{model_name}'...")

        # Use ollama.pull with stream to track progress
        client = ollama.Client()

        for response in client.pull(model_name, stream=True):
            status = response.get("status", "")

            if "completed" in response and "total" in response:
                completed = response["completed"]
                total = response["total"]
                if total > 0:
                    pct = completed / total
                    progress(pct, desc=f"{status}: {completed}/{total}")
            else:
                progress(0.5, desc=status)

        progress(1.0, desc="Done!")
        return f"[OK] '{model_name}' downloaded!"

    except Exception as e:
        return f"[Error] Download failed: {str(e)}"


def delete_ollama_model(model_name: str) -> tuple[str, list]:
    """Delete an Ollama model."""
    import ollama

    if not model_name:
        return "[Error] Select a model to delete", get_ollama_models()

    try:
        client = ollama.Client()
        client.delete(model_name)
        return f"[OK] '{model_name}' deleted", get_ollama_models()
    except Exception as e:
        return f"[Error] Delete failed: {str(e)}", get_ollama_models()


def start_watch(
    input_dir: str,
    output_dir: str,
    poll_interval: float,
    persona: str,
    auto_print: bool = False,
    printer_name: str = "",
    paper_size: str = "",
    landscape: bool = False,
    font_size: int = 12,
    font_name: str = "Malgun Gothic",
) -> tuple[str, str]:
    """Start the folder watcher from GUI."""
    global _watcher, _watcher_log_since

    if _watcher is not None and _watcher.is_running:
        return "Running", "[Already running]"

    p = get_pipeline()
    _watcher_log_since = time.time()

    _watcher = FolderWatcher(
        input_dir=Path(input_dir),
        output_dir=Path(output_dir),
        pipeline=p,
        poll_interval=float(poll_interval),
        persona=persona if persona and persona != "custom" else None,
        auto_print=bool(auto_print),
        printer_name=printer_name if printer_name else None,
        paper_size=paper_size if paper_size else "",
        landscape=bool(landscape),
        font_size=int(font_size),
        font_name=font_name if font_name else "Malgun Gothic",
    )
    _watcher.start()
    return "Running", "[OK] Watch mode started"


def stop_watch() -> tuple[str, str]:
    """Stop the folder watcher from GUI."""
    global _watcher

    if _watcher is None or not _watcher.is_running:
        return "Stopped", "[Already stopped]"

    _watcher.stop()
    return "Stopped", "[OK] Watch mode stopped"


def poll_watch_logs() -> tuple[str, str, gr.update]:
    """Poll watcher logs for the Timer callback."""
    global _watcher_log_since

    if _watcher is None or not _watcher.is_running:
        status = "Stopped"
        active = False
    else:
        status = "Running"
        active = True

    logs = _watcher.get_logs(since=_watcher_log_since) if _watcher else []
    if logs:
        _watcher_log_since = time.time()
    log_text = "\n".join(logs) if logs else ""

    return status, log_text, gr.update(active=active)


def poll_queue_status() -> tuple[str, str]:
    """Poll watcher queue status for the Timer callback."""
    if _watcher is None or not _watcher.is_running:
        return "", ""
    current, pending = _watcher.get_queue_status()
    current_text = current if current else "(none)"
    pending_text = "\n".join(pending) if pending else "(empty)"
    return current_text, pending_text


def cancel_queue_file(filename: str) -> tuple[str, str, str]:
    """Cancel a single pending file."""
    if not filename or not filename.strip():
        return gr.update(), gr.update(), "[Error] Enter a filename"
    if _watcher is None or not _watcher.is_running:
        return gr.update(), gr.update(), "[Error] Watch not running"
    ok = _watcher.cancel_file(filename.strip())
    if ok:
        current, pending = _watcher.get_queue_status()
        current_text = current if current else "(none)"
        pending_text = "\n".join(pending) if pending else "(empty)"
        return current_text, pending_text, f"[OK] Cancelled: {filename.strip()}"
    return gr.update(), gr.update(), f"[Error] '{filename.strip()}' not in queue"


def clear_watch_queue() -> tuple[str, str, str]:
    """Clear all pending files from queue."""
    if _watcher is None or not _watcher.is_running:
        return gr.update(), gr.update(), "[Error] Watch not running"
    count = _watcher.clear_queue()
    current, pending = _watcher.get_queue_status()
    current_text = current if current else "(none)"
    pending_text = "\n".join(pending) if pending else "(empty)"
    return current_text, pending_text, f"[OK] Cleared {count} file(s)"


def _get_default_browse_root() -> str:
    """Return a sensible default root for the folder browser."""
    import platform
    if platform.system() == "Windows":
        return str(Path.home())
    return "/mnt" if Path("/mnt").exists() else str(Path.home())


def create_ui() -> gr.Blocks:
    """Create Gradio UI."""

    with gr.Blocks(title="Aletheia") as app:
        gr.Markdown("# Aletheia")
        gr.Markdown("Voice/Text Style Transformation Pipeline")

        with gr.Tabs():
            # Main tab - Transform
            with gr.TabItem("Transform"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### Settings")

                        persona_dropdown = gr.Dropdown(
                            choices=get_persona_choices(),
                            value=get_pipeline().style_transformer.default_persona_key,
                            label="Persona",
                            info="Select AI personality",
                        )

                        custom_persona = gr.Textbox(
                            label="Custom Persona",
                            placeholder="e.g., You are a pirate. Talk like a pirate.",
                            lines=2,
                            visible=False,
                        )

                        style_prompt = gr.Textbox(
                            label="Style Prompt (Optional)",
                            placeholder="Custom transformation instructions",
                            lines=2,
                        )

                        skip_filter = gr.Checkbox(
                            label="Skip Filtering",
                            value=False,
                        )

                        output_audio = gr.Checkbox(
                            label="Generate Audio Output",
                            value=True,
                        )

                        with gr.Accordion("Service Status", open=False):
                            status_text = gr.Textbox(
                                label="",
                                value=check_services,
                                interactive=False,
                            )
                            refresh_btn = gr.Button("Refresh", size="sm")
                            refresh_btn.click(check_services, outputs=status_text)

                    with gr.Column(scale=2):
                        with gr.Tabs():
                            with gr.TabItem("Text Input"):
                                text_input = gr.Textbox(
                                    label="Input Text",
                                    placeholder="Enter text to transform...",
                                    lines=3,
                                )
                                text_submit = gr.Button("Transform", variant="primary")

                                with gr.Row():
                                    text_original = gr.Textbox(label="Original", interactive=False)
                                    text_transformed = gr.Textbox(label="Transformed", interactive=False)

                                text_audio_output = gr.Audio(label="Audio Output", type="filepath")

                            with gr.TabItem("Audio Input"):
                                audio_input = gr.Audio(
                                    label="Record or Upload Audio",
                                    type="filepath",
                                    sources=["microphone", "upload"],
                                )
                                audio_submit = gr.Button("Transform", variant="primary")

                                with gr.Row():
                                    audio_original = gr.Textbox(label="Transcribed", interactive=False)
                                    audio_transformed = gr.Textbox(label="Transformed", interactive=False)

                                audio_audio_output = gr.Audio(label="Audio Output", type="filepath")

            # Persona management tab
            with gr.TabItem("Personas"):
                gr.Markdown("### Persona Preset Management")
                gr.Markdown("Add, edit, or delete persona presets.")

                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("#### Preset List")

                        persona_table = gr.Dataframe(
                            headers=["Key", "Name", "Prompt", "Default"],
                            value=get_personas_list,
                            interactive=False,
                            wrap=True,
                        )

                        refresh_table_btn = gr.Button("Refresh List")

                    with gr.Column(scale=1):
                        gr.Markdown("#### Edit")

                        edit_key_dropdown = gr.Dropdown(
                            choices=get_persona_keys(),
                            label="Select Persona to Edit",
                            info="Leave empty to add new",
                            allow_custom_value=True,
                        )

                        edit_key = gr.Textbox(
                            label="Key (lowercase, no spaces)",
                            placeholder="e.g., friendly_bot",
                        )

                        edit_name = gr.Textbox(
                            label="Name",
                            placeholder="e.g., Friendly Bot",
                        )

                        edit_prompt = gr.Textbox(
                            label="Prompt",
                            placeholder="e.g., You are a friendly assistant...",
                            lines=5,
                        )

                        edit_default = gr.Checkbox(
                            label="Set as Default",
                            value=False,
                        )

                        with gr.Row():
                            save_btn = gr.Button("Save", variant="primary")
                            delete_btn = gr.Button("Delete", variant="stop")
                            clear_btn = gr.Button("Clear")

                        edit_status = gr.Textbox(
                            label="Status",
                            interactive=False,
                        )

            # Settings tab
            with gr.TabItem("Settings"):
                # --- Model Accordion ---
                with gr.Accordion("Model", open=True):
                    model_dropdown = gr.Dropdown(
                        choices=get_ollama_models(),
                        value=get_current_model(),
                        label="Model to Use",
                        info="Select from installed models",
                    )
                    with gr.Row():
                        model_refresh_btn = gr.Button("Refresh")
                        model_apply_btn = gr.Button("Apply", variant="primary")
                    no_think_checkbox = gr.Checkbox(
                        label="no_think",
                        value=load_config().get("ollama", {}).get("no_think", False),
                        info="Disable model thinking (for Qwen etc.)",
                    )
                    with gr.Accordion("Generation Parameters", open=False):
                        _ollama_cfg = load_config().get("ollama", {})
                        gen_temperature = gr.Slider(
                            label="Temperature",
                            value=_ollama_cfg.get("temperature", 0.8),
                            minimum=0.0, maximum=2.0, step=0.05,
                            info="0.0=deterministic, 1.0+=creative",
                        )
                        gen_top_p = gr.Slider(
                            label="Top P",
                            value=_ollama_cfg.get("top_p", 0.9),
                            minimum=0.0, maximum=1.0, step=0.05,
                            info="Nucleus sampling threshold",
                        )
                        gen_top_k = gr.Slider(
                            label="Top K",
                            value=_ollama_cfg.get("top_k", 40),
                            minimum=1, maximum=200, step=1,
                            info="Top-k sampling",
                        )
                        gen_repeat_penalty = gr.Slider(
                            label="Repeat Penalty",
                            value=_ollama_cfg.get("repeat_penalty", 1.1),
                            minimum=1.0, maximum=2.0, step=0.05,
                            info="1.0=off, higher=less repetition",
                        )
                        gen_max_tokens = gr.Slider(
                            label="Max Tokens",
                            value=_ollama_cfg.get("max_tokens", 4096),
                            minimum=256, maximum=16384, step=256,
                            info="Maximum output tokens",
                        )
                        gen_apply_btn = gr.Button("Apply Parameters", variant="primary")
                        gen_status = gr.Textbox(label="Status", interactive=False)
                    model_status = gr.Textbox(
                        label="Status",
                        interactive=False,
                    )

                # --- Model Library Accordion ---
                with gr.Accordion("Model Library", open=False):
                    popular_model_dropdown = gr.Dropdown(
                        choices=[(desc, name) for name, desc in POPULAR_MODELS],
                        label="Popular Models",
                        info="Click to auto-fill",
                    )
                    with gr.Row():
                        model_name_input = gr.Textbox(
                            label="Model Name",
                            placeholder="e.g., llama3.2:3b, qwen2.5:7b",
                            info="Enter model name to download",
                        )
                        model_pull_btn = gr.Button("Download", variant="primary")
                    gr.Markdown("---")
                    with gr.Row():
                        model_delete_dropdown = gr.Dropdown(
                            choices=get_ollama_models(),
                            label="Model to Delete",
                            info="Select installed model",
                        )
                        model_delete_btn = gr.Button("Delete", variant="stop")
                    model_lib_status = gr.Textbox(
                        label="Status",
                        interactive=False,
                    )
                    gr.Markdown(
                        "Model size: 1B < 3B < 7B < 9B (larger = smarter but slower) · "
                        "Korean recommended: `qwen2.5` · "
                        "[Ollama Library](https://ollama.com/library)"
                    )

                # --- Watch Mode Accordion ---
                with gr.Accordion("Watch Mode", open=False):
                    watch_input_dir, watch_output_dir, watch_poll = load_watch_config()

                    with gr.Row():
                        watch_input = gr.Textbox(
                            label="Input Directory",
                            value=watch_input_dir,
                            placeholder="./input",
                        )
                        watch_output = gr.Textbox(
                            label="Output Directory",
                            value=watch_output_dir,
                            placeholder="./output",
                        )
                        watch_poll_interval = gr.Number(
                            label="Poll Interval (sec)",
                            value=watch_poll,
                            minimum=0.1,
                            maximum=10.0,
                            step=0.1,
                        )

                    watch_persona = gr.Dropdown(
                        choices=get_persona_choices(),
                        value=get_pipeline().style_transformer.default_persona_key,
                        label="Watch Persona",
                        info="Persona to use in watch mode",
                    )

                    with gr.Row():
                        watch_start_btn = gr.Button("Start", variant="primary")
                        watch_stop_btn = gr.Button("Stop", variant="stop")
                        watch_running_status = gr.Textbox(
                            label="Status", value="Stopped", interactive=False,
                        )

                    watch_log_viewer = gr.Textbox(
                        label="Watch Log",
                        interactive=False,
                        lines=10,
                        max_lines=20,
                    )

                    with gr.Accordion("Queue", open=True):
                        queue_current_file = gr.Textbox(
                            label="Processing",
                            value="(none)",
                            interactive=False,
                        )
                        queue_pending_list = gr.Textbox(
                            label="Pending Files",
                            value="(empty)",
                            interactive=False,
                            lines=4,
                            max_lines=10,
                        )
                        with gr.Row():
                            queue_cancel_input = gr.Textbox(
                                label="Filename to Cancel",
                                placeholder="e.g., recording.wav",
                                scale=3,
                            )
                            queue_cancel_btn = gr.Button("Cancel File", scale=1)
                        queue_clear_btn = gr.Button("Clear Queue", variant="stop")
                        queue_status = gr.Textbox(
                            label="Queue Action",
                            interactive=False,
                        )

                    watch_timer = gr.Timer(1.0, active=False)

                    # Nested: Browse Folders
                    with gr.Accordion("Browse Folders", open=False):
                        file_explorer = gr.FileExplorer(
                            root_dir=_get_default_browse_root(),
                            file_count="single",
                            label="Select a file inside the target folder",
                            height=300,
                        )
                        with gr.Row():
                            browse_set_input_btn = gr.Button(
                                "Set as Input Dir", variant="primary",
                            )
                            browse_set_output_btn = gr.Button(
                                "Set as Output Dir", variant="primary",
                            )

                    # Nested: Print Settings
                    with gr.Accordion("Print Settings", open=False):
                        print_auto, print_printer, print_paper, print_landscape, print_font_size, print_font_name = load_print_config()
                        printer_choices = list_windows_printers()

                        with gr.Row():
                            watch_auto_print = gr.Checkbox(
                                label="Auto-Print Output",
                                value=print_auto,
                                info="Automatically print output files",
                            )
                            watch_printer = gr.Dropdown(
                                choices=printer_choices,
                                value=print_printer if print_printer in printer_choices else None,
                                label="Printer",
                                info="Select Windows printer",
                            )
                            watch_paper_size = gr.Dropdown(
                                choices=PAPER_SIZES,
                                value=print_paper if print_paper in PAPER_SIZES else "A4",
                                label="Paper Size",
                                info="Select paper size for printing",
                            )
                            watch_refresh_printers = gr.Button("Refresh", size="sm")

                        with gr.Row():
                            watch_landscape = gr.Checkbox(
                                label="Landscape",
                                value=print_landscape,
                                info="Print in landscape orientation",
                            )
                            watch_font_size = gr.Slider(
                                label="Font Size (pt)",
                                value=print_font_size,
                                minimum=6,
                                maximum=48,
                                step=1,
                                info="Font size for printing",
                            )
                        font_choices = list_windows_fonts()
                        watch_font_name = gr.Dropdown(
                            choices=font_choices,
                            value=print_font_name if print_font_name in font_choices else "Malgun Gothic",
                            label="Font",
                            info="Select font for printing",
                            allow_custom_value=True,
                        )

                    with gr.Row():
                        watch_save_btn = gr.Button("Save Settings", variant="primary")
                        watch_status = gr.Textbox(label="Status", interactive=False)

                # --- Restart ---
                with gr.Accordion("Application", open=False):
                    gr.Markdown("Reload: config.yaml 재적용 (빠름) / Restart: 프로세스 전체 재시작 (코드 변경 시)")
                    with gr.Row():
                        reload_btn = gr.Button("Reload Config", variant="secondary")
                        restart_btn = gr.Button("Restart App", variant="stop")
                    app_status = gr.Textbox(label="Status", interactive=False)

        # Event handlers
        def toggle_custom_persona(choice):
            return gr.update(visible=(choice == "custom"))

        persona_dropdown.change(
            toggle_custom_persona,
            inputs=[persona_dropdown],
            outputs=[custom_persona],
        )

        text_submit.click(
            process_text_input,
            inputs=[text_input, persona_dropdown, custom_persona, style_prompt, skip_filter, output_audio],
            outputs=[text_original, text_transformed, text_audio_output],
        )

        audio_submit.click(
            process_audio_input,
            inputs=[audio_input, persona_dropdown, custom_persona, style_prompt, skip_filter, output_audio],
            outputs=[audio_original, audio_transformed, audio_audio_output],
        )

        # Persona management handlers
        def on_select_persona(key):
            if key:
                k, name, prompt, is_default = load_persona_for_edit(key)
                return k, name, prompt, is_default
            return "", "", "", False

        edit_key_dropdown.change(
            on_select_persona,
            inputs=[edit_key_dropdown],
            outputs=[edit_key, edit_name, edit_prompt, edit_default],
        )

        def on_save_and_refresh(key, name, prompt, is_default):
            status = save_persona(key, name, prompt, is_default)
            return (
                status,
                get_personas_list(),
                gr.update(choices=get_persona_keys()),
                gr.update(choices=get_persona_choices()),
            )

        save_btn.click(
            on_save_and_refresh,
            inputs=[edit_key, edit_name, edit_prompt, edit_default],
            outputs=[edit_status, persona_table, edit_key_dropdown, persona_dropdown],
        )

        def on_delete_and_refresh(key):
            status = delete_persona(key)
            return (
                status,
                get_personas_list(),
                gr.update(choices=get_persona_keys(), value=""),
                gr.update(choices=get_persona_choices()),
                "", "", "", False,
            )

        delete_btn.click(
            on_delete_and_refresh,
            inputs=[edit_key],
            outputs=[edit_status, persona_table, edit_key_dropdown, persona_dropdown, edit_key, edit_name, edit_prompt, edit_default],
        )

        def clear_form():
            return "", "", "", False, gr.update(value="")

        clear_btn.click(
            clear_form,
            outputs=[edit_key, edit_name, edit_prompt, edit_default, edit_key_dropdown],
        )

        def refresh_table():
            return get_personas_list(), gr.update(choices=get_persona_keys())

        refresh_table_btn.click(
            refresh_table,
            outputs=[persona_table, edit_key_dropdown],
        )

        # Settings handlers
        def refresh_models():
            models = get_ollama_models()
            current = get_current_model()
            return gr.update(choices=models, value=current), gr.update(choices=models)

        model_refresh_btn.click(
            refresh_models,
            outputs=[model_dropdown, model_delete_dropdown],
        )

        model_apply_btn.click(
            set_ollama_model,
            inputs=[model_dropdown],
            outputs=[model_status],
        )

        # Popular model selection - auto-fill input
        def on_popular_model_select(model):
            return model if model else ""

        popular_model_dropdown.change(
            on_popular_model_select,
            inputs=[popular_model_dropdown],
            outputs=[model_name_input],
        )

        # Model download handler
        def on_model_pull(model_name, progress=gr.Progress()):
            status = pull_ollama_model(model_name, progress)
            models = get_ollama_models()
            return (
                status,
                gr.update(choices=models),
                gr.update(choices=models),
            )

        model_pull_btn.click(
            on_model_pull,
            inputs=[model_name_input],
            outputs=[model_lib_status, model_dropdown, model_delete_dropdown],
        )

        # Model delete handler
        def on_model_delete(model_name):
            status, models = delete_ollama_model(model_name)
            current = get_current_model()
            return (
                status,
                gr.update(choices=models, value=current if current in models else None),
                gr.update(choices=models, value=""),
            )

        model_delete_btn.click(
            on_model_delete,
            inputs=[model_delete_dropdown],
            outputs=[model_lib_status, model_dropdown, model_delete_dropdown],
        )

        # no_think toggle handler
        no_think_checkbox.change(
            toggle_no_think,
            inputs=[no_think_checkbox],
            outputs=[model_status],
        )

        # Generation parameters handler
        def on_apply_gen_params(temperature, top_p, top_k, repeat_penalty, max_tokens):
            config = load_config()
            if "ollama" not in config:
                config["ollama"] = {}
            config["ollama"]["temperature"] = float(temperature)
            config["ollama"]["top_p"] = float(top_p)
            config["ollama"]["top_k"] = int(top_k)
            config["ollama"]["repeat_penalty"] = float(repeat_penalty)
            config["ollama"]["max_tokens"] = int(max_tokens)
            save_config(config)

            p = get_pipeline()
            p.style_transformer.temperature = float(temperature)
            p.style_transformer.top_p = float(top_p)
            p.style_transformer.top_k = int(top_k)
            p.style_transformer.repeat_penalty = float(repeat_penalty)
            p.style_transformer.max_tokens = int(max_tokens)

            return f"[OK] temperature={temperature}, top_p={top_p}, top_k={int(top_k)}, repeat_penalty={repeat_penalty}, max_tokens={int(max_tokens)}"

        gen_apply_btn.click(
            on_apply_gen_params,
            inputs=[gen_temperature, gen_top_p, gen_top_k, gen_repeat_penalty, gen_max_tokens],
            outputs=[gen_status],
        )

        # Watch mode handlers
        def on_watch_save(input_dir, output_dir, poll_interval, auto_print, printer_name, paper_size, landscape, font_size, font_name):
            watch_msg = save_watch_config(input_dir, output_dir, poll_interval)
            print_msg = save_print_config(auto_print, printer_name, paper_size, landscape, int(font_size), font_name)
            # Update running watcher's print settings in real-time
            if _watcher is not None and _watcher.is_running:
                _watcher.auto_print = bool(auto_print)
                _watcher.printer_name = printer_name if printer_name else None
                _watcher.paper_size = paper_size if paper_size else ""
                _watcher.landscape = bool(landscape)
                _watcher.font_size = int(font_size)
                _watcher.font_name = font_name if font_name else "Malgun Gothic"
                print_msg += " (applied to running watcher)"
            return f"{watch_msg}\n{print_msg}"

        watch_save_btn.click(
            on_watch_save,
            inputs=[watch_input, watch_output, watch_poll_interval, watch_auto_print, watch_printer, watch_paper_size, watch_landscape, watch_font_size, watch_font_name],
            outputs=[watch_status],
        )

        # Refresh printers & fonts handler
        def _refresh_printers_and_fonts():
            return gr.update(choices=list_windows_printers()), gr.update(choices=list_windows_fonts())

        watch_refresh_printers.click(
            _refresh_printers_and_fonts,
            outputs=[watch_printer, watch_font_name],
        )

        def on_watch_start(input_dir, output_dir, poll_interval, persona, auto_print, printer_name, paper_size, landscape, font_size, font_name):
            status, msg = start_watch(input_dir, output_dir, poll_interval, persona, auto_print, printer_name, paper_size, landscape, int(font_size), font_name)
            return status, msg, gr.update(active=True), "(none)", "(empty)"

        watch_start_btn.click(
            on_watch_start,
            inputs=[watch_input, watch_output, watch_poll_interval, watch_persona, watch_auto_print, watch_printer, watch_paper_size, watch_landscape, watch_font_size, watch_font_name],
            outputs=[watch_running_status, watch_status, watch_timer, queue_current_file, queue_pending_list],
        )

        def on_watch_stop():
            status, msg = stop_watch()
            return status, msg, gr.update(active=False), "(none)", "(empty)"

        watch_stop_btn.click(
            on_watch_stop,
            outputs=[watch_running_status, watch_status, watch_timer, queue_current_file, queue_pending_list],
        )

        def on_watch_tick(current_log):
            status, new_lines, timer_update = poll_watch_logs()
            if new_lines:
                updated = (current_log + "\n" + new_lines).strip() if current_log else new_lines
            else:
                updated = current_log or ""
            q_current, q_pending = poll_queue_status()
            return status, updated, timer_update, q_current, q_pending

        watch_timer.tick(
            on_watch_tick,
            inputs=[watch_log_viewer],
            outputs=[watch_running_status, watch_log_viewer, watch_timer, queue_current_file, queue_pending_list],
        )

        # Queue cancel/clear handlers
        queue_cancel_btn.click(
            cancel_queue_file,
            inputs=[queue_cancel_input],
            outputs=[queue_current_file, queue_pending_list, queue_status],
        )

        queue_clear_btn.click(
            clear_watch_queue,
            outputs=[queue_current_file, queue_pending_list, queue_status],
        )

        # FileExplorer browse handlers
        _browse_root = _get_default_browse_root()

        def _selected_to_dir(selected) -> str:
            """Convert FileExplorer selection to an absolute directory path.

            FileExplorer returns a relative path from root_dir.
            If the selected item is a file, use its parent directory.
            """
            if not selected:
                return ""
            abs_path = Path(_browse_root) / selected
            if abs_path.is_file():
                return str(abs_path.parent)
            return str(abs_path)

        def _set_input(sel):
            d = _selected_to_dir(sel)
            if not d:
                return gr.update(), "[Error] No file selected"
            return d, f"[OK] Input: {d}"

        def _set_output(sel):
            d = _selected_to_dir(sel)
            if not d:
                return gr.update(), "[Error] No file selected"
            return d, f"[OK] Output: {d}"

        browse_set_input_btn.click(
            _set_input,
            inputs=[file_explorer],
            outputs=[watch_input, watch_status],
        )
        browse_set_output_btn.click(
            _set_output,
            inputs=[file_explorer],
            outputs=[watch_output, watch_status],
        )

        # Reload config (no restart)
        def on_reload_config():
            reload_pipeline()
            return "[OK] Config reloaded"

        reload_btn.click(on_reload_config, outputs=[app_status])

        # Full restart
        def on_restart_app():
            import os, subprocess, threading
            def _restart():
                time.sleep(1)
                # Find and run run_gui.bat for proper restart
                project_root = CONFIG_PATH.parent
                bat_file = project_root / "run_gui.bat"
                if bat_file.exists():
                    subprocess.Popen(
                        ["cmd", "/c", str(bat_file)],
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                    )
                else:
                    # Fallback: run exe/script directly with correct cwd
                    cmd = sys.argv if sys.argv[0].endswith('.exe') else [sys.executable] + sys.argv
                    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=str(project_root))
                os._exit(0)
            threading.Thread(target=_restart, daemon=True).start()
            return "[OK] Restarting... (refresh browser in a few seconds)"

        restart_btn.click(on_restart_app, outputs=[app_status])

        # Auto-start watch mode on GUI load
        def _auto_start_watch():
            input_dir, output_dir, poll_interval = load_watch_config()
            print_auto, print_printer, print_paper, print_land, print_fs, print_fn = load_print_config()
            persona = get_pipeline().style_transformer.default_persona_key
            status, msg = start_watch(
                input_dir, output_dir, poll_interval, persona,
                print_auto, print_printer, print_paper, print_land, print_fs, print_fn,
            )
            return status, msg, gr.update(active=True), "(none)", "(empty)"

        app.load(
            _auto_start_watch,
            outputs=[watch_running_status, watch_status, watch_timer, queue_current_file, queue_pending_list],
        )

    return app


def main():
    """Launch GUI."""
    app = create_ui()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
    )


if __name__ == "__main__":
    main()
