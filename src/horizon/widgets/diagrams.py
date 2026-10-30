import unicodedata

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from horizon import theme as _theme
from horizon.dialogs import ConfirmDialog
from horizon.diagram import Diagram, DiagramRepository
from horizon.project import ProjectRepository
from horizon.titlebar import TitleBar
from horizon.widgets.drawio import DrawioEditor, make_thumbnail
from horizon.widgets.markdown import _plus_icon, _PLUS_ICON_SIZE

_THUMB_WIDTH  = 200
_THUMB_HEIGHT = 150
_TILE_WIDTH   = _THUMB_WIDTH + 16
_GRID_SPACING = 12


def _fold(text: str) -> str:
    """Casse et accents ignorés, pour que « etat » trouve « État »."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class _DiagramTile(QFrame):
    clicked = Signal(int)  # emits diagram_id

    def __init__(self, diagram: Diagram, parent=None, *, context_menu: bool = True) -> None:
        super().__init__(parent)
        self._diagram_id = diagram.id
        self.setFixedSize(_TILE_WIDTH, _THUMB_HEIGHT + 40)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(diagram.title)
        if context_menu:
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._show_context_menu)

        thumb_label = QLabel(self)
        thumb_label.setFixedSize(_THUMB_WIDTH, _THUMB_HEIGHT)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        px = QPixmap()
        if diagram.thumbnail and px.loadFromData(diagram.thumbnail):
            thumb_label.setPixmap(px.scaled(
                _THUMB_WIDTH,
                _THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            thumb_label.setText("Vide")
            thumb_label.setStyleSheet("color: gray;")

        title_label = QLabel(self)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title_label.setText(title_label.fontMetrics().elidedText(
            diagram.title, Qt.TextElideMode.ElideRight, _THUMB_WIDTH))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(4)
        layout.addWidget(thumb_label)
        layout.addWidget(title_label)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._diagram_id)
        super().mousePressEvent(event)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        open_action = QAction("Ouvrir", self)
        open_action.triggered.connect(lambda: self.clicked.emit(self._diagram_id))
        menu.addAction(open_action)
        menu.exec(self.mapToGlobal(pos))


class _DiagramGrid(QScrollArea):
    """Thumbnail tiles on as many columns as the visible width allows."""

    diagram_clicked = Signal(int)  # emits diagram_id

    def __init__(self, parent=None, *, context_menu: bool = True) -> None:
        super().__init__(parent)
        self._context_menu = context_menu
        self._tiles: list[_DiagramTile] = []
        self._columns = 0

        self._grid_widget = QWidget(self)
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(_GRID_SPACING)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.setWidgetResizable(True)
        self.setWidget(self._grid_widget)

    def set_diagrams(self, diagrams: list[Diagram]) -> None:
        for tile in self._tiles:
            self._grid_layout.removeWidget(tile)
            tile.deleteLater()
        self._tiles = []
        for diagram in diagrams:
            tile = _DiagramTile(diagram, self._grid_widget, context_menu=self._context_menu)
            tile.clicked.connect(self.diagram_clicked)
            self._tiles.append(tile)
        self._columns = 0  # force the placement below
        self._relayout()

    def _relayout(self) -> None:
        width = self.viewport().width()
        columns = max(1, (width + _GRID_SPACING) // (_TILE_WIDTH + _GRID_SPACING))
        if columns == self._columns:
            return
        self._columns = columns
        for tile in self._tiles:
            self._grid_layout.removeWidget(tile)
        for i, tile in enumerate(self._tiles):
            row, col = divmod(i, columns)
            self._grid_layout.addWidget(tile, row, col)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()


class DiagramPickerDialog(QDialog):
    """Dialog frameless de choix d'un diagramme à insérer dans une note WYSIWYG.

    Un clic sur une miniature la choisit ; Entrée dans la recherche prend la première.
    """

    def __init__(self, diagram_repo: DiagramRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insérer un diagramme")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.resize(4 * (_TILE_WIDTH + _GRID_SPACING) + 48, 560)
        self._diagrams = diagram_repo.list_all()
        self._shown: list[Diagram] = []
        self._diagram_id: int | None = None

        self._search_edit = QLineEdit(self)
        self._search_edit.setPlaceholderText("Rechercher un diagramme par son nom…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._apply_filter)
        self._search_edit.returnPressed.connect(self._choose_first)

        self._grid = _DiagramGrid(self, context_menu=False)
        self._grid.diagram_clicked.connect(self._choose)

        self._empty_label = QLabel(self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet("color: gray;")

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._grid)
        self._stack.addWidget(self._empty_label)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        btn_box.rejected.connect(self.reject)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 16)
        content_layout.setSpacing(12)
        content_layout.addWidget(self._search_edit)
        content_layout.addWidget(self._stack, stretch=1)
        content_layout.addWidget(btn_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle="Insérer un diagramme", show_min_max=False))
        layout.addWidget(content, stretch=1)

        self._apply_filter("")
        self._search_edit.setFocus()

    def _apply_filter(self, text: str) -> None:
        query = _fold(text.strip())
        self._shown = [d for d in self._diagrams if query in _fold(d.title)]
        self._grid.set_diagrams(self._shown)
        if self._shown:
            self._stack.setCurrentWidget(self._grid)
            return
        if self._diagrams:
            self._empty_label.setText(f"Aucun diagramme ne correspond à « {text.strip()} ».")
        else:
            self._empty_label.setText("Aucun diagramme pour l'instant : créez-en un dans le module Diagrams.")
        self._stack.setCurrentWidget(self._empty_label)

    def _choose(self, diagram_id: int) -> None:
        self._diagram_id = diagram_id
        self.accept()

    def _choose_first(self) -> None:
        if self._shown:
            self._choose(self._shown[0].id)

    @staticmethod
    def ask(diagram_repo: DiagramRepository, parent=None) -> int | None:
        dlg = DiagramPickerDialog(diagram_repo, parent)
        try:
            if dlg.exec() == QDialog.DialogCode.Accepted:
                return dlg._diagram_id
            return None
        finally:
            dlg.deleteLater()  # its tiles hold every thumbnail; the editor outlives many picks


class DiagramsListWidget(QWidget):
    diagram_edit_requested = Signal(int)  # emits diagram_id

    def __init__(self, diagram_repo: DiagramRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._diagram_repo = diagram_repo
        self._project_repo = project_repo

        title = QLabel("Diagrams")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        new_btn = QPushButton("New")
        new_btn.setIcon(_plus_icon())
        new_btn.setIconSize(_PLUS_ICON_SIZE)
        new_btn.clicked.connect(self._on_new_diagram)

        self._show_archived_cb = QCheckBox("Show archived")
        self._show_archived_cb.stateChanged.connect(self.load)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self._show_archived_cb)
        header_layout.addWidget(new_btn)

        self._grid = _DiagramGrid(self)
        self._grid.diagram_clicked.connect(self.diagram_edit_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(self._grid, stretch=1)

    def load(self) -> None:
        self._grid.set_diagrams(self._diagram_repo.list_all(archived_only=self._show_archived_cb.isChecked()))

    def _on_new_diagram(self) -> None:
        diagram = self._diagram_repo.create(title="New Diagram")
        self.load()
        self.diagram_edit_requested.emit(diagram.id)


class DiagramEditorWidget(QWidget):
    back_requested = Signal()
    diagram_changed = Signal(int)  # emits diagram_id once its rendering was redone, or it was deleted

    def __init__(self, diagram_repo: DiagramRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._diagram_repo = diagram_repo
        self._project_repo = project_repo
        self._current: Diagram | None = None
        self._xml_at_open = ""
        self._updating_combo = False

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(2000)
        self._autosave_timer.timeout.connect(lambda: self._save_xml(show_status=True))

        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.setInterval(2000)
        self._status_clear_timer.timeout.connect(lambda: self._status_label.setText(""))

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

        self._archive_cb = QCheckBox("Archive")
        self._archive_cb.stateChanged.connect(self._on_archive_changed)

        self._delete_btn = QPushButton("Delete")
        _t = _theme.current()
        self._delete_btn.setStyleSheet(f"color: {_t.delete_btn_text}; background-color: {_t.delete_btn_bg};")
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self._on_back_clicked)

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._id_label)
        header_layout.addWidget(self._title_edit, stretch=1)
        header_layout.addWidget(self._archive_cb)
        header_layout.addWidget(self._delete_btn)
        header_layout.addWidget(back_btn)

        self._project_combo = QComboBox()
        self._project_combo.currentIndexChanged.connect(self._on_project_changed)

        project_row = QHBoxLayout()
        project_row.addWidget(QLabel("Project:"))
        project_row.addWidget(self._project_combo)
        project_row.addStretch()

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)

        self._unavailable_banner = QWidget(self)
        self._unavailable_banner.setStyleSheet("background: #f59e0b; color: #1a1a1a;")
        banner_layout = QHBoxLayout(self._unavailable_banner)
        banner_layout.setContentsMargins(8, 2, 8, 2)
        banner_label = QLabel(
            "draw.io est injoignable — une connexion Internet est requise pour éditer les diagrammes.")
        banner_label.setStyleSheet("font-size: 11px;")
        retry_btn = QPushButton("Réessayer")
        retry_btn.clicked.connect(self._on_retry)
        banner_layout.addWidget(banner_label, stretch=1)
        banner_layout.addWidget(retry_btn)
        self._unavailable_banner.setVisible(False)

        self._editor = DrawioEditor(self)
        self._editor.xml_changed.connect(self._autosave_timer.start)
        self._editor.ready.connect(lambda: self._unavailable_banner.setVisible(False))
        self._editor.unavailable.connect(lambda: self._unavailable_banner.setVisible(True))

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addLayout(project_row)
        layout.addWidget(sep)
        layout.addWidget(self._unavailable_banner)
        layout.addWidget(self._editor, stretch=1)
        layout.addWidget(self._status_label)

    def load_diagram(self, diagram: Diagram, projects: list) -> None:
        self._autosave_timer.stop()
        self._status_label.setText("")
        self._current = diagram
        self._xml_at_open = diagram.xml

        self._id_label.setText(f"#{diagram.id}")
        self._title_edit.setText(diagram.title)
        self._archive_cb.blockSignals(True)
        self._archive_cb.setChecked(diagram.archived)
        self._archive_cb.blockSignals(False)
        self._delete_btn.setVisible(diagram.archived)

        self._updating_combo = True
        self._project_combo.clear()
        self._project_combo.addItem("Uncategorized", userData=None)
        for project in projects:
            self._project_combo.addItem(project.name, userData=project.id)
        idx = self._project_combo.findData(diagram.project_id)
        self._project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._updating_combo = False

        self._editor.load_xml(diagram.xml)

    def flush_and_save(self) -> None:
        """Persist the diagram and redo its renderings (list thumbnail, SVG shown in
        notes) if it changed, or if one of them is missing.

        Called on Back and from closeEvent, where the debounced autosave would never fire.
        """
        self._autosave_timer.stop()
        if self._current is None:
            return
        self._save_xml()
        rendered = self._current.thumbnail is not None and self._current.svg is not None
        if self._current.xml == self._xml_at_open and rendered:
            return
        if not self._current.xml:
            return  # never drawn in: the tile keeps its placeholder
        png = self._editor.export_png()
        thumbnail = make_thumbnail(png) if png else None
        svg = self._editor.export_svg() if thumbnail is not None else None
        if svg is None:
            return  # draw.io unreachable: keep the previous renderings
        self._current.thumbnail = thumbnail
        self._current.svg = svg
        self._diagram_repo.update(self._current)
        self._xml_at_open = self._current.xml
        self.diagram_changed.emit(self._current.id)

    def _save_xml(self, show_status: bool = False) -> None:
        if self._current is None:
            return
        xml = self._editor.xml()
        if xml == self._current.xml:
            return
        self._current.xml = xml
        self._diagram_repo.update(self._current)
        if show_status:
            self._status_label.setText("Saving...")
            self._status_clear_timer.start()

    def _save_title(self) -> None:
        if self._current is None:
            return
        self._current.title = self._title_edit.text().strip() or self._current.title
        self._title_edit.setText(self._current.title)
        self._diagram_repo.update(self._current)

    def _on_project_changed(self, _index: int) -> None:
        if self._updating_combo or self._current is None:
            return
        self._current.project_id = self._project_combo.currentData()
        self._diagram_repo.update(self._current)

    def _on_archive_changed(self) -> None:
        if self._current is None:
            return
        self._current.archived = self._archive_cb.isChecked()
        self._diagram_repo.update(self._current)
        self._delete_btn.setVisible(self._current.archived)

    def _on_delete_clicked(self) -> None:
        if self._current is None or not self._current.archived:
            return
        if ConfirmDialog.ask(
            "Delete Diagram",
            f"Permanently delete \"{self._current.title}\"?\nThis cannot be undone.",
            self,
        ):
            self._autosave_timer.stop()
            diagram_id = self._current.id
            self._diagram_repo.delete(diagram_id)
            self._current = None
            self.diagram_changed.emit(diagram_id)
            self.back_requested.emit()

    def _on_retry(self) -> None:
        self._unavailable_banner.setVisible(False)
        self._editor.reload()

    def _on_back_clicked(self) -> None:
        self.flush_and_save()
        self.back_requested.emit()
