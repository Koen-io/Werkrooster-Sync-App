"""Automatic updates via GitHub Releases.

Flow: on startup (and via the manual check in Onderhoud) the latest release
is fetched from the GitHub API. If it is newer than the running version, the
UI shows the update dialog; on confirmation the platform asset is downloaded
with progress reporting and installed in place of the current app, after
which the new version is launched and the old process exits.

Install strategy per platform:
- **Windows** (portable .exe): a running executable cannot be overwritten,
  but it *can* be renamed. The old exe is renamed to ``<name>.old``, the new
  one moved into its place, and the leftover is cleaned up on next start.
- **macOS** (.app bundle): the downloaded zip is extracted with ``ditto``
  (preserves signatures/permissions), the old bundle is moved aside and the
  new one takes its path; the app relaunches via ``open``.
"""
from __future__ import annotations

import hashlib
import json
import platform as _platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..version import __version__

RELEASES_API = (
    "https://api.github.com/repos/Koen-io/Werkrooster-Sync-App/releases/latest"
)
RELEASES_PAGE = "https://github.com/Koen-io/Werkrooster-Sync-App/releases/latest"
_TIMEOUT = 15

#: A real browser User-Agent: GitHub's API rejects requests without any UA,
#: and Cloudflare bot-detection scores a custom/script UA as suspicious — a
#: genuine browser string is treated far more leniently.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class UpdateError(Exception):
    """Raised when checking/downloading/installing an update fails."""


def _ssl_context() -> ssl.SSLContext:
    """SSL context with a CA bundle that also works inside the packaged app.

    The frozen Python has no access to the OS certificate store, so HTTPS
    verification fails without certifi's bundled CA file.
    """
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover - certifi is a hard dependency
        ctx = ssl.create_default_context()
    # Also trust the OS certificate store, so corporate TLS-inspection
    # proxies (whose root CA is installed on the machine) keep working.
    try:
        ctx.load_default_certs()
    except Exception:  # pragma: no cover
        pass
    return ctx


@dataclass
class UpdateInfo:
    version: str  # e.g. "1.3.0"
    notes: str
    asset_name: str
    asset_url: str
    asset_size: int
    #: SHA-256 of the file as published by GitHub (hex), "" when unknown.
    asset_sha256: str = ""

    @property
    def tag(self) -> str:
        return f"v{self.version}"


def current_version() -> str:
    return __version__


def is_dev_build() -> bool:
    return "dev" in __version__


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    if not parts:
        raise ValueError(version)
    return tuple(int(p) for p in parts[:3])


def is_newer(remote: str, local: str) -> bool:
    try:
        return _version_tuple(remote) > _version_tuple(local)
    except ValueError:
        return False


def pick_asset(assets: list[dict], platform: str | None = None,
               machine: str | None = None) -> dict | None:
    platform = platform or sys.platform
    # Intel-Macs krijgen hun eigen zip; geen Intel-zip = geen update aanbieden.
    mac_suffix = ("-macOS-Intel.zip" if (machine or _platform.machine()) == "x86_64"
                  else "-macOS.zip")
    for asset in assets:
        name = asset.get("name", "")
        if platform == "darwin" and name.endswith(mac_suffix):
            return asset
        if platform == "win32" and name.endswith(".exe"):
            return asset
    return None


def check_for_update(platform: str | None = None) -> UpdateInfo | None:
    """Return info about a newer release, or None when up to date."""
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise UpdateError(f"Kan niet controleren op updates: {exc}") from exc

    tag = str(data.get("tag_name", "")).lstrip("v")
    if not tag or not is_newer(tag, current_version()):
        return None
    asset = pick_asset(data.get("assets", []), platform)
    if not asset:
        return None
    return UpdateInfo(
        version=tag,
        notes=str(data.get("body", "")).strip(),
        asset_name=asset["name"],
        asset_url=asset["browser_download_url"],
        asset_size=int(asset.get("size", 0)),
        asset_sha256=_digest(asset),
    )


#: Updates are only ever downloaded from the releases of this repository.
DOWNLOAD_PREFIX = "https://github.com/Koen-io/Werkrooster-Sync-App/releases/download/"


def _digest(asset: dict) -> str:
    """The sha256 GitHub publishes for a release file, as lowercase hex."""
    value = str(asset.get("digest") or "")
    if value.startswith("sha256:"):
        value = value[7:].strip().lower()
        if len(value) == 64 and all(c in "0123456789abcdef" for c in value):
            return value
    return ""


def _vertrouwde_url(update: UpdateInfo) -> bool:
    """Precies .../releases/download/<tag van deze versie>/<bestandsnaam>: geen
    omweg via "..", geen andere repository en geen oudere release onder een
    nieuw versienummer."""
    url = update.asset_url
    if not url.startswith(DOWNLOAD_PREFIX) or any(
            t in url.casefold() for t in ("..", "%2e", "%2f", "%5c", "\\", "?", "#")):
        return False
    rest = url[len(DOWNLOAD_PREFIX):]
    return rest in (f"v{update.version}/{update.asset_name}",
                    f"{update.version}/{update.asset_name}")


def download(update: UpdateInfo, progress=None) -> Path:
    """Download the asset to a temp file; ``progress(done, total)`` optional."""
    # Checked before anything is fetched: right place, and a known size and
    # fingerprint to compare the download with.
    if not _vertrouwde_url(update):
        raise UpdateError("De update komt niet van de vertrouwde downloadplek.")
    if not update.asset_sha256 or update.asset_size <= 0:
        raise UpdateError(
            "Deze update kan niet gecontroleerd worden. Download hem handmatig "
            f"via {RELEASES_PAGE}"
        )
    # Path(...).name: the file name comes from the internet.
    dest = (Path(tempfile.mkdtemp(prefix="werkroostersync-update-"))
            / (Path(update.asset_name).name or "update"))
    sha = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(
            update.asset_url, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(
            req, timeout=60, context=_ssl_context()
        ) as resp, open(dest, "wb") as out:
            total = update.asset_size
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > total:
                    break  # larger than announced: stop, rejected below
                out.write(chunk)
                sha.update(chunk)
                if progress:
                    progress(done, total)
    except Exception as exc:
        shutil.rmtree(dest.parent, ignore_errors=True)
        raise UpdateError(f"Download mislukt: {exc}") from exc
    if done != update.asset_size or sha.hexdigest() != update.asset_sha256:
        shutil.rmtree(dest.parent, ignore_errors=True)
        raise UpdateError(
            "De gedownloade update klopt niet met wat GitHub heeft gepubliceerd "
            "(grootte of vingerafdruk wijkt af). Er is niets geïnstalleerd."
        )
    return dest


def cleanup_old_binary() -> None:
    """Remove the '<exe>.old'/'.new' leftovers from a previous Windows update."""
    if not getattr(sys, "frozen", False):
        return
    for suffix in (".old", ".new"):
        leftover = Path(sys.executable + suffix)
        try:
            if leftover.exists():
                leftover.unlink()
        except OSError:
            pass


def install_and_restart(update: UpdateInfo, downloaded: Path) -> None:
    """Replace the running app with *downloaded* and relaunch. Exits the
    process on success; raises UpdateError on failure."""
    if not getattr(sys, "frozen", False):
        raise UpdateError(
            "Automatisch installeren werkt alleen in de gebouwde app. "
            f"Download handmatig via {RELEASES_PAGE}"
        )
    if sys.platform == "darwin":
        _install_macos(downloaded)
    elif sys.platform == "win32":
        _install_windows(downloaded)
    else:  # pragma: no cover
        raise UpdateError("Automatisch installeren wordt niet ondersteund op dit platform.")


def _install_macos(zip_path: Path) -> None:
    exe = Path(sys.executable).resolve()
    try:
        app_bundle = next(p for p in exe.parents if p.suffix == ".app")
    except StopIteration as exc:
        raise UpdateError("Kan de app-locatie niet bepalen.") from exc

    extract_dir = zip_path.parent / "extracted"
    try:
        subprocess.run(
            ["ditto", "-x", "-k", str(zip_path), str(extract_dir)],
            check=True, capture_output=True,
        )
        new_app = next(extract_dir.glob("*.app"))
        if new_app.is_symlink():
            raise UpdateError("De update is geen echte app. Er is niets geïnstalleerd.")
    except (subprocess.CalledProcessError, StopIteration) as exc:
        raise UpdateError(f"Uitpakken van de update mislukt: {exc}") from exc
    if not any((new_app / "Contents" / "MacOS").glob("*")):
        raise UpdateError("De update bevat geen werkende app. Er is niets geïnstalleerd.")

    _swap_macos_app(new_app, app_bundle, zip_path.parent / (app_bundle.name + ".old"))

    # In-app downloads carry no quarantine flag, so Gatekeeper will not show
    # the "open anyway" dance again — strip it anyway in case anything set it.
    subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(app_bundle)],
        capture_output=True,
    )
    subprocess.Popen(["open", "-n", str(app_bundle)])
    raise SystemExit(0)


def _swap_macos_app(new_app: Path, app_bundle: Path, backup: Path) -> None:
    """Move the old bundle aside and the new one into its place. If the
    second step fails the old app is put back, so the user is never left
    without an app. Separated from relaunching so it can be tested."""
    try:
        shutil.move(str(app_bundle), str(backup))
    except OSError as exc:
        raise UpdateError(f"Installeren mislukt (geen schrijfrechten?): {exc}") from exc
    try:
        shutil.move(str(new_app), str(app_bundle))
    except OSError as exc:
        shutil.rmtree(app_bundle, ignore_errors=True)  # half-moved copy
        try:
            shutil.move(str(backup), str(app_bundle))
        except OSError:
            raise UpdateError(
                "Installeren mislukt en terugzetten lukte niet. De vorige "
                f"versie staat in {backup}. Download de app opnieuw via {RELEASES_PAGE}"
            ) from exc
        raise UpdateError(
            f"Installeren mislukt; de vorige versie is teruggezet. ({exc})"
        ) from exc


def _swap_windows_exe(exe_path: Path, current: Path) -> None:
    """Replace *current* with *exe_path*, robust across drives. Separated
    from process relaunch so it can be tested."""
    old = Path(str(current) + ".old")
    staged = Path(str(current) + ".new")
    try:
        # 1) Copy the download next to the target first. This is the only
        #    cross-drive step (the download sits in the system temp dir on
        #    C:, while the app may run from a mapped/shared drive such as a
        #    Parallels share, which os.replace refuses to move across).
        if staged.exists():
            staged.unlink()
        shutil.copy2(str(exe_path), str(staged))
        # 2) Swap with two same-drive renames (always allowed, even on
        #    mapped drives, and cheap/atomic).
        if old.exists():
            old.unlink()
        current.rename(old)      # move the running exe aside
        staged.rename(current)   # put the new exe in its place
    except OSError as exc:
        # Roll back so the app is never left without its executable.
        try:
            if not current.exists() and old.exists():
                old.rename(current)
        except OSError:
            pass
        try:
            if staged.exists():
                staged.unlink()
        except OSError:
            pass
        raise UpdateError(
            f"Installeren mislukt: {exc}. Download eventueel handmatig via "
            f"{RELEASES_PAGE}"
        ) from exc


def _install_windows(exe_path: Path) -> None:
    current = Path(sys.executable).resolve()
    _swap_windows_exe(exe_path, current)
    subprocess.Popen([str(current)], close_fds=True)
    raise SystemExit(0)
