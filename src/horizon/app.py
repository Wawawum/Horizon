import ctypes
import ctypes.wintypes

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.database import Database
from horizon.document import DocumentRepository
from horizon.folder import FolderRepository
from horizon.image import ImageRepository
from horizon.note import NoteRepository, NoteVersionRepository
from horizon.note_task import NoteTaskRepository
from horizon.preferences import Preferences
from horizon.project import ProjectRepository
from horizon.search import SearchRepository
from horizon.tag import TagRepository
from horizon.task import SubtaskRepository, TaskRepository
from horizon.titlebar import TitleBar, native_hit_test
from horizon.widgets import CalendarMeeting, CommandBar, HomeWidget, NoteDetailWidget, NotesListWidget, ProjectDetailWidget, ProjectListWidget, RightPanelWidget, SearchResultsWidget
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
from horizon.archimate import ArchimateModelRepository
from horizon.widgets.archimate import ArchimateWidget
from horizon.widgets.debug_drop import DebugDropWidget
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
        _theme.init()
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
        self._note_task_repo = NoteTaskRepository(db)
        self._folder_repo = FolderRepository(db)
        self._tag_repo = TagRepository(db)
        image_repo = ImageRepository(db)
        self._image_repo = image_repo
        self._search_repo = SearchRepository(db)
        # Une note a au plus une fenêtre détachée, pense-bête ou non : deux éditeurs
        # concurrents sur la même note divergeraient l'un de l'autre.
        self._note_windows: dict[int, NoteWindow] = {}
        self._tmpl_repo = DeliverableTemplateRepository(db)
        self._deliverable_repo = DeliverableRepository(db)
        self._archimate_repo = ArchimateModelRepository(db)
        self._document_repo = DocumentRepository(db)
        self._note_source: str = "notes"
        self._current_project = None

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._project_list = ProjectListWidget(self._proj_repo)
        self._splitter.addWidget(self._project_list)

        self._right_stack = QStackedWidget()

        self._home_widget = HomeWidget(task_repo, subtask_repo, self._proj_repo)
        self._right_stack.addWidget(self._home_widget)     # index 0

        self._project_detail = ProjectDetailWidget(task_repo, self._proj_repo, subtask_repo, self._note_repo, self._folder_repo, self._deliverable_repo, self._tmpl_repo, self._document_repo, self._prefs)
        self._right_stack.addWidget(self._project_detail)  # index 1

        self._notes_list = NotesListWidget(self._note_repo, self._proj_repo)
        self._right_stack.addWidget(self._notes_list)      # index 2

        self._note_detail = NoteDetailWidget(
            self._note_repo, self._proj_repo, self._folder_repo,
            prefs=self._prefs, image_repo=image_repo,
            version_repo=self._note_version_repo,
            task_repo=task_repo, subtask_repo=subtask_repo,
            note_task_repo=self._note_task_repo,
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

        self._template_detail = DeliverableTemplateDetailWidget(self._tmpl_repo, image_repo, prefs=self._prefs)
        self._right_stack.addWidget(self._template_detail)        # index 8

        self._deliverable_detail = DeliverableDetailWidget(self._deliverable_repo, image_repo, prefs=self._prefs)
        self._right_stack.addWidget(self._deliverable_detail)     # index 9

        self._media_widget = MediaWidget(image_repo, self._search_repo, self._note_repo, self._proj_repo)
        self._right_stack.addWidget(self._media_widget)           # index 10

        self._archimate_widget = ArchimateWidget(self._archimate_repo, self._prefs)
        self._right_stack.addWidget(self._archimate_widget)       # index 11

        self._debug_widget = DebugDropWidget()
        self._right_stack.addWidget(self._debug_widget)           # index 12

        self._splitter.addWidget(self._right_stack)

        self._right_panel = RightPanelWidget()
        self._splitter.addWidget(self._right_panel)

        self._splitter.setStretchFactor(0, 0)  # left panel keeps its natural width
        self._splitter.setStretchFactor(1, 1)  # center panel absorbs extra space
        self._splitter.setStretchFactor(2, 0)  # right panel keeps its natural width

        self._command_bar = CommandBar()

        self._right_panel.create_note_requested.connect(self._on_create_note_from_meeting)
        self._search_results.note_requested.connect(self._open_note_from_notes)
        self._search_results.task_requested.connect(self._on_task_from_search)
        self._search_results.project_requested.connect(self._on_project_from_search)

        self._command_bar.home_requested.connect(self._show_home)
        self._project_list.project_selected.connect(self._show_project)
        self._command_bar.notes_requested.connect(self._show_notes)
        self._command_bar.tags_requested.connect(self._show_tags)
        self._command_bar.deliverables_requested.connect(self._show_deliverables)
        self._command_bar.media_requested.connect(self._show_media)
        self._command_bar.archimate_requested.connect(self._show_archimate)
        self._command_bar.debug_requested.connect(self._show_debug)
        self._command_bar.search_requested.connect(self._on_search)
        self._media_widget.note_open_requested.connect(self._open_note_from_media)
        self._notes_list.note_edit_requested.connect(self._open_note_from_notes)
        self._notes_list.note_open_in_window_requested.connect(self._open_note_in_window)
        self._tags_widget.note_edit_requested.connect(self._open_note_from_tags)
        self._project_detail.note_edit_requested.connect(self._open_note_from_project)
        self._project_detail.deliverable_edit_requested.connect(self._open_deliverable_from_project)
        self._project_detail.document_open_requested.connect(self._open_document_url)
        self._project_detail.project_renamed.connect(self._project_list._load_projects)
        self._note_detail.back_requested.connect(self._go_back_from_note)
        self._note_detail.note_link_clicked.connect(self._show_note_detail)
        self._note_detail.open_in_window_requested.connect(self._open_note_in_window)
        self._note_detail.open_as_sticky_requested.connect(self._open_note_as_sticky)
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

        self._title_bar = TitleBar(self, subtitle="workspace")
        container_layout.addWidget(self._title_bar)
        container_layout.addWidget(self._command_bar)
        container_layout.addWidget(self._splitter, stretch=1)

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

    def _close_pin_border(self, hwnd: int) -> None:
        overlay = self._pin_borders.pop(hwnd, None)
        if overlay is not None:
            try:
                overlay.close()
            except RuntimeError:
                pass

    def _pin_hwnd(self, hwnd: int) -> None:
        """Passe la fenêtre au-dessus des autres et dessine la bordure d'accent."""
        ctypes.windll.user32.SetWindowPos(
            hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
        self._close_pin_border(hwnd)  # remplace un overlay resté d'un épinglage précédent
        self._pin_borders[hwnd] = PinBorderOverlay(hwnd)

    def _unpin_hwnd(self, hwnd: int) -> None:
        ctypes.windll.user32.SetWindowPos(
            hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
        self._close_pin_border(hwnd)

    def _on_pin_hotkey(self) -> None:
        user32 = ctypes.windll.user32
        target = user32.GetForegroundWindow()
        if not target:
            return
        if user32.GetWindowLongW(target, _GWL_EXSTYLE) & _WS_EX_TOPMOST:
            self._unpin_hwnd(target)
            label = "Désépinglé"
        else:
            self._pin_hwnd(target)
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
        self._load_note_into_detail(note)
        self._right_stack.setCurrentIndex(3)

    def _show_home(self) -> None:
        self._project_list.clear_selection()
        self._command_bar.set_active("board")
        self._home_widget.load()
        self._right_stack.setCurrentIndex(0)

    def _show_project(self, project) -> None:
        if project is None:
            self._show_home()
            return
        self._current_project = project
        self._command_bar.clear_active()
        self._project_detail.load_project(project)
        self._right_stack.setCurrentIndex(1)

    def _show_notes(self) -> None:
        self._project_list.clear_selection()
        self._command_bar.set_active("notes")
        self._notes_list.load()
        self._right_stack.setCurrentIndex(2)

    def _show_tags(self) -> None:
        self._project_list.clear_selection()
        self._command_bar.set_active("tags")
        self._tags_widget.load()
        self._right_stack.setCurrentIndex(5)

    def _show_deliverables(self) -> None:
        self._project_list.clear_selection()
        self._command_bar.set_active("deliverables")
        self._deliverables_widget.load()
        self._right_stack.setCurrentIndex(6)

    def _show_media(self) -> None:
        self._project_list.clear_selection()
        self._command_bar.set_active("media")
        self._media_widget.load()
        self._right_stack.setCurrentIndex(10)

    def _show_archimate(self) -> None:
        self._project_list.clear_selection()
        self._command_bar.set_active("archimate")
        self._archimate_widget.load()
        self._right_stack.setCurrentIndex(11)

    def _show_debug(self) -> None:
        self._project_list.clear_selection()
        self._command_bar.set_active("debug")
        self._debug_widget.load()
        self._right_stack.setCurrentIndex(12)

    def _open_note_from_media(self, note_id: int) -> None:
        self._note_source = "media"
        self._show_note_detail(note_id)

    def _show_templates_list(self) -> None:
        self._project_list.clear_selection()
        self._command_bar.set_active("deliverables")
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

    def _open_document_url(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

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

    def _load_note_into_detail(self, note) -> None:
        """Charge une note dans le panneau principal en recalculant son verrou.

        Le déverrouillage précède load_note : _apply_readonly lit _locked, donc un verrou
        laissé par la note précédente s'afficherait sur la nouvelle.
        """
        self._note_detail.set_locked(False)
        self._note_detail.load_note(note, self._proj_repo.list_all())
        self._note_detail.set_locked(note.id in self._note_windows)

    def _show_note_detail(self, note_id: int) -> None:
        note = self._note_repo.get(note_id)
        if note is None:
            return
        self._load_note_into_detail(note)
        self._right_stack.setCurrentIndex(3)

    def _refresh_note_lock(self, note_id: int) -> None:
        """Aligne le verrou du panneau principal sur la présence d'une fenêtre détachée."""
        if self._note_detail.current_note_id == note_id:
            self._note_detail.set_locked(note_id in self._note_windows)

    def _open_note_window(self, note_id: int, sticky: bool) -> NoteWindow | None:
        """Ouvre la fenêtre détachée de `note_id`, ou ramène l'existante au premier plan.

        Retourne None dans ce second cas, pour que l'appelant n'ait pas à refaire son
        travail d'installation. Une fenêtre déjà ouverte l'emporte sur le mode demandé :
        un second éditeur sur la même note rouvrirait la divergence que le verrou ferme.
        """
        existing = self._note_windows.get(note_id)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return None
        win = NoteWindow(
            self._note_repo, self._proj_repo, self._folder_repo,
            self._image_repo, self._note_version_repo, self._prefs,
            task_repo=self._task_repo, subtask_repo=self._subtask_repo,
            note_task_repo=self._note_task_repo,
            sticky=sticky,
        )
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.closed.connect(self._on_note_window_closed)
        win.note_changed.connect(self._on_note_window_note_changed)
        # Filet pour une destruction sans closeEvent. Par identité et non par id de note :
        # après un [[lien]] la fenêtre a changé de clé, et une clé périmée retirerait du
        # registre une autre fenêtre légitimement rouverte entre-temps.
        win.destroyed.connect(lambda _=None, w=win: self._forget_note_window(w))
        self._note_windows[note_id] = win
        # Avant load_note : le verrou déclenche un flush du panneau principal, sans quoi la
        # fenêtre relirait un corps périmé depuis la base.
        self._refresh_note_lock(note_id)
        win.load_note(note_id)
        win.show()
        return win

    def _forget_note_window(self, win) -> None:
        """Retire `win` du registre. Comparaison d'identité seule : l'objet C++ est mort."""
        for note_id, existing in list(self._note_windows.items()):
            if existing is win:
                del self._note_windows[note_id]

    def _on_note_window_closed(self, note_id: int) -> None:
        self._note_windows.pop(note_id, None)
        if self._note_detail.current_note_id == note_id:
            self._note_detail.set_locked(False)
            note = self._note_repo.get(note_id)
            if note is not None:
                self._note_detail.load_note(note, self._proj_repo.list_all())
        # Le titre a pu changer dans la fenêtre : rafraîchir la liste affichée.
        index = self._right_stack.currentIndex()
        if index == 2:
            self._notes_list.load()
        elif index == 1 and self._current_project is not None:
            self._project_detail.load_project(self._current_project)

    def _on_note_window_note_changed(self, old_id: int, new_id: int) -> None:
        win = self._note_windows.pop(old_id, None)
        if win is not None:
            self._note_windows[new_id] = win
        self._refresh_note_lock(old_id)  # l'ancienne note se libère
        self._refresh_note_lock(new_id)  # la nouvelle se verrouille

    def _open_note_in_window(self, note_id: int) -> None:
        self._open_note_window(note_id, sticky=False)

    def _open_note_as_sticky(self, note_id: int) -> None:
        win = self._open_note_window(note_id, sticky=True)
        if win is None:
            return
        hwnd = int(win.winId())
        # L'épinglage attend un tour de boucle : PinBorderOverlay lit la géométrie native
        # de la fenêtre, qui n'est pas encore posée au retour de show().
        QTimer.singleShot(0, lambda: self._pin_hwnd(hwnd))
        # Sans ça, fermer un pense-bête encore épinglé laisse la bordure à l'écran et une
        # entrée morte dans _pin_borders.
        win.destroyed.connect(lambda _=None, h=hwnd: self._unpin_hwnd(h))

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
                hit_test = native_hit_test(self, msg.lParam)
                if hit_test is not None:
                    return True, hit_test
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event) -> None:
        for detail in (self._note_detail, self._deliverable_detail, self._template_detail):
            detail.flush_and_save()
        ctypes.windll.user32.UnregisterHotKey(int(self.winId()), _PIN_HOTKEY_ID)
        for hwnd in list(self._pin_borders):
            self._close_pin_border(hwnd)
        self._prefs.window_maximized = self.isMaximized()
        if not self.isMaximized():
            self._prefs.window_size = (self.width(), self.height())
        self._prefs.splitter_sizes = self._splitter.sizes()
        self._prefs.save()
        super().closeEvent(event)
