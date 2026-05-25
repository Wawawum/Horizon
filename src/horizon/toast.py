from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from horizon import theme as _theme


class ToastNotification(QWidget):
    def __init__(self, message: str) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        t = _theme.current()
        label = QLabel(message, self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f"background-color: {t.surface_bg};"
            f"color: {t.accent_color};"
            f"border: 1px solid {t.accent_color};"
            "border-radius: 6px;"
            "padding: 8px 20px;"
            "font-size: 12px;"
            "font-weight: bold;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        self.adjustSize()

        geom = QApplication.primaryScreen().availableGeometry()
        self.move(
            geom.center().x() - self.width() // 2,
            geom.bottom() - self.height() - 40,
        )
        self.show()
        QTimer.singleShot(1500, self.close)
