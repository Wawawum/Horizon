from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter

from horizon.database import Database
from horizon.project import ProjectRepository
from horizon.widgets import ProjectListWidget


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        self._db = db
        super().__init__()
        self.setWindowTitle("Horizon")
        self.resize(800, 600)

        repo = ProjectRepository(db)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._project_list = ProjectListWidget(repo)
        splitter.addWidget(self._project_list)

        placeholder = QLabel("Select a project")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        splitter.addWidget(placeholder)

        splitter.setStretchFactor(0, 0)  # left panel keeps its natural width
        splitter.setStretchFactor(1, 1)  # right panel absorbs extra space

        self.setCentralWidget(splitter)
