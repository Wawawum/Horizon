"""Genere build/horizon.ico a partir de l'icone PNG du paquet.

Windows attend un .ico multi-tailles pour l'executable, or le depot ne contient
que le PNG 256x256 servant d'icone de fenetre (horizon/app.py). Ce script est
appele par le workflow de build avant PyInstaller ; si le .ico est absent,
horizon.spec construit simplement l'executable sans icone.

    python tools/make_icon.py
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "horizon" / "resources" / "Horizon_Icon.png"
TARGET = ROOT / "build" / "horizon.ico"
SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    if not SOURCE.exists():
        sys.exit(f"icone source introuvable : {SOURCE}")

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as image:
        image.convert("RGBA").save(TARGET, format="ICO", sizes=SIZES)

    print(f"{TARGET} genere ({TARGET.stat().st_size} octets)")


if __name__ == "__main__":
    main()
