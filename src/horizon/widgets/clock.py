from datetime import date as _date

from PySide6.QtCore import Qt, Signal, QTimer, QTime, QDate, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import QRect, QRectF

from horizon import theme as _theme
from horizon.widgets.calendar import MeetingsWidget


class AnalogClockWidget(QWidget):
    _SIZE = 160

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        timer = QTimer(self)
        timer.timeout.connect(self.update)
        timer.start(1000)

    def paintEvent(self, event) -> None:
        side = min(self.width(), self.height())
        time = QTime.currentTime()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(side / 200.0, side / 200.0)

        t = _theme.current()

        # Clock face
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(t.clock_face)))
        painter.drawEllipse(-90, -90, 180, 180)

        # Outer ring
        painter.setPen(QPen(QColor(t.clock_ring), 4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(-90, -90, 180, 180)

        # Hour tick marks
        painter.setPen(QPen(QColor(t.clock_tick_hour), 3))
        for i in range(12):
            painter.drawLine(QPointF(0, -76), QPointF(0, -90))
            painter.rotate(30)

        # Minute tick marks
        painter.setPen(QPen(QColor(t.clock_tick_minute), 1))
        for i in range(60):
            if i % 5 != 0:
                painter.drawLine(QPointF(0, -82), QPointF(0, -90))
            painter.rotate(6)

        # Hour hand
        hour_angle = 30.0 * time.hour() + 0.5 * time.minute()
        painter.save()
        painter.rotate(hour_angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(t.clock_hand)))
        painter.drawConvexPolygon([
            QPointF(-5, 10), QPointF(5, 10),
            QPointF(3, -50), QPointF(-3, -50),
        ])
        painter.restore()

        # Minute hand
        minute_angle = 6.0 * time.minute() + 0.1 * time.second()
        painter.save()
        painter.rotate(minute_angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(t.clock_hand)))
        painter.drawConvexPolygon([
            QPointF(-4, 10), QPointF(4, 10),
            QPointF(2, -70), QPointF(-2, -70),
        ])
        painter.restore()

        # Second hand
        second_angle = 6.0 * time.second()
        painter.save()
        painter.rotate(second_angle)
        painter.setPen(QPen(QColor(t.clock_second), 2))
        painter.drawLine(QPointF(0, 15), QPointF(0, -72))
        painter.restore()

        # Center dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(t.clock_second)))
        painter.drawEllipse(-4, -4, 8, 8)


class SysClockWidget(QFrame):
    """Panneau HUD plat affichant l'heure, calqué sur la maquette.

    Le panneau a des angles droits sauf le coin bas-droit, biseauté —
    impossible à obtenir avec `border-radius` (qui ne fait qu'arrondir),
    donc le fond et la bordure sont peints à la main dans paintEvent().
    """

    _W = 190
    _CHAMFER = 16

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._t = t = _theme.current()
        self.setMinimumWidth(self._W)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 16, 12)
        layout.setSpacing(6)

        # ── En-tête : SYS.CLOCK ── LIVE ──
        header = QHBoxLayout()
        header.setSpacing(0)
        label_title = QLabel("SYS.CLOCK")
        label_title.setStyleSheet(
            f"color: {t.titlebar_accent};"
            "font-size: 10px;"
            "font-weight: bold;"
            "letter-spacing: 1px;"
            "background: transparent;"
            "border: none;"
        )
        header.addWidget(label_title)
        header.addStretch()
        label_live = QLabel(f'<span style="color:{t.clock_live_dot};">●</span> LIVE')
        label_live.setStyleSheet(
            f"color: {t.clock_live_dot};"
            "font-size: 9px;"
            "font-weight: bold;"
            "letter-spacing: 1px;"
            "background: transparent;"
            "border: none;"
        )
        header.addWidget(label_live)
        layout.addLayout(header)

        # ── Heure ──
        time_row = QHBoxLayout()
        time_row.setSpacing(2)
        time_row.addStretch()
        self._hm_label = QLabel()
        self._hm_label.setStyleSheet(
            f"color: {t.titlebar_text};"
            "background: transparent;"
            "border: none;"
        )
        self._hm_label.setFont(QFont("JetBrains Mono", 22, QFont.Weight.Bold))
        time_row.addWidget(self._hm_label)
        self._sec_label = QLabel()
        self._sec_label.setStyleSheet(
            f"color: {t.clock_second};"
            "background: transparent;"
            "border: none;"
        )
        self._sec_label.setFont(QFont("JetBrains Mono", 13, QFont.Weight.Bold))
        self._sec_label.setAlignment(Qt.AlignmentFlag.AlignBottom)
        time_row.addWidget(self._sec_label, 0, Qt.AlignmentFlag.AlignBottom)
        time_row.addStretch()
        layout.addLayout(time_row)

        # ── Date ── UTC+1 ──
        footer = QHBoxLayout()
        footer.setSpacing(0)
        self._date_label = QLabel()
        self._date_label.setStyleSheet(
            f"color: {t.titlebar_muted};"
            "font-size: 10px;"
            "background: transparent;"
            "border: none;"
        )
        footer.addWidget(self._date_label)
        footer.addStretch()
        label_utc = QLabel("UTC+1")
        label_utc.setStyleSheet(
            f"color: {t.titlebar_accent};"
            "font-size: 10px;"
            "font-weight: bold;"
            "background: transparent;"
            "border: none;"
        )
        footer.addWidget(label_utc)
        layout.addLayout(footer)

        # ── Rangée de segments décoratifs ──
        segments = QHBoxLayout()
        segments.setSpacing(3)
        segment_colors = (t.titlebar_accent, t.clock_second, t.titlebar_muted, None)
        for color in segment_colors:
            chip = QFrame()
            chip.setFixedSize(28, 4)
            if color:
                chip.setStyleSheet(
                    f"background-color: {color}; border-radius: 2px; border: none;"
                )
            else:
                chip.setStyleSheet(
                    f"background-color: transparent; border-radius: 2px;"
                    f" border: 1px solid {t.titlebar_border};"
                )
            segments.addWidget(chip)
        layout.addLayout(segments)

        self._update()
        timer = QTimer(self)
        timer.timeout.connect(self._update)
        timer.start(1000)

    def _update(self) -> None:
        now = QTime.currentTime()
        self._hm_label.setText(now.toString("HH:mm"))
        self._sec_label.setText(f":{now.toString('ss')}")
        self._date_label.setText(QDate.currentDate().toString("dd.MM.yyyy"))

    def paintEvent(self, event) -> None:
        t = self._t
        w, h, c = self.width(), self.height(), self._CHAMFER
        polygon = [
            QPointF(0, 0),
            QPointF(w, 0),
            QPointF(w, h - c),
            QPointF(w - c, h),
            QPointF(0, h),
        ]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(t.titlebar_border), 1))
        p.setBrush(QBrush(QColor(t.titlebar_bg)))
        p.drawPolygon(polygon)


class RightPanelWidget(QWidget):
    create_note_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(214)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 16, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        clock = SysClockWidget()
        layout.addWidget(clock, 0, Qt.AlignmentFlag.AlignHCenter)
        self._meetings = MeetingsWidget()
        self._meetings.create_note_requested.connect(self.create_note_requested)
        layout.addWidget(self._meetings, stretch=1)
