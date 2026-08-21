"""Markdown editor backed by CodeMirror 6 running inside a QWebEngineView.

The document itself stays plain markdown text; only the editing surface is web-based.
Python keeps a synchronous mirror of the document (see `WebMarkdownEditor.text`) so that
callers can save on close or on navigation without restructuring their control flow.

The JavaScript half lives in `web/src/editor.js` and is bundled to
`resources/horizon-editor.bundle.js`; see `web/README.md`.
"""

import base64
import json
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.image import ImageRepository

_RESOURCES_DIR      = Path(__file__).parent.parent / "resources"
_RESOURCES_BASE_URL = QUrl((_RESOURCES_DIR / "").as_uri())
_EDITOR_BUNDLE_URL  = (_RESOURCES_DIR / "horizon-editor.bundle.js").as_uri()
_JETBRAINS_MONO_URL = (_RESOURCES_DIR / "JetBrainsMono-Regular.ttf").as_uri()

DEFAULT_FONT_SIZE = 13

_TOOLBAR_ICON_SIZE   = QSize(16, 16)
_TOOLBAR_BUTTON_SIZE = QSize(26, 26)

_PROFILE: QWebEngineProfile | None = None


def _editor_profile() -> QWebEngineProfile:
    """Off-the-record profile shared by every editor page.

    The views would share the default profile implicitly anyway; making it explicit
    gives one place to switch features off, and keeps editor pages out of the
    default profile's cache and cookie jar. Created lazily because a QWebEngineProfile
    must not be instantiated before QApplication exists.
    """
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = QWebEngineProfile()  # unnamed == off-the-record
        _PROFILE.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        _PROFILE.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
    return _PROFILE


def _make_editor_html() -> str:
    t = _theme.current()
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{_theme.to_css_variables(t)}
  @font-face {{
    font-family: 'JetBrains Mono';
    src: url('{_JETBRAINS_MONO_URL}');
    font-weight: normal;
    font-style: normal;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; overflow: hidden; background: var(--hz-input-bg); }}
  #editor {{ height: 100%; }}
  .cm-editor {{ height: 100%; }}
</style>
</head>
<body>
<div id="editor"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="{_EDITOR_BUNDLE_URL}"></script>
</body>
</html>"""


class _EditorBridge(QObject):
    """QWebChannel endpoint. Owns the authoritative text mirror and generation counter."""

    # Python -> JS
    set_text_requested = Signal(str, int)

    # JS -> Python (the widget listens to these)
    text_pushed      = Signal(str)
    dirty_marked     = Signal()
    blurred          = Signal()
    ready            = Signal()
    font_size_pushed = Signal(int)
    shortcut_pushed  = Signal(str)
    image_started    = Signal()
    image_finished   = Signal(bool)

    def __init__(self, image_repo: ImageRepository | None, parent=None) -> None:
        super().__init__(parent)
        self._image_repo = image_repo
        self._text = ""
        self._generation = 0
        self._font_size = DEFAULT_FONT_SIZE
        self._placeholder = ""
        self._read_only = False

    # ── Python-side API ───────────────────────────────────────────────────
    def set_text(self, text: str) -> None:
        """Load a document programmatically. Bumps the generation so that any push
        still in flight for the previous document is discarded rather than echoed
        back as a user edit."""
        self._text = text
        self._generation += 1
        self.set_text_requested.emit(text, self._generation)

    def text(self) -> str:
        return self._text

    def set_mirror(self, text: str) -> None:
        """Overwrite the mirror without touching the generation (used by flush())."""
        self._text = text

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only

    def set_font_size(self, px: int) -> None:
        self._font_size = px

    def font_size(self) -> int:
        return self._font_size

    # ── Slots invoked from JavaScript ─────────────────────────────────────
    @Slot(result="QVariantMap")
    def get_initial_state(self) -> dict:
        """Pulled by the page once the channel connects, so a document set before the
        page finished loading is not lost."""
        return {
            "text": self._text,
            "generation": self._generation,
            "font_size": self._font_size,
            "placeholder": self._placeholder,
            "read_only": self._read_only,
        }

    @Slot(str, int)
    def push_text(self, text: str, generation: int) -> None:
        if generation != self._generation:
            return  # stale push from a document that has since been replaced
        if text == self._text:
            return
        self._text = text
        self.text_pushed.emit(text)

    @Slot()
    def mark_dirty(self) -> None:
        self.dirty_marked.emit()

    @Slot()
    def editor_blurred(self) -> None:
        self.blurred.emit()

    @Slot()
    def editor_ready(self) -> None:
        self.ready.emit()

    @Slot(int)
    def set_font_size_from_js(self, px: int) -> None:
        self._font_size = px
        self.font_size_pushed.emit(px)

    @Slot(str)
    def shortcut(self, name: str) -> None:
        self.shortcut_pushed.emit(name)

    @Slot()
    def image_upload_started(self) -> None:
        self.image_started.emit()

    @Slot(bool)
    def image_upload_finished(self, ok: bool) -> None:
        self.image_finished.emit(ok)

    @Slot(str, result=int)
    def store_image(self, data_url: str) -> int:
        """Persist a pasted image and return its id, or -1 on failure."""
        if self._image_repo is None:
            return -1
        try:
            _, _, b64 = data_url.partition(",")
            return self._image_repo.create(base64.b64decode(b64))
        except Exception as exc:
            print(f"Horizon: image paste failed: {exc}", file=sys.stderr)
            return -1


class _WebMarkdownToolbar(QWidget):
    """Vertical column of icon buttons driving the CodeMirror editor through JS.

    Kept as Qt widgets rather than HTML: the icons live in the Qt resource system and
    are recoloured at load time by theme.make_icon(), which a file:// page cannot reach.
    """

    def __init__(self, editor: "WebMarkdownEditor", parent=None) -> None:
        super().__init__(parent)
        self._editor = editor

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        def add_button(icon_name: str, tooltip: str, handler) -> QToolButton:
            btn = QToolButton(self)
            btn.setIcon(_theme.make_icon(f":/icons/{icon_name}.svg", _TOOLBAR_ICON_SIZE))
            btn.setIconSize(_TOOLBAR_ICON_SIZE)
            btn.setFixedSize(_TOOLBAR_BUTTON_SIZE)
            btn.setToolTip(tooltip)
            # Without NoFocus every click would steal DOM focus from the web view,
            # hiding the caret and firing a spurious blur/save.
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(handler)
            layout.addWidget(btn)
            return btn

        for level in (1, 2, 3, 4):
            add_button(
                f"heading{level}_cyan", f"Titre {level}",
                lambda _checked=False, lvl=level: self._editor.call_js("setHeading", lvl),
            )

        add_button("bullet_list_cyan", "Liste à puce", lambda: self._editor.call_js("toggleBulletList"))

        add_button("bold_cyan", "Gras", lambda: self._editor.call_js("wrapSelection", "**", "**", False))
        add_button("italic_cyan", "Italique", lambda: self._editor.call_js("wrapSelection", "*", "*", False))
        add_button("underline_cyan", "Souligné", lambda: self._editor.call_js("wrapSelection", "_", "_", True))
        add_button("strikethrough_cyan", "Barré", lambda: self._editor.call_js("wrapSelection", "~~", "~~", False))

        add_button("table_cyan", "Insérer un tableau", self._insert_table)
        add_button("link_external_cyan", "Insérer un lien externe", self._insert_external_link)
        add_button("link_internal_cyan", "Insérer un lien vers une note interne", self._insert_internal_link)
        add_button("mermaid_cyan", "Insérer un diagramme Mermaid", self._insert_mermaid)
        add_button("code_cyan", "Insérer un bloc de code", self._insert_code_block)

        layout.addStretch()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def _insert_table(self) -> None:
        self._editor.call_js(
            "insertBlock",
            "| Colonne 1 | Colonne 2 | Colonne 3 |\n"
            "| --- | --- | --- |\n"
            "|  |  |  |\n"
            "|  |  |  |",
        )

    def _insert_external_link(self) -> None:
        self._editor.call_js("insertInline", "[texte](https://exemple.com)")

    def _insert_internal_link(self) -> None:
        self._editor.call_js("insertInline", "[[id|texte]]")

    def _insert_mermaid(self) -> None:
        self._editor.call_js(
            "insertBlock",
            "```mermaid\n"
            "flowchart TD\n"
            "    A[Début] --> B{Condition}\n"
            "    B -->|Oui| C[Fin]\n"
            "    B -->|Non| A\n"
            "```",
        )

    def _insert_code_block(self) -> None:
        self._editor.call_js("insertBlock", "```python\nprint(\"Hello world\")\n```")


class WebMarkdownEditor(QWidget):
    """Drop-in-ish replacement for the old QPlainTextEdit-based MarkdownEditor.

    Deliberately does NOT reuse Qt method names (`setPlainText`, `toPlainText`,
    `blockSignals`): the semantics changed from synchronous to mirrored-async, and a
    silently-inert `blockSignals(True)` would be a timing-dependent bug.
    """

    text_changed      = Signal()
    editing_finished  = Signal()
    shortcut_pressed  = Signal(str)
    font_size_changed = Signal(int)
    flushed           = Signal()
    image_upload      = Signal(bool)  # True = started, False = finished
    editor_ready      = Signal()      # CodeMirror is live; call_js() lands from here on

    def __init__(
        self,
        image_repo: ImageRepository | None,
        parent=None,
        *,
        show_toolbar: bool = False,
        placeholder: str = "",
        prefs=None,
    ) -> None:
        super().__init__(parent)
        self._prefs = prefs
        self._ready = False
        self._js_dirty = False
        self._flushing = False

        self._bridge = _EditorBridge(image_repo, self)
        self._bridge.set_placeholder(placeholder)
        if prefs is not None:
            self._bridge.set_font_size(prefs.editor_font_size)

        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)

        # The view is built on first show, not here: these widgets are all constructed
        # at application startup but only one is ever visible, and a Chromium frame per
        # never-opened editor is pure cost. Text set before then is not lost — the
        # bridge holds it and the page pulls it via get_initial_state() on connect.
        self._view: QWebEngineView | None = None

        self._bridge.text_pushed.connect(self._on_text_pushed)
        self._bridge.dirty_marked.connect(self._on_dirty_marked)
        self._bridge.blurred.connect(self.editing_finished)
        self._bridge.ready.connect(self._on_ready)
        self._bridge.font_size_pushed.connect(self._on_font_size_pushed)
        self._bridge.shortcut_pushed.connect(self.shortcut_pressed)
        self._bridge.image_started.connect(lambda: self.image_upload.emit(True))
        self._bridge.image_finished.connect(lambda _ok: self.image_upload.emit(False))

        self._toolbar = _WebMarkdownToolbar(self, self) if show_toolbar else None

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        if self._toolbar is not None:
            self._layout.addWidget(self._toolbar)

    def _ensure_view(self) -> None:
        if self._view is not None:
            return
        page = QWebEnginePage(_editor_profile(), self)
        page.setWebChannel(self._channel)
        self._view = QWebEngineView(self)
        self._view.setPage(page)
        # Chromium's menu offers Reload, which would destroy the editor state.
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._layout.addWidget(self._view, stretch=1)
        self._view.setHtml(_make_editor_html(), _RESOURCES_BASE_URL)

    def showEvent(self, event) -> None:
        self._ensure_view()
        super().showEvent(event)

    # ── Content ───────────────────────────────────────────────────────────
    def set_text(self, text: str) -> None:
        """Load a document. Never emits `text_changed`."""
        self._js_dirty = False
        self._bridge.set_text(text)

    def text(self) -> str:
        """The mirrored document. Synchronous; may lag the editor by up to the JS
        debounce (~120 ms) unless `flush()` was called first."""
        return self._bridge.text()

    def flush(self, timeout_ms: int = 200) -> None:
        """Make `text()` exact by pulling the document straight out of JavaScript.

        A no-op unless JavaScript actually holds unpushed edits, which is the common
        case. Spins a nested QEventLoop: re-entrant by nature, so the render and
        autosave timers may fire while it runs — both are idempotent here.
        """
        if self._view is None or not self._ready or self._flushing or not self._js_dirty:
            return
        self._flushing = True
        loop = QEventLoop(self)

        def _done(value) -> None:
            if isinstance(value, str):
                self._bridge.set_mirror(value)
                self._js_dirty = False
            loop.quit()

        try:
            self._view.page().runJavaScript("window.HorizonEditor.readDoc()", _done)
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
        except RuntimeError:
            pass  # the view was already torn down
        finally:
            self._flushing = False
        self.flushed.emit()

    # ── State ─────────────────────────────────────────────────────────────
    def set_read_only(self, read_only: bool) -> None:
        self._bridge.set_read_only(read_only)
        self.call_js("setReadOnly", read_only)
        if self._toolbar is not None:
            self._toolbar.setEnabled(not read_only)

    def set_placeholder(self, text: str) -> None:
        self._bridge.set_placeholder(text)
        self.call_js("setPlaceholder", text)

    def focus_editor(self) -> None:
        self.call_js("focusEditor")

    # ── Zoom ──────────────────────────────────────────────────────────────
    def set_font_size(self, px: int) -> None:
        self._bridge.set_font_size(px)
        self.call_js("setFontSize", px)

    def font_size(self) -> int:
        return self._bridge.font_size()

    # ── JS plumbing ───────────────────────────────────────────────────────
    def call_js(self, fn: str, *args) -> None:
        """Invoke a window.HorizonEditor method. Arguments go through json.dumps so
        newlines, backticks, pipes and accented text survive intact."""
        if self._view is None:
            return  # not shown yet; state is carried by the bridge instead
        payload = ", ".join(json.dumps(a) for a in args)
        try:
            self._view.page().runJavaScript(f"window.HorizonEditor.{fn}({payload});")
        except RuntimeError:
            pass  # the view was already torn down

    def _on_ready(self) -> None:
        self._ready = True
        self.editor_ready.emit()

    def _on_text_pushed(self, _text: str) -> None:
        self._js_dirty = False
        self.text_changed.emit()

    def _on_dirty_marked(self) -> None:
        self._js_dirty = True

    def _on_font_size_pushed(self, px: int) -> None:
        if self._prefs is not None:
            self._prefs.editor_font_size = px  # persisted by the closeEvent handlers
        self.font_size_changed.emit(px)
