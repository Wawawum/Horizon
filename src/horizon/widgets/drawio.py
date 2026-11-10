"""draw.io (diagrams.net) editor running inside a QWebEngineView.

The editor is draw.io's own web application, embedded in Horizon: the release archive
(`resources/drawio/draw.war`, fetched by `tools/fetch_drawio.py`) is served straight
from the zip on the horizon-drawio://app origin, so editing needs no network — some
corporate networks block embed.diagrams.net. A small wrapper page, served on the same
origin, loads draw.io in an <iframe> and relays its JSON embed protocol
(https://www.drawio.com/doc/faq/embed-mode) between the iframe and Python over a
QWebChannel. As with the note editors, Python keeps a synchronous mirror of the
document (`DrawioEditor.xml`), fed by draw.io's autosave events.

Start-up is traced to `~/.horizon/drawio.log` (served files, blocked requests, console
messages, a snapshot of the page when draw.io never answers): the failures it is
meant to explain happen on machines the developer cannot reach.
"""

import base64
import json
import os
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import PySide6
from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QFile, QObject, QSize, Qt, QTimer, QUrl, Signal, Slot, qVersion
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
    qWebEngineChromiumVersion,
    qWebEngineVersion,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.version import current_version
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

LOG_PATH       = Path.home() / ".horizon" / "drawio.log"
_LOG_MAX_BYTES = 1024 * 1024  # beyond that, the previous log moves to drawio.log.old
_log_rotated   = False
# Between a page load and draw.io's init, every served file and console message is
# logged; afterwards only failures, so that a working editor writes next to nothing.
_tracing = False


def log(message: str) -> None:
    """Append to the draw.io diagnostic log; never raises."""
    global _log_rotated
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not _log_rotated:
            _log_rotated = True
            if LOG_PATH.exists() and LOG_PATH.stat().st_size > _LOG_MAX_BYTES:
                LOG_PATH.replace(LOG_PATH.with_name(LOG_PATH.name + ".old"))
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}"[:-3] + f"  {message}\n")
    except OSError:
        pass


def _archive_problem() -> str | None:
    """Why the archive cannot serve draw.io, or None when it can. Reads index.html for
    real: an antivirus may leave the file in place but deny or quarantine its content."""
    if not _ARCHIVE.is_file():
        return f"archive draw.io absente ({_ARCHIVE}) — réinstallez Horizon (pip install .), qui la télécharge"
    try:
        with zipfile.ZipFile(_ARCHIVE) as archive:
            archive.read("index.html")
            archive.getinfo("js/app.min.js")
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        return f"archive draw.io illisible ({_ARCHIVE}) : {e!r}"
    return None


def _log_environment() -> None:
    scheme = QWebEngineUrlScheme.schemeByName(QByteArray(DRAWIO_SCHEME))
    size = _ARCHIVE.stat().st_size if _ARCHIVE.is_file() else None
    log("──── chargement de draw.io")
    log(f"Horizon {current_version()} ({'exécutable' if getattr(sys, 'frozen', False) else 'sources'}), "
        f"Python {platform.python_version()}, {platform.platform()}")
    log(f"PySide6 {PySide6.__version__}, Qt {qVersion()}, QtWebEngine {qWebEngineVersion()}, "
        f"Chromium {qWebEngineChromiumVersion()}")
    log(f"archive : {_ARCHIVE} ({size} octets)")
    log(f"schéma {DRAWIO_SCHEME.decode()} déclaré : {bool(scheme.name())}")
    for name in ("QTWEBENGINE_CHROMIUM_FLAGS", "QTWEBENGINE_DISABLE_SANDBOX", "QT_OPENGL", "HTTPS_PROXY"):
        if os.environ.get(name):
            log(f"{name}={os.environ[name]}")


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

  // Start-up milestones for the diagnostic log, through the same single slot.
  function diag(step) {{
    const data = JSON.stringify({{ horizonDiag: step }});
    if (bridge) bridge.receive(data); else queue.push(data);
  }}
  window.addEventListener('error', function (e) {{
    diag('erreur JS : ' + e.message + ' (' + e.filename + ':' + e.lineno + ')');
  }});
  frame.addEventListener('load', function () {{
    let href = '?';
    try {{ href = frame.contentWindow.location.href; }} catch (err) {{ href = String(err); }}
    diag('iframe chargée : ' + href);
  }});

  if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined') {{
    console.error('QWebChannel indisponible : qwebchannel.js non chargé ou qt.webChannelTransport absent');
  }} else {{
    new QWebChannel(qt.webChannelTransport, function (channel) {{
      bridge = channel.objects.bridge;
      bridge.receive(JSON.stringify({{ horizonDiag: 'canal Python connecté' }}));
      while (queue.length) bridge.receive(queue.shift());
    }});
  }}

  window.addEventListener('message', function (e) {{
    // Only draw.io's own frame may talk to Python.
    if (e.origin !== ORIGIN || e.source !== frame.contentWindow) {{
      diag('message ignoré : origine ' + e.origin + ', source = iframe : ' + (e.source === frame.contentWindow));
      return;
    }}
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


# Run in the wrapper page when draw.io never answered: how far did it get?
_SNAPSHOT_JS = """(function () {
  const r = { wrapper: document.readyState, qt: typeof qt, QWebChannel: typeof QWebChannel };
  try {
    const w = document.getElementById('drawio').contentWindow;
    r.iframe = w.location.href;
    r.iframeState = w.document.readyState;
    r.App = typeof w.App;
    r.mxClient = typeof w.mxClient;
    const status = w.document.getElementById('geStatus');
    r.geStatus = status ? status.textContent : null;
    r.scripts = Array.from(w.document.scripts).map(function (s) { return s.src; }).filter(Boolean);
  } catch (e) {
    r.iframeError = String(e);
  }
  return JSON.stringify(r);
})()"""


class _DrawioSchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves horizon-drawio://app/<path>: draw.io's files straight from its release
    archive, plus the wrapper page and qwebchannel.js, which have to share draw.io's
    origin."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._archive: zipfile.ZipFile | None = None

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        path = job.requestUrl().path(QUrl.ComponentFormattingOption.FullyDecoded).lstrip("/")
        try:
            self._serve(job, path)
        except Exception as e:  # a Python exception here would leave the request hanging
            log(f"ERREUR en servant {path} : {e!r}")
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)

    def _serve(self, job: QWebEngineUrlRequestJob, path: str) -> None:
        if path == _WRAPPER_PATH:
            data, mime = _make_wrapper_html().encode("utf-8"), _MIME_TYPES[".html"]
        elif path == _CHANNEL_PATH:
            source = QFile(":/qtwebchannel/qwebchannel.js")
            if not source.open(QFile.OpenModeFlag.ReadOnly):
                log(f"ERREUR : ressource Qt {source.fileName()} introuvable ({source.errorString()})")
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            data, mime = bytes(source.readAll()), _MIME_TYPES[".js"]
        else:
            data = self._read(path or "index.html")
            if data is None:
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            mime = _MIME_TYPES.get(Path(path).suffix.lower(), b"application/octet-stream")
        if _tracing:
            log(f"servi {path} ({len(data)} octets)")
        _reply(job, data, mime)

    def _read(self, member: str) -> bytes | None:
        try:
            if self._archive is None:
                self._archive = zipfile.ZipFile(_ARCHIVE)
            return self._archive.read(member)
        except KeyError:
            log(f"introuvable dans l'archive : {member}")
        except (OSError, zipfile.BadZipFile) as e:
            log(f"ERREUR de lecture de {member} dans {_ARCHIVE} : {e!r}")
            self._archive = None  # reopen next time, in case it was transient
        return None


class _ExternalRequestBlocker(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        if info.requestUrl().scheme() not in _ALLOWED_SCHEMES:
            info.block(True)
            if _tracing:
                log(f"requête externe bloquée : {info.requestUrl().toString()[:200]}")


class _DrawioPage(QWebEnginePage):
    """Forwards the page's console (draw.io's iframe included) to the diagnostic log."""

    def javaScriptConsoleMessage(self, level, message: str, line: int, source: str) -> None:
        is_error = level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel
        if _tracing or is_error:
            log(f"console {level.name.removesuffix('MessageLevel').lower()} : {message[:500]} ({source}:{line})")


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
        else:
            log("ERREUR : register_drawio_scheme() n'a pas été appelé, draw.io ne répondra pas")
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

    xml_changed = Signal()     # the mirror changed (draw.io autosave or Ctrl+S)
    ready       = Signal()     # draw.io answered and holds the current diagram
    unavailable = Signal(str)  # draw.io cannot start; the reason, in French, for the user

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
        self._init_timer.timeout.connect(self._on_init_timeout)
        self._load_started_at = datetime.now()

        # Built on first show, like the note editors: no Chromium frame (nor 10 MB of
        # draw.io to parse) for a session that never opens a diagram.
        self._view: QWebEngineView | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def _ensure_view(self) -> None:
        if self._view is not None:
            return
        page = _DrawioPage(_drawio_profile(), self)
        page.setWebChannel(self._channel)
        page.loadFinished.connect(self._on_load_finished)
        page.renderProcessTerminated.connect(self._on_render_process_terminated)
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
        global _tracing
        self._initialized = False
        self._loaded = False
        self._load_started_at = datetime.now()
        _tracing = True
        _log_environment()
        problem = _archive_problem()
        if problem is not None:
            # No point waiting for the timeout; queued so that callers connected after
            # the first show still hear it.
            QTimer.singleShot(0, lambda: self._fail(problem))
            return
        self._init_timer.start()
        self._view.load(QUrl(f"{DRAWIO_ORIGIN}/{_WRAPPER_PATH}"))

    def _elapsed(self) -> str:
        return f"{(datetime.now() - self._load_started_at).total_seconds():.1f} s"

    def _fail(self, reason: str) -> None:
        global _tracing
        self._init_timer.stop()
        _tracing = False
        log(f"ÉCHEC : {reason}")
        self.unavailable.emit(reason)

    def _on_load_finished(self, ok: bool) -> None:
        if _tracing or not ok:
            log(f"page {'chargée' if ok else 'NON chargée'} après {self._elapsed()}")

    def _on_render_process_terminated(self, status, exit_code: int) -> None:
        if status == QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus:
            return
        self._initialized = False
        self._loaded = False
        self._fail(f"le moteur web s'est arrêté ({status.name}, code {exit_code})")

    def _on_init_timeout(self) -> None:
        # The snapshot comes back asynchronously, after the failure is logged.
        if self._view is not None:
            self._view.page().runJavaScript(_SNAPSHOT_JS, 0, lambda r: log(f"état de la page : {r}"))
        self._fail(f"draw.io n'a pas répondu en {_INIT_TIMEOUT_MS // 1000} s")

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
        global _tracing
        try:
            message = json.loads(data)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        if "horizonDiag" in message:  # a start-up milestone from the wrapper page
            log(f"page : {str(message['horizonDiag'])[:500]}")
            return
        event = message.get("event")
        if event == "init":
            if _tracing:
                log(f"draw.io a répondu (init) après {self._elapsed()}")
            self._initialized = True
            self._init_timer.stop()
            self._send_load()
        elif event == "load":
            if _tracing:
                log(f"diagramme chargé après {self._elapsed()}")
                _tracing = False
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
