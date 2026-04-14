"""
widgets.py — кастомный QListWidget с drag-and-drop и редактированием глав.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class ChapterItemWidget(QWidget):
    """Виджет одной строки: иконка-ручка + номер + редактируемое имя + кнопка удалить."""

    remove_requested = Signal(QListWidgetItem)
    title_changed = Signal()

    def __init__(self, file_path: str, chapter_title: str, duration_text: str = "--:--", parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self._item_ref: Optional[QListWidgetItem] = None

        # Фиксированная высота строки устраняет смещения между платформами.
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(6)

        self.index_lbl = QLabel("01")
        self.index_lbl.setFixedWidth(24)
        self.index_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.index_lbl.setStyleSheet("color: #a0a0a0; font-size: 11px; font-weight: 600;")
        layout.addWidget(self.index_lbl, 0, Qt.AlignVCenter)

        # Иконка перетаскивания
        drag_lbl = QLabel("⠿")
        drag_lbl.setFont(QFont("", 15))
        drag_lbl.setFixedWidth(16)
        drag_lbl.setAlignment(Qt.AlignCenter)
        drag_lbl.setCursor(Qt.OpenHandCursor)
        drag_lbl.setToolTip("Перетащите для изменения порядка")
        drag_lbl.setStyleSheet("color: #888;")
        layout.addWidget(drag_lbl, 0, Qt.AlignVCenter)

        # Поле с названием главы
        self.title_edit = QLineEdit(chapter_title)
        self.title_edit.setPlaceholderText("Название главы…")
        self.title_edit.setFixedHeight(26)
        self.title_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.title_edit.textChanged.connect(self.title_changed)
        layout.addWidget(self.title_edit, 1, Qt.AlignVCenter)

        self.duration_lbl = QLabel(duration_text)
        self.duration_lbl.setFixedWidth(54)
        self.duration_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.duration_lbl.setStyleSheet("color: #8a8a8a; font-size: 11px;")
        layout.addWidget(self.duration_lbl, 0, Qt.AlignVCenter)

        # Имя файла (серый текст)
        fname = Path(file_path).name
        file_lbl = QLabel(fname)
        file_lbl.setStyleSheet("color: #888; font-size: 11px;")
        file_lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        file_lbl.setToolTip(file_path)
        layout.addWidget(file_lbl, 0, Qt.AlignVCenter)

        # Кнопка удалить
        btn_remove = QPushButton("×")
        btn_remove.setFixedSize(22, 22)
        btn_remove.setFont(QFont("", 15, QFont.Bold))
        btn_remove.setStyleSheet(
            """
            QPushButton {
                border: none;
                color: #c0392b;
                background: transparent;
                font-weight: bold;
                border-radius: 11px;
                padding: 0;
                min-width: 22px;
                min-height: 22px;
            }
            QPushButton:hover {
                color: #e74c3c;
                background: rgba(192,57,43,0.08);
            }
            QPushButton:pressed {
                color: #a93226;
                background: rgba(192,57,43,0.16);
            }
            """
        )
        btn_remove.setToolTip("Удалить из списка")
        btn_remove.clicked.connect(self._on_remove)
        layout.addWidget(btn_remove, 0, Qt.AlignVCenter)

    def set_item_ref(self, item: QListWidgetItem):
        self._item_ref = item

    def title(self) -> str:
        return self.title_edit.text().strip()

    def set_index(self, index: int) -> None:
        self.index_lbl.setText(f"{index:02d}")

    def set_invalid(self, is_invalid: bool) -> None:
        if is_invalid:
            self.title_edit.setStyleSheet("border: 1px solid #c0392b;")
            self.title_edit.setToolTip("Название не должно быть пустым и не должно дублироваться")
        else:
            self.title_edit.setStyleSheet("")
            self.title_edit.setToolTip("")

    def _on_remove(self):
        if self._item_ref:
            self.remove_requested.emit(self._item_ref)


class ChapterListWidget(QListWidget):
    """QListWidget с внутренним Drag & Drop и именованными главами."""

    chapters_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_active = False
        self.setDragDropMode(QListWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setSpacing(2)
        self.setMinimumHeight(200)
        self.setAcceptDrops(True)
        self._apply_style()
        # После перетаскивания эмитируем сигнал
        self.model().rowsMoved.connect(self._on_rows_moved)

    def _apply_style(self) -> None:
        border = "#2f7b6c" if self._drag_active else "#555"
        self.setStyleSheet(
            f"QListWidget {{ border: 1px solid {border}; border-radius: 8px; background: #232323; }}"
            "QListWidget::item:selected { background: #2f3e3b; }"
            "QListWidget::item:hover { background: #2b3231; }"
        )

    @staticmethod
    def _normalized_title_from_path(file_path: str) -> str:
        stem = Path(file_path).stem
        stem = re.sub(r"\s+", " ", stem).strip()

        # Поддерживаем шаблон вида "001 - Название" и сохраняем номер главы.
        match = re.match(r"^(\d{1,4})\s*[-._)\]]+\s*(.+)$", stem)
        if match:
            number, title = match.groups()
            title = re.sub(r"\s+", " ", title.replace("_", " ").strip(" -._"))
            if title:
                return f"{number}. {title}"
            return f"{number}. Глава"

        # Для остальных случаев оставляем текст, убирая только лишние разделители.
        stem = stem.replace("_", " ")
        stem = re.sub(r"\s+", " ", stem).strip(" -._")
        return stem[:1].upper() + stem[1:] if stem else "Глава"

    @staticmethod
    def _duration_text(file_path: str) -> str:
        try:
            from mutagen import File as MutagenFile

            data = MutagenFile(file_path)
            if not data or not getattr(data, "info", None) or not getattr(data.info, "length", None):
                return "--:--"
            total = int(max(0, round(float(data.info.length))))
            minutes, seconds = divmod(total, 60)
            hours, minutes = divmod(minutes, 60)
            if hours > 0:
                return f"{hours:d}:{minutes:02d}:{seconds:02d}"
            return f"{minutes:02d}:{seconds:02d}"
        except Exception:
            return "--:--"

    def _refresh_indexes(self) -> None:
        for i in range(self.count()):
            item = self.item(i)
            widget: ChapterItemWidget = self.itemWidget(item)
            widget.set_index(i + 1)

    def _refresh_validation(self) -> None:
        titles = []
        for i in range(self.count()):
            item = self.item(i)
            widget: ChapterItemWidget = self.itemWidget(item)
            titles.append(widget.title().casefold())
        duplicates = {t for t in titles if t and titles.count(t) > 1}

        for i in range(self.count()):
            item = self.item(i)
            widget: ChapterItemWidget = self.itemWidget(item)
            title = widget.title().casefold()
            widget.set_invalid((not title) or (title in duplicates))

    def _on_item_title_changed(self) -> None:
        self._refresh_validation()
        self.chapters_changed.emit()

    def _on_rows_moved(self, *_args) -> None:
        self._refresh_indexes()
        self._refresh_validation()
        self.chapters_changed.emit()

    def _append_chapter_widget(self, file_path: str, title: str, duration_text: str) -> None:
        item = QListWidgetItem(self)
        widget = ChapterItemWidget(file_path, title, duration_text=duration_text)
        widget.set_item_ref(item)
        widget.remove_requested.connect(self._remove_item)
        widget.title_changed.connect(self._on_item_title_changed)
        item.setSizeHint(QSize(0, 36))
        self.addItem(item)
        self.setItemWidget(item, widget)

    # ── Drag-and-drop с файловой системы ──────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self._drag_active = True
            self._apply_style()
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            self._drag_active = True
            self._apply_style()
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._drag_active = False
        self._apply_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drag_active = False
        self._apply_style()
        if event.mimeData().hasUrls():
            mp3_paths = [
                u.toLocalFile()
                for u in event.mimeData().urls()
                if u.toLocalFile().lower().endswith((".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"))
            ]
            self.add_chapters(mp3_paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
            # внутреннее перемещение уже эмитируется через rowsMoved

    # ── Публичное API ──────────────────────────────────────────────────
    def add_chapter(self, file_path: str, title: str = "", compute_duration: bool = True, emit_change: bool = True) -> None:
        if not title:
            title = self._normalized_title_from_path(file_path)
        duration_text = self._duration_text(file_path) if compute_duration else "--:--"
        self._append_chapter_widget(file_path, title, duration_text)
        self._refresh_indexes()
        self._refresh_validation()
        if emit_change:
            self.chapters_changed.emit()

    def add_chapters(self, file_paths: list[str]) -> None:
        if not file_paths:
            return

        self.setUpdatesEnabled(False)
        try:
            for file_path in file_paths:
                title = self._normalized_title_from_path(file_path)
                # Для больших батчей избегаем чтения длительности в UI-потоке.
                self._append_chapter_widget(file_path, title, "--:--")
            self._refresh_indexes()
            self._refresh_validation()
        finally:
            self.setUpdatesEnabled(True)

        self.chapters_changed.emit()

    def get_chapters(self) -> list[tuple[str, str]]:
        """Возвращает [(file_path, chapter_title), …] в текущем порядке."""
        result = []
        for i in range(self.count()):
            item = self.item(i)
            widget: ChapterItemWidget = self.itemWidget(item)
            result.append((widget.file_path, widget.title()))
        return result

    def _remove_item(self, item: QListWidgetItem):
        row = self.row(item)
        if row >= 0:
            self.takeItem(row)
            self._refresh_indexes()
            self._refresh_validation()
            self.chapters_changed.emit()
