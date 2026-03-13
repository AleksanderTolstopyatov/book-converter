"""
main.py — главное окно приложения AudioBook Maker.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QIcon, QFont, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from converter import Chapter, ConversionWorker
from widgets import ChapterListWidget

DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: "SF Pro Text", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #444;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
    font-weight: bold;
    color: #aaa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    top: -1px;
    padding: 0 4px;
}
QLineEdit {
    background: #2d2d2d;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 4px 8px;
    color: #d4d4d4;
    selection-background-color: #264f78;
}
QLineEdit:focus {
    border-color: #0e639c;
}
QPushButton {
    background-color: #0e639c;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #1177bb;
}
QPushButton:pressed {
    background-color: #0a4a7a;
}
QPushButton:disabled {
    background-color: #3a3a3a;
    color: #666;
}
QPushButton#btn_secondary {
    background-color: #3a3a3a;
    color: #d4d4d4;
}
QPushButton#btn_secondary:hover {
    background-color: #4a4a4a;
}
QPushButton#btn_danger {
    background-color: #7a1a1a;
    color: #d4d4d4;
}
QPushButton#btn_danger:hover {
    background-color: #9a2020;
}
QProgressBar {
    border: 1px solid #555;
    border-radius: 4px;
    background: #2d2d2d;
    text-align: center;
    color: #d4d4d4;
    height: 18px;
}
QProgressBar::chunk {
    background-color: #0e639c;
    border-radius: 3px;
}
QLabel {
    color: #d4d4d4;
}
QStatusBar {
    background: #252525;
    color: #888;
    border-top: 1px solid #333;
}
"""


class CoverLabel(QLabel):
    """Кликабельный QLabel для обложки, поддерживает drag-and-drop изображений."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 140)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self._cover_path: str | None = None
        self._show_placeholder()

    def _show_placeholder(self):
        self.setStyleSheet(
            "QLabel { border: 2px dashed #555; border-radius: 8px;"
            " background: #2b2b2b; color: #666; font-size: 11px; }"
        )
        self.setText("Нажмите или\nперетащите\nобложку")
        self._cover_path = None

    def set_cover(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            return
        self._cover_path = path
        self.setPixmap(
            pix.scaled(138, 138, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.setStyleSheet(
            "QLabel { border: 2px solid #0e639c; border-radius: 8px; background: #2b2b2b; }"
        )

    def clear_cover(self):
        self._show_placeholder()
        self.setPixmap(QPixmap())  # очищаем картинку

    @property
    def cover_path(self) -> str | None:
        return self._cover_path

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "Выбрать обложку",
                str(Path.home()),
                "Изображения (*.jpg *.jpeg *.png *.webp *.bmp)"
            )
            if path:
                self.set_cover(path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                self.set_cover(path)
                event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AudioBook Maker")
        self.setMinimumSize(700, 620)
        self.resize(800, 700)
        self._worker: ConversionWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(12)
        root.setContentsMargins(14, 14, 14, 14)

        # ── Блок: список файлов ──────────────────────────────────────────
        files_group = QGroupBox("Главы (MP3 / M4A / FLAC / WAV …)")
        files_layout = QVBoxLayout(files_group)

        # Кнопки управления списком
        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Добавить файлы")
        btn_add.setObjectName("btn_secondary")
        btn_add.clicked.connect(self._add_files)
        btn_clear = QPushButton("Очистить список")
        btn_clear.setObjectName("btn_danger")
        btn_clear.clicked.connect(self._clear_list)
        btn_row.addWidget(btn_add)
        btn_row.addStretch()
        btn_row.addWidget(btn_clear)
        files_layout.addLayout(btn_row)

        # Подсказка drag-and-drop
        hint = QLabel("Перетащите файлы сюда или нажмите «+ Добавить файлы»")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        hint.setAlignment(Qt.AlignCenter)
        files_layout.addWidget(hint)

        self.chapter_list = ChapterListWidget()
        self.chapter_list.chapters_changed.connect(self._update_convert_btn)
        files_layout.addWidget(self.chapter_list)

        root.addWidget(files_group)

        # ── Блок: метаданные + обложка ───────────────────────────────────
        meta_group = QGroupBox("Метаданные аудиокниги")
        meta_layout = QHBoxLayout(meta_group)
        meta_layout.setSpacing(16)

        # Обложка
        cover_col = QVBoxLayout()
        self.cover_label = CoverLabel()
        cover_col.addWidget(self.cover_label)
        btn_clear_cover = QPushButton("Убрать обложку")
        btn_clear_cover.setObjectName("btn_secondary")
        btn_clear_cover.setFixedWidth(140)
        btn_clear_cover.clicked.connect(self.cover_label.clear_cover)
        cover_col.addWidget(btn_clear_cover)
        meta_layout.addLayout(cover_col)

        # Поля
        fields = QGridLayout()
        fields.setColumnStretch(1, 1)
        fields.setVerticalSpacing(8)

        lbl_title = QLabel("Название:")
        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("Название аудиокниги")
        fields.addWidget(lbl_title, 0, 0)
        fields.addWidget(self.edit_title, 0, 1)

        lbl_author = QLabel("Автор:")
        self.edit_author = QLineEdit()
        self.edit_author.setPlaceholderText("Имя автора")
        fields.addWidget(lbl_author, 1, 0)
        fields.addWidget(self.edit_author, 1, 1)

        lbl_output = QLabel("Сохранить как:")
        out_row = QHBoxLayout()
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText("/путь/к/audiobook.m4b")
        btn_browse_out = QPushButton("…")
        btn_browse_out.setObjectName("btn_secondary")
        btn_browse_out.setFixedWidth(36)
        btn_browse_out.clicked.connect(self._browse_output)
        out_row.addWidget(self.edit_output)
        out_row.addWidget(btn_browse_out)
        fields.addWidget(lbl_output, 2, 0)
        fields.addLayout(out_row, 2, 1)

        fields_widget = QWidget()
        fields_widget.setLayout(fields)
        meta_layout.addWidget(fields_widget)

        root.addWidget(meta_group)

        # ── Прогресс ──────────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        # ── Кнопки действий ───────────────────────────────────────────────
        action_row = QHBoxLayout()
        self.btn_convert = QPushButton("▶  Конвертировать в M4B")
        self.btn_convert.setFixedHeight(40)
        font = self.btn_convert.font()
        font.setPointSize(13)
        self.btn_convert.setFont(font)
        self.btn_convert.setEnabled(False)
        self.btn_convert.clicked.connect(self._start_conversion)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setObjectName("btn_danger")
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_conversion)

        action_row.addWidget(self.btn_convert)
        action_row.addWidget(self.btn_cancel)
        root.addLayout(action_row)

        # ── Статус-бар ────────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Добавьте MP3 файлы для начала работы")

    # ────────────────────────────────────────────────────────────────────
    # Слоты
    # ────────────────────────────────────────────────────────────────────

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выбрать аудиофайлы",
            str(Path.home() / "Music"),
            "Аудиофайлы (*.mp3 *.m4a *.aac *.flac *.wav *.ogg);;Все файлы (*)",
        )
        for p in paths:
            self.chapter_list.add_chapter(p)

    def _clear_list(self):
        if self.chapter_list.count() == 0:
            return
        reply = QMessageBox.question(
            self, "Очистить список",
            "Удалить все файлы из списка?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.chapter_list.clear()
            self.chapter_list.chapters_changed.emit()

    def _browse_output(self):
        default_name = (self.edit_title.text().strip() or "audiobook") + ".m4b"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить аудиокнигу",
            str(Path.home() / "Desktop" / default_name),
            "Audiobook (*.m4b)",
        )
        if path:
            if not path.lower().endswith(".m4b"):
                path += ".m4b"
            self.edit_output.setText(path)

    def _update_convert_btn(self):
        self.btn_convert.setEnabled(self.chapter_list.count() > 0)

    def _start_conversion(self):
        # Валидация
        chapters_data = self.chapter_list.get_chapters()
        if not chapters_data:
            QMessageBox.warning(self, "Ошибка", "Добавьте хотя бы один аудиофайл.")
            return

        output = self.edit_output.text().strip()
        if not output:
            self._browse_output()
            output = self.edit_output.text().strip()
            if not output:
                return

        title = self.edit_title.text().strip() or Path(output).stem
        author = self.edit_author.text().strip() or "Unknown"

        chapters = [Chapter(file_path=fp, title=t) for fp, t in chapters_data]

        # Запуск
        self.btn_convert.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        self._worker = ConversionWorker(
            chapters=chapters,
            output_path=output,
            title=title,
            author=author,
            cover_path=self.cover_label.cover_path,
        )
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.status.connect(self.status_bar.showMessage)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _cancel_conversion(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        self._reset_ui()
        self.status_bar.showMessage("Конвертация отменена.")

    def _on_finished(self, output_path: str):
        self._reset_ui()
        self.progress_bar.setValue(100)
        reply = QMessageBox.information(
            self,
            "Готово!",
            f"Аудиокнига успешно создана:\n{output_path}\n\nОткрыть папку?",
            QMessageBox.Open | QMessageBox.Close,
        )
        if reply == QMessageBox.Open:
            self._open_in_finder(output_path)

    def _on_error(self, message: str):
        self._reset_ui()
        QMessageBox.critical(self, "Ошибка конвертации", message)
        self.status_bar.showMessage("Ошибка! " + message[:80])

    def _reset_ui(self):
        self.btn_convert.setEnabled(self.chapter_list.count() > 0)
        self.btn_cancel.setVisible(False)

    @staticmethod
    def _open_in_finder(path: str):
        import subprocess, platform
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", "-R", path])
        elif system == "Windows":
            subprocess.Popen(["explorer", "/select,", path])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AudioBook Maker")
    app.setStyleSheet(DARK_STYLE)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
