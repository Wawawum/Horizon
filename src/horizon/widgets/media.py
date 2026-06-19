from __future__ import annotations

import base64
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from horizon.image import ImageRepository
from horizon.note import NoteRepository
from horizon.project import ProjectRepository
from horizon.search import SearchRepository

_THUMB_SIZE = 128
_COLUMNS = 4
_IMG_REF_RE = re.compile(r'!\[[^\]]*\]\(horizon-image://(\d+)\)')


class _MediaTile(QFrame):
    clicked = Signal(int)         # emits image_id on left click
    delete_requested = Signal(int)  # emits image_id on context menu Delete

    def __init__(self, image_id: int, data: bytes, parent=None) -> None:
        super().__init__(parent)
        self._image_id = image_id
        self.setFixedSize(_THUMB_SIZE + 16, _THUMB_SIZE + 32)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        img_label = QLabel()
        img_label.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        px = QPixmap()
        px.loadFromData(data)
        px = px.scaled(
            _THUMB_SIZE,
            _THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        img_label.setPixmap(px)

        id_label = QLabel(f"#{image_id}")
        id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        id_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(4)
        layout.addWidget(img_label)
        layout.addWidget(id_label)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._image_id)
        super().mousePressEvent(event)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self._image_id))
        menu.addAction(delete_action)
        menu.exec(self.mapToGlobal(pos))


class MediaWidget(QWidget):
    note_open_requested = Signal(int)

    def __init__(self, image_repo: ImageRepository, search_repo: SearchRepository, note_repo: NoteRepository, proj_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._image_repo = image_repo
        self._search_repo = search_repo
        self._note_repo = note_repo
        self._proj_repo = proj_repo

        title = QLabel("Media")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(12)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(scroll, stretch=1)

    def load(self) -> None:
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, image_id in enumerate(self._image_repo.list_all_ids()):
            data = self._image_repo.get(image_id)
            if data is None:
                continue
            tile = _MediaTile(image_id, data)
            tile.clicked.connect(self._on_tile_clicked)
            tile.delete_requested.connect(self._on_delete_requested)
            row, col = divmod(i, _COLUMNS)
            self._grid_layout.addWidget(tile, row, col)

    def _on_tile_clicked(self, image_id: int) -> None:
        from horizon.dialogs import ImageViewerDialog
        data = self._image_repo.get(image_id)
        if data is None:
            return
        b64 = base64.b64encode(data).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
        dlg = ImageViewerDialog(data_uri, parent=self, image_id=image_id, search_repo=self._search_repo, note_repo=self._note_repo, proj_repo=self._proj_repo)
        dlg.exec()
        if dlg.selected_note_id is not None:
            self.note_open_requested.emit(dlg.selected_note_id)

    def _on_delete_requested(self, image_id: int) -> None:
        reply = QMessageBox.question(
            self,
            "Delete image",
            f"Delete image #{image_id}?\n\nAll references in notes will be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        results = self._search_repo.search(f"horizon-image://{image_id}", mode="all")
        for result in results:
            if result.type != "note":
                continue
            note = self._note_repo.get(result.entity_id)
            if note is None:
                continue
            new_body = _IMG_REF_RE.sub(
                lambda m: "" if int(m.group(1)) == image_id else m.group(0),
                note.body,
            )
            if new_body != note.body:
                note.body = new_body
                self._note_repo.update(note)

        self._image_repo.delete(image_id)
        self.load()
