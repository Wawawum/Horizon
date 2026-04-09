from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QSplitter, QStackedWidget

from horizon import theme as _theme
from horizon.database import Database
from horizon.image import ImageRepository
from horizon.note import NoteRepository
from horizon.preferences import Preferences
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskRepository
from horizon.widgets import CalendarMeeting, HomeWidget, NoteDetailWidget, NotesListWidget, ProjectDetailWidget, ProjectListWidget, RightPanelWidget


def _build_meeting_note_body(meeting: CalendarMeeting) -> str:
    sections: list[str] = []
    if meeting.required_attendees:
        lines = ["**Required**"] + [f"- {name}" for name in meeting.required_attendees]
        sections.append("\n".join(lines))
    if meeting.optional_attendees:
        lines = ["**Optional**"] + [f"- {name}" for name in meeting.optional_attendees]
        sections.append("\n".join(lines))
    if not sections:
        return ""
    return "## Participants\n\n" + "\n\n".join(sections)


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        self._db = db
        self._prefs = Preferences()
        _theme.init(self._prefs.theme)
        super().__init__()
        self.setWindowTitle("Horizon")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "resources" / "Horizon_Icon.png")))
        w, h = self._prefs.window_size
        self.resize(w, h)
        if self._prefs.window_maximized:
            self.showMaximized()

        self._proj_repo = ProjectRepository(db)
        task_repo = TaskRepository(db)
        subtask_repo = SubtaskRepository(db)
        self._note_repo = NoteRepository(db)
        image_repo = ImageRepository(db)
        self._note_source: str = "notes"
        self._current_project = None

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._project_list = ProjectListWidget(self._proj_repo)
        self._splitter.addWidget(self._project_list)

        self._right_stack = QStackedWidget()

        self._home_widget = HomeWidget(task_repo, subtask_repo, self._proj_repo)
        self._right_stack.addWidget(self._home_widget)     # index 0

        self._project_detail = ProjectDetailWidget(task_repo, self._proj_repo, subtask_repo, self._note_repo, self._prefs)
        self._right_stack.addWidget(self._project_detail)  # index 1

        self._notes_list = NotesListWidget(self._note_repo, self._proj_repo)
        self._right_stack.addWidget(self._notes_list)      # index 2

        self._note_detail = NoteDetailWidget(self._note_repo, self._proj_repo, prefs=self._prefs, image_repo=image_repo)
        self._right_stack.addWidget(self._note_detail)     # index 3

        self._splitter.addWidget(self._right_stack)

        self._right_panel = RightPanelWidget()
        self._splitter.addWidget(self._right_panel)

        self._splitter.setStretchFactor(0, 0)  # left panel keeps its natural width
        self._splitter.setStretchFactor(1, 1)  # center panel absorbs extra space
        self._splitter.setStretchFactor(2, 0)  # right panel keeps its natural width

        self._right_panel.create_note_requested.connect(self._on_create_note_from_meeting)

        self._project_list.home_requested.connect(self._show_home)
        self._project_list.project_selected.connect(self._show_project)
        self._project_list.notes_requested.connect(self._show_notes)
        self._notes_list.note_edit_requested.connect(self._open_note_from_notes)
        self._project_detail.note_edit_requested.connect(self._open_note_from_project)
        self._project_detail.project_renamed.connect(self._project_list._load_projects)
        self._note_detail.back_requested.connect(self._go_back_from_note)

        self._show_home()  # default view on startup

        self.setCentralWidget(self._splitter)
        saved = self._prefs.splitter_sizes
        if saved:
            self._splitter.setSizes(saved)

    def _on_create_note_from_meeting(self, meeting: CalendarMeeting) -> None:
        subject = meeting.subject[:220]
        title = f"Meeting note - {subject} - {meeting.start.strftime('%Y-%m-%d %H:%M')}"
        body = _build_meeting_note_body(meeting)
        note = self._note_repo.create(project_id=None, title=title, body=body, dt=meeting.start)
        projects = self._proj_repo.list_all()
        self._note_detail.load_note(note, projects)
        self._right_stack.setCurrentIndex(3)

    def _show_home(self) -> None:
        self._project_list.clear_selection()
        self._home_widget.load()
        self._right_stack.setCurrentIndex(0)

    def _show_project(self, project) -> None:
        if project is None:
            self._show_home()
            return
        self._current_project = project
        self._project_detail.load_project(project)
        self._right_stack.setCurrentIndex(1)

    def _show_notes(self) -> None:
        self._project_list.clear_selection()
        self._notes_list.load()
        self._right_stack.setCurrentIndex(2)

    def _open_note_from_notes(self, note_id: int) -> None:
        self._note_source = "notes"
        self._show_note_detail(note_id)

    def _open_note_from_project(self, note_id: int) -> None:
        self._note_source = "project"
        self._show_note_detail(note_id)

    def _go_back_from_note(self) -> None:
        if self._note_source == "project" and self._current_project is not None:
            self._show_project(self._current_project)
        else:
            self._show_notes()

    def _show_note_detail(self, note_id: int) -> None:
        note = self._note_repo.get(note_id)
        if note is None:
            return
        projects = self._proj_repo.list_all()
        self._note_detail.load_note(note, projects)
        self._right_stack.setCurrentIndex(3)

    def closeEvent(self, event) -> None:
        self._prefs.window_maximized = self.isMaximized()
        if not self.isMaximized():
            self._prefs.window_size = (self.width(), self.height())
        self._prefs.splitter_sizes = self._splitter.sizes()
        self._prefs.save()
        super().closeEvent(event)
