import ctypes
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

import horizon.resources_rc  # enregistre les ressources Qt (:/fonts/..., :/icons/...)
from horizon.api_server import ApiServer
from horizon.app import MainWindow
from horizon.database import DB_PATH, Database
from horizon.preferences import Preferences

# Nom global (toutes sessions Windows) : une seule instance d'Horizon, quel que soit
# le dépôt ou l'environnement virtuel depuis lequel elle est lancée.
_SINGLE_INSTANCE_MUTEX_NAME = "Global\\Horizon-SingleInstance-Mutex"
_ERROR_ALREADY_EXISTS = 183

# use_last_error=True : le code d'erreur est capturé juste après CreateMutexW,
# sans qu'un autre appel Win32 puisse l'écraser.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def main() -> None:
    # Le mutex vit aussi longtemps que le processus ; Windows le libère à sa fin.
    mutex = _kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        app = QApplication(sys.argv)
        QMessageBox.warning(
            None,
            "Horizon est déjà ouvert",
            "Horizon est déjà en cours d'exécution.\n"
            "Vous ne pouvez pas lancer une seconde instance de l'application.",
        )
        sys.exit(0)

    prefs = Preferences()
    db = Database()
    app = QApplication(sys.argv)

    api = ApiServer(port=prefs.api_port, db_path=DB_PATH)
    api.start()

    window = MainWindow(db)
    window.show()
    result = app.exec()

    api.stop()
    db.close()
    _kernel32.CloseHandle(mutex)
    sys.exit(result)


if __name__ == "__main__":
    main()
