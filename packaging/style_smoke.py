"""Launch-level check for native Windows styling without entering the event loop."""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDockWidget, QLineEdit

from clearview_pdf import app as entry_point
from clearview_pdf.ui import DARK_STYLE, MainWindow, system_dark_mode


def main() -> None:
    observed = {}
    real_exec = QApplication.exec

    def smoke_exec(application):
        observed["style"] = application.style().objectName().lower()
        assert observed["style"] in {"windows11", "windowsvista"}, observed["style"]
        window = next(
            widget for widget in application.topLevelWidgets() if isinstance(widget, MainWindow)
        )
        assert window.sidebar_dock.features() == QDockWidget.DockWidgetFeature.DockWidgetClosable
        assert isinstance(window.zoom_edit, QLineEdit)
        assert not hasattr(window, "semantic_search")
        for menu_action in window.menuBar().actions():
            for action in menu_action.menu().actions():
                if not action.isSeparator():
                    assert not action.isIconVisibleInMenu(), action.text()
        actions = (
            window.open_action,
            window.print_action,
            window.search_action,
            window.first_action,
            window.previous_action,
            window.next_action,
            window.last_action,
            window.zoom_out_action,
            window.zoom_in_action,
            window.fit_width_action,
            window.fit_height_action,
            window.rotate_action,
            window.rotate_back_action,
            window.reset_rotation_action,
            window.sidebar_action,
        )
        null_icons = [action.text() for action in actions if action.icon().isNull()]
        assert not null_icons, null_icons
        original_dark = system_dark_mode()
        assert (window.styleSheet() == DARK_STYLE) == original_dark
        assert not hasattr(window, "night_action")
        observed["system_theme"] = "dark" if original_dark else "light"
        try:
            for dark, background, foreground in (
                (True, "#25282c", "#e5e7eb"),
                (False, "#f4f5f7", "#20252b"),
            ):
                window.set_night_mode(dark)
                application.processEvents()
                image = window.menuBar().grab().toImage()
                assert image.pixelColor(image.width() - 5, image.height() // 2) == QColor(background)
                assert window.menuBar().palette().windowText().color() == QColor(foreground)
        finally:
            window.set_night_mode(original_dark)
        observed["icons"] = len(actions)
        return 0

    QApplication.exec = smoke_exec
    try:
        assert entry_point.main([]) == 0
    finally:
        QApplication.exec = real_exec
    print(f"NATIVE_STYLE={observed['style']} TOOLBAR_AND_MENU_ICONS={observed['icons']} SYSTEM_THEME={observed['system_theme']} MENU_THEMES=OK")


if __name__ == "__main__":
    main()
