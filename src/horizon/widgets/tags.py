from PySide6.QtCore import Qt, Signal, QRect, QSize, QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from horizon import theme as _theme
from horizon.folder import FolderRepository
from horizon.note import NoteRepository
from horizon.project import ProjectRepository
from horizon.tag import Tag, TagRepository


class _FlowLayout(QLayout):
    """Positions child widgets left-to-right, wrapping to the next row."""

    def __init__(self, parent=None, h_spacing: int = 6, v_spacing: int = 6) -> None:
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list = []

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        x = rect.x() + margins.left()
        y = rect.y() + margins.top()
        row_height = 0
        right = rect.right() - margins.right()

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width()
            if next_x > right and row_height > 0:
                x = rect.x() + margins.left()
                y += row_height + self._v_spacing
                next_x = x + hint.width()
                row_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + self._h_spacing
            row_height = max(row_height, hint.height())

        return y + row_height - rect.y() + margins.bottom()


class TagsWidget(QWidget):
    note_edit_requested = Signal(int)

    def __init__(
        self,
        tag_repo: TagRepository,
        note_repo: NoteRepository,
        project_repo: ProjectRepository,
        folder_repo: FolderRepository,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._tag_repo = tag_repo
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._folder_repo = folder_repo
        self._selected_tag: Tag | None = None
        self._tag_buttons: dict[int, QPushButton] = {}

        # ── Title ─────────────────────────────────────────────────────────
        title = QLabel("Tags")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        # ── Tag chips panel ───────────────────────────────────────────────
        self._chips_widget = QWidget()
        self._chips_layout = _FlowLayout(self._chips_widget, h_spacing=6, v_spacing=6)
        self._chips_widget.setLayout(self._chips_layout)

        self._chips_scroll = QScrollArea()
        self._chips_scroll.setWidgetResizable(True)
        self._chips_scroll.setWidget(self._chips_widget)
        self._chips_scroll.setFrameShape(self._chips_scroll.Shape.NoFrame)
        self._chips_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._chips_scroll.setMaximumHeight(180)

        # ── Notes table ───────────────────────────────────────────────────
        self._notes_label = QLabel("Select a tag to see its notes")
        self._notes_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Title", "Project", "Date", "Folder"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self._table.hide()

        notes_panel = QWidget()
        notes_layout = QVBoxLayout(notes_panel)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(4)
        notes_layout.addWidget(self._notes_label)
        notes_layout.addWidget(self._table, stretch=1)

        # ── Main layout ───────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)
        chips_container = QWidget()
        chips_vbox = QVBoxLayout(chips_container)
        chips_vbox.setContentsMargins(0, 0, 0, 0)
        chips_vbox.setSpacing(8)
        chips_vbox.addWidget(title)
        chips_vbox.addWidget(self._chips_scroll, stretch=1)
        splitter.addWidget(chips_container)
        splitter.addWidget(notes_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)
        root.addWidget(splitter)

    # ── Public API ────────────────────────────────────────────────────────

    def load(self) -> None:
        self._selected_tag = None
        self._tag_buttons.clear()
        self._table.setRowCount(0)
        self._table.hide()
        self._notes_label.setText("Select a tag to see its notes")
        self._notes_label.show()

        # Clear old chips
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        tags = self._tag_repo.list_all()
        if not tags:
            empty = QLabel("No tags yet")
            self._chips_layout.addWidget(empty)
            return

        t = _theme.current()
        accent = t.accent_color
        chip_style = (
            f"QPushButton {{"
            f"  background-color: {accent}22;"
            f"  border: 1px solid {accent};"
            f"  border-radius: 4px;"
            f"  padding: 2px 10px;"
            f"  color: {accent};"
            f"  font-weight: 500;"
            f"}}"
            f"QPushButton:checked {{"
            f"  background-color: {accent};"
            f"  color: {t.app_bg};"
            f"}}"
            f"QPushButton:hover:!checked {{"
            f"  background-color: {accent}44;"
            f"}}"
        )

        for tag in tags:
            btn = QPushButton(f"#{tag.name}")
            btn.setCheckable(True)
            btn.setStyleSheet(chip_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda checked, _tag=tag: self._on_tag_clicked(_tag))
            self._chips_layout.addWidget(btn)
            self._tag_buttons[tag.id] = btn

        self._chips_widget.adjustSize()

    # ── Private helpers ───────────────────────────────────────────────────

    def _on_tag_clicked(self, tag: Tag) -> None:
        # Uncheck previously selected button
        if self._selected_tag is not None and self._selected_tag.id != tag.id:
            prev_btn = self._tag_buttons.get(self._selected_tag.id)
            if prev_btn:
                prev_btn.setChecked(False)

        self._selected_tag = tag
        self._tag_buttons[tag.id].setChecked(True)

        projects = {p.id: p.name for p in self._project_repo.list_all()}
        folders: dict[int, str] = {}
        for p in self._project_repo.list_all():
            for f in self._folder_repo.list_for_project(p.id):
                folders[f.id] = f.name

        notes = self._note_repo.list_for_tag(tag.id)
        self._table.setRowCount(len(notes))

        if notes:
            self._notes_label.hide()
            self._table.show()
        else:
            self._notes_label.setText(f"No notes tagged #{tag.name}")
            self._notes_label.show()
            self._table.hide()

        for row, note in enumerate(notes):
            title_item = QTableWidgetItem(note.title)
            title_item.setData(Qt.ItemDataRole.UserRole, note.id)
            self._table.setItem(row, 0, title_item)
            project_name = projects.get(note.project_id, "—") if note.project_id else "—"
            self._table.setItem(row, 1, QTableWidgetItem(project_name))
            self._table.setItem(row, 2, QTableWidgetItem(note.dt.strftime("%Y-%m-%d %H:%M")))
            folder_name = folders.get(note.folder_id, "—") if note.folder_id else "—"
            self._table.setItem(row, 3, QTableWidgetItem(folder_name))

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is not None:
            self.note_edit_requested.emit(item.data(Qt.ItemDataRole.UserRole))
