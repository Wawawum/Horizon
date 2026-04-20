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
from horizon.folder import FolderRepository
from horizon.image import ImageRepository
from horizon.note import Note, NoteRepository
from horizon.project import ProjectRepository

_PLUS_ICON: QIcon | None = None
_PLUS_ICON_SIZE = QSize(12, 12)

def _plus_icon() -> QIcon:
    global _PLUS_ICON
    if _PLUS_ICON is None:
        _PLUS_ICON = _theme.make_icon(":/icons/plus_cyan.svg", _PLUS_ICON_SIZE)
    return _PLUS_ICON

_JETBRAINS_MONO_URL = (Path(__file__).parent.parent / "resources" / "JetBrainsMono-Regular.ttf").as_uri()

_MD_IMG_RE  = re.compile(r'!\[([^\]]*)\]\(horizon-image://(\d+)\)')
_HTML_PH_RE = re.compile(r'HORIZONIMG(\d+)END')

# Blockquote extraction: one or more "> …" lines + optional {.is-TYPE} annotation
_BQ_EXTRACT_RE      = re.compile(
    r'((?:^[ \t]*>[ \t]?[^\n]*\n?)+)(?:\{\.is-(info|success|warning|danger)\}[ \t]*\n?)?',
    re.MULTILINE,
)
_BQ_GT_PREFIX_RE    = re.compile(r'^[ \t]*>[ \t]?', re.MULTILINE)
# Strip Qt inline styles from <p> so our CSS rules apply (used on both full and inner HTML)
_BLOCK_STYLE_RE     = re.compile(r'(<(?:p|blockquote)\b[^>]*?) style="[^"]*"')
# Locate <body>…</body> in Qt's full HTML output
_QT_BODY_RE         = re.compile(r'<body[^>]*>(.*)</body>', re.DOTALL | re.IGNORECASE)
# Detect lines that begin a block-level element (must not receive a line-break marker)
_BLOCK_LINE_RE  = re.compile(r'^(#{1,6} |> ?|[-*+] |\d+\. |    |\t|```|~~~|\|)')
# Detect standalone horizontal-rule lines (---, ***, ___, with optional spaces)
_HR_LINE_RE     = re.compile(r'^[-*_](\s*[-*_]){2,}\s*$')


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
    font-family: '{t.font_family}', sans-serif;
    font-size: 13px; line-height: 1.6; color: {t.preview_text};
    background: {t.preview_bg}; padding: 16px 24px; max-width: 860px;
  }}
  h1, h2, h3, h4, h5, h6 {{ margin-top: 1.2em; margin-bottom: 0.4em; font-weight: 600; }}
  h1 {{ font-size: 1.75em; border-bottom: 1px solid {t.preview_border}; padding-bottom: 0.2em; }}
  h2 {{ font-size: 1.4em; border-bottom: 1px solid {t.preview_border}; padding-bottom: 0.15em; }}
  p {{ margin-bottom: 0.8em !important; }}
  ul, ol {{ padding-left: 1.5em; margin-bottom: 0.8em; }}
  li {{ margin-bottom: 0.2em; }}
  code {{ font-family: 'JetBrains Mono', monospace; background: {t.preview_code_bg}; border-radius: 3px; padding: 0.1em 0.35em; font-size: 0.9em; }}
  pre {{ background: {t.preview_code_bg}; border-radius: 4px; padding: 12px 16px; overflow-x: auto; margin-bottom: 0.8em; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 4px solid {t.preview_blockquote_border}; background: {t.preview_blockquote_bg}; margin-left: 0; padding: 0.6em 1em; color: {t.preview_blockquote_text}; margin-bottom: 0.8em; border-radius: 0 4px 4px 0; }}
  blockquote.bq-info    {{ border-left-color: #3b82f6; background: rgba(59,130,246,0.10); color: inherit; }}
  blockquote.bq-success {{ border-left-color: #22c55e; background: rgba(34,197,94,0.10);  color: inherit; }}
  blockquote.bq-warning {{ border-left-color: #f59e0b; background: rgba(245,158,11,0.10); color: inherit; }}
  blockquote.bq-danger  {{ border-left-color: #ef4444; background: rgba(239,68,68,0.10);  color: inherit; }}
  hr {{ border: none; border-top: 1px solid {t.preview_border}; margin: 1em 0; }}
  a {{ color: {t.preview_link}; }}
  table {{ border-collapse: collapse; margin-bottom: 0.8em; width: 100%; }}
  td {{ border: 1px solid {t.preview_border}; padding: 6px 12px; }}
</style>
</head>
<body>
<div id="content"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
  var TABLE_HEADER_BG = '{t.preview_table_header_bg}';
  function styleTableHeaders() {{
    document.querySelectorAll('#content table').forEach(function(table) {{
      var firstRow = table.querySelector('tr');
      if (firstRow) {{
        firstRow.querySelectorAll('td').forEach(function(td) {{
          td.style.backgroundColor = TABLE_HEADER_BG;
          td.style.fontWeight = '600';
        }});
      }}
    }});
  }}
  function attachImageHandlers() {{
    document.querySelectorAll('#content img').forEach(function(img) {{
      if (img.dataset.zoomBound) return;
      img.dataset.zoomBound = '1';
      img.style.cursor = 'zoom-in';
      img.addEventListener('click', function() {{
        var src = img.getAttribute('src');
        if (src && src.startsWith('data:')) {{
          window.bridge.open_image(src);
        }}
      }});
    }});
  }}
  function applyHtml(html) {{
    var doc = new DOMParser().parseFromString(html, 'text/html');
    document.getElementById('content').innerHTML = doc.body ? doc.body.innerHTML : html;
    styleTableHeaders();
    attachImageHandlers();
  }}
  new QWebChannel(qt.webChannelTransport, function(channel) {{
    window.bridge = channel.objects.bridge;
    window.bridge.html_changed.connect(function(html) {{ applyHtml(html); }});
    window.bridge.get_current_html(function(html) {{ if (html) applyHtml(html); }});
  }});
</script>
</body>
</html>"""


def _add_hard_breaks(md: str) -> str:
    """Mark paragraph soft breaks with a HORIZONLBR text placeholder.

    Qt compiles markdown with MarkdownNoHTML (part of MarkdownDialectGitHub),
    so injecting raw <br> tags would be stripped.  Instead we embed a plain-text
    marker that survives Qt's parser and is replaced with <br> in post-processing.

    Block-level lines (headings, blockquotes, list items, tables, code fences,
    horizontal rules) are left untouched so Qt can still parse them correctly.
    """
    lines = md.split('\n')
    result = []
    in_fence = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track fenced code blocks — never modify content inside them
        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_fence = not in_fence
            result.append(line)
            continue

        if in_fence or not stripped:
            result.append(line)
            continue

        # Block-level element: pass through unchanged
        if _BLOCK_LINE_RE.match(stripped) or _HR_LINE_RE.match(stripped):
            result.append(line)
            continue

        # Plain paragraph line: embed marker only when the *next* line is also
        # a plain paragraph line (not blank, not a block/HR element).
        next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ''
        next_is_para  = (
            bool(next_stripped)
            and not _BLOCK_LINE_RE.match(next_stripped)
            and not _HR_LINE_RE.match(next_stripped)
        )

        result.append(line + ('HORIZONLBR' if next_is_para else ''))

    return '\n'.join(result)


def _extract_blockquotes(md: str) -> tuple[str, list[tuple[list[str], str | None]]]:
    """Remove blockquote blocks from *md* and return them as a separate list.

    Each entry in the returned list is ``(content_lines, css_class_or_None)``
    where *content_lines* are the blockquote lines with their ``> `` prefix
    stripped, and *css_class_or_None* is e.g. ``"danger"`` when a
    ``{.is-danger}`` annotation was present.

    The blockquotes are replaced by ``HORIZONBLOCKQUOTEN`` placeholders so Qt
    never sees the ``>`` syntax (whose HTML representation varies across Qt
    versions and cannot be relied upon for post-processing).
    """
    bq_list: list[tuple[list[str], str | None]] = []

    def replace(m: re.Match) -> str:
        idx      = len(bq_list)
        raw_bq   = m.group(1)          # the "> …" lines (with trailing \n)
        cls      = m.group(2)          # "info" / … or None
        lines    = [
            _BQ_GT_PREFIX_RE.sub('', ln)
            for ln in raw_bq.rstrip('\n').split('\n')
        ]
        bq_list.append((lines, cls))
        # Surround with blank lines so Qt treats the placeholder as its own block
        return f'\nHORIZONBLOCKQUOTE{idx}END\n\n'

    return _BQ_EXTRACT_RE.sub(replace, md), bq_list


def _blockquote_inner_html(lines: list[str]) -> str:
    """Convert blockquote content lines to inner HTML, applying line-break markers."""
    md = _add_hard_breaks('\n'.join(lines))
    doc = QTextDocument()
    doc.setMarkdown(md)
    raw = doc.toHtml()
    body = _QT_BODY_RE.search(raw)
    inner = body.group(1).strip() if body else '\n'.join(lines)
    inner = _BLOCK_STYLE_RE.sub(r'\1', inner)
    inner = inner.replace('HORIZONLBR ', '<br>').replace('HORIZONLBR', '<br>')
    return inner


def _inject_blockquotes(html: str, bq_list: list[tuple[list[str], str | None]]) -> str:
    """Replace HORIZONBLOCKQUOTEN placeholders with styled <blockquote> elements."""
    for idx, (lines, cls) in enumerate(bq_list):
        placeholder = f'HORIZONBLOCKQUOTE{idx}END'
        inner       = _blockquote_inner_html(lines)
        cls_attr    = f' class="bq-{cls}"' if cls else ''
        bq_html     = f'<blockquote{cls_attr}>{inner}</blockquote>'
        # Qt may have wrapped the placeholder in a <p>…</p>; handle both forms
        html = re.sub(
            r'<p[^>]*>\s*' + re.escape(placeholder) + r'\s*</p>',
            bq_html,
            html,
            flags=re.IGNORECASE,
        )
        html = html.replace(placeholder, bq_html)   # fallback (naked placeholder)
    return html


def _markdown_to_html(markdown: str, image_repo: ImageRepository | None = None) -> str:
    """Convert markdown to HTML, resolving horizon-image:// references to inline data URIs.

    Qt's QTextDocument.toHtml() does not reliably preserve unknown URL schemes
    (it may encode or drop them).  We therefore substitute image references with
    plain-text placeholders *before* the Qt markdown pass, then replace those
    placeholders with proper <img> tags in the resulting HTML.
    """
    images: dict[int, bytes | None] = {}

    # Step 1: extract image references
    if image_repo is not None:
        def _extract(m: re.Match) -> str:
            img_id = int(m.group(2))
            if img_id not in images:
                images[img_id] = image_repo.get(img_id)
            return f"HORIZONIMG{img_id}END"

        markdown = _MD_IMG_RE.sub(_extract, markdown)

    # Step 2: extract blockquotes (with optional {.is-TYPE} annotations) so Qt
    #         never sees "> …" lines whose HTML representation is unpredictable.
    markdown, bq_list = _extract_blockquotes(markdown)

    # Step 3: mark paragraph soft-breaks with a plain-text placeholder
    markdown = _add_hard_breaks(markdown)

    # Step 4: Qt markdown → HTML
    doc = QTextDocument()
    doc.setMarkdown(markdown)
    html = doc.toHtml()

    # Step 5: strip Qt inline styles from <p> so our CSS controls spacing
    html = _BLOCK_STYLE_RE.sub(r'\1', html)

    # Step 6: inject blockquote HTML (replaces HORIZONBLOCKQUOTEN placeholders)
    html = _inject_blockquotes(html, bq_list)

    # Step 7: replace line-break placeholders with <br>
    # Qt emits a soft-break space between the two halves; strip it as well.
    html = html.replace('HORIZONLBR ', '<br>').replace('HORIZONLBR', '<br>')

    # Step 8: re-inject images
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
    html_changed  = Signal(str)
    image_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_html: str = ""

    def push_html(self, html: str) -> None:
        self._current_html = html
        self.html_changed.emit(html)

    @Slot(result=str)
    def get_current_html(self) -> str:
        return self._current_html

    @Slot(str)
    def open_image(self, data_uri: str) -> None:
        self.image_clicked.emit(data_uri)


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
        new_btn.setIcon(_plus_icon())
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

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, folder_repo: FolderRepository, prefs=None, image_repo: ImageRepository | None = None, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._folder_repo = folder_repo
        self._prefs = prefs
        self._image_repo = image_repo
        self._current_note: Note | None = None
        self._body_raw: str = ""
        self._updating_combo = False
        self._updating_folder_combo = False

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

        self._folder_combo = QComboBox()
        self._folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        self._folder_label = QLabel("Folder:")

        self._view_source_btn = QPushButton("View source")
        self._view_source_btn.clicked.connect(self._on_view_source)

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._title_edit, stretch=1)
        header_layout.addWidget(self._archive_cb)
        header_layout.addWidget(self._delete_btn)
        header_layout.addWidget(back_btn)

        project_row = QHBoxLayout()
        project_row.addWidget(QLabel("Project:"))
        project_row.addWidget(self._project_combo)
        project_row.addSpacing(16)
        project_row.addWidget(self._folder_label)
        project_row.addWidget(self._folder_combo)
        project_row.addStretch()
        project_row.addWidget(self._view_source_btn)

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
        self._bridge.image_clicked.connect(self._on_image_clicked)

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

    def _on_view_source(self) -> None:
        """Open a dialog showing the raw HTML sent to the preview."""
        html = self._bridge._current_html
        dlg = QDialog(self)
        dlg.setWindowTitle("Preview HTML source")
        dlg.resize(800, 600)
        text = QPlainTextEdit(dlg)
        text.setReadOnly(True)
        text.setPlainText(html)
        text.setFont(QFont("Courier New", 9))
        lay = QVBoxLayout(dlg)
        lay.addWidget(text)
        dlg.exec()

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

        self._updating_folder_combo = True
        if note.project_id is not None:
            self._folder_label.setVisible(True)
            self._folder_combo.setVisible(True)
            self._populate_folder_combo(note.project_id, note.folder_id)
        else:
            self._folder_label.setVisible(False)
            self._folder_combo.setVisible(False)
            self._folder_combo.clear()
        self._updating_folder_combo = False

        self._editor.blockSignals(True)
        self._editor.setPlainText(self._body_raw)
        self._editor.blockSignals(False)

        self._bridge.push_html(_markdown_to_html(self._body_raw, self._image_repo))

    def _populate_folder_combo(self, project_id: int, selected_folder_id: int | None) -> None:
        self._folder_combo.clear()
        self._folder_combo.addItem("No folder", userData=None)

        all_folders = self._folder_repo.list_for_project(project_id)

        def _dfs(parent_id: int | None, depth: int) -> None:
            children = sorted(
                [f for f in all_folders if f.parent_id == parent_id],
                key=lambda f: f.name.lower(),
            )
            for folder in children:
                prefix = "  " * depth + ("└ " if depth > 0 else "")
                self._folder_combo.addItem(prefix + folder.name, userData=folder.id)
                _dfs(folder.id, depth + 1)

        _dfs(None, 0)

        idx = self._folder_combo.findData(selected_folder_id)
        self._folder_combo.setCurrentIndex(idx if idx >= 0 else 0)

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

    def _on_image_clicked(self, data_uri: str) -> None:
        from horizon.dialogs import ImageViewerDialog
        dlg = ImageViewerDialog(data_uri, parent=self)
        dlg.exec()

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
        new_project_id = self._project_combo.currentData()
        self._current_note.project_id = new_project_id
        self._current_note.folder_id = None
        self._note_repo.update(self._current_note)

        self._updating_folder_combo = True
        if new_project_id is not None:
            self._folder_label.setVisible(True)
            self._folder_combo.setVisible(True)
            self._populate_folder_combo(new_project_id, None)
        else:
            self._folder_label.setVisible(False)
            self._folder_combo.setVisible(False)
            self._folder_combo.clear()
        self._updating_folder_combo = False

    def _on_folder_changed(self, _index: int) -> None:
        if self._updating_folder_combo or self._current_note is None:
            return
        self._current_note.folder_id = self._folder_combo.currentData()
        self._note_repo.update(self._current_note)
