"""Qt page canvas with lazy rendering, highlights, links, and text selection."""

from __future__ import annotations

from typing import Optional

import re

import pymupdf
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QMenu, QScrollArea, QVBoxLayout, QWidget

from .document import PDFDocument, SearchHit
from .selection import TextWord, select_words, words_to_text


_WEB_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _web_link_for_word(word) -> Optional[dict]:
    match = _WEB_URL.search(word.text)
    if match is None:
        return None
    uri = match.group(0).rstrip(".,;:!?)]}")
    if uri.lower() in {"http://", "https://", "www."}:
        return None
    if uri.lower().startswith("www."):
        uri = "https://" + uri
    return {
        "kind": pymupdf.LINK_URI,
        "from": pymupdf.Rect(word.rect),
        "uri": uri,
    }


def qimage_from_pixmap(pixmap: pymupdf.Pixmap) -> QImage:
    """Copy MuPDF's RGB samples into Qt-owned memory."""

    image = QImage(
        pixmap.samples,
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        QImage.Format.Format_RGB888,
    )
    return image.copy()


class PageWidget(QWidget):
    selectionChanged = Signal(str)
    linkActivated = Signal(object)
    pressed = Signal(int)
    rotateRequested = Signal(int)
    panStarted = Signal(object)
    panMoved = Signal(object)
    panEnded = Signal()

    def __init__(
        self,
        document: PDFDocument,
        page_index: int,
        zoom: float,
        rotation: int,
        dark: bool,
    ) -> None:
        super().__init__()
        self.document = document
        self.page_index = page_index
        self.zoom = zoom
        self.rotation = rotation
        self.dark = dark
        self.image = QImage()
        self.words: list[TextWord] = []
        self.selected_words: list[TextWord] = []
        self.search_rects: list[tuple[float, float, float, float]] = []
        self.current_search_rect: Optional[tuple[float, float, float, float]] = None
        self._links: list[dict] = []
        self._drag_start: Optional[tuple[float, float]] = None
        self._drag_moved = False
        self._panning = False
        self._render_key: Optional[tuple] = None
        self._matrix = pymupdf.Matrix()
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.update_display(zoom, rotation, dark)

    def update_display(self, zoom: float, rotation: int, dark: bool) -> None:
        old_key = (self.zoom, self.rotation, self.dark, self.devicePixelRatioF())
        self.zoom = zoom
        self.rotation = rotation % 360
        self.dark = dark
        width, height = self.document.page_size(self.page_index, self.rotation)
        self.setFixedSize(max(1, round(width * zoom)), max(1, round(height * zoom)))

        page = self.document.page(self.page_index)
        matrix = page.rotation_matrix * pymupdf.Matrix(zoom, zoom).prerotate(
            self.rotation
        )
        bounds = page.cropbox * matrix
        self._matrix = pymupdf.Matrix(
            matrix.a,
            matrix.b,
            matrix.c,
            matrix.d,
            matrix.e - bounds.x0,
            matrix.f - bounds.y0,
        )
        new_key = (self.zoom, self.rotation, self.dark, self.devicePixelRatioF())
        if old_key != new_key:
            self.clear_image()
        self.update()

    def clear_image(self) -> None:
        self.image = QImage()
        self._render_key = None
        self.update()

    def render(self, force: bool = False) -> None:
        key = (self.zoom, self.rotation, self.dark, self.devicePixelRatioF())
        if not force and self._render_key == key and not self.image.isNull():
            return
        pixmap = self.document.render_page(
            self.page_index,
            zoom=self.zoom * self.devicePixelRatioF(),
            rotation=self.rotation,
        )
        self.image = qimage_from_pixmap(pixmap)
        page = self.document.page(self.page_index)
        self.words = [
            TextWord(tuple(word[:4]), word[4], word[5], word[6], word[7])
            for word in page.get_text("words", sort=False)
        ]
        self._links = page.get_links()
        self._links.extend(
            link
            for word in self.words
            if (link := _web_link_for_word(word)) is not None
        )
        self._render_key = key
        self.update()

    def _widget_rect(self, rect) -> QRectF:
        transformed = pymupdf.Rect(rect) * self._matrix
        return QRectF(
            transformed.x0,
            transformed.y0,
            transformed.width,
            transformed.height,
        )

    def _pdf_point(self, point: QPoint) -> tuple[float, float]:
        transformed = pymupdf.Point(point.x(), point.y()) * ~self._matrix
        return (transformed.x, transformed.y)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        if self.image.isNull():
            painter.setPen(QColor("#888888"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, f"Page {self.page_index + 1}"
            )
            return
        painter.drawImage(self.rect(), self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for rect in self.search_rects:
            painter.fillRect(self._widget_rect(rect), QColor(255, 213, 0, 75))
        if self.current_search_rect is not None:
            painter.fillRect(
                self._widget_rect(self.current_search_rect), QColor(255, 119, 0, 125)
            )
        for word in self.selected_words:
            painter.fillRect(self._widget_rect(word.rect), QColor(35, 116, 230, 80))

    def _set_selection(self, start, end) -> None:
        self.selected_words = select_words(self.words, start, end)
        self.selectionChanged.emit(words_to_text(self.selected_words))
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.panStarted.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit(self.page_index)
            self._drag_start = self._pdf_point(event.position().toPoint())
            self._drag_moved = False
            self.selected_words = []
            self.selectionChanged.emit("")
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._panning and event.buttons() & Qt.MouseButton.MiddleButton:
            self.panMoved.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_moved = True
            self._set_selection(self._drag_start, self._pdf_point(event.position().toPoint()))
            event.accept()
            return
        link = self._link_at(event.position().toPoint())
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if link else Qt.CursorShape.IBeamCursor
        )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.IBeamCursor)
            self.panEnded.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            if not self._drag_moved:
                link = self._link_at(event.position().toPoint())
                if link:
                    self.linkActivated.emit(link)
            self._drag_start = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        point = self._pdf_point(event.position().toPoint())
        self.selected_words = select_words(self.words, point, point)
        self.selectionChanged.emit(words_to_text(self.selected_words))
        self.update()
        event.accept()

    def _link_at(self, point: QPoint) -> Optional[dict]:
        pdf_point = pymupdf.Point(*self._pdf_point(point))
        for link in self._links:
            if pymupdf.Rect(link["from"]).contains(pdf_point):
                return link
        return None

    def select_all(self) -> None:
        self.selected_words = sorted(
            self.words, key=lambda word: (word.block, word.line, word.word)
        )
        self.selectionChanged.emit(words_to_text(self.selected_words))
        self.update()

    def copy_selection(self) -> None:
        QGuiApplication.clipboard().setText(words_to_text(self.selected_words))

    def _show_context_menu(self, point: QPoint) -> None:
        menu = QMenu(self)
        copy = menu.addAction("Copy", self.copy_selection)
        copy.setEnabled(bool(self.selected_words))
        menu.addAction("Select all page text", self.select_all)
        menu.addAction(
            "Copy page text",
            lambda: QGuiApplication.clipboard().setText(
                self.document.page_text(self.page_index)
            ),
        )
        menu.addSeparator()
        menu.addAction(
            "Rotate 90° clockwise  (Ctrl++)",
            lambda: self.rotateRequested.emit(90),
        )
        menu.addAction(
            "Rotate 90° counterclockwise",
            lambda: self.rotateRequested.emit(-90),
        )
        menu.addAction("Reset rotation", lambda: self.rotateRequested.emit(0))
        menu.exec(self.mapToGlobal(point))


class DocumentView(QScrollArea):
    currentPageChanged = Signal(int)
    zoomChanged = Signal(float)
    selectionChanged = Signal(str)
    linkActivated = Signal(object)
    rotateRequested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.document: Optional[PDFDocument] = None
        self.pages: list[PageWidget] = []
        self.current_page = 0
        self.zoom = 1.0
        self.fit_mode = "width"
        self.rotation = 0
        self.dark = False
        self.continuous = True
        self.selected_text = ""
        self._pan_point = QPoint()
        self._pan_delta = QPoint()
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(16)
        self._auto_scroll_timer.timeout.connect(self._auto_scroll)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setBackgroundRole(self.backgroundRole())
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(15)
        self._render_timer.timeout.connect(self.render_visible)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def shutdown(self) -> None:
        """Detach the document and invalidate all queued rendering callbacks."""

        self._auto_scroll_timer.stop()
        self._pan_delta = QPoint()
        self._render_timer.stop()
        self.document = None
        self.pages = []
        self.selected_text = ""
        old = self.takeWidget()
        if old is not None:
            old.deleteLater()

    def set_document(self, document: PDFDocument) -> None:
        self._auto_scroll_timer.stop()
        self._pan_delta = QPoint()
        old = self.takeWidget()
        if old is not None:
            old.deleteLater()
        self.document = document
        self.pages = []
        self.current_page = 0
        canvas = QWidget()
        canvas.setObjectName("documentCanvas")
        canvas.setStyleSheet("QWidget#documentCanvas { background: #53585e; }")
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        for page_index in range(document.page_count):
            page = PageWidget(document, page_index, self.zoom, self.rotation, self.dark)
            page.selectionChanged.connect(
                lambda text, index=page_index: self._on_page_selection(index, text)
            )
            page.linkActivated.connect(self.linkActivated)
            page.pressed.connect(self._set_current_page)
            page.rotateRequested.connect(self.rotateRequested)
            page.panStarted.connect(self._start_pan)
            page.panMoved.connect(self._move_pan)
            page.panEnded.connect(self._end_pan)
            layout.addWidget(page, 0, Qt.AlignmentFlag.AlignHCenter)
            self.pages.append(page)
        self.setWidget(canvas)
        self.set_continuous(self.continuous)
        QTimer.singleShot(0, self.render_visible)

    def _start_pan(self, point: QPoint) -> None:
        self._pan_point = point
        self._pan_delta = QPoint()
        self._auto_scroll_timer.start()

    def _move_pan(self, point: QPoint) -> None:
        self._pan_delta = point - self._pan_point

    def _auto_scroll(self) -> None:
        for offset, scrollbar in (
            (self._pan_delta.x(), self.horizontalScrollBar()),
            (self._pan_delta.y(), self.verticalScrollBar()),
        ):
            magnitude = abs(offset) - 6
            if magnitude <= 0:
                continue
            step = min(96, (magnitude + 4) // 5)
            scrollbar.setValue(scrollbar.value() + (step if offset > 0 else -step))

    def _end_pan(self) -> None:
        self._auto_scroll_timer.stop()
        self._pan_delta = QPoint()
        self.render_visible()

    def _on_page_selection(self, page_index: int, text: str) -> None:
        for index, page in enumerate(self.pages):
            if index != page_index and page.selected_words:
                page.selected_words = []
                page.update()
        self.selected_text = text
        self.selectionChanged.emit(text)

    def _set_current_page(self, page_index: int) -> None:
        if page_index == self.current_page:
            return
        self.current_page = page_index
        self.currentPageChanged.emit(page_index)

    def _on_scroll(self) -> None:
        self._render_timer.start()
        if not self.pages or not self.continuous:
            return
        viewport_top = self.verticalScrollBar().value()
        viewport_bottom = viewport_top + self.viewport().height()
        visible = []
        for page in self.pages:
            top = page.y()
            bottom = top + page.height()
            overlap = max(0, min(bottom, viewport_bottom) - max(top, viewport_top))
            if overlap:
                visible.append((overlap, page.page_index))
        if visible:
            self._set_current_page(max(visible)[1])

    def render_visible(self) -> None:
        if not self.pages:
            return
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        preload = self.viewport().height()
        release_distance = self.viewport().height() * 4
        for page in self.pages:
            page_top = page.y()
            page_bottom = page_top + page.height()
            if page_bottom >= top - preload and page_top <= bottom + preload:
                page.render()
            elif page_bottom < top - release_distance or page_top > bottom + release_distance:
                page.clear_image()

    def go_to_page(self, page_index: int) -> None:
        if not self.pages:
            return
        page_index = max(0, min(page_index, len(self.pages) - 1))
        if not self.continuous:
            self.current_page = page_index
            self.set_continuous(False)
        canvas = self.widget()
        if canvas is not None and canvas.layout() is not None:
            canvas.layout().invalidate()
            canvas.layout().activate()
            canvas.adjustSize()
        page = self.pages[page_index]
        page.render()
        self.verticalScrollBar().setValue(max(0, page.y() - 16))
        self._set_current_page(page_index)
        self.render_visible()

    def center_on_rect(self, page_index: int, rect) -> None:
        if not 0 <= page_index < len(self.pages):
            return
        self.go_to_page(page_index)
        page = self.pages[page_index]
        target = page._widget_rect(rect)
        self.verticalScrollBar().setValue(
            max(0, round(page.y() + target.center().y() - self.viewport().height() / 2))
        )
        self.horizontalScrollBar().setValue(
            max(0, round(page.x() + target.center().x() - self.viewport().width() / 2))
        )

    def set_search_hits(self, hits: list[SearchHit], current: int = -1) -> None:
        by_page: dict[int, list] = {index: [] for index in range(len(self.pages))}
        for hit in hits:
            if not 0 <= hit.page_index < len(self.pages):
                continue
            rectangles = hit.rects or ((hit.rect,) if hit.rect[2] > hit.rect[0] else ())
            by_page[hit.page_index].extend(rectangles)
        current_hit = hits[current] if 0 <= current < len(hits) else None
        for index, page in enumerate(self.pages):
            page.search_rects = by_page[index]
            page.current_search_rect = (
                current_hit.rect
                if current_hit is not None and current_hit.page_index == index
                else None
            )
            page.update()

    def set_zoom(self, zoom: float, fit_mode: str = "custom") -> None:
        zoom = max(0.20, min(5.0, zoom))
        self.zoom = zoom
        self.fit_mode = fit_mode
        current = self.current_page
        for page in self.pages:
            page.update_display(zoom, self.rotation, self.dark)
        if self.widget() is not None and self.widget().layout() is not None:
            self.widget().layout().activate()
        self.go_to_page(current)
        self.zoomChanged.emit(zoom)

    def apply_fit(self) -> None:
        if not self.pages or self.fit_mode == "custom":
            return
        width, height = self.document.page_size(self.current_page, self.rotation)
        available_width = max(100, self.viewport().width() - 40)
        available_height = max(100, self.viewport().height() - 40)
        if self.fit_mode == "width":
            zoom = available_width / width
        elif self.fit_mode == "height":
            zoom = available_height / height
        else:
            return
        self.set_zoom(zoom, self.fit_mode)

    def set_fit_mode(self, mode: str) -> None:
        self.fit_mode = mode
        self.apply_fit()

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom / 1.2)

    def set_rotation(self, rotation: int) -> None:
        self.rotation = rotation % 360
        for page in self.pages:
            page.update_display(self.zoom, self.rotation, self.dark)
        self.apply_fit()
        self.go_to_page(self.current_page)

    def set_dark(self, dark: bool) -> None:
        self.dark = dark
        for page in self.pages:
            page.update_display(self.zoom, self.rotation, dark)
        self.render_visible()

    def set_continuous(self, continuous: bool) -> None:
        self.continuous = continuous
        for index, page in enumerate(self.pages):
            page.setVisible(continuous or index == self.current_page)
        self.render_visible()

    def clear_selection(self) -> None:
        for page in self.pages:
            page.selected_words = []
            page.update()
        self.selected_text = ""
        self.selectionChanged.emit("")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self.fit_mode != "custom" and self.pages:
            QTimer.singleShot(0, self.apply_fit)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)
