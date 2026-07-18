"""Application entry point."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Werkrooster Sync")
    app.setOrganizationName("WerkroosterSync")

    from .ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    # Allow opening the app with an .ics file as argument (e.g. "Open with…").
    for arg in sys.argv[1:]:
        if arg.lower().endswith(".ics"):
            window.load_file(arg)
            break

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
