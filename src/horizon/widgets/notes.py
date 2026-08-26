from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from horizon import theme as _theme
from horizon.dialogs import ConfirmDialog, TaskDetailDialog
from horizon.folder import FolderRepository
from horizon.image import ImageRepository
from horizon.note import Note, NoteRepository, NoteVersion, NoteVersionRepository
from horizon.note_task import NoteTaskRepository, build_task_render_map, sync_note_tasks
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskRepository
from horizon.widgets.markdown import (
    _plus_icon,
    _PLUS_ICON_SIZE,
    _RESOURCES_BASE_URL,
    _make_preview_html,
    _markdown_to_html,
    MarkdownBridge,
)
from horizon.widgets.webeditor import WebMarkdownEditor


class NotesListWidget(QWidget):
    note_edit_requested = Signal(int)  # emits note_id
    note_open_in_window_requested = Signal(int)  # emits note_id

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo

        title = QLabel("Notes")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        new_btn = QPushButton("New Note")
        new_btn.setIcon(_plus_icon())
        new_btn.setIconSize(_PLUS_ICON_SIZE)
        new_btn.clicked.connect(self._on_new_note)

        self._show_archived_cb = QCheckBox("Show archived")
        self._show_archived_cb.stateChanged.connect(self.load)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self._show_archived_cb)
        header_layout.addWidget(new_btn)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Title", "Date", "Project"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._on_double_clicked)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(self._table, stretch=1)

    def load(self) -> None:
        project_names = {p.id: p.name for p in self._project_repo.list_all()}
        notes = self._note_repo.list_all(archived_only=self._show_archived_cb.isChecked())
        self._table.setRowCount(len(notes))
        for row, note in enumerate(notes):
            title_item = QTableWidgetItem(note.title)
            title_item.setData(Qt.ItemDataRole.UserRole, note.id)
            self._table.setItem(row, 0, title_item)
            date_item = QTableWidgetItem(note.dt.strftime("%Y-%m-%d %H:%M"))
            self._table.setItem(row, 1, date_item)
            project_item = QTableWidgetItem(project_names.get(note.project_id, "Uncategorized"))
            self._table.setItem(row, 2, project_item)

    def _on_double_clicked(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is not None:
            self.note_edit_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_new_note(self) -> None:
        projects = self._project_repo.list_all()
        if not projects:
            return
        note = self._note_repo.create(project_id=projects[0].id, title="New Note")
        self.load()
        self.note_edit_requested.emit(note.id)

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self._table.itemAt(pos)
        if item is None:
            return
        row = self._table.row(item)
        note_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if note_id is None:
            return
        menu = QMenu(self)
        open_action = menu.addAction("Ouvrir")
        window_action = menu.addAction("Ouvrir dans une fenêtre")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == open_action:
            self.note_edit_requested.emit(note_id)
        elif action == window_action:
            self.note_open_in_window_requested.emit(note_id)


class NoteDetailWidget(QWidget):
    back_requested = Signal()
    note_link_clicked = Signal(int)  # emits note_id
    open_in_window_requested = Signal(int)  # emits note_id
    open_as_sticky_requested = Signal(int)  # emits note_id
    title_changed = Signal(str)  # emits new title after save
    editor_ready = Signal()  # CodeMirror is live; focus_editor() lands from here on

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, folder_repo: FolderRepository, prefs=None, image_repo: ImageRepository | None = None, version_repo: NoteVersionRepository | None = None, task_repo: TaskRepository | None = None, subtask_repo: SubtaskRepository | None = None, note_task_repo: NoteTaskRepository | None = None, windowed: bool = False, sticky: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._folder_repo = folder_repo
        self._prefs = prefs
        self._image_repo = image_repo
        self._version_repo = version_repo
        self._task_repo = task_repo
        self._subtask_repo = subtask_repo
        self._note_task_repo = note_task_repo
        self._current_note: Note | None = None
        self._body_raw: str = ""
        self._body_at_open: str = ""
        self._viewing_version: NoteVersion | None = None
        # Verrou posé quand la note est détenue par une fenêtre détachée. Orthogonal à
        # _viewing_version : les deux mènent en lecture seule, pas avec le même périmètre.
        self._locked = False
        self._updating_combo = False
        self._updating_folder_combo = False

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(5000)
        self._autosave_timer.timeout.connect(self._autosave)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(300)
        self._render_timer.timeout.connect(self._do_render)

        self._note_title_to_id: dict[str, int] = {}
        self._note_id_exists: set[int] = set()
        self._image_cache: dict[int, bytes | None] = {}
        # Task titles/states, resolved when the note is opened rather than on
        # every keystroke — the preview deliberately shows a snapshot.
        self._task_info: dict[int, tuple[str, str]] = {}

        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.setInterval(2000)
        self._status_clear_timer.timeout.connect(self._clear_status)

        # Le pense-bête est une fenêtre détachée réduite à l'éditeur : il implique windowed.
        windowed = windowed or sticky
        self._windowed = windowed
        self._sticky = sticky

        back_btn = QPushButton("← Back")
        self._back_btn = back_btn
        self._back_btn.clicked.connect(self._on_back_clicked)

        self._window_btn = QPushButton("⧉ Fenêtre")
        self._window_btn.setToolTip("Ouvrir dans une fenêtre séparée")
        self._window_btn.clicked.connect(self._on_open_in_window)
        self._window_btn.setVisible(not windowed)

        self._sticky_btn = QPushButton("📌 Pense-bête")
        self._sticky_btn.setToolTip("Ouvrir en pense-bête — fenêtre épinglée au-dessus des autres")
        self._sticky_btn.clicked.connect(self._on_open_as_sticky)
        self._sticky_btn.setVisible(not windowed)

        self._archive_cb = QCheckBox("Archive")
        self._archive_cb.stateChanged.connect(self._on_archive_changed)

        self._delete_btn = QPushButton("Delete")
        _t = _theme.current()
        self._delete_btn.setStyleSheet(f"color: {_t.delete_btn_text}; background-color: {_t.delete_btn_bg};")
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)

        self._id_label = QLabel()
        id_font = self._id_label.font()
        id_font.setPointSize(id_font.pointSize() + 4)
        id_font.setBold(True)
        self._id_label.setFont(id_font)

        self._title_edit = QLineEdit()
        self._title_edit.setMaxLength(255)
        font = self._title_edit.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self._title_edit.setFont(font)
        self._title_edit.setFrame(False)
        self._title_edit.editingFinished.connect(self._save_title)

        self._project_combo = QComboBox()
        self._project_combo.currentIndexChanged.connect(self._on_project_changed)

        self._folder_combo = QComboBox()
        self._folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        self._folder_label = QLabel("Folder:")

        self._history_btn = QPushButton("History")
        self._history_btn.setCheckable(True)
        self._history_btn.clicked.connect(self._on_toggle_history)

        self._view_source_btn = QPushButton("View source")
        self._view_source_btn.clicked.connect(self._on_view_source)

        self._presentation_btn = QPushButton("⊞ Présentation")
        self._presentation_btn.setCheckable(True)
        self._presentation_btn.setToolTip("Cacher l'éditeur pour la présentation")
        self._presentation_btn.clicked.connect(self._on_toggle_presentation)

        # Les deux rangées de chrome vivent dans un conteneur plutôt que dans une layout
        # nue, pour que le mode pense-bête les masque d'un seul setVisible().
        self._header_widget = QWidget(self)
        header_layout = QHBoxLayout(self._header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self._id_label)
        header_layout.addWidget(self._title_edit, stretch=1)
        header_layout.addWidget(self._archive_cb)
        header_layout.addWidget(self._delete_btn)
        header_layout.addWidget(self._sticky_btn)
        header_layout.addWidget(self._window_btn)
        header_layout.addWidget(back_btn)

        self._project_row_widget = QWidget(self)
        project_row = QHBoxLayout(self._project_row_widget)
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.addWidget(QLabel("Project:"))
        project_row.addWidget(self._project_combo)
        project_row.addSpacing(16)
        project_row.addWidget(self._folder_label)
        project_row.addWidget(self._folder_combo)
        project_row.addStretch()
        project_row.addWidget(self._history_btn)
        project_row.addWidget(self._view_source_btn)
        project_row.addWidget(self._presentation_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)

        self._editor = WebMarkdownEditor(
            image_repo, self,
            show_toolbar=not sticky,
            placeholder="Notes de réunion…" if sticky else "Write markdown here…",
            prefs=prefs,
        )
        self._editor.editing_finished.connect(self._on_editing_finished)
        self._editor.shortcut_pressed.connect(self._on_editor_shortcut)
        self._editor.image_upload.connect(self._on_image_upload)
        self._editor.editor_ready.connect(self.editor_ready)

        self._bridge = MarkdownBridge(self)
        self._bridge.image_clicked.connect(self._on_image_clicked)
        self._bridge.link_clicked.connect(self._on_link_clicked)
        self._bridge.mermaid_open_requested.connect(self._on_open_mermaid)

        # En pense-bête l'aperçu n'existe pas du tout : pas de QWebEngineView, et le rendu
        # markdown est court-circuité (voir _do_render). Le bridge reste construit, c'est un
        # simple QObject et _on_view_source lit encore son HTML courant.
        self._preview: QWebEngineView | None = None
        self._channel: QWebChannel | None = None
        if not sticky:
            self._channel = QWebChannel(self)
            self._channel.registerObject("bridge", self._bridge)
            self._preview = QWebEngineView()
            self._preview.page().setWebChannel(self._channel)
            self._preview.setHtml(_make_preview_html(), _RESOURCES_BASE_URL)

        self._editor.text_changed.connect(self._on_editor_text_changed)

        self._history_panel = QWidget()
        _hp_layout = QVBoxLayout(self._history_panel)
        _hp_layout.setContentsMargins(8, 0, 0, 0)
        _hp_layout.setSpacing(4)
        _hp_layout.addWidget(QLabel("Version history"))
        self._history_list = QListWidget()
        self._history_list.setFixedWidth(200)
        self._history_list.currentItemChanged.connect(self._on_history_item_selected)
        _hp_layout.addWidget(self._history_list)
        self._history_panel.setVisible(False)

        self._body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._body_splitter.addWidget(self._editor)
        if self._preview is not None:
            self._body_splitter.addWidget(self._preview)
        self._body_splitter.addWidget(self._history_panel)
        self._body_splitter.setStretchFactor(0, 1)
        if self._preview is not None:
            self._body_splitter.setStretchFactor(1, 1)
        self._body_splitter.setStretchFactor(self._body_splitter.count() - 1, 0)
        self._body_splitter.splitterMoved.connect(self._on_splitter_moved)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")

        self._readonly_banner = QLabel("Viewing historical version — read only. Press ← Back to return.")
        self._readonly_banner.setStyleSheet("background: #f59e0b; color: #1a1a1a; padding: 4px 8px; font-size: 11px;")
        self._readonly_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._readonly_banner.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*((6, 6, 6, 6) if sticky else (16, 16, 16, 16)))
        layout.setSpacing(4 if sticky else 8)
        layout.addWidget(self._header_widget)
        layout.addWidget(self._project_row_widget)
        layout.addWidget(sep)
        layout.addWidget(self._readonly_banner)
        layout.addWidget(self._body_splitter, stretch=1)
        layout.addWidget(self._status_label)

        if sticky:
            self._header_widget.setVisible(False)
            self._project_row_widget.setVisible(False)
            sep.setVisible(False)
        else:
            # Les tailles sauvegardées valent pour le splitter à trois volets.
            self._restore_splitter_sizes()

    def _on_view_source(self) -> None:
        """Open a dialog showing the raw HTML sent to the preview."""
        html = self._bridge._current_html
        dlg = QDialog(self)
        dlg.setWindowTitle("Preview HTML source")
        dlg.resize(800, 600)
        text = QPlainTextEdit(dlg)
        text.setReadOnly(True)
        text.setPlainText(html)
        text.setFont(QFont("Courier New", 9))
        lay = QVBoxLayout(dlg)
        lay.addWidget(text)
        dlg.exec()

    def _apply_readonly(self) -> None:
        """Source unique de vérité de l'état lecture seule et de sa bannière."""
        if self._viewing_version is not None:
            message = "Viewing historical version — read only. Press ← Back to return."
        elif self._locked:
            message = ("Ouverte dans une fenêtre séparée — lecture seule ici. "
                       "Fermez la fenêtre pour reprendre l'édition.")
        else:
            message = ""
        self._readonly_banner.setText(message)
        self._readonly_banner.setVisible(bool(message))
        self._editor.set_read_only(bool(message))
        # Réservé au verrou : consulter une version laisse ces contrôles actifs, comme avant.
        for widget in (self._title_edit, self._project_combo, self._folder_combo,
                       self._archive_cb, self._delete_btn, self._history_btn):
            widget.setEnabled(not self._locked)

    def set_locked(self, locked: bool) -> None:
        """Passe le panneau en lecture seule tant qu'une fenêtre détachée détient la note.

        Sans ce verrou les deux vues gardent chacune leur copie du corps, et la dernière à
        écrire écrase l'autre — NoteRepository.update réécrit toutes les colonnes.
        """
        if locked == self._locked:
            return
        if locked:
            # Avant de verrouiller, jamais après : la fenêtre détachée relit la note depuis
            # la base juste ensuite et doit voir la dernière frappe faite ici.
            self.flush_and_save()
        self._locked = locked
        self._apply_readonly()

    @property
    def current_note_id(self) -> int | None:
        return self._current_note.id if self._current_note is not None else None

    def load_note(self, note: Note, projects: list) -> None:
        self._autosave_timer.stop()
        self._status_label.setText("")
        self._current_note = note
        self._body_raw = note.body
        self._body_at_open = note.body
        self._viewing_version = None
        self._back_btn.setText("← Back")
        self._apply_readonly()
        if self._history_btn.isChecked():
            self._history_btn.setChecked(False)
            self._history_panel.setVisible(False)

        self._id_label.setText(f"#{note.id}" if note.id is not None else "")
        self._title_edit.setText(note.title)
        self._archive_cb.setChecked(note.archived)
        self._delete_btn.setVisible(note.archived)

        self._updating_combo = True
        self._project_combo.clear()
        self._project_combo.addItem("Uncategorized", userData=None)
        for project in projects:
            self._project_combo.addItem(project.name, userData=project.id)
        idx = self._project_combo.findData(note.project_id)
        self._project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._updating_combo = False

        self._updating_folder_combo = True
        if note.project_id is not None:
            self._folder_label.setVisible(True)
            self._folder_combo.setVisible(True)
            self._populate_folder_combo(note.project_id, note.folder_id)
        else:
            self._folder_label.setVisible(False)
            self._folder_combo.setVisible(False)
            self._folder_combo.clear()
        self._updating_folder_combo = False

        self._editor.set_text(self._body_raw)

        self._image_cache = {}
        self._refresh_note_cache()
        # _task_info sert aussi au rendu qui suit la réécriture des blocs {task: …},
        # donc le cache est rafraîchi même sans aperçu.
        self._refresh_task_cache(self._body_raw)
        self._do_render()

    def _populate_folder_combo(self, project_id: int, selected_folder_id: int | None) -> None:
        self._folder_combo.clear()
        self._folder_combo.addItem("No folder", userData=None)

        all_folders = self._folder_repo.list_for_project(project_id)

        def _dfs(parent_id: int | None, depth: int) -> None:
            children = sorted(
                [f for f in all_folders if f.parent_id == parent_id],
                key=lambda f: f.name.lower(),
            )
            for folder in children:
                prefix = "  " * depth + ("└ " if depth > 0 else "")
                self._folder_combo.addItem(prefix + folder.name, userData=folder.id)
                _dfs(folder.id, depth + 1)

        _dfs(None, 0)

        idx = self._folder_combo.findData(selected_folder_id)
        self._folder_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _on_editor_shortcut(self, name: str) -> None:
        if name == "save":
            self._save_body(show_status=True)

    def _on_image_upload(self, started: bool) -> None:
        if started:
            self._status_clear_timer.stop()
            self._status_label.setText("Enregistrement de l'image…")
        else:
            self._status_label.setText("")

    def _autosave(self) -> None:
        # Task blocks are left alone here: rewriting them into ids mid-typing
        # would move the caret under the user's hands.
        self._save_body(show_status=True, sync_tasks=False)

    def _on_editing_finished(self) -> None:
        self._save_body()

    def flush_and_save(self) -> None:
        """Persist any pending body edit immediately.

        Called from closeEvent handlers, where the debounced autosave timer would
        otherwise never fire and the edit would be lost.
        """
        self._autosave_timer.stop()
        self._save_body()

    def _clear_status(self) -> None:
        self._status_label.setText("")

    def _save_body(self, show_status: bool = False, sync_tasks: bool = True) -> None:
        if self._locked or self._viewing_version is not None:
            return
        if self._current_note is None:
            return
        self._editor.flush()
        new_body = self._editor.text()
        changed = new_body != self._body_raw
        rewritten = False

        # The body may be unchanged and still hold blocks an autosave persisted
        # verbatim, so this cannot sit behind the "changed" check.
        if (
            sync_tasks
            and self._task_repo is not None
            and self._note_task_repo is not None
            and self._current_note.project_id is not None
            and (changed or "{task:" in new_body)
        ):
            synced = sync_note_tasks(
                new_body,
                self._current_note.id,
                self._current_note.project_id,
                self._task_repo,
                self._note_task_repo,
            )
            if synced != new_body:
                new_body = synced
                changed = True
                rewritten = True

        if not changed:
            return
        self._autosave_timer.stop()
        self._body_raw = new_body
        self._current_note.body = self._body_raw
        self._note_repo.update(self._current_note)
        if rewritten:
            self._refresh_task_cache(self._body_raw)
            self._editor.set_text(self._body_raw)
            self._do_render()
        if show_status:
            self._status_label.setText("Saving...")
            self._status_clear_timer.start()

    def _refresh_note_cache(self) -> None:
        if self._note_repo is not None:
            notes = self._note_repo.list_all()
            self._note_title_to_id = {n.title.lower(): n.id for n in notes}
            self._note_id_exists = {n.id for n in notes}

    def _refresh_task_cache(self, body: str) -> None:
        if self._task_repo is not None:
            self._task_info = build_task_render_map(body, self._task_repo)

    def _on_editor_text_changed(self) -> None:
        if not self._sticky:
            self._render_timer.start()
        if self._current_note is not None and self._viewing_version is None and not self._locked:
            self._autosave_timer.start()

    def _do_render(self) -> None:
        if self._sticky:
            return  # pas d'aperçu à alimenter, et _markdown_to_html est le gros du coût
        # No flush(): this sits behind a 300 ms debounce, so a ~120 ms stale mirror
        # is invisible and a nested event loop here would be gratuitous.
        self._bridge.push_html(_markdown_to_html(
            self._editor.text(),
            self._image_repo,
            self._note_repo,
            title_to_id=self._note_title_to_id,
            id_exists=self._note_id_exists,
            image_cache=self._image_cache,
            task_info=self._task_info,
        ))

    def _on_image_clicked(self, data_uri: str) -> None:
        from horizon.dialogs import ImageViewerDialog
        dlg = ImageViewerDialog(data_uri, parent=self)
        dlg.exec()

    def _on_open_mermaid(self, source: str) -> None:
        from horizon.dialogs import MermaidViewerDialog
        dlg = MermaidViewerDialog(source, parent=self)
        dlg.show()

    def _on_link_clicked(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        parsed = QUrl(url)
        if parsed.scheme() == "horizon" and parsed.host() == "note":
            try:
                note_id = int(parsed.path().lstrip("/"))
            except ValueError:
                return
            self.note_link_clicked.emit(note_id)
            return
        if parsed.scheme() == "horizon" and parsed.host() == "task":
            try:
                task_id = int(parsed.path().lstrip("/"))
            except ValueError:
                return
            self._open_task_dialog(task_id)
            return
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(parsed)

    def _open_task_dialog(self, task_id: int) -> None:
        if self._task_repo is None or self._subtask_repo is None:
            return
        task = self._task_repo.get(task_id)
        if task is None:
            return
        dialog = TaskDetailDialog(task, self._subtask_repo, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.deleted():
            # note_tasks rows for this task go with it, through the FK cascade
            self._task_repo.delete(task.id)
        else:
            task.title = dialog.title()
            task.description = dialog.description()
            task.state = dialog.state()
            task.priority = dialog.priority()
            task.bucket = dialog.bucket()
            task.archived = dialog.archived()
            self._task_repo.update(task)
        self._refresh_task_cache(self._editor.text())
        self._do_render()

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        if self._prefs is not None:
            self._prefs.note_splitter_sizes = self._body_splitter.sizes()

    def _restore_splitter_sizes(self) -> None:
        if self._prefs is not None:
            saved = self._prefs.note_splitter_sizes
            if saved:
                self._body_splitter.setSizes(saved)

    def _on_open_in_window(self) -> None:
        if self._current_note is not None:
            self.open_in_window_requested.emit(self._current_note.id)

    def _on_open_as_sticky(self) -> None:
        if self._current_note is not None:
            self.open_as_sticky_requested.emit(self._current_note.id)

    def focus_editor(self) -> None:
        self._editor.focus_editor()

    def _save_title(self) -> None:
        if self._locked or self._current_note is None:
            return
        self._current_note.title = self._title_edit.text().strip() or self._current_note.title
        self._title_edit.setText(self._current_note.title)
        self._note_repo.update(self._current_note)
        self._refresh_note_cache()
        self.title_changed.emit(self._current_note.title)

    def _on_archive_changed(self) -> None:
        if self._locked or self._current_note is None:
            return
        self._current_note.archived = self._archive_cb.isChecked()
        self._note_repo.update(self._current_note)
        self._delete_btn.setVisible(self._current_note.archived)

    def _on_delete_clicked(self) -> None:
        if self._locked or self._current_note is None or not self._current_note.archived:
            return
        if ConfirmDialog.ask(
            "Delete Note",
            f"Permanently delete \"{self._current_note.title}\"?\nThis cannot be undone.",
            self,
        ):
            self._note_repo.delete(self._current_note.id)
            self._current_note = None
            self.back_requested.emit()

    def _on_project_changed(self, _index: int) -> None:
        if self._locked or self._updating_combo or self._current_note is None:
            return
        new_project_id = self._project_combo.currentData()
        self._current_note.project_id = new_project_id
        self._current_note.folder_id = None
        self._note_repo.update(self._current_note)

        self._updating_folder_combo = True
        if new_project_id is not None:
            self._folder_label.setVisible(True)
            self._folder_combo.setVisible(True)
            self._populate_folder_combo(new_project_id, None)
        else:
            self._folder_label.setVisible(False)
            self._folder_combo.setVisible(False)
            self._folder_combo.clear()
        self._updating_folder_combo = False

    def _on_folder_changed(self, _index: int) -> None:
        if self._locked or self._updating_folder_combo or self._current_note is None:
            return
        self._current_note.folder_id = self._folder_combo.currentData()
        self._note_repo.update(self._current_note)

    def _on_back_clicked(self) -> None:
        if self._viewing_version is not None:
            self._viewing_version = None
            self._back_btn.setText("← Back")
            self._apply_readonly()
            self._editor.set_text(self._body_raw)
            self._refresh_task_cache(self._body_raw)
            self._bridge.push_html(_markdown_to_html(
                self._body_raw, self._image_repo, self._note_repo, task_info=self._task_info))
            self._history_list.blockSignals(True)
            if self._history_list.count() > 0:
                self._history_list.setCurrentRow(0)
            self._history_list.blockSignals(False)
            return

        self._autosave_timer.stop()
        self._save_body()

        if (self._version_repo is not None
                and self._current_note is not None
                and self._body_raw != self._body_at_open):
            self._version_repo.create_version(self._current_note)

        self.back_requested.emit()

    def _on_toggle_history(self, checked: bool) -> None:
        self._history_panel.setVisible(checked)
        if checked and self._current_note is not None:
            self._load_history()

    def _on_toggle_presentation(self, checked: bool) -> None:
        self._editor.setVisible(not checked)

    def _load_history(self) -> None:
        if self._version_repo is None or self._current_note is None:
            return
        self._history_list.blockSignals(True)
        self._history_list.clear()
        for v in self._version_repo.list_for_note(self._current_note.id):
            label = v.version_dt.strftime("%Y-%m-%d %H:%M:%S")
            if v.is_current:
                label += " (current)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, v.id)
            self._history_list.addItem(item)
        self._history_list.blockSignals(False)

    def _on_history_item_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None or self._version_repo is None:
            return
        version = self._version_repo.get(current.data(Qt.ItemDataRole.UserRole))
        if version is None:
            return
        if version.is_current:
            self._viewing_version = None
            self._back_btn.setText("← Back")
            self._apply_readonly()
            self._editor.set_text(self._body_raw)
            self._refresh_task_cache(self._body_raw)
            self._bridge.push_html(_markdown_to_html(
                self._body_raw, self._image_repo, self._note_repo, task_info=self._task_info))
        else:
            self._viewing_version = version
            self._back_btn.setText("← Return to current")
            self._apply_readonly()
            self._editor.set_text(version.body)
            self._refresh_task_cache(version.body)
            self._bridge.push_html(_markdown_to_html(
                version.body, self._image_repo, self._note_repo, task_info=self._task_info))
