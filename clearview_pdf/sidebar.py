"""Lightweight, on-demand thumbnail sidebar."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from .document import PDFDocument
from .view import qimage_from_pixmap


class ThumbnailList(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.document: Optional[PDFDocument] = None
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(192, 288))
        self.setGridSize(QSize(224, 330))
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.verticalScrollBar().valueChanged.connect(self._schedule_load)
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(30)
        self._load_timer.timeout.connect(self.load_visible)

    def shutdown(self) -> None:
        self._load_timer.stop()
        self.document = None
        self.clear()

    def set_document(self, document: PDFDocument) -> None:
        self.clear()
        self.document = document
        page_width, page_height = document.page_size(0)
        icon_height = min(288, max(1, round(192 * page_height / page_width)))
        self.setIconSize(QSize(192, icon_height))
        self.setGridSize(QSize(224, icon_height + 32))
        for page_index in range(document.page_count):
            item = QListWidgetItem(str(page_index + 1))
            item.setSizeHint(
                QSize(self.iconSize().width() + 16, self.iconSize().height() + 24)
            )
            item.setData(Qt.ItemDataRole.UserRole, page_index)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setToolTip(f"Page {page_index + 1}")
            self.addItem(item)
        QTimer.singleShot(0, self.load_visible)

    def _schedule_load(self) -> None:
        self._load_timer.start()

    def load_visible(self) -> None:
        if self.document is None:
            return
        viewport = self.viewport().rect().adjusted(0, -300, 0, 300)
        for row in range(self.count()):
            item = self.item(row)
            if not viewport.intersects(self.visualItemRect(item)):
                continue
            if not item.icon().isNull():
                continue
            page_index = item.data(Qt.ItemDataRole.UserRole)
            width, _ = self.document.page_size(page_index)
            pixmap = self.document.render_page(page_index, zoom=self.iconSize().width() / width)
            image = qimage_from_pixmap(pixmap)
            icon = QPixmap.fromImage(image).scaled(
                self.iconSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            item.setIcon(QIcon(icon))

    def set_current_page(self, page_index: int) -> None:
        if 0 <= page_index < self.count():
            previously_blocked = self.blockSignals(True)
            try:
                self.setCurrentRow(page_index)
            finally:
                self.blockSignals(previously_blocked)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._schedule_load()
