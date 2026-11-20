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

    from .core import logbook
    from .version import __version__

    def tell_user(message: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            None,
            "Er ging iets mis",
            "Er ging iets onverwachts mis. Aan je agenda is door deze fout "
            "niets veranderd dat de app niet heeft gemeld.\n\n"
            "De fout is genoteerd in het logboek. Via Feedback kun je het "
            f"logboek meesturen.\n\n({message})",
        )

    logbook.setup(on_crash=tell_user)
    logbook.log.info("Start versie %s op %s", __version__, sys.platform)

    # Het meegeleverde lettertype laden voordat er een venster gebouwd wordt.
    from .core.updater import cleanup_old_binary
    from .ui import theme

    theme.laad_lettertype()
    cleanup_old_binary()  # leftover from a previous Windows update

    splash = _make_splash(app)
    if splash:
        splash.show()
        splash.raise_()
        app.processEvents()

    from .ui.main_window import MainWindow

    window = MainWindow()

    pending_files = [arg for arg in sys.argv[1:] if arg.lower().endswith(".pdf")]

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
        if pending_files:
            window.load_files(pending_files)

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
