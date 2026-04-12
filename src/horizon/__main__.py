import sys

from PySide6.QtWidgets import QApplication

import horizon.resources_rc  # enregistre les ressources Qt (:/fonts/..., :/icons/...)
from horizon.app import MainWindow
from horizon.database import Database


def main() -> None:
    db = Database()
    app = QApplication(sys.argv)
    window = MainWindow(db)
    window.show()
    result = app.exec()
    db.close()
    sys.exit(result)


if __name__ == "__main__":
    main()
