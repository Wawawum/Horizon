from PySide6.QtCore import QEvent, QSize, QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from horizon.task import SubtaskRepository, TaskBucket, TaskPriority, TaskState


class NewProjectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setMinimumWidth(400)

        self._name_edit = QLineEdit()
        self._name_edit.setMaxLength(255)
        self._name_edit.setPlaceholderText("Project name")

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText("Description (optional)")
        self._desc_edit.setFixedHeight(80)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accepted)
        btn_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Name"))
        layout.addWidget(self._name_edit)
        layout.addWidget(QLabel("Description"))
        layout.addWidget(self._desc_edit)
        layout.addWidget(btn_box)

    def _on_accepted(self) -> None:
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Project name cannot be blank.")
            return
        self.accept()

    def name(self) -> str:
        return self._name_edit.text()

    def description(self) -> str:
        return self._desc_edit.toPlainText()


class NewTaskDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Task")
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

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Title"))
        layout.addWidget(self._title_edit)
        layout.addWidget(QLabel("Description"))
        layout.addWidget(self._desc_edit)
        layout.addWidget(QLabel("State"))
        layout.addWidget(self._state_combo)
        layout.addWidget(QLabel("Priority"))
        layout.addWidget(self._priority_combo)
        layout.addWidget(QLabel("Bucket"))
        layout.addWidget(self._bucket_combo)
        layout.addWidget(btn_box)

    def _on_accepted(self) -> None:
        if not self._title_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Task title cannot be blank.")
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
        add_subtask_btn = QPushButton("+")
        add_subtask_btn.setFixedWidth(28)
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

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accepted)
        btn_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Title"))
        layout.addWidget(self._title_edit)
        layout.addWidget(QLabel("Description"))
        layout.addWidget(self._desc_edit)
        layout.addWidget(QLabel("State"))
        layout.addWidget(self._state_combo)
        layout.addWidget(QLabel("Priority"))
        layout.addWidget(self._priority_combo)
        layout.addWidget(QLabel("Bucket"))
        layout.addWidget(self._bucket_combo)
        layout.addLayout(subtasks_header)
        layout.addWidget(self._subtask_list)
        layout.addWidget(self._new_subtask_edit)
        layout.addWidget(self._archive_cb)
        layout.addWidget(btn_box)

        self._load_subtasks()

    def _load_subtasks(self) -> None:
        self._subtask_list.model().blockSignals(True)
        self._subtask_list.clear()
        for subtask in self._subtask_repo.list_for_task(self._task_id):
            subtask_id = subtask.id

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 0, 4, 0)

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

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, subtask_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
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
            QMessageBox.warning(self, "Validation Error", "Task title cannot be blank.")
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
