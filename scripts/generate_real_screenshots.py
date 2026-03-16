from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QMessageBox

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import DARK_STYLE, MainWindow


def _grab_widget_area(window: MainWindow, target_rect: QRect, out_path: Path) -> None:
    shot = window.grab(target_rect)
    shot.save(str(out_path))


def main() -> None:
    out_dir = Path("docs/screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    app.setApplicationName("AudioBook Maker")
    app.setStyleSheet(DARK_STYLE)

    window = MainWindow()
    window.resize(1280, 860)

    # Наполняем интерфейс, чтобы скриншоты выглядели как реальный сценарий работы.
    sample_files = [
        ("/Users/demo/Books/01-intro.mp3", "Введение"),
        ("/Users/demo/Books/02-chapter.mp3", "Глава 1"),
        ("/Users/demo/Books/03-chapter.mp3", "Глава 2"),
        ("/Users/demo/Books/04-chapter.mp3", "Глава 3"),
    ]
    for fp, title in sample_files:
        window.chapter_list.add_chapter(fp, title)

    window.edit_title.setText("Atomic Habits")
    window.edit_author.setText("James Clear")
    window.edit_output.setText(str(Path.home() / "Desktop" / "Atomic Habits.m4b"))
    window._set_bitrate_slider_value(192)
    window.label_bitrate_hint.setText(
        "Разные битрейты (96k-320k). По умолчанию выбран 192k (самый частый)."
    )

    window.show()
    app.processEvents()

    # 1) Главное окно
    window.grab().save(str(out_dir / "main-window-overview.png"))

    # 2) Фокус на блоке битрейта
    slider_top_left = window.slider_bitrate.mapTo(window, QPoint(0, 0))
    slider_rect = QRect(
        max(0, slider_top_left.x() - 260),
        max(0, slider_top_left.y() - 70),
        min(window.width(), 980),
        220,
    )
    _grab_widget_area(window, slider_rect, out_dir / "bitrate-slider.png")

    # 3) Модалка завершения
    msg = QMessageBox(window)
    msg.setWindowTitle("Готово!")
    msg.setIcon(QMessageBox.Information)
    msg.setText("Аудиокнига успешно создана:\n/Users/demo/Desktop/Atomic Habits.m4b")
    msg.setInformativeText("Открыть папку?")
    msg.addButton("Открыть", QMessageBox.AcceptRole)
    msg.addButton("Закрыть", QMessageBox.RejectRole)
    msg.show()
    app.processEvents()
    msg.grab().save(str(out_dir / "finish-modal.png"))
    msg.close()

    window.close()
    app.quit()


if __name__ == "__main__":
    main()
