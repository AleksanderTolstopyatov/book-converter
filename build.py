"""
build.py — скрипт сборки, который:
1. Находит ffmpeg и ffprobe (в PATH или стандартных местах)
2. Генерирует и запускает PyInstaller с нужными флагами

Запуск:
    python build.py
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _is_chocolatey_shim(path: Path) -> bool:
    """Chocolatey puts tiny shim exes into ProgramData/chocolatey/bin."""
    if platform.system() != "Windows":
        return False
    norm = str(path).replace("/", "\\").lower()
    return "\\programdata\\chocolatey\\bin\\" in norm


def _windows_real_binary_from_choco(name: str) -> Path | None:
    """Find real ffmpeg binary inside Chocolatey package folders."""
    if platform.system() != "Windows":
        return None

    exe = name + ".exe"
    roots = [
        Path(r"C:\ProgramData\chocolatey\lib\ffmpeg\tools"),
        Path(r"C:\ProgramData\chocolatey\lib\ffmpeg-full\tools"),
    ]

    for root in roots:
        if not root.exists():
            continue
        # Common layouts: tools/ffmpeg/bin, tools/ffmpeg-release-*/bin, etc.
        direct = [
            root / "ffmpeg" / "bin" / exe,
            root / "ffmpeg-release-essentials" / "bin" / exe,
            root / "ffmpeg-release-full" / "bin" / exe,
        ]
        for candidate in direct:
            if candidate.is_file():
                return candidate

        for candidate in root.rglob(exe):
            if "\\bin\\" in str(candidate).replace("/", "\\").lower() and candidate.is_file():
                return candidate

    return None


def find_binary(name: str) -> Path:
    is_win = platform.system() == "Windows"
    exe = name + ".exe" if is_win else name

    found = shutil.which(exe)
    if found:
        found_path = Path(found)
        # Never bundle Chocolatey shim, it breaks outside the original machine.
        if _is_chocolatey_shim(found_path):
            real = _windows_real_binary_from_choco(name)
            if real:
                return real
        return found_path

    candidates = [
        Path("/opt/homebrew/bin") / exe,
        Path("/usr/local/bin") / exe,
        Path(r"C:\ffmpeg\bin") / exe,
        Path(r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin") / exe,
    ]
    for c in candidates:
        if c.is_file():
            return c

    if is_win:
        real = _windows_real_binary_from_choco(name)
        if real:
            return real

    raise FileNotFoundError(
        f"{name} was not found in PATH. Install ffmpeg first:\n"
        "  macOS:   brew install ffmpeg\n"
        "  Windows: winget install ffmpeg\n"
        "  Linux:   sudo apt install ffmpeg"
    )


def main():
    system = platform.system()
    print(f"Build for {system}...")

    ffmpeg_path = find_binary("ffmpeg")
    ffprobe_path = find_binary("ffprobe")
    print(f"  ffmpeg  -> {ffmpeg_path}")
    print(f"  ffprobe -> {ffprobe_path}")

    extra_binaries: list[str] = []
    if system == "Windows":
        # Some Windows ffmpeg builds depend on sibling DLL files.
        for dll in sorted(ffmpeg_path.parent.glob("*.dll")):
            extra_binaries.append(str(dll))
        if extra_binaries:
            print(f"  extra dlls -> {len(extra_binaries)}")

    # Разделитель для --add-binary: ':' на macOS/Linux, ';' на Windows
    sep = ";" if system == "Windows" else ":"

    app_name = "AudioBook Maker"
    icon_flag = []
    # Иконка (необязательно): добавь icon.icns / icon.ico рядом с build.py
    if system == "Darwin" and Path("icon.icns").is_file():
        icon_flag = ["--icon", "icon.icns"]
    elif system == "Windows" and Path("icon.ico").is_file():
        icon_flag = ["--icon", "icon.ico"]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", app_name,
        f"--add-binary={ffmpeg_path}{sep}.",
        f"--add-binary={ffprobe_path}{sep}.",
        *[f"--add-binary={dll}{sep}." for dll in extra_binaries],
        *icon_flag,
        "main.py",
    ]

    print("\nRunning PyInstaller:")
    print("  " + " ".join(str(c) for c in cmd))
    print()

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("\nBuild failed!")
        sys.exit(1)

    dist_path = Path("dist") / (app_name + (".exe" if system == "Windows" else ""))
    if system == "Darwin":
        dist_path = Path("dist") / (app_name + ".app")

    print(f"\nDone: {dist_path.resolve()}")


if __name__ == "__main__":
    main()
