from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from horizon import theme as _theme


class _SearchLineEdit(QLineEdit):
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        # Prevent double-click from bubbling up to the title bar (would toggle maximize)
        event.accept()


class TitleBar(QWidget):
    """Barre de titre personnalisée au style Synthwave."""

    search_requested = Signal(str)

    def __init__(self, parent=None, *, subtitle: str = "", show_min_max: bool = True, show_search: bool = False) -> None:
        super().__init__(parent)
        self.setProperty("titlebar", "true")
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(0)

        # Icône de l'application
        icon_label = QLabel()
        pixmap = QPixmap(":/icons/Horizon_Icon.png").scaled(
            16, 16,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        icon_label.setPixmap(pixmap)
        icon_label.setFixedSize(20, 36)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        layout.addSpacing(8)

        # Nom de l'application
        title_label = QLabel("HORIZON")
        title_label.setStyleSheet(
            f"color: {_theme.current().accent_color};"
            "font-size: 11px;"
            "font-weight: bold;"
            "letter-spacing: 3px;"
            "background: transparent;"
        )
        layout.addWidget(title_label)

        # Séparateur décoratif
        t = _theme.current()
        sep_label = QLabel("  //")
        sep_label.setStyleSheet(
            f"color: {t.scrollbar_handle};"
            "font-size: 10px;"
            "letter-spacing: 2px;"
            "background: transparent;"
        )
        layout.addWidget(sep_label)

        # Sous-titre optionnel (nom du dialog)
        if subtitle:
            layout.addSpacing(8)
            sub_label = QLabel(subtitle.upper())
            sub_label.setStyleSheet(
                f"color: {t.scrollbar_handle_hover};"
                "font-size: 10px;"
                "font-weight: bold;"
                "letter-spacing: 2px;"
                "background: transparent;"
            )
            layout.addWidget(sub_label)

        layout.addStretch()

        # Barre de recherche (fenêtre principale uniquement)
        self._search_edit: _SearchLineEdit | None = None
        if show_search:
            self._search_edit = _SearchLineEdit()
            self._search_edit.setPlaceholderText("Rechercher…")
            self._search_edit.setFixedWidth(220)
            self._search_edit.setFixedHeight(22)
            self._search_edit.setStyleSheet(
                f"QLineEdit {{"
                f"  background-color: {t.input_bg};"
                f"  color: {t.text};"
                f"  border: 1px solid {t.border};"
                f"  border-radius: 3px;"
                f"  padding: 0 6px;"
                f"  font-size: 11px;"
                f"}}"
            )
            self._search_edit.returnPressed.connect(self._on_search_return)
            layout.addWidget(self._search_edit)
            layout.addStretch()

        # Bouton minimiser
        self._btn_min = QPushButton("—")
        self._btn_min.setProperty("title_btn", "min")
        self._btn_min.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_min.setToolTip("Minimiser")
        self._btn_min.clicked.connect(self._minimize)
        self._btn_min.setVisible(show_min_max)
        layout.addWidget(self._btn_min)

        # Bouton maximiser / restaurer
        self._btn_max = QPushButton("□")
        self._btn_max.setProperty("title_btn", "max")
        self._btn_max.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_max.setToolTip("Maximiser")
        self._btn_max.clicked.connect(self._toggle_maximize)
        self._btn_max.setVisible(show_min_max)
        layout.addWidget(self._btn_max)

        # Bouton fermer
        self._btn_close = QPushButton("✕")
        self._btn_close.setProperty("title_btn", "close")
        self._btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_close.setToolTip("Fermer")
        self._btn_close.clicked.connect(self._close_window)
        layout.addWidget(self._btn_close)

    def _on_search_return(self) -> None:
        query = self._search_edit.text().strip()
        if query:
            self.search_requested.emit(query)

    def _minimize(self) -> None:
        self.window().showMinimized()

    def update_max_button(self, maximized: bool) -> None:
        if maximized:
            self._btn_max.setText("❐")
            self._btn_max.setToolTip("Restaurer")
        else:
            self._btn_max.setText("□")
            self._btn_max.setToolTip("Maximiser")

    def _toggle_maximize(self) -> None:
        win = self.window()
        if win.windowState() & Qt.WindowState.WindowMaximized:
            win.showNormal()
        else:
            win.showMaximized()

    def _close_window(self) -> None:
        self.window().close()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)

