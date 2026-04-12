import base64
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QBuffer, QByteArray, QIODevice, QObject, QEvent, QSize, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from horizon import theme as _theme
from horizon.dialogs import ConfirmDialog
from horizon.image import ImageRepository
from horizon.note import Note, NoteRepository
from horizon.project import ProjectRepository

_PLUS_ICON      = QIcon(":/icons/plus_cyan.svg")
_PLUS_ICON_SIZE = QSize(12, 12)

_JETBRAINS_MONO_URL = (Path(__file__).parent.parent / "resources" / "JetBrainsMono-Regular.ttf").as_uri()

_MD_IMG_RE  = re.compile(r'!\[([^\]]*)\]\(horizon-image://(\d+)\)')
_HTML_PH_RE = re.compile(r'HORIZONIMG(\d+)END')


def _make_preview_html() -> str:
    t = _theme.current()
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @font-face {{
    font-family: 'JetBrains Mono';
    src: url('{_JETBRAINS_MONO_URL}');
    font-weight: normal;
    font-style: normal;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px; line-height: 1.6; color: {t.preview_text};
    background: {t.preview_bg}; padding: 16px 24px; max-width: 860px;
  }}
  h1, h2, h3, h4, h5, h6 {{ margin-top: 1.2em; margin-bottom: 0.4em; font-weight: 600; }}
  h1 {{ font-size: 1.75em; border-bottom: 1px solid {t.preview_border}; padding-bottom: 0.2em; }}
  h2 {{ font-size: 1.4em; border-bottom: 1px solid {t.preview_border}; padding-bottom: 0.15em; }}
  p {{ margin-bottom: 0.8em; }}
  ul, ol {{ margin-left: 1.5em; margin-bottom: 0.8em; }}
  code {{ font-family: 'JetBrains Mono', monospace; background: {t.preview_code_bg}; border-radius: 3px; padding: 0.1em 0.35em; font-size: 0.9em; }}
  pre {{ background: {t.preview_code_bg}; border-radius: 4px; padding: 12px 16px; overflow-x: auto; margin-bottom: 0.8em; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 3px solid {t.preview_blockquote_border}; margin-left: 0; padding-left: 1em; color: {t.preview_blockquote_text}; margin-bottom: 0.8em; }}
  hr {{ border: none; border-top: 1px solid {t.preview_border}; margin: 1em 0; }}
  a {{ color: {t.preview_link}; }}
  table {{ border-collapse: collapse; margin-bottom: 0.8em; width: 100%; }}
  th, td {{ border: 1px solid {t.preview_border}; padding: 6px 12px; }}
  th {{ background: {t.preview_table_header_bg}; font-weight: 600; }}
</style>
</head>
<body>
<div id="content"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
  function applyHtml(html) {{
    var doc = new DOMParser().parseFromString(html, 'text/html');
    document.getElementById('content').innerHTML = doc.body ? doc.body.innerHTML : html;
  }}
  new QWebChannel(qt.webChannelTransport, function(channel) {{
    var bridge = channel.objects.bridge;
    bridge.html_changed.connect(function(html) {{ applyHtml(html); }});
    bridge.get_current_html(function(html) {{ if (html) applyHtml(html); }});
  }});
</script>
</body>
</html>"""


def _markdown_to_html(markdown: str, image_repo: ImageRepository | None = None) -> str:
    """Convert markdown to HTML, resolving horizon-image:// references to inline data URIs.

    Qt's QTextDocument.toHtml() does not reliably preserve unknown URL schemes
    (it may encode or drop them).  We therefore substitute image references with
    plain-text placeholders *before* the Qt markdown pass, then replace those
    placeholders with proper <img> tags in the resulting HTML.
    """
    images: dict[int, bytes | None] = {}

    if image_repo is not None:
        def _extract(m: re.Match) -> str:
            img_id = int(m.group(2))
            if img_id not in images:
                images[img_id] = image_repo.get(img_id)
            return f"HORIZONIMG{img_id}END"

        markdown = _MD_IMG_RE.sub(_extract, markdown)

    doc = QTextDocument()
    doc.setMarkdown(markdown)
    html = doc.toHtml()

    if images:
        def _inject(m: re.Match) -> str:
            data = images.get(int(m.group(1)))
            if not data:
                return ""
            b64 = base64.b64encode(data).decode()
            return f'<img src="data:image/png;base64,{b64}" style="max-width:100%;">'

        html = _HTML_PH_RE.sub(_inject, html)

    return html


class MarkdownBridge(QObject):
    html_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_html: str = ""

    def push_html(self, html: str) -> None:
        self._current_html = html
        self.html_changed.emit(html)

    @Slot(result=str)
    def get_current_html(self) -> str:
        return self._current_html


class MarkdownEditor(QPlainTextEdit):
    def __init__(self, image_repo: ImageRepository, parent=None) -> None:
        super().__init__(parent)
        self._image_repo = image_repo

    def insertFromMimeData(self, source) -> None:
        if source.hasImage():
            image = source.imageData()
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buf, "PNG")
            buf.close()
            image_id = self._image_repo.create(bytes(ba))
            self.insertPlainText(f"![](horizon-image://{image_id})")
        else:
            super().insertFromMimeData(source)


class NotesListWidget(QWidget):
    note_edit_requested = Signal(int)  # emits note_id

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo

        title = QLabel("Notes")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        new_btn = QPushButton("New Note")
        new_btn.setIcon(_PLUS_ICON)
        new_btn.setIconSize(_PLUS_ICON_SIZE)
        new_btn.clicked.connect(self._on_new_note)

        self._show_archived_cb = QCheckBox("Show archived")
        self._show_archived_cb.stateChanged.connect(self.load)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self._show_archived_cb)
        header_layout.addWidget(new_btn)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Title", "Date", "Project"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._on_double_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(self._table, stretch=1)

    def load(self) -> None:
        project_names = {p.id: p.name for p in self._project_repo.list_all()}
        notes = self._note_repo.list_all(archived_only=self._show_archived_cb.isChecked())
        self._table.setRowCount(len(notes))
        for row, note in enumerate(notes):
            title_item = QTableWidgetItem(note.title)
            title_item.setData(Qt.ItemDataRole.UserRole, note.id)
            self._table.setItem(row, 0, title_item)
            date_item = QTableWidgetItem(note.dt.strftime("%Y-%m-%d %H:%M"))
            self._table.setItem(row, 1, date_item)
            project_item = QTableWidgetItem(project_names.get(note.project_id, "Uncategorized"))
            self._table.setItem(row, 2, project_item)

    def _on_double_clicked(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is not None:
            self.note_edit_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_new_note(self) -> None:
        projects = self._project_repo.list_all()
        if not projects:
            return
        note = self._note_repo.create(project_id=projects[0].id, title="New Note")
        self.load()
        self.note_edit_requested.emit(note.id)


class NoteDetailWidget(QWidget):
    back_requested = Signal()

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, prefs=None, image_repo: ImageRepository | None = None, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._prefs = prefs
        self._image_repo = image_repo
        self._current_note: Note | None = None
        self._body_raw: str = ""
        self._updating_combo = False

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.back_requested)

        self._archive_cb = QCheckBox("Archive")
        self._archive_cb.stateChanged.connect(self._on_archive_changed)

        self._delete_btn = QPushButton("Delete")
        _t = _theme.current()
        self._delete_btn.setStyleSheet(f"color: {_t.delete_btn_text}; background-color: {_t.delete_btn_bg};")
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)

        self._title_edit = QLineEdit()
        self._title_edit.setMaxLength(255)
        font = self._title_edit.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self._title_edit.setFont(font)
        self._title_edit.setFrame(False)
        self._title_edit.editingFinished.connect(self._save_title)

        self._project_combo = QComboBox()
        self._project_combo.currentIndexChanged.connect(self._on_project_changed)

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._title_edit, stretch=1)
        header_layout.addWidget(self._archive_cb)
        header_layout.addWidget(self._delete_btn)
        header_layout.addWidget(back_btn)

        project_row = QHBoxLayout()
        project_row.addWidget(QLabel("Project:"))
        project_row.addWidget(self._project_combo)
        project_row.addStretch()

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)

        self._editor = MarkdownEditor(image_repo) if image_repo is not None else QPlainTextEdit()
        self._editor.setPlaceholderText("Write markdown here…")
        self._editor.installEventFilter(self)

        self._bridge = MarkdownBridge(self)
        self._channel = QWebChannel(self)

        self._preview = QWebEngineView()
        self._preview.page().setWebChannel(self._channel)
        self._channel.registerObject("bridge", self._bridge)
        self._preview.setHtml(_make_preview_html())

        self._editor.textChanged.connect(self._on_editor_text_changed)

        self._body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._body_splitter.addWidget(self._editor)
        self._body_splitter.addWidget(self._preview)
        self._body_splitter.setStretchFactor(0, 1)
        self._body_splitter.setStretchFactor(1, 1)
        self._body_splitter.splitterMoved.connect(self._on_splitter_moved)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addLayout(project_row)
        layout.addWidget(sep)
        layout.addWidget(self._body_splitter, stretch=1)

        self._restore_splitter_sizes()

    def load_note(self, note: Note, projects: list) -> None:
        self._current_note = note
        self._body_raw = note.body

        self._title_edit.setText(note.title)
        self._archive_cb.setChecked(note.archived)
        self._delete_btn.setVisible(note.archived)

        self._updating_combo = True
        self._project_combo.clear()
        self._project_combo.addItem("Uncategorized", userData=None)
        for project in projects:
            self._project_combo.addItem(project.name, userData=project.id)
        idx = self._project_combo.findData(note.project_id)
        self._project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._updating_combo = False

        self._editor.blockSignals(True)
        self._editor.setPlainText(self._body_raw)
        self._editor.blockSignals(False)
        self._bridge.push_html(_markdown_to_html(self._body_raw, self._image_repo))

    def eventFilter(self, obj, event) -> bool:
        if obj is self._editor and event.type() == QEvent.Type.FocusOut:
            self._save_body()
        return super().eventFilter(obj, event)

    def _save_body(self) -> None:
        if self._current_note is None:
            return
        new_body = self._editor.toPlainText()
        if new_body == self._body_raw:
            return
        self._body_raw = new_body
        self._current_note.body = self._body_raw
        self._note_repo.update(self._current_note)

    def _on_editor_text_changed(self) -> None:
        self._bridge.push_html(_markdown_to_html(self._editor.toPlainText(), self._image_repo))

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        if self._prefs is not None:
            self._prefs.note_splitter_sizes = self._body_splitter.sizes()

    def _restore_splitter_sizes(self) -> None:
        if self._prefs is not None:
            saved = self._prefs.note_splitter_sizes
            if saved:
                self._body_splitter.setSizes(saved)

    def _save_title(self) -> None:
        if self._current_note is None:
            return
        self._current_note.title = self._title_edit.text().strip() or self._current_note.title
        self._title_edit.setText(self._current_note.title)
        self._note_repo.update(self._current_note)

    def _on_archive_changed(self) -> None:
        if self._current_note is None:
            return
        self._current_note.archived = self._archive_cb.isChecked()
        self._note_repo.update(self._current_note)
        self._delete_btn.setVisible(self._current_note.archived)

    def _on_delete_clicked(self) -> None:
        if self._current_note is None or not self._current_note.archived:
            return
        if ConfirmDialog.ask(
            "Delete Note",
            f"Permanently delete \"{self._current_note.title}\"?\nThis cannot be undone.",
            self,
        ):
            self._note_repo.delete(self._current_note.id)
            self._current_note = None
            self.back_requested.emit()

    def _on_project_changed(self, _index: int) -> None:
        if self._updating_combo or self._current_note is None:
            return
        self._current_note.project_id = self._project_combo.currentData()
        self._note_repo.update(self._current_note)
