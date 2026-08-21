import ctypes
import ctypes.wintypes

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from horizon.folder import FolderRepository
from horizon.image import ImageRepository
from horizon.note import NoteRepository, NoteVersionRepository
from horizon.note_task import NoteTaskRepository
from horizon.preferences import Preferences
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskRepository
from horizon.titlebar import TitleBar
from horizon.widgets.notes import NoteDetailWidget


class NoteWindow(QMainWindow):
    closed = Signal(int)  # emits note_id, once the body has been flushed to the database
    note_changed = Signal(int, int)  # emits (previous_note_id, new_note_id)

    def __init__(
        self,
        note_repo: NoteRepository,
        project_repo: ProjectRepository,
        folder_repo: FolderRepository,
        image_repo: ImageRepository | None,
        version_repo: NoteVersionRepository | None,
        prefs: Preferences,
        task_repo: TaskRepository | None = None,
        subtask_repo: SubtaskRepository | None = None,
        note_task_repo: NoteTaskRepository | None = None,
        sticky: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._prefs = prefs
        self._note_repo = note_repo
        self._project_repo = project_repo
        # Mode pense-bête : fenêtre réduite à l'éditeur, épinglée au-dessus des autres par
        # MainWindow (l'épinglage est un appel Win32, pas un flag Qt — voir app.py).
        self._sticky = sticky
        self._note_id: int | None = None

        self.setWindowIcon(QIcon(":/icons/Horizon_Icon.png"))
        w, h = prefs.sticky_note_window_size if sticky else prefs.note_window_size
        self.resize(w, h)

        self._note_detail = NoteDetailWidget(
            note_repo, project_repo, folder_repo,
            prefs=prefs,
            image_repo=image_repo,
            version_repo=version_repo,
            task_repo=task_repo,
            subtask_repo=subtask_repo,
            note_task_repo=note_task_repo,
            windowed=True,
            sticky=sticky,
        )
        self._note_detail.back_requested.connect(self.close)
        self._note_detail.note_link_clicked.connect(self.load_note)
        self._note_detail.title_changed.connect(self._on_title_changed)
        if sticky:
            # call_js() est inerte tant que CodeMirror n'a pas signalé qu'il est prêt, donc
            # le focus ne peut pas être posé juste après show().
            self._note_detail.editor_ready.connect(self._note_detail.focus_editor)

        self._title_bar = TitleBar(
            self, subtitle="Pense-bête" if sticky else "Note", show_search=False)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._title_bar)
        layout.addWidget(self._note_detail)
        self.setCentralWidget(container)

    def note_id(self) -> int | None:
        return self._note_id

    def load_note(self, note_id: int) -> None:
        note = self._note_repo.get(note_id)
        if note is None:
            return
        projects = self._project_repo.list_all()
        self._note_detail.load_note(note, projects)
        title = note.title or f"Note #{note_id}"
        self.setWindowTitle(f"{title} — Horizon")
        # Suivre un [[lien]] fait changer de note à la fenêtre : le registre de MainWindow
        # la référence encore sous l'ancien id, et c'est lui qui décide du verrou.
        previous, self._note_id = self._note_id, note_id
        if previous is not None and previous != note_id:
            self.note_changed.emit(previous, note_id)

    def _on_title_changed(self, title: str) -> None:
        self.setWindowTitle(f"{title} — Horizon")

    def closeEvent(self, event) -> None:
        self._note_detail.flush_and_save()
        if self._sticky:
            self._prefs.sticky_note_window_size = (self.width(), self.height())
        else:
            self._prefs.note_window_size = (self.width(), self.height())
        self._prefs.save()
        super().closeEvent(event)
        # Après flush_and_save : la fenêtre principale recharge depuis la base.
        if self._note_id is not None:
            self.closed.emit(self._note_id)

    def changeEvent(self, event) -> None:
        if event.type() == 105 and hasattr(self, "_title_bar"):  # QEvent.Type.WindowStateChange = 105
            maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized)
            self._title_bar.update_max_button(maximized)
        super().changeEvent(event)

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE
                if self.isMaximized():
                    b = (ctypes.windll.user32.GetSystemMetrics(32) +
                         ctypes.windll.user32.GetSystemMetrics(92))
                    rect = ctypes.wintypes.RECT.from_address(msg.lParam)
                    rect.left += b
                    rect.top += b
                    rect.right -= b
                    rect.bottom -= b
                return True, 0
            if msg.message == 0x0084:  # WM_NCHITTEST
                lp = msg.lParam
                x = ctypes.c_int16(lp & 0xFFFF).value
                y = ctypes.c_int16((lp >> 16) & 0xFFFF).value
                r = self.frameGeometry()
                if r.top() <= y < r.top() + 36 and x < r.right() - 138:
                    return True, 2  # HTCAPTION
                if not self.isMaximized():
                    b = 6
                    left   = x < r.left()   + b
                    right  = x > r.right()  - b
                    top    = y < r.top()    + b
                    bottom = y > r.bottom() - b
                    if top    and left:  return True, 13
                    if top    and right: return True, 14
                    if bottom and left:  return True, 16
                    if bottom and right: return True, 17
                    if left:             return True, 10
                    if right:            return True, 11
                    if top:              return True, 12
                    if bottom:           return True, 15
        return super().nativeEvent(event_type, message)
