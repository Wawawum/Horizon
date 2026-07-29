import re as _re
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRectF, QSize, QTimer, QUrl, Qt
from PySide6.QtWebEngineWidgets import QWebEngineView
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
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QStackedWidget,
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

_PENCIL_ICON: QIcon | None = None
_TRASH_ICON: QIcon | None = None
_SUBTASK_BTN_ICON_SIZE = QSize(8, 8)

def _pencil_icon() -> QIcon:
    global _PENCIL_ICON
    if _PENCIL_ICON is None:
        _PENCIL_ICON = _theme.make_icon(":/icons/pencil_cyan.svg", _SUBTASK_BTN_ICON_SIZE)
    return _PENCIL_ICON

def _trash_icon() -> QIcon:
    global _TRASH_ICON
    if _TRASH_ICON is None:
        _TRASH_ICON = _theme.make_icon(":/icons/trash_cyan.svg", _SUBTASK_BTN_ICON_SIZE)
    return _TRASH_ICON


_TASK_TAG_RE = _re.compile(r'\{#([A-Za-z0-9_\-]+)\}')


def _render_desc_with_tags(widget: QTextEdit, desc_raw: str) -> None:
    accent = _theme.current().accent_color
    widget.setMarkdown(desc_raw)
    html = widget.toHtml()

    def replacer(m: _re.Match) -> str:
        return (
            f'<span style="display:inline; background-color:{accent}22;'
            f' border:1px solid {accent};'
            f' padding:1px 7px; color:{accent};'
            f' font-size:small; font-weight:500;">#{m.group(1)}</span>'
        )

    widget.setHtml(_TASK_TAG_RE.sub(replacer, html))


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
            _render_desc_with_tags(self._desc_edit, self._desc_raw)
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
        self._subtask_list.viewport().installEventFilter(self)

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

            cb = QCheckBox()
            cb.setChecked(subtask.completed)
            cb.stateChanged.connect(
                lambda state, sid=subtask_id: self._subtask_repo.set_completed(
                    sid, state == Qt.CheckState.Checked.value
                )
            )
            row_layout.addWidget(cb)

            lbl = QLabel(subtask.title)
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            lbl.mousePressEvent = lambda _e, c=cb: c.toggle()
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)

            edit_field = QLineEdit(subtask.title)
            edit_field._subtask_id = subtask_id  # type: ignore[attr-defined]
            edit_field._label = lbl              # type: ignore[attr-defined]
            edit_field.installEventFilter(self)

            stack = QStackedWidget()
            stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            stack.addWidget(lbl)        # index 0 — lecture
            stack.addWidget(edit_field) # index 1 — édition
            edit_field._stack = stack   # type: ignore[attr-defined]
            row_layout.addWidget(stack)

            _icon_btn_style = "QPushButton { min-height: 0; padding: 0; border-radius: 2px; }"

            edit_btn = QPushButton()
            edit_btn.setIcon(_pencil_icon())
            edit_btn.setIconSize(_SUBTASK_BTN_ICON_SIZE)
            edit_btn.setFixedSize(16, 16)
            edit_btn.setStyleSheet(_icon_btn_style)
            edit_btn.setToolTip("Modifier")
            edit_btn.setVisible(False)
            edit_btn.clicked.connect(lambda checked, s=stack, e=edit_field: self._start_subtask_edit(s, e))
            row_layout.addWidget(edit_btn)

            del_btn = QPushButton()
            del_btn.setIcon(_trash_icon())
            del_btn.setIconSize(_SUBTASK_BTN_ICON_SIZE)
            del_btn.setFixedSize(16, 16)
            del_btn.setStyleSheet(_icon_btn_style)
            del_btn.setToolTip("Supprimer")
            del_btn.setVisible(False)
            del_btn.clicked.connect(lambda checked, sid=subtask_id: self._delete_subtask(sid))
            row_layout.addWidget(del_btn)

            row._hover_btns = [edit_btn, del_btn]  # type: ignore[attr-defined]
            row.installEventFilter(self)

            item.setSizeHint(QSize(0, row.sizeHint().height()))
            self._subtask_list.addItem(item)
            self._subtask_list.setItemWidget(item, row)

        QTimer.singleShot(0, self._update_subtask_heights)
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

    def _start_subtask_edit(self, stack: QStackedWidget, edit: QLineEdit) -> None:
        stack.setCurrentIndex(1)
        edit.selectAll()
        edit.setFocus()

    def _save_subtask_edit(self, edit: QLineEdit) -> None:
        title = edit.text().strip()
        if title:
            self._subtask_repo.update_title(edit._subtask_id, title)  # type: ignore[attr-defined]
            edit._label.setText(title)                                 # type: ignore[attr-defined]
        edit._stack.setCurrentIndex(0)                                 # type: ignore[attr-defined]

    def _cancel_subtask_edit(self, edit: QLineEdit) -> None:
        edit.setText(edit._label.text())  # type: ignore[attr-defined]
        edit._stack.setCurrentIndex(0)    # type: ignore[attr-defined]

    def _update_subtask_heights(self) -> None:
        vw = self._subtask_list.viewport().width()
        if vw <= 0:
            return
        for i in range(self._subtask_list.count()):
            item = self._subtask_list.item(i)
            row = self._subtask_list.itemWidget(item)
            if row is None:
                continue
            row.setFixedWidth(vw)
            h = row.sizeHint().height()
            row.setMinimumWidth(0)
            row.setMaximumWidth(16777215)
            item.setSizeHint(QSize(0, h))

    def _show_new_subtask_input(self) -> None:
        self._new_subtask_edit.setVisible(True)
        QTimer.singleShot(0, self._new_subtask_edit.setFocus)

    def eventFilter(self, obj, event) -> bool:
        hover_btns = getattr(obj, "_hover_btns", None)
        if hover_btns is not None:
            if event.type() == QEvent.Type.Enter:
                for btn in hover_btns:
                    btn.setVisible(True)
            elif event.type() == QEvent.Type.Leave:
                for btn in hover_btns:
                    btn.setVisible(False)
        if getattr(obj, "_subtask_id", None) is not None:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._save_subtask_edit(obj)
                    return True
                elif event.key() == Qt.Key.Key_Escape:
                    self._cancel_subtask_edit(obj)
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                self._save_subtask_edit(obj)
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
        if hasattr(self, '_subtask_list') and obj is self._subtask_list.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._update_subtask_heights)
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
            _render_desc_with_tags(self._desc_edit, self._desc_raw)
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

    def __init__(self, data_uri: str, parent=None, image_id: int | None = None, search_repo=None, note_repo=None, proj_repo=None) -> None:
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

        if image_id is not None and search_repo is not None:
            self._related_btn = QPushButton("Related notes")
            self._related_btn.clicked.connect(self._toggle_related)
            toolbar.addWidget(self._related_btn)
            self._image_id = image_id
            self._search_repo = search_repo
            self._note_repo = note_repo
            self._proj_repo = proj_repo
        else:
            self._related_btn = None
            self._image_id = None
            self._search_repo = None
            self._note_repo = None
            self._proj_repo = None

        image_page = QWidget()
        ip = QVBoxLayout(image_page)
        ip.setContentsMargins(0, 0, 0, 0)
        ip.setSpacing(0)
        ip.addWidget(self._view, stretch=1)

        self._notes_table = QTableWidget()
        self._notes_table.setColumnCount(2)
        self._notes_table.setHorizontalHeaderLabels(["Project", "Note"])
        self._notes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._notes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._notes_table.verticalHeader().setVisible(False)
        self._notes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._notes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self._selected_note_id: int | None = None
        self._notes_table.cellDoubleClicked.connect(self._on_note_double_clicked)

        self._stack = QStackedWidget()
        self._stack.addWidget(image_page)        # index 0 — image
        self._stack.addWidget(self._notes_table) # index 1 — related notes

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addLayout(toolbar)
        cl.addWidget(self._stack, stretch=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle="Image", show_min_max=True))
        layout.addWidget(content)

        QTimer.singleShot(0, lambda: self._view.fit(self._scene_rect))

    def _toggle_related(self) -> None:
        if self._stack.currentIndex() == 0:
            self._load_related_notes()
            self._stack.setCurrentIndex(1)
            self._related_btn.setText("← Image")
        else:
            self._stack.setCurrentIndex(0)
            self._related_btn.setText("Related notes")

    @property
    def selected_note_id(self) -> int | None:
        return self._selected_note_id

    def _on_note_double_clicked(self, row: int, _col: int) -> None:
        item = self._notes_table.item(row, 1)
        if item is None:
            return
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is not None:
            self._selected_note_id = note_id
            self.accept()

    def _load_related_notes(self) -> None:
        self._notes_table.setRowCount(0)
        if self._note_repo is None:
            return

        project_names: dict[int, str] = {}
        if self._proj_repo is not None:
            project_names = {p.id: p.name for p in self._proj_repo.list_all()}

        notes = self._note_repo.find_referencing_image(self._image_id)
        if not notes:
            self._notes_table.setRowCount(1)
            self._notes_table.setItem(0, 0, QTableWidgetItem(""))
            self._notes_table.setItem(0, 1, QTableWidgetItem("No related notes found."))
            return

        self._notes_table.setRowCount(len(notes))
        for row, note in enumerate(notes):
            project_name = project_names.get(note.project_id, "") if note.project_id else ""
            self._notes_table.setItem(row, 0, QTableWidgetItem(project_name))
            title_item = QTableWidgetItem(note.title)
            title_item.setData(Qt.ItemDataRole.UserRole, note.id)
            self._notes_table.setItem(row, 1, title_item)


class SelectTemplatesDialog(QDialog):
    """Dialog listing deliverable templates with checkboxes for multi-selection."""

    def __init__(self, templates, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(400)
        self._templates = sorted(templates, key=lambda t: t.title.lower())
        self._checkboxes: list[QCheckBox] = []

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for tmpl in self._templates:
            item = QListWidgetItem(self._list)
            cb = QCheckBox(tmpl.title)
            item.setSizeHint(cb.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, cb)
            self._checkboxes.append(cb)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(8)
        cl.addWidget(self._list, stretch=1)
        cl.addWidget(btn_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle="Select Templates"))
        layout.addWidget(content)

    def selected_templates(self):
        return [
            tmpl
            for tmpl, cb in zip(self._templates, self._checkboxes)
            if cb.isChecked()
        ]

    @classmethod
    def ask(cls, templates, parent=None):
        dlg = cls(templates, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.selected_templates()
        return []


_MERMAID_JS_PATH = Path(__file__).parent / "resources" / "mermaid.min.js"


class MermaidViewerDialog(QDialog):
    _ZOOM_IN  = 1.2
    _ZOOM_OUT = 1.0 / 1.2

    def __init__(self, source: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.resize(900, 700)

        self._view = QWebEngineView(self)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        zoom_in_btn  = QPushButton("+")
        zoom_out_btn = QPushButton("−")
        fit_btn      = QPushButton("Fit")
        for btn in (zoom_in_btn, zoom_out_btn, fit_btn):
            btn.setFixedWidth(40)

        zoom_in_btn.clicked.connect(lambda: self._run_js("zoomIn()"))
        zoom_out_btn.clicked.connect(lambda: self._run_js("zoomOut()"))
        fit_btn.clicked.connect(lambda: self._run_js("resetView()"))

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
        layout.addWidget(TitleBar(self, subtitle="Diagramme", show_min_max=True))
        layout.addWidget(content)

        html = self._build_html(source)
        self._view.setHtml(html, QUrl(_MERMAID_JS_PATH.parent.as_uri() + "/"))

    def _run_js(self, code: str) -> None:
        self._view.page().runJavaScript(code)

    @staticmethod
    def _build_html(source: str) -> str:
        import html as _h
        from horizon import theme as _t_mod
        t = _t_mod.current()
        mermaid_theme = "dark" if t.is_dark else "default"
        mermaid_js_url = _MERMAID_JS_PATH.as_uri()
        escaped_source = _h.escape(source)
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {t.preview_bg}; overflow: hidden; width: 100vw; height: 100vh; }}
  #viewport {{ width: 100%; height: 100%; overflow: hidden; position: relative; cursor: grab; user-select: none; }}
  #viewport.grabbing {{ cursor: grabbing; }}
  #canvas {{
    position: absolute;
    top: 50%; left: 50%;
    transform-origin: center center;
    transform: translate(-50%, -50%) scale(1);
  }}
  .mermaid svg {{ display: block; }}
</style>
</head>
<body>
<div id="viewport">
  <div id="canvas">
    <div class="mermaid">{escaped_source}</div>
  </div>
</div>
<script src="{mermaid_js_url}"></script>
<script>
  mermaid.initialize({{ startOnLoad: false, theme: '{mermaid_theme}', securityLevel: 'loose' }});

  var scale = 1, tx = 0, ty = 0;
  var canvas = document.getElementById('canvas');
  var viewport = document.getElementById('viewport');

  function applyTransform() {{
    canvas.style.transform =
      'translate(calc(-50% + ' + tx + 'px), calc(-50% + ' + ty + 'px)) scale(' + scale + ')';
  }}

  function zoomIn()    {{ scale = Math.min(scale * 1.2, 20); applyTransform(); }}
  function zoomOut()   {{ scale = Math.max(scale / 1.2, 0.05); applyTransform(); }}
  function resetView() {{ scale = 1; tx = 0; ty = 0; applyTransform(); }}

  viewport.addEventListener('wheel', function(e) {{
    e.preventDefault();
    var factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    scale = Math.min(Math.max(scale * factor, 0.05), 20);
    applyTransform();
  }}, {{ passive: false }});

  var dragging = false, lastX = 0, lastY = 0;
  viewport.addEventListener('mousedown', function(e) {{
    if (e.button !== 0) return;
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    viewport.classList.add('grabbing');
  }});
  window.addEventListener('mousemove', function(e) {{
    if (!dragging) return;
    tx += e.clientX - lastX; ty += e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    applyTransform();
  }});
  window.addEventListener('mouseup', function() {{
    dragging = false; viewport.classList.remove('grabbing');
  }});
  viewport.addEventListener('dblclick', function() {{ resetView(); }});

  mermaid.run({{ nodes: [document.querySelector('.mermaid')] }}).catch(function(e) {{
    console.warn('Mermaid:', e);
  }});
</script>
</body>
</html>"""
