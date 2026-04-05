from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter, QStackedWidget

from horizon.database import Database
from horizon.note import NoteRepository
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskRepository
from horizon.widgets import HomeWidget, NoteDetailWidget, NotesListWidget, ProjectDetailWidget, ProjectListWidget, RightPanelWidget


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        self._db = db
        super().__init__()
        self.setWindowTitle("Horizon")
        self.resize(800, 600)

        self._proj_repo = ProjectRepository(db)
        task_repo = TaskRepository(db)
        subtask_repo = SubtaskRepository(db)
        self._note_repo = NoteRepository(db)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._project_list = ProjectListWidget(self._proj_repo)
        splitter.addWidget(self._project_list)

        self._right_stack = QStackedWidget()

        self._home_widget = HomeWidget(task_repo, subtask_repo, self._proj_repo)
        self._right_stack.addWidget(self._home_widget)     # index 0

        self._project_detail = ProjectDetailWidget(task_repo, self._proj_repo, subtask_repo, self._note_repo)
        self._right_stack.addWidget(self._project_detail)  # index 1

        self._notes_list = NotesListWidget(self._note_repo, self._proj_repo)
        self._right_stack.addWidget(self._notes_list)      # index 2

        self._note_detail = NoteDetailWidget(self._note_repo, self._proj_repo)
        self._right_stack.addWidget(self._note_detail)     # index 3

        splitter.addWidget(self._right_stack)

        self._right_panel = RightPanelWidget()
        splitter.addWidget(self._right_panel)

        splitter.setStretchFactor(0, 0)  # left panel keeps its natural width
        splitter.setStretchFactor(1, 1)  # center panel absorbs extra space
        splitter.setStretchFactor(2, 0)  # right panel keeps its natural width

        self._project_list.home_requested.connect(self._show_home)
        self._project_list.project_selected.connect(self._show_project)
        self._project_list.notes_requested.connect(self._show_notes)
        self._notes_list.note_edit_requested.connect(self._show_note_detail)
        self._project_detail.note_edit_requested.connect(self._show_note_detail)
        self._project_detail.project_renamed.connect(self._project_list._load_projects)
        self._note_detail.back_requested.connect(self._show_notes)

        self._show_home()  # default view on startup

        self.setCentralWidget(splitter)

    def _show_home(self) -> None:
        self._project_list.clear_selection()
        self._home_widget.load()
        self._right_stack.setCurrentIndex(0)

    def _show_project(self, project) -> None:
        if project is None:
            self._show_home()
            return
        self._project_detail.load_project(project)
        self._right_stack.setCurrentIndex(1)

    def _show_notes(self) -> None:
        self._project_list.clear_selection()
        self._notes_list.load()
        self._right_stack.setCurrentIndex(2)

    def _show_note_detail(self, note_id: int) -> None:
        note = self._note_repo.get(note_id)
        if note is None:
            return
        projects = self._proj_repo.list_all()
        self._note_detail.load_note(note, projects)
        self._right_stack.setCurrentIndex(3)
