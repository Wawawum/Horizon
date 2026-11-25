"""Mind Elixir mind map editor running inside a QWebEngineView.

The JavaScript half is `web/src/mindmap.js`, bundled to
`resources/horizon-mindmap.bundle.{js,css}` (see `web/README.md`); it needs no network.
As with draw.io, Python keeps a synchronous mirror of the document
(`MindElixirEditor.document`: Mind Elixir's `getDataString()` JSON), fed by the page after
every operation, and asks the page for renderings — SVG for the notes, PNG for the list
thumbnail — through a nested event loop.
"""

import base64
import json

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.widgets.webeditor import _RESOURCES_BASE_URL, _RESOURCES_DIR, _editor_profile

_BUNDLE_URL = (_RESOURCES_DIR / "horizon-mindmap.bundle.js").as_uri()
_CSS_URL    = (_RESOURCES_DIR / "horizon-mindmap.bundle.css").as_uri()

_EXPORT_TIMEOUT_MS = 3000


def _make_page_html() -> str:
    t = _theme.current()
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="{_CSS_URL}">
<style>
{_theme.to_css_variables(t)}
  html, body {{ height: 100%; margin: 0; overflow: hidden; background: var(--hz-input-bg); }}
  #map {{ height: 100%; width: 100%; }}
  /* Arial: the font @erseco/mind-elixir-export-svg lays the SVG out for, so that the
     rendering shown in notes matches the editor. */
  .map-container {{ font-family: Arial, Helvetica, 'Liberation Sans', Arimo, sans-serif; }}
</style>
</head>
<body>
<div id="map"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="{_BUNDLE_URL}"></script>
</body>
</html>"""


class _MindmapBridge(QObject):
    """QWebChannel endpoint. Owns the mirror and the generation counter."""

    data_pushed     = Signal()
    ready           = Signal()
    export_received = Signal(int, str)  # request id, data URI ("" when the export failed)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data = ""
        self._generation = 0
        self._root_topic = ""

    def load(self, data: str, root_topic: str) -> int:
        self._data = data
        self._root_topic = root_topic
        self._generation += 1
        return self._generation

    def data(self) -> str:
        return self._data

    def set_mirror(self, data: str, generation: int) -> None:
        """Overwrite the mirror with what flush() read, unless the map was replaced since."""
        if generation == self._generation:
            self._data = data

    @Slot(result="QVariantMap")
    def get_initial_state(self) -> dict:
        """Pulled by the page once the channel connects, so a map loaded before the page
        finished loading is not lost."""
        return {
            "data": self._data,
            "generation": self._generation,
            "root_topic": self._root_topic,
            "dark": _theme.current().is_dark,
        }

    @Slot(str, int)
    def push_data(self, data: str, generation: int) -> None:
        if generation != self._generation or data == self._data:
            return  # stale push from a map since replaced, or nothing new
        self._data = data
        self.data_pushed.emit()

    @Slot(int)
    def editor_ready(self, generation: int) -> None:
        if generation == self._generation:
            self.ready.emit()

    @Slot(int, str)
    def export_done(self, request_id: int, data_uri: str) -> None:
        self.export_received.emit(request_id, data_uri)


class MindElixirEditor(QWidget):
    """One Mind Elixir page, reused from one mind map to the next."""

    document_changed = Signal()  # the mirror changed
    ready            = Signal()  # the page holds the current map

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loaded = False
        self._export_seq = 0

        self._bridge = _MindmapBridge(self)
        self._bridge.data_pushed.connect(self.document_changed)
        self._bridge.ready.connect(self._on_ready)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)

        # Built on first show, like the note editors and draw.io.
        self._view: QWebEngineView | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def _ensure_view(self) -> None:
        if self._view is not None:
            return
        page = QWebEnginePage(_editor_profile(), self)
        page.setWebChannel(self._channel)
        self._view = QWebEngineView(self)
        self._view.setPage(page)
        # Chromium's menu offers Reload, which would drop unsaved edits; Mind Elixir has its own.
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._layout.addWidget(self._view)
        self._view.setHtml(_make_page_html(), _RESOURCES_BASE_URL)

    def showEvent(self, event) -> None:
        self._ensure_view()
        super().showEvent(event)

    def _on_ready(self) -> None:
        self._loaded = True
        self.ready.emit()

    # ── Content ───────────────────────────────────────────────────────────
    def load_document(self, data: str, root_topic: str = "") -> None:
        """Open a mind map ("" for a new one, whose root topic is `root_topic`). Never
        emits `document_changed` for `data` itself; a new map is pushed back once created."""
        self._loaded = False
        generation = self._bridge.load(data, root_topic)
        self._call("load", data, generation, root_topic)
        # Before the page is up, get_initial_state() carries the map.

    def document(self) -> str:
        """The mirrored map, as of the page's last push."""
        return self._bridge.data()

    def is_loaded(self) -> bool:
        return self._loaded

    def flush(self, timeout_ms: int = 200) -> None:
        """Make `document()` exact by reading the map straight out of the page, which
        otherwise pushes it ~300 ms after the last operation. Spins a nested QEventLoop,
        like _WebEditorBase.flush()."""
        if self._view is None or not self._loaded:
            return
        loop = QEventLoop(self)

        def _done(value) -> None:
            try:
                doc = json.loads(value) if isinstance(value, str) and value else None
            except ValueError:
                doc = None
            if isinstance(doc, dict) and isinstance(doc.get("data"), str):
                self._bridge.set_mirror(doc["data"], int(doc.get("generation", -1)))
            loop.quit()

        try:
            self._view.page().runJavaScript(
                "window.HorizonMindmap ? window.HorizonMindmap.readDoc() : null", 0, _done)
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
        except RuntimeError:
            pass  # the view was already torn down

    def export_png(self, timeout_ms: int = _EXPORT_TIMEOUT_MS) -> bytes | None:
        """Render the current map to PNG, or None if the page is not there to do it."""
        return self._export("png", timeout_ms)

    def export_svg(self, timeout_ms: int = _EXPORT_TIMEOUT_MS) -> str | None:
        """Render the current map to SVG (shown in WYSIWYG notes), or None."""
        data = self._export("svg", timeout_ms)
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _export(self, fmt: str, timeout_ms: int) -> bytes | None:
        """Ask the page for a rendering and wait for it, in a nested QEventLoop (see
        DrawioEditor._export). The page pushes its data first, so the mirror is exact
        once this returns."""
        if self._view is None or not self._loaded:
            return None
        self._export_seq += 1
        request_id = self._export_seq
        result: list[str] = []
        loop = QEventLoop(self)

        def _done(rid: int, data_uri: str) -> None:
            if rid == request_id:
                result.append(data_uri)
                loop.quit()

        self._bridge.export_received.connect(_done)
        try:
            self._call("exportImage", fmt, request_id)
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
        finally:
            self._bridge.export_received.disconnect(_done)
        if not result:
            return None
        _, _, b64 = result[0].partition("base64,")
        if not b64:
            return None
        try:
            return base64.b64decode(b64)
        except ValueError:
            return None

    def _call(self, fn: str, *args) -> None:
        if self._view is None:
            return
        payload = ", ".join(json.dumps(a) for a in args)
        try:
            self._view.page().runJavaScript(
                f"window.HorizonMindmap && window.HorizonMindmap.{fn}({payload});")
        except RuntimeError:
            pass  # the view was already torn down
