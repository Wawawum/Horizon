from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter, QStackedWidget

from horizon.database import Database
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskRepository
from horizon.widgets import HomeWidget, ProjectDetailWidget, ProjectListWidget, RightPanelWidget


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        self._db = db
        super().__init__()
        self.setWindowTitle("Horizon")
        self.resize(800, 600)

        repo = ProjectRepository(db)
        task_repo = TaskRepository(db)
        subtask_repo = SubtaskRepository(db)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._project_list = ProjectListWidget(repo)
        splitter.addWidget(self._project_list)

        self._right_stack = QStackedWidget()

        self._home_widget = HomeWidget(task_repo, subtask_repo, repo)
        self._right_stack.addWidget(self._home_widget)     # index 0

        self._project_detail = ProjectDetailWidget(task_repo, repo, subtask_repo)
        self._right_stack.addWidget(self._project_detail)  # index 1

        splitter.addWidget(self._right_stack)

        self._right_panel = RightPanelWidget()
        splitter.addWidget(self._right_panel)

        splitter.setStretchFactor(0, 0)  # left panel keeps its natural width
        splitter.setStretchFactor(1, 1)  # center panel absorbs extra space
        splitter.setStretchFactor(2, 0)  # right panel keeps its natural width

        self._project_list.home_requested.connect(self._show_home)
        self._project_list.project_selected.connect(self._show_project)

        self._show_home()  # default view on startup

        self.setCentralWidget(splitter)

    def _show_home(self) -> None:
        self._home_widget.load()
        self._right_stack.setCurrentIndex(0)

    def _show_project(self, project) -> None:
        if project is None:
            self._show_home()
            return
        self._project_detail.load_project(project)
        self._right_stack.setCurrentIndex(1)
