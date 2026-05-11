import json
import logging
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from horizon.database import open_connection
from horizon.search import SearchRepository

logger = logging.getLogger(__name__)


class _Db:
    """Minimal shim so SearchRepository can access .conn without a full Database instance."""
    def __init__(self, conn) -> None:
        self.conn = conn


def _make_handler(db_path: Path):
    class Handler(_SearchHandler):
        _db_path = db_path
    return Handler


class _SearchHandler(BaseHTTPRequestHandler):
    _db_path: Path

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/search":
            self._send_json(404, {"error": "not found"})
            return

        params = urllib.parse.parse_qs(parsed.query)
        q_values = params.get("q", [])
        q = q_values[0].strip() if q_values else ""
        if not q:
            self._send_json(400, {"error": "q parameter is required"})
            return

        conn = open_connection(self._db_path)
        try:
            results = SearchRepository(_Db(conn)).search(q)
            payload = {
                "results": [
                    {"type": r.type, "id": r.entity_id, "title": r.title, "body": r.snippet}
                    for r in results
                ]
            }
            self._send_json(200, payload)
        except Exception:
            logger.exception("Search failed for query %r", q)
            self._send_json(500, {"error": "search failed"})
        finally:
            conn.close()

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args) -> None:
        pass


class ApiServer:
    def __init__(self, port: int, db_path: Path) -> None:
        self._port = port
        self._db_path = db_path
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            handler = _make_handler(self._db_path)
            self._server = ThreadingHTTPServer(("127.0.0.1", self._port), handler)
        except OSError:
            logger.warning("Horizon API: port %d already in use, API disabled.", self._port)
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="horizon-api",
        )
        self._thread.start()
        logger.info("Horizon API listening on http://127.0.0.1:%d", self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
