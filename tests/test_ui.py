import os
import time
from pathlib import Path

import numpy as np
import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QToolBar

from clearview_pdf.state import StateStore
from clearview_pdf.ui import MainWindow


def make_pdf(path: Path) -> Path:
    document = pymupdf.open()
    for number in range(1, 4):
        page = document.new_page(width=400, height=600)
        page.insert_text((48, 72), f"Chapter {number}", fontsize=16)
        page.insert_text((48, 110), "Searchable text for the reader.", fontsize=11)
    document.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])
    document.save(path)
    document.close()
    return path


def test_window_opens_navigates_renders_and_saves_position(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()

    window.open_path(path)
    assert window.document.page_count == 3
    assert window.page_total.text() == "/ 3"
    assert window.outline_tree.topLevelItemCount() == 2

    window.go_to_page(1)
    window.view.render_visible()
    assert window.current_page == 1
    assert window.page_edit.text() == "2"
    assert not window.view.pages[1].image.isNull()

    window.close()
    assert StateStore(tmp_path / "state.json").document_state(path).page_index == 1


def test_search_navigation_and_bookmark_shortcut(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.open_path(path)

    window.search_edit.setText("Searchable")
    window.start_search()
    assert len(window.search_hits) == 3
    assert window.search_label.text() == "1 / 3"
    window.next_match()
    assert window.current_search_index == 1
    assert window.current_page == 1

    window.toggle_bookmark()
    assert StateStore(tmp_path / "state.json").bookmarks(path)[0].page_index == 1
    assert window.bookmark_action.isChecked()


def test_changing_a_search_query_does_not_navigate_stale_results(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.show_search()
    window.search_edit.setText("Searchable")
    window.start_search()
    assert len(window.search_hits) == 3

    window.search_edit.setText("Chapter 2")
    window.next_match()

    assert len(window.search_hits) == 1
    assert window.current_search_index == 0
    assert window.current_page == 1


def test_middle_mouse_drag_keeps_auto_scrolling_without_cursor_movement(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.view.set_zoom(1.0)
    scrollbar = window.view.verticalScrollBar()
    scrollbar.setValue(0)
    page = window.view.pages[0]
    start = QPoint(100, 250)

    qtbot.mousePress(page, Qt.MouseButton.MiddleButton, pos=start)
    qtbot.mouseMove(page, start + QPoint(0, 80))
    try:
        qtbot.waitUntil(lambda: scrollbar.value() > 0, timeout=1000)
        initial = scrollbar.value()
        qtbot.wait(150)
        assert scrollbar.value() > initial
    finally:
        qtbot.mouseRelease(page, Qt.MouseButton.MiddleButton, pos=start + QPoint(0, 80))


def test_middle_mouse_auto_scroll_pauses_near_click_origin(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.view.set_zoom(1.0)
    scrollbar = window.view.verticalScrollBar()
    scrollbar.setValue(0)
    page = window.view.pages[0]
    start = QPoint(100, 250)
    origin = page.mapToGlobal(start)

    qtbot.mousePress(page, Qt.MouseButton.MiddleButton, pos=start)
    qtbot.mouseMove(page, start + QPoint(0, 80))
    qtbot.waitUntil(lambda: scrollbar.value() > 30, timeout=1000)
    near_origin = page.mapFromGlobal(origin + QPoint(0, 3))
    qtbot.mouseMove(page, near_origin)
    paused = scrollbar.value()
    qtbot.wait(150)
    assert scrollbar.value() == paused
    qtbot.mouseRelease(page, Qt.MouseButton.MiddleButton, pos=near_origin)


def test_middle_mouse_auto_scroll_stops_on_release(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.view.set_zoom(1.0)
    scrollbar = window.view.verticalScrollBar()
    scrollbar.setValue(0)
    page = window.view.pages[0]
    start = QPoint(100, 250)

    qtbot.mousePress(page, Qt.MouseButton.MiddleButton, pos=start)
    qtbot.mouseMove(page, start + QPoint(0, 80))
    qtbot.waitUntil(lambda: scrollbar.value() > 0, timeout=1000)
    qtbot.mouseRelease(page, Qt.MouseButton.MiddleButton, pos=start + QPoint(0, 80))
    stopped = scrollbar.value()
    qtbot.wait(150)
    assert scrollbar.value() == stopped


def test_middle_mouse_auto_scroll_maximum_speed_is_doubled(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    scrollbar = window.view.verticalScrollBar()
    scrollbar.setValue(100)

    window.view._pan_delta = QPoint(0, 1000)
    window.view._auto_scroll()
    assert scrollbar.value() == 196

    scrollbar.setValue(100)
    window.view._pan_delta = QPoint(0, 20)
    window.view._auto_scroll()
    assert scrollbar.value() == 103


def test_closing_document_stops_middle_mouse_auto_scroll(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.view.set_zoom(1.0)
    window.view.verticalScrollBar().setValue(0)
    page = window.view.pages[0]
    start = QPoint(100, 250)

    qtbot.mousePress(page, Qt.MouseButton.MiddleButton, pos=start)
    qtbot.mouseMove(page, start + QPoint(0, 80))
    qtbot.waitUntil(lambda: window.view.verticalScrollBar().value() > 0, timeout=1000)
    assert window.view._auto_scroll_timer.isActive()

    window.close_document()
    qtbot.mouseRelease(window, Qt.MouseButton.MiddleButton)

    assert not window.view._auto_scroll_timer.isActive()


def test_opening_another_document_stops_middle_mouse_auto_scroll(qtbot, tmp_path):
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(first)
    window.view.set_zoom(1.0)
    window.view.verticalScrollBar().setValue(0)
    page = window.view.pages[0]
    start = QPoint(100, 250)

    qtbot.mousePress(page, Qt.MouseButton.MiddleButton, pos=start)
    qtbot.mouseMove(page, start + QPoint(0, 80))
    qtbot.waitUntil(lambda: window.view.verticalScrollBar().value() > 0, timeout=1000)
    assert window.view._auto_scroll_timer.isActive()

    assert window.open_path(second)
    qtbot.mouseRelease(window, Qt.MouseButton.MiddleButton)

    assert not window.view._auto_scroll_timer.isActive()


def test_clicking_web_link_uses_default_os_browser(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "web-link.pdf"
    document = pymupdf.open()
    page = document.new_page(width=400, height=600)
    url = "https://example.com/research?q=clearview"
    link_rect = pymupdf.Rect(48, 72, 260, 96)
    page.insert_text((50, 90), "Example research link", fontsize=12)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": link_rect, "uri": url})
    document.save(path)
    document.close()
    opened = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda target: opened.append(target.toString()) or True,
    )
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    page_widget = window.view.pages[0]
    page_widget.render(force=True)
    point = page_widget._widget_rect(link_rect).center().toPoint()

    qtbot.mouseClick(page_widget, Qt.MouseButton.LeftButton, pos=point)

    assert opened == [url]


@pytest.mark.parametrize(
    ("visible", "expected"),
    [
        ("https://example.com/plain", "https://example.com/plain"),
        ("www.example.com", "https://www.example.com"),
    ],
)
def test_clicking_printed_web_address_uses_default_os_browser(
    qtbot, tmp_path, monkeypatch, visible, expected
):
    path = tmp_path / "printed-link.pdf"
    document = pymupdf.open()
    page = document.new_page(width=400, height=600)
    page.insert_text((48, 90), visible, fontsize=12)
    document.save(path)
    document.close()
    opened = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda target: opened.append(target.toString()) or True,
    )
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    page_widget = window.view.pages[0]
    page_widget.render(force=True)
    word = next(word for word in page_widget.words if visible in word.text)
    point = page_widget._widget_rect(word.rect).center().toPoint()

    qtbot.mouseClick(page_widget, Qt.MouseButton.LeftButton, pos=point)

    assert opened == [expected]


def test_rotation_shortcut_and_context_signal_are_reversible(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.open_path(path)

    assert window.rotate_action.shortcut().toString() == "Ctrl++"
    window.rotate_action.trigger()
    assert window.view.rotation == 90
    window.rotate_back_action.trigger()
    assert window.view.rotation == 0
    window.view.rotateRequested.emit(90)
    assert window.view.rotation == 90
    window.view.rotateRequested.emit(0)
    assert window.view.rotation == 0


def test_sidebar_tabs_navigate_through_real_mouse_clicks(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)

    def assert_page_occupies_viewport(page_index):
        QApplication.processEvents()
        page = window.view.pages[page_index]
        top = window.view.verticalScrollBar().value()
        bottom = top + window.view.viewport().height()
        visible = max(0, min(bottom, page.y() + page.height()) - max(top, page.y()))
        assert visible > window.view.viewport().height() * 0.6, (
            f"page={page_index} top={top} bottom={bottom} "
            f"page_y={page.y()} page_bottom={page.y() + page.height()} "
            f"maximum={window.view.verticalScrollBar().maximum()} zoom={window.view.zoom}"
        )

    tabs = window.sidebar_tabs
    tabs.setCurrentWidget(window.thumbnails)
    item = window.thumbnails.item(1)
    rect = window.thumbnails.visualItemRect(item)
    qtbot.mouseClick(
        window.thumbnails.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )
    assert window.current_page == 1
    assert_page_occupies_viewport(1)

    window.go_to_page(0)
    tabs.setCurrentWidget(window.outline_tree)
    outline_item = window.outline_tree.topLevelItem(1)
    rect = window.outline_tree.visualItemRect(outline_item)
    qtbot.mouseClick(
        window.outline_tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )
    assert window.current_page == 1
    assert_page_occupies_viewport(1)

    window.toggle_bookmark()
    window.go_to_page(0)
    tabs.setCurrentWidget(window.bookmarks_list)
    bookmark = window.bookmarks_list.item(0)
    rect = window.bookmarks_list.visualItemRect(bookmark)
    qtbot.mouseClick(
        window.bookmarks_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )
    assert window.current_page == 1
    assert_page_occupies_viewport(1)


def test_thumbnail_selection_itself_navigates_to_the_page(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)

    window.thumbnails.setCurrentRow(1)

    assert window.current_page == 1
    page = window.view.pages[1]
    assert window.view.verticalScrollBar().value() == max(0, page.y() - 16)


def test_entire_thumbnail_cell_is_clickable_before_lazy_icon_load(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)

    item = window.thumbnails.item(1)
    rect = window.thumbnails.visualItemRect(item)
    assert item.sizeHint().width() >= window.thumbnails.iconSize().width()
    assert item.sizeHint().height() >= window.thumbnails.iconSize().height()
    assert rect.width() >= window.thumbnails.iconSize().width()
    assert rect.height() >= window.thumbnails.iconSize().height()

    qtbot.mouseClick(
        window.thumbnails.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.topLeft() + QPoint(8, rect.height() // 2),
    )

    assert window.current_page == 1


def test_document_scrolling_does_not_snap_back_to_the_thumbnail(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.view.set_zoom(1.0)
    target_scroll = window.view.pages[1].y() + 120

    window.view.verticalScrollBar().setValue(target_scroll)
    QApplication.processEvents()

    assert window.current_page == 1
    assert window.view.verticalScrollBar().value() == target_scroll


def test_clicking_the_selected_thumbnail_recenters_its_page(qtbot, tmp_path):
    from PySide6.QtTest import QTest

    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.view.set_zoom(1.0)
    window.go_to_page(1)
    page = window.view.pages[1]
    window.view.verticalScrollBar().setValue(page.y() + 50)
    item = window.thumbnails.item(1)
    assert window.current_page == 1
    assert window.view.verticalScrollBar().value() != max(0, page.y() - 16)

    QTest.mouseClick(
        window.thumbnails.viewport(),
        Qt.MouseButton.LeftButton,
        pos=window.thumbnails.visualItemRect(item).center(),
    )

    assert window.current_page == 1
    assert window.view.verticalScrollBar().value() == max(0, page.y() - 16)


def test_empty_bookmarks_tab_can_bookmark_the_current_page(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.sidebar_tabs.setCurrentWidget(window.bookmarks_list)

    assert window.bookmarks_list.count() == 1
    prompt = window.bookmarks_list.item(0)
    assert "click to add this page" in prompt.text().lower()
    rect = window.bookmarks_list.visualItemRect(prompt)
    qtbot.mouseClick(
        window.bookmarks_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )

    bookmarks = StateStore(tmp_path / "state.json").bookmarks(path)
    assert len(bookmarks) == 1 and bookmarks[0].page_index == 0
    assert window.bookmarks_list.item(0).data(Qt.ItemDataRole.UserRole) == 0


def test_primary_menu_and_toolbar_controls_are_visible(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)

    assert window.menuBar().isVisible()
    assert [action.text() for action in window.menuBar().actions()] == [
        "&File", "&Edit", "&View", "&Go", "&Help"
    ]
    toolbars = window.findChildren(QToolBar)
    for action in (
        window.open_action,
        window.print_action,
        window.search_action,
        window.sidebar_action,
    ):
        buttons = [toolbar.widgetForAction(action) for toolbar in toolbars]
        assert any(button is not None and button.isVisible() for button in buttons), action.text()
    menus = {action.text(): action.menu() for action in window.menuBar().actions()}
    for action in (
        window.rotate_action,
        window.rotate_back_action,
        window.reset_rotation_action,
    ):
        assert action in menus["&View"].actions()
    assert window.bookmark_action in menus["&Go"].actions()


class ConstantModel:
    created = 0
    embed_calls = 0

    def __init__(self, cache_dir):
        type(self).created += 1
        self.cache_dir = cache_dir

    def embed(self, texts):
        type(self).embed_calls += 1
        time.sleep(0.08)
        return np.ones((len(texts), 2), dtype=np.float32)

    def query_embed(self, texts):
        return np.ones((len(texts), 2), dtype=np.float32)


def test_fuzzy_search_is_available_from_the_find_bar(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(
        state_path=tmp_path / "state.json", semantic_model_factory=ConstantModel
    )
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.show_search()
    window.fuzzy_search.setChecked(True)
    window.search_edit.setText("Serchable")
    window.start_search()
    qtbot.waitUntil(
        lambda: bool(window.search_hits) and not window.search_progress.isVisible(),
        timeout=5000,
    )
    assert len(window.search_hits) == 3


def test_fuzzy_and_semantic_search_combine_without_duplicate_passages(qtbot, tmp_path):
    path = tmp_path / "hybrid.pdf"
    document = pymupdf.open()
    for text in (
        "Searchable introduction with enough words for semantic indexing",
        "Transformer inference uses grouped query attention with enough words for semantic indexing",
    ):
        page = document.new_page(width=500, height=700)
        page.insert_textbox(pymupdf.Rect(40, 40, 460, 660), text, fontsize=12)
    document.save(path)
    document.close()

    window = MainWindow(
        state_path=tmp_path / "state.json", semantic_model_factory=ConstantModel
    )
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.show_search()
    assert not hasattr(window, "semantic_search")
    window.fuzzy_search.setChecked(True)
    window.search_edit.setText("Serchable")

    window.start_search()
    qtbot.waitUntil(
        lambda: bool(window.search_hits) and not window.search_progress.isVisible(),
        timeout=5000,
    )

    assert [(hit.page_index, hit.source) for hit in window.search_hits] == [
        (0, "text"),
        (1, "semantic"),
    ]


def test_semantic_search_runs_in_background_and_returns_clickable_results(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(
        state_path=tmp_path / "state.json", semantic_model_factory=ConstantModel
    )
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.show_search()
    window.fuzzy_search.setChecked(True)
    window.search_edit.setText("talks about chapters")

    window.start_search()
    assert window.search_progress.isVisible()
    qtbot.waitUntil(lambda: bool(window.search_hits), timeout=5000)

    assert window.search_hits[0].source == "semantic"
    assert not window.search_progress.isVisible()
    assert window.search_results.count() == len(window.search_hits)
    first = window.search_results.item(0)
    window._search_result_clicked(first)
    assert window.current_search_index == 0
    assert window.search_label.text().startswith("1 / ")

    created = ConstantModel.created
    embed_calls = ConstantModel.embed_calls
    window.search_edit.setText("another semantic query")
    window.start_search()
    qtbot.waitUntil(
        lambda: not window.search_progress.isVisible()
        and window.search_label.text().startswith("1 / "),
        timeout=5000,
    )
    assert ConstantModel.created == created
    assert ConstantModel.embed_calls == embed_calls


def test_dirty_fuzzy_search_restarts_after_worker_cleanup(qtbot, tmp_path, monkeypatch):
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(make_pdf(tmp_path / "reader.pdf"))
    window.show_search()
    window.fuzzy_search.setChecked(True)
    calls = []
    monkeypatch.setattr(window, "start_search", lambda: calls.append(1))
    window._semantic_dirty = True
    window._semantic_thread = None

    window._semantic_thread_done(object())

    assert calls == [1]
    assert not window._semantic_dirty


def test_window_follows_system_theme_without_saved_night_switch(qtbot, tmp_path, monkeypatch):
    from clearview_pdf import ui

    state_path = tmp_path / "state.json"
    StateStore(state_path).set_preference("dark_mode", False)
    monkeypatch.setattr(ui, "system_dark_mode", lambda: True, raising=False)
    window = ui.MainWindow(state_path=state_path)
    qtbot.addWidget(window)

    assert window.styleSheet() == ui.DARK_STYLE
    assert not hasattr(window, "night_action")
    assert StateStore(state_path).preference("dark_mode") is False


def test_windows_color_scheme_signal_updates_chrome(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication
    from clearview_pdf import ui

    window = ui.MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.set_night_mode(False)
    hints = QApplication.instance().styleHints()

    hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    QApplication.processEvents()
    assert window.styleSheet() == ui.DARK_STYLE

    hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
    QApplication.processEvents()
    assert window.styleSheet() == ui.LIGHT_STYLE


def test_light_palette_forces_dark_ui_text(qtbot, tmp_path):
    from PySide6.QtGui import QColor, QPalette
    from clearview_pdf.ui import reading_palette

    palette = reading_palette(False)
    expected = QColor("#20252b")
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        assert palette.color(role) == expected


def test_dark_and_light_modes_paint_the_menu_bar(qtbot, tmp_path):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    for dark, background, foreground in (
        (True, "#25282c", "#e5e7eb"),
        (False, "#f4f5f7", "#20252b"),
    ):
        window.set_night_mode(dark)
        QApplication.processEvents()
        image = window.menuBar().grab().toImage()
        assert image.pixelColor(image.width() - 5, image.height() // 2) == QColor(background)
        assert window.menuBar().palette().windowText().color() == QColor(foreground)


def test_night_mode_does_not_recolor_pdf_pages(qtbot, tmp_path):
    from PySide6.QtGui import QColor

    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    page = window.view.pages[0]

    window.set_night_mode(False)
    page.render(force=True)
    original = page.image.copy()
    assert original.pixelColor(0, 0) == QColor("white")

    window.set_night_mode(True)
    page.render(force=True)
    assert page.image == original


def test_night_mode_page_placeholder_stays_white(qtbot, tmp_path):
    from PySide6.QtGui import QColor

    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)
    window.set_night_mode(True)
    page = window.view.pages[0]
    page.clear_image()

    assert page.grab().toImage().pixelColor(0, 0) == QColor("white")


def test_primary_actions_have_standard_icons(qtbot, tmp_path):
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    for action in (
        window.open_action,
        window.print_action,
        window.previous_action,
        window.next_action,
        window.rotate_action,
        window.rotate_back_action,
        window.reset_rotation_action,
        window.sidebar_action,
    ):
        assert not action.icon().isNull(), action.text()


def test_sidebar_cannot_float_or_show_restore_control(qtbot, tmp_path):
    from PySide6.QtWidgets import QDockWidget

    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)

    assert window.sidebar_dock.features() == QDockWidget.DockWidgetFeature.DockWidgetClosable
    assert not window.sidebar_dock.isFloating()


def test_zoom_percentage_is_editable_and_clamps_to_20_500(qtbot, tmp_path):
    from PySide6.QtWidgets import QLineEdit

    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(make_pdf(tmp_path / "reader.pdf"))
    zoom_edit = getattr(window, "zoom_edit", None)
    assert isinstance(zoom_edit, QLineEdit)
    assert not zoom_edit.isReadOnly()
    assert zoom_edit.alignment() == Qt.AlignmentFlag.AlignCenter
    assert window.page_edit.alignment() == Qt.AlignmentFlag.AlignCenter

    for text, expected in (("125%", 1.25), ("600%", 5.0), ("20%", 0.20), ("19%", 0.20), ("0%", 0.20)):
        zoom_edit.setText(text)
        qtbot.keyClick(zoom_edit, Qt.Key.Key_Return)
        assert window.view.zoom == pytest.approx(expected)
        assert window.view.fit_mode == "custom"
        assert zoom_edit.text() == f"{round(expected * 100)}%"


def test_gibberish_zoom_input_is_a_true_no_op(qtbot, tmp_path):
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(make_pdf(tmp_path / "reader.pdf"))
    window.zoom_edit.setText("125%")
    qtbot.keyClick(window.zoom_edit, Qt.Key.Key_Return)
    window.statusBar().showMessage("unchanged")

    window.zoom_edit.setText("not-a-zoom")
    qtbot.keyClick(window.zoom_edit, Qt.Key.Key_Return)

    assert window.view.zoom == pytest.approx(1.25)
    assert window.view.fit_mode == "custom"
    assert window.zoom_edit.text() == "not-a-zoom"
    assert window.statusBar().currentMessage() == "unchanged"


def test_document_controls_remain_centered_when_sidebar_toggles(qtbot, tmp_path):
    from PySide6.QtWidgets import QToolBar

    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.resize(1300, 800)
    window.show()
    window.open_path(make_pdf(tmp_path / "reader.pdf"))
    toolbar = window.findChild(QToolBar, "documentToolbar")
    first = toolbar.widgetForAction(window.first_action)
    last = toolbar.widgetForAction(window.fit_height_action)

    def assert_centered():
        contents = toolbar.contentsRect()
        controls_center = (first.geometry().left() + last.geometry().right()) / 2
        row_center = (contents.left() + contents.right()) / 2
        assert abs(controls_center - row_center) <= 2

    for visible in (True, False, True):
        window.sidebar_dock.setVisible(visible)
        qtbot.wait(20)
        assert_centered()


def test_menubar_actions_are_text_only_without_losing_toolbar_icons(qtbot, tmp_path):
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    menus = [action.menu() for action in window.menuBar().actions()]
    assert len(menus) == 5

    for menu in menus:
        for action in menu.actions():
            if not action.isSeparator():
                assert not action.isIconVisibleInMenu(), action.text()
    assert not window.open_action.icon().isNull()
    assert not window.print_action.icon().isNull()
    assert not window.search_action.icon().isNull()


def test_about_uses_plain_text_and_shows_the_exact_mention(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    captured = {}

    def reject_static_about(*args):
        raise AssertionError("Static rich-text About must not be used")

    def capture_exec(dialog):
        captured.update(title=dialog.windowTitle(), text=dialog.text(), text_format=dialog.textFormat())
        return 0

    monkeypatch.setattr(QMessageBox, "about", reject_static_about)
    monkeypatch.setattr(QMessageBox, "exec", capture_exec)

    window.show_about()
    lines = [line for line in captured["text"].splitlines() if line.strip()]

    assert captured["title"] == "About ClearView PDF"
    assert captured["text_format"] == Qt.TextFormat.PlainText
    assert "<@839649633130643466>" in lines
    assert "&lt;" not in captured["text"] and "&gt;" not in captured["text"]
    assert not any("Rendering:" in line or "MuPDF" in line for line in lines)


def test_requested_toolbar_glyph_icons(qtbot, tmp_path):
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    fit_height = getattr(window, "fit_height_action", None)
    assert fit_height is not None

    def image(icon):
        return icon.pixmap(24, 24).toImage()

    for action, symbol in (
        (window.first_action, "<<"),
        (window.previous_action, "<"),
        (window.next_action, ">"),
        (window.last_action, ">>"),
        (window.fit_width_action, "⟷"),
        (fit_height, "↕"),
    ):
        assert image(action.icon()) == image(window._compact_symbol_icon(symbol)), action.text()
    assert window.fit_width_action.text() == "Fit to width"
    assert fit_height.text() == "Fit to height"
    assert window.fit_width_action.iconText() == "Fit to width"
    assert fit_height.iconText() == "Fit to height"


@pytest.mark.parametrize("dark", [False, True])
def test_open_print_find_share_monochrome_icon_style(qtbot, tmp_path, dark):
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.set_night_mode(dark)
    expected = window.palette().color(window.palette().ColorRole.ButtonText)

    for action in (window.open_action, window.print_action, window.search_action):
        image = action.icon().pixmap(24, 24).toImage()
        colors = {
            (color.red(), color.green(), color.blue())
            for x in range(image.width())
            for y in range(image.height())
            if (color := image.pixelColor(x, y)).alpha() == 255
        }
        assert colors, action.text()
        assert colors == {(expected.red(), expected.green(), expected.blue())}, action.text()


def test_document_controls_are_compact_icons_above_pdf(qtbot, tmp_path):
    from PySide6.QtWidgets import QToolBar

    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    central = window.stack.parentWidget()
    document_toolbar = window.findChild(QToolBar, "documentToolbar")
    reading_toolbar = window.findChild(QToolBar, "readingToolbar")

    assert document_toolbar is not None
    assert document_toolbar.isHidden()
    assert central.layout().indexOf(document_toolbar) >= 0
    assert central.layout().indexOf(document_toolbar) < central.layout().indexOf(window.stack)
    assert document_toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert 16 <= document_toolbar.iconSize().width() <= 20
    assert document_toolbar.iconSize().height() == document_toolbar.iconSize().width()

    compact_actions = (
        window.first_action,
        window.previous_action,
        window.next_action,
        window.last_action,
        window.zoom_out_action,
        window.zoom_in_action,
        window.fit_width_action,
        window.fit_height_action,
    )
    for action in compact_actions:
        assert action in document_toolbar.actions()
        assert action not in reading_toolbar.actions()
        assert not action.icon().isNull(), action.text()

    assert window.bookmark_action not in reading_toolbar.actions()
    for action in (
        window.rotate_action,
        window.rotate_back_action,
        window.reset_rotation_action,
    ):
        assert action not in document_toolbar.actions()

    window.open_path(make_pdf(tmp_path / "reader.pdf"))
    assert document_toolbar.isVisible()
    assert window.page_edit.parentWidget() is document_toolbar
    assert window.zoom_edit.parentWidget() is document_toolbar


def test_compact_fit_actions_track_the_current_mode(qtbot, tmp_path):
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(make_pdf(tmp_path / "reader.pdf"))

    window.fit_height_action.trigger()
    assert window.view.fit_mode == "height"
    assert window.fit_height_action.isChecked()
    assert not window.fit_width_action.isChecked()

    window.fit_width_action.trigger()
    assert window.view.fit_mode == "width"
    assert window.fit_width_action.isChecked()
    assert not window.fit_height_action.isChecked()

    window.view.zoom_in()
    assert not window.fit_width_action.isChecked()
    assert not window.fit_height_action.isChecked()


def test_fit_height_uses_viewport_height_even_for_wide_pages(qtbot, tmp_path):
    path = tmp_path / "wide.pdf"
    document = pymupdf.open()
    document.new_page(width=1200, height=400)
    document.save(path)
    document.close()
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)

    window.view.set_fit_mode("height")

    expected_zoom = (window.view.viewport().height() - 40) / 400
    assert window.view.zoom == pytest.approx(expected_zoom)
    assert window.view.fit_mode == "height"


def test_ctrl_w_closes_the_document_without_quitting(qtbot, tmp_path):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(make_pdf(tmp_path / "reader.pdf"))
    window.activateWindow()
    window.view.setFocus()
    QApplication.processEvents()

    assert window.close_action.shortcut() == QKeySequence("Ctrl+W")
    QTest.keyClick(window.view, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()

    assert window.document is None
    assert window.document_toolbar.isHidden()
    assert window.isVisible()


def test_thumbnail_rows_fit_document_page_aspect_ratio(qtbot, tmp_path):
    path = tmp_path / "short-pages.pdf"
    document = pymupdf.open()
    document.new_page(width=400, height=520)
    document.save(path)
    document.close()
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)

    expected_icon_height = round(192 * 520 / 400)
    item = window.thumbnails.item(0)
    assert window.thumbnails.iconSize().width() == 192
    assert window.thumbnails.iconSize().height() == expected_icon_height
    assert item.sizeHint().height() == expected_icon_height + 24
    assert window.thumbnails.gridSize().height() == expected_icon_height + 32


def test_thumbnails_are_large_and_rendered_at_icon_resolution(qtbot, tmp_path):
    path = make_pdf(tmp_path / "reader.pdf")
    window = MainWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(window)
    window.show()
    window.open_path(path)

    assert window.thumbnails.iconSize().width() >= 180
    window.thumbnails.load_visible()
    sizes = window.thumbnails.item(0).icon().availableSizes()
    assert sizes and max(size.width() for size in sizes) >= 180
