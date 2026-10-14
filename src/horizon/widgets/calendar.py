from dataclasses import dataclass, field
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta

from PySide6.QtCore import Qt, Signal, QThread, QTimer, QTime
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget
from PySide6.QtCore import QRect, QRectF

from horizon import theme as _theme

try:
    import win32com.client as _win32com
    import pythoncom as _pythoncom
    _OUTLOOK_AVAILABLE = True
except ImportError:
    _OUTLOOK_AVAILABLE = False


def _parse_attendees(raw: str) -> list[str]:
    """Split a semicolon-separated Outlook attendees string into a clean list of names."""
    if not raw:
        return []
    return [name.strip() for name in raw.split(";") if name.strip()]


@dataclass
class CalendarMeeting:
    start: _datetime
    end: _datetime
    subject: str
    required_attendees: list[str] = field(default_factory=list)
    optional_attendees: list[str] = field(default_factory=list)


class OutlookFetchWorker(QThread):
    meetings_ready = Signal(object, list)   # day, list[CalendarMeeting]
    fetch_failed = Signal(object, str)      # day, message

    def __init__(self, day: _date, parent=None) -> None:
        super().__init__(parent)
        self._day = day

    def run(self) -> None:
        if not _OUTLOOK_AVAILABLE:
            self.fetch_failed.emit(self._day, "pywin32 not installed")
            return
        try:
            self._fetch()
        except Exception as exc:
            self.fetch_failed.emit(self._day, str(exc))

    def _fetch(self) -> None:
        _pythoncom.CoInitialize()
        try:
            outlook = _win32com.Dispatch("Outlook.Application")
            ns = outlook.GetNamespace("MAPI")
            cal = ns.GetDefaultFolder(9)  # olFolderCalendar
            start_str = self._day.strftime("%m/%d/%Y 12:00 AM")
            end_str = self._day.strftime("%m/%d/%Y 11:59 PM")
            items = cal.Items
            items.IncludeRecurrences = True
            items.Sort("[Start]")
            restricted = items.Restrict(
                f"[Start] >= '{start_str}' AND [Start] <= '{end_str}'"
            )
            meetings: list[CalendarMeeting] = []
            for appt in restricted:
                try:
                    meetings.append(CalendarMeeting(
                        start=appt.Start,
                        end=appt.End,
                        subject=appt.Subject or "(No title)",
                        required_attendees=_parse_attendees(appt.RequiredAttendees),
                        optional_attendees=_parse_attendees(appt.OptionalAttendees),
                    ))
                except Exception:
                    continue
            self.meetings_ready.emit(self._day, meetings)
        finally:
            _pythoncom.CoUninitialize()


class CalendarTimelineWidget(QWidget):
    HOUR_HEIGHT = 60
    LABEL_WIDTH = 44
    START_HOUR = 7
    END_HOUR = 21

    create_note_requested = Signal(object)  # emits CalendarMeeting

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._meetings: list[CalendarMeeting] = []
        self._day = _date.today()
        self._layout_cache: list[tuple] = []  # list of (CalendarMeeting, QRect)
        self.setFixedHeight((self.END_HOUR - self.START_HOUR) * self.HOUR_HEIGHT)
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(60 * 1000)
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_timer.start()

    def set_meetings(self, meetings: list[CalendarMeeting], day: _date) -> None:
        self._meetings = meetings
        self._day = day
        self._layout_cache = []
        self.update()

    @staticmethod
    def _compute_columns(meetings: list) -> list:
        """Returns [(meeting, col_index, total_cols), ...] for side-by-side layout."""
        if not meetings:
            return []
        sorted_m = sorted(meetings, key=lambda m: m.start)
        # Greedily assign each meeting to the first column whose last event ended
        col_ends: list = []
        assignments: list[int] = []
        for m in sorted_m:
            assigned = next(
                (i for i, end in enumerate(col_ends) if m.start >= end), None
            )
            if assigned is None:
                assigned = len(col_ends)
                col_ends.append(m.end)
            else:
                col_ends[assigned] = m.end
            assignments.append(assigned)
        # Group into overlap clusters so each cluster shares the same total_cols
        clusters: list[list[int]] = []
        current: list[int] = [0]
        cluster_end = sorted_m[0].end
        for i in range(1, len(sorted_m)):
            if sorted_m[i].start < cluster_end:
                current.append(i)
                cluster_end = max(cluster_end, sorted_m[i].end)
            else:
                clusters.append(current)
                current = [i]
                cluster_end = sorted_m[i].end
        clusters.append(current)
        result = []
        for cluster in clusters:
            total_cols = max(assignments[i] for i in cluster) + 1
            for i in cluster:
                result.append((sorted_m[i], assignments[i], total_cols))
        return result

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        event_left = self.LABEL_WIDTH + 4
        event_right = w - 2

        t = _theme.current()
        painter.fillRect(self.rect(), QColor(t.calendar_bg))

        for hour in range(self.START_HOUR, self.END_HOUR + 1):
            y = (hour - self.START_HOUR) * self.HOUR_HEIGHT
            if hour == 0:
                label = "12 AM"
            elif hour < 12:
                label = f"{hour} AM"
            elif hour == 12:
                label = "12 PM"
            else:
                label = f"{hour - 12} PM"

            painter.setPen(QColor(t.calendar_label))
            painter.drawText(
                QRect(0, y - 7, self.LABEL_WIDTH - 4, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(QPen(QColor(t.calendar_hour_line), 1))
            painter.drawLine(self.LABEL_WIDTH, y, w, y)

            if hour < self.END_HOUR:
                half_y = y + self.HOUR_HEIGHT // 2
                painter.setPen(QPen(QColor(t.calendar_half_hour_line), 1, Qt.PenStyle.DotLine))
                painter.drawLine(self.LABEL_WIDTH, half_y, w, half_y)

        available_w = event_right - event_left
        self._layout_cache = []
        for meeting, col, total_cols in self._compute_columns(self._meetings):
            start_frac = meeting.start.hour + meeting.start.minute / 60.0
            end_frac = meeting.end.hour + meeting.end.minute / 60.0
            y_top = max(0.0, (start_frac - self.START_HOUR) * self.HOUR_HEIGHT)
            y_bot = min(
                float((self.END_HOUR - self.START_HOUR) * self.HOUR_HEIGHT),
                (end_frac - self.START_HOUR) * self.HOUR_HEIGHT,
            )
            if y_bot <= y_top + 2:
                continue
            col_w = available_w / total_cols
            rect = QRect(
                int(event_left + col * col_w) + 1, int(y_top) + 1,
                int(col_w) - 2, int(y_bot - y_top) - 2,
            )
            self._layout_cache.append((meeting, rect))
            painter.fillRect(rect, QColor(t.calendar_event_bg))
            painter.setPen(QColor(t.calendar_event_text))
            painter.drawText(
                rect.adjusted(4, 3, -3, -3),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                meeting.subject,
            )

        now = QTime.currentTime()
        current_frac = now.hour() + now.minute() / 60.0
        if self._day == _date.today() and self.START_HOUR <= current_frac <= self.END_HOUR:
            cy = int((current_frac - self.START_HOUR) * self.HOUR_HEIGHT)
            painter.setPen(QPen(QColor(t.calendar_now_line), 1))
            painter.drawLine(self.LABEL_WIDTH, cy, w, cy)
            path = QPainterPath()
            path.moveTo(self.LABEL_WIDTH - 1, cy - 5)
            path.lineTo(self.LABEL_WIDTH + 5, cy)
            path.lineTo(self.LABEL_WIDTH - 1, cy + 5)
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(t.calendar_now_line)))
            painter.drawPath(path)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._layout_cache:
            pos = event.position().toPoint()
            for meeting, rect in self._layout_cache:
                if rect.contains(pos):
                    menu = QMenu(self)
                    action = menu.addAction("Create note")
                    action.triggered.connect(
                        lambda checked=False, m=meeting: self.create_note_requested.emit(m)
                    )
                    menu.exec(event.globalPosition().toPoint())
                    return
        super().mousePressEvent(event)


class MeetingsWidget(QWidget):
    _REFRESH_MS = 60 * 1000

    create_note_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: OutlookFetchWorker | None = None
        self._pending_refresh = False
        self._day = _date.today()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(4)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(4)

        self._prev_btn = QPushButton("‹")
        self._prev_btn.setToolTip("Previous day")
        self._prev_btn.setFixedWidth(28)
        self._prev_btn.clicked.connect(lambda: self._set_day(self._day - _timedelta(days=1)))
        nav.addWidget(self._prev_btn)

        self._date_label = QLabel()
        font = self._date_label.font()
        font.setBold(True)
        self._date_label.setFont(font)
        self._date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._date_label, stretch=1)

        self._today_btn = QPushButton("Today")
        self._today_btn.setToolTip("Back to today")
        self._today_btn.clicked.connect(lambda: self._set_day(_date.today()))
        nav.addWidget(self._today_btn)

        self._next_btn = QPushButton("›")
        self._next_btn.setToolTip("Next day")
        self._next_btn.setFixedWidth(28)
        self._next_btn.clicked.connect(lambda: self._set_day(self._day + _timedelta(days=1)))
        nav.addWidget(self._next_btn)

        outer.addLayout(nav)
        self._update_nav()

        self._timeline = CalendarTimelineWidget()
        self._timeline.create_note_requested.connect(self.create_note_requested)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._timeline)
        outer.addWidget(self._scroll, stretch=1)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.hide()
        outer.addWidget(self._status_label)

        self._timer = QTimer(self)
        self._timer.setInterval(self._REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _update_nav(self) -> None:
        is_today = self._day == _date.today()
        label = self._day.strftime("%a %d %b %Y")
        self._date_label.setText(f"Today · {label}" if is_today else label)
        self._today_btn.setVisible(not is_today)

    def _set_day(self, day: _date) -> None:
        self._day = day
        self._update_nav()
        self.refresh()

    def refresh(self) -> None:
        self._update_nav()
        if self._worker is not None and self._worker.isRunning():
            self._pending_refresh = True
            return
        self._worker = OutlookFetchWorker(self._day, self)
        self._worker.meetings_ready.connect(self._on_meetings_ready)
        self._worker.fetch_failed.connect(self._on_fetch_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        if self._pending_refresh:
            self._pending_refresh = False
            self.refresh()

    def _on_meetings_ready(self, day: _date, meetings: list) -> None:
        if day != self._day:
            return
        self._status_label.hide()
        self._timeline.set_meetings(meetings, day)
        QTimer.singleShot(0, self._scroll_to_relevant_hour)

    def _on_fetch_failed(self, day: _date, message: str) -> None:
        if day != self._day:
            return
        self._timeline.set_meetings([], day)
        self._status_label.setText(f"Outlook unavailable\n{message}")
        self._status_label.show()

    def _scroll_to_relevant_hour(self) -> None:
        if self._day == _date.today():
            now = QTime.currentTime()
            frac = now.hour() + now.minute() / 60.0
        else:
            frac = 8.0
        y = int((frac - CalendarTimelineWidget.START_HOUR) * CalendarTimelineWidget.HOUR_HEIGHT)
        self._scroll.verticalScrollBar().setValue(max(0, y - 30))
