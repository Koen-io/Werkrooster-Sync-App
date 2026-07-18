@echo off
REM Build the portable Windows .exe. Run on Windows, from the repository root:
REM   packaging\build_win.bat
cd /d "%~dp0\.."

python -m pip install -r requirements-dev.txt || exit /b 1
python -m PyInstaller WerkroosterSync.spec --noconfirm --workpath .pyibuild || exit /b 1

echo.
echo Klaar!  ^>  dist\WerkroosterSync.exe
echo Dit ene .exe-bestand is de hele app: kopieer het naar elke Windows-pc en start het direct.
