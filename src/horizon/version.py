import importlib.metadata
import tomllib
from pathlib import Path


# Gravé par le CI dans le bundle avant PyInstaller : c'est la version du tag, donc
# celle du nom du zip publié. Absent en mode source.
_VERSION_FILE = Path(__file__).parent / "VERSION"
_PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def current_version() -> str:
    """Version de l'Horizon en cours d'exécution."""
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    # Mode source : le TOML fait foi, alors que les métadonnées d'une installation
    # éditable restent figées à la version du dernier `pip install -e .`.
    try:
        return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        pass
    try:
        return importlib.metadata.version("horizon")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def parse_version(value: str) -> tuple[int, ...] | None:
    """`"v0.3.1"` -> `(0, 3, 1)` ; None pour tout ce qui n'est pas purement numérique."""
    parts = value.strip().removeprefix("v").split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)
