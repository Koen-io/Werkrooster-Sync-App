#!/usr/bin/env bash
# Build the self-contained macOS app. Run on a Mac, from the repository root:
#   ./packaging/build_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install -r requirements-dev.txt
python3 -m PyInstaller WerkroosterSync.spec --noconfirm --workpath .pyibuild

# Ad-hoc codesign so macOS Gatekeeper and the Agenda-permission prompt behave.
codesign --force --deep -s - "dist/Werkrooster Sync.app"

echo
echo "Klaar ✓  →  dist/Werkrooster Sync.app"
echo "Kopieer de hele .app naar een andere Mac (bijv. via AirDrop of USB) en hij werkt direct."
