"""Folder-based watch mode for TouchDesigner integration.

Watches an input directory for new WAV files, processes them through
the Aletheia pipeline sequentially, and writes results to an output directory.
"""

import logging
import shutil
import time
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread

from .pipeline import AletheiaPipeline
from .printing import print_file, print_text, print_positioned_text

logger = logging.getLogger(__name__)


class FolderWatcher:
    """Watches a folder for new WAV files and queues them for processing."""

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path,
        pipeline: AletheiaPipeline,
        poll_interval: float = 0.5,
        style_prompt: str | None = None,
        persona: str | None = None,
        skip_filter: bool = False,
        skip_transform: bool = False,
        auto_print: bool = False,
        printer_name: str | None = None,
        paper_size: str = "",
        landscape: bool = False,
        font_size_ko: int = 12,
        font_size_en: int = 12,
        font_name_ko: str = "Malgun Gothic",
        font_name_en: str = "Arial",
        layout: dict | None = None,
        margin_lr: int = 60,
    ):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.done_dir = self.input_dir / "done"
        self.pipeline = pipeline
        self.poll_interval = poll_interval
        self.style_prompt = style_prompt
        self.persona = persona
        self.skip_filter = skip_filter
        self.skip_transform = skip_transform
        self.auto_print = auto_print
        self.printer_name = printer_name
        self.paper_size = paper_size
        self.landscape = landscape
        self.font_size_ko = font_size_ko
        self.font_size_en = font_size_en
        self.font_name_ko = font_name_ko
        self.font_name_en = font_name_en
        self.layout = layout
        self.margin_lr = margin_lr

        self.backup_input_dir = self.output_dir / "backup" / "input"
        self.backup_output_dir = self.output_dir / "backup" / "output"
        self._backup_index: int = 0

        self.queue: Queue[Path] = Queue()
        self._stop_event = Event()
        self._known_files: set[str] = set()
        self._log_lines: list[tuple[float, str]] = []
        self._log_lock = Lock()
        self._pending_files: list[Path] = []
        self._pending_lock = Lock()
        self._current_file: Path | None = None

    @property
    def is_running(self) -> bool:
        """Return True if the watcher threads are active."""
        return not self._stop_event.is_set()

    def _log(self, message: str):
        """Append a timestamped log line."""
        with self._log_lock:
            self._log_lines.append((time.time(), message))

    def get_logs(self, since: float = 0.0) -> list[str]:
        """Return log lines with timestamp > *since*."""
        with self._log_lock:
            return [msg for ts, msg in self._log_lines if ts > since]

    def start(self):
        """Start the watcher and worker threads (non-blocking)."""
        self._stop_event.clear()

        # Create directories
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.done_dir.mkdir(parents=True, exist_ok=True)
        self.backup_input_dir.mkdir(parents=True, exist_ok=True)
        self.backup_output_dir.mkdir(parents=True, exist_ok=True)

        # Scan existing backup files to resume index
        existing = [int(f.stem) for d in (self.backup_input_dir, self.backup_output_dir)
                     for f in d.glob("*.txt") if f.stem.isdigit()]
        self._backup_index = max(existing) if existing else 0

        # Mark files already present at startup as known (skip processing)
        _audio_globs = ["*.[wW][aA][vV]", "*.[mM][pP]3"]
        for pattern in _audio_globs:
            for f in self.input_dir.glob(pattern):
                self._known_files.add(f.name)
        if self._known_files:
            msg = f"Found {len(self._known_files)} existing audio file(s), skipped"
            logger.info(msg)
            self._log(msg)

        # Start threads
        watcher_thread = Thread(target=self._poll_loop, name="watcher", daemon=True)
        worker_thread = Thread(target=self._worker_loop, name="worker", daemon=True)
        watcher_thread.start()
        worker_thread.start()

        logger.info("Watch mode started")
        logger.info("  Input:  %s", self.input_dir.resolve())
        logger.info("  Output: %s", self.output_dir.resolve())
        logger.info("  Done:   %s", self.done_dir.resolve())
        self._log(f"Watch mode started  Input: {self.input_dir.resolve()}  Output: {self.output_dir.resolve()}")

    def run_forever(self):
        """Block the calling thread until stopped (for CLI use)."""
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=1.0)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.stop()

    def get_queue_status(self) -> tuple[str | None, list[str]]:
        """Return (current_file_name, list_of_pending_file_names)."""
        with self._pending_lock:
            current = self._current_file.name if self._current_file else None
            pending = [f.name for f in self._pending_files]
        return current, pending

    def cancel_file(self, filename: str) -> bool:
        """Cancel a pending file by name. Returns True if removed."""
        with self._pending_lock:
            for f in self._pending_files:
                if f.name == filename:
                    self._pending_files.remove(f)
                    self._log(f"Cancelled: {filename}")
                    return True
        return False

    def clear_queue(self) -> int:
        """Cancel all pending files. Returns count removed."""
        with self._pending_lock:
            count = len(self._pending_files)
            self._pending_files.clear()
        if count:
            self._log(f"Queue cleared: {count} file(s) cancelled")
        return count

    def stop(self):
        """Signal threads to stop."""
        self._stop_event.set()
        with self._pending_lock:
            self._pending_files.clear()
        self._current_file = None
        self._log("Watch mode stopped")

    def _poll_loop(self):
        """Poll input directory for new audio files (WAV, MP3)."""
        _audio_globs = ["*.[wW][aA][vV]", "*.[mM][pP]3"]
        while not self._stop_event.is_set():
            try:
                # Case-insensitive match for .wav/.mp3 on WSL
                for pattern in _audio_globs:
                    for f in sorted(self.input_dir.glob(pattern)):
                        if f.name not in self._known_files:
                            self._known_files.add(f.name)
                            self.queue.put(f)
                            with self._pending_lock:
                                self._pending_files.append(f)
                            logger.info("Queued: %s", f.name)
                            self._log(f"Queued: {f.name}")
            except Exception as e:
                logger.warning("Error scanning input directory: %s", e)
                self._log(f"Poll error: {e}")

            self._stop_event.wait(timeout=self.poll_interval)

    def _wait_until_stable(self, file_path: Path, timeout: float = 5.0) -> bool:
        """Wait until a file's size stops changing (copy finished)."""
        deadline = time.time() + timeout
        prev_size = -1
        while time.time() < deadline:
            try:
                size = file_path.stat().st_size
            except OSError:
                return False
            if size == prev_size and size > 0:
                return True
            prev_size = size
            time.sleep(0.3)
        return prev_size > 0

    def _worker_loop(self):
        """Process queued files one by one."""
        while not self._stop_event.is_set():
            try:
                file_path = self.queue.get(timeout=1.0)
            except Empty:
                continue

            # Check if cancelled (removed from _pending_files)
            with self._pending_lock:
                if file_path not in self._pending_files:
                    logger.info("Skipped (cancelled): %s", file_path.name)
                    self._log(f"Skipped (cancelled): {file_path.name}")
                    continue
                self._pending_files.remove(file_path)
                self._current_file = file_path

            try:
                if not file_path.exists():
                    logger.warning("File disappeared before processing: %s", file_path.name)
                    continue

                if not self._wait_until_stable(file_path):
                    logger.warning("File not stable, skipping: %s", file_path.name)
                    self._log(f"Skipped (incomplete): {file_path.name}")
                    continue

                self._process_file(file_path)
            except Exception as e:
                logger.exception("Worker error for %s: %s", file_path.name, e)
                self._log(f"ERROR: {file_path.name}: {e}")
            finally:
                self._current_file = None

    def _process_file(self, file_path: Path):
        """Process a single WAV file and save the result."""
        stem = file_path.stem
        output_path = self.output_dir / f"{stem}.txt"

        logger.info("Processing: %s", file_path.name)
        self._log(f"Processing: {file_path.name}")
        try:
            result = self.pipeline.process_file(
                file_path,
                style_prompt=self.style_prompt,
                persona=self.persona,
                skip_filter=self.skip_filter,
                skip_transform=self.skip_transform,
            )

            # Write transformed text to output
            output_path.write_text(result.transformed_text, encoding="utf-8")
            logger.info("Output: %s", output_path.name)
            self._log(f"Output: {output_path.name}")

            # Backup input/output pair
            try:
                self._backup_index += 1
                idx = f"{self._backup_index:04d}"
                self.backup_input_dir.joinpath(f"{idx}.txt").write_text(
                    result.original_text or "", encoding="utf-8")
                self.backup_output_dir.joinpath(f"{idx}.txt").write_text(
                    result.transformed_text or "", encoding="utf-8")
                self._log(f"Backup: {idx}")
            except Exception as backup_err:
                logger.warning("Backup failed for index %s: %s", self._backup_index, backup_err)
                self._log(f"Backup failed: {backup_err}")

            # Auto-print if enabled (input + output together)
            if self.auto_print and self.printer_name:
                input_text = result.original_text or ""
                output_text = result.transformed_text or ""
                lang = getattr(result, "language", "ko")
                font = self.font_name_ko if lang == "ko" else self.font_name_en
                fs = self.font_size_ko if lang == "ko" else self.font_size_en
                if self.layout:
                    printed = print_positioned_text(
                        input_text, output_text, self.printer_name,
                        paper_size=self.paper_size, landscape=self.landscape,
                        font_size=fs, font_name=font,
                        input_y_pct=self.layout.get("input_y_pct", 10.0),
                        output_y_pct=self.layout.get("output_y_pct", 55.0),
                        draw_separator=self.layout.get("separator", True),
                        margin_lr=self.margin_lr,
                    )
                else:
                    print_content = f"{input_text}\n\n---\n\n{output_text}"
                    printed = print_text(print_content, self.printer_name, self.paper_size, self.landscape, fs, font, margin_lr=self.margin_lr)
                if printed:
                    logger.info("Printed: %s -> %s", output_path.name, self.printer_name)
                    self._log(f"Printed: {output_path.name} -> {self.printer_name}")
                else:
                    self._log(f"Print failed: {output_path.name}")

            # Move processed file to done/
            try:
                dest = self.done_dir / file_path.name
                shutil.move(str(file_path), str(dest))
                logger.info("Moved to done: %s", file_path.name)
            except OSError as move_err:
                logger.warning("Could not move to done/: %s", move_err)

            self._log(f"Done: {file_path.name}")

        except Exception as exc:
            logger.exception("Error processing %s", file_path.name)
            self._log(f"ERROR processing {file_path.name}: {exc}")
