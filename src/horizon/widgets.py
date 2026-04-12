import base64
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QBuffer, QByteArray, QIODevice, QMimeData, QObject, QRect, QRectF, QSize, QEvent, QTimer, QTime, QPointF, QThread, Slot
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QIcon, QPalette, QPixmap, QTextCursor, QTextDocument, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
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
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QPlainTextEdit,
    QTextEdit,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from horizon import theme as _theme
from horizon.dialogs import AlertDialog, ConfirmDialog, NewProjectDialog, NewTaskDialog, TaskDetailDialog
from horizon.image import ImageRepository
from horizon.note import Note, NoteRepository
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskBucket, TaskPriority, TaskRepository, TaskState

from dataclasses import dataclass, field
from datetime import date as _date, datetime as _datetime

try:
    import win32com.client as _win32com
    import pythoncom as _pythoncom
    _OUTLOOK_AVAILABLE = True
except ImportError:
    _OUTLOOK_AVAILABLE = False


def _parse_attendees(raw: str) -> list[str]:
    """Split a semicolon-separated Outlook attendees string into a clean list of names."""
    if not raw:
        return []
    return [name.strip() for name in raw.split(";") if name.strip()]


@dataclass
class CalendarMeeting:
    start: _datetime
    end: _datetime
    subject: str
    required_attendees: list[str] = field(default_factory=list)
    optional_attendees: list[str] = field(default_factory=list)


_PROJECT_COLOR_ROLE = Qt.ItemDataRole.UserRole + 1


class ProjectListDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        t = _theme.current()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        is_selected = bool(opt.state & QStyle.StateFlag.State_Selected)

        painter.save()

        # Background: own rendering for selection (avoids relying on the system
        # palette which can produce white-on-white when Qt picks up an OS theme);
        # let the system style handle hover/normal states.
        if is_selected:
            painter.fillRect(option.rect, QColor(t.list_selected_bg))
        else:
            bg_opt = QStyleOptionViewItem(opt)
            bg_opt.text = ""
            style = opt.widget.style() if opt.widget else QApplication.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, bg_opt, painter, bg_opt.widget)

        # Draw color band on the left edge
        color_str = index.data(_PROJECT_COLOR_ROLE)
        if color_str:
            painter.fillRect(
                QRect(option.rect.x(), option.rect.y(), _BAND_WIDTH, option.rect.height()),
                QColor(color_str),
            )

        # Draw text indented past the band
        text_x = option.rect.x() + _BAND_WIDTH + 4
        text_rect = QRect(text_x, option.rect.y(), option.rect.right() - text_x, option.rect.height())
        text_color = QColor(t.list_selected_text) if is_selected else opt.palette.text().color()
        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, opt.text)

        painter.restore()


class _NavButton(QPushButton):
    """Sidebar nav button: label on the left, dim ordinal on the right."""

    def __init__(self, label: str, number: str, parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self._number = number
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("nav_btn", True)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        t = _theme.current()
        painter = QPainter(self)
        text_color = QColor(t.text) if (self.isChecked() or self.underMouse()) else QColor(t.tile_project_label)
        r = self.rect().adjusted(12, 0, -12, 0)
        painter.setPen(text_color)
        painter.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)
        painter.setPen(QColor(t.color_btn_border))
        painter.drawText(r, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._number)
        painter.end()


from horizon.titlebar import TitleBar  # noqa: F401  (re-exporté pour app.py)


class ProjectListWidget(QWidget):
    project_selected = Signal(object)  # emits Project | None
    home_requested = Signal()
    notes_requested = Signal()

    def __init__(self, repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self.setMinimumWidth(200)

        self._board_btn = _NavButton("Board", "01")
        self._board_btn.setChecked(True)
        self._board_btn.clicked.connect(self.home_requested)

        self._notes_btn = _NavButton("Notes", "02")
        self._notes_btn.clicked.connect(self.notes_requested)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_group.addButton(self._board_btn)
        self._nav_group.addButton(self._notes_btn)

        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(6, 6, 6, 4)
        nav_layout.setSpacing(6)
        nav_layout.addWidget(self._board_btn)
        nav_layout.addWidget(self._notes_btn)

        self._list = QListWidget()
        self._list.setItemDelegate(ProjectListDelegate(self._list))
        self._list.currentItemChanged.connect(self._on_selection_changed)

        self._show_archived_cb = QCheckBox("Show archived")
        self._show_archived_cb.stateChanged.connect(self._load_projects)

        self._new_btn = QPushButton("New Project")
        self._new_btn.setIcon(_PLUS_ICON)
        self._new_btn.setIconSize(_PLUS_ICON_SIZE)
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
            item.setData(_PROJECT_COLOR_ROLE, project.color)
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
            self._repo.create(name=dialog.name(), description=dialog.description(), color=dialog.color())
            self._load_projects()

    def clear_selection(self) -> None:
        self._list.blockSignals(True)
        self._list.setCurrentRow(-1)
        self._list.blockSignals(False)


_KANBAN_MIME = "application/x-horizon-task-id"
_PRIORITY_ROLE  = Qt.ItemDataRole.UserRole + 1
_PROJECT_ROLE   = Qt.ItemDataRole.UserRole + 2
_SUBTASKS_ROLE  = Qt.ItemDataRole.UserRole + 3
_CHECK_SVG      = ":/icons/check_black.svg"
_PLUS_ICON      = QIcon(":/icons/plus_cyan.svg")
_JETBRAINS_MONO_URL = (Path(__file__).parent / "resources" / "JetBrainsMono-Regular.ttf").as_uri()
_PLUS_ICON_SIZE = QSize(12, 12)
_ARROW_ICON_SIZE = QSize(10, 10)
_BAND_WIDTH  = 5

_RESOURCES_DIR = Path(__file__).parent / "resources"


def _arrow_icon(direction: str) -> QIcon:
    """Charge l'icône de flèche (up/down) depuis le fichier SVG généré par le thème."""
    return QIcon(str(_RESOURCES_DIR / f"arrow_{direction}.svg"))
_TILE_RADIUS = 4
_TILE_MARGIN = 2


class KanbanCardDelegate(QStyledItemDelegate):
    def _project_font(self, base_font) -> QFont:
        font = QFont(base_font)
        font.setItalic(True)
        font.setPointSize(max(base_font.pointSize() - 2, 7))
        return font

    def paint(self, painter, option, index) -> None:
        t = _theme.current()
        tile_bg = QColor(t.tile_bg)
        tile_border = QColor(t.tile_border)
        priority_colors = {
            TaskPriority.Low:    QColor(t.priority_low),
            TaskPriority.Medium: QColor(t.priority_medium),
            TaskPriority.High:   QColor(t.priority_high),
        }

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tile_rect  = option.rect.adjusted(_TILE_MARGIN, _TILE_MARGIN, -_TILE_MARGIN, -_TILE_MARGIN)
        tile_rectf = QRectF(tile_rect)

        # background
        path = QPainterPath()
        path.addRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(tile_bg))
        painter.drawPath(path)

        # clip to tile so selection highlight respects rounded corners
        painter.setClipPath(path)

        priority = index.data(_PRIORITY_ROLE)
        color = priority_colors.get(priority, QColor(t.priority_low))
        band = QRect(tile_rect.x(), tile_rect.y(), _BAND_WIDTH, tile_rect.height())
        painter.fillRect(band, color)

        # border drawn outside clip so the stroke isn't cut off
        painter.restore()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(tile_border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + _TILE_MARGIN * 2)
        return size


_PROJECT_COLOR_SQUARE = 10


class KanbanCardWidget(QWidget):
    def __init__(self, task, subtasks, project_name, subtask_repo, project_color: str = "", parent=None) -> None:
        super().__init__(parent)
        self._priority = task.priority
        self._project_color = project_color
        t = _theme.current()
        self.setStyleSheet(f"""
            QLabel    {{ color: {t.tile_text}; background: transparent; }}
            QCheckBox {{ color: {t.tile_text}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_BAND_WIDTH + 6, 4, 6, 4)
        layout.setSpacing(2)

        title = QLabel(task.title)
        title.setWordWrap(True)
        layout.addWidget(title)

        for subtask in subtasks:
            cb = QCheckBox(subtask.title)
            cb.setChecked(subtask.completed)
            # Give the checkbox a light palette so the system style draws a
            # visible indicator (border + checkmark) on our white card background.
            cb.setStyleSheet(
                f"QCheckBox {{ color: {t.tile_text}; }}"
                f" QCheckBox::indicator {{ border: 1px solid {t.tile_checkbox_border}; border-radius: 2px; }}"
                f" QCheckBox::indicator:checked {{ background-color: {t.tile_checkbox_checked_bg}; border-color: {t.tile_checkbox_checked_border}; image: url({_CHECK_SVG}); }}"
            )
            cb.stateChanged.connect(
                lambda state, sid=subtask.id: subtask_repo.set_completed(
                    sid, state == Qt.CheckState.Checked.value
                )
            )
            layout.addWidget(cb)

        if project_name:
            proj_label = QLabel(project_name)
            proj_font = QFont(proj_label.font())
            proj_font.setItalic(True)
            proj_font.setPointSize(max(proj_font.pointSize() - 2, 7))
            proj_label.setFont(proj_font)
            proj_label.setStyleSheet(f"color: {t.tile_project_label}; background: transparent;")
            layout.addWidget(proj_label)

    def paintEvent(self, event) -> None:
        t = _theme.current()
        tile_bg = QColor(t.tile_bg)
        tile_border = QColor(t.tile_border)
        priority_colors = {
            TaskPriority.Low:    QColor(t.priority_low),
            TaskPriority.Medium: QColor(t.priority_medium),
            TaskPriority.High:   QColor(t.priority_high),
        }

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tile_rect  = self.rect().adjusted(_TILE_MARGIN, _TILE_MARGIN, -_TILE_MARGIN, -_TILE_MARGIN)
        tile_rectf = QRectF(tile_rect)

        # Rounded background
        path = QPainterPath()
        path.addRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(tile_bg))
        painter.drawPath(path)

        # Priority band clipped to rounded rect
        painter.setClipPath(path)
        color = priority_colors.get(self._priority, QColor(t.priority_low))
        painter.fillRect(QRectF(tile_rect.x(), tile_rect.y(), _BAND_WIDTH, tile_rect.height()), color)

        # Project color square — bottom-right corner
        if self._project_color:
            sq = _PROJECT_COLOR_SQUARE
            sq_x = tile_rect.right() - sq - 4
            sq_y = tile_rect.bottom() - sq - 4
            painter.fillRect(QRectF(sq_x, sq_y, sq, sq), QColor(self._project_color))

        painter.setClipping(False)

        # Border
        painter.setPen(QPen(tile_border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)


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

    def populate(self, tasks: list, project_names: dict | None = None, project_colors: dict | None = None, subtask_repo=None) -> None:
        self._selected_task_id = None
        for lw in self._columns.values():
            lw.clear()
        for task in tasks:
            subtasks = subtask_repo.list_for_task(task.id) if subtask_repo else []
            project_name = project_names.get(task.project_id, "") if project_names else ""
            project_color = project_colors.get(task.project_id, "") if project_colors else ""
            card = KanbanCardWidget(task, subtasks, project_name, subtask_repo, project_color=project_color)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            item.setData(_PRIORITY_ROLE, task.priority)
            item.setData(_PROJECT_ROLE, project_name)
            item.setSizeHint(QSize(0, card.sizeHint().height() + _TILE_MARGIN * 2))
            column = self._columns[task.bucket]
            column.addItem(item)
            column.setItemWidget(item, card)

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

        self._move_up_btn = QPushButton()
        self._move_up_btn.setIcon(_arrow_icon("up"))
        self._move_up_btn.setIconSize(_ARROW_ICON_SIZE)
        self._move_up_btn.setFixedWidth(28)
        self._move_up_btn.setToolTip("Move up")
        self._move_up_btn.clicked.connect(self._on_move_up)

        self._move_down_btn = QPushButton()
        self._move_down_btn.setIcon(_arrow_icon("down"))
        self._move_down_btn.setIconSize(_ARROW_ICON_SIZE)
        self._move_down_btn.setFixedWidth(28)
        self._move_down_btn.setToolTip("Move down")
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
        projects = self._project_repo.list_all()
        project_names = {p.id: p.name for p in projects}
        project_colors = {p.id: p.color for p in projects}
        self._board.populate(self._task_repo.list_all(archived_only=self._show_archived_cb.isChecked()), project_names=project_names, project_colors=project_colors, subtask_repo=self._subtask_repo)

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

    def __init__(self, task_repo: TaskRepository, project_repo: ProjectRepository, subtask_repo: SubtaskRepository, note_repo: NoteRepository, prefs=None, parent=None) -> None:
        super().__init__(parent)
        self._task_repo = task_repo
        self._project_repo = project_repo
        self._subtask_repo = subtask_repo
        self._note_repo = note_repo
        self._prefs = prefs
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

        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(24, 24)
        self._color_btn.setToolTip("Choose a color")
        self._color_btn.setStyleSheet(f"border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px;")
        self._color_btn.clicked.connect(self._pick_color)

        name_header = QHBoxLayout()
        name_header.addWidget(self._name_label, stretch=1)
        name_header.addWidget(self._color_btn)
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

        # ── Tasks panel (left side of splitter) ──────────────────────────
        tasks_panel = QGroupBox("Tasks")
        tasks_panel_layout = QVBoxLayout(tasks_panel)
        tasks_panel_layout.setContentsMargins(8, 4, 8, 8)
        tasks_panel_layout.setSpacing(4)

        # Tasks header row: view selector + "+" button right
        tasks_header = QHBoxLayout()
        tasks_header.addStretch()

        self._view_selector = QComboBox()
        self._view_selector.addItem("List")
        self._view_selector.addItem("Board")
        self._view_selector.currentIndexChanged.connect(self._on_view_changed)
        tasks_header.addWidget(self._view_selector)

        self._purge_btn = QPushButton("Purge")
        self._purge_btn.clicked.connect(self._on_purge)
        tasks_header.addWidget(self._purge_btn)

        self._move_up_btn = QPushButton()
        self._move_up_btn.setIcon(_arrow_icon("up"))
        self._move_up_btn.setIconSize(_ARROW_ICON_SIZE)
        self._move_up_btn.setFixedWidth(28)
        self._move_up_btn.setToolTip("Move up")
        self._move_up_btn.clicked.connect(self._on_move_up)

        self._move_down_btn = QPushButton()
        self._move_down_btn.setIcon(_arrow_icon("down"))
        self._move_down_btn.setIconSize(_ARROW_ICON_SIZE)
        self._move_down_btn.setFixedWidth(28)
        self._move_down_btn.setToolTip("Move down")
        self._move_down_btn.clicked.connect(self._on_move_down)

        new_task_btn = QPushButton("New")
        new_task_btn.setIcon(_PLUS_ICON)
        new_task_btn.setIconSize(_PLUS_ICON_SIZE)
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
        notes_panel = QGroupBox("Notes")
        notes_panel_layout = QVBoxLayout(notes_panel)
        notes_panel_layout.setContentsMargins(8, 4, 8, 8)
        notes_panel_layout.setSpacing(4)

        notes_header = QHBoxLayout()
        notes_header.addStretch()
        new_note_btn = QPushButton("New")
        new_note_btn.setIcon(_PLUS_ICON)
        new_note_btn.setIconSize(_PLUS_ICON_SIZE)
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
        h_splitter.setHandleWidth(16)
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

    def _pick_color(self) -> None:
        if self._current_project is None:
            return
        initial = QColor(self._current_project.color) if self._current_project.color else QColor()
        chosen = QColorDialog.getColor(initial=initial, parent=self)
        if chosen.isValid():
            self._current_project.color = chosen.name()
            self._project_repo.update(self._current_project)
            self._color_btn.setStyleSheet(
                f"background-color: {self._current_project.color}; border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px;"
            )
            self.project_renamed.emit()

    def _on_purge(self) -> None:
        if self._current_project_id is None:
            return
        if not ConfirmDialog.ask(
            "Purge completed tasks",
            "Archive all completed tasks in this project?",
            self,
        ):
            return
        tasks = self._task_repo.list_for_project(self._current_project_id)
        for task in tasks:
            if task.state == TaskState.Completed and not task.archived:
                task.archived = True
                self._task_repo.update(task)
        self._load_tasks(self._current_project_id)

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
        if self._prefs is not None and self._current_project_id is not None:
            self._prefs.set_project_view(self._current_project_id, index)
            self._prefs.save()

    def _load_tasks(self, project_id: int) -> None:
        tasks = [t for t in self._task_repo.list_for_project(project_id) if not t.archived]
        self._populate_table(tasks)
        project_colors = {project_id: self._current_project.color} if self._current_project else None
        self._kanban_board.populate(tasks, project_colors=project_colors, subtask_repo=self._subtask_repo)

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
            if project.color:
                self._color_btn.setStyleSheet(
                    f"background-color: {project.color}; border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px;"
                )
            else:
                self._color_btn.setStyleSheet(f"border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px;")
            self._desc_raw = project.description
            if self._desc_raw:
                self._desc_text.setMarkdown(self._desc_raw)
            else:
                self._desc_text.setPlainText("")
            self._desc_text.setReadOnly(True)
            self._desc_text.setFrameShape(QFrame.Shape.NoFrame)
            self._load_tasks(project.id)
            self._load_notes(project.id)
            if self._prefs is not None:
                view_index = self._prefs.get_project_view(project.id)
                self._view_selector.blockSignals(True)
                self._view_selector.setCurrentIndex(view_index)
                self._view_selector.blockSignals(False)
                self._task_view_stack.setCurrentIndex(view_index)
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
                        required_attendees=_parse_attendees(appt.RequiredAttendees),
                        optional_attendees=_parse_attendees(appt.OptionalAttendees),
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

    create_note_requested = Signal(object)  # emits CalendarMeeting

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._meetings: list[CalendarMeeting] = []
        self._layout_cache: list[tuple] = []  # list of (CalendarMeeting, QRect)
        self.setFixedHeight((self.END_HOUR - self.START_HOUR) * self.HOUR_HEIGHT)
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(60 * 1000)
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_timer.start()

    def set_meetings(self, meetings: list[CalendarMeeting]) -> None:
        self._meetings = meetings
        self._layout_cache = []
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

        t = _theme.current()
        painter.fillRect(self.rect(), QColor(t.calendar_bg))

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

            painter.setPen(QColor(t.calendar_label))
            painter.drawText(
                QRect(0, y - 7, self.LABEL_WIDTH - 4, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(QPen(QColor(t.calendar_hour_line), 1))
            painter.drawLine(self.LABEL_WIDTH, y, w, y)

            if hour < self.END_HOUR:
                half_y = y + self.HOUR_HEIGHT // 2
                painter.setPen(QPen(QColor(t.calendar_half_hour_line), 1, Qt.PenStyle.DotLine))
                painter.drawLine(self.LABEL_WIDTH, half_y, w, half_y)

        available_w = event_right - event_left
        self._layout_cache = []
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
            self._layout_cache.append((meeting, rect))
            painter.fillRect(rect, QColor(t.calendar_event_bg))
            painter.setPen(QColor(t.calendar_event_text))
            painter.drawText(
                rect.adjusted(4, 3, -3, -3),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                meeting.subject,
            )

        now = QTime.currentTime()
        current_frac = now.hour() + now.minute() / 60.0
        if self.START_HOUR <= current_frac <= self.END_HOUR:
            cy = int((current_frac - self.START_HOUR) * self.HOUR_HEIGHT)
            painter.setPen(QPen(QColor(t.calendar_now_line), 1))
            painter.drawLine(self.LABEL_WIDTH, cy, w, cy)
            path = QPainterPath()
            path.moveTo(self.LABEL_WIDTH - 1, cy - 5)
            path.lineTo(self.LABEL_WIDTH + 5, cy)
            path.lineTo(self.LABEL_WIDTH - 1, cy + 5)
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(t.calendar_now_line)))
            painter.drawPath(path)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._layout_cache:
            pos = event.position().toPoint()
            for meeting, rect in self._layout_cache:
                if rect.contains(pos):
                    menu = QMenu(self)
                    action = menu.addAction("Create note")
                    action.triggered.connect(
                        lambda checked=False, m=meeting: self.create_note_requested.emit(m)
                    )
                    menu.exec(event.globalPosition().toPoint())
                    return
        super().mousePressEvent(event)


class MeetingsWidget(QWidget):
    _REFRESH_MS = 60 * 1000

    create_note_requested = Signal(object)

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
        self._timeline.create_note_requested.connect(self.create_note_requested)
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

        t = _theme.current()

        # Clock face
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(t.clock_face)))
        painter.drawEllipse(-90, -90, 180, 180)

        # Outer ring
        painter.setPen(QPen(QColor(t.clock_ring), 4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(-90, -90, 180, 180)

        # Hour tick marks
        painter.setPen(QPen(QColor(t.clock_tick_hour), 3))
        for i in range(12):
            painter.drawLine(QPointF(0, -76), QPointF(0, -90))
            painter.rotate(30)

        # Minute tick marks
        painter.setPen(QPen(QColor(t.clock_tick_minute), 1))
        for i in range(60):
            if i % 5 != 0:
                painter.drawLine(QPointF(0, -82), QPointF(0, -90))
            painter.rotate(6)

        # Hour hand
        hour_angle = 30.0 * time.hour() + 0.5 * time.minute()
        painter.save()
        painter.rotate(hour_angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(t.clock_hand)))
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
        painter.setBrush(QBrush(QColor(t.clock_hand)))
        painter.drawConvexPolygon([
            QPointF(-4, 10), QPointF(4, 10),
            QPointF(2, -70), QPointF(-2, -70),
        ])
        painter.restore()

        # Second hand
        second_angle = 6.0 * time.second()
        painter.save()
        painter.rotate(second_angle)
        painter.setPen(QPen(QColor(t.clock_second), 2))
        painter.drawLine(QPointF(0, 15), QPointF(0, -72))
        painter.restore()

        # Center dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(t.clock_second)))
        painter.drawEllipse(-4, -4, 8, 8)


class GShockClockWidget(QWidget):
    _W, _H = 182, 216

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self._W, self._H)
        timer = QTimer(self)
        timer.timeout.connect(self.update)
        timer.start(1000)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = _theme.current()
        self._draw_case(p, t)
        self._draw_buttons(p, t)
        self._draw_bezel(p, t)
        self._draw_lcd(p, t)
        self._draw_brand(p, t)

    def _draw_case(self, p: QPainter, t) -> None:
        case_rect = QRectF(3, 3, 176, 196)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.gshock_case)))
        p.drawRoundedRect(case_rect, 14, 14)
        # Bevel interne
        p.setPen(QPen(QColor(t.gshock_case_shadow), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(case_rect.adjusted(4, 4, -4, -4), 11, 11)
        # Vis de coin
        for cx, cy in ((14, 14), (168, 14), (14, 186), (168, 186)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(t.gshock_screw)))
            p.drawEllipse(QPointF(cx, cy), 5, 5)
            p.setPen(QPen(QColor(t.gshock_case_shadow), 1))
            p.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
            p.drawLine(QPointF(cx, cy - 3), QPointF(cx, cy + 3))

    def _draw_buttons(self, p: QPainter, t) -> None:
        p.setPen(QPen(QColor(t.gshock_case_shadow), 1))
        p.setBrush(QBrush(QColor(t.gshock_screw)))
        for x in (0, 175):
            for y in (48, 78):
                p.drawRoundedRect(QRectF(x, y, 7, 22), 3, 3)

    def _draw_bezel(self, p: QPainter, t) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.gshock_bezel)))
        p.drawRoundedRect(QRectF(11, 13, 160, 166), 8, 8)

    def _draw_lcd(self, p: QPainter, t) -> None:
        lx, ly, lw, lh = 17, 21, 148, 140
        # Fond LCD
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.gshock_lcd_bg)))
        p.drawRoundedRect(QRectF(lx, ly, lw, lh), 4, 4)

        # ── Rangée supérieure : barres signal + CASIO + ALARM ──
        # Barres signal (4 barres de hauteurs croissantes)
        bar_x = lx + 5
        bar_y_base = ly + 17
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.gshock_lcd_fg)))
        for i in range(4):
            bh = 4 + i * 2
            p.drawRect(QRect(bar_x + i * 6, bar_y_base - bh, 4, bh))

        font_small = QFont("JetBrains Mono", 6, QFont.Weight.Bold)
        p.setFont(font_small)
        # CASIO
        p.setPen(QColor(t.gshock_lcd_label))
        p.drawText(QRect(lx + 30, ly + 4, 46, 13),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "CASIO")
        # ALARM
        p.setPen(QColor(t.gshock_lcd_alarm))
        p.drawText(QRect(lx + 76, ly + 4, lw - 80, 13),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "ALARM")

        # Date DD/MM
        font_date = QFont("JetBrains Mono", 7, QFont.Weight.Bold)
        p.setFont(font_date)
        p.setPen(QColor(t.gshock_lcd_fg))
        p.drawText(QRect(lx + 76, ly + 17, lw - 80, 13),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _date.today().strftime("%d/%m"))

        # Séparateur haut
        p.setPen(QPen(QColor(t.gshock_lcd_label), 1))
        p.drawLine(lx + 2, ly + 31, lx + lw - 4, ly + 31)

        # ── Chiffres heure (ghost + réels) ──
        font_time = QFont("JetBrains Mono", 32, QFont.Weight.Bold)
        p.setFont(font_time)
        time_rect = QRect(lx + 4, ly + 33, lw - 8, 62)
        p.setPen(QColor(t.gshock_lcd_dim))
        p.drawText(time_rect, Qt.AlignmentFlag.AlignCenter, "88:88")
        p.setPen(QColor(t.gshock_lcd_fg))
        p.drawText(time_rect, Qt.AlignmentFlag.AlignCenter,
                   QTime.currentTime().toString("hh:mm"))

        # ── Stopwatch ──
        font_sw = QFont("JetBrains Mono", 7, QFont.Weight.Normal)
        p.setFont(font_sw)
        sw_rect = QRect(lx + 4, ly + 97, lw - 8, 16)
        p.setPen(QColor(t.gshock_lcd_dim))
        p.drawText(sw_rect, Qt.AlignmentFlag.AlignCenter, "ST 88:88:88")
        p.setPen(QColor(t.gshock_lcd_fg))
        p.drawText(sw_rect, Qt.AlignmentFlag.AlignCenter, "ST 00:00:00")

        # Séparateur bas
        p.setPen(QPen(QColor(t.gshock_lcd_label), 1))
        p.drawLine(lx + 2, ly + 115, lx + lw - 4, ly + 115)

        # ── Labels bas ──
        font_btm = QFont("JetBrains Mono", 5, QFont.Weight.Normal)
        p.setFont(font_btm)
        p.setPen(QColor(t.gshock_lcd_label))
        p.drawText(QRect(lx + 2, ly + 117, lw - 4, 14),
                   Qt.AlignmentFlag.AlignCenter,
                   "BATTERY   WATER RESIST")

        # Dots décoratifs rouges
        dot_color = QColor("#cc2222")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dot_color))
        for dy in (ly + 50, ly + 70, ly + 90):
            p.drawRect(QRect(lx + 1, dy, 4, 4))
            p.drawRect(QRect(lx + lw - 5, dy, 4, 4))

    def _draw_brand(self, p: QPainter, t) -> None:
        font_brand = QFont("JetBrains Mono", 8, QFont.Weight.Bold)
        p.setFont(font_brand)
        p.setPen(QColor(t.gshock_lcd_fg))
        p.drawText(QRect(3, 196, 176, 14),
                   Qt.AlignmentFlag.AlignCenter, "G-SHOCK")


class RightPanelWidget(QWidget):
    create_note_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        clock = GShockClockWidget()
        layout.addWidget(clock, 0, Qt.AlignmentFlag.AlignHCenter)
        self._meetings = MeetingsWidget()
        self._meetings.create_note_requested.connect(self.create_note_requested)
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

        new_btn = QPushButton("New Note")
        new_btn.setIcon(_PLUS_ICON)
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


class MarkdownBridge(QObject):
    html_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_html: str = ""

    def push_html(self, html: str) -> None:
        self._current_html = html
        self.html_changed.emit(html)

    @Slot(result=str)
    def get_current_html(self) -> str:
        return self._current_html


def _make_preview_html() -> str:
    t = _theme.current()
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @font-face {{
    font-family: 'JetBrains Mono';
    src: url('{_JETBRAINS_MONO_URL}');
    font-weight: normal;
    font-style: normal;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px; line-height: 1.6; color: {t.preview_text};
    background: {t.preview_bg}; padding: 16px 24px; max-width: 860px;
  }}
  h1, h2, h3, h4, h5, h6 {{ margin-top: 1.2em; margin-bottom: 0.4em; font-weight: 600; }}
  h1 {{ font-size: 1.75em; border-bottom: 1px solid {t.preview_border}; padding-bottom: 0.2em; }}
  h2 {{ font-size: 1.4em; border-bottom: 1px solid {t.preview_border}; padding-bottom: 0.15em; }}
  p {{ margin-bottom: 0.8em; }}
  ul, ol {{ margin-left: 1.5em; margin-bottom: 0.8em; }}
  code {{ font-family: 'JetBrains Mono', monospace; background: {t.preview_code_bg}; border-radius: 3px; padding: 0.1em 0.35em; font-size: 0.9em; }}
  pre {{ background: {t.preview_code_bg}; border-radius: 4px; padding: 12px 16px; overflow-x: auto; margin-bottom: 0.8em; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 3px solid {t.preview_blockquote_border}; margin-left: 0; padding-left: 1em; color: {t.preview_blockquote_text}; margin-bottom: 0.8em; }}
  hr {{ border: none; border-top: 1px solid {t.preview_border}; margin: 1em 0; }}
  a {{ color: {t.preview_link}; }}
  table {{ border-collapse: collapse; margin-bottom: 0.8em; width: 100%; }}
  th, td {{ border: 1px solid {t.preview_border}; padding: 6px 12px; }}
  th {{ background: {t.preview_table_header_bg}; font-weight: 600; }}
</style>
</head>
<body>
<div id="content"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
  function applyHtml(html) {{
    var doc = new DOMParser().parseFromString(html, 'text/html');
    document.getElementById('content').innerHTML = doc.body ? doc.body.innerHTML : html;
  }}
  new QWebChannel(qt.webChannelTransport, function(channel) {{
    var bridge = channel.objects.bridge;
    bridge.html_changed.connect(function(html) {{ applyHtml(html); }});
    bridge.get_current_html(function(html) {{ if (html) applyHtml(html); }});
  }});
</script>
</body>
</html>"""


_MD_IMG_RE   = re.compile(r'!\[([^\]]*)\]\(horizon-image://(\d+)\)')
_HTML_PH_RE  = re.compile(r'HORIZONIMG(\d+)END')


def _markdown_to_html(markdown: str, image_repo: ImageRepository | None = None) -> str:
    """Convert markdown to HTML, resolving horizon-image:// references to inline data URIs.

    Qt's QTextDocument.toHtml() does not reliably preserve unknown URL schemes
    (it may encode or drop them).  We therefore substitute image references with
    plain-text placeholders *before* the Qt markdown pass, then replace those
    placeholders with proper <img> tags in the resulting HTML.
    """
    images: dict[int, bytes | None] = {}

    if image_repo is not None:
        def _extract(m: re.Match) -> str:
            img_id = int(m.group(2))
            if img_id not in images:
                images[img_id] = image_repo.get(img_id)
            return f"HORIZONIMG{img_id}END"

        markdown = _MD_IMG_RE.sub(_extract, markdown)

    doc = QTextDocument()
    doc.setMarkdown(markdown)
    html = doc.toHtml()

    if images:
        def _inject(m: re.Match) -> str:
            data = images.get(int(m.group(1)))
            if not data:
                return ""
            b64 = base64.b64encode(data).decode()
            return f'<img src="data:image/png;base64,{b64}" style="max-width:100%;">'

        html = _HTML_PH_RE.sub(_inject, html)

    return html


class MarkdownEditor(QPlainTextEdit):
    def __init__(self, image_repo: ImageRepository, parent=None) -> None:
        super().__init__(parent)
        self._image_repo = image_repo

    def insertFromMimeData(self, source) -> None:
        if source.hasImage():
            image = source.imageData()
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buf, "PNG")
            buf.close()
            image_id = self._image_repo.create(bytes(ba))
            self.insertPlainText(f"![](horizon-image://{image_id})")
        else:
            super().insertFromMimeData(source)


class NoteDetailWidget(QWidget):
    back_requested = Signal()

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, prefs=None, image_repo: ImageRepository | None = None, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._prefs = prefs
        self._image_repo = image_repo
        self._current_note: Note | None = None
        self._body_raw: str = ""
        self._updating_combo = False

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.back_requested)

        self._archive_cb = QCheckBox("Archive")
        self._archive_cb.stateChanged.connect(self._on_archive_changed)

        self._delete_btn = QPushButton("Delete")
        _t = _theme.current()
        self._delete_btn.setStyleSheet(f"color: {_t.delete_btn_text}; background-color: {_t.delete_btn_bg};")
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

        self._editor = MarkdownEditor(image_repo) if image_repo is not None else QPlainTextEdit()
        self._editor.setPlaceholderText("Write markdown here…")
        self._editor.installEventFilter(self)

        self._bridge = MarkdownBridge(self)
        self._channel = QWebChannel(self)

        self._preview = QWebEngineView()
        self._preview.page().setWebChannel(self._channel)
        self._channel.registerObject("bridge", self._bridge)
        self._preview.setHtml(_make_preview_html())

        self._editor.textChanged.connect(self._on_editor_text_changed)

        self._body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._body_splitter.addWidget(self._editor)
        self._body_splitter.addWidget(self._preview)
        self._body_splitter.setStretchFactor(0, 1)
        self._body_splitter.setStretchFactor(1, 1)
        self._body_splitter.splitterMoved.connect(self._on_splitter_moved)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addLayout(project_row)
        layout.addWidget(sep)
        layout.addWidget(self._body_splitter, stretch=1)

        self._restore_splitter_sizes()

    def load_note(self, note: Note, projects: list) -> None:
        self._current_note = note
        self._body_raw = note.body

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

        self._editor.blockSignals(True)
        self._editor.setPlainText(self._body_raw)
        self._editor.blockSignals(False)
        self._bridge.push_html(_markdown_to_html(self._body_raw, self._image_repo))

    def eventFilter(self, obj, event) -> bool:
        if obj is self._editor and event.type() == QEvent.Type.FocusOut:
            self._save_body()
        return super().eventFilter(obj, event)

    def _save_body(self) -> None:
        if self._current_note is None:
            return
        new_body = self._editor.toPlainText()
        if new_body == self._body_raw:
            return
        self._body_raw = new_body
        self._current_note.body = self._body_raw
        self._note_repo.update(self._current_note)

    def _on_editor_text_changed(self) -> None:
        self._bridge.push_html(_markdown_to_html(self._editor.toPlainText(), self._image_repo))

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        if self._prefs is not None:
            self._prefs.note_splitter_sizes = self._body_splitter.sizes()

    def _restore_splitter_sizes(self) -> None:
        if self._prefs is not None:
            saved = self._prefs.note_splitter_sizes
            if saved:
                self._body_splitter.setSizes(saved)

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
        self._current_note.project_id = self._project_combo.currentData()
        self._note_repo.update(self._current_note)
