import ctypes
import ctypes.wintypes

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.database import Database
from horizon.folder import FolderRepository
from horizon.image import ImageRepository
from horizon.note import NoteRepository, NoteVersionRepository
from horizon.preferences import Preferences
from horizon.project import ProjectRepository
from horizon.search import SearchRepository
from horizon.tag import TagRepository
from horizon.task import SubtaskRepository, TaskRepository
from horizon.titlebar import TitleBar
from horizon.widgets import CalendarMeeting, HomeWidget, NoteDetailWidget, NotesListWidget, ProjectDetailWidget, ProjectListWidget, RightPanelWidget, SearchResultsWidget
from horizon.widgets.tags import TagsWidget
from horizon.deliverable import DeliverableRepository
from horizon.deliverable_template import DeliverableTemplateRepository
from horizon.widgets.deliverables import (
    DeliverablesWidget,
    DeliverableDetailWidget,
    DeliverableTemplatesListWidget,
    DeliverableTemplateDetailWidget,
)
from horizon.widgets.media import MediaWidget
from horizon.toast import ToastNotification
from horizon.pin_border import PinBorderOverlay
from horizon.note_window import NoteWindow

# ── Pin-window hotkey Win32 constants ─────────────────────────────────────────
_WM_HOTKEY      = 0x0312
_MOD_ALT        = 0x0001
_MOD_CONTROL    = 0x0002
_MOD_SHIFT      = 0x0004
_MOD_WIN        = 0x0008
_GWL_EXSTYLE    = -20
_WS_EX_TOPMOST  = 0x00000008
_HWND_TOPMOST   = ctypes.c_void_p(-1)
_HWND_NOTOPMOST = ctypes.c_void_p(-2)
_SWP_NOSIZE     = 0x0001
_SWP_NOMOVE     = 0x0002
_SWP_NOACTIVATE = 0x0010
_PIN_HOTKEY_ID  = 1

_MOD_MAP = {"alt": _MOD_ALT, "ctrl": _MOD_CONTROL, "shift": _MOD_SHIFT, "win": _MOD_WIN}


def _modifiers_to_flags(modifiers: list[str]) -> int:
    result = 0
    for m in modifiers:
        result |= _MOD_MAP.get(m.lower(), 0)
    return result


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
        QApplication.instance().setStyleSheet(_theme.make_stylesheet(_theme.current()))
        QFontDatabase.addApplicationFont(":/fonts/JetBrainsMono-Regular.ttf")
        app_font = QFont(_theme.current().font_family)
        app_font.setPointSize(9)
        QApplication.instance().setFont(app_font)
        super().__init__()
        # Keep WS_OVERLAPPEDWINDOW (includes WS_THICKFRAME + WS_CAPTION) so that
        # Windows Aero snap and Win+arrow shortcuts work. The native title bar and
        # borders are hidden by returning 0 in WM_NCCALCSIZE (see nativeEvent).
        self.setWindowIcon(QIcon(":/icons/Horizon_Icon.png"))
        w, h = self._prefs.window_size
        self.resize(w, h)
        if self._prefs.window_maximized:
            self.showMaximized()

        self._proj_repo = ProjectRepository(db)
        task_repo = TaskRepository(db)
        self._task_repo = task_repo
        subtask_repo = SubtaskRepository(db)
        self._subtask_repo = subtask_repo
        self._note_repo = NoteRepository(db)
        self._note_version_repo = NoteVersionRepository(db)
        self._folder_repo = FolderRepository(db)
        self._tag_repo = TagRepository(db)
        image_repo = ImageRepository(db)
        self._image_repo = image_repo
        self._search_repo = SearchRepository(db)
        self._note_windows: dict[int, NoteWindow] = {}
        self._tmpl_repo = DeliverableTemplateRepository(db)
        self._deliverable_repo = DeliverableRepository(db)
        self._note_source: str = "notes"
        self._current_project = None

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._project_list = ProjectListWidget(self._proj_repo)
        self._splitter.addWidget(self._project_list)

        self._right_stack = QStackedWidget()

        self._home_widget = HomeWidget(task_repo, subtask_repo, self._proj_repo)
        self._right_stack.addWidget(self._home_widget)     # index 0

        self._project_detail = ProjectDetailWidget(task_repo, self._proj_repo, subtask_repo, self._note_repo, self._folder_repo, self._deliverable_repo, self._tmpl_repo, self._prefs)
        self._right_stack.addWidget(self._project_detail)  # index 1

        self._notes_list = NotesListWidget(self._note_repo, self._proj_repo)
        self._right_stack.addWidget(self._notes_list)      # index 2

        self._note_detail = NoteDetailWidget(
            self._note_repo, self._proj_repo, self._folder_repo,
            prefs=self._prefs, image_repo=image_repo,
            version_repo=self._note_version_repo,
        )
        self._right_stack.addWidget(self._note_detail)     # index 3

        self._search_results = SearchResultsWidget()
        self._right_stack.addWidget(self._search_results)  # index 4

        self._tags_widget = TagsWidget(self._tag_repo, self._note_repo, self._proj_repo, self._folder_repo)
        self._right_stack.addWidget(self._tags_widget)     # index 5

        self._deliverables_widget = DeliverablesWidget(self._deliverable_repo, self._proj_repo)
        self._right_stack.addWidget(self._deliverables_widget)   # index 6

        self._templates_list = DeliverableTemplatesListWidget(self._tmpl_repo)
        self._right_stack.addWidget(self._templates_list)         # index 7

        self._template_detail = DeliverableTemplateDetailWidget(self._tmpl_repo, image_repo)
        self._right_stack.addWidget(self._template_detail)        # index 8

        self._deliverable_detail = DeliverableDetailWidget(self._deliverable_repo, image_repo)
        self._right_stack.addWidget(self._deliverable_detail)     # index 9

        self._media_widget = MediaWidget(image_repo, self._search_repo, self._note_repo, self._proj_repo)
        self._right_stack.addWidget(self._media_widget)           # index 10

        self._splitter.addWidget(self._right_stack)

        self._right_panel = RightPanelWidget()
        self._splitter.addWidget(self._right_panel)

        self._splitter.setStretchFactor(0, 0)  # left panel keeps its natural width
        self._splitter.setStretchFactor(1, 1)  # center panel absorbs extra space
        self._splitter.setStretchFactor(2, 0)  # right panel keeps its natural width

        self._right_panel.create_note_requested.connect(self._on_create_note_from_meeting)
        self._search_results.note_requested.connect(self._open_note_from_notes)
        self._search_results.task_requested.connect(self._on_task_from_search)
        self._search_results.project_requested.connect(self._on_project_from_search)

        self._project_list.home_requested.connect(self._show_home)
        self._project_list.project_selected.connect(self._show_project)
        self._project_list.notes_requested.connect(self._show_notes)
        self._project_list.tags_requested.connect(self._show_tags)
        self._project_list.deliverables_requested.connect(self._show_deliverables)
        self._project_list.media_requested.connect(self._show_media)
        self._media_widget.note_open_requested.connect(self._open_note_from_media)
        self._notes_list.note_edit_requested.connect(self._open_note_from_notes)
        self._notes_list.note_open_in_window_requested.connect(self._open_note_in_window)
        self._tags_widget.note_edit_requested.connect(self._open_note_from_tags)
        self._project_detail.note_edit_requested.connect(self._open_note_from_project)
        self._project_detail.deliverable_edit_requested.connect(self._open_deliverable_from_project)
        self._project_detail.project_renamed.connect(self._project_list._load_projects)
        self._note_detail.back_requested.connect(self._go_back_from_note)
        self._note_detail.note_link_clicked.connect(self._show_note_detail)
        self._note_detail.open_in_window_requested.connect(self._open_note_in_window)
        self._deliverable_detail.back_requested.connect(self._go_back_from_deliverable)
        self._deliverables_widget.show_templates_requested.connect(self._show_templates_list)
        self._deliverables_widget.deliverable_edit_requested.connect(self._open_deliverable_from_list)
        self._templates_list.back_requested.connect(self._show_deliverables)
        self._templates_list.template_edit_requested.connect(self._open_template)
        self._template_detail.back_requested.connect(self._show_templates_list)

        self._show_home()  # default view on startup

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self._title_bar = TitleBar(self, show_search=True)
        self._title_bar.search_requested.connect(self._on_search)
        container_layout.addWidget(self._title_bar)
        container_layout.addWidget(self._splitter)

        self.setCentralWidget(container)
        saved = self._prefs.splitter_sizes
        if saved:
            self._splitter.setSizes(saved)

        self._pin_toast: ToastNotification | None = None
        self._pin_borders: dict[int, PinBorderOverlay] = {}
        self._register_pin_hotkey()

    def _register_pin_hotkey(self) -> None:
        hk = self._prefs.pin_hotkey
        mods = _modifiers_to_flags(hk["modifiers"])
        vk = hk["vk"]
        hwnd = int(self.winId())
        ctypes.windll.user32.UnregisterHotKey(hwnd, _PIN_HOTKEY_ID)
        ok = ctypes.windll.user32.RegisterHotKey(hwnd, _PIN_HOTKEY_ID, mods, vk)
        if not ok:
            import sys
            print(
                f"[Horizon] Avertissement : impossible d'enregistrer le raccourci "
                f"(modifiers={mods:#x}, vk={vk}). Un autre programme utilise peut-être cette combinaison.",
                file=sys.stderr,
            )

    def _on_pin_hotkey(self) -> None:
        user32 = ctypes.windll.user32
        target = user32.GetForegroundWindow()
        if not target:
            return
        ex_style = user32.GetWindowLongW(target, _GWL_EXSTYLE)
        if ex_style & _WS_EX_TOPMOST:
            # Unpin: remove topmost and destroy the border overlay
            user32.SetWindowPos(target, _HWND_NOTOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
            overlay = self._pin_borders.pop(target, None)
            if overlay is not None:
                try:
                    overlay.close()
                except RuntimeError:
                    pass
            label = "Désépinglé"
        else:
            # Pin: set topmost and create the border overlay
            user32.SetWindowPos(target, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
            # Replace any stale overlay for this HWND
            old = self._pin_borders.pop(target, None)
            if old is not None:
                try:
                    old.close()
                except RuntimeError:
                    pass
            self._pin_borders[target] = PinBorderOverlay(target)
            label = "Épinglé"
        if self._pin_toast is not None:
            try:
                self._pin_toast.close()
            except RuntimeError:
                pass
        self._pin_toast = ToastNotification(label)

    def _on_search(self, query: str, mode: str = "all") -> None:
        results = self._search_repo.search(query, mode)
        self._search_results.load_results(query, results)
        self._right_stack.setCurrentIndex(4)

    def _on_project_from_search(self, project_id: int) -> None:
        self._show_project(self._proj_repo.get(project_id))

    def _on_task_from_search(self, task_id: int) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        project = self._proj_repo.get(task.project_id)
        if project is None:
            return
        self._show_project(project)
        self._project_detail.open_task(task_id)

    def _on_create_note_from_meeting(self, meeting: CalendarMeeting) -> None:
        subject = meeting.subject[:220]
        title = f"{meeting.start.strftime('%Y-%m-%d')} {subject}"
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

    def _show_tags(self) -> None:
        self._project_list.clear_selection()
        self._tags_widget.load()
        self._right_stack.setCurrentIndex(5)

    def _show_deliverables(self) -> None:
        self._project_list.clear_selection()
        self._deliverables_widget.load()
        self._right_stack.setCurrentIndex(6)

    def _show_media(self) -> None:
        self._project_list.clear_selection()
        self._media_widget.load()
        self._right_stack.setCurrentIndex(10)

    def _open_note_from_media(self, note_id: int) -> None:
        self._note_source = "media"
        self._show_note_detail(note_id)

    def _show_templates_list(self) -> None:
        self._project_list.clear_selection()
        self._templates_list.load()
        self._right_stack.setCurrentIndex(7)

    def _open_template(self, template_id: int) -> None:
        tmpl = self._tmpl_repo.get(template_id)
        if tmpl is None:
            return
        self._template_detail.load_template(tmpl)
        self._right_stack.setCurrentIndex(8)

    def _open_note_from_notes(self, note_id: int) -> None:
        self._note_source = "notes"
        self._show_note_detail(note_id)

    def _open_note_from_project(self, note_id: int) -> None:
        self._note_source = "project"
        self._show_note_detail(note_id)

    def _open_note_from_tags(self, note_id: int) -> None:
        self._note_source = "tags"
        self._show_note_detail(note_id)

    def _go_back_from_note(self) -> None:
        if self._note_source == "project" and self._current_project is not None:
            self._show_project(self._current_project)
        elif self._note_source == "tags":
            self._show_tags()
        elif self._note_source == "media":
            self._show_media()
        else:
            self._show_notes()

    def _show_note_detail(self, note_id: int) -> None:
        note = self._note_repo.get(note_id)
        if note is None:
            return
        projects = self._proj_repo.list_all()
        self._note_detail.load_note(note, projects)
        self._right_stack.setCurrentIndex(3)

    def _open_note_in_window(self, note_id: int) -> None:
        if note_id in self._note_windows:
            win = self._note_windows[note_id]
            win.raise_()
            win.activateWindow()
            return
        win = NoteWindow(
            self._note_repo, self._proj_repo, self._folder_repo,
            self._image_repo, self._note_version_repo, self._prefs,
        )
        win.load_note(note_id)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.destroyed.connect(lambda _, nid=note_id: self._note_windows.pop(nid, None))
        self._note_windows[note_id] = win
        win.show()

    def _open_deliverable_from_project(self, deliverable_id: int) -> None:
        self._deliverable_source = "project"
        deliverable = self._deliverable_repo.get(deliverable_id)
        if deliverable is None:
            return
        self._deliverable_detail.load_deliverable(deliverable)
        self._right_stack.setCurrentIndex(9)

    def _open_deliverable_from_list(self, deliverable_id: int) -> None:
        self._deliverable_source = "list"
        deliverable = self._deliverable_repo.get(deliverable_id)
        if deliverable is None:
            return
        self._deliverable_detail.load_deliverable(deliverable)
        self._right_stack.setCurrentIndex(9)

    def _go_back_from_deliverable(self) -> None:
        if getattr(self, "_deliverable_source", "project") == "list":
            self._show_deliverables()
        elif self._current_project is not None:
            self._show_project(self._current_project)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_title_bar"):
            maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized)
            self._title_bar.update_max_button(maximized)
        super().changeEvent(event)

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY and msg.wParam == _PIN_HOTKEY_ID:
                self._on_pin_hotkey()
                return True, 0
            if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE — hide native frame
                if self.isMaximized():
                    # When maximized with WS_THICKFRAME, Windows offsets the window by the
                    # frame border width to hide the resize handles off-screen. Compensate
                    # so the client area fills the monitor work area exactly.
                    b = (ctypes.windll.user32.GetSystemMetrics(32) +
                         ctypes.windll.user32.GetSystemMetrics(92))  # SM_CXSIZEFRAME + SM_CXPADDEDBORDER
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
                # Title bar zone (exclude rightmost 138px reserved for the 3 control buttons)
                if r.top() <= y < r.top() + 36 and x < r.right() - 138:
                    # Exclude interactive titlebar widgets so they receive normal mouse events
                    if hasattr(self, "_title_bar"):
                        for widget in (self._title_bar._search_edit, self._title_bar._search_mode):
                            if widget is not None:
                                wpos = widget.mapToGlobal(QPoint(0, 0))
                                if wpos.x() <= x < wpos.x() + widget.width():
                                    return True, 1  # HTCLIENT
                    return True, 2  # HTCAPTION — enables Win+arrows and Aero snap
                if not self.isMaximized():
                    b = 6  # resize border width in pixels
                    left   = x < r.left()   + b
                    right  = x > r.right()  - b
                    top    = y < r.top()    + b
                    bottom = y > r.bottom() - b
                    if top    and left:  return True, 13  # HTTOPLEFT
                    if top    and right: return True, 14  # HTTOPRIGHT
                    if bottom and left:  return True, 16  # HTBOTTOMLEFT
                    if bottom and right: return True, 17  # HTBOTTOMRIGHT
                    if left:             return True, 10  # HTLEFT
                    if right:            return True, 11  # HTRIGHT
                    if top:              return True, 12  # HTTOP
                    if bottom:           return True, 15  # HTBOTTOM
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event) -> None:
        ctypes.windll.user32.UnregisterHotKey(int(self.winId()), _PIN_HOTKEY_ID)
        for overlay in list(self._pin_borders.values()):
            try:
                overlay.close()
            except RuntimeError:
                pass
        self._pin_borders.clear()
        self._prefs.window_maximized = self.isMaximized()
        if not self.isMaximized():
            self._prefs.window_size = (self.width(), self.height())
        self._prefs.splitter_sizes = self._splitter.sizes()
        self._prefs.save()
        super().closeEvent(event)
