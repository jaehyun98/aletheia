"""FastAPI REST API server for Aletheia."""

import tempfile
from pathlib import Path
from typing import Annotated

import uvicorn
import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import CONFIG_PATH, get_config, reset_config
from .pipeline import AletheiaPipeline

app = FastAPI(
    title="Aletheia API",
    description="Voice/Text Style Transformation Pipeline with STT, filtering, and style transformation",
    version="0.1.0",
)

# Global pipeline instance
_pipeline: AletheiaPipeline | None = None


def _load_config() -> dict:
    """Load config from file."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_config(config: dict):
    """Save config to file."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _reload_pipeline():
    """Reload pipeline to pick up config changes."""
    global _pipeline
    _pipeline = None
    reset_config()
    return get_pipeline()


def get_pipeline() -> AletheiaPipeline:
    """Get or create the global pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = AletheiaPipeline()
    return _pipeline


class TransformRequest(BaseModel):
    """Request model for text transformation."""

    text: str
    persona: str | None = None
    style_prompt: str | None = None
    skip_filter: bool = False
    skip_transform: bool = False


class PersonaRequest(BaseModel):
    """Request model for creating/updating a persona."""

    key: str
    name: str
    prompt: str
    is_default: bool = False


class PersonaResponse(BaseModel):
    """Response model for a single persona."""

    key: str
    name: str
    prompt: str
    is_default: bool


class PersonaListResponse(BaseModel):
    """Response model for listing personas."""

    personas: list[PersonaResponse]
    default_persona: str | None


class ModelListResponse(BaseModel):
    """Response model for listing models."""

    models: list[str]
    current_model: str


class ModelSetRequest(BaseModel):
    """Request model for setting current model."""

    model: str


class TransformResponse(BaseModel):
    """Response model for transformation results."""

    original_text: str
    filtered_text: str
    transformed_text: str
    filtered_words: list[str]


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str
    services: dict[str, bool]


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check server and service health."""
    pipeline = get_pipeline()
    services = pipeline.check_services()
    all_healthy = all(services.values())

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        services=services,
    )


@app.post("/transform", response_model=TransformResponse)
async def transform_text(request: TransformRequest):
    """Transform text through filtering and style transformation.

    - **text**: Input text to transform
    - **persona**: Persona key to use (optional, overrides style_prompt)
    - **style_prompt**: Custom style prompt (optional)
    - **skip_filter**: Skip content filtering (default: false)
    - **skip_transform**: Skip style transformation (default: false)
    """
    pipeline = get_pipeline()

    try:
        result = pipeline.process_text(
            request.text,
            persona=request.persona,
            style_prompt=request.style_prompt,
            skip_filter=request.skip_filter,
            skip_transform=request.skip_transform,
        )
        return TransformResponse(
            original_text=result.original_text,
            filtered_text=result.filtered_text,
            transformed_text=result.transformed_text,
            filtered_words=result.filtered_words,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/transform/stream")
async def transform_text_stream(request: TransformRequest):
    """Transform text with streaming response.

    Returns Server-Sent Events (SSE) stream of transformed text chunks.
    """
    pipeline = get_pipeline()

    def generate():
        try:
            for chunk in pipeline.process_stream(
                request.text,
                persona=request.persona,
                style_prompt=request.style_prompt,
                skip_filter=request.skip_filter,
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


@app.post("/transcribe", response_model=TransformResponse)
async def transcribe_audio(
    file: Annotated[UploadFile, File(description="Audio file to transcribe")],
    persona: Annotated[str | None, Form()] = None,
    style_prompt: Annotated[str | None, Form()] = None,
    skip_filter: Annotated[bool, Form()] = False,
    skip_transform: Annotated[bool, Form()] = False,
):
    """Transcribe audio file and optionally transform the text.

    - **file**: Audio file (WAV, MP3, etc.)
    - **persona**: Persona key to use (optional, overrides style_prompt)
    - **style_prompt**: Custom style prompt (optional)
    - **skip_filter**: Skip content filtering (default: false)
    - **skip_transform**: Skip style transformation (default: false)
    """
    pipeline = get_pipeline()

    # Read uploaded file
    content = await file.read()

    # Save to temp file for processing
    suffix = Path(file.filename).suffix if file.filename else ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = pipeline.process_file(
            tmp_path,
            persona=persona,
            style_prompt=style_prompt,
            skip_filter=skip_filter,
            skip_transform=skip_transform,
        )
        return TransformResponse(
            original_text=result.original_text,
            filtered_text=result.filtered_text,
            transformed_text=result.transformed_text,
            filtered_words=result.filtered_words,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


# =============================================================================
# Persona Management Endpoints
# =============================================================================


@app.get("/personas", response_model=PersonaListResponse)
async def list_personas():
    """List all available personas."""
    config = _load_config()
    personas_dict = config.get("style", {}).get("personas", {})
    default_key = config.get("style", {}).get("default_persona", "")

    personas = [
        PersonaResponse(
            key=key,
            name=info.get("name", key),
            prompt=info.get("prompt", ""),
            is_default=(key == default_key),
        )
        for key, info in personas_dict.items()
    ]

    return PersonaListResponse(personas=personas, default_persona=default_key or None)


@app.get("/personas/{key}", response_model=PersonaResponse)
async def get_persona(key: str):
    """Get a specific persona by key."""
    config = _load_config()
    personas = config.get("style", {}).get("personas", {})
    default_key = config.get("style", {}).get("default_persona", "")

    if key not in personas:
        raise HTTPException(status_code=404, detail=f"Persona '{key}' not found")

    info = personas[key]
    return PersonaResponse(
        key=key,
        name=info.get("name", key),
        prompt=info.get("prompt", ""),
        is_default=(key == default_key),
    )


@app.post("/personas", response_model=PersonaResponse, status_code=201)
async def create_persona(request: PersonaRequest):
    """Create a new persona."""
    key = request.key.strip().lower().replace(" ", "_")

    if not key:
        raise HTTPException(status_code=400, detail="Key is required")
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    config = _load_config()
    if "style" not in config:
        config["style"] = {}
    if "personas" not in config["style"]:
        config["style"]["personas"] = {}

    if key in config["style"]["personas"]:
        raise HTTPException(status_code=409, detail=f"Persona '{key}' already exists")

    config["style"]["personas"][key] = {
        "name": request.name.strip(),
        "prompt": request.prompt.strip(),
    }

    if request.is_default:
        config["style"]["default_persona"] = key

    _save_config(config)
    _reload_pipeline()

    return PersonaResponse(
        key=key,
        name=request.name.strip(),
        prompt=request.prompt.strip(),
        is_default=request.is_default,
    )


@app.put("/personas/{key}", response_model=PersonaResponse)
async def update_persona(key: str, request: PersonaRequest):
    """Update an existing persona."""
    config = _load_config()
    personas = config.get("style", {}).get("personas", {})

    if key not in personas:
        raise HTTPException(status_code=404, detail=f"Persona '{key}' not found")

    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    new_key = request.key.strip().lower().replace(" ", "_")

    # Handle key change
    if new_key != key:
        if new_key in personas:
            raise HTTPException(status_code=409, detail=f"Persona '{new_key}' already exists")
        del config["style"]["personas"][key]
        # Update default if needed
        if config.get("style", {}).get("default_persona") == key:
            config["style"]["default_persona"] = new_key

    config["style"]["personas"][new_key] = {
        "name": request.name.strip(),
        "prompt": request.prompt.strip(),
    }

    if request.is_default:
        config["style"]["default_persona"] = new_key

    _save_config(config)
    _reload_pipeline()

    return PersonaResponse(
        key=new_key,
        name=request.name.strip(),
        prompt=request.prompt.strip(),
        is_default=request.is_default,
    )


@app.delete("/personas/{key}", status_code=204)
async def delete_persona(key: str):
    """Delete a persona."""
    config = _load_config()
    personas = config.get("style", {}).get("personas", {})

    if key not in personas:
        raise HTTPException(status_code=404, detail=f"Persona '{key}' not found")

    del config["style"]["personas"][key]

    # Clear default if deleted persona was default
    if config.get("style", {}).get("default_persona") == key:
        config["style"]["default_persona"] = ""

    _save_config(config)
    _reload_pipeline()


@app.patch("/personas/{key}/default", response_model=PersonaResponse)
async def set_default_persona(key: str):
    """Set a persona as the default."""
    config = _load_config()
    personas = config.get("style", {}).get("personas", {})

    if key not in personas:
        raise HTTPException(status_code=404, detail=f"Persona '{key}' not found")

    config["style"]["default_persona"] = key
    _save_config(config)
    _reload_pipeline()

    info = personas[key]
    return PersonaResponse(
        key=key,
        name=info.get("name", key),
        prompt=info.get("prompt", ""),
        is_default=True,
    )


# =============================================================================
# Model Management Endpoints
# =============================================================================


@app.get("/models", response_model=ModelListResponse)
async def list_models():
    """List available Ollama models."""
    pipeline = get_pipeline()
    models = pipeline.style_transformer.list_models()
    current = pipeline.style_transformer.get_current_model()

    return ModelListResponse(models=models, current_model=current)


@app.put("/models/current", response_model=ModelListResponse)
async def set_current_model(request: ModelSetRequest):
    """Set the current Ollama model."""
    pipeline = get_pipeline()
    available_models = pipeline.style_transformer.list_models()

    # Check if model exists (allow partial match for tags)
    model_base = request.model.split(":")[0]
    found = False
    for available in available_models:
        if available == request.model or available.startswith(model_base + ":"):
            found = True
            break

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{request.model}' not found. Available: {available_models}"
        )

    # Update config and pipeline
    config = _load_config()
    if "ollama" not in config:
        config["ollama"] = {}
    config["ollama"]["model"] = request.model
    _save_config(config)

    pipeline.style_transformer.set_model(request.model)

    return ModelListResponse(models=available_models, current_model=request.model)


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the API server."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Aletheia API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--config", type=str, help="Path to config.yaml file")

    args = parser.parse_args()

    if args.config:
        get_config(args.config)

    run_server(args.host, args.port)
