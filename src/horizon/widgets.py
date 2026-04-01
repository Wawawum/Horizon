from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from horizon.dialogs import NewProjectDialog
from horizon.project import ProjectRepository


class ProjectListWidget(QWidget):
    def __init__(self, repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self.setMinimumWidth(200)

        self._list = QListWidget()

        self._new_btn = QPushButton("\uff0b New Project")
        self._new_btn.clicked.connect(self._on_new_project)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._list, stretch=1)    # fills all available vertical space
        layout.addWidget(self._new_btn, stretch=0)  # pinned to the bottom

        self._load_projects()

    def _load_projects(self) -> None:
        self._list.clear()
        for project in self._repo.list_all():
            item = QListWidgetItem(project.name)
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            self._list.addItem(item)

    def _on_new_project(self) -> None:
        dialog = NewProjectDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._repo.create(name=dialog.name(), description=dialog.description())
            self._load_projects()
