"""Gradio web GUI for Aletheia."""

import tempfile

import gradio as gr
import yaml

from .config import CONFIG_PATH, get_config
from .pipeline import AletheiaPipeline

# Global pipeline instance
pipeline: AletheiaPipeline | None = None


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
    ("exaone3.5:7.8b", "EXAONE 3.5 7.8B - Best for Korean (default)"),
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
                with gr.Row():
                    # Left column - Current model selection
                    with gr.Column(scale=1):
                        gr.Markdown("### Current Model")

                        model_dropdown = gr.Dropdown(
                            choices=get_ollama_models(),
                            value=get_current_model(),
                            label="Model to Use",
                            info="Select from installed models",
                        )

                        with gr.Row():
                            model_refresh_btn = gr.Button("Refresh")
                            model_apply_btn = gr.Button("Apply", variant="primary")

                        model_status = gr.Textbox(
                            label="Status",
                            interactive=False,
                        )

                        gr.Markdown("---")
                        gr.Markdown("### Delete Model")

                        model_delete_dropdown = gr.Dropdown(
                            choices=get_ollama_models(),
                            label="Model to Delete",
                            info="Select installed model",
                        )
                        model_delete_btn = gr.Button("Delete", variant="stop")
                        model_delete_status = gr.Textbox(
                            label="Delete Status",
                            interactive=False,
                        )

                    # Right column - Download new models
                    with gr.Column(scale=1):
                        gr.Markdown("### Download Model")

                        gr.Markdown("**Popular Models:**")
                        popular_model_dropdown = gr.Dropdown(
                            choices=[(desc, name) for name, desc in POPULAR_MODELS],
                            label="Popular Models",
                            info="Click to auto-fill",
                        )

                        model_name_input = gr.Textbox(
                            label="Model Name",
                            placeholder="e.g., llama3.2:3b, qwen2.5:7b",
                            info="Enter model name to download",
                        )

                        model_pull_btn = gr.Button("Download", variant="primary")

                        model_pull_status = gr.Textbox(
                            label="Download Status",
                            interactive=False,
                        )

                        gr.Markdown("---")
                        gr.Markdown("#### Help")
                        gr.Markdown("""
- Select from **Popular Models** or enter name directly
- Model size: 1B < 3B < 7B < 9B (larger = smarter but slower)
- Korean recommended: `qwen2.5` series
- See more at [Ollama Library](https://ollama.com/library)
                        """)

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
            outputs=[
                edit_status, persona_table, edit_key_dropdown, persona_dropdown,
                edit_key, edit_name, edit_prompt, edit_default,
            ],
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
            outputs=[model_pull_status, model_dropdown, model_delete_dropdown],
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
            outputs=[model_delete_status, model_dropdown, model_delete_dropdown],
        )

    return app


def main():
    """Launch GUI."""
    app = create_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
    )


if __name__ == "__main__":
    main()
