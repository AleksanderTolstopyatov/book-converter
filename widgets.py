"""
widgets.py — кастомный QListWidget с drag-and-drop и редактированием глав.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QFont
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

    def __init__(self, file_path: str, chapter_title: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self._item_ref: Optional[QListWidgetItem] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # Иконка перетаскивания
        drag_lbl = QLabel("⠿")
        drag_lbl.setFont(QFont("", 16))
        drag_lbl.setCursor(Qt.OpenHandCursor)
        drag_lbl.setToolTip("Перетащите для изменения порядка")
        drag_lbl.setStyleSheet("color: #888;")
        layout.addWidget(drag_lbl)

        # Поле с названием главы
        self.title_edit = QLineEdit(chapter_title)
        self.title_edit.setPlaceholderText("Название главы…")
        self.title_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.title_edit.textChanged.connect(self.title_changed)
        layout.addWidget(self.title_edit)

        # Имя файла (серый текст)
        fname = Path(file_path).name
        file_lbl = QLabel(fname)
        file_lbl.setStyleSheet("color: #888; font-size: 11px;")
        file_lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        file_lbl.setToolTip(file_path)
        layout.addWidget(file_lbl)

        # Кнопка удалить
        btn_remove = QPushButton("✕")
        btn_remove.setFixedSize(24, 24)
        btn_remove.setStyleSheet(
            "QPushButton { border: none; color: #c0392b; font-weight: bold; }"
            "QPushButton:hover { color: #e74c3c; }"
        )
        btn_remove.setToolTip("Удалить из списка")
        btn_remove.clicked.connect(self._on_remove)
        layout.addWidget(btn_remove)

    def set_item_ref(self, item: QListWidgetItem):
        self._item_ref = item

    def title(self) -> str:
        return self.title_edit.text().strip()

    def _on_remove(self):
        if self._item_ref:
            self.remove_requested.emit(self._item_ref)


class ChapterListWidget(QListWidget):
    """QListWidget с внутренним Drag & Drop и именованными главами."""

    chapters_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setSpacing(2)
        self.setMinimumHeight(200)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            "QListWidget { border: 1px solid #555; border-radius: 6px; background: #2b2b2b; }"
            "QListWidget::item:selected { background: #3a3a3a; }"
            "QListWidget::item:hover { background: #333333; }"
        )
        # После перетаскивания эмитируем сигнал
        self.model().rowsMoved.connect(self.chapters_changed)

    # ── Drag-and-drop с файловой системы ──────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            mp3_paths = [
                u.toLocalFile()
                for u in event.mimeData().urls()
                if u.toLocalFile().lower().endswith((".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"))
            ]
            for p in mp3_paths:
                self.add_chapter(p)
            event.acceptProposedAction()
            self.chapters_changed.emit()
        else:
            super().dropEvent(event)
            # внутреннее перемещение уже эмитируется через rowsMoved

    # ── Публичное API ──────────────────────────────────────────────────
    def add_chapter(self, file_path: str, title: str = "") -> None:
        if not title:
            title = Path(file_path).stem
        item = QListWidgetItem(self)
        widget = ChapterItemWidget(file_path, title)
        widget.set_item_ref(item)
        widget.remove_requested.connect(self._remove_item)
        widget.title_changed.connect(self.chapters_changed)
        item.setSizeHint(widget.sizeHint())
        self.addItem(item)
        self.setItemWidget(item, widget)
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
            self.chapters_changed.emit()
