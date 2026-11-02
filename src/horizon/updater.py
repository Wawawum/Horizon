"""Mise à jour de Horizon depuis les Releases GitHub.

Seule l'application gelée (PyInstaller, mode onedir) se met à jour elle-même : le zip
publié est extrait dans un dossier frère de l'installation, puis un script PowerShell
détaché attend la fin du processus, permute les deux dossiers et relance Horizon.
En mode source, on se contente de signaler la nouvelle version : c'est git qui met
à jour un dépôt.
"""

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import certifi

from horizon.version import current_version, parse_version


GITHUB_REPO = "Wawawum/Horizon"
_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_UPDATES_DIR = Path.home() / ".horizon" / "updates"
_LOG_PATH = _UPDATES_DIR / "update.log"
_CHUNK_SIZE = 256 * 1024


def _open(request: urllib.request.Request, timeout: float):
    # Bundle certifi plutôt que le magasin Windows : l'OpenSSL de Python ne télécharge pas
    # les racines manquantes comme le fait schannel, et la chaîne Sectigo E46 servie par
    # api.github.com échoue alors avec CERTIFICATE_VERIFY_FAILED.
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(request, timeout=timeout, context=context)

# Exécuté après la fermeture de Horizon, une fois que plus aucun fichier du dossier
# d'installation n'est verrouillé. ASCII uniquement : Windows PowerShell 5.1 lit les
# scripts sans BOM en ANSI.
_INSTALL_SCRIPT = r"""
param(
    [int]$ProcessId,
    [string]$Source,
    [string]$Target,
    [string]$Log
)

function Write-Log([string]$Message) {
    Add-Content -LiteralPath $Log -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $Message)
}

$exe = Join-Path $Target 'Horizon.exe'
$backup = "$Target.old"

Write-Log "Attente de la fin de Horizon (PID $ProcessId)"
Wait-Process -Id $ProcessId -Timeout 60 -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $backup) {
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
}

# QtWebEngineProcess peut survivre quelques instants au processus principal.
$moved = $false
for ($i = 0; $i -lt 30 -and -not $moved; $i++) {
    try {
        Move-Item -LiteralPath $Target -Destination $backup -ErrorAction Stop
        $moved = $true
    } catch {
        $lastError = $_
        Start-Sleep -Seconds 1
    }
}
if (-not $moved) {
    Write-Log "Echec : $Target reste verrouille ($lastError). Ancienne version relancee."
    Start-Process -FilePath $exe
    exit 1
}

try {
    Move-Item -LiteralPath $Source -Destination $Target -ErrorAction Stop
} catch {
    Write-Log "Echec de la mise en place ($_). Restauration de l'ancienne version."
    Move-Item -LiteralPath $backup -Destination $Target
    Start-Process -FilePath $exe
    exit 1
}

Write-Log "Nouvelle version en place, relance de $exe"
Start-Process -FilePath $exe
Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
Write-Log "Termine"
"""


class UpdateCancelled(Exception):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    html_url: str
    notes: str
    asset_name: str | None = None
    asset_url: str | None = None
    asset_size: int = 0
    sha256: str | None = None


def log(message: str) -> None:
    """Journal des mises à jour, partagé avec le script d'installation."""
    try:
        _UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")
    except OSError:
        pass


def fetch_latest_release() -> ReleaseInfo | None:
    """Dernière Release publiée (ni brouillon ni pré-release) ; None si elle est inexploitable."""
    request = urllib.request.Request(
        _LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Horizon/{current_version()}",
        },
    )
    with _open(request, timeout=10) as response:
        data = json.load(response)

    tag = data.get("tag_name") or ""
    version = tag.removeprefix("v")
    if parse_version(version) is None:
        return None
    release = ReleaseInfo(
        version=version,
        tag=tag,
        html_url=data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases",
        notes=data.get("body") or "",
    )
    # Nom fixé par .github/workflows/build.yml.
    expected = f"Horizon-{version}-win64.zip"
    for asset in data.get("assets", []):
        if asset.get("name") == expected:
            release.asset_name = expected
            release.asset_url = asset.get("browser_download_url")
            release.asset_size = asset.get("size") or 0
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                release.sha256 = digest.removeprefix("sha256:").lower()
            break
    return release


def is_newer(remote: str, local: str) -> bool:
    remote_v, local_v = parse_version(remote), parse_version(local)
    if remote_v is None or local_v is None:
        return False
    return remote_v > local_v


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    """Dossier contenant Horizon.exe (application gelée uniquement)."""
    return Path(sys.executable).resolve().parent


def _staging_dir() -> Path:
    install = install_dir()
    return install.with_name(install.name + ".new")


def can_self_update(release: ReleaseInfo) -> str | None:
    """None si la mise à jour peut s'installer seule, sinon la raison."""
    if not is_frozen():
        return "Horizon est lancé depuis les sources : mettez le dépôt à jour avec git."
    if not release.asset_url:
        return f"La release {release.tag} ne contient pas d'archive Windows."
    # Le basculement renomme le dossier d'installation : il faut écrire dans son parent.
    try:
        with tempfile.TemporaryFile(dir=install_dir().parent):
            pass
    except OSError:
        return f"Le dossier {install_dir().parent} n'est pas accessible en écriture."
    return None


def download_update(
    release: ReleaseInfo,
    progress: Callable[[int, int], None],
    cancelled: Callable[[], bool],
) -> Path:
    """Télécharge l'archive de la release et vérifie son intégrité."""
    _UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    target = _UPDATES_DIR / release.asset_name
    part = target.with_name(target.name + ".part")
    request = urllib.request.Request(
        release.asset_url, headers={"User-Agent": f"Horizon/{current_version()}"}
    )
    sha256 = hashlib.sha256()
    received = 0
    log(f"Téléchargement de {release.asset_url}")
    try:
        with _open(request, timeout=30) as response, part.open("wb") as out:
            total = int(response.headers.get("Content-Length") or release.asset_size)
            while chunk := response.read(_CHUNK_SIZE):
                if cancelled():
                    raise UpdateCancelled()
                out.write(chunk)
                sha256.update(chunk)
                received += len(chunk)
                progress(received, total)
    except BaseException:
        part.unlink(missing_ok=True)
        raise

    if release.asset_size and received != release.asset_size:
        part.unlink(missing_ok=True)
        raise ValueError(f"Archive incomplète : {received} octets reçus sur {release.asset_size}.")
    if release.sha256 and sha256.hexdigest() != release.sha256:
        part.unlink(missing_ok=True)
        raise ValueError("L'empreinte SHA-256 de l'archive ne correspond pas à celle de la release.")
    part.replace(target)
    log(f"Archive vérifiée : {target}")
    return target


def stage_update(zip_path: Path) -> Path:
    """Extrait l'archive à côté de l'installation et renvoie le dossier prêt à la remplacer."""
    staging = _staging_dir()
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staging)
        # 7z conserve le chemin passé par le workflow : tout est sous dist/Horizon/. On
        # cherche à n'importe quelle profondeur pour survivre à un changement d'archivage.
        executables = sorted(staging.rglob("Horizon.exe"), key=lambda p: len(p.parts))
        app_dir = next((exe.parent for exe in executables if (exe.parent / "_internal").is_dir()), None)
        if app_dir is None:
            raise ValueError("L'archive ne contient pas Horizon.exe et son dossier _internal.")
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    zip_path.unlink(missing_ok=True)
    log(f"Nouvelle version extraite dans {app_dir}")
    return app_dir


def launch_installer(staged: Path) -> None:
    """Lance le script qui remplacera l'installation dès la fin de ce processus."""
    _UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    script = _UPDATES_DIR / "install.ps1"
    script.write_text(_INSTALL_SCRIPT, encoding="ascii")
    log(f"Lancement de l'installation : {staged} -> {install_dir()}")
    subprocess.Popen(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", str(script),
            "-ProcessId", str(os.getpid()),
            "-Source", str(staged),
            "-Target", str(install_dir()),
            "-Log", str(_LOG_PATH),
        ],
        # Jamais le dossier d'installation : un répertoire courant le verrouillerait.
        cwd=str(_UPDATES_DIR),
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def cleanup_previous_update() -> None:
    """Efface les restes d'une mise à jour : ancienne version, extraction orpheline, archives."""
    if is_frozen():
        install = install_dir()
        for leftover in (install.with_name(install.name + ".old"), _staging_dir()):
            if leftover.exists():
                shutil.rmtree(leftover, ignore_errors=True)
                log(f"Nettoyage de {leftover}")
    if _UPDATES_DIR.is_dir():
        for archive in (*_UPDATES_DIR.glob("*.zip"), *_UPDATES_DIR.glob("*.part")):
            archive.unlink(missing_ok=True)
