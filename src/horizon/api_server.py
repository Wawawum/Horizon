import json
import logging
import re
import threading
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from horizon.database import open_connection
from horizon.note import Note, NoteRepository
from horizon.search import SearchRepository

logger = logging.getLogger(__name__)

_NOTES_ID_RE = re.compile(r"^/notes/(\d+)$")
_PROJECTS_ID_RE = re.compile(r"^/projects/(\d+)$")


def _port_file() -> Path:
    return Path.home() / ".horizon" / "api.port"


class _Db:
    """Minimal shim so repositories can access .conn without a full Database instance."""
    def __init__(self, conn) -> None:
        self.conn = conn


def _note_to_dict(note: Note, *, include_body: bool = True) -> dict:
    d = {
        "id": note.id,
        "project_id": note.project_id,
        "folder_id": note.folder_id,
        "title": note.title,
        "dt": note.dt.isoformat(),
        "archived": note.archived,
    }
    if include_body:
        d["body"] = note.body
    return d


def _make_handler(db_path: Path):
    class Handler(_Handler):
        _db_path = db_path
    return Handler


class _Handler(BaseHTTPRequestHandler):
    _db_path: Path

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/search":
            self._handle_search(parsed.query)
        elif path == "/notes":
            self._handle_notes_list()
        elif m := _NOTES_ID_RE.match(path):
            self._handle_note_detail(int(m.group(1)))
        elif m := _PROJECTS_ID_RE.match(path):
            self._handle_project_detail(int(m.group(1)))
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_search(self, query_string: str) -> None:
        params = urllib.parse.parse_qs(query_string)
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

    def _handle_notes_list(self) -> None:
        conn = open_connection(self._db_path)
        try:
            notes = NoteRepository(_Db(conn)).list_all()
            self._send_json(200, {"notes": [_note_to_dict(n, include_body=False) for n in notes]})
        except Exception:
            logger.exception("Failed to list notes")
            self._send_json(500, {"error": "failed to list notes"})
        finally:
            conn.close()

    def _handle_note_detail(self, note_id: int) -> None:
        conn = open_connection(self._db_path)
        try:
            note = NoteRepository(_Db(conn)).get(note_id)
            if note is None:
                self._send_json(404, {"error": "note not found"})
            else:
                self._send_json(200, _note_to_dict(note))
        except Exception:
            logger.exception("Failed to get note %d", note_id)
            self._send_json(500, {"error": "failed to get note"})
        finally:
            conn.close()

    def _handle_project_detail(self, project_id: int) -> None:
        conn = open_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT id, name, description, archived, color FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                self._send_json(404, {"error": "project not found"})
            else:
                self._send_json(200, {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "archived": bool(row["archived"]),
                    "color": row["color"],
                })
        except Exception:
            logger.exception("Failed to get project %d", project_id)
            self._send_json(500, {"error": "failed to get project"})
        finally:
            conn.close()

    def do_POST(self) -> None:
        if self.path == "/notes":
            self._handle_create_note()
        else:
            self._send_json(404, {"error": "not found"})

    def do_PUT(self) -> None:
        if m := _NOTES_ID_RE.match(self.path):
            self._handle_update_note(int(m.group(1)))
        else:
            self._send_json(404, {"error": "not found"})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def _handle_create_note(self) -> None:
        try:
            body = self._read_json_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid JSON body"})
            return
        title = body.get("title", "").strip()
        if not title:
            self._send_json(400, {"error": "title is required"})
            return
        dt_raw = body.get("dt")
        try:
            dt = datetime.fromisoformat(dt_raw) if dt_raw else None
        except ValueError:
            self._send_json(400, {"error": "invalid dt format, expected ISO-8601"})
            return
        conn = open_connection(self._db_path)
        try:
            note = NoteRepository(_Db(conn)).create(
                project_id=body.get("project_id"),
                title=title,
                body=body.get("body", ""),
                dt=dt,
                folder_id=body.get("folder_id"),
            )
            self._send_json(201, _note_to_dict(note))
        except Exception:
            logger.exception("Failed to create note")
            self._send_json(500, {"error": "failed to create note"})
        finally:
            conn.close()

    def _handle_update_note(self, note_id: int) -> None:
        conn = open_connection(self._db_path)
        try:
            repo = NoteRepository(_Db(conn))
            note = repo.get(note_id)
            if note is None:
                self._send_json(404, {"error": "note not found"})
                return
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "invalid JSON body"})
                return
            if "title" in body:
                note.title = body["title"]
            if "body" in body:
                note.body = body["body"]
            if "project_id" in body:
                note.project_id = body["project_id"]
            if "folder_id" in body:
                note.folder_id = body["folder_id"]
            if "archived" in body:
                note.archived = bool(body["archived"])
            if "dt" in body:
                try:
                    note.dt = datetime.fromisoformat(body["dt"])
                except ValueError:
                    self._send_json(400, {"error": "invalid dt format, expected ISO-8601"})
                    return
            repo.update(note)
            self._send_json(200, _note_to_dict(note))
        except Exception:
            logger.exception("Failed to update note %d", note_id)
            self._send_json(500, {"error": "failed to update note"})
        finally:
            conn.close()

    def _send_json(self, status: int, data) -> None:
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
        _port_file().write_text(str(self._port))

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        _port_file().unlink(missing_ok=True)
