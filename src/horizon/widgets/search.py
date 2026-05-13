from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from horizon import theme as _theme
from horizon.search import SearchResult


class _SearchResultItem(QWidget):
    clicked = Signal(str, int)  # (type, entity_id)

    def __init__(self, result: SearchResult, parent=None) -> None:
        super().__init__(parent)
        self._result = result
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        t = _theme.current()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # Header row: badge + title
        header = QHBoxLayout()
        header.setSpacing(8)

        if result.type == "note":
            badge_text, badge_color = "Note", t.accent_color
        elif result.type == "task":
            badge_text, badge_color = "Tâche", t.priority_medium
        else:
            badge_text, badge_color = "Projet", t.priority_low
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"color: {badge_color};"
            "font-size: 10px;"
            "font-weight: bold;"
            "letter-spacing: 1px;"
            "background: transparent;"
            "padding: 1px 4px;"
            f"border: 1px solid {badge_color};"
            "border-radius: 3px;"
        )
        badge.setFixedHeight(16)
        header.addWidget(badge)

        title_label = QLabel(result.title)
        title_label.setStyleSheet(
            f"color: {t.text};"
            "font-weight: bold;"
            "font-size: 12px;"
            "background: transparent;"
        )
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.addWidget(title_label, stretch=1)
        layout.addLayout(header)

        # Snippet
        snippet_label = QLabel()
        snippet_label.setTextFormat(Qt.TextFormat.RichText)
        snippet_label.setText(
            f'<span style="color:{t.scrollbar_handle_hover}; font-size:11px;">'
            + result.snippet
            + "</span>"
        )
        snippet_label.setWordWrap(True)
        snippet_label.setStyleSheet("background: transparent;")
        layout.addWidget(snippet_label)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        self.setStyleSheet(
            f"_SearchResultItem:hover {{ background-color: {t.button_hover}; }}"
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._result.type, self._result.entity_id)
        super().mousePressEvent(event)


class SearchResultsWidget(QWidget):
    note_requested = Signal(int)
    task_requested = Signal(int)
    project_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        t = _theme.current()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header_widget = QWidget()
        header_widget.setFixedHeight(40)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 0, 16, 0)

        self._header_label = QLabel()
        self._header_label.setStyleSheet(
            f"color: {t.text}; font-size: 13px; font-weight: bold; background: transparent;"
        )
        header_layout.addWidget(self._header_label)
        header_layout.addStretch()
        outer.addWidget(header_widget)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(sep)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, stretch=1)

        self._empty_label = QLabel("Aucun résultat.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {t.scrollbar_handle}; background: transparent;")
        self._empty_label.hide()
        outer.addWidget(self._empty_label)

    def load_results(self, query: str, results: list[SearchResult]) -> None:
        self._header_label.setText(f'Résultats pour : « {query} »')

        # Clear previous items (all except the stretch at the end)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not results:
            self._empty_label.show()
            self._scroll.hide()
        else:
            self._empty_label.hide()
            self._scroll.show()
            for result in results:
                item = _SearchResultItem(result)
                item.clicked.connect(self._on_item_clicked)
                self._list_layout.insertWidget(self._list_layout.count() - 1, item)

    def _on_item_clicked(self, type_: str, entity_id: int) -> None:
        if type_ == "note":
            self.note_requested.emit(entity_id)
        elif type_ == "project":
            self.project_requested.emit(entity_id)
        else:
            self.task_requested.emit(entity_id)
