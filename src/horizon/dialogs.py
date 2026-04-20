from PySide6.QtCore import QByteArray, QEvent, QPoint, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from horizon import theme as _theme
from horizon.task import SubtaskRepository, TaskBucket, TaskPriority, TaskState
from horizon.titlebar import TitleBar

_PLUS_ICON: QIcon | None = None
_PLUS_ICON_SIZE = QSize(12, 12)

def _plus_icon() -> QIcon:
    global _PLUS_ICON
    if _PLUS_ICON is None:
        _PLUS_ICON = _theme.make_icon(":/icons/plus_cyan.svg", _PLUS_ICON_SIZE)
    return _PLUS_ICON


class _DragHandle(QLabel):
    """Grip icon that initiates a QListWidget InternalMove drag."""

    def __init__(self, list_widget: QListWidget, item: QListWidgetItem, parent=None) -> None:
        super().__init__("⠿", parent)
        self._list = list_widget
        self._item = item
        self._start: QPoint | None = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setFixedWidth(18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip("Drag to reorder")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.pos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._start is None:
            return
        if (event.pos() - self._start).manhattanLength() < QApplication.startDragDistance():
            return
        self._list.setCurrentItem(self._item)
        self._list.startDrag(Qt.DropAction.MoveAction)
        event.accept()


class ConfirmDialog(QDialog):
    """Dialog de confirmation frameless (Oui / Annuler)."""

    def __init__(self, title: str, message: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(360)

        msg_label = QLabel(message)
        msg_label.setWordWrap(True)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 16)
        content_layout.setSpacing(16)
        content_layout.addWidget(msg_label)
        content_layout.addWidget(btn_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle=title, show_min_max=False))
        layout.addWidget(content)

    @staticmethod
    def ask(title: str, message: str, parent=None) -> bool:
        return ConfirmDialog(title, message, parent).exec() == QDialog.DialogCode.Accepted


class AlertDialog(QDialog):
    """Dialog d'alerte frameless (Ok uniquement)."""

    def __init__(self, title: str, message: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(360)

        msg_label = QLabel(message)
        msg_label.setWordWrap(True)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btn_box.accepted.connect(self.accept)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 16)
        content_layout.setSpacing(16)
        content_layout.addWidget(msg_label)
        content_layout.addWidget(btn_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle=title, show_min_max=False))
        layout.addWidget(content)

    @staticmethod
    def warn(title: str, message: str, parent=None) -> None:
        AlertDialog(title, message, parent).exec()


class NewProjectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(400)
        self._color: str = ""

        self._name_edit = QLineEdit()
        self._name_edit.setMaxLength(255)
        self._name_edit.setPlaceholderText("Project name")

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText("Description (optional)")
        self._desc_edit.setFixedHeight(80)

        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(24, 24)
        self._color_btn.setToolTip("Choose a color")
        self._color_btn.setStyleSheet(f"border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px;")
        self._color_btn.clicked.connect(self._pick_color)

        color_layout = QHBoxLayout()
        color_layout.addWidget(self._color_btn)
        color_layout.addStretch()

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accepted)
        btn_box.rejected.connect(self.reject)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.addWidget(QLabel("Name"))
        content_layout.addWidget(self._name_edit)
        content_layout.addWidget(QLabel("Description"))
        content_layout.addWidget(self._desc_edit)
        content_layout.addWidget(QLabel("Color"))
        content_layout.addLayout(color_layout)
        content_layout.addWidget(btn_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle="New Project", show_min_max=False))
        layout.addWidget(content)

    def _pick_color(self) -> None:
        from PySide6.QtGui import QColor
        initial = QColor(self._color) if self._color else QColor()
        chosen = QColorDialog.getColor(initial=initial, parent=self)
        if chosen.isValid():
            self._color = chosen.name()
            self._color_btn.setStyleSheet(
                f"background-color: {self._color}; border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px;"
            )

    def _on_accepted(self) -> None:
        if not self._name_edit.text().strip():
            AlertDialog.warn("Validation Error", "Project name cannot be blank.", self)
            return
        self.accept()

    def name(self) -> str:
        return self._name_edit.text()

    def description(self) -> str:
        return self._desc_edit.toPlainText()

    def color(self) -> str:
        return self._color


class NewTaskDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Task")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(400)

        self._title_edit = QLineEdit()
        self._title_edit.setMaxLength(255)
        self._title_edit.setPlaceholderText("Task title")

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText("Description (optional)")
        self._desc_edit.setFixedHeight(80)

        self._state_combo = QComboBox()
        for member in TaskState:
            self._state_combo.addItem(member.value, userData=member)

        self._priority_combo = QComboBox()
        for member in TaskPriority:
            self._priority_combo.addItem(member.value, userData=member)
        medium_idx = self._priority_combo.findData(TaskPriority.Medium)
        if medium_idx >= 0:
            self._priority_combo.setCurrentIndex(medium_idx)

        self._bucket_combo = QComboBox()
        for member in TaskBucket:
            self._bucket_combo.addItem(member.value, userData=member)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accepted)
        btn_box.rejected.connect(self.reject)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.addWidget(QLabel("Title"))
        content_layout.addWidget(self._title_edit)
        content_layout.addWidget(QLabel("Description"))
        content_layout.addWidget(self._desc_edit)
        content_layout.addWidget(QLabel("State"))
        content_layout.addWidget(self._state_combo)
        content_layout.addWidget(QLabel("Priority"))
        content_layout.addWidget(self._priority_combo)
        content_layout.addWidget(QLabel("Bucket"))
        content_layout.addWidget(self._bucket_combo)
        content_layout.addWidget(btn_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle="New Task", show_min_max=False))
        layout.addWidget(content)

    def _on_accepted(self) -> None:
        if not self._title_edit.text().strip():
            AlertDialog.warn("Validation Error", "Task title cannot be blank.", self)
            return
        self.accept()

    def title(self) -> str:
        return self._title_edit.text().strip()

    def description(self) -> str:
        return self._desc_edit.toPlainText()

    def state(self) -> TaskState:
        return self._state_combo.currentData()

    def priority(self) -> TaskPriority:
        return self._priority_combo.currentData()

    def bucket(self) -> TaskBucket:
        return self._bucket_combo.currentData()


class TaskDetailDialog(QDialog):
    def __init__(self, task, subtask_repo: SubtaskRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Task Details")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(400)

        self._task_id: int = task.id
        self._subtask_repo = subtask_repo

        self._title_edit = QLineEdit(task.title)
        self._title_edit.setMaxLength(255)

        self._desc_raw: str = task.description
        self._desc_edit = QTextEdit()
        self._desc_edit.setMinimumHeight(80)
        self._desc_edit.setReadOnly(True)
        self._desc_edit.setFrameShape(QFrame.Shape.NoFrame)
        if self._desc_raw:
            self._desc_edit.setMarkdown(self._desc_raw)
        self._desc_edit.installEventFilter(self)
        self._desc_edit.viewport().installEventFilter(self)
        self._desc_edit.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        self._state_combo = QComboBox()
        for member in TaskState:
            self._state_combo.addItem(member.value, userData=member)
        self._state_combo.setCurrentIndex(self._state_combo.findData(task.state))

        self._priority_combo = QComboBox()
        for member in TaskPriority:
            self._priority_combo.addItem(member.value, userData=member)
        self._priority_combo.setCurrentIndex(self._priority_combo.findData(task.priority))

        self._bucket_combo = QComboBox()
        for member in TaskBucket:
            self._bucket_combo.addItem(member.value, userData=member)
        self._bucket_combo.setCurrentIndex(self._bucket_combo.findData(task.bucket))

        # --- Sub-tasks section ---
        subtasks_header = QHBoxLayout()
        subtasks_header.addWidget(QLabel("Sub-tasks"))
        subtasks_header.addStretch()
        add_subtask_btn = QPushButton("New")
        add_subtask_btn.setIcon(_plus_icon())
        add_subtask_btn.setIconSize(_PLUS_ICON_SIZE)
        add_subtask_btn.clicked.connect(self._show_new_subtask_input)
        subtasks_header.addWidget(add_subtask_btn)

        self._subtask_list = QListWidget()
        self._subtask_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._subtask_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._subtask_list.setSpacing(1)
        self._subtask_list.model().rowsMoved.connect(self._on_subtasks_reordered)

        self._new_subtask_edit = QLineEdit()
        self._new_subtask_edit.setMaxLength(255)
        self._new_subtask_edit.setPlaceholderText("New sub-task…")
        self._new_subtask_edit.setVisible(False)
        self._new_subtask_edit.installEventFilter(self)

        self._archive_cb = QCheckBox("Archive")
        self._archive_cb.setChecked(task.archived)
        self._archive_cb.stateChanged.connect(self._on_archive_changed)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setStyleSheet(f"color: {_theme.current().delete_btn_text}; background-color: {_theme.current().delete_btn_bg};")
        self._delete_btn.setVisible(task.archived)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        self._deleted = False

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accepted)
        btn_box.rejected.connect(self.reject)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.addWidget(QLabel("Title"))
        content_layout.addWidget(self._title_edit)
        content_layout.addWidget(QLabel("Description"))
        content_layout.addWidget(self._desc_edit)
        content_layout.addWidget(QLabel("State"))
        content_layout.addWidget(self._state_combo)
        content_layout.addWidget(QLabel("Priority"))
        content_layout.addWidget(self._priority_combo)
        content_layout.addWidget(QLabel("Bucket"))
        content_layout.addWidget(self._bucket_combo)
        content_layout.addLayout(subtasks_header)
        content_layout.addWidget(self._subtask_list)
        content_layout.addWidget(self._new_subtask_edit)
        archive_row = QHBoxLayout()
        archive_row.addWidget(self._archive_cb)
        archive_row.addWidget(self._delete_btn)
        archive_row.addStretch()
        content_layout.addLayout(archive_row)
        content_layout.addWidget(btn_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle="Task Details", show_min_max=False))
        layout.addWidget(content)

        self._load_subtasks()

    def _load_subtasks(self) -> None:
        self._subtask_list.model().blockSignals(True)
        self._subtask_list.clear()
        for subtask in self._subtask_repo.list_for_task(self._task_id):
            subtask_id = subtask.id

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, subtask_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 0, 4, 0)

            handle = _DragHandle(self._subtask_list, item)
            row_layout.addWidget(handle)

            cb = QCheckBox(subtask.title)
            cb.setChecked(subtask.completed)
            cb.stateChanged.connect(
                lambda state, sid=subtask_id: self._subtask_repo.set_completed(
                    sid, state == Qt.CheckState.Checked.value
                )
            )
            row_layout.addWidget(cb)
            row_layout.addStretch()

            del_btn = QPushButton("Delete")
            del_btn.setVisible(False)
            del_btn.clicked.connect(lambda checked, sid=subtask_id: self._delete_subtask(sid))
            row_layout.addWidget(del_btn)

            row._del_btn = del_btn  # type: ignore[attr-defined]
            row.installEventFilter(self)

            item.setSizeHint(QSize(0, row.sizeHint().height()))
            self._subtask_list.addItem(item)
            self._subtask_list.setItemWidget(item, row)

        self._subtask_list.model().blockSignals(False)

    def _on_subtasks_reordered(self) -> None:
        subtask_ids = [
            self._subtask_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._subtask_list.count())
        ]
        self._subtask_repo.set_order_for_task(self._task_id, subtask_ids)

    def _delete_subtask(self, subtask_id: int) -> None:
        self._subtask_repo.delete(subtask_id)
        self._load_subtasks()

    def _show_new_subtask_input(self) -> None:
        self._new_subtask_edit.setVisible(True)
        QTimer.singleShot(0, self._new_subtask_edit.setFocus)

    def eventFilter(self, obj, event) -> bool:
        del_btn = getattr(obj, "_del_btn", None)
        if del_btn is not None:
            if event.type() == QEvent.Type.Enter:
                del_btn.setVisible(True)
            elif event.type() == QEvent.Type.Leave:
                del_btn.setVisible(False)
        if obj is getattr(self, "_new_subtask_edit", None):
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    title = obj.text().strip()
                    if title:
                        self._subtask_repo.create(self._task_id, title)
                        self._load_subtasks()
                    obj.clear()
                    return True  # consume — prevents Enter from triggering OK
            elif event.type() == QEvent.Type.FocusOut:
                title = obj.text().strip()
                if title:
                    self._subtask_repo.create(self._task_id, title)
                    self._load_subtasks()
                obj.clear()
                obj.setVisible(False)
        if obj is self._desc_edit.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and self._desc_edit.isReadOnly():
                self._enter_desc_edit()
                return True
        if obj is self._desc_edit:
            if event.type() == QEvent.Type.FocusOut and not self._desc_edit.isReadOnly():
                self._save_and_render_desc()
        return super().eventFilter(obj, event)

    def _enter_desc_edit(self) -> None:
        self._desc_edit.setFrameShape(QFrame.Shape.StyledPanel)
        self._desc_edit.setReadOnly(False)
        self._desc_edit.setPlainText(self._desc_raw)
        self._desc_edit.viewport().unsetCursor()
        self._desc_edit.moveCursor(QTextCursor.MoveOperation.End)
        self._desc_edit.setFocus()

    def _save_and_render_desc(self) -> None:
        self._desc_raw = self._desc_edit.toPlainText()
        if self._desc_raw:
            self._desc_edit.setMarkdown(self._desc_raw)
        else:
            self._desc_edit.setPlainText("")
        self._desc_edit.setReadOnly(True)
        self._desc_edit.setFrameShape(QFrame.Shape.NoFrame)
        self._desc_edit.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def _on_accepted(self) -> None:
        if not self._title_edit.text().strip():
            AlertDialog.warn("Validation Error", "Task title cannot be blank.", self)
            return
        self.accept()

    def title(self) -> str:
        return self._title_edit.text().strip()

    def description(self) -> str:
        return self._desc_raw

    def state(self) -> TaskState:
        return self._state_combo.currentData()

    def priority(self) -> TaskPriority:
        return self._priority_combo.currentData()

    def bucket(self) -> TaskBucket:
        return self._bucket_combo.currentData()

    def archived(self) -> bool:
        return self._archive_cb.isChecked()

    def deleted(self) -> bool:
        return self._deleted

    def _on_archive_changed(self) -> None:
        self._delete_btn.setVisible(self._archive_cb.isChecked())

    def _on_delete_clicked(self) -> None:
        if ConfirmDialog.ask(
            "Delete Task",
            f"Permanently delete \"{self._title_edit.text().strip()}\"?\nThis cannot be undone.",
            self,
        ):
            self._deleted = True
            self.accept()


class NewFolderDialog(QDialog):
    def __init__(self, title: str = "New Folder", initial_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(360)

        self._name_edit = QLineEdit(initial_name)
        self._name_edit.setMaxLength(255)
        self._name_edit.setPlaceholderText("Folder name")
        self._name_edit.selectAll()

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accepted)
        btn_box.rejected.connect(self.reject)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.addWidget(QLabel("Name"))
        content_layout.addWidget(self._name_edit)
        content_layout.addWidget(btn_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle=title, show_min_max=False))
        layout.addWidget(content)

    def _on_accepted(self) -> None:
        if not self._name_edit.text().strip():
            AlertDialog.warn("Validation Error", "Folder name cannot be blank.", self)
            return
        self.accept()

    def name(self) -> str:
        return self._name_edit.text().strip()


class _ZoomableGraphicsView(QGraphicsView):
    _ZOOM_FACTOR = 1.15
    _MIN_SCALE   = 0.05
    _MAX_SCALE   = 20.0

    def __init__(self, scene: QGraphicsScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._scale = 1.0

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return super().wheelEvent(event)
        factor = self._ZOOM_FACTOR if delta > 0 else 1.0 / self._ZOOM_FACTOR
        new_scale = self._scale * factor
        if self._MIN_SCALE <= new_scale <= self._MAX_SCALE:
            self._scale = new_scale
            self.scale(factor, factor)
        event.accept()

    def zoom_by(self, factor: float) -> None:
        new_scale = self._scale * factor
        if self._MIN_SCALE <= new_scale <= self._MAX_SCALE:
            self._scale = new_scale
            self.scale(factor, factor)

    def fit(self, rect: QRectF) -> None:
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._scale = self.transform().m11()


class ImageViewerDialog(QDialog):
    _ZOOM_IN  = 1.2
    _ZOOM_OUT = 1.0 / 1.2

    def __init__(self, data_uri: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.resize(860, 640)

        pixmap = QPixmap()
        if data_uri.startswith("data:"):
            _, _, b64 = data_uri.partition(",")
            pixmap.loadFromData(QByteArray.fromBase64(b64.encode("ascii")))

        scene = QGraphicsScene(self)
        scene.addPixmap(pixmap)
        scene.setSceneRect(QRectF(pixmap.rect()))
        self._scene_rect = scene.sceneRect()

        self._view = _ZoomableGraphicsView(scene, self)

        zoom_in_btn  = QPushButton("+")
        zoom_out_btn = QPushButton("−")
        fit_btn      = QPushButton("Fit")
        for btn in (zoom_in_btn, zoom_out_btn, fit_btn):
            btn.setFixedWidth(40)

        zoom_in_btn.clicked.connect(lambda: self._view.zoom_by(self._ZOOM_IN))
        zoom_out_btn.clicked.connect(lambda: self._view.zoom_by(self._ZOOM_OUT))
        fit_btn.clicked.connect(lambda: self._view.fit(self._scene_rect))

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 6, 8, 6)
        toolbar.addWidget(zoom_out_btn)
        toolbar.addWidget(zoom_in_btn)
        toolbar.addWidget(fit_btn)
        toolbar.addStretch()

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addLayout(toolbar)
        cl.addWidget(self._view, stretch=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle="Image", show_min_max=True))
        layout.addWidget(content)

        QTimer.singleShot(0, lambda: self._view.fit(self._scene_rect))
