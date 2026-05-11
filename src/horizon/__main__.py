import sys

from PySide6.QtWidgets import QApplication

import horizon.resources_rc  # enregistre les ressources Qt (:/fonts/..., :/icons/...)
from horizon.api_server import ApiServer
from horizon.app import MainWindow
from horizon.database import DB_PATH, Database
from horizon.preferences import Preferences


def main() -> None:
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
    sys.exit(result)


if __name__ == "__main__":
    main()
