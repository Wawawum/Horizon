"""Importe tous les modules du paquet horizon et signale ceux qui echouent.

`python -m compileall` ne detecte que les erreurs de syntaxe : une annotation
faisant reference a un nom non importe (NameError a l'import) passe la
compilation et ne casse qu'au lancement. Ce controle attrape ce cas, qui a
deja empeche l'application gelee de demarrer.

Qt tourne en mode offscreen : aucun affichage n'est requis, ce qui rend le
script utilisable sur un runner CI.

    python tools/check_imports.py
"""

import importlib
import os
import pkgutil
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import horizon  # noqa: E402


def main() -> None:
    # Certains widgets construisent des objets Qt au moment de l'import.
    app = QApplication([])

    failures: list[tuple[str, str]] = []
    for module in pkgutil.walk_packages(horizon.__path__, f"{horizon.__name__}."):
        try:
            importlib.import_module(module.name)
        except Exception:
            failures.append((module.name, traceback.format_exc()))

    del app

    for name, tb in failures:
        print(f"--- {name} ---\n{tb}", file=sys.stderr)

    if failures:
        sys.exit(f"{len(failures)} module(s) impossible(s) a importer")

    print("Tous les modules du paquet horizon s'importent.")


if __name__ == "__main__":
    main()
