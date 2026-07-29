import ctypes
import ctypes.wintypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.folder import FolderRepository
from horizon.image import ImageRepository
from horizon.note import NoteRepository, NoteVersionRepository
from horizon.preferences import Preferences
from horizon.project import ProjectRepository
from horizon.titlebar import TitleBar
from horizon.widgets.notes import NoteDetailWidget

_GWL_EXSTYLE    = -20
_WS_EX_TOPMOST  = 0x00000008


class NoteWindow(QMainWindow):
    def __init__(
        self,
        note_repo: NoteRepository,
        project_repo: ProjectRepository,
        folder_repo: FolderRepository,
        image_repo: ImageRepository | None,
        version_repo: NoteVersionRepository | None,
        prefs: Preferences,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._prefs = prefs
        self._note_repo = note_repo
        self._project_repo = project_repo

        self.setWindowIcon(QIcon(":/icons/Horizon_Icon.png"))
        w, h = prefs.note_window_size
        self.resize(w, h)

        self._note_detail = NoteDetailWidget(
            note_repo, project_repo, folder_repo,
            prefs=prefs,
            image_repo=image_repo,
            version_repo=version_repo,
            windowed=True,
        )
        self._note_detail.back_requested.connect(self.close)
        self._note_detail.note_link_clicked.connect(self.load_note)
        self._note_detail.title_changed.connect(self._on_title_changed)

        self._title_bar = TitleBar(self, subtitle="Note", show_search=False)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._title_bar)
        layout.addWidget(self._note_detail)
        self.setCentralWidget(container)

    def load_note(self, note_id: int) -> None:
        note = self._note_repo.get(note_id)
        if note is None:
            return
        projects = self._project_repo.list_all()
        self._note_detail.load_note(note, projects)
        title = note.title or f"Note #{note_id}"
        self.setWindowTitle(f"{title} — Horizon")

    def _on_title_changed(self, title: str) -> None:
        self.setWindowTitle(f"{title} — Horizon")

    def closeEvent(self, event) -> None:
        self._note_detail.flush_and_save()
        self._prefs.note_window_size = (self.width(), self.height())
        self._prefs.save()
        super().closeEvent(event)

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
