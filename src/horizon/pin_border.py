import ctypes
import ctypes.wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from horizon import theme as _theme

_BORDER_WIDTH       = 3
_POLL_INTERVAL_MS   = 50

# Win32 constants
_GWL_EXSTYLE                 = -20
_WS_EX_LAYERED               = 0x00080000
_WS_EX_TRANSPARENT           = 0x00000020
_DWMWA_EXTENDED_FRAME_BOUNDS = 9


def _visible_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) of the window's visible frame.

    Uses DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS) which strips the
    invisible DWM shadow/padding present in GetWindowRect on modern Windows.
    Falls back to GetWindowRect for non-DWM windows.
    """
    rect = ctypes.wintypes.RECT()
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd,
        _DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if hr == 0:
        return rect.left, rect.top, rect.right, rect.bottom
    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return None


class PinBorderOverlay(QWidget):
    """Frameless transparent overlay that draws a coloured border around a
    foreign window.  Mouse events pass through completely (WS_EX_TRANSPARENT).
    Position and size are kept in sync with the target via a QTimer poll.
    """

    def __init__(self, target_hwnd: int) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._target = target_hwnd

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Initial position before show() so the widget doesn't flash at (0,0)
        self._apply_geometry()
        self.show()

        # Make the overlay fully transparent to mouse/keyboard input at the
        # Win32 level so clicks pass through to the window below.
        overlay_hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        ex = user32.GetWindowLongW(overlay_hwnd, _GWL_EXSTYLE)
        user32.SetWindowLongW(overlay_hwnd, _GWL_EXSTYLE, ex | _WS_EX_LAYERED | _WS_EX_TRANSPARENT)

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ── geometry sync ──────────────────────────────────────────────────────

    def _apply_geometry(self) -> None:
        bounds = _visible_rect(self._target)
        if bounds is None:
            return
        l, t, r, b = bounds
        self.setGeometry(l, t, r - l, b - t)

    def _poll(self) -> None:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(self._target):
            self.close()
            return
        if user32.IsIconic(self._target):       # minimised → hide without destroying
            if self.isVisible():
                self.hide()
            return
        self._apply_geometry()
        if not self.isVisible():
            self.show()

    # ── painting ───────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        color = QColor(_theme.current().accent_color)
        painter = QPainter(self)
        pen = QPen(color, _BORDER_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Inset by half the pen width so the stroke is entirely inside the widget
        half = _BORDER_WIDTH // 2
        painter.drawRect(
            half,
            half,
            self.width()  - _BORDER_WIDTH,
            self.height() - _BORDER_WIDTH,
        )
        painter.end()
