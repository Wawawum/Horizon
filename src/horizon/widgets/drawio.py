"""draw.io (diagrams.net) editor running inside a QWebEngineView.

The editor itself is the online embed of diagrams.net, loaded in an <iframe> by a small
local wrapper page; nothing of draw.io is bundled, so editing needs an Internet
connection. The wrapper relays draw.io's JSON embed protocol
(https://www.drawio.com/doc/faq/embed-mode) between the iframe and Python over a
QWebChannel. As with the note editors, Python keeps a synchronous mirror of the
document (`DrawioEditor.xml`), fed by draw.io's autosave events.
"""

import base64
import json

from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QObject, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.widgets.webeditor import _RESOURCES_BASE_URL

DRAWIO_ORIGIN = "https://embed.diagrams.net"

_INIT_TIMEOUT_MS   = 20000  # without draw.io's init by then, it is deemed unreachable
_EXPORT_TIMEOUT_MS = 3000
_THUMBNAIL_SIZE    = QSize(320, 240)

_PROFILE: QWebEngineProfile | None = None


def _drawio_profile() -> QWebEngineProfile:
    """Off-the-record profile for the draw.io page.

    Not the note editors' profile: that one disables the HTTP cache, which suits
    local pages but would download draw.io again on every open. The default
    off-the-record cache is in memory, so draw.io is fetched once per session.
    Created lazily because a QWebEngineProfile must not exist before QApplication.
    """
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = QWebEngineProfile()  # unnamed == off-the-record
    return _PROFILE


def _drawio_url() -> str:
    params = "embed=1&proto=json&spin=1&noSaveBtn=1&noExitBtn=1&saveAndExit=0&libraries=1&lang=fr"
    if _theme.current().is_dark:
        params += "&dark=1"
    return f"{DRAWIO_ORIGIN}/?{params}"


def _make_wrapper_html() -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ height: 100%; margin: 0; overflow: hidden; background: {_theme.current().input_bg}; }}
  iframe {{ border: 0; width: 100%; height: 100%; display: block; }}
</style>
</head>
<body>
<iframe id="drawio" allow="clipboard-read; clipboard-write" src="{_drawio_url()}"></iframe>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
(function () {{
  const ORIGIN = {json.dumps(DRAWIO_ORIGIN)};
  const frame = document.getElementById('drawio');
  let bridge = null;
  const queue = [];  // messages draw.io sent before the channel connected

  new QWebChannel(qt.webChannelTransport, function (channel) {{
    bridge = channel.objects.bridge;
    while (queue.length) bridge.receive(queue.shift());
  }});

  window.addEventListener('message', function (e) {{
    // Only draw.io's own frame may talk to Python.
    if (e.origin !== ORIGIN || e.source !== frame.contentWindow) return;
    const data = typeof e.data === 'string' ? e.data : JSON.stringify(e.data);
    if (bridge) bridge.receive(data); else queue.push(data);
  }});

  window.HorizonDrawio = {{
    post: function (message) {{ frame.contentWindow.postMessage(message, ORIGIN); }},
  }};
}})();
</script>
</body>
</html>"""


def make_thumbnail(png: bytes) -> bytes | None:
    """Shrink an exported PNG to list-thumbnail size; None if it cannot be decoded."""
    image = QImage()
    if not image.loadFromData(png) or image.isNull():
        return None
    if image.width() > _THUMBNAIL_SIZE.width() or image.height() > _THUMBNAIL_SIZE.height():
        image = image.scaled(
            _THUMBNAIL_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class _DrawioBridge(QObject):
    """QWebChannel endpoint. Deliberately exposes a single slot: the page it serves
    hosts remote content."""

    message_received = Signal(str)

    @Slot(str)
    def receive(self, data: str) -> None:
        self.message_received.emit(data)


class DrawioEditor(QWidget):
    """One draw.io instance, reused from one diagram to the next through its `load` action."""

    xml_changed = Signal()   # the mirror changed (draw.io autosave or Ctrl+S)
    ready       = Signal()   # draw.io answered and holds the current diagram
    unavailable = Signal()   # draw.io never answered: offline, or diagrams.net down

    _export_received = Signal(str)  # data URI, or "" when the export failed

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._xml = ""
        # draw.io sent its init event: it can receive actions from here on.
        self._initialized = False
        # draw.io confirmed loading the current diagram. False between a load action and
        # its load event, during which autosaves still belong to the previous diagram.
        self._loaded = False

        self._bridge = _DrawioBridge(self)
        self._bridge.message_received.connect(self._on_message)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)

        self._init_timer = QTimer(self)
        self._init_timer.setSingleShot(True)
        self._init_timer.setInterval(_INIT_TIMEOUT_MS)
        self._init_timer.timeout.connect(self.unavailable)

        # Built on first show, like the note editors: no Chromium frame (nor download of
        # draw.io) for a session that never opens a diagram.
        self._view: QWebEngineView | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def _ensure_view(self) -> None:
        if self._view is not None:
            return
        page = QWebEnginePage(_drawio_profile(), self)
        page.setWebChannel(self._channel)
        settings = page.settings()
        # The wrapper is a file:// page and draw.io an https:// iframe.
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
        self._view = QWebEngineView(self)
        self._view.setPage(page)
        # Chromium's menu offers Reload, which would drop unsaved edits.
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._layout.addWidget(self._view)
        self._load_page()

    def _load_page(self) -> None:
        self._initialized = False
        self._loaded = False
        self._init_timer.start()
        self._view.setHtml(_make_wrapper_html(), _RESOURCES_BASE_URL)

    def showEvent(self, event) -> None:
        self._ensure_view()
        super().showEvent(event)

    def reload(self) -> None:
        """Retry loading draw.io, after it was found unavailable."""
        if self._view is not None:
            self._load_page()

    # ── Content ───────────────────────────────────────────────────────────
    def load_xml(self, xml: str) -> None:
        """Open a diagram ("" for a blank one). Never emits `xml_changed`."""
        self._xml = xml
        self._loaded = False
        if self._initialized:
            self._send_load()
        # Otherwise the init handler sends it.

    def xml(self) -> str:
        """The mirrored diagram, as of draw.io's last autosave."""
        return self._xml

    def is_loaded(self) -> bool:
        return self._loaded

    def export_png(self, timeout_ms: int = _EXPORT_TIMEOUT_MS) -> bytes | None:
        """Render the current diagram to PNG, or None if draw.io is not there to do it.

        Spins a nested QEventLoop, like _WebEditorBase.flush(): the answer comes back
        asynchronously through the channel. Not to be called from a handler of a draw.io
        message (`ready`, `xml_changed`): the channel does not deliver the answer while
        that delivery is still on the stack, and the export times out.
        """
        if self._view is None or not self._loaded:
            return None
        result: list[str] = []
        loop = QEventLoop(self)

        def _done(data: str) -> None:
            result.append(data)
            loop.quit()

        self._export_received.connect(_done)
        try:
            self._post({"action": "export", "format": "png", "background": "#ffffff", "border": 10})
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
        finally:
            self._export_received.disconnect(_done)
        if not result:
            return None
        _, _, b64 = result[0].partition("base64,")
        if not b64:
            return None
        try:
            return base64.b64decode(b64)
        except ValueError:
            return None

    # ── Protocol ──────────────────────────────────────────────────────────
    def _post(self, message: dict) -> None:
        if self._view is None:
            return
        try:
            self._view.page().runJavaScript(
                f"window.HorizonDrawio && window.HorizonDrawio.post({json.dumps(json.dumps(message))});")
        except RuntimeError:
            pass  # the view was already torn down

    def _send_load(self) -> None:
        self._post({"action": "load", "xml": self._xml, "autosave": 1})

    def _on_message(self, data: str) -> None:
        try:
            message = json.loads(data)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        event = message.get("event")
        if event == "init":
            self._initialized = True
            self._init_timer.stop()
            self._send_load()
        elif event == "load":
            self._loaded = True
            self.ready.emit()
        elif event in ("autosave", "save"):
            xml = message.get("xml")
            if not self._loaded or not isinstance(xml, str) or xml == self._xml:
                return
            self._xml = xml
            self.xml_changed.emit()
        elif event == "export":
            data_uri = message.get("data")
            self._export_received.emit(data_uri if isinstance(data_uri, str) else "")
