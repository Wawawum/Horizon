"""draw.io (diagrams.net) editor running inside a QWebEngineView.

The editor is draw.io's own web application, embedded in Horizon: the release archive
(`resources/drawio/draw.war`, fetched by `tools/fetch_drawio.py`) is served straight
from the zip on the horizon-drawio://app origin, so editing needs no network — some
corporate networks block embed.diagrams.net. A small wrapper page, served on the same
origin, loads draw.io in an <iframe> and relays its JSON embed protocol
(https://www.drawio.com/doc/faq/embed-mode) between the iframe and Python over a
QWebChannel. As with the note editors, Python keeps a synchronous mirror of the
document (`DrawioEditor.xml`), fed by draw.io's autosave events.
"""

import base64
import json
import zipfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QFile, QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.widgets.webeditor import _RESOURCES_DIR, _reply

DRAWIO_SCHEME = b"horizon-drawio"
DRAWIO_ORIGIN = "horizon-drawio://app"

_ARCHIVE      = _RESOURCES_DIR / "drawio" / "draw.war"
_WRAPPER_PATH = "horizon.html"
_CHANNEL_PATH = "qwebchannel.js"

_INIT_TIMEOUT_MS   = 20000  # without draw.io's init by then, it is deemed broken
_EXPORT_TIMEOUT_MS = 3000
_THUMBNAIL_SIZE    = QSize(320, 240)

# Requests the draw.io page may make; everything else (fonts, analytics, cloud pickers…)
# is cut off, so that a network that blocks or stalls them changes nothing.
_ALLOWED_SCHEMES = {DRAWIO_SCHEME.decode(), "data", "blob"}

_MIME_TYPES = {
    ".html": b"text/html;charset=utf-8",
    ".js":   b"text/javascript;charset=utf-8",
    ".css":  b"text/css;charset=utf-8",
    ".json": b"application/json",
    ".txt":  b"text/plain;charset=utf-8",
    ".xml":  b"application/xml",
    ".svg":  b"image/svg+xml",
    ".png":  b"image/png",
    ".gif":  b"image/gif",
    ".jpg":  b"image/jpeg",
    ".ico":  b"image/x-icon",
    ".woff": b"font/woff",
    ".woff2": b"font/woff2",
    ".ttf":  b"font/ttf",
    ".wasm": b"application/wasm",
}

_PROFILE: QWebEngineProfile | None = None


def register_drawio_scheme() -> None:
    """Declare horizon-drawio:// to Chromium; like webeditor.register_schemes(), must
    run before QApplication exists."""
    scheme = QWebEngineUrlScheme(DRAWIO_SCHEME)
    # Host, not Path: draw.io rebuilds its own URL from location.host at start-up (and
    # redirects when the result differs), and a host gives the page a real origin for
    # postMessage.
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    # SecureScheme: draw.io relies on secure-context APIs (clipboard, crypto).
    # CorsEnabled / FetchApiAllowed: it loads its translations, stencils and plugins
    # with XMLHttpRequest and fetch.
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.CorsEnabled
        | QWebEngineUrlScheme.Flag.FetchApiAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)


def drawio_available() -> bool:
    """Whether the embedded draw.io was fetched (tools/fetch_drawio.py)."""
    return _ARCHIVE.is_file()


def _drawio_query() -> str:
    # stealth=1: draw.io's switch for "no external services"; pwa=0: no service worker.
    params = ("embed=1&proto=json&spin=1&noSaveBtn=1&noExitBtn=1&saveAndExit=0"
              "&libraries=1&lang=fr&stealth=1&pwa=0")
    if _theme.current().is_dark:
        params += "&dark=1"
    return params


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
<iframe id="drawio" allow="clipboard-read; clipboard-write" src="index.html?{_drawio_query()}"></iframe>
<script src="{_CHANNEL_PATH}"></script>
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


class _DrawioSchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves horizon-drawio://app/<path>: draw.io's files straight from its release
    archive, plus the wrapper page and qwebchannel.js, which have to share draw.io's
    origin."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._archive: zipfile.ZipFile | None = None

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        path = job.requestUrl().path(QUrl.ComponentFormattingOption.FullyDecoded).lstrip("/")
        if path == _WRAPPER_PATH:
            _reply(job, _make_wrapper_html().encode("utf-8"), _MIME_TYPES[".html"])
            return
        if path == _CHANNEL_PATH:
            source = QFile(":/qtwebchannel/qwebchannel.js")
            if source.open(QFile.OpenModeFlag.ReadOnly):
                _reply(job, bytes(source.readAll()), _MIME_TYPES[".js"])
                return
        data = self._read(path or "index.html")
        if data is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        _reply(job, data, _MIME_TYPES.get(Path(path).suffix.lower(), b"application/octet-stream"))

    def _read(self, member: str) -> bytes | None:
        try:
            if self._archive is None:
                self._archive = zipfile.ZipFile(_ARCHIVE)
            return self._archive.read(member)
        except (OSError, KeyError, zipfile.BadZipFile):
            return None


class _ExternalRequestBlocker(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        if info.requestUrl().scheme() not in _ALLOWED_SCHEMES:
            info.block(True)


def _drawio_profile() -> QWebEngineProfile:
    """Off-the-record profile for the draw.io page, with the horizon-drawio:// handler
    and the external-request blocker. Not the note editors' profile: those pages do not
    need either. Created lazily because a QWebEngineProfile must not exist before
    QApplication."""
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = QWebEngineProfile()  # unnamed == off-the-record
        _PROFILE.setUrlRequestInterceptor(_ExternalRequestBlocker(_PROFILE))
        if QWebEngineUrlScheme.schemeByName(QByteArray(DRAWIO_SCHEME)).name():
            _PROFILE.installUrlSchemeHandler(QByteArray(DRAWIO_SCHEME), _DrawioSchemeHandler(_PROFILE))
        # Otherwise register_drawio_scheme() was not called: draw.io never answers.
    return _PROFILE


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
    hosts a third-party application."""

    message_received = Signal(str)

    @Slot(str)
    def receive(self, data: str) -> None:
        self.message_received.emit(data)


class DrawioEditor(QWidget):
    """One draw.io instance, reused from one diagram to the next through its `load` action."""

    xml_changed = Signal()   # the mirror changed (draw.io autosave or Ctrl+S)
    ready       = Signal()   # draw.io answered and holds the current diagram
    unavailable = Signal()   # draw.io never answered: archive missing or broken

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

        # Built on first show, like the note editors: no Chromium frame (nor 10 MB of
        # draw.io to parse) for a session that never opens a diagram.
        self._view: QWebEngineView | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def _ensure_view(self) -> None:
        if self._view is not None:
            return
        page = QWebEnginePage(_drawio_profile(), self)
        page.setWebChannel(self._channel)
        settings = page.settings()
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
        if not drawio_available():
            # No point waiting for the timeout; queued so that callers connected after
            # the first show still hear it.
            QTimer.singleShot(0, self.unavailable)
            return
        self._init_timer.start()
        self._view.load(QUrl(f"{DRAWIO_ORIGIN}/{_WRAPPER_PATH}"))

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
        """Render the current diagram to PNG, or None if draw.io is not there to do it."""
        return self._export("png", timeout_ms)

    def export_svg(self, timeout_ms: int = _EXPORT_TIMEOUT_MS) -> str | None:
        """Render the current diagram to SVG (shown in WYSIWYG notes), or None if
        draw.io is not there to do it."""
        data = self._export("svg", timeout_ms)
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _export(self, fmt: str, timeout_ms: int) -> bytes | None:
        """Ask draw.io for an export and wait for it.

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
            self._post({"action": "export", "format": fmt, "background": "#ffffff", "border": 10})
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
