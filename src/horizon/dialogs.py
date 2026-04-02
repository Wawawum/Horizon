from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from horizon.task import TaskBucket, TaskPriority, TaskState


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
    def __init__(self, task, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Task Details")
        self.setMinimumWidth(400)

        self._title_edit = QLineEdit(task.title)
        self._title_edit.setMaxLength(255)

        self._desc_edit = QPlainTextEdit(task.description)
        self._desc_edit.setFixedHeight(80)

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
