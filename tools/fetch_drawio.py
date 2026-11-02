"""Telecharge l'editeur draw.io embarque dans src/horizon/resources/drawio/draw.war.

Horizon sert draw.io lui-meme (widgets/drawio.py) au lieu de charger
embed.diagrams.net, que bloquent certains reseaux d'entreprise. L'archive
(~47 Mo, licence Apache 2.0) n'est pas versionnee : ce script la recupere
depuis la release GitHub de jgraph/drawio indiquee ci-dessous et verifie son
empreinte. Il est appele par le workflow de build avant PyInstaller et par
Lancer-Horizon.bat ; il ne fait rien si l'archive attendue est deja la.

    python tools/fetch_drawio.py

Pour monter de version : changer VERSION et SHA256 (Get-FileHash -Algorithm
SHA256 sur le draw.war de la nouvelle release).
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

VERSION = "32.6.9"
SHA256 = "31afc82b7920c409d0591f6126ccb6c377d7800e7f11ab324f88bdf1e4249ce7"
URL = f"https://github.com/jgraph/drawio/releases/download/v{VERSION}/draw.war"

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "src" / "horizon" / "resources" / "drawio" / "draw.war"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if TARGET.exists() and _sha256(TARGET) == SHA256:
        print(f"draw.io {VERSION} deja present : {TARGET}")
        return

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    partial = TARGET.with_suffix(".part")
    print(f"Telechargement de draw.io {VERSION} depuis {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=60) as response, partial.open("wb") as f:
            while chunk := response.read(1 << 20):
                f.write(chunk)
    except OSError as e:
        partial.unlink(missing_ok=True)
        sys.exit(f"echec du telechargement : {e}")

    actual = _sha256(partial)
    if actual != SHA256:
        partial.unlink()
        sys.exit(f"empreinte inattendue pour draw.war : {actual} (attendu {SHA256})")

    partial.replace(TARGET)
    print(f"{TARGET} ({TARGET.stat().st_size // 1048576} Mo)")


if __name__ == "__main__":
    main()
