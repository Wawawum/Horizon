from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from horizon import theme as _theme
from horizon.dialogs import ConfirmDialog, SelectTemplatesDialog
from horizon.deliverable import DeliverableRepository
from horizon.deliverable_template import DeliverableTemplate, DeliverableTemplateRepository
from horizon.image import ImageRepository
from horizon.widgets.markdown import (
    _make_preview_html,
    _markdown_to_html,
    _plus_icon,
    _PLUS_ICON_SIZE,
    _RESOURCES_BASE_URL,
    MarkdownBridge,
    MarkdownEditor,
)


class ProjectDeliverablesPanel(QWidget):
    """Panel displayed in the Deliverables tab of a project."""

    deliverable_edit_requested = Signal(int)  # emits deliverable_id

    def __init__(self, deliverable_repo: DeliverableRepository, tmpl_repo: DeliverableTemplateRepository, parent=None) -> None:
        super().__init__(parent)
        self._deliverable_repo = deliverable_repo
        self._tmpl_repo = tmpl_repo
        self._current_project_id: int | None = None

        title = QLabel("Deliverables")
        font = title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title.setFont(font)

        self._new_btn = QPushButton("New")
        self._new_btn.setIcon(_plus_icon())
        self._new_btn.setIconSize(_PLUS_ICON_SIZE)
        self._new_btn.clicked.connect(self._on_new)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._new_btn)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemDoubleClicked.connect(self._on_double_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 8)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self._list, stretch=1)

    def load(self, project_id: int) -> None:
        self._current_project_id = project_id
        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        if self._current_project_id is None:
            return
        for deliverable in self._deliverable_repo.list_for_project(self._current_project_id):
            item = QListWidgetItem(deliverable.title)
            item.setData(Qt.ItemDataRole.UserRole, deliverable.id)
            self._list.addItem(item)

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        deliverable_id = item.data(Qt.ItemDataRole.UserRole)
        if deliverable_id is not None:
            self.deliverable_edit_requested.emit(deliverable_id)

    def _on_new(self) -> None:
        if self._current_project_id is None:
            return
        templates = self._tmpl_repo.list_all()
        selected = SelectTemplatesDialog.ask(templates, self)
        for tmpl in selected:
            self._deliverable_repo.create(
                project_id=self._current_project_id,
                title=tmpl.title,
                body=tmpl.template,
                template_id=tmpl.id,
            )
        if selected:
            self._refresh()


class DeliverableDetailWidget(QWidget):
    """Full-screen editor for a single project deliverable."""

    back_requested = Signal()

    def __init__(
        self,
        deliverable_repo: DeliverableRepository,
        image_repo: ImageRepository,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._deliverable_repo = deliverable_repo
        self._image_repo = image_repo
        self._current: "Deliverable | None" = None  # type: ignore[name-defined]
        self._body_raw: str = ""

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(5000)
        self._autosave_timer.timeout.connect(self._autosave)

        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.setInterval(2000)
        self._status_clear_timer.timeout.connect(self._clear_status)

        # ── Header ────────────────────────────────────────────────────────
        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self._on_back)

        self._title_edit = QLineEdit()
        self._title_edit.setMaxLength(255)
        font = self._title_edit.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self._title_edit.setFont(font)
        self._title_edit.setFrame(False)
        self._title_edit.editingFinished.connect(self._save_title)

        _t = _theme.current()
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setStyleSheet(
            f"color: {_t.delete_btn_text}; background-color: {_t.delete_btn_bg};"
        )
        self._delete_btn.clicked.connect(self._on_delete)

        header_layout = QHBoxLayout()
        header_layout.addWidget(back_btn)
        header_layout.addWidget(self._title_edit, stretch=1)
        header_layout.addWidget(self._delete_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)

        # ── Editor + Preview ──────────────────────────────────────────────
        self._editor = MarkdownEditor(image_repo)
        self._editor.setPlaceholderText("Write deliverable content here…")
        self._editor.textChanged.connect(self._on_text_changed)

        self._bridge = MarkdownBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)

        self._preview = QWebEngineView()
        self._preview.page().setWebChannel(self._channel)
        self._preview.setHtml(_make_preview_html(), _RESOURCES_BASE_URL)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._editor)
        self._splitter.addWidget(self._preview)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(sep)
        layout.addWidget(self._splitter, stretch=1)
        layout.addWidget(self._status_label)

    def load_deliverable(self, deliverable) -> None:
        self._autosave_timer.stop()
        self._status_label.setText("")
        self._current = deliverable
        self._body_raw = deliverable.body

        self._title_edit.setText(deliverable.title)

        self._editor.blockSignals(True)
        self._editor.setPlainText(self._body_raw)
        self._editor.blockSignals(False)

        self._bridge.push_html(_markdown_to_html(self._body_raw, self._image_repo))

    def _on_text_changed(self) -> None:
        self._bridge.push_html(_markdown_to_html(self._editor.toPlainText(), self._image_repo))
        if self._current is not None:
            self._autosave_timer.start()

    def _autosave(self) -> None:
        self._save_body(show_status=True)

    def _clear_status(self) -> None:
        self._status_label.setText("")

    def _save_body(self, show_status: bool = False) -> None:
        if self._current is None:
            return
        new_body = self._editor.toPlainText()
        if new_body == self._body_raw:
            return
        self._autosave_timer.stop()
        self._body_raw = new_body
        self._current.body = self._body_raw
        self._deliverable_repo.update(self._current)
        if show_status:
            self._status_label.setText("Saving…")
            self._status_clear_timer.start()

    def _save_title(self) -> None:
        if self._current is None:
            return
        new_title = self._title_edit.text().strip()
        if new_title:
            self._current.title = new_title
        self._title_edit.setText(self._current.title)
        self._deliverable_repo.update(self._current)

    def _on_delete(self) -> None:
        if self._current is None:
            return
        from horizon.dialogs import ConfirmDialog
        if ConfirmDialog.ask(
            "Delete Deliverable",
            f"Permanently delete \"{self._current.title}\"?\nThis cannot be undone.",
            self,
        ):
            self._deliverable_repo.delete(self._current.id)
            self._current = None
            self.back_requested.emit()

    def _on_back(self) -> None:
        self._autosave_timer.stop()
        self._save_body()
        self.back_requested.emit()


class DeliverablesWidget(QWidget):
    show_templates_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        title = QLabel("Deliverables")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        show_templates_btn = QPushButton("Show templates")
        show_templates_btn.clicked.connect(self.show_templates_requested)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(show_templates_btn)

        placeholder = QLabel("Deliverables — coming soon")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(placeholder, stretch=1)


class DeliverableTemplatesListWidget(QWidget):
    back_requested = Signal()
    template_edit_requested = Signal(int)

    def __init__(self, tmpl_repo: DeliverableTemplateRepository, parent=None) -> None:
        super().__init__(parent)
        self._tmpl_repo = tmpl_repo

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.back_requested)

        title = QLabel("Templates")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        new_btn = QPushButton("New Template")
        new_btn.setIcon(_plus_icon())
        new_btn.setIconSize(_PLUS_ICON_SIZE)
        new_btn.clicked.connect(self._on_new_template)

        header_layout = QHBoxLayout()
        header_layout.addWidget(back_btn)
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(new_btn)

        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["Title", "Created"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._on_double_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(self._table, stretch=1)

    def load(self) -> None:
        templates = self._tmpl_repo.list_all()
        self._table.setRowCount(len(templates))
        for row, tmpl in enumerate(templates):
            title_item = QTableWidgetItem(tmpl.title)
            title_item.setData(Qt.ItemDataRole.UserRole, tmpl.id)
            self._table.setItem(row, 0, title_item)
            date_item = QTableWidgetItem(tmpl.created_at.strftime("%Y-%m-%d %H:%M"))
            self._table.setItem(row, 1, date_item)

    def _on_double_clicked(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is not None:
            self.template_edit_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_new_template(self) -> None:
        tmpl = self._tmpl_repo.create()
        self.load()
        self.template_edit_requested.emit(tmpl.id)


class DeliverableTemplateDetailWidget(QWidget):
    back_requested = Signal()

    def __init__(
        self,
        tmpl_repo: DeliverableTemplateRepository,
        image_repo: ImageRepository,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._tmpl_repo = tmpl_repo
        self._image_repo = image_repo
        self._current_tmpl: DeliverableTemplate | None = None
        self._body_raw: str = ""

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(5000)
        self._autosave_timer.timeout.connect(self._autosave)

        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.setInterval(2000)
        self._status_clear_timer.timeout.connect(self._clear_status)

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self._on_back_clicked)

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

        self._delete_btn = QPushButton("Delete")
        _t = _theme.current()
        self._delete_btn.setStyleSheet(
            f"color: {_t.delete_btn_text}; background-color: {_t.delete_btn_bg};"
        )
        self._delete_btn.clicked.connect(self._on_delete_clicked)

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._id_label)
        header_layout.addWidget(self._title_edit, stretch=1)
        header_layout.addWidget(self._delete_btn)
        header_layout.addWidget(back_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)

        self._editor = MarkdownEditor(image_repo)
        self._editor.setPlaceholderText("Write template markdown here…")
        self._editor.textChanged.connect(self._on_editor_text_changed)

        self._bridge = MarkdownBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)

        self._preview = QWebEngineView()
        self._preview.page().setWebChannel(self._channel)
        self._preview.setHtml(_make_preview_html(), _RESOURCES_BASE_URL)

        self._body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._body_splitter.addWidget(self._editor)
        self._body_splitter.addWidget(self._preview)
        self._body_splitter.setStretchFactor(0, 1)
        self._body_splitter.setStretchFactor(1, 1)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(sep)
        layout.addWidget(self._body_splitter, stretch=1)
        layout.addWidget(self._status_label)

    def load_template(self, tmpl: DeliverableTemplate) -> None:
        self._autosave_timer.stop()
        self._status_label.setText("")
        self._current_tmpl = tmpl
        self._body_raw = tmpl.template

        self._id_label.setText(f"#{tmpl.id}" if tmpl.id is not None else "")
        self._title_edit.setText(tmpl.title)

        self._editor.blockSignals(True)
        self._editor.setPlainText(self._body_raw)
        self._editor.blockSignals(False)

        self._bridge.push_html(_markdown_to_html(self._body_raw, self._image_repo))

    def _on_editor_text_changed(self) -> None:
        self._bridge.push_html(_markdown_to_html(self._editor.toPlainText(), self._image_repo))
        if self._current_tmpl is not None:
            self._autosave_timer.start()

    def _autosave(self) -> None:
        self._save_body(show_status=True)

    def _clear_status(self) -> None:
        self._status_label.setText("")

    def _save_body(self, show_status: bool = False) -> None:
        if self._current_tmpl is None:
            return
        new_body = self._editor.toPlainText()
        if new_body == self._body_raw:
            return
        self._autosave_timer.stop()
        self._body_raw = new_body
        self._current_tmpl.template = self._body_raw
        self._tmpl_repo.update(self._current_tmpl)
        if show_status:
            self._status_label.setText("Saving...")
            self._status_clear_timer.start()

    def _save_title(self) -> None:
        if self._current_tmpl is None:
            return
        new_title = self._title_edit.text().strip()
        if new_title:
            self._current_tmpl.title = new_title
        self._title_edit.setText(self._current_tmpl.title)
        self._tmpl_repo.update(self._current_tmpl)

    def _on_delete_clicked(self) -> None:
        if self._current_tmpl is None:
            return
        if ConfirmDialog.ask(
            "Delete Template",
            f"Permanently delete \"{self._current_tmpl.title}\"?\nThis cannot be undone.",
            self,
        ):
            self._tmpl_repo.delete(self._current_tmpl.id)
            self._current_tmpl = None
            self.back_requested.emit()

    def _on_back_clicked(self) -> None:
        self._autosave_timer.stop()
        self._save_body()
        self.back_requested.emit()
