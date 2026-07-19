"""Launcher used both for development (`python run_app.py`) and by PyInstaller."""
from werkrooster_sync.app import main

raise SystemExit(main())
