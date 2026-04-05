from PySide6.QtCore import Qt, Signal, QByteArray, QMimeData, QRect, QEvent, QTimer, QTime, QPointF
from PySide6.QtGui import QColor, QDrag, QTextCursor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from horizon.dialogs import NewProjectDialog, NewTaskDialog, TaskDetailDialog
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskBucket, TaskPriority, TaskRepository, TaskState


class ProjectListWidget(QWidget):
    project_selected = Signal(object)  # emits Project | None
    home_requested = Signal()

    def __init__(self, repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self.setMinimumWidth(200)

        self._home_btn = QPushButton("Home")
        self._home_btn.clicked.connect(self.home_requested)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)

        self._new_btn = QPushButton("\uff0b New Project")
        self._new_btn.clicked.connect(self._on_new_project)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._home_btn, stretch=0)  # pinned to the top
        layout.addWidget(self._list, stretch=1)      # fills all available vertical space
        layout.addWidget(self._new_btn, stretch=0)   # pinned to the bottom

        self._load_projects()

    def _load_projects(self) -> None:
        self._list.clear()
        for project in self._repo.list_all():
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


_KANBAN_MIME = "application/x-horizon-task-id"
_PRIORITY_ROLE = Qt.ItemDataRole.UserRole + 1
_BAND_WIDTH = 5

_PRIORITY_COLOR: dict[TaskPriority, QColor] = {
    TaskPriority.Low:    QColor("#9e9e9e"),
    TaskPriority.Medium: QColor("#2196f3"),
    TaskPriority.High:   QColor("#f44336"),
}


class KanbanCardDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setClipRect(option.rect)
        opt = QStyleOptionViewItem(option)
        opt.rect = option.rect.adjusted(_BAND_WIDTH + 2, 0, 0, 0)
        super().paint(painter, opt, index)
        priority = index.data(_PRIORITY_ROLE)
        color = _PRIORITY_COLOR.get(priority, QColor("#9e9e9e"))
        band = QRect(option.rect.x(), option.rect.y(), _BAND_WIDTH, option.rect.height())
        painter.fillRect(band, color)
        painter.restore()

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option)
        parent = self.parent()
        if parent is not None:
            vp_width = parent.viewport().width()
            if vp_width > 0:
                opt.rect.setWidth(vp_width - _BAND_WIDTH - 2)
        return super().sizeHint(opt, index)


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
            list_widget.setSpacing(3)
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

    def populate(self, tasks: list) -> None:
        self._selected_task_id = None
        for lw in self._columns.values():
            lw.clear()
        for task in tasks:
            item = QListWidgetItem(task.title)
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            item.setData(_PRIORITY_ROLE, task.priority)
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
    def __init__(self, task_repo: TaskRepository, subtask_repo: SubtaskRepository, parent=None) -> None:
        super().__init__(parent)
        self._task_repo = task_repo
        self._subtask_repo = subtask_repo

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

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self._move_up_btn)
        header_layout.addWidget(self._move_down_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(self._board, stretch=1)

    def load(self) -> None:
        self._board.populate(self._task_repo.list_all())

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
        bucket_tasks = [t for t in self._task_repo.list_all() if t.bucket == task.bucket]
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
            task.title = dialog.title()
            task.description = dialog.description()
            task.state = dialog.state()
            task.priority = dialog.priority()
            task.bucket = dialog.bucket()
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
    def __init__(self, task_repo: TaskRepository, project_repo: ProjectRepository, subtask_repo: SubtaskRepository, parent=None) -> None:
        super().__init__(parent)
        self._task_repo = task_repo
        self._project_repo = project_repo
        self._subtask_repo = subtask_repo
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

        # Name header
        self._name_label = QLabel()
        font = self._name_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self._name_label.setFont(font)
        self._name_label.setWordWrap(True)
        content_layout.addWidget(self._name_label)

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
        content_layout.addLayout(tasks_header)

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
        content_layout.addWidget(self._task_view_stack, stretch=1)

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

    def _on_desc_toggled(self, expanded: bool) -> None:
        self._desc_text.setVisible(expanded)
        self._desc_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _on_view_changed(self, index: int) -> None:
        self._task_view_stack.setCurrentIndex(index)

    def _load_tasks(self, project_id: int) -> None:
        tasks = self._task_repo.list_for_project(project_id)
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

    def load_project(self, project) -> None:
        if project is None:
            self._current_project = None
            self._current_project_id = None
            self._stack.setCurrentIndex(0)
        else:
            self._current_project = project
            self._current_project_id = project.id
            self._name_label.setText(project.name)
            self._desc_raw = project.description
            if self._desc_raw:
                self._desc_text.setMarkdown(self._desc_raw)
            else:
                self._desc_text.setPlainText("")
            self._desc_text.setReadOnly(True)
            self._desc_text.setFrameShape(QFrame.Shape.NoFrame)
            self._load_tasks(project.id)
            self._stack.setCurrentIndex(1)


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
        layout.addStretch(1)
