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
from .printing import print_file

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
        font_size: int = 12,
        font_name: str = "Malgun Gothic",
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
        self.font_size = font_size
        self.font_name = font_name

        self.queue: Queue[Path] = Queue()
        self._stop_event = Event()
        self._known_files: set[str] = set()
        self._log_lines: list[tuple[float, str]] = []
        self._log_lock = Lock()

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

    def stop(self):
        """Signal threads to stop."""
        self._stop_event.set()
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

            # Auto-print if enabled
            if self.auto_print and self.printer_name:
                if print_file(output_path, self.printer_name, self.paper_size, self.landscape, self.font_size, self.font_name):
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
