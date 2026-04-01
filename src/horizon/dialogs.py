from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)


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
