import ctypes
import ctypes.wintypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from horizon import theme as _theme

_TITLEBAR_HEIGHT = 36
_TITLEBAR_CONTROLS_WIDTH = 138  # min/max/close buttons, 46 px each
_RESIZE_BORDER = 6


def window_hit_test(
    x: int,
    y: int,
    left: int,
    top: int,
    right: int,
    bottom: int,
    scale: float,
    maximized: bool,
) -> int | None:
    """Win32 hit-test code for a frameless window, or None for the client area.

    All coordinates are physical pixels; `scale` converts the logical sizes of
    the title bar and resize border to the window's DPI.
    """
    titlebar_height = round(_TITLEBAR_HEIGHT * scale)
    controls_width = round(_TITLEBAR_CONTROLS_WIDTH * scale)
    if top <= y < top + titlebar_height and x < right - controls_width:
        return 2  # HTCAPTION — enables Win+arrows and Aero snap

    if maximized:
        return None

    border = round(_RESIZE_BORDER * scale)
    is_left = x < left + border
    is_right = x > right - border
    is_top = y < top + border
    is_bottom = y > bottom - border
    if is_top and is_left:
        return 13  # HTTOPLEFT
    if is_top and is_right:
        return 14  # HTTOPRIGHT
    if is_bottom and is_left:
        return 16  # HTBOTTOMLEFT
    if is_bottom and is_right:
        return 17  # HTBOTTOMRIGHT
    if is_left:
        return 10  # HTLEFT
    if is_right:
        return 11  # HTRIGHT
    if is_top:
        return 12  # HTTOP
    if is_bottom:
        return 15  # HTBOTTOM
    return None


def native_hit_test(window: QWidget, lparam: int) -> int | None:
    """Handle WM_NCHITTEST for a frameless top-level window.

    WM_NCHITTEST coordinates are physical screen pixels, while Qt geometry is
    logical (DPI-scaled): compare against GetWindowRect instead so the hit zones
    stay aligned at any display scaling.
    """
    x = ctypes.c_int16(lparam & 0xFFFF).value
    y = ctypes.c_int16((lparam >> 16) & 0xFFFF).value
    hwnd = int(window.winId())
    rect = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
    if not dpi:
        return None
    return window_hit_test(
        x, y, rect.left, rect.top, rect.right, rect.bottom, dpi / 96.0, window.isMaximized()
    )


class TitleBar(QWidget):
    """Barre de titre personnalisée au style Synthwave."""

    def __init__(self, parent=None, *, subtitle: str = "", show_min_max: bool = True) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
        t = _theme.current()
        title_label = QLabel("HORIZON")
        title_label.setStyleSheet(
            f"color: {t.titlebar_text};"
            "font-size: 11px;"
            "font-weight: bold;"
            "letter-spacing: 3px;"
            "background: transparent;"
        )
        layout.addWidget(title_label)

        # Séparateur décoratif
        sep_label = QLabel("  //")
        sep_label.setStyleSheet(
            f"color: {t.titlebar_muted};"
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
                f"color: {t.titlebar_muted_hover};"
                "font-size: 10px;"
                "font-weight: bold;"
                "letter-spacing: 2px;"
                "background: transparent;"
            )
            layout.addWidget(sub_label)

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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)
