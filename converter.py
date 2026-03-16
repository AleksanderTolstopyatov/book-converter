"""
converter.py — логика конвертации MP3 → M4B с главами и метаданными.
Запускается в отдельном QThread чтобы не блокировать UI.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QThread, Signal


@dataclass
class Chapter:
    file_path: str
    title: str


def _bundle_dir() -> Path:
    """Папка с бинарниками: при запуске из PyInstaller bundle — _MEIPASS,
    иначе — директория скрипта."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _find_binary(name: str) -> str:
    """Ищет бинарник: сначала в bundle, потом в PATH и стандартных местах."""
    is_win = platform.system() == "Windows"
    exe_name = name + ".exe" if is_win else name

    # 1. Внутри PyInstaller bundle (или рядом со скриптом)
    bundled = _bundle_dir() / exe_name
    if bundled.is_file():
        return str(bundled)

    # 2. PATH
    found = shutil.which(name)
    if found:
        return found

    # 3. Явные пути (brew, apt, winget)
    candidates = [
        "/opt/homebrew/bin/" + name,
        "/usr/local/bin/" + name,
        os.path.join(r"C:\ffmpeg\bin", exe_name),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    raise FileNotFoundError(
        f"{name} не найден.\n"
        "  macOS:   brew install ffmpeg\n"
        "  Windows: winget install ffmpeg\n"
        "  Linux:   sudo apt install ffmpeg"
    )


def _ffmpeg() -> str:
    return _find_binary("ffmpeg")


def _embed_cover(m4b_path: str, cover_path: str) -> None:
    """Вшивает обложку в M4B через mutagen (covr-атом MP4).

    Apple Books, VLC и все совместимые плееры читают именно covr-атом,
    а не видеодорожку. WEBP/BMP конвертируются в JPEG через Pillow.
    """
    from mutagen.mp4 import MP4, MP4Cover

    ext = Path(cover_path).suffix.lower()

    if ext in (".jpg", ".jpeg"):
        img_fmt = MP4Cover.FORMAT_JPEG
        with open(cover_path, "rb") as f:
            cover_data = f.read()
    elif ext == ".png":
        img_fmt = MP4Cover.FORMAT_PNG
        with open(cover_path, "rb") as f:
            cover_data = f.read()
    else:
        # WEBP, BMP и прочие — конвертируем в JPEG через Pillow
        from PIL import Image
        import io
        with Image.open(cover_path) as img:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=90)
            cover_data = buf.getvalue()
        img_fmt = MP4Cover.FORMAT_JPEG

    tags = MP4(m4b_path)
    tags["covr"] = [MP4Cover(cover_data, imageformat=img_fmt)]
    tags.save()


def _windows_no_console_kwargs() -> dict:
    """Параметры subprocess для скрытого запуска на Windows."""
    if platform.system() != "Windows":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def _run_checked(cmd: list[str], step: str) -> subprocess.CompletedProcess:
    """Запускает процесс и возвращает подробную ошибку при неуспехе."""
    run_kwargs: dict = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    run_kwargs.update(_windows_no_console_kwargs())

    result = subprocess.run(
        cmd,
        **run_kwargs,
    )
    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip()[-3000:]
        stdout_tail = (result.stdout or "").strip()[-3000:]
        details = stderr_tail or stdout_tail or "No output from process."
        cmd_preview = " ".join(f'"{part}"' if " " in part else part for part in cmd)
        raise RuntimeError(
            f"{step} failed (exit code {result.returncode}).\n"
            f"Command: {cmd_preview}\n\n"
            f"Process output:\n{details}"
        )
    return result


def _run_ffmpeg_with_progress(
    cmd: list[str],
    step: str,
    on_progress: Callable[[float], None],
) -> None:
    """Запускает ffmpeg и репортит прогресс 0..1 по out_time_ms."""
    popen_kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    popen_kwargs.update(_windows_no_console_kwargs())

    proc = subprocess.Popen(cmd, **popen_kwargs)
    stdout_lines: list[str] = []

    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        stdout_lines.append(line)
        if line.startswith("out_time_ms="):
            raw = line.split("=", 1)[1].strip()
            try:
                out_time_sec = max(0.0, float(raw) / 1_000_000.0)
                # Будет ограничено вызывающим кодом через свою шкалу.
                on_progress(out_time_sec)
            except ValueError:
                pass
        elif line.startswith("progress=end"):
            on_progress(float("inf"))

    stderr_tail = ""
    if proc.stderr is not None:
        stderr_tail = proc.stderr.read()

    if proc.returncode != 0:
        stdout_tail = "".join(stdout_lines)[-3000:]
        stderr_tail = (stderr_tail or "")[-3000:]
        details = stderr_tail or stdout_tail or "No output from process."
        cmd_preview = " ".join(f'"{part}"' if " " in part else part for part in cmd)
        raise RuntimeError(
            f"{step} failed (exit code {proc.returncode}).\n"
            f"Command: {cmd_preview}\n\n"
            f"Process output:\n{details}"
        )


def get_duration_seconds(file_path: str) -> float:
    """Возвращает длительность аудиофайла в секундах через ffprobe."""
    ffprobe = _find_binary("ffprobe")
    result = _run_checked(
        [
            ffprobe, "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path,
        ],
        step=f"Reading duration for {Path(file_path).name}",
    )
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


class ConversionWorker(QThread):
    """Фоновый поток конвертации. Эмитирует сигналы прогресса и статуса."""

    progress = Signal(int)        # 0..100
    status = Signal(str)          # текстовый статус
    finished = Signal(str)        # путь к выходному файлу
    error = Signal(str)           # сообщение об ошибке

    def __init__(
        self,
        chapters: List[Chapter],
        output_path: str,
        title: str,
        author: str,
        cover_path: Optional[str],
        parent=None,
    ):
        super().__init__(parent)
        self.chapters = chapters
        self.output_path = output_path
        self.title = title
        self.author = author
        self.cover_path = cover_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    # ------------------------------------------------------------------
    def run(self):
        try:
            self._convert()
        except Exception as exc:
            self.error.emit(str(exc))

    # ------------------------------------------------------------------
    def _convert(self):
        ffmpeg = _ffmpeg()
        ffprobe = _find_binary("ffprobe")
        tmp_dir = tempfile.mkdtemp(prefix="audiobook_")

        try:
            out_dir = Path(self.output_path).resolve().parent
            out_dir.mkdir(parents=True, exist_ok=True)

            total = len(self.chapters)
            # Имена выходных файлов фиксированы заранее для правильного порядка.
            aac_files: list[str] = [
                os.path.join(tmp_dir, f"chapter_{i:04d}.m4a") for i in range(total)
            ]
            source_durations = [max(0.01, get_duration_seconds(ch.file_path)) for ch in self.chapters]
            total_duration = max(0.01, sum(source_durations))

            # Прогресс каждой главы в секундах: индекс → текущая позиция.
            # Суммируем все потоки — прогресс всегда только растёт.
            _lock = threading.Lock()
            _per_chapter: dict[int, float] = {i: 0.0 for i in range(total)}

            def _emit_progress() -> None:
                """Считает суммарный прогресс по всем потокам и эмитит сигнал."""
                total_done = sum(_per_chapter.values())
                self.progress.emit(int(min(60, total_done / total_duration * 60)))

            def _convert_chapter(i: int) -> None:
                """Конвертирует одну главу; вызывается из пула потоков."""
                if self._cancelled:
                    return
                ch = self.chapters[i]
                aac_path = aac_files[i]
                chapter_duration = source_durations[i]

                self.status.emit(f"Конвертация {i+1}/{total}: {Path(ch.file_path).name}")

                def _on_progress(out_time_sec: float):
                    if self._cancelled:
                        return
                    if out_time_sec == float("inf"):
                        out_time_sec = chapter_duration
                    with _lock:
                        _per_chapter[i] = min(chapter_duration, max(_per_chapter[i], out_time_sec))
                        _emit_progress()

                _run_ffmpeg_with_progress(
                    [
                        ffmpeg, "-y", "-v", "error", "-nostats",
                        "-progress", "pipe:1",
                        "-i", ch.file_path,
                        "-vn",
                        "-c:a", "aac",
                        "-b:a", "128k",
                        "-ar", "44100",
                        aac_path,
                    ],
                    step=f"Converting chapter {i+1}/{total}",
                    on_progress=_on_progress,
                )

                with _lock:
                    _per_chapter[i] = chapter_duration
                    _emit_progress()

            # ── Шаг 1: параллельная конвертация MP3 → AAC ────────────────
            # Используем min(4, total) потоков — больше нет смысла,
            # т.к. ffmpeg сам использует несколько ядер внутри.
            workers = min(4, total, os.cpu_count() or 4)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_convert_chapter, i): i for i in range(total)}
                for future in as_completed(futures):
                    if self._cancelled:
                        pool.shutdown(wait=False, cancel_futures=True)
                        return
                    exc = future.exception()
                    if exc:
                        pool.shutdown(wait=False, cancel_futures=True)
                        raise exc

            # ── Шаг 2: конкатенируем через concat demuxer ─────────────────
            if self._cancelled:
                return
            self.status.emit("Объединение файлов…")
            list_file = os.path.join(tmp_dir, "list.txt")
            with open(list_file, "w", encoding="utf-8") as f:
                for p in aac_files:
                    # Экранируем одинарные кавычки в пути
                    safe = p.replace("'", "'\\''")
                    f.write(f"file '{safe}'\n")

            merged = os.path.join(tmp_dir, "merged.m4a")
            _run_checked(
                [
                    ffmpeg, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", list_file,
                    "-c", "copy",
                    merged,
                ],
                step="Merging chapters",
            )
            self.progress.emit(75)

            # ── Шаг 3: собираем файл метаданных с главами ─────────────────
            if self._cancelled:
                return
            self.status.emit("Генерация глав…")

            # Используем длительности исходных файлов, чтобы избежать лишних запусков ffprobe.
            durations = source_durations
            meta_file = os.path.join(tmp_dir, "metadata.txt")
            with open(meta_file, "w", encoding="utf-8") as f:
                f.write(";FFMETADATA1\n")
                f.write(f"title={self.title}\n")
                f.write(f"artist={self.author}\n")
                f.write(f"album={self.title}\n")
                f.write("genre=Audiobook\n\n")

                start_ms = 0
                for ch, dur in zip(self.chapters, durations):
                    end_ms = start_ms + int(dur * 1000)
                    f.write("[CHAPTER]\n")
                    f.write("TIMEBASE=1/1000\n")
                    f.write(f"START={start_ms}\n")
                    f.write(f"END={end_ms}\n")
                    f.write(f"title={ch.title}\n\n")
                    start_ms = end_ms

            self.progress.emit(82)

            # ── Шаг 4: финальная сборка M4B (с главами и обложкой) ───────
            if self._cancelled:
                return
            self.status.emit("Финальная сборка M4B…")

            # ── Шаг 4: финальная сборка M4B (без обложки — её добавим через mutagen) ─
            _run_checked(
                [
                    ffmpeg, "-y",
                    "-i", merged,
                    "-f", "ffmetadata", "-i", meta_file,
                    "-map", "0:a",
                    "-map_metadata", "1",
                    "-map_chapters", "1",
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    self.output_path,
                ],
                step="Final M4B muxing",
            )
            self.progress.emit(95)

            # ── Шаг 5: обложка через mutagen (covr атом — единственный надёжный способ) ─
            if self.cover_path and os.path.isfile(self.cover_path):
                self.status.emit("Добавление обложки…")
                try:
                    _embed_cover(self.output_path, self.cover_path)
                except Exception as e:
                    # Обложка не критична — книга уже создана, просто предупреждаем.
                    self.status.emit(f"Обложка не добавлена: {e}")

            self.progress.emit(100)
            self.status.emit("Готово!")
            self.finished.emit(self.output_path)

        finally:
            # Удаляем временные файлы
            shutil.rmtree(tmp_dir, ignore_errors=True)
