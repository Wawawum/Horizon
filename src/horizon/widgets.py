from PySide6.QtCore import Qt, Signal, QByteArray, QMimeData, QRect, QRectF, QEvent, QTimer, QTime, QPointF, QThread
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPalette, QTextCursor, QPainter, QPainterPath, QPen, QBrush
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from horizon.dialogs import NewProjectDialog, NewTaskDialog, TaskDetailDialog
from horizon.note import Note, NoteRepository
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskBucket, TaskPriority, TaskRepository, TaskState

from dataclasses import dataclass
from datetime import datetime as _datetime

try:
    import win32com.client as _win32com
    import pythoncom as _pythoncom
    _OUTLOOK_AVAILABLE = True
except ImportError:
    _OUTLOOK_AVAILABLE = False


@dataclass
class CalendarMeeting:
    start: _datetime
    end: _datetime
    subject: str


class ProjectListWidget(QWidget):
    project_selected = Signal(object)  # emits Project | None
    home_requested = Signal()
    notes_requested = Signal()

    def __init__(self, repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self.setMinimumWidth(200)

        self._board_btn = QPushButton("Board")
        self._board_btn.clicked.connect(self.home_requested)

        self._notes_btn = QPushButton("Notes")
        self._notes_btn.clicked.connect(self.notes_requested)

        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        nav_layout.addWidget(self._board_btn)
        nav_layout.addWidget(self._notes_btn)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)

        self._show_archived_cb = QCheckBox("Show archived")
        self._show_archived_cb.stateChanged.connect(self._load_projects)

        self._new_btn = QPushButton("\uff0b New Project")
        self._new_btn.clicked.connect(self._on_new_project)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(4, 2, 4, 2)
        bottom_layout.addWidget(self._show_archived_cb)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self._new_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(nav_layout)                 # Board + Notes buttons at top
        layout.addWidget(self._list, stretch=1)      # fills all available vertical space
        layout.addLayout(bottom_layout)              # archived checkbox + new project button

        self._load_projects()

    def _load_projects(self) -> None:
        show_archived = self._show_archived_cb.isChecked()
        self._list.clear()
        for project in self._repo.list_all():
            if project.archived != show_archived:
                continue
            item = QListWidgetItem(project.name)
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            self._list.addItem(item)

    def _on_selection_changed(
        self, current: QListWidgetItem | None, _: QListWidgetItem | None
    ) -> None:
        if current is None:
            self.project_selected.emit(None)
            return
        project_id = current.data(Qt.ItemDataRole.UserRole)
        self.project_selected.emit(self._repo.get(project_id))

    def _on_new_project(self) -> None:
        dialog = NewProjectDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._repo.create(name=dialog.name(), description=dialog.description())
            self._load_projects()

    def clear_selection(self) -> None:
        self._list.blockSignals(True)
        self._list.setCurrentRow(-1)
        self._list.blockSignals(False)


_KANBAN_MIME = "application/x-horizon-task-id"
_PRIORITY_ROLE = Qt.ItemDataRole.UserRole + 1
_PROJECT_ROLE  = Qt.ItemDataRole.UserRole + 2
_BAND_WIDTH  = 5
_TILE_RADIUS = 4
_TILE_BG     = QColor("#ffffff")
_TILE_BORDER = QColor("#cccccc")
_TILE_MARGIN = 2

_PRIORITY_COLOR: dict[TaskPriority, QColor] = {
    TaskPriority.Low:    QColor("#9e9e9e"),
    TaskPriority.Medium: QColor("#2196f3"),
    TaskPriority.High:   QColor("#f44336"),
}


class KanbanCardDelegate(QStyledItemDelegate):
    def _project_font(self, base_font) -> QFont:
        font = QFont(base_font)
        font.setItalic(True)
        font.setPointSize(max(base_font.pointSize() - 2, 7))
        return font

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tile_rect  = option.rect.adjusted(_TILE_MARGIN, _TILE_MARGIN, -_TILE_MARGIN, -_TILE_MARGIN)
        tile_rectf = QRectF(tile_rect)

        # background
        path = QPainterPath()
        path.addRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_TILE_BG))
        painter.drawPath(path)

        # clip to tile so selection highlight respects rounded corners
        painter.setClipPath(path)

        project_name = index.data(_PROJECT_ROLE)
        proj_line_h = QFontMetrics(self._project_font(option.font)).height() if project_name else 0
        opt = QStyleOptionViewItem(option)
        opt.rect = tile_rect.adjusted(_BAND_WIDTH + 2, 0, 0, -proj_line_h)
        palette = QPalette(opt.palette)
        palette.setColor(QPalette.ColorRole.Text, QColor("#1a1a1a"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1a1a1a"))
        opt.palette = palette
        super().paint(painter, opt, index)

        priority = index.data(_PRIORITY_ROLE)
        color = _PRIORITY_COLOR.get(priority, QColor("#9e9e9e"))
        band = QRect(tile_rect.x(), tile_rect.y(), _BAND_WIDTH, tile_rect.height())
        painter.fillRect(band, color)

        if project_name:
            proj_font = self._project_font(option.font)
            painter.setFont(proj_font)
            painter.setPen(QColor("#555555"))
            proj_rect = QRect(
                tile_rect.x() + _BAND_WIDTH + 4,
                tile_rect.bottom() - proj_line_h,
                tile_rect.width() - _BAND_WIDTH - 6,
                proj_line_h,
            )
            painter.drawText(proj_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, project_name)

        # border drawn outside clip so the stroke isn't cut off
        painter.restore()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(_TILE_BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)
        painter.restore()

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option)
        parent = self.parent()
        if parent is not None:
            vp_width = parent.viewport().width()
            if vp_width > 0:
                opt.rect.setWidth(vp_width - _BAND_WIDTH - 2)
        size = super().sizeHint(opt, index)
        project_name = index.data(_PROJECT_ROLE)
        if project_name:
            size.setHeight(size.height() + QFontMetrics(self._project_font(option.font)).height())
        size.setHeight(size.height() + _TILE_MARGIN * 2)
        return size


class KanbanColumnWidget(QListWidget):
    task_dropped    = Signal(int, object)   # (task_id, target_bucket: TaskBucket)
    tasks_reordered = Signal(object, list)  # (bucket: TaskBucket, task_ids: list[int])

    def __init__(self, bucket: TaskBucket, parent=None) -> None:
        super().__init__(parent)
        self._bucket = bucket
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        task_id: int = item.data(Qt.ItemDataRole.UserRole)
        mime = self.model().mimeData([self.currentIndex()])
        mime.setData(_KANBAN_MIME, QByteArray(str(task_id).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_KANBAN_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_KANBAN_MIME):
            super().dragMoveEvent(event)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_KANBAN_MIME):
            event.ignore()
            return
        task_id = int(event.mimeData().data(_KANBAN_MIME).data().decode())
        source = event.source()
        if isinstance(source, KanbanColumnWidget) and source._bucket == self._bucket:
            event.acceptProposedAction()
            pos = event.pos()
            drop_row = self.count()
            for i in range(self.count()):
                if pos.y() < self.visualItemRect(self.item(i)).center().y():
                    drop_row = i
                    break
            for i in range(self.count()):
                if self.item(i).data(Qt.ItemDataRole.UserRole) == task_id:
                    dragged_item = self.takeItem(i)
                    if i < drop_row:
                        drop_row -= 1
                    break
            else:
                return
            self.insertItem(drop_row, dragged_item)
            self.setCurrentItem(dragged_item)
            task_ids = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
            self.tasks_reordered.emit(self._bucket, task_ids)
            return
        event.acceptProposedAction()
        self.task_dropped.emit(task_id, self._bucket)


class KanbanBoardWidget(QWidget):
    task_edit_requested = Signal(int)           # emits task_id
    task_bucket_changed = Signal(int, object)   # (task_id, new_bucket: TaskBucket)
    task_selected       = Signal(int)           # emits task_id
    tasks_reordered     = Signal(object, list)  # (bucket: TaskBucket, task_ids: list[int])

    COLUMNS = [
        TaskBucket.Inbox,
        TaskBucket.Today,
        TaskBucket.On_Hold,
        TaskBucket.Completed,
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._columns: dict[TaskBucket, QListWidget] = {}
        self._selected_task_id: int | None = None

        board = QWidget()
        board_layout = QHBoxLayout(board)
        board_layout.setSpacing(8)
        board_layout.setContentsMargins(0, 0, 0, 0)

        for bucket in self.COLUMNS:
            col_widget = QWidget()
            col_layout = QVBoxLayout(col_widget)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(4)

            header = QLabel(bucket.value)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            col_layout.addWidget(header)

            list_widget = KanbanColumnWidget(bucket)
            list_widget.setSpacing(5)
            list_widget.setWordWrap(True)
            list_widget.setItemDelegate(KanbanCardDelegate(list_widget))
            list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
            list_widget.task_dropped.connect(self._on_task_dropped)
            list_widget.tasks_reordered.connect(self._on_tasks_reordered)
            list_widget.currentItemChanged.connect(self._on_column_selection_changed)
            col_layout.addWidget(list_widget, stretch=1)

            self._columns[bucket] = list_widget
            board_layout.addWidget(col_widget, stretch=1)

        scroll = QScrollArea()
        scroll.setWidget(board)
        scroll.setWidgetResizable(True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

    def populate(self, tasks: list, project_names: dict | None = None) -> None:
        self._selected_task_id = None
        for lw in self._columns.values():
            lw.clear()
        for task in tasks:
            item = QListWidgetItem(task.title)
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            item.setData(_PRIORITY_ROLE, task.priority)
            if project_names:
                item.setData(_PROJECT_ROLE, project_names.get(task.project_id, ""))
            self._columns[task.bucket].addItem(item)

    def _on_column_selection_changed(
        self, current: QListWidgetItem | None, _previous
    ) -> None:
        sender_widget = self.sender()
        for lw in self._columns.values():
            if lw is not sender_widget:
                lw.blockSignals(True)
                lw.clearSelection()
                lw.setCurrentItem(None)
                lw.blockSignals(False)
        if current is None:
            self._selected_task_id = None
            return
        self._selected_task_id = current.data(Qt.ItemDataRole.UserRole)
        self.task_selected.emit(self._selected_task_id)

    def selected_task_id(self) -> int | None:
        return self._selected_task_id

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self.task_edit_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_task_dropped(self, task_id: int, target_bucket) -> None:
        self.task_bucket_changed.emit(task_id, target_bucket)

    def _on_tasks_reordered(self, bucket, task_ids: list[int]) -> None:
        self.tasks_reordered.emit(bucket, task_ids)


class HomeWidget(QWidget):
    def __init__(self, task_repo: TaskRepository, subtask_repo: SubtaskRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._task_repo = task_repo
        self._subtask_repo = subtask_repo
        self._project_repo = project_repo

        self._board = KanbanBoardWidget()
        self._board.task_edit_requested.connect(self._on_task_edit_requested)
        self._board.task_bucket_changed.connect(self._on_bucket_changed)
        self._board.tasks_reordered.connect(self._on_tasks_reordered)

        title = QLabel("All Tasks")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        self._move_up_btn = QPushButton("↑")
        self._move_up_btn.setFixedWidth(28)
        self._move_up_btn.clicked.connect(self._on_move_up)

        self._move_down_btn = QPushButton("↓")
        self._move_down_btn.setFixedWidth(28)
        self._move_down_btn.clicked.connect(self._on_move_down)

        self._show_archived_cb = QCheckBox("Show archived")
        self._show_archived_cb.stateChanged.connect(self.load)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self._show_archived_cb)
        header_layout.addWidget(self._move_up_btn)
        header_layout.addWidget(self._move_down_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(self._board, stretch=1)

    def load(self) -> None:
        project_names = {p.id: p.name for p in self._project_repo.list_all()}
        self._board.populate(self._task_repo.list_all(archived_only=self._show_archived_cb.isChecked()), project_names=project_names)

    def _on_move_up(self) -> None:
        self._on_move(-1)

    def _on_move_down(self) -> None:
        self._on_move(1)

    def _on_move(self, direction: int) -> None:
        task_id = self._board.selected_task_id()
        if task_id is None:
            return
        task = self._task_repo.get(task_id)
        if task is None:
            return
        bucket_tasks = [t for t in self._task_repo.list_all(archived_only=self._show_archived_cb.isChecked()) if t.bucket == task.bucket]
        idx = next((i for i, t in enumerate(bucket_tasks) if t.id == task_id), None)
        if idx is None:
            return
        neighbor_idx = idx + direction
        if not (0 <= neighbor_idx < len(bucket_tasks)):
            return
        self._task_repo.swap_order(task_id, bucket_tasks[neighbor_idx].id)
        self.load()

    def _on_task_edit_requested(self, task_id: int) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        dialog = TaskDetailDialog(task, self._subtask_repo, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.deleted():
                self._task_repo.delete(task.id)
            else:
                task.title = dialog.title()
                task.description = dialog.description()
                task.state = dialog.state()
                task.priority = dialog.priority()
                task.bucket = dialog.bucket()
                task.archived = dialog.archived()
                self._task_repo.update(task)
            self.load()

    def _on_bucket_changed(self, task_id: int, new_bucket) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        prev_bucket = task.bucket
        task.bucket = new_bucket
        if new_bucket == TaskBucket.Completed:
            task.state = TaskState.Completed
        elif new_bucket == TaskBucket.On_Hold:
            task.state = TaskState.On_Hold
        elif new_bucket in (TaskBucket.Inbox, TaskBucket.Today) and prev_bucket in (TaskBucket.Completed, TaskBucket.On_Hold):
            task.state = TaskState.In_Progress
        self._task_repo.update(task)
        self.load()

    def _on_tasks_reordered(self, bucket, task_ids: list[int]) -> None:
        self._task_repo.set_order_for_bucket(bucket, task_ids)


class ProjectDetailWidget(QWidget):
    note_edit_requested = Signal(int)  # emits note_id
    project_renamed = Signal()

    def __init__(self, task_repo: TaskRepository, project_repo: ProjectRepository, subtask_repo: SubtaskRepository, note_repo: NoteRepository, parent=None) -> None:
        super().__init__(parent)
        self._task_repo = task_repo
        self._project_repo = project_repo
        self._subtask_repo = subtask_repo
        self._note_repo = note_repo
        self._current_project = None
        self._current_project_id: int | None = None
        self._desc_raw: str = ""

        # --- Empty state page ---
        empty_label = QLabel("Select a project from the list")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # --- Content page ---
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(8)

        # Name header (inline-editable)
        self._name_label = QLineEdit()
        self._name_label.setFrame(False)
        font = self._name_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self._name_label.setFont(font)
        self._name_label.editingFinished.connect(self._save_name)

        self._archive_cb = QCheckBox("Archive")
        self._archive_cb.stateChanged.connect(self._on_archive_changed)

        name_header = QHBoxLayout()
        name_header.addWidget(self._name_label, stretch=1)
        name_header.addWidget(self._archive_cb)
        content_layout.addLayout(name_header)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        content_layout.addWidget(sep1)

        # Description toggle
        self._desc_toggle = QToolButton()
        self._desc_toggle.setText("Description")
        self._desc_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._desc_toggle.setArrowType(Qt.ArrowType.RightArrow)  # collapsed by default
        self._desc_toggle.setCheckable(True)
        self._desc_toggle.setChecked(False)
        self._desc_toggle.setAutoRaise(True)
        self._desc_toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._desc_toggle.toggled.connect(self._on_desc_toggled)
        content_layout.addWidget(self._desc_toggle)

        # Description body (no stretch — sizeHint sizes it, task table takes remaining space)
        self._desc_text = QTextEdit()
        self._desc_text.setReadOnly(True)
        self._desc_text.setFrameShape(QFrame.Shape.NoFrame)
        self._desc_text.setVisible(False)
        self._desc_text.installEventFilter(self)
        self._desc_text.viewport().installEventFilter(self)
        self._desc_text.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        content_layout.addWidget(self._desc_text)

        # Separator before tasks
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        content_layout.addWidget(sep2)

        # ── Tasks panel (left side of splitter) ──────────────────────────
        tasks_panel = QWidget()
        tasks_panel_layout = QVBoxLayout(tasks_panel)
        tasks_panel_layout.setContentsMargins(0, 0, 0, 0)
        tasks_panel_layout.setSpacing(4)

        # Tasks header row: label left, view selector + "+" button right
        tasks_header = QHBoxLayout()
        tasks_header.addWidget(QLabel("Tasks"))
        tasks_header.addStretch()

        self._view_selector = QComboBox()
        self._view_selector.addItem("List")
        self._view_selector.addItem("Board")
        self._view_selector.currentIndexChanged.connect(self._on_view_changed)
        tasks_header.addWidget(self._view_selector)

        self._move_up_btn = QPushButton("↑")
        self._move_up_btn.setFixedWidth(28)
        self._move_up_btn.clicked.connect(self._on_move_up)

        self._move_down_btn = QPushButton("↓")
        self._move_down_btn.setFixedWidth(28)
        self._move_down_btn.clicked.connect(self._on_move_down)

        new_task_btn = QPushButton("+")
        new_task_btn.setFixedWidth(28)
        new_task_btn.clicked.connect(self._on_new_task)

        tasks_header.addWidget(self._move_up_btn)
        tasks_header.addWidget(self._move_down_btn)
        tasks_header.addWidget(new_task_btn)
        tasks_panel_layout.addLayout(tasks_header)

        # Task table
        self._task_table = QTableWidget()
        self._task_table.setColumnCount(4)
        self._task_table.setHorizontalHeaderLabels(["Title", "State", "Priority", "Bucket"])
        self._task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._task_table.verticalHeader().setVisible(False)
        self._task_table.horizontalHeader().setStretchLastSection(True)
        self._task_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._task_table.cellDoubleClicked.connect(self._on_task_double_clicked)

        # Kanban board (board view)
        self._kanban_board = KanbanBoardWidget()
        self._kanban_board.task_edit_requested.connect(self._on_kanban_task_edit_requested)
        self._kanban_board.task_bucket_changed.connect(self._on_kanban_bucket_changed)
        self._kanban_board.tasks_reordered.connect(self._on_kanban_tasks_reordered)

        # Inner stack: index 0 = List, index 1 = Board
        self._task_view_stack = QStackedWidget()
        self._task_view_stack.addWidget(self._task_table)
        self._task_view_stack.addWidget(self._kanban_board)
        tasks_panel_layout.addWidget(self._task_view_stack, stretch=1)

        # ── Notes panel (right side of splitter) ─────────────────────────
        notes_panel = QWidget()
        notes_panel_layout = QVBoxLayout(notes_panel)
        notes_panel_layout.setContentsMargins(0, 0, 0, 0)
        notes_panel_layout.setSpacing(4)

        notes_header = QHBoxLayout()
        notes_label = QLabel("Notes")
        notes_header.addWidget(notes_label)
        notes_header.addStretch()
        new_note_btn = QPushButton("+")
        new_note_btn.setFixedWidth(28)
        new_note_btn.clicked.connect(self._on_new_note)
        notes_header.addWidget(new_note_btn)
        notes_panel_layout.addLayout(notes_header)

        self._note_table = QTableWidget()
        self._note_table.setColumnCount(2)
        self._note_table.setHorizontalHeaderLabels(["Title", "Date"])
        self._note_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._note_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._note_table.verticalHeader().setVisible(False)
        self._note_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._note_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._note_table.cellDoubleClicked.connect(self._on_note_double_clicked)
        notes_panel_layout.addWidget(self._note_table, stretch=1)

        # ── Horizontal splitter holding both panels ───────────────────────
        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(tasks_panel)
        h_splitter.addWidget(notes_panel)
        h_splitter.setStretchFactor(0, 3)
        h_splitter.setStretchFactor(1, 2)
        content_layout.addWidget(h_splitter, stretch=1)

        # --- Stack ---
        self._stack = QStackedWidget()
        self._stack.addWidget(empty_label)  # index 0
        self._stack.addWidget(content)      # index 1

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self._stack)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._desc_text.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and self._desc_text.isReadOnly():
                self._enter_desc_edit()
                return True
        if obj is self._desc_text:
            if event.type() == QEvent.Type.FocusOut and not self._desc_text.isReadOnly():
                self._save_and_render_desc()
        return super().eventFilter(obj, event)

    def _enter_desc_edit(self) -> None:
        self._desc_text.setFrameShape(QFrame.Shape.StyledPanel)
        self._desc_text.setReadOnly(False)
        self._desc_text.setPlainText(self._desc_raw)
        self._desc_text.viewport().unsetCursor()
        self._desc_text.moveCursor(QTextCursor.MoveOperation.End)
        self._desc_text.setFocus()

    def _save_and_render_desc(self) -> None:
        if self._current_project is None:
            return
        self._desc_raw = self._desc_text.toPlainText()
        self._current_project.description = self._desc_raw
        self._project_repo.update(self._current_project)
        if self._desc_raw:
            self._desc_text.setMarkdown(self._desc_raw)
        else:
            self._desc_text.setPlainText("")
        self._desc_text.setReadOnly(True)
        self._desc_text.setFrameShape(QFrame.Shape.NoFrame)
        self._desc_text.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def _on_archive_changed(self) -> None:
        if self._current_project is None:
            return
        self._current_project.archived = self._archive_cb.isChecked()
        self._project_repo.update(self._current_project)
        self.project_renamed.emit()

    def _save_name(self) -> None:
        if self._current_project is None:
            return
        new_name = self._name_label.text().strip()
        if not new_name:
            self._name_label.setText(self._current_project.name)
            return
        if new_name == self._current_project.name:
            return
        self._current_project.name = new_name
        self._project_repo.update(self._current_project)
        self.project_renamed.emit()

    def _on_desc_toggled(self, expanded: bool) -> None:
        self._desc_text.setVisible(expanded)
        self._desc_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _on_view_changed(self, index: int) -> None:
        self._task_view_stack.setCurrentIndex(index)

    def _load_tasks(self, project_id: int) -> None:
        tasks = [t for t in self._task_repo.list_for_project(project_id) if not t.archived]
        self._populate_table(tasks)
        self._kanban_board.populate(tasks)

    def _populate_table(self, tasks: list) -> None:
        self._task_table.setRowCount(0)
        self._task_table.setRowCount(len(tasks))
        for i, task in enumerate(tasks):
            title_item = QTableWidgetItem(task.title)
            title_item.setData(Qt.ItemDataRole.UserRole, task.id)
            self._task_table.setItem(i, 0, title_item)
            self._task_table.setItem(i, 1, QTableWidgetItem(task.state.value))
            self._task_table.setItem(i, 2, QTableWidgetItem(task.priority.value))
            self._task_table.setItem(i, 3, QTableWidgetItem(task.bucket.value))

    def _on_task_double_clicked(self, row: int, _col: int) -> None:
        task_id = self._task_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        task = self._task_repo.get(task_id)
        if task is None:
            return
        dialog = TaskDetailDialog(task, self._subtask_repo, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            task.title = dialog.title()
            task.description = dialog.description()
            task.state = dialog.state()
            task.priority = dialog.priority()
            task.bucket = dialog.bucket()
            task.archived = dialog.archived()
            self._task_repo.update(task)
            self._load_tasks(self._current_project_id)

    def _on_kanban_task_edit_requested(self, task_id: int) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        dialog = TaskDetailDialog(task, self._subtask_repo, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            task.title = dialog.title()
            task.description = dialog.description()
            task.state = dialog.state()
            task.priority = dialog.priority()
            task.bucket = dialog.bucket()
            task.archived = dialog.archived()
            self._task_repo.update(task)
            self._load_tasks(self._current_project_id)

    def _on_kanban_tasks_reordered(self, bucket, task_ids: list[int]) -> None:
        self._task_repo.set_order_for_bucket(bucket, task_ids)

    def _on_kanban_bucket_changed(self, task_id: int, new_bucket) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        prev_bucket = task.bucket
        task.bucket = new_bucket
        if new_bucket == TaskBucket.Completed:
            task.state = TaskState.Completed
        elif new_bucket == TaskBucket.On_Hold:
            task.state = TaskState.On_Hold
        elif new_bucket in (TaskBucket.Inbox, TaskBucket.Today) and prev_bucket in (TaskBucket.Completed, TaskBucket.On_Hold):
            task.state = TaskState.In_Progress
        self._task_repo.update(task)
        self._load_tasks(self._current_project_id)

    def _on_move_up(self) -> None:
        self._on_move(-1)

    def _on_move_down(self) -> None:
        self._on_move(1)

    def _on_move(self, direction: int) -> None:
        if self._current_project_id is None:
            return
        if self._task_view_stack.currentIndex() == 0:  # List view
            row = self._task_table.currentRow()
            if row < 0:
                return
            task_id = self._task_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        else:  # Board view
            task_id = self._kanban_board.selected_task_id()
            if task_id is None:
                return
        task = self._task_repo.get(task_id)
        if task is None:
            return
        bucket_tasks = [
            t for t in self._task_repo.list_for_project(self._current_project_id)
            if t.bucket == task.bucket
        ]
        idx = next((i for i, t in enumerate(bucket_tasks) if t.id == task_id), None)
        if idx is None:
            return
        neighbor_idx = idx + direction
        if not (0 <= neighbor_idx < len(bucket_tasks)):
            return
        self._task_repo.swap_order(task_id, bucket_tasks[neighbor_idx].id)
        self._load_tasks(self._current_project_id)

    def _on_new_task(self) -> None:
        if self._current_project_id is None:
            return
        dialog = NewTaskDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._task_repo.create(
                project_id=self._current_project_id,
                title=dialog.title(),
                description=dialog.description(),
                state=dialog.state(),
                priority=dialog.priority(),
                bucket=dialog.bucket(),
            )
            self._load_tasks(self._current_project_id)

    def _load_notes(self, project_id: int) -> None:
        notes = [n for n in self._note_repo.list_all_for_project(project_id) if not n.archived]
        self._note_table.setRowCount(len(notes))
        for row, note in enumerate(notes):
            title_item = QTableWidgetItem(note.title)
            title_item.setData(Qt.ItemDataRole.UserRole, note.id)
            self._note_table.setItem(row, 0, title_item)
            date_item = QTableWidgetItem(note.dt.strftime("%Y-%m-%d %H:%M"))
            self._note_table.setItem(row, 1, date_item)

    def _on_note_double_clicked(self, row: int, _col: int) -> None:
        item = self._note_table.item(row, 0)
        if item is not None:
            self.note_edit_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_new_note(self) -> None:
        if self._current_project_id is None:
            return
        note = self._note_repo.create(project_id=self._current_project_id, title="New Note")
        self._load_notes(self._current_project_id)
        self.note_edit_requested.emit(note.id)

    def load_project(self, project) -> None:
        if project is None:
            self._current_project = None
            self._current_project_id = None
            self._stack.setCurrentIndex(0)
        else:
            self._current_project = project
            self._current_project_id = project.id
            self._name_label.setText(project.name)
            self._archive_cb.setChecked(project.archived)
            self._desc_raw = project.description
            if self._desc_raw:
                self._desc_text.setMarkdown(self._desc_raw)
            else:
                self._desc_text.setPlainText("")
            self._desc_text.setReadOnly(True)
            self._desc_text.setFrameShape(QFrame.Shape.NoFrame)
            self._load_tasks(project.id)
            self._load_notes(project.id)
            self._stack.setCurrentIndex(1)


class OutlookFetchWorker(QThread):
    meetings_ready = Signal(list)   # list[CalendarMeeting]
    fetch_failed = Signal(str)

    def run(self) -> None:
        if not _OUTLOOK_AVAILABLE:
            self.fetch_failed.emit("pywin32 not installed")
            return
        try:
            self._fetch()
        except Exception as exc:
            self.fetch_failed.emit(str(exc))

    def _fetch(self) -> None:
        from datetime import date
        _pythoncom.CoInitialize()
        try:
            outlook = _win32com.Dispatch("Outlook.Application")
            ns = outlook.GetNamespace("MAPI")
            cal = ns.GetDefaultFolder(9)  # olFolderCalendar
            today = date.today()
            start_str = today.strftime("%m/%d/%Y 12:00 AM")
            end_str = today.strftime("%m/%d/%Y 11:59 PM")
            items = cal.Items
            items.IncludeRecurrences = True
            items.Sort("[Start]")
            restricted = items.Restrict(
                f"[Start] >= '{start_str}' AND [Start] <= '{end_str}'"
            )
            meetings: list[CalendarMeeting] = []
            for appt in restricted:
                try:
                    meetings.append(CalendarMeeting(
                        start=appt.Start,
                        end=appt.End,
                        subject=appt.Subject or "(No title)",
                    ))
                except Exception:
                    continue
            self.meetings_ready.emit(meetings)
        finally:
            _pythoncom.CoUninitialize()


class CalendarTimelineWidget(QWidget):
    HOUR_HEIGHT = 60
    LABEL_WIDTH = 44
    START_HOUR = 7
    END_HOUR = 21

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._meetings: list[CalendarMeeting] = []
        self.setFixedHeight((self.END_HOUR - self.START_HOUR) * self.HOUR_HEIGHT)
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(60 * 1000)
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_timer.start()

    def set_meetings(self, meetings: list[CalendarMeeting]) -> None:
        self._meetings = meetings
        self.update()

    @staticmethod
    def _compute_columns(meetings: list) -> list:
        """Returns [(meeting, col_index, total_cols), ...] for side-by-side layout."""
        if not meetings:
            return []
        sorted_m = sorted(meetings, key=lambda m: m.start)
        # Greedily assign each meeting to the first column whose last event ended
        col_ends: list = []
        assignments: list[int] = []
        for m in sorted_m:
            assigned = next(
                (i for i, end in enumerate(col_ends) if m.start >= end), None
            )
            if assigned is None:
                assigned = len(col_ends)
                col_ends.append(m.end)
            else:
                col_ends[assigned] = m.end
            assignments.append(assigned)
        # Group into overlap clusters so each cluster shares the same total_cols
        clusters: list[list[int]] = []
        current: list[int] = [0]
        cluster_end = sorted_m[0].end
        for i in range(1, len(sorted_m)):
            if sorted_m[i].start < cluster_end:
                current.append(i)
                cluster_end = max(cluster_end, sorted_m[i].end)
            else:
                clusters.append(current)
                current = [i]
                cluster_end = sorted_m[i].end
        clusters.append(current)
        result = []
        for cluster in clusters:
            total_cols = max(assignments[i] for i in cluster) + 1
            for i in cluster:
                result.append((sorted_m[i], assignments[i], total_cols))
        return result

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        event_left = self.LABEL_WIDTH + 4
        event_right = w - 2

        painter.fillRect(self.rect(), QColor(18, 18, 18))

        for hour in range(self.START_HOUR, self.END_HOUR + 1):
            y = (hour - self.START_HOUR) * self.HOUR_HEIGHT
            if hour == 0:
                label = "12 AM"
            elif hour < 12:
                label = f"{hour} AM"
            elif hour == 12:
                label = "12 PM"
            else:
                label = f"{hour - 12} PM"

            painter.setPen(QColor(130, 130, 130))
            painter.drawText(
                QRect(0, y - 7, self.LABEL_WIDTH - 4, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(QPen(QColor(55, 55, 55), 1))
            painter.drawLine(self.LABEL_WIDTH, y, w, y)

            if hour < self.END_HOUR:
                half_y = y + self.HOUR_HEIGHT // 2
                painter.setPen(QPen(QColor(40, 40, 40), 1, Qt.PenStyle.DotLine))
                painter.drawLine(self.LABEL_WIDTH, half_y, w, half_y)

        available_w = event_right - event_left
        for meeting, col, total_cols in self._compute_columns(self._meetings):
            start_frac = meeting.start.hour + meeting.start.minute / 60.0
            end_frac = meeting.end.hour + meeting.end.minute / 60.0
            y_top = max(0.0, (start_frac - self.START_HOUR) * self.HOUR_HEIGHT)
            y_bot = min(
                float((self.END_HOUR - self.START_HOUR) * self.HOUR_HEIGHT),
                (end_frac - self.START_HOUR) * self.HOUR_HEIGHT,
            )
            if y_bot <= y_top + 2:
                continue
            col_w = available_w / total_cols
            rect = QRect(
                int(event_left + col * col_w) + 1, int(y_top) + 1,
                int(col_w) - 2, int(y_bot - y_top) - 2,
            )
            painter.fillRect(rect, QColor(150, 20, 20))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                rect.adjusted(4, 3, -3, -3),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                meeting.subject,
            )

        now = QTime.currentTime()
        current_frac = now.hour() + now.minute() / 60.0
        if self.START_HOUR <= current_frac <= self.END_HOUR:
            cy = int((current_frac - self.START_HOUR) * self.HOUR_HEIGHT)
            painter.setPen(QPen(QColor(220, 220, 220), 1))
            painter.drawLine(self.LABEL_WIDTH, cy, w, cy)
            path = QPainterPath()
            path.moveTo(self.LABEL_WIDTH - 1, cy - 5)
            path.lineTo(self.LABEL_WIDTH + 5, cy)
            path.lineTo(self.LABEL_WIDTH - 1, cy + 5)
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(220, 220, 220)))
            painter.drawPath(path)


class MeetingsWidget(QWidget):
    _REFRESH_MS = 60 * 1000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: OutlookFetchWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(4)

        header = QLabel("Today")
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        outer.addWidget(header)

        self._timeline = CalendarTimelineWidget()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._timeline)
        outer.addWidget(self._scroll, stretch=1)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.hide()
        outer.addWidget(self._status_label)

        self._timer = QTimer(self)
        self._timer.setInterval(self._REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = OutlookFetchWorker(self)
        self._worker.meetings_ready.connect(self._on_meetings_ready)
        self._worker.fetch_failed.connect(self._on_fetch_failed)
        self._worker.start()

    def _on_meetings_ready(self, meetings: list) -> None:
        self._status_label.hide()
        self._timeline.set_meetings(meetings)
        QTimer.singleShot(0, self._scroll_to_now)

    def _on_fetch_failed(self, message: str) -> None:
        self._timeline.set_meetings([])
        self._status_label.setText(f"Outlook unavailable\n{message}")
        self._status_label.show()

    def _scroll_to_now(self) -> None:
        now = QTime.currentTime()
        frac = now.hour() + now.minute() / 60.0
        y = int((frac - CalendarTimelineWidget.START_HOUR) * CalendarTimelineWidget.HOUR_HEIGHT)
        self._scroll.verticalScrollBar().setValue(max(0, y - 30))


class AnalogClockWidget(QWidget):
    _SIZE = 160

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        timer = QTimer(self)
        timer.timeout.connect(self.update)
        timer.start(1000)

    def paintEvent(self, event) -> None:
        side = min(self.width(), self.height())
        time = QTime.currentTime()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(side / 200.0, side / 200.0)

        # Clock face
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(-90, -90, 180, 180)

        # Outer ring
        painter.setPen(QPen(QColor(80, 80, 80), 4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(-90, -90, 180, 180)

        # Hour tick marks
        painter.setPen(QPen(QColor(60, 60, 60), 3))
        for i in range(12):
            painter.drawLine(QPointF(0, -76), QPointF(0, -90))
            painter.rotate(30)

        # Minute tick marks
        painter.setPen(QPen(QColor(140, 140, 140), 1))
        for i in range(60):
            if i % 5 != 0:
                painter.drawLine(QPointF(0, -82), QPointF(0, -90))
            painter.rotate(6)

        # Hour hand
        hour_angle = 30.0 * time.hour() + 0.5 * time.minute()
        painter.save()
        painter.rotate(hour_angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(40, 40, 40)))
        painter.drawConvexPolygon([
            QPointF(-5, 10), QPointF(5, 10),
            QPointF(3, -50), QPointF(-3, -50),
        ])
        painter.restore()

        # Minute hand
        minute_angle = 6.0 * time.minute() + 0.1 * time.second()
        painter.save()
        painter.rotate(minute_angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(40, 40, 40)))
        painter.drawConvexPolygon([
            QPointF(-4, 10), QPointF(4, 10),
            QPointF(2, -70), QPointF(-2, -70),
        ])
        painter.restore()

        # Second hand
        second_angle = 6.0 * time.second()
        painter.save()
        painter.rotate(second_angle)
        painter.setPen(QPen(QColor(200, 40, 40), 2))
        painter.drawLine(QPointF(0, 15), QPointF(0, -72))
        painter.restore()

        # Center dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(200, 40, 40)))
        painter.drawEllipse(-4, -4, 8, 8)


class RightPanelWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        clock = AnalogClockWidget()
        layout.addWidget(clock, 0, Qt.AlignmentFlag.AlignHCenter)
        self._meetings = MeetingsWidget()
        layout.addWidget(self._meetings, stretch=1)


class NotesListWidget(QWidget):
    note_edit_requested = Signal(int)  # emits note_id

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo

        title = QLabel("Notes")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        new_btn = QPushButton("+ New Note")
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
            project_item = QTableWidgetItem(project_names.get(note.project_id, ""))
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


class NoteDetailWidget(QWidget):
    back_requested = Signal()

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._current_note: Note | None = None
        self._body_raw: str = ""
        self._updating_combo = False

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.back_requested)

        self._archive_cb = QCheckBox("Archive")
        self._archive_cb.stateChanged.connect(self._on_archive_changed)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setStyleSheet("color: white; background-color: red;")
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)

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

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._title_edit, stretch=1)
        header_layout.addWidget(self._archive_cb)
        header_layout.addWidget(self._delete_btn)
        header_layout.addWidget(back_btn)

        project_row = QHBoxLayout()
        project_row.addWidget(QLabel("Project:"))
        project_row.addWidget(self._project_combo)
        project_row.addStretch()

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)

        self._body_edit = QTextEdit()
        self._body_edit.setReadOnly(True)
        self._body_edit.setFrameShape(QFrame.Shape.NoFrame)
        self._body_edit.installEventFilter(self)
        self._body_edit.viewport().installEventFilter(self)
        self._body_edit.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addLayout(project_row)
        layout.addWidget(sep)
        layout.addWidget(self._body_edit, stretch=1)

    def load_note(self, note: Note, projects: list) -> None:
        self._current_note = note
        self._body_raw = note.body

        self._title_edit.setText(note.title)
        self._archive_cb.setChecked(note.archived)
        self._delete_btn.setVisible(note.archived)

        self._updating_combo = True
        self._project_combo.clear()
        for project in projects:
            self._project_combo.addItem(project.name, userData=project.id)
        idx = self._project_combo.findData(note.project_id)
        if idx >= 0:
            self._project_combo.setCurrentIndex(idx)
        self._updating_combo = False

        self._render_body()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._body_edit.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and self._body_edit.isReadOnly():
                self._enter_body_edit()
                return True
        if obj is self._body_edit:
            if event.type() == QEvent.Type.FocusOut and not self._body_edit.isReadOnly():
                self._save_body()
        return super().eventFilter(obj, event)

    def _enter_body_edit(self) -> None:
        self._body_edit.setFrameShape(QFrame.Shape.StyledPanel)
        self._body_edit.setReadOnly(False)
        self._body_edit.setPlainText(self._body_raw)
        self._body_edit.viewport().unsetCursor()
        self._body_edit.moveCursor(QTextCursor.MoveOperation.End)
        self._body_edit.setFocus()

    def _save_body(self) -> None:
        if self._current_note is None:
            return
        self._body_raw = self._body_edit.toPlainText()
        self._current_note.body = self._body_raw
        self._note_repo.update(self._current_note)
        self._render_body()

    def _render_body(self) -> None:
        self._body_edit.setReadOnly(True)
        self._body_edit.setFrameShape(QFrame.Shape.NoFrame)
        self._body_edit.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        if self._body_raw:
            self._body_edit.setMarkdown(self._body_raw)
        else:
            self._body_edit.setPlainText("")

    def _save_title(self) -> None:
        if self._current_note is None:
            return
        self._current_note.title = self._title_edit.text().strip() or self._current_note.title
        self._title_edit.setText(self._current_note.title)
        self._note_repo.update(self._current_note)

    def _on_archive_changed(self) -> None:
        if self._current_note is None:
            return
        self._current_note.archived = self._archive_cb.isChecked()
        self._note_repo.update(self._current_note)
        self._delete_btn.setVisible(self._current_note.archived)

    def _on_delete_clicked(self) -> None:
        if self._current_note is None or not self._current_note.archived:
            return
        answer = QMessageBox.question(
            self,
            "Delete Note",
            f"Permanently delete \"{self._current_note.title}\"?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._note_repo.delete(self._current_note.id)
            self._current_note = None
            self.back_requested.emit()

    def _on_project_changed(self, _index: int) -> None:
        if self._updating_combo or self._current_note is None:
            return
        project_id = self._project_combo.currentData()
        if project_id is not None:
            self._current_note.project_id = project_id
            self._note_repo.update(self._current_note)
