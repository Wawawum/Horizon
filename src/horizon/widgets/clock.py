from datetime import date as _date

from PySide6.QtCore import Qt, Signal, QTimer, QTime, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
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


class GShockClockWidget(QWidget):
    _W, _H = 182, 216

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self._W, self._H)
        timer = QTimer(self)
        timer.timeout.connect(self.update)
        timer.start(1000)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = _theme.current()
        self._draw_case(p, t)
        self._draw_buttons(p, t)
        self._draw_bezel(p, t)
        self._draw_lcd(p, t)
        self._draw_brand(p, t)

    def _draw_case(self, p: QPainter, t) -> None:
        case_rect = QRectF(3, 3, 176, 196)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.gshock_case)))
        p.drawRoundedRect(case_rect, 14, 14)
        # Bevel interne
        p.setPen(QPen(QColor(t.gshock_case_shadow), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(case_rect.adjusted(4, 4, -4, -4), 11, 11)
        # Vis de coin
        for cx, cy in ((14, 14), (168, 14), (14, 186), (168, 186)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(t.gshock_screw)))
            p.drawEllipse(QPointF(cx, cy), 5, 5)
            p.setPen(QPen(QColor(t.gshock_case_shadow), 1))
            p.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
            p.drawLine(QPointF(cx, cy - 3), QPointF(cx, cy + 3))

    def _draw_buttons(self, p: QPainter, t) -> None:
        p.setPen(QPen(QColor(t.gshock_case_shadow), 1))
        p.setBrush(QBrush(QColor(t.gshock_screw)))
        for x in (0, 175):
            for y in (48, 78):
                p.drawRoundedRect(QRectF(x, y, 7, 22), 3, 3)

    def _draw_bezel(self, p: QPainter, t) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.gshock_bezel)))
        p.drawRoundedRect(QRectF(11, 13, 160, 166), 8, 8)

    def _draw_lcd(self, p: QPainter, t) -> None:
        lx, ly, lw, lh = 17, 21, 148, 140
        # Fond LCD
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.gshock_lcd_bg)))
        p.drawRoundedRect(QRectF(lx, ly, lw, lh), 4, 4)

        # ── Rangée supérieure : barres signal + CASIO + ALARM ──
        # Barres signal (4 barres de hauteurs croissantes)
        bar_x = lx + 5
        bar_y_base = ly + 17
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.gshock_lcd_fg)))
        for i in range(4):
            bh = 4 + i * 2
            p.drawRect(QRect(bar_x + i * 6, bar_y_base - bh, 4, bh))

        font_small = QFont("JetBrains Mono", 6, QFont.Weight.Bold)
        p.setFont(font_small)
        # CASIO
        p.setPen(QColor(t.gshock_lcd_label))
        p.drawText(QRect(lx + 30, ly + 4, 46, 13),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "CASIO")
        # ALARM
        p.setPen(QColor(t.gshock_lcd_alarm))
        p.drawText(QRect(lx + 76, ly + 4, lw - 80, 13),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "ALARM")

        # Date DD/MM
        font_date = QFont("JetBrains Mono", 7, QFont.Weight.Bold)
        p.setFont(font_date)
        p.setPen(QColor(t.gshock_lcd_fg))
        p.drawText(QRect(lx + 76, ly + 17, lw - 80, 13),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _date.today().strftime("%d/%m"))

        # Séparateur haut
        p.setPen(QPen(QColor(t.gshock_lcd_label), 1))
        p.drawLine(lx + 2, ly + 31, lx + lw - 4, ly + 31)

        # ── Chiffres heure (ghost + réels) ──
        font_time = QFont("JetBrains Mono", 32, QFont.Weight.Bold)
        p.setFont(font_time)
        time_rect = QRect(lx + 4, ly + 33, lw - 8, 62)
        p.setPen(QColor(t.gshock_lcd_dim))
        p.drawText(time_rect, Qt.AlignmentFlag.AlignCenter, "88:88")
        p.setPen(QColor(t.gshock_lcd_fg))
        p.drawText(time_rect, Qt.AlignmentFlag.AlignCenter,
                   QTime.currentTime().toString("hh:mm"))

        # ── Stopwatch ──
        font_sw = QFont("JetBrains Mono", 7, QFont.Weight.Normal)
        p.setFont(font_sw)
        sw_rect = QRect(lx + 4, ly + 97, lw - 8, 16)
        p.setPen(QColor(t.gshock_lcd_dim))
        p.drawText(sw_rect, Qt.AlignmentFlag.AlignCenter, "ST 88:88:88")
        p.setPen(QColor(t.gshock_lcd_fg))
        p.drawText(sw_rect, Qt.AlignmentFlag.AlignCenter, "ST 00:00:00")

        # Séparateur bas
        p.setPen(QPen(QColor(t.gshock_lcd_label), 1))
        p.drawLine(lx + 2, ly + 115, lx + lw - 4, ly + 115)

        # ── Labels bas ──
        font_btm = QFont("JetBrains Mono", 5, QFont.Weight.Normal)
        p.setFont(font_btm)
        p.setPen(QColor(t.gshock_lcd_label))
        p.drawText(QRect(lx + 2, ly + 117, lw - 4, 14),
                   Qt.AlignmentFlag.AlignCenter,
                   "BATTERY   WATER RESIST")

        # Dots décoratifs rouges
        dot_color = QColor("#cc2222")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dot_color))
        for dy in (ly + 50, ly + 70, ly + 90):
            p.drawRect(QRect(lx + 1, dy, 4, 4))
            p.drawRect(QRect(lx + lw - 5, dy, 4, 4))

    def _draw_brand(self, p: QPainter, t) -> None:
        font_brand = QFont("JetBrains Mono", 8, QFont.Weight.Bold)
        p.setFont(font_brand)
        p.setPen(QColor(t.gshock_lcd_fg))
        p.drawText(QRect(3, 196, 176, 14),
                   Qt.AlignmentFlag.AlignCenter, "G-SHOCK")


class RightPanelWidget(QWidget):
    create_note_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        clock = GShockClockWidget()
        layout.addWidget(clock, 0, Qt.AlignmentFlag.AlignHCenter)
        self._meetings = MeetingsWidget()
        self._meetings.create_note_requested.connect(self.create_note_requested)
        layout.addWidget(self._meetings, stretch=1)
