"""Application entry point: splash screen, app icon, main window."""
from __future__ import annotations

import sys

#: How long the splash screen stays visible before the main window opens.
SPLASH_MILLISECONDS = 1800


def _app_icon():
    from PySide6.QtGui import QIcon

    from .resources import asset_path

    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512):
        p = asset_path(f"icons/app-icon-{size}.png")
        if p.exists():
            icon.addFile(str(p))
    if icon.isNull():
        logo = asset_path("logo.png")
        if logo.exists():
            icon.addFile(str(logo))
    return icon


def _make_splash(app):
    """Build the splash screen, centered on the primary screen. Returns None
    when no splash image is bundled."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QSplashScreen

    from .resources import asset_path

    splash_file = asset_path("splash.png")
    if not splash_file.exists():
        return None
    pixmap = QPixmap(str(splash_file))
    if pixmap.isNull():
        return None
    # The artwork is delivered at 2x; scale to a comfortable logical size and
    # keep it crisp on Retina/HiDPI screens.
    pixmap.setDevicePixelRatio(2.0)
    splash = QSplashScreen(pixmap, Qt.WindowType.WindowStaysOnTopHint)
    screen = app.primaryScreen().availableGeometry()
    frame = splash.frameGeometry()
    frame.moveCenter(screen.center())
    splash.move(frame.topLeft())
    return splash


def _center_on_screen(app, window) -> None:
    screen = app.primaryScreen().availableGeometry()
    frame = window.frameGeometry()
    frame.moveCenter(screen.center())
    window.move(frame.topLeft())


def main() -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Werkrooster Sync")
    app.setOrganizationName("WerkroosterSync")
    app.setWindowIcon(_app_icon())

    splash = _make_splash(app)
    if splash:
        splash.show()
        splash.raise_()
        app.processEvents()

    from .ui.main_window import MainWindow

    window = MainWindow()

    pending_file = next(
        (arg for arg in sys.argv[1:] if arg.lower().endswith((".ics", ".pdf"))), None
    )

    def show_main() -> None:
        # Front and centre at startup; after that the window behaves normally.
        _center_on_screen(app, window)
        window.show()
        window.raise_()
        window.activateWindow()
        if splash:
            splash.finish(window)
        if pending_file:
            window.load_file(pending_file)

    if splash:
        QTimer.singleShot(SPLASH_MILLISECONDS, show_main)
    else:
        show_main()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
