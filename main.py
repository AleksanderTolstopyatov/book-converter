"""
main.py — главное окно приложения AudioBook Maker.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from collections import Counter

from PySide6.QtCore import Qt, QSize, QSettings
from PySide6.QtGui import QPixmap, QIcon, QFont, QDragEnterEvent, QDropEvent, QImage
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
    QSlider,
    QSizePolicy,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from converter import Chapter, ConversionWorker, get_audio_bitrate_kbps
from widgets import ChapterListWidget

DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #151a19;
    color: #d5ddd9;
    font-family: "SF Pro Text", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QWidget#HeaderCard {
    border: 1px solid #2f3f3b;
    border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a2321, stop:1 #1d2b29);
}
QLabel#HeaderTitle {
    font-size: 18px;
    font-weight: 700;
    color: #eef6f2;
}
QLabel#HeaderSubtitle {
    color: #93a39b;
    font-size: 12px;
}
QGroupBox {
    border: 1px solid #33413f;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 6px;
    font-weight: bold;
    color: #a7b7b0;
    background: #1b2221;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    top: -1px;
    padding: 0 4px;
}
QLineEdit {
    background: #232d2b;
    border: 1px solid #43514e;
    border-radius: 5px;
    padding: 4px 8px;
    color: #e2ebe7;
    selection-background-color: #3a645b;
}
QLineEdit:focus {
    border-color: #3a8f7e;
}
QSlider::groove:horizontal {
    border: 1px solid #43514e;
    height: 6px;
    border-radius: 3px;
    background: #232d2b;
}
QSlider::sub-page:horizontal {
    background: #3a8f7e;
    border-radius: 3px;
}
QSlider::add-page:horizontal {
    background: #232d2b;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #dce8e3;
    border: 1px solid #7f9a92;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QPushButton {
    background-color: #3a8f7e;
    color: #f5fcf9;
    border: 1px solid #4da08f;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #46a390;
}
QPushButton:pressed {
    background-color: #2d7062;
}
QPushButton:disabled {
    background-color: #2b3130;
    border-color: #394341;
    color: #6f7a76;
}
QPushButton#btn_secondary {
    background-color: #2c3533;
    border-color: #45514e;
    color: #d5ddd9;
}
QPushButton#btn_secondary:hover {
    background-color: #35403d;
}
QPushButton#btn_danger {
    background-color: #6a2a2a;
    border-color: #8e3a3a;
    color: #f0dfdf;
}
QPushButton#btn_danger:hover {
    background-color: #7d3232;
}
QPushButton#btn_preset {
    background-color: #293331;
    border: 1px solid #45514e;
    color: #9db1aa;
    min-width: 52px;
}
QPushButton#btn_preset:hover {
    background-color: #32403d;
}
QPushButton#btn_preset:checked {
    background-color: #365f55;
    border-color: #4ea08f;
    color: #e6f2ee;
}
QProgressBar {
    border: 1px solid #42514d;
    border-radius: 5px;
    background: #212a28;
    text-align: center;
    color: #dfebe6;
    height: 20px;
}
QProgressBar::chunk {
    background-color: #3a8f7e;
    border-radius: 3px;
}
QLabel {
    color: #d5ddd9;
}
QStatusBar {
    background: #1a201f;
    color: #8ea19a;
    border-top: 1px solid #2e3d39;
}
"""


class CoverLabel(QLabel):
    """Кликабельный QLabel для обложки, поддерживает drag-and-drop изображений."""

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self._settings = settings
        self.setFixedSize(180, 180)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self._cover_path: str | None = None
        self._drag_active = False
        self._show_placeholder()

    def _set_state_style(self, has_cover: bool, drag_active: bool) -> None:
        if has_cover:
            border = "#49a691" if drag_active else "#3a8f7e"
            self.setStyleSheet(
                f"QLabel {{ border: 2px solid {border}; border-radius: 10px; background: #232d2b; }}"
            )
            return

        border = "#49a691" if drag_active else "#53615e"
        bg = "#273331" if drag_active else "#222a28"
        self.setStyleSheet(
            f"QLabel {{ border: 2px dashed {border}; border-radius: 10px;"
            f" background: {bg}; color: #879791; font-size: 11px; }}"
        )

    def _show_placeholder(self):
        self._set_state_style(has_cover=False, drag_active=self._drag_active)
        self.setText("Нажмите или\nперетащите\nобложку")
        self._cover_path = None

    def set_cover(self, path: str):
        display_pix = self._load_image_for_display(path)
        if display_pix.isNull():
            return
        self._cover_path = path
        self.setPixmap(
            display_pix.scaled(176, 176, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self._set_state_style(has_cover=True, drag_active=self._drag_active)

    @staticmethod
    def _load_image_for_display(path: str) -> QPixmap:
        """Завантажувати зображення, конвертуючи невідомі Qt форматы на льоту."""
        pix = QPixmap(path)
        if not pix.isNull():
            return pix

        try:
            from PIL import Image
            import io

            with Image.open(path) as img:
                if img.mode in ("RGBA", "LA", "P"):
                    pass
                else:
                    img = img.convert("RGB")

                png_buffer = io.BytesIO()
                img.save(png_buffer, format="PNG")
                png_data = png_buffer.getvalue()

                q_img = QImage()
                q_img.loadFromData(png_data)
                return QPixmap.fromImage(q_img)
        except Exception:
            pass

        return QPixmap()

    def clear_cover(self):
        self._show_placeholder()
        self.setPixmap(QPixmap())  # очищаем картинку

    @property
    def cover_path(self) -> str | None:
        return self._cover_path

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            last_dir = str(Path.home())
            if self._settings:
                last_dir = self._settings.value("last_files_dir", str(Path.home()), str)
            if last_dir and not Path(last_dir).exists():
                last_dir = str(Path.home())

            path, _ = QFileDialog.getOpenFileName(
                self, "Выбрать обложку",
                last_dir,
                "Изображения (*);;Все файлы (*)"
            )
            if path:
                if self._is_supported_image(path):
                    self.set_cover(path)
                    if self._settings:
                        self._settings.setValue("last_files_dir", str(Path(path).parent))
                else:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self,
                        "Ошибка",
                        f"Не удалось загрузить изображение.\n\nПроверьте, что файл действительно является изображением и что Pillow поддерживает этот формат."
                    )

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and self._is_supported_image(urls[0].toLocalFile()):
                self._drag_active = True
                self._set_state_style(has_cover=bool(self._cover_path), drag_active=True)
                event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drag_active = False
        self._set_state_style(has_cover=bool(self._cover_path), drag_active=False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self._drag_active = False
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if self._is_supported_image(path):
                self.set_cover(path)
                event.acceptProposedAction()
            else:
                self._set_state_style(has_cover=bool(self._cover_path), drag_active=False)
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Не удалось загрузить изображение.\n\nПроверьте, что файл действительно является изображением и что Pillow поддерживает этот формат."
                )
        else:
            self._set_state_style(has_cover=bool(self._cover_path), drag_active=False)

    @staticmethod
    def _is_supported_image(path: str) -> bool:
        if not path or not Path(path).is_file():
            return False

        # Pillow поддерживает больше форматов, чем фиксированный список расширений.
        try:
            from PIL import Image

            with Image.open(path) as img:
                img.verify()
            return True
        except Exception:
            return False


class MainWindow(QMainWindow):
    BITRATE_MIN = 64
    BITRATE_MAX = 320
    BITRATE_STEP = 8

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AudioBook Maker")
        self.setMinimumSize(840, 720)
        self.resize(940, 780)
        self._worker: ConversionWorker | None = None
        self._bitrate_cache: dict[str, int | None] = {}
        self._duration_cache: dict[str, float | None] = {}
        self._settings = QSettings("AudioBookMaker", "AudioBookMaker")
        self._is_cancelling = False
        self._progress_started_at = 0.0
        self._last_progress_value = 0
        self._preset_buttons: list[QPushButton] = []

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(12)
        root.setContentsMargins(14, 14, 14, 14)

        header_card = QWidget()
        header_card.setObjectName("HeaderCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(2)

        header_title = QLabel("AudioBook Maker")
        header_title.setObjectName("HeaderTitle")
        header_subtitle = QLabel("Соберите аудиокнигу в 4 шага: файлы, метаданные, качество, экспорт")
        header_subtitle.setObjectName("HeaderSubtitle")
        header_layout.addWidget(header_title)
        header_layout.addWidget(header_subtitle)
        root.addWidget(header_card)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        self.btn_add_files = QPushButton("+ Добавить файлы")
        self.btn_add_files.setObjectName("btn_secondary")
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_clear_list = QPushButton("Очистить")
        self.btn_clear_list.setObjectName("btn_danger")
        self.btn_clear_list.clicked.connect(self._clear_list)
        self.label_step_state = QLabel("Шаг 1 из 4: добавьте главы")
        self.label_step_state.setStyleSheet("color: #98a8a1; font-size: 12px;")
        quick_row.addWidget(self.btn_add_files)
        quick_row.addWidget(self.btn_clear_list)
        quick_row.addStretch()
        quick_row.addWidget(self.label_step_state)
        root.addLayout(quick_row)

        # ── Блок: список файлов ──────────────────────────────────────────
        files_group = QGroupBox("1. Файлы и порядок глав")
        files_layout = QVBoxLayout(files_group)

        # Подсказка drag-and-drop
        hint = QLabel("Перетащите аудиофайлы в список ниже или используйте кнопку «+ Добавить файлы»")
        hint.setStyleSheet("color: #8ea19a; font-size: 11px;")
        hint.setAlignment(Qt.AlignCenter)
        files_layout.addWidget(hint)

        self.chapter_list = ChapterListWidget()
        self.chapter_list.chapters_changed.connect(self._update_convert_btn)
        files_layout.addWidget(self.chapter_list)

        self.label_chapter_summary = QLabel("Глав: 0")
        self.label_chapter_summary.setStyleSheet("color: #8ea19a; font-size: 11px;")
        files_layout.addWidget(self.label_chapter_summary)

        root.addWidget(files_group)

        # ── Блок: метаданные + обложка ───────────────────────────────────
        meta_group = QGroupBox("2. Метаданные, обложка и экспорт")
        meta_layout = QHBoxLayout(meta_group)
        meta_layout.setSpacing(16)

        # Обложка
        cover_col = QVBoxLayout()
        self.cover_label = CoverLabel(settings=self._settings)
        cover_col.addWidget(self.cover_label)
        btn_clear_cover = QPushButton("Убрать обложку")
        btn_clear_cover.setObjectName("btn_secondary")
        btn_clear_cover.setFixedWidth(180)
        btn_clear_cover.clicked.connect(self.cover_label.clear_cover)
        cover_col.addWidget(btn_clear_cover)
        cover_col.addStretch()
        meta_layout.addLayout(cover_col)

        # Поля
        fields = QGridLayout()
        fields.setColumnStretch(1, 1)
        fields.setVerticalSpacing(8)

        lbl_title = QLabel("Название:")
        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("Название аудиокниги")
        self.edit_title.textChanged.connect(self._save_settings)
        fields.addWidget(lbl_title, 0, 0)
        fields.addWidget(self.edit_title, 0, 1)

        lbl_author = QLabel("Автор:")
        self.edit_author = QLineEdit()
        self.edit_author.setPlaceholderText("Имя автора")
        self.edit_author.textChanged.connect(self._save_settings)
        fields.addWidget(lbl_author, 1, 0)
        fields.addWidget(self.edit_author, 1, 1)

        lbl_output = QLabel("Сохранить как:")
        out_row = QHBoxLayout()
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText("/путь/к/audiobook.m4b")
        self.edit_output.textChanged.connect(self._update_estimated_size)
        self.edit_output.textChanged.connect(self._update_convert_btn)
        self.edit_output.textChanged.connect(self._save_settings)

        btn_browse_out = QPushButton("…")
        btn_browse_out.setObjectName("btn_secondary")
        btn_browse_out.setFixedWidth(36)
        btn_browse_out.clicked.connect(self._browse_output)

        self.btn_open_output_dir = QPushButton("Открыть папку")
        self.btn_open_output_dir.setObjectName("btn_secondary")
        self.btn_open_output_dir.clicked.connect(self._open_selected_output_folder)

        out_row.addWidget(self.edit_output)
        out_row.addWidget(btn_browse_out)
        out_row.addWidget(self.btn_open_output_dir)
        fields.addWidget(lbl_output, 2, 0)
        fields.addLayout(out_row, 2, 1)

        lbl_bitrate = QLabel("Битрейт:")
        self.slider_bitrate = QSlider(Qt.Horizontal)
        self.slider_bitrate.setRange(self.BITRATE_MIN, self.BITRATE_MAX)
        self.slider_bitrate.setSingleStep(self.BITRATE_STEP)
        self.slider_bitrate.setPageStep(32)
        self.slider_bitrate.setTickInterval(32)
        self.slider_bitrate.setTickPosition(QSlider.TicksBelow)
        self.slider_bitrate.valueChanged.connect(self._on_bitrate_slider_changed)
        self.label_bitrate_value = QLabel("128k")
        self.label_bitrate_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._set_bitrate_slider_value(128)

        bitrate_row = QHBoxLayout()
        bitrate_row.setContentsMargins(0, 0, 0, 0)
        bitrate_row.setSpacing(8)
        bitrate_row.addWidget(self.slider_bitrate, 1)
        bitrate_row.addWidget(self.label_bitrate_value, 0)

        self.label_bitrate_hint = QLabel("По умолчанию: 128k")
        self.label_bitrate_hint.setStyleSheet("color: #888; font-size: 11px;")
        bitrate_col = QVBoxLayout()
        bitrate_col.setContentsMargins(0, 0, 0, 0)
        bitrate_col.setSpacing(2)
        bitrate_col.addLayout(bitrate_row)

        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(6)
        for preset in (96, 128, 192, 256):
            btn = QPushButton(f"{preset}k")
            btn.setObjectName("btn_preset")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, kbps=preset: self._apply_bitrate_preset(kbps))
            self._preset_buttons.append(btn)
            preset_row.addWidget(btn)
        self.btn_auto_bitrate = QPushButton("Авто")
        self.btn_auto_bitrate.setObjectName("btn_preset")
        self.btn_auto_bitrate.clicked.connect(self._update_bitrate_default)
        preset_row.addWidget(self.btn_auto_bitrate)
        preset_row.addStretch()

        bitrate_col.addLayout(preset_row)

        bitrate_col.addWidget(self.label_bitrate_hint)

        self.label_estimated_size = QLabel("Оценка размера: --")
        self.label_estimated_size.setStyleSheet("color: #8ea19a; font-size: 11px;")
        bitrate_col.addWidget(self.label_estimated_size)

        fields.addWidget(lbl_bitrate, 3, 0)
        fields.addLayout(bitrate_col, 3, 1)

        fields_widget = QWidget()
        fields_widget.setLayout(fields)
        meta_layout.addWidget(fields_widget)

        root.addWidget(meta_group)

        # ── Прогресс ──────────────────────────────────────────────────────
        self.label_progress_status = QLabel("4. Готово к конвертации")
        self.label_progress_status.setStyleSheet("color: #8ea19a; font-size: 12px;")
        root.addWidget(self.label_progress_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        # ── Кнопки действий ───────────────────────────────────────────────
        action_row = QHBoxLayout()
        self.btn_convert = QPushButton("4. Конвертировать в M4B")
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
        self._load_settings()
        self._update_convert_btn()
        self._update_estimated_size()
        self._update_step_state()
        self.status_bar.showMessage("Добавьте аудиофайлы для начала работы")

    # ────────────────────────────────────────────────────────────────────
    # Слоты
    # ────────────────────────────────────────────────────────────────────

    def _add_files(self):
        last_dir = self._settings.value("last_files_dir", str(Path.home() / "Music"), str)
        if last_dir and not Path(last_dir).exists():
            last_dir = str(Path.home() / "Music")

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выбрать аудиофайлы",
            last_dir,
            "Аудиофайлы (*.mp3 *.m4a *.aac *.flac *.wav *.ogg);;Все файлы (*)",
        )
        if paths:
            self.chapter_list.add_chapters(paths)
            self._settings.setValue("last_files_dir", str(Path(paths[-1]).parent))
        self._update_estimated_size()
        self._save_settings()

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
            self._update_estimated_size()

    def _browse_output(self):
        default_name = (self.edit_title.text().strip() or "audiobook") + ".m4b"
        last_dir = self._settings.value("last_files_dir", str(Path.home() / "Desktop"), str)
        if last_dir and not Path(last_dir).exists():
            last_dir = str(Path.home() / "Desktop")
        default_path = str(Path(last_dir) / default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить аудиокнигу",
            default_path,
            "Audiobook (*.m4b)",
        )
        if path:
            if not path.lower().endswith(".m4b"):
                path += ".m4b"
            self.edit_output.setText(path)
            self._settings.setValue("last_files_dir", str(Path(path).parent))
            self._save_settings()

    def _open_selected_output_folder(self):
        output = self.edit_output.text().strip()
        if output:
            self._open_output_folder(output)

    def _apply_bitrate_preset(self, kbps: int):
        self._set_bitrate_slider_value(kbps)
        self.label_bitrate_hint.setText(f"Выбран пресет: {self._selected_bitrate_kbps()}k")
        self._sync_preset_buttons(self._selected_bitrate_kbps())
        self._update_estimated_size()

    def _sync_preset_buttons(self, bitrate: int):
        for btn in self._preset_buttons:
            btn.blockSignals(True)
            btn.setChecked(btn.text() == f"{bitrate}k")
            btn.blockSignals(False)

    def _human_size(self, size_bytes: float) -> str:
        units = ["B", "KB", "MB", "GB"]
        size = max(0.0, float(size_bytes))
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return "--"

    @staticmethod
    def _read_duration_seconds_fast(file_path: str) -> float | None:
        try:
            from mutagen import File as MutagenFile

            data = MutagenFile(file_path)
            if data and getattr(data, "info", None) and getattr(data.info, "length", None):
                return max(0.0, float(data.info.length))
        except Exception:
            pass
        return None

    def _estimate_total_seconds(self) -> float:
        total_seconds = 0.0
        for file_path, _title in self.chapter_list.get_chapters():
            cached = self._duration_cache.get(file_path)
            if isinstance(cached, (float, int)):
                total_seconds += max(0.0, float(cached))
                continue

            duration = self._read_duration_seconds_fast(file_path)
            self._duration_cache[file_path] = duration
            if isinstance(duration, (float, int)):
                total_seconds += max(0.0, float(duration))

        return total_seconds

    def _estimate_total_seconds_sampled(self, max_files: int = 30) -> tuple[float, bool]:
        chapters = self.chapter_list.get_chapters()
        if not chapters:
            return 0.0, True

        file_paths = [fp for fp, _ in chapters]
        sample = file_paths[:max_files]
        sample_seconds = 0.0
        measured = 0

        for file_path in sample:
            cached = self._duration_cache.get(file_path)
            if not isinstance(cached, (float, int)):
                cached = self._read_duration_seconds_fast(file_path)
                self._duration_cache[file_path] = cached

            if isinstance(cached, (float, int)):
                sample_seconds += float(cached)
                measured += 1

        if measured == 0:
            return 0.0, False

        avg = sample_seconds / measured
        estimated_total = avg * len(file_paths)
        is_precise = len(file_paths) <= max_files
        return estimated_total, is_precise

    def _update_estimated_size(self):
        if not hasattr(self, "label_estimated_size") or not hasattr(self, "label_chapter_summary"):
            return

        chapters_count = self.chapter_list.count()
        if chapters_count == 0:
            self.label_estimated_size.setText("Оценка размера: --")
            self.label_chapter_summary.setText("Глав: 0")
            self._update_step_state()
            return

        if chapters_count > 80:
            total_seconds, is_precise = self._estimate_total_seconds_sampled(max_files=30)
        else:
            total_seconds = self._estimate_total_seconds()
            is_precise = True

        bitrate = self._selected_bitrate_kbps()
        estimated_bytes = (bitrate * 1000 / 8) * total_seconds
        estimate = self._human_size(estimated_bytes)
        total_minutes = int(round(total_seconds / 60.0))

        if is_precise:
            self.label_estimated_size.setText(f"Оценка размера: {estimate} при {bitrate}k")
        else:
            self.label_estimated_size.setText(f"Оценка размера: ~{estimate} при {bitrate}k (по выборке)")

        self.label_chapter_summary.setText(f"Глав: {chapters_count}  •  Длительность: ~{total_minutes} мин")
        self._update_step_state()

    def _update_step_state(self):
        chapters_ok = self.chapter_list.count() > 0
        output_ok = bool(self.edit_output.text().strip())
        if not chapters_ok:
            self.label_step_state.setText("Шаг 1 из 4: добавьте главы")
            return
        if not output_ok:
            self.label_step_state.setText("Шаг 3 из 4: выберите путь сохранения")
            return
        self.label_step_state.setText("Шаг 4 из 4: можно запускать конвертацию")

    def _update_convert_btn(self):
        self.btn_convert.setEnabled(self.chapter_list.count() > 0 and bool(self.edit_output.text().strip()))
        self._update_bitrate_default()
        self._update_estimated_size()
        self._save_settings()

    def _selected_bitrate_kbps(self) -> int:
        return int(self.slider_bitrate.value())

    def _normalize_bitrate(self, kbps: int) -> int:
        bounded = max(self.BITRATE_MIN, min(self.BITRATE_MAX, int(kbps)))
        step = self.BITRATE_STEP
        return int(round(bounded / step) * step)

    def _set_bitrate_slider_value(self, kbps: int) -> None:
        self.slider_bitrate.setValue(self._normalize_bitrate(kbps))

    def _on_bitrate_slider_changed(self, value: int):
        self.label_bitrate_value.setText(f"{value}k")
        self._sync_preset_buttons(value)
        self._update_estimated_size()
        self._save_settings()

    def _nearest_slider_bitrate(self, kbps: int) -> int:
        return self._normalize_bitrate(kbps)

    def _update_bitrate_default(self):
        chapters_data = self.chapter_list.get_chapters()
        file_paths = [fp for fp, _ in chapters_data]

        if not file_paths:
            self._set_bitrate_slider_value(128)
            self.label_bitrate_hint.setText("По умолчанию: 128k")
            self._sync_preset_buttons(self._selected_bitrate_kbps())
            return

        # Для больших списков избегаем полного прохода по всем файлам в UI-потоке.
        scan_limit = 30 if len(file_paths) > 80 else len(file_paths)
        for file_path in file_paths[:scan_limit]:
            if file_path in self._bitrate_cache:
                continue
            try:
                self._bitrate_cache[file_path] = get_audio_bitrate_kbps(file_path)
            except Exception:
                self._bitrate_cache[file_path] = None

        detected = [self._bitrate_cache.get(fp) for fp in file_paths[:scan_limit]]
        known = [int(v) for v in detected if isinstance(v, int)]

        if not known:
            self._set_bitrate_slider_value(128)
            self.label_bitrate_hint.setText("Не удалось определить битрейт файлов. Используется 128k.")
            self._sync_preset_buttons(self._selected_bitrate_kbps())
            return

        unique = sorted(set(known))
        if len(unique) == 1:
            selected = self._nearest_slider_bitrate(unique[0])
            self._set_bitrate_slider_value(selected)
            self.label_bitrate_hint.setText(f"Определен битрейт исходников: {unique[0]}k")
            self._sync_preset_buttons(self._selected_bitrate_kbps())
            return

        # Для смешанных битрейтов выбираем моду (самое частое значение).
        # Если есть несколько лидеров, берём большее, чтобы меньше терять качество.
        counts = Counter(known)
        max_count = max(counts.values())
        candidates = [bitrate for bitrate, c in counts.items() if c == max_count]
        auto_choice = max(candidates)
        selected = self._nearest_slider_bitrate(auto_choice)
        min_kbps = min(unique)
        max_kbps = max(unique)

        self._set_bitrate_slider_value(selected)
        if len(file_paths) > scan_limit:
            self.label_bitrate_hint.setText(
                f"Разные битрейты ({min_kbps}k-{max_kbps}k) в выборке. По умолчанию выбран {selected}k."
            )
        else:
            self.label_bitrate_hint.setText(
                f"Разные битрейты ({min_kbps}k-{max_kbps}k). По умолчанию выбран {selected}k (самый частый)."
            )
        self._sync_preset_buttons(self._selected_bitrate_kbps())

    def _start_conversion(self):
        # Валидация
        chapters_data = self.chapter_list.get_chapters()
        if not chapters_data:
            QMessageBox.warning(self, "Ошибка", "Добавьте хотя бы один аудиофайл.")
            return

        chapter_titles = [title.strip() for _fp, title in chapters_data]
        if any(not t for t in chapter_titles):
            QMessageBox.warning(self, "Ошибка", "У каждой главы должно быть непустое название.")
            return
        lowered = [t.casefold() for t in chapter_titles]
        if len(set(lowered)) != len(lowered):
            QMessageBox.warning(self, "Ошибка", "Названия глав не должны дублироваться.")
            return

        output = self.edit_output.text().strip()
        if not output:
            self._browse_output()
            output = self.edit_output.text().strip()
            if not output:
                return

        if not output.lower().endswith(".m4b"):
            output += ".m4b"
            self.edit_output.setText(output)

        output_dir = Path(output).expanduser().resolve().parent
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось создать папку назначения:\n{exc}")
            return

        title = self.edit_title.text().strip() or Path(output).stem
        author = self.edit_author.text().strip() or "Unknown"

        chapters = [Chapter(file_path=fp, title=t) for fp, t in chapters_data]

        # Запуск
        self.btn_convert.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_add_files.setEnabled(False)
        self.btn_clear_list.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setVisible(True)
        self._progress_started_at = time.monotonic()
        self._last_progress_value = 0
        self.label_progress_status.setText("Подготовка конвертации…")

        self._worker = ConversionWorker(
            chapters=chapters,
            output_path=output,
            title=title,
            author=author,
            audio_bitrate_kbps=self._selected_bitrate_kbps(),
            cover_path=self.cover_label.cover_path,
        )
        self._is_cancelling = False
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.status.connect(self._on_worker_status)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self._save_settings()

    def _cancel_conversion(self):
        if self._worker and self._worker.isRunning():
            self._is_cancelling = True
            self._worker.cancel()
        self._reset_ui()
        self.status_bar.showMessage("Конвертация отменена.")
        self.label_progress_status.setText("Конвертация отменена")

    def _on_worker_progress(self, value: int):
        now_value = max(0, min(100, int(value)))
        self._last_progress_value = now_value
        self.progress_bar.setValue(now_value)

        if now_value <= 0:
            self.progress_bar.setFormat("%p%")
            return

        elapsed = max(0.1, time.monotonic() - self._progress_started_at)
        remaining_seconds = max(0.0, elapsed * (100 - now_value) / now_value)
        mins, secs = divmod(int(remaining_seconds), 60)
        self.progress_bar.setFormat(f"%p%  •  осталось ~{mins:02d}:{secs:02d}")

    def _on_worker_status(self, message: str):
        self.status_bar.showMessage(message)
        self.label_progress_status.setText(message)

    def _on_finished(self, output_path: str):
        if self._is_cancelling:
            self._worker = None
            return
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("%p%")
        msg = QMessageBox(self)
        msg.setWindowTitle("Готово!")
        msg.setIcon(QMessageBox.Information)
        msg.setText(f"Аудиокнига успешно создана:\n{output_path}")
        msg.setInformativeText("Что сделать дальше?")
        btn_open_folder = msg.addButton("Открыть папку", QMessageBox.AcceptRole)
        btn_open_file = msg.addButton("Открыть файл", QMessageBox.ActionRole)
        btn_new = msg.addButton("Собрать еще", QMessageBox.ActionRole)
        msg.addButton("Закрыть", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() == btn_open_folder:
            self._open_output_folder(output_path)
        elif msg.clickedButton() == btn_open_file:
            self._open_output_file(output_path)
        elif msg.clickedButton() == btn_new:
            self.chapter_list.clear()
            self.chapter_list.chapters_changed.emit()
            self.edit_output.clear()
        self._worker = None
        self.label_progress_status.setText("Готово: аудиокнига создана")
        self._reset_ui()

    def _on_error(self, message: str):
        if self._is_cancelling:
            self._worker = None
            return
        self._worker = None
        self._reset_ui()
        QMessageBox.critical(self, "Ошибка конвертации", message)
        self.status_bar.showMessage("Ошибка! " + message[:80])
        self.label_progress_status.setText("Ошибка конвертации")

    def _reset_ui(self):
        self.btn_convert.setEnabled(self.chapter_list.count() > 0 and bool(self.edit_output.text().strip()))
        self.btn_cancel.setVisible(False)
        self.btn_add_files.setEnabled(True)
        self.btn_clear_list.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self._update_step_state()

    def _load_settings(self):
        self.edit_title.setText(self._settings.value("title", "", str))
        self.edit_author.setText(self._settings.value("author", "", str))
        self.edit_output.setText(self._settings.value("output", "", str))
        try:
            bitrate = int(self._settings.value("bitrate", 128))
        except Exception:
            bitrate = 128
        self._set_bitrate_slider_value(bitrate)
        last_dir = self._settings.value("last_output_dir", str(Path.home() / "Desktop"), str)
        if last_dir and not Path(last_dir).exists():
            last_dir = str(Path.home() / "Desktop")
        self._settings.setValue("last_output_dir", last_dir)

    def _save_settings(self):
        self._settings.setValue("title", self.edit_title.text().strip())
        self._settings.setValue("author", self.edit_author.text().strip())
        self._settings.setValue("output", self.edit_output.text().strip())
        self._settings.setValue("bitrate", self._selected_bitrate_kbps())
        output = self.edit_output.text().strip()
        if output:
            self._settings.setValue("last_output_dir", str(Path(output).parent))

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    @staticmethod
    def _open_output_file(path: str):
        import subprocess

        target = str(Path(path).resolve())
        if sys.platform == "darwin":
            subprocess.Popen(["open", target])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", target])
        else:
            subprocess.Popen(["xdg-open", target])

    @staticmethod
    def _open_output_folder(path: str):
        import subprocess, platform
        target_dir = str(Path(path).resolve().parent)
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", target_dir])
        elif system == "Windows":
            subprocess.Popen(["explorer", target_dir])
        else:
            subprocess.Popen(["xdg-open", target_dir])


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AudioBook Maker")
    app.setStyleSheet(DARK_STYLE)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
