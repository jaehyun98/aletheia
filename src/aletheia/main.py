"""CLI entry point for Aletheia."""

import argparse
import logging
import sys
from pathlib import Path

# Suppress noisy Windows asyncio connection-reset warnings
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

from .config import get_config
from .pipeline import AletheiaPipeline


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Aletheia - Voice/Text Style Transformation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  aletheia -i audio -o audio    # Audio input -> Audio output
  aletheia -i audio -o text     # Audio input -> Text output
  aletheia -i text -o audio     # Text input -> Audio output
  aletheia -i text -o text      # Text input -> Text output
  aletheia -i audio -o both     # Audio input -> Text + Audio output
  aletheia --check              # Check service status

Watch mode (TouchDesigner integration):
  aletheia --watch                           # Use config.yaml defaults
  aletheia --watch --input-dir ./in --output-dir ./out

Persona examples:
  aletheia --list-personas              # List available presets
  aletheia -t "Hello" -p casual         # Use preset
  aletheia -t "Hello" -p comedian       # Comedian persona
  aletheia -t "Hello" -p "Custom prompt"  # Custom persona
        """,
    )
    parser.add_argument(
        "--input", "-i", type=str, choices=["text", "audio"], default="text",
        help="Input mode: text or audio (default: text)"
    )
    parser.add_argument(
        "--output", "-o", type=str, choices=["text", "audio", "both"], default="text",
        help="Output mode: text, audio, or both (default: text)"
    )
    parser.add_argument(
        "--text", "-t", type=str, help="Text to process (when input=text)"
    )
    parser.add_argument(
        "--file", "-f", type=str, help="Path to audio file (when input=audio)"
    )
    parser.add_argument(
        "--config", "-c", type=str, help="Path to config.yaml file"
    )
    parser.add_argument(
        "--style", "-s", type=str, help="Custom style prompt"
    )
    parser.add_argument(
        "--persona", "-p", type=str,
        help="Persona preset name (e.g., assistant, casual, professional) or custom prompt"
    )
    parser.add_argument(
        "--list-personas", action="store_true", help="List available persona presets"
    )
    parser.add_argument(
        "--no-filter", action="store_true", help="Skip content filtering"
    )
    parser.add_argument(
        "--no-transform", action="store_true", help="Skip style transformation"
    )
    parser.add_argument(
        "--stream", action="store_true", help="Enable streaming output"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check service status and exit"
    )
    parser.add_argument(
        "--loop", "-l", action="store_true", help="Continuous mode"
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Watch mode: monitor input folder for WAV files and process sequentially"
    )
    parser.add_argument(
        "--input-dir", type=str,
        help="Input directory for watch mode (default: from config.yaml)"
    )
    parser.add_argument(
        "--output-dir", type=str,
        help="Output directory for watch mode (default: from config.yaml)"
    )
    parser.add_argument(
        "--poll-interval", type=float,
        help="Polling interval in seconds for watch mode (default: from config.yaml)"
    )

    args = parser.parse_args()

    # Initialize config
    config_path = args.config
    if config_path:
        config_path = Path(config_path)
        if not config_path.exists():
            print(f"Error: Config file not found: {config_path}")
            sys.exit(1)

    # Create pipeline
    try:
        pipeline = AletheiaPipeline(config_path)
    except Exception as e:
        print(f"Error initializing pipeline: {e}")
        sys.exit(1)

    # Check services
    if args.check:
        print("Checking services...")
        status = pipeline.check_services()
        for service, available in status.items():
            status_str = "OK" if available else "FAIL"
            print(f"  [{status_str}] {service}")
        sys.exit(0 if all(status.values()) else 1)

    # List personas
    if args.list_personas:
        print("Available persona presets:\n")
        personas = pipeline.style_transformer.list_personas()
        default_key = pipeline.style_transformer.default_persona_key
        for key, name in personas.items():
            marker = " (default)" if key == default_key else ""
            print(f"  {key:15} - {name}{marker}")
        print(f"\nUsage: aletheia -p <preset_name>")
        print(f"       aletheia -p \"custom persona prompt\"")
        sys.exit(0)

    # Watch mode
    if args.watch:
        from .watch import FolderWatcher

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )

        cfg = get_config()

        input_dir = Path(args.input_dir or cfg.get("watch.input_dir", "./input"))
        output_dir = Path(args.output_dir or cfg.get("watch.output_dir", "./output"))
        poll_interval = args.poll_interval or cfg.get("watch.poll_interval", 0.5)

        # Load print settings from config (saved by GUI)
        auto_print = cfg.get("printing.auto_print", False)
        printer_name = cfg.get("printing.printer_name", "")
        paper_size = cfg.get("printing.paper_size", "A4")
        landscape = cfg.get("printing.landscape", False)
        font_size = cfg.get("printing.font_size", 12)
        font_name = cfg.get("printing.font_name", "Malgun Gothic")

        # Use persona from CLI arg or default from config
        persona = args.persona or pipeline.style_transformer.default_persona_key or None

        watcher = FolderWatcher(
            input_dir=input_dir,
            output_dir=output_dir,
            pipeline=pipeline,
            poll_interval=poll_interval,
            style_prompt=args.style,
            persona=persona,
            skip_filter=args.no_filter,
            skip_transform=args.no_transform,
            auto_print=auto_print,
            printer_name=printer_name if printer_name else None,
            paper_size=paper_size,
            landscape=landscape,
            font_size=font_size,
            font_name=font_name,
        )
        watcher.start()
        watcher.run_forever()
        sys.exit(0)

    # Determine output settings
    speak = args.output in ("audio", "both")
    show_text = args.output in ("text", "both")

    # Process based on input mode
    try:
        if args.input == "text":
            # Text input mode
            if not args.text:
                # Interactive text input
                if args.loop:
                    print("Interactive text mode. Type 'exit' or Ctrl+C to quit.\n")
                    while True:
                        try:
                            text = input("You: ").strip()
                            if text.lower() == "exit":
                                break
                            if not text:
                                continue
                            result = pipeline.process_text(
                                text,
                                style_prompt=args.style,
                                persona=args.persona,
                                skip_filter=args.no_filter,
                                skip_transform=args.no_transform,
                                speak=speak,
                            )
                            if show_text:
                                print(f"Out: {result.transformed_text}\n")
                        except KeyboardInterrupt:
                            print("\nExiting...")
                            break
                else:
                    text = input("Enter text: ").strip()
                    if text:
                        result = pipeline.process_text(
                            text,
                            style_prompt=args.style,
                            persona=args.persona,
                            skip_filter=args.no_filter,
                            skip_transform=args.no_transform,
                            speak=speak,
                        )
                        if show_text:
                            print_result(result)
            else:
                # Text provided via argument
                if args.stream and show_text:
                    print("Transformed: ", end="", flush=True)
                    for chunk in pipeline.process_stream(
                        args.text,
                        style_prompt=args.style,
                        persona=args.persona,
                        skip_filter=args.no_filter,
                    ):
                        print(chunk, end="", flush=True)
                    print()
                    if speak:
                        # Speak after streaming complete
                        result = pipeline.process_text(
                            args.text,
                            style_prompt=args.style,
                            persona=args.persona,
                            skip_filter=args.no_filter,
                            skip_transform=args.no_transform,
                            speak=True,
                        )
                else:
                    result = pipeline.process_text(
                        args.text,
                        style_prompt=args.style,
                        persona=args.persona,
                        skip_filter=args.no_filter,
                        skip_transform=args.no_transform,
                        speak=speak,
                    )
                    if show_text:
                        print_result(result)

        elif args.input == "audio":
            # Audio input mode
            if args.file:
                # File input
                file_path = Path(args.file)
                if not file_path.exists():
                    print(f"Error: File not found: {file_path}")
                    sys.exit(1)

                result = pipeline.process_file(
                    file_path,
                    style_prompt=args.style,
                    persona=args.persona,
                    skip_filter=args.no_filter,
                    skip_transform=args.no_transform,
                    speak=speak,
                )
                if show_text:
                    print_result(result)
            else:
                # Microphone input
                if args.loop:
                    print("Voice mode. Press Ctrl+C to exit.\n")
                    while True:
                        try:
                            result = pipeline.process_microphone(
                                style_prompt=args.style,
                                persona=args.persona,
                                skip_filter=args.no_filter,
                                skip_transform=args.no_transform,
                                speak=speak,
                            )
                            if result.original_text:
                                if show_text:
                                    print(f"In:  {result.original_text}")
                                    print(f"Out: {result.transformed_text}\n")
                        except KeyboardInterrupt:
                            print("\nExiting...")
                            break
                else:
                    result = pipeline.process_microphone(
                        style_prompt=args.style,
                        persona=args.persona,
                        skip_filter=args.no_filter,
                        skip_transform=args.no_transform,
                        speak=speak,
                    )
                    if show_text:
                        print_result(result)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def print_result(result):
    """Print pipeline result."""
    print("\n" + "=" * 40)
    print(f"Original:    {result.original_text}")
    if result.filtered_words:
        print(f"Filtered:    {result.filtered_text}")
        print(f"Removed:     {result.filtered_words}")
    print(f"Transformed: {result.transformed_text}")
    print("=" * 40)


if __name__ == "__main__":
    main()
