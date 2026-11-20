#!/usr/bin/env bash
# Maak assets/handleiding.pdf (en de kopie in docs/) opnieuw uit
# docs/handleiding/handleiding.html. Nodig: Google Chrome op een Mac.
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="assets/handleiding.pdf" "file://$PWD/docs/handleiding/handleiding.html"
cp assets/handleiding.pdf docs/Werkrooster-Sync-Handleiding.pdf
echo "Klaar: assets/handleiding.pdf"
