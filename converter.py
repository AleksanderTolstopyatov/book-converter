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
from typing import List, Optional

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


def get_duration_seconds(file_path: str) -> float:
    """Возвращает длительность аудиофайла в секундах через ffprobe."""
    ffprobe = _find_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe, "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path,
        ],
        capture_output=True,
        text=True,
        check=True,
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
        tmp_dir = tempfile.mkdtemp(prefix="audiobook_")

        try:
            total = len(self.chapters)
            aac_files: list[str] = []

            # ── Шаг 1: конвертируем каждый MP3 → AAC (.m4a) ─────────────
            for i, ch in enumerate(self.chapters):
                if self._cancelled:
                    return
                self.status.emit(f"Конвертация {i+1}/{total}: {Path(ch.file_path).name}")
                aac_path = os.path.join(tmp_dir, f"chapter_{i:04d}.m4a")
                subprocess.run(
                    [
                        ffmpeg, "-y", "-i", ch.file_path,
                        "-vn",                  # без видео
                        "-c:a", "aac",
                        "-b:a", "128k",
                        "-ar", "44100",
                        aac_path,
                    ],
                    capture_output=True,
                    check=True,
                )
                aac_files.append(aac_path)
                self.progress.emit(int((i + 1) / total * 60))  # 0-60%

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
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", list_file,
                    "-c", "copy",
                    merged,
                ],
                capture_output=True,
                check=True,
            )
            self.progress.emit(75)

            # ── Шаг 3: собираем файл метаданных с главами ─────────────────
            if self._cancelled:
                return
            self.status.emit("Генерация глав…")

            # Считаем старты глав по длительностям AAC файлов
            durations = [get_duration_seconds(p) for p in aac_files]
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

            cmd = [
                ffmpeg, "-y",
                "-i", merged,
                "-i", meta_file,
                "-map_metadata", "1",
                "-map_chapters", "1",
            ]

            if self.cover_path and os.path.isfile(self.cover_path):
                cmd += [
                    "-i", self.cover_path,
                    "-map", "0:a",
                    "-map", "2:v",
                    "-c:v", "mjpeg",
                    "-disposition:v", "attached_pic",
                ]
            else:
                cmd += ["-map", "0:a"]

            cmd += [
                "-c:a", "copy",
                "-movflags", "+faststart",
                self.output_path,
            ]

            subprocess.run(cmd, capture_output=True, check=True)
            self.progress.emit(100)
            self.status.emit("Готово!")
            self.finished.emit(self.output_path)

        finally:
            # Удаляем временные файлы
            shutil.rmtree(tmp_dir, ignore_errors=True)
