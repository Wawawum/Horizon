from __future__ import annotations

import base64

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from horizon.image import ImageRepository

_THUMB_SIZE = 128
_COLUMNS = 4


class _MediaTile(QFrame):
    clicked = Signal(int)  # emits image_id

    def __init__(self, image_id: int, data: bytes, parent=None) -> None:
        super().__init__(parent)
        self._image_id = image_id
        self.setFixedSize(_THUMB_SIZE + 16, _THUMB_SIZE + 32)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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


class MediaWidget(QWidget):
    def __init__(self, image_repo: ImageRepository, parent=None) -> None:
        super().__init__(parent)
        self._image_repo = image_repo

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
            row, col = divmod(i, _COLUMNS)
            self._grid_layout.addWidget(tile, row, col)

    def _on_tile_clicked(self, image_id: int) -> None:
        from horizon.dialogs import ImageViewerDialog
        data = self._image_repo.get(image_id)
        if data is None:
            return
        b64 = base64.b64encode(data).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
        dlg = ImageViewerDialog(data_uri, parent=self)
        dlg.exec()
