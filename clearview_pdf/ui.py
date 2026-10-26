"""ClearView PDF main window."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pymupdf
from PySide6.QtCore import QLineF, QRectF, QSize, QStandardPaths, QThread, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QIntValidator,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .document import DocumentError, InvalidPassword, PasswordRequired, PDFDocument
from .search import SearchOptions, merge_search_hits
from .semantic import LocalEmbeddingModel
from .semantic_worker import SemanticSearchWorker
from .sidebar import ThumbnailList
from .state import Bookmark, DocumentState, StateStore
from .view import DocumentView, qimage_from_pixmap

LIGHT_STYLE = """
QMainWindow, QDialog { background: #f4f5f7; color: #20252b; }
QMenuBar { background: #f4f5f7; color: #20252b; }
QMenuBar::item { background: transparent; color: #20252b; padding: 4px 8px; }
QMenuBar::item:selected { background: #dfe5ec; }
QMenu { background: white; color: #20252b; }
QMenu::item:selected { background: #2f6f9f; color: white; }
QLabel, QCheckBox, QTabBar::tab { color: #20252b; }
QTabBar::tab { background: #e7eaee; padding: 6px 10px; }
QTabBar::tab:selected { background: white; }
QToolBar { background: #f4f5f7; color: #20252b; border: 0; spacing: 4px; padding: 5px; }
QToolBar#documentToolbar { padding: 2px 4px; spacing: 2px; }
QToolBar QToolButton { color: #20252b; padding: 5px 8px; border-radius: 4px; }
QToolBar#documentToolbar QToolButton { padding: 2px; }
QToolBar QToolButton:hover, QToolButton:hover { background: #dfe5ec; }
QToolBar QToolButton:checked { background: #c7d9ee; }
QLineEdit, QComboBox, QListWidget, QTreeWidget, QTabWidget::pane {
  background: white; color: #20252b; border: 1px solid #c8cdd3; border-radius: 4px;
}
QDockWidget::title { background: #e7eaee; color: #20252b; padding: 6px; }
QStatusBar { background: #f4f5f7; color: #20252b; }
"""
DARK_STYLE = """
QMainWindow, QDialog, QWidget#welcomePage { background: #25282c; color: #e5e7eb; }
QMenuBar { background: #25282c; color: #e5e7eb; }
QMenuBar::item { background: transparent; color: #e5e7eb; padding: 4px 8px; }
QMenuBar::item:selected { background: #41464d; }
QLabel, QCheckBox, QTabBar::tab { color: #e5e7eb; }
QTabBar::tab { background: #25282c; padding: 6px 10px; }
QTabBar::tab:selected { background: #30343a; }
QToolBar, QStatusBar { background: #25282c; color: #e5e7eb; border: 0; spacing: 4px; padding: 5px; }
QToolBar#documentToolbar { padding: 2px 4px; spacing: 2px; }
QToolBar QToolButton, QToolButton { color: #e5e7eb; padding: 5px 8px; border-radius: 4px; }
QToolBar#documentToolbar QToolButton { padding: 2px; }
QToolBar QToolButton:hover, QToolButton:hover { background: #41464d; }
QToolBar QToolButton:checked { background: #345675; }
QLineEdit, QComboBox, QListWidget, QTreeWidget, QTabWidget::pane {
  background: #30343a; color: #e5e7eb; border: 1px solid #535a63; border-radius: 4px;
}
QDockWidget::title { background: #30343a; color: #e5e7eb; padding: 6px; }
QMenu { background: #30343a; color: #e5e7eb; }
QMenu::item:selected { background: #345675; }
"""


def reading_palette(dark: bool) -> QPalette:
    """Explicit colors so Windows' system theme cannot make light text illegible."""

    palette = QPalette()
    text = QColor("#e5e7eb" if dark else "#20252b")
    window = QColor("#25282c" if dark else "#f4f5f7")
    base = QColor("#30343a" if dark else "#ffffff")
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2c3035" if dark else "#eceff1"))
    palette.setColor(QPalette.ColorRole.Button, window)
    palette.setColor(QPalette.ColorRole.ToolTipBase, base)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.ToolTipText,
        QPalette.ColorRole.BrightText,
    ):
        palette.setColor(role, text)
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#345675" if dark else "#2f6f9f"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#6db3f2" if dark else "#175a9c"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9aa1a9" if dark else "#6b7280"))
    disabled = QColor("#767d85" if dark else "#8a9199")
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return palette


def system_dark_mode() -> bool:
    application = QApplication.instance()
    return (
        application is not None
        and application.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )


class MainWindow(QMainWindow):
    def __init__(
        self, state_path: Optional[Path] = None, semantic_model_factory=None
    ) -> None:
        super().__init__()
        if state_path is None:
            data_dir = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            ))
            state_path = data_dir / "reading-state.json"
        self.state = StateStore(state_path)
        self.document: Optional[PDFDocument] = None
        self._document_password: Optional[str] = None
        self._semantic_model_factory = semantic_model_factory or LocalEmbeddingModel
        self._semantic_cache_dir = state_path.parent / "semantic-models"
        self._semantic_engine = None
        self._semantic_thread: Optional[QThread] = None
        self._semantic_worker = None
        self._semantic_generation = 0
        self._semantic_dirty = False
        self._semantic_text_hits = []
        self.search_hits = []
        self.current_search_index = -1
        self._searched_query = ""
        self._document_actions: list[QAction] = []
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.setInterval(500)
        self._state_timer.timeout.connect(self.save_reading_state)

        self.setWindowTitle("ClearView PDF")
        self.resize(1180, 820)
        self.setAcceptDrops(True)
        self._build_central_widget()
        self._build_sidebar()
        self._build_actions()
        self._build_toolbar()
        self._build_menus()
        self.statusBar().showMessage("Open a PDF to start reading")
        self.set_night_mode(system_dark_mode())
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._system_color_scheme_changed
        )
        self.sidebar_action.setChecked(bool(self.state.preference("sidebar_visible", True)))

    @property
    def current_page(self) -> int:
        return self.view.current_page

    def _build_central_widget(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.search_bar = QFrame()
        search_outer = QVBoxLayout(self.search_bar)
        search_outer.setContentsMargins(8, 5, 8, 5)
        search_layout = QHBoxLayout()
        search_outer.addLayout(search_layout)
        search_layout.addWidget(QLabel("Find"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search this document…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.next_match)
        search_layout.addWidget(self.search_edit, 1)
        previous = QToolButton()
        previous.setText("↑")
        previous.setToolTip("Previous match (Shift+F3)")
        previous.clicked.connect(self.previous_match)
        search_layout.addWidget(previous)
        following = QToolButton()
        following.setText("↓")
        following.setToolTip("Next match (F3)")
        following.clicked.connect(self.next_match)
        search_layout.addWidget(following)
        self.search_progress = QProgressBar()
        self.search_progress.setRange(0, 0)
        self.search_progress.setTextVisible(False)
        self.search_progress.setFixedWidth(110)
        self.search_progress.hide()
        search_layout.addWidget(self.search_progress)
        self.search_label = QLabel("")
        self.search_label.setMinimumWidth(80)
        search_layout.addWidget(self.search_label)
        close_search = QToolButton()
        close_search.setText("×")
        close_search.clicked.connect(self.hide_search)
        search_layout.addWidget(close_search)

        options_layout = QHBoxLayout()
        self.search_mode = QComboBox()
        self.search_mode.addItems(["Exact phrase", "Any of the words", "All of the words"])
        self.search_mode.currentIndexChanged.connect(self._search_options_changed)
        options_layout.addWidget(self.search_mode)
        self.match_case = QCheckBox("Match case")
        self.match_case.toggled.connect(self._search_options_changed)
        options_layout.addWidget(self.match_case)
        self.whole_words = QCheckBox("Whole words only")
        self.whole_words.toggled.connect(self._search_options_changed)
        options_layout.addWidget(self.whole_words)
        self.search_bookmarks = QCheckBox("Bookmarks")
        self.search_bookmarks.toggled.connect(self._search_options_changed)
        options_layout.addWidget(self.search_bookmarks)
        self.search_comments = QCheckBox("Comments")
        self.search_comments.toggled.connect(self._search_options_changed)
        options_layout.addWidget(self.search_comments)
        self.fuzzy_search = QCheckBox("Fuzzy")
        self.fuzzy_search.setToolTip(
            "Tolerate small typing errors and find related meanings locally. "
            'Examples: "talks about GQA"; "attention" near "memory"; '
            '"attention" near/20 "memory".\n'
            "First use downloads a 67 MB model; document search then runs locally."
        )
        self.fuzzy_search.toggled.connect(self._search_options_changed)
        options_layout.addWidget(self.fuzzy_search)
        options_layout.addStretch()
        search_outer.addLayout(options_layout)
        self.search_bar.hide()
        layout.addWidget(self.search_bar)

        self.document_toolbar = QToolBar("Document controls", central)
        self.document_toolbar.setObjectName("documentToolbar")
        self.document_toolbar.setMovable(False)
        self.document_toolbar.setFloatable(False)
        self.document_toolbar.setIconSize(QSize(18, 18))
        self.document_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        layout.addWidget(self.document_toolbar)
        self.document_toolbar.hide()

        self.stack = QStackedWidget()
        welcome = QWidget()
        welcome.setObjectName("welcomePage")
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.addStretch()
        title = QLabel("ClearView PDF")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: 600;")
        welcome_layout.addWidget(title)
        subtitle = QLabel("A fast, local PDF reader. Nothing else.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(subtitle)
        welcome_layout.addSpacing(20)
        self.welcome_open = QPushButton("Open a PDF")
        self.welcome_open.setFixedWidth(180)
        welcome_layout.addWidget(self.welcome_open, 0, Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Drop a file here  •  Ctrl+O to open  •  Ctrl+F to search")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addSpacing(12)
        welcome_layout.addWidget(hint)
        welcome_layout.addStretch()
        self.stack.addWidget(welcome)

        self.view = DocumentView()
        self.view.currentPageChanged.connect(self._on_page_changed)
        self.view.zoomChanged.connect(self._on_zoom_changed)
        self.view.selectionChanged.connect(self._on_selection_changed)
        self.view.linkActivated.connect(self._open_link)
        self.view.rotateRequested.connect(self._rotate_from_context)
        self.stack.addWidget(self.view)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

    def _build_sidebar(self) -> None:
        self.sidebar_dock = QDockWidget("Reader", self)
        self.sidebar_dock.setObjectName("readerSidebar")
        self.sidebar_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.sidebar_dock.setFloating(False)
        self.sidebar_dock.setMinimumWidth(250)
        self.sidebar_tabs = QTabWidget()
        self.thumbnails = ThumbnailList()
        self.thumbnails.currentRowChanged.connect(self._thumbnail_row_selected)
        self.thumbnails.itemClicked.connect(self._thumbnail_clicked)
        self.sidebar_tabs.addTab(self.thumbnails, "Pages")
        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderLabels(["Contents", "Page"])
        self.outline_tree.setColumnWidth(0, 210)
        self.outline_tree.itemClicked.connect(self._outline_clicked)
        self.sidebar_tabs.addTab(self.outline_tree, "Contents")
        self.bookmarks_list = QListWidget()
        self.bookmarks_list.itemClicked.connect(self._bookmark_clicked)
        self.bookmarks_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bookmarks_list.customContextMenuRequested.connect(self._bookmark_menu)
        self.sidebar_tabs.addTab(self.bookmarks_list, "Bookmarks")
        self.search_results = QListWidget()
        self.search_results.itemClicked.connect(self._search_result_clicked)
        self.search_results.setWordWrap(True)
        self.sidebar_tabs.addTab(self.search_results, "Search")
        self.sidebar_dock.setWidget(self.sidebar_tabs)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.sidebar_dock)

    def _action(
        self,
        text: str,
        slot,
        shortcut=None,
        checkable: bool = False,
        document: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.setIconVisibleInMenu(False)
        action.setCheckable(checkable)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                action.setShortcuts(shortcut)
            else:
                action.setShortcut(shortcut)
        action.triggered.connect(slot)
        if document:
            action.setEnabled(False)
            self._document_actions.append(action)
        return action

    def _build_actions(self) -> None:
        self.open_action = self._action("&Open…", self.open_dialog, QKeySequence.StandardKey.Open)
        self.close_action = self._action(
            "Close document", self.close_document, "Ctrl+W", document=True
        )
        self.print_action = self._action(
            "&Print…", self.print_document, QKeySequence.StandardKey.Print, document=True
        )
        self.quit_action = self._action("E&xit", self.close, "Ctrl+Q")
        self.previous_action = self._action(
            "Previous page", self.previous_page,
            [QKeySequence("PgUp"), QKeySequence("Alt+Left")], document=True
        )
        self.next_action = self._action(
            "Next page", self.next_page,
            [QKeySequence("PgDown"), QKeySequence("Alt+Right")], document=True
        )
        self.first_action = self._action("First page", lambda: self.go_to_page(0), "Ctrl+Home", document=True)
        self.last_action = self._action("Last page", self.last_page, "Ctrl+End", document=True)
        self.zoom_out_action = self._action(
            "Zoom out", self.view.zoom_out,
            [QKeySequence("Ctrl+-"), QKeySequence("Ctrl+Down")], document=True
        )
        self.zoom_in_action = self._action(
            "Zoom in", self.view.zoom_in, "Ctrl+Up", document=True
        )
        self.actual_size_action = self._action(
            "Actual size", lambda: self.view.set_zoom(1.0), "Ctrl+1", document=True
        )
        self.fit_width_action = self._action(
            "Fit to width", lambda: self.view.set_fit_mode("width"), "Ctrl+2",
            checkable=True, document=True
        )
        self.fit_height_action = self._action(
            "Fit to height", lambda: self.view.set_fit_mode("height"), "Ctrl+0",
            checkable=True, document=True
        )
        self.rotate_action = self._action(
            "Rotate 90° clockwise", lambda: self.rotate(90),
            [QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")], document=True
        )
        self.rotate_back_action = self._action(
            "Rotate 90° counterclockwise", lambda: self.rotate(-90),
            [QKeySequence("Ctrl+Shift++"), QKeySequence("Ctrl+Shift+=")], document=True
        )
        self.reset_rotation_action = self._action(
            "Reset rotation", lambda: self.view.set_rotation(0), "Ctrl+Shift+0", document=True
        )
        self.continuous_action = self._action(
            "Continuous scrolling", self.view.set_continuous, "Ctrl+Shift+C",
            checkable=True, document=True
        )
        self.continuous_action.setChecked(True)
        self.bookmark_action = self._action(
            "Bookmark this page", self.toggle_bookmark, "Ctrl+B", checkable=True, document=True
        )
        self.search_action = self._action("&Find…", self.show_search, QKeySequence.StandardKey.Find, document=True)
        self.find_next_action = self._action("Find next", self.next_match, "F3", document=True)
        self.find_previous_action = self._action("Find previous", self.previous_match, "Shift+F3", document=True)
        self.copy_action = self._action("Copy", self.copy_selection, QKeySequence.StandardKey.Copy, document=True)
        self.select_all_action = self._action("Select all page text", self.select_all_page, QKeySequence.StandardKey.SelectAll, document=True)
        self.sidebar_action = self._action("Sidebar", self._toggle_sidebar, "F9", checkable=True)
        self.fullscreen_action = self._action("Full screen", self.toggle_fullscreen, "F11")
        self.about_action = self._action("About ClearView PDF", self.show_about)
        self.welcome_open.clicked.connect(self.open_dialog)
        for action in self.findChildren(QAction):
            self.addAction(action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Reading controls")
        toolbar.setObjectName("readingToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action, standard_icon in (
            (self.close_action, QStyle.StandardPixmap.SP_DialogCloseButton),
            (self.find_next_action, QStyle.StandardPixmap.SP_ArrowDown),
            (self.find_previous_action, QStyle.StandardPixmap.SP_ArrowUp),
            (self.rotate_action, QStyle.StandardPixmap.SP_BrowserReload),
            (self.reset_rotation_action, QStyle.StandardPixmap.SP_DialogResetButton),
            (self.sidebar_action, QStyle.StandardPixmap.SP_FileDialogDetailedView),
        ):
            action.setIcon(self.style().standardIcon(standard_icon))

        rotate_back_icon = QIcon.fromTheme("object-rotate-left")
        if rotate_back_icon.isNull() and not self.rotate_action.icon().isNull():
            clockwise = self.rotate_action.icon().pixmap(24, 24)
            rotate_back_icon = QIcon(clockwise.transformed(QTransform().scale(-1, 1)))
        self.rotate_back_action.setIcon(rotate_back_icon)
        self._update_compact_icons()

        for action, label in (
            (self.open_action, "Open"),
            (self.print_action, "Print"),
            (self.first_action, "First"),
            (self.previous_action, "Prev"),
            (self.next_action, "Next"),
            (self.last_action, "Last"),
            (self.zoom_out_action, "Zoom out"),
            (self.zoom_in_action, "Zoom in"),
            (self.fit_width_action, "Fit to width"),
            (self.fit_height_action, "Fit to height"),
            (self.search_action, "Find"),
            (self.bookmark_action, "Bookmark"),
            (self.rotate_action, "Rotate CW"),
            (self.rotate_back_action, "Rotate CCW"),
            (self.reset_rotation_action, "Reset"),
            (self.sidebar_action, "Sidebar"),
        ):
            action.setIconText(label)

        self.addToolBar(toolbar)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.print_action)
        toolbar.addSeparator()
        toolbar.addAction(self.search_action)
        toolbar.addSeparator()
        toolbar.addAction(self.sidebar_action)

        compact = self.document_toolbar
        left_spacer = QWidget(compact)
        left_spacer.setObjectName("documentControlsLeftSpacer")
        left_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        compact.addWidget(left_spacer)
        compact.addAction(self.first_action)
        compact.addAction(self.previous_action)
        self.page_edit = QLineEdit("—")
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.setFixedWidth(44)
        self.page_edit.setValidator(QIntValidator(1, 1, self))
        self.page_edit.returnPressed.connect(self._page_entered)
        compact.addWidget(self.page_edit)
        self.page_total = QLabel("/ —")
        compact.addWidget(self.page_total)
        compact.addAction(self.next_action)
        compact.addAction(self.last_action)
        compact.addSeparator()
        compact.addAction(self.zoom_out_action)
        self.zoom_edit = QLineEdit("100%")
        self.zoom_edit.setObjectName("zoomEdit")
        self.zoom_edit.setAccessibleName("Zoom percentage")
        self.zoom_edit.setToolTip("Zoom percentage (20–500%; press Enter)")
        self.zoom_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_edit.setFixedWidth(56)
        self.zoom_edit.returnPressed.connect(self._zoom_entered)
        compact.addWidget(self.zoom_edit)
        compact.addAction(self.zoom_in_action)
        compact.addSeparator()
        compact.addAction(self.fit_width_action)
        compact.addAction(self.fit_height_action)
        right_spacer = QWidget(compact)
        right_spacer.setObjectName("documentControlsRightSpacer")
        right_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        compact.addWidget(right_spacer)

    def _compact_symbol_icon(self, symbol: str) -> QIcon:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(self.palette().color(QPalette.ColorRole.ButtonText))
        font = painter.font()
        font.setPixelSize(17 if len(symbol) > 1 else 19)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, symbol)
        painter.end()
        return QIcon(pixmap)

    def _tool_icon(self, kind: str) -> QIcon:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().color(QPalette.ColorRole.ButtonText), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "open":
            path = QPainterPath()
            path.moveTo(3, 18)
            path.lineTo(3, 6)
            path.lineTo(9, 6)
            path.lineTo(11, 8)
            path.lineTo(20, 8)
            path.lineTo(20, 18)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(QLineF(3, 11, 20, 11))
        elif kind == "print":
            painter.drawRect(QRectF(7, 3, 10, 6))
            painter.drawRoundedRect(QRectF(3, 9, 18, 9), 2, 2)
            painter.drawRect(QRectF(7, 14, 10, 7))
            painter.drawLine(QLineF(8, 18, 16, 18))
        elif kind == "search":
            painter.drawEllipse(QRectF(3, 3, 12, 12))
            painter.drawLine(QLineF(13, 13, 21, 21))
        else:
            raise ValueError(f"Unknown toolbar icon: {kind}")
        painter.end()
        return QIcon(pixmap)

    def _update_compact_icons(self) -> None:
        for action, symbol in (
            (self.first_action, "<<"),
            (self.previous_action, "<"),
            (self.next_action, ">"),
            (self.last_action, ">>"),
            (self.zoom_out_action, "−"),
            (self.zoom_in_action, "+"),
            (self.fit_width_action, "⟷"),
            (self.fit_height_action, "↕"),
        ):
            action.setIcon(self._compact_symbol_icon(symbol))
        for action, kind in (
            (self.open_action, "open"),
            (self.print_action, "print"),
            (self.search_action, "search"),
        ):
            action.setIcon(self._tool_icon(kind))

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.open_action)
        self.recent_menu = QMenu("Open recent", self)
        self.recent_menu.menuAction().setIconVisibleInMenu(False)
        self.recent_menu.aboutToShow.connect(self._refresh_recent_menu)
        file_menu.addMenu(self.recent_menu)
        file_menu.addAction(self.close_action)
        file_menu.addSeparator()
        file_menu.addAction(self.print_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.search_action)
        edit_menu.addAction(self.find_next_action)
        edit_menu.addAction(self.find_previous_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.select_all_action)

        view_menu = self.menuBar().addMenu("&View")
        for action in (
            self.zoom_in_action, self.zoom_out_action, self.actual_size_action,
            self.fit_width_action, self.fit_height_action, self.rotate_action,
            self.rotate_back_action, self.reset_rotation_action, self.continuous_action,
            self.sidebar_action, self.fullscreen_action,
        ):
            view_menu.addAction(action)

        go_menu = self.menuBar().addMenu("&Go")
        for action in (self.previous_action, self.next_action, self.first_action, self.last_action, self.bookmark_action):
            go_menu.addAction(action)
        self.menuBar().addMenu("&Help").addAction(self.about_action)

    def open_dialog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF documents (*.pdf)")
        if filename:
            self.open_path(Path(filename))

    def open_path(self, path: Path) -> bool:
        path = Path(path).expanduser().resolve()
        password = None
        while True:
            try:
                document = PDFDocument.open(path, password=password)
                break
            except PasswordRequired:
                password, accepted = QInputDialog.getText(
                    self, "Password protected PDF", "Password:", QLineEdit.EchoMode.Password
                )
                if not accepted:
                    return False
            except InvalidPassword:
                QMessageBox.warning(self, "Wrong password", "That password did not unlock the PDF.")
                password = None
            except DocumentError as exc:
                QMessageBox.critical(self, "Could not open PDF", str(exc))
                return False

        self.save_reading_state()
        old_document = self.document
        self.document = document
        self._document_password = password
        saved = self.state.document_state(path)
        self.view.zoom = saved.zoom
        self.view.fit_mode = saved.fit_mode
        self.view.rotation = saved.rotation
        self.view.set_document(document)
        if old_document is not None:
            old_document.close()
        self.stack.setCurrentWidget(self.view)
        self.document_toolbar.show()
        self.setWindowTitle(f"{path.name} — ClearView PDF")
        self.page_total.setText(f"/ {document.page_count}")
        self.page_edit.setValidator(QIntValidator(1, document.page_count, self))
        self.thumbnails.set_document(document)
        self._populate_outline()
        self.refresh_bookmarks()
        self.hide_search()
        self.state.add_recent(path)
        for action in self._document_actions:
            action.setEnabled(True)
        if saved.fit_mode == "custom":
            self.view.set_zoom(saved.zoom, "custom")
        else:
            QTimer.singleShot(0, self.view.apply_fit)
        self.go_to_page(min(saved.page_index, document.page_count - 1))
        self.statusBar().showMessage(f"{document.page_count} pages  •  {path}")
        return True

    def close_document(self) -> None:
        self.save_reading_state()
        self.hide_search()
        self.view.shutdown()
        self.thumbnails.shutdown()
        self.outline_tree.clear()
        self.bookmarks_list.clear()
        if self.document is not None:
            self.document.close()
        self.document = None
        self._document_password = None
        self.stack.setCurrentIndex(0)
        self.document_toolbar.hide()
        self.setWindowTitle("ClearView PDF")
        self.page_total.setText("/ —")
        self.page_edit.setText("—")
        for action in self._document_actions:
            action.setEnabled(False)

    def save_reading_state(self) -> None:
        if self.document is None:
            return
        self.state.remember_document(
            self.document.path,
            DocumentState(
                page_index=self.view.current_page,
                zoom=self.view.zoom,
                fit_mode=self.view.fit_mode,
                rotation=self.view.rotation,
            ),
        )

    def _on_page_changed(self, page_index: int) -> None:
        self.page_edit.setText(str(page_index + 1))
        self.thumbnails.set_current_page(page_index)
        self._update_bookmark_action()
        self._state_timer.start()

    def _on_zoom_changed(self, zoom: float) -> None:
        self.zoom_edit.setText(f"{round(zoom * 100)}%")
        self.fit_width_action.setChecked(self.view.fit_mode == "width")
        self.fit_height_action.setChecked(self.view.fit_mode == "height")
        self._state_timer.start()

    def _page_entered(self) -> None:
        try:
            page_number = int(self.page_edit.text())
        except ValueError:
            self.page_edit.setText(str(self.current_page + 1))
            return
        self.go_to_page(page_number - 1)

    def _zoom_entered(self) -> None:
        text = self.zoom_edit.text().strip()
        if text.endswith("%"):
            text = text[:-1].strip()
        try:
            percent = int(text)
        except ValueError:
            return
        percent = max(20, min(500, percent))
        self.view.set_zoom(percent / 100)

    def go_to_page(self, page_index: int) -> None:
        if self.document is None:
            return
        self.view.go_to_page(page_index)
        self._on_page_changed(self.view.current_page)

    def previous_page(self) -> None:
        self.go_to_page(self.current_page - 1)

    def next_page(self) -> None:
        self.go_to_page(self.current_page + 1)

    def last_page(self) -> None:
        if self.document is not None:
            self.go_to_page(self.document.page_count - 1)

    def rotate(self, degrees: int) -> None:
        self.view.set_rotation(self.view.rotation + degrees)
        self._state_timer.start()

    def _rotate_from_context(self, degrees: int) -> None:
        if degrees == 0:
            self.view.set_rotation(0)
        else:
            self.rotate(degrees)
        self._state_timer.start()

    def _system_color_scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        if scheme != Qt.ColorScheme.Unknown:
            self.set_night_mode(scheme == Qt.ColorScheme.Dark)

    def set_night_mode(self, enabled: bool) -> None:
        self.view.set_dark(enabled)
        palette = reading_palette(enabled)
        application = QApplication.instance()
        if application is not None:
            application.setPalette(palette)
        self.setPalette(palette)
        self.setStyleSheet(DARK_STYLE if enabled else LIGHT_STYLE)
        self._update_compact_icons()

    def _toggle_sidebar(self, visible: bool) -> None:
        self.sidebar_dock.setVisible(visible)
        self.state.set_preference("sidebar_visible", visible)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def show_search(self) -> None:
        self.search_bar.show()
        self.search_edit.setFocus()
        self.search_edit.selectAll()
        if self.search_edit.text():
            self.start_search()

    def hide_search(self) -> None:
        self._semantic_generation += 1
        self._semantic_dirty = False
        self.search_progress.hide()
        self.search_bar.hide()
        self.search_edit.clear()
        self.search_hits = []
        self.current_search_index = -1
        self._searched_query = ""
        self.search_label.clear()
        self.search_results.clear()
        self.view.set_search_hits([])

    def _search_options_changed(self) -> None:
        if self.document is not None and self.search_edit.text().strip():
            self.start_search()

    def _search_options(self) -> SearchOptions:
        return SearchOptions(
            mode=("phrase", "any", "all")[self.search_mode.currentIndex()],
            match_case=self.match_case.isChecked(),
            whole_words=self.whole_words.isChecked(),
            include_bookmarks=self.search_bookmarks.isChecked(),
            include_comments=self.search_comments.isChecked(),
            fuzzy=self.fuzzy_search.isChecked(),
        )

    def _populate_search_results(self) -> None:
        self.search_results.clear()
        for index, hit in enumerate(self.search_hits):
            source = "" if hit.source == "text" else f"  [{hit.source}]"
            item = QListWidgetItem(
                f"{index + 1}. Page {hit.page_index + 1}{source}\n{hit.snippet}"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(hit.snippet)
            self.search_results.addItem(item)

    def _search_result_clicked(self, item: QListWidgetItem) -> None:
        self.current_search_index = item.data(Qt.ItemDataRole.UserRole)
        self._show_current_match()

    def start_search(self) -> None:
        if self.document is None:
            return
        query = self.search_edit.text().strip()
        self._searched_query = query
        if self.fuzzy_search.isChecked():
            text_hits = self.document.search(query, self._search_options())
            self._start_semantic_search(query, text_hits)
            return
        self._semantic_generation += 1
        self._semantic_dirty = False
        self.search_progress.hide()
        self.search_hits = self.document.search(query, self._search_options())
        self._accept_search_hits(self.search_hits)

    def _accept_search_hits(self, hits) -> None:
        self.search_hits = hits
        self.search_progress.hide()
        self._populate_search_results()
        self.sidebar_tabs.setCurrentWidget(self.search_results)
        self.current_search_index = 0 if self.search_hits else -1
        if self.search_hits:
            self._show_current_match()
        else:
            self.view.set_search_hits([])
            self.search_label.setText("No matches" if self._searched_query else "")

    def _start_semantic_search(self, query: str, text_hits=None) -> None:
        self._semantic_text_hits = list(text_hits or [])
        self._semantic_generation += 1
        generation = self._semantic_generation
        self.search_hits = []
        self.current_search_index = -1
        self.search_results.clear()
        self.view.set_search_hits([])
        self.search_progress.show()
        self.search_label.setToolTip("")
        if self._semantic_thread is not None and self._semantic_thread.isRunning():
            self._semantic_dirty = True
            self.search_label.setText("Updating…")
            return
        self._semantic_dirty = False
        self.search_label.setText("Indexing…")
        self.statusBar().showMessage(
            "Semantic search: loading the local model and indexing passages "
            "(first use downloads 67 MB)…"
        )
        thread = QThread(self)
        worker = SemanticSearchWorker(
            self.document.path,
            self._document_password,
            query,
            self._semantic_model_factory,
            self._semantic_cache_dir,
            self._semantic_engine,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda hits, engine: self._semantic_succeeded(generation, hits, engine)
        )
        worker.failed.connect(lambda message: self._semantic_failed(generation, message))
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._semantic_thread_done(thread))
        thread.finished.connect(thread.deleteLater)
        self._semantic_thread = thread
        self._semantic_worker = worker
        thread.start()

    def _semantic_succeeded(self, generation: int, hits, engine) -> None:
        if engine is not None:
            self._semantic_engine = engine
        if generation != self._semantic_generation:
            return
        hits = merge_search_hits(self._semantic_text_hits, hits)
        self._accept_search_hits(hits)
        self.statusBar().showMessage(f"{len(hits)} search results", 4000)

    def _semantic_failed(self, generation: int, message: str) -> None:
        if generation != self._semantic_generation:
            return
        self.search_hits = []
        self.current_search_index = -1
        self.search_results.clear()
        self.view.set_search_hits([])
        self.search_progress.hide()
        self.search_label.setText("Semantic error")
        self.search_label.setToolTip(message)
        self.statusBar().showMessage(f"Semantic search failed: {message}", 10000)

    def _semantic_thread_done(self, thread: QThread) -> None:
        if self._semantic_thread is thread:
            self._semantic_thread = None
            self._semantic_worker = None
        if (
            self._semantic_dirty
            and self.document is not None
            and self.search_bar.isVisible()
            and self.fuzzy_search.isChecked()
        ):
            self._semantic_dirty = False
            self.start_search()

    def next_match(self) -> None:
        if not self.search_bar.isVisible():
            self.show_search()
        if self.search_edit.text().strip() != self._searched_query:
            self.start_search()
            return
        if self.search_edit.text().strip() and not self.search_hits:
            self.start_search()
            return
        if self.search_hits:
            self.current_search_index = (self.current_search_index + 1) % len(self.search_hits)
            self._show_current_match()

    def previous_match(self) -> None:
        if self.search_edit.text().strip() != self._searched_query:
            self.start_search()
            if self.search_hits:
                self.current_search_index = len(self.search_hits) - 1
                self._show_current_match()
            return
        if self.search_edit.text().strip() and not self.search_hits:
            self.start_search()
            if self.search_hits:
                self.current_search_index = len(self.search_hits) - 1
                self._show_current_match()
            return
        if self.search_hits:
            self.current_search_index = (self.current_search_index - 1) % len(self.search_hits)
            self._show_current_match()

    def _show_current_match(self) -> None:
        hit = self.search_hits[self.current_search_index]
        self.view.set_search_hits(self.search_hits, self.current_search_index)
        self.search_label.setText(f"{self.current_search_index + 1} / {len(self.search_hits)}")
        self.search_results.setCurrentRow(self.current_search_index)
        if hit.source == "bookmark":
            self.go_to_page(hit.page_index)
        else:
            self.view.center_on_rect(hit.page_index, hit.rect)

    def copy_selection(self) -> None:
        if self.view.selected_text:
            QGuiApplication.clipboard().setText(self.view.selected_text)
            self.statusBar().showMessage("Selection copied", 2000)

    def select_all_page(self) -> None:
        if self.view.pages:
            page = self.view.pages[self.current_page]
            page.render()
            page.select_all()

    def _on_selection_changed(self, text: str) -> None:
        if text:
            self.statusBar().showMessage(f"{len(text)} characters selected  •  Ctrl+C to copy")

    def toggle_bookmark(self) -> None:
        if self.document is None:
            return
        existing = {
            bookmark.page_index for bookmark in self.state.bookmarks(self.document.path)
        }
        if self.current_page in existing:
            self.state.remove_bookmark(self.document.path, self.current_page)
        else:
            first_line = next(
                (line.strip() for line in self.document.page_text(self.current_page).splitlines() if line.strip()),
                "",
            )
            title = f"Page {self.current_page + 1}"
            if first_line:
                title += f" — {first_line[:60]}"
            self.state.add_bookmark(self.document.path, self.current_page, title)
        self.refresh_bookmarks()

    def _update_bookmark_action(self) -> None:
        if self.document is None:
            self.bookmark_action.setChecked(False)
            return
        pages = {item.page_index for item in self.state.bookmarks(self.document.path)}
        self.bookmark_action.setChecked(self.current_page in pages)

    def refresh_bookmarks(self) -> None:
        self.bookmarks_list.clear()
        if self.document is None:
            self._update_bookmark_action()
            return
        bookmarks = self.state.bookmarks(self.document.path)
        if not bookmarks:
            prompt = QListWidgetItem("No bookmarks — click to add this page")
            prompt.setToolTip("Bookmark the current page (Ctrl+B)")
            self.bookmarks_list.addItem(prompt)
        for bookmark in bookmarks:
            item = QListWidgetItem(f"{bookmark.page_index + 1}   {bookmark.title}")
            item.setData(Qt.ItemDataRole.UserRole, bookmark.page_index)
            self.bookmarks_list.addItem(item)
        self._update_bookmark_action()

    def _bookmark_clicked(self, item: QListWidgetItem) -> None:
        page_index = item.data(Qt.ItemDataRole.UserRole)
        if page_index is None:
            self.toggle_bookmark()
            return
        self.go_to_page(page_index)

    def _bookmark_menu(self, point) -> None:
        item = self.bookmarks_list.itemAt(point)
        if (
            item is None
            or self.document is None
            or item.data(Qt.ItemDataRole.UserRole) is None
        ):
            return
        menu = QMenu(self)
        menu.addAction("Go to bookmark", lambda: self._bookmark_clicked(item))
        menu.addAction(
            "Remove bookmark",
            lambda: (
                self.state.remove_bookmark(
                    self.document.path, item.data(Qt.ItemDataRole.UserRole)
                ),
                self.refresh_bookmarks(),
            ),
        )
        menu.exec(self.bookmarks_list.mapToGlobal(point))

    def _populate_outline(self) -> None:
        self.outline_tree.clear()
        if self.document is None:
            return
        root = self.outline_tree.invisibleRootItem()
        parents = {0: root}
        for entry in self.document.outline():
            item = QTreeWidgetItem([
                entry.title,
                str(entry.page_index + 1) if entry.page_index is not None else "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.page_index)
            parent = parents.get(entry.level - 1, root)
            parent.addChild(item)
            parents[entry.level] = item
            for level in list(parents):
                if level > entry.level:
                    del parents[level]
        self.outline_tree.expandAll()

    def _outline_clicked(self, item: QTreeWidgetItem) -> None:
        page_index = item.data(0, Qt.ItemDataRole.UserRole)
        if page_index is not None:
            self.go_to_page(page_index)

    def _thumbnail_row_selected(self, row: int) -> None:
        # Mouse selection is followed by itemClicked; do not render the page twice.
        if row >= 0 and QApplication.mouseButtons() == Qt.MouseButton.NoButton:
            self._thumbnail_clicked(self.thumbnails.item(row))

    def _thumbnail_clicked(self, item: QListWidgetItem) -> None:
        self.go_to_page(item.data(Qt.ItemDataRole.UserRole))

    def _open_link(self, link: dict) -> None:
        page_index = link.get("page", -1)
        if link.get("kind") == pymupdf.LINK_GOTO and page_index >= 0:
            self.go_to_page(page_index)
            return
        uri = link.get("uri", "")
        if uri.lower().startswith(("https://", "http://", "mailto:")):
            QDesktopServices.openUrl(QUrl(uri))
        elif uri:
            self.statusBar().showMessage("Blocked unsupported link type", 4000)

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        recents = self.state.recent_files()
        if not recents:
            empty = self.recent_menu.addAction("No recent documents")
            empty.setEnabled(False)
            return
        for filename in recents:
            path = Path(filename)
            action = self.recent_menu.addAction(path.name)
            action.setToolTip(filename)
            action.triggered.connect(lambda checked=False, p=path: self.open_path(p))

    def print_document(self) -> None:
        if self.document is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self.document.path.name)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        first, last = 0, self.document.page_count - 1
        if dialog.printRange() == QPrintDialog.PrintRange.PageRange:
            first = max(0, dialog.fromPage() - 1)
            last = min(last, dialog.toPage() - 1)
        from PySide6.QtGui import QPainter

        painter = QPainter(printer)
        for page_index in range(first, last + 1):
            if page_index > first:
                printer.newPage()
            pixmap = self.document.render_page(
                page_index, zoom=min(3.0, printer.resolution() / 72), rotation=self.view.rotation
            )
            image = qimage_from_pixmap(pixmap)
            target = painter.viewport()
            scaled = image.scaled(
                target.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = target.x() + (target.width() - scaled.width()) // 2
            y = target.y() + (target.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)
        painter.end()
        self.statusBar().showMessage("Printing finished", 4000)

    def show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("About ClearView PDF")
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(
            f"ClearView PDF {__version__}\n\n"
            "A local, reading-first PDF viewer.\n\n"
            "No accounts, ads, telemetry, cloud sync, or background services.\n\n"
            "<@839649633130643466>"
        )
        box.exec()
        box.deleteLater()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if any(url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf") for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                self.open_path(Path(url.toLocalFile()))
                event.acceptProposedAction()
                return

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
            elif self.search_bar.isVisible():
                self.hide_search()
            else:
                self.view.clear_selection()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and self.document is not None:
            direction = -1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            scrollbar = self.view.verticalScrollBar()
            scrollbar.setValue(scrollbar.value() + direction * round(self.view.viewport().height() * 0.9))
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._state_timer.stop()
        self.save_reading_state()
        self.state.set_preference("sidebar_visible", self.sidebar_action.isChecked())
        self._semantic_generation += 1
        self._semantic_dirty = False
        if self._semantic_thread is not None and self._semantic_thread.isRunning():
            self._semantic_thread.requestInterruption()
            self._semantic_thread.wait()
        self._semantic_engine = None
        self.view.shutdown()
        self.thumbnails.shutdown()
        if self.document is not None:
            self.document.close()
            self.document = None
        self._document_password = None
        event.accept()
