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
            # Preflight: часто на Windows ffmpeg.exe не стартует из-за отсутствующих DLL.
            _run_checked([ffmpeg, "-version"], step="ffmpeg preflight check")
            _run_checked([ffprobe, "-version"], step="ffprobe preflight check")

            out_dir = Path(self.output_path).resolve().parent
            out_dir.mkdir(parents=True, exist_ok=True)

            total = len(self.chapters)
            aac_files: list[str] = []
            source_durations = [max(0.01, get_duration_seconds(ch.file_path)) for ch in self.chapters]
            total_duration = max(0.01, sum(source_durations))
            processed_duration = 0.0

            # ── Шаг 1: конвертируем каждый MP3 → AAC (.m4a) ─────────────
            for i, ch in enumerate(self.chapters):
                if self._cancelled:
                    return
                self.status.emit(f"Конвертация {i+1}/{total}: {Path(ch.file_path).name}")
                aac_path = os.path.join(tmp_dir, f"chapter_{i:04d}.m4a")
                chapter_duration = source_durations[i]

                def _update_chapter_progress(out_time_sec: float):
                    if out_time_sec == float("inf"):
                        out_time_sec = chapter_duration
                    clamped = min(chapter_duration, max(0.0, out_time_sec))
                    absolute = (processed_duration + clamped) / total_duration
                    self.progress.emit(int(min(60, max(0, absolute * 60))))

                progress_cmd = [
                    ffmpeg, "-y", "-v", "error", "-nostats",
                    "-progress", "pipe:1",
                    "-i", ch.file_path,
                    "-vn",                  # без видео
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-ar", "44100",
                    aac_path,
                ]
                _run_ffmpeg_with_progress(
                    progress_cmd,
                    step=f"Converting chapter {i+1}/{total}",
                    on_progress=_update_chapter_progress,
                )
                aac_files.append(aac_path)
                processed_duration += chapter_duration
                self.progress.emit(int(min(60, max(0, (processed_duration / total_duration) * 60))))

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

            cmd_base = [
                ffmpeg, "-y",
                "-i", merged,
                "-f", "ffmetadata",
                "-i", meta_file,
                "-map_metadata", "1",
                "-map_chapters", "1",
            ]

            cmd_with_cover = None
            if self.cover_path and os.path.isfile(self.cover_path):
                cmd_with_cover = cmd_base + [
                    "-i", self.cover_path,
                    "-map", "0:a",
                    "-map", "2:v",
                    "-c:v", "copy",
                    "-disposition:v", "attached_pic",
                ]

            cmd_no_cover = cmd_base + [
                "-map", "0:a",
                "-c:a", "copy",
                "-movflags", "+faststart",
                self.output_path,
            ]

            if cmd_with_cover is not None:
                cmd_with_cover += [
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    self.output_path,
                ]

            # Иногда конкретная обложка/кодек не поддерживаются контейнером M4B.
            # В таком случае сохраняем книгу без обложки вместо полного провала.
            if cmd_with_cover is not None:
                try:
                    _run_checked(cmd_with_cover, step="Final M4B muxing (with cover)")
                except Exception:
                    self.status.emit("Обложка не применена, повтор без обложки…")
                    _run_checked(cmd_no_cover, step="Final M4B muxing (without cover)")
            else:
                _run_checked(cmd_no_cover, step="Final M4B muxing")

            self.progress.emit(100)
            self.status.emit("Готово!")
            self.finished.emit(self.output_path)

        finally:
            # Удаляем временные файлы
            shutil.rmtree(tmp_dir, ignore_errors=True)
