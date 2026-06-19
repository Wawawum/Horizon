from PySide6.QtCore import Qt, Signal, QEvent, QTimer
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
from horizon.dialogs import ConfirmDialog
from horizon.folder import FolderRepository
from horizon.image import ImageRepository
from horizon.note import Note, NoteRepository, NoteVersion, NoteVersionRepository
from horizon.project import ProjectRepository
from horizon.widgets.markdown import (
    _plus_icon,
    _PLUS_ICON_SIZE,
    _RESOURCES_BASE_URL,
    _make_preview_html,
    _markdown_to_html,
    MarkdownBridge,
    MarkdownEditor,
    MarkdownToolbar,
)


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
    title_changed = Signal(str)  # emits new title after save

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, folder_repo: FolderRepository, prefs=None, image_repo: ImageRepository | None = None, version_repo: NoteVersionRepository | None = None, windowed: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._folder_repo = folder_repo
        self._prefs = prefs
        self._image_repo = image_repo
        self._version_repo = version_repo
        self._current_note: Note | None = None
        self._body_raw: str = ""
        self._body_at_open: str = ""
        self._viewing_version: NoteVersion | None = None
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

        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.setInterval(2000)
        self._status_clear_timer.timeout.connect(self._clear_status)

        self._windowed = windowed

        back_btn = QPushButton("← Back")
        self._back_btn = back_btn
        self._back_btn.clicked.connect(self._on_back_clicked)

        self._window_btn = QPushButton("⧉ Fenêtre")
        self._window_btn.setToolTip("Ouvrir dans une fenêtre séparée")
        self._window_btn.clicked.connect(self._on_open_in_window)
        self._window_btn.setVisible(not windowed)

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

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._id_label)
        header_layout.addWidget(self._title_edit, stretch=1)
        header_layout.addWidget(self._archive_cb)
        header_layout.addWidget(self._delete_btn)
        header_layout.addWidget(self._window_btn)
        header_layout.addWidget(back_btn)

        project_row = QHBoxLayout()
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

        self._editor = MarkdownEditor(image_repo) if image_repo is not None else QPlainTextEdit()
        self._editor.setPlaceholderText("Write markdown here…")
        self._editor.installEventFilter(self)

        self._toolbar = MarkdownToolbar(self._editor)

        self._bridge = MarkdownBridge(self)
        self._channel = QWebChannel(self)

        self._preview = QWebEngineView()
        self._preview.page().setWebChannel(self._channel)
        self._channel.registerObject("bridge", self._bridge)
        self._preview.setHtml(_make_preview_html(), _RESOURCES_BASE_URL)
        self._bridge.image_clicked.connect(self._on_image_clicked)
        self._bridge.link_clicked.connect(self._on_link_clicked)
        self._bridge.mermaid_open_requested.connect(self._on_open_mermaid)

        self._editor.textChanged.connect(self._on_editor_text_changed)

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

        self._editor_container = QWidget()
        editor_layout = QHBoxLayout(self._editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(4)
        editor_layout.addWidget(self._toolbar)
        editor_layout.addWidget(self._editor, stretch=1)

        self._body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._body_splitter.addWidget(self._editor_container)
        self._body_splitter.addWidget(self._preview)
        self._body_splitter.addWidget(self._history_panel)
        self._body_splitter.setStretchFactor(0, 1)
        self._body_splitter.setStretchFactor(1, 1)
        self._body_splitter.setStretchFactor(2, 0)
        self._body_splitter.splitterMoved.connect(self._on_splitter_moved)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")

        self._readonly_banner = QLabel("Viewing historical version — read only. Press ← Back to return.")
        self._readonly_banner.setStyleSheet("background: #f59e0b; color: #1a1a1a; padding: 4px 8px; font-size: 11px;")
        self._readonly_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._readonly_banner.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addLayout(project_row)
        layout.addWidget(sep)
        layout.addWidget(self._readonly_banner)
        layout.addWidget(self._body_splitter, stretch=1)
        layout.addWidget(self._status_label)

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

    def load_note(self, note: Note, projects: list) -> None:
        self._autosave_timer.stop()
        self._status_label.setText("")
        self._current_note = note
        self._body_raw = note.body
        self._body_at_open = note.body
        self._viewing_version = None
        self._readonly_banner.setVisible(False)
        self._back_btn.setText("← Back")
        self._editor.setReadOnly(False)
        self._toolbar.setEnabled(True)
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

        self._editor.blockSignals(True)
        self._editor.setPlainText(self._body_raw)
        self._editor.blockSignals(False)

        self._image_cache = {}
        self._refresh_note_cache()
        self._bridge.push_html(_markdown_to_html(
            self._body_raw,
            self._image_repo,
            self._note_repo,
            title_to_id=self._note_title_to_id,
            id_exists=self._note_id_exists,
            image_cache=self._image_cache,
        ))

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

    def eventFilter(self, obj, event) -> bool:
        if obj is self._editor and event.type() == QEvent.Type.FocusOut:
            self._save_body()
        return super().eventFilter(obj, event)

    def _autosave(self) -> None:
        self._save_body(show_status=True)

    def _clear_status(self) -> None:
        self._status_label.setText("")

    def _save_body(self, show_status: bool = False) -> None:
        if self._viewing_version is not None:
            return
        if self._current_note is None:
            return
        new_body = self._editor.toPlainText()
        if new_body == self._body_raw:
            return
        self._autosave_timer.stop()
        self._body_raw = new_body
        self._current_note.body = self._body_raw
        self._note_repo.update(self._current_note)
        if show_status:
            self._status_label.setText("Saving...")
            self._status_clear_timer.start()

    def _refresh_note_cache(self) -> None:
        if self._note_repo is not None:
            notes = self._note_repo.list_all()
            self._note_title_to_id = {n.title.lower(): n.id for n in notes}
            self._note_id_exists = {n.id for n in notes}

    def _on_editor_text_changed(self) -> None:
        self._render_timer.start()
        if self._current_note is not None and self._viewing_version is None:
            self._autosave_timer.start()

    def _do_render(self) -> None:
        self._bridge.push_html(_markdown_to_html(
            self._editor.toPlainText(),
            self._image_repo,
            self._note_repo,
            title_to_id=self._note_title_to_id,
            id_exists=self._note_id_exists,
            image_cache=self._image_cache,
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
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(parsed)

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

    def _save_title(self) -> None:
        if self._current_note is None:
            return
        self._current_note.title = self._title_edit.text().strip() or self._current_note.title
        self._title_edit.setText(self._current_note.title)
        self._note_repo.update(self._current_note)
        self._refresh_note_cache()
        self.title_changed.emit(self._current_note.title)

    def _on_archive_changed(self) -> None:
        if self._current_note is None:
            return
        self._current_note.archived = self._archive_cb.isChecked()
        self._note_repo.update(self._current_note)
        self._delete_btn.setVisible(self._current_note.archived)

    def _on_delete_clicked(self) -> None:
        if self._current_note is None or not self._current_note.archived:
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
        if self._updating_combo or self._current_note is None:
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
        if self._updating_folder_combo or self._current_note is None:
            return
        self._current_note.folder_id = self._folder_combo.currentData()
        self._note_repo.update(self._current_note)

    def _on_back_clicked(self) -> None:
        if self._viewing_version is not None:
            self._viewing_version = None
            self._readonly_banner.setVisible(False)
            self._back_btn.setText("← Back")
            self._editor.setReadOnly(False)
            self._toolbar.setEnabled(True)
            self._editor.blockSignals(True)
            self._editor.setPlainText(self._body_raw)
            self._editor.blockSignals(False)
            self._bridge.push_html(_markdown_to_html(self._body_raw, self._image_repo, self._note_repo))
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
        self._editor_container.setVisible(not checked)

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
            self._readonly_banner.setVisible(False)
            self._back_btn.setText("← Back")
            self._editor.setReadOnly(False)
            self._toolbar.setEnabled(True)
            self._editor.blockSignals(True)
            self._editor.setPlainText(self._body_raw)
            self._editor.blockSignals(False)
            self._bridge.push_html(_markdown_to_html(self._body_raw, self._image_repo, self._note_repo))
        else:
            self._viewing_version = version
            self._readonly_banner.setVisible(True)
            self._back_btn.setText("← Return to current")
            self._editor.setReadOnly(True)
            self._toolbar.setEnabled(False)
            self._editor.blockSignals(True)
            self._editor.setPlainText(version.body)
            self._editor.blockSignals(False)
            self._bridge.push_html(_markdown_to_html(version.body, self._image_repo, self._note_repo))
