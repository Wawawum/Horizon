from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter

from horizon.database import Database
from horizon.project import ProjectRepository
from horizon.widgets import ProjectDetailWidget, ProjectListWidget


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

        self._project_detail = ProjectDetailWidget()
        splitter.addWidget(self._project_detail)

        self._project_list.project_selected.connect(self._project_detail.load_project)

        splitter.setStretchFactor(0, 0)  # left panel keeps its natural width
        splitter.setStretchFactor(1, 1)  # right panel absorbs extra space

        self.setCentralWidget(splitter)
