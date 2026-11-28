"""Tests for the auto-update logic (no network involved)."""
from __future__ import annotations

import os

import pytest

from werkrooster_sync.core.updater import (
    UpdateInfo,
    is_newer,
    pick_asset,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ASSETS = [
    {"name": "WerkroosterSync-macOS.zip",
     "browser_download_url": "https://example/mac.zip", "size": 41_000_000},
    {"name": "WerkroosterSync.exe",
     "browser_download_url": "https://example/win.exe", "size": 58_000_000},
]


def test_version_comparison():
    assert is_newer("1.3.0", "1.2.0")
    assert is_newer("2.0.0", "1.9.9")
    assert is_newer("1.2.10", "1.2.9")
    assert not is_newer("1.2.0", "1.2.0")
    assert not is_newer("1.1.9", "1.2.0")
    # A dev build or garbage never triggers an update prompt by comparison.
    assert not is_newer("garbage", "1.2.0")
    assert is_newer("1.3.0", "0.0.0-dev") is True


def test_windows_exe_swap_across_directories(tmp_path):
    """Reproduces WinError 17: the download and the installed app live in
    different locations (drives). The swap must still succeed and leave a
    .old backup, never delete the running exe on failure."""
    from werkrooster_sync.core.updater import _swap_windows_exe

    app_dir = tmp_path / "app"
    download_dir = tmp_path / "download"
    app_dir.mkdir()
    download_dir.mkdir()

    current = app_dir / "WerkroosterSync.exe"
    current.write_bytes(b"OLD-VERSION")
    new_exe = download_dir / "WerkroosterSync.exe"
    new_exe.write_bytes(b"NEW-VERSION")

    _swap_windows_exe(new_exe, current)

    assert current.read_bytes() == b"NEW-VERSION"
    assert (app_dir / "WerkroosterSync.exe.old").read_bytes() == b"OLD-VERSION"
    assert not (app_dir / "WerkroosterSync.exe.new").exists()


def test_pick_asset_per_platform():
    assert pick_asset(ASSETS, "darwin")["name"] == "WerkroosterSync-macOS.zip"
    assert pick_asset(ASSETS, "win32")["name"] == "WerkroosterSync.exe"
    assert pick_asset([], "darwin") is None
    assert pick_asset(ASSETS, "linux") is None


def test_pick_asset_mac_intel():
    intel = {"name": "WerkroosterSync-macOS-Intel.zip"}
    assert pick_asset(ASSETS + [intel], "darwin", "arm64")["name"] == "WerkroosterSync-macOS.zip"
    assert pick_asset([intel] + ASSETS, "darwin", "x86_64") is intel
    assert pick_asset(ASSETS, "darwin", "x86_64") is None


def test_ssl_context_uses_certifi_bundle():
    import certifi

    from werkrooster_sync.core.updater import _ssl_context

    ctx = _ssl_context()
    # A CA store must actually be loaded (this is what fails in a frozen
    # app without certifi: no local issuer certificates).
    assert ctx.cert_store_stats()["x509_ca"] > 0
    assert certifi.where()


def test_up_to_date_dialog_smoke():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from werkrooster_sync.ui.update_dialog import UpToDateDialog

    dialog = UpToDateDialog("1.3.1")
    assert dialog.windowTitle() == "Up-to-date"
    from PySide6.QtWidgets import QLabel

    texts = " ".join(l.text() for l in dialog.findChildren(QLabel))
    assert "v1.3.1" in texts
    dialog.close()


def test_update_dialog_smoke():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from werkrooster_sync.ui.update_dialog import UpdateDialog

    update = UpdateInfo(
        version="9.9.9",
        notes="## Downloads\n- **macOS**: nieuwe versie\n- Windows: idem",
        asset_name="WerkroosterSync-macOS.zip",
        asset_url="https://example/mac.zip",
        asset_size=41_000_000,
    )
    dialog = UpdateDialog(update, current_version="1.2.0")
    # Progress formatting path
    dialog._on_progress(20_500_000, 41_000_000)
    assert dialog.progress.value() == 50
    assert "MB" in dialog.status.text()
    dialog._on_failed("Download mislukt: test")
    assert dialog.install_btn.isEnabled()
    dialog.close()


# ----------------------------------------------------------------------
# Controle van de download (2.0)
# ----------------------------------------------------------------------
import hashlib
import io

from werkrooster_sync.core import updater as updater_mod
from werkrooster_sync.core.updater import DOWNLOAD_PREFIX, UpdateError, _digest


def _update(inhoud: bytes, **anders) -> UpdateInfo:
    velden = dict(
        version="9.9.9", notes="", asset_name="WerkroosterSync.exe",
        asset_url=DOWNLOAD_PREFIX + "v9.9.9/WerkroosterSync.exe",
        asset_size=len(inhoud), asset_sha256=hashlib.sha256(inhoud).hexdigest(),
    )
    velden.update(anders)
    return UpdateInfo(**velden)


class _Antwoord(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _nep_internet(monkeypatch, geleverd: bytes):
    opgevraagd = []

    def urlopen(req, **kwargs):
        opgevraagd.append(req.full_url)
        return _Antwoord(geleverd)

    monkeypatch.setattr(updater_mod.urllib.request, "urlopen", urlopen)
    return opgevraagd


def test_download_met_juiste_vingerafdruk_wordt_geaccepteerd(monkeypatch):
    inhoud = b"nieuwe versie" * 1000
    _nep_internet(monkeypatch, inhoud)
    pad = updater_mod.download(_update(inhoud))
    assert pad.read_bytes() == inhoud


@pytest.mark.parametrize("geleverd", [
    b"x" * 13000,                    # zelfde grootte, andere inhoud
    b"nieuwe versie" * 999,          # afgebroken download
    b"nieuwe versie" * 1000 + b"!",  # groter dan aangekondigd
])
def test_afwijkende_download_wordt_geweigerd(monkeypatch, geleverd):
    _nep_internet(monkeypatch, geleverd)
    with pytest.raises(UpdateError, match="klopt niet"):
        updater_mod.download(_update(b"nieuwe versie" * 1000))


@pytest.mark.parametrize("anders", [
    {"asset_sha256": ""},                                  # GitHub gaf geen vingerafdruk
    {"asset_size": 0},
    {"asset_url": "https://example.com/WerkroosterSync.exe"},
    {"asset_url": "http://github.com/Koen-io/Werkrooster-Sync-App/releases/download/x.exe"},
])
def test_oncontroleerbare_update_wordt_niet_eens_opgehaald(monkeypatch, anders):
    opgevraagd = _nep_internet(monkeypatch, b"abc")
    with pytest.raises(UpdateError):
        updater_mod.download(_update(b"abc", **anders))
    assert opgevraagd == []


def test_bestandsnaam_van_internet_kan_niet_buiten_de_map_schrijven(monkeypatch):
    opgevraagd = _nep_internet(monkeypatch, b"abc")
    # Past de naam niet bij de downloadplek, dan wordt er niets opgehaald.
    with pytest.raises(UpdateError):
        updater_mod.download(_update(b"abc", asset_name="../../kwaad.exe"))
    assert opgevraagd == []


def test_digest_alleen_geldige_sha256():
    assert _digest({"digest": "sha256:" + "AB" * 32}) == "ab" * 32
    assert _digest({"digest": "md5:abc"}) == ""
    assert _digest({"digest": "sha256:kort"}) == ""
    assert _digest({}) == ""


def test_mac_update_zet_oude_app_terug_als_het_misgaat(tmp_path, monkeypatch):
    app = tmp_path / "Werkrooster Sync.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "oud.txt").write_text("oud")
    nieuw = tmp_path / "bestaat-niet.app"  # verplaatsen hiervan mislukt
    with pytest.raises(UpdateError, match="teruggezet"):
        updater_mod._swap_macos_app(nieuw, app, tmp_path / "backup.old")
    assert (app / "Contents" / "oud.txt").read_text() == "oud"


def test_mac_update_wisselt_de_app(tmp_path):
    app = tmp_path / "Werkrooster Sync.app"
    (app / "Contents").mkdir(parents=True)
    nieuw = tmp_path / "uit" / "Werkrooster Sync.app"
    (nieuw / "Contents").mkdir(parents=True)
    (nieuw / "Contents" / "nieuw.txt").write_text("nieuw")
    updater_mod._swap_macos_app(nieuw, app, tmp_path / "backup.old")
    assert (app / "Contents" / "nieuw.txt").exists()
    assert (tmp_path / "backup.old").is_dir()


@pytest.mark.parametrize("url", [
    DOWNLOAD_PREFIX + "../../../ander/repo/releases/download/v9.9.9/WerkroosterSync.exe",
    DOWNLOAD_PREFIX + "v9.9.9/%2e%2e/WerkroosterSync.exe",
    DOWNLOAD_PREFIX + "v1.0.0/WerkroosterSync.exe",       # oude release onder nieuw nummer
    DOWNLOAD_PREFIX + "v9.9.9/Iets-anders.exe",
    DOWNLOAD_PREFIX + "v9.9.9/WerkroosterSync.exe?x=1",
    "https://github.com/Koen-io/Werkrooster-Sync-App-nep/releases/download/v9.9.9/WerkroosterSync.exe",
])
def test_omweg_in_de_downloadplek_wordt_geweigerd(monkeypatch, url):
    opgevraagd = _nep_internet(monkeypatch, b"x")
    with pytest.raises(UpdateError, match="vertrouwde"):
        updater_mod.download(_update(b"x", asset_url=url))
    assert opgevraagd == []
