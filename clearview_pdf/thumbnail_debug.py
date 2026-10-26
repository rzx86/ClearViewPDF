"""Temporary opt-in thumbnail mouse diagnostics; not part of normal operation."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget


class ThumbnailMouseLogger(QObject):
    def __init__(self, window, path: Path) -> None:
        super().__init__(window)
        self.window = window
        self.handle = path.open("a", encoding="utf-8", buffering=1)
        self.log("run_start", pid=os.getpid())
        window.thumbnails.currentRowChanged.connect(
            lambda row: self.log("currentRowChanged", row=row)
        )
        window.thumbnails.itemPressed.connect(
            lambda item: self.log("itemPressed", row=window.thumbnails.row(item))
        )
        window.thumbnails.itemClicked.connect(
            lambda item: self.log("itemClicked", row=window.thumbnails.row(item))
        )
        window.bookmarks_list.currentRowChanged.connect(
            lambda row: self.log("bookmarkCurrentRowChanged", row=row)
        )
        window.bookmarks_list.itemPressed.connect(
            lambda item: self.log("bookmarkItemPressed", row=window.bookmarks_list.row(item))
        )
        window.bookmarks_list.itemClicked.connect(
            lambda item: self.log("bookmarkItemClicked", row=window.bookmarks_list.row(item))
        )
        window.bookmark_action.toggled.connect(
            lambda checked: self.log("bookmarkActionToggled", checked=checked)
        )
        window.view.currentPageChanged.connect(
            lambda page: self.log("currentPageChanged", page=page)
        )
        QApplication.instance().aboutToQuit.connect(self.handle.close)

    @staticmethod
    def widget_info(widget: QWidget | None) -> dict:
        if widget is None:
            return {"class": None, "name": None}
        return {"class": widget.metaObject().className(), "name": widget.objectName()}

    def widget_role(self, widget: QWidget | None) -> str | None:
        if widget is self.window.thumbnails.viewport():
            return "thumbnails"
        if widget is self.window.bookmarks_list.viewport():
            return "bookmarks"
        if widget is self.window.view.viewport():
            return "document"
        return None

    def log(self, kind: str, **fields) -> None:
        record = {
            "debug": "[DEBUG-thumbs]",
            "time": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **fields,
        }
        self.handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def eventFilter(self, receiver: QObject, event) -> bool:  # noqa: N802 - Qt API
        mouse_types = {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        }
        if event.type() not in mouse_types:
            return False
        global_point = event.globalPosition().toPoint()
        thumbnails = self.window.thumbnails
        viewport = thumbnails.viewport()
        local_point = viewport.mapFromGlobal(global_point)
        item = thumbnails.itemAt(local_point)
        widget_at = QApplication.widgetAt(global_point)
        bookmarks = self.window.bookmarks_list
        bookmark_local = bookmarks.viewport().mapFromGlobal(global_point)
        bookmark_item = bookmarks.itemAt(bookmark_local)
        receiver_widget = receiver if isinstance(receiver, QWidget) else None
        self.log(
            "mouse",
            event_type=event.type().name,
            receiver=self.widget_info(receiver_widget),
            receiver_role=self.widget_role(receiver_widget),
            widget_at=self.widget_info(widget_at),
            widget_at_role=self.widget_role(widget_at),
            global_point=[global_point.x(), global_point.y()],
            thumbnail_local=[local_point.x(), local_point.y()],
            item_at_row=thumbnails.row(item) if item is not None else -1,
            bookmark_local=[bookmark_local.x(), bookmark_local.y()],
            bookmark_item_at_row=bookmarks.row(bookmark_item) if bookmark_item is not None else -1,
            bookmark_current_row=bookmarks.currentRow(),
            bookmark_count=bookmarks.count(),
            current_row=thumbnails.currentRow(),
            viewport_rect=list(viewport.rect().getRect()),
            item_rect=list(thumbnails.visualItemRect(item).getRect()) if item is not None else None,
            button=str(event.button()),
            buttons=str(event.buttons()),
            dpr=viewport.devicePixelRatioF(),
        )
        return False


def install_thumbnail_debug(window) -> ThumbnailMouseLogger:
    path = Path(os.environ["CLEARVIEW_THUMBNAIL_DEBUG"])
    logger = ThumbnailMouseLogger(window, path)
    QApplication.instance().installEventFilter(logger)
    return logger
