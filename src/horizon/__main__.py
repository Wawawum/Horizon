import sys

from PySide6.QtWidgets import QApplication, QMessageBox

import horizon.resources_rc  # enregistre les ressources Qt (:/fonts/..., :/icons/...)
from horizon.api_server import ApiServer
from horizon.app import MainWindow
from horizon.database import DB_PATH, Database
from horizon.preferences import Preferences
from horizon.single_instance import ActivationServer, acquire_mutex, notify_running_instance, release_mutex
from horizon.widgets.webeditor import register_image_scheme


def main() -> None:
    # Le mutex vit aussi longtemps que le processus ; Windows le libère à sa fin.
    mutex = acquire_mutex()
    if mutex is None:
        app = QApplication(sys.argv)
        # Horizon tourne déjà : on réaffiche sa fenêtre. Repli sur un avertissement si
        # l'instance existante ne répond pas (figée, ou ouverte dans une autre session).
        if not notify_running_instance():
            QMessageBox.warning(
                None,
                "Horizon est déjà ouvert",
                "Horizon est déjà en cours d'exécution.\n"
                "Vous ne pouvez pas lancer une seconde instance de l'application.",
            )
        sys.exit(0)

    prefs = Preferences()
    db = Database()
    register_image_scheme()  # avant QApplication : exigence de QtWebEngine
    app = QApplication(sys.argv)

    api = ApiServer(port=prefs.api_port, db_path=DB_PATH)
    api.start()

    window = MainWindow(db)
    window.show()

    activation = ActivationServer(app)
    activation.activationRequested.connect(window.bring_to_front)
    activation.listen()

    result = app.exec()

    api.stop()
    db.close()
    release_mutex(mutex)
    sys.exit(result)


if __name__ == "__main__":
    main()
