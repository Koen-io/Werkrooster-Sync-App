"""Application entry point: splash screen, app icon, main window."""
from __future__ import annotations

import sys

#: How long the splash screen stays visible before the main window opens.
#: Long enough for the full entrance animation plus one glow pulse.
SPLASH_MILLISECONDS = 2400


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
    """Build the animated splash screen, centered on the primary screen."""
    from .ui.splash import AnimatedSplash
    from .version import __version__

    label = "dev" if "dev" in __version__ else f"v{__version__}"
    splash = AnimatedSplash(version=label)
    screen = app.primaryScreen().availableGeometry()
    frame = splash.frameGeometry()
    frame.moveCenter(screen.center())
    splash.move(frame.topLeft())
    return splash


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

    # Activate the configured color palette before any window is built.
    from .core.settings import Settings
    from .core.updater import cleanup_old_binary
    from .ui import theme

    theme.apply_palette(Settings.load().theme)
    cleanup_old_binary()  # leftover from a previous Windows update

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
        # Open maximized so the whole title bar is visible. A sensible restore
        # size is set first, so un-maximizing gives a comfortable window.
        screen = app.primaryScreen().availableGeometry()
        rw, rh = int(screen.width() * 0.72), int(screen.height() * 0.85)
        window.resize(rw, rh)
        window.move(
            screen.x() + (screen.width() - rw) // 2,
            screen.y() + (screen.height() - rh) // 2,
        )
        window.showMaximized()
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

    def check_updates() -> None:
        from .core.updater import check_for_update, current_version, is_dev_build

        if is_dev_build():
            return
        from .ui.settings_dialog import _Worker

        worker = _Worker(check_for_update, window)

        def on_found(update) -> None:
            if update is not None:
                from .ui.update_dialog import UpdateDialog

                UpdateDialog(update, current_version(), window).exec()

        worker.done.connect(on_found)
        worker.failed.connect(lambda _msg: None)  # silent when offline
        window._update_worker = worker
        worker.start()

    # Check shortly after startup so it never delays the window itself.
    QTimer.singleShot(SPLASH_MILLISECONDS + 1500, check_updates)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
