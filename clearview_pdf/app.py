"""Application entry point for ClearView PDF."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QStyleFactory

from . import __version__
from .ui import MainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A small, offline PDF reader")
    parser.add_argument("pdf", nargs="?", type=Path, help="PDF to open")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("ClearView PDF")
    app.setApplicationDisplayName("ClearView PDF")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("ClearView")
    if sys.platform == "win32":
        available_styles = {name.lower() for name in QStyleFactory.keys()}
        for native_style in ("windows11", "windowsvista"):
            if native_style in available_styles:
                app.setStyle(native_style)
                break
    else:
        app.setStyle("Fusion")
    icon = Path(__file__).parent / "assets" / "clearview.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ClearView.PDF.Reader"
        )

    window = MainWindow()
    if args.pdf is not None and not window.open_path(args.pdf):
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
