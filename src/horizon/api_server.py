import json
import logging
import re
import threading
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from horizon.database import open_connection
from horizon.deliverable import Deliverable, DeliverableRepository, DeliverableState
from horizon.note import Note, NoteRepository, NoteVersion, NoteVersionRepository
from horizon.search import SearchRepository
from horizon.task import (
    Subtask, SubtaskRepository, Task, TaskBucket, TaskPriority, TaskRepository,
    TaskState,
)

logger = logging.getLogger(__name__)

_NOTES_ID_RE = re.compile(r"^/notes/(\d+)$")
_NOTES_VERSIONS_RE = re.compile(r"^/notes/(\d+)/versions$")
_PROJECTS_ID_RE = re.compile(r"^/projects/(\d+)$")
_TASKS_ID_RE = re.compile(r"^/tasks/(\d+)$")
_DELIVERABLES_ID_RE = re.compile(r"^/deliverables/(\d+)$")


def _port_file() -> Path:
    return Path.home() / ".horizon" / "api.port"


class _Db:
    """Minimal shim so repositories can access .conn without a full Database instance."""
    def __init__(self, conn) -> None:
        self.conn = conn


def _version_to_dict(v: NoteVersion) -> dict:
    return {"id": v.id, "note_id": v.note_id, "title": v.title, "body": v.body,
            "version_dt": v.version_dt.isoformat(), "is_current": v.is_current}


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


def _deliverable_to_dict(d: Deliverable) -> dict:
    return {"id": d.id, "project_id": d.project_id,
            "template_id": d.template_id, "title": d.title, "body": d.body,
            "state": d.state.value}


def _task_to_dict(task: Task, subtasks: list) -> dict:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "state": task.state.value,
        "priority": task.priority.value,
        "bucket": task.bucket.value,
        "order": task.order,
        "archived": task.archived,
        "subtasks": [
            {"id": s.id, "title": s.title, "completed": s.completed}
            for s in subtasks
        ],
    }


def _parse_enum(enum_class, value, field_name: str):
    try:
        return enum_class(value), None
    except ValueError:
        valid = [e.value for e in enum_class]
        return None, f"invalid {field_name}: must be one of {valid}"


def _sync_subtasks(conn, subtask_repo: SubtaskRepository, task_id: int, subtasks_input: list) -> list:
    existing = subtask_repo.list_for_task(task_id)
    existing_by_id = {s.id: s for s in existing}
    input_ids = {item["id"] for item in subtasks_input if isinstance(item.get("id"), int)}

    for s in existing:
        if s.id not in input_ids:
            subtask_repo.delete(s.id)

    result = []
    for item in subtasks_input:
        st_title = str(item.get("title", "")).strip()
        if not st_title:
            continue
        completed = bool(item.get("completed", False))
        item_id = item.get("id")

        if isinstance(item_id, int) and item_id in existing_by_id:
            existing_st = existing_by_id[item_id]
            if existing_st.title != st_title:
                conn.execute("UPDATE subtasks SET title = ? WHERE id = ?", (st_title, item_id))
                conn.commit()
            if existing_st.completed != completed:
                subtask_repo.set_completed(item_id, completed)
            result.append(Subtask(id=item_id, task_id=task_id, title=st_title, completed=completed))
        else:
            subtask = subtask_repo.create(task_id, st_title)
            if completed:
                subtask_repo.set_completed(subtask.id, True)
                subtask = Subtask(id=subtask.id, task_id=task_id, title=st_title, completed=True)
            result.append(subtask)

    return result


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
        elif m := _NOTES_VERSIONS_RE.match(path):
            self._handle_note_versions(int(m.group(1)))
        elif m := _NOTES_ID_RE.match(path):
            self._handle_note_detail(int(m.group(1)))
        elif m := _PROJECTS_ID_RE.match(path):
            self._handle_project_detail(int(m.group(1)))
        elif m := _TASKS_ID_RE.match(path):
            self._handle_task_detail(int(m.group(1)))
        elif m := _DELIVERABLES_ID_RE.match(path):
            self._handle_deliverable_detail(int(m.group(1)))
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_search(self, query_string: str) -> None:
        params = urllib.parse.parse_qs(query_string)
        q = (params.get("q", [""])[0]).strip()
        mode = params.get("mode", ["all"])[0]
        if mode not in ("all", "any"):
            mode = "all"
        if not q:
            self._send_json(400, {"error": "q parameter is required"})
            return

        conn = open_connection(self._db_path)
        try:
            results = SearchRepository(_Db(conn)).search(q, mode)
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

    def _handle_note_versions(self, note_id: int) -> None:
        conn = open_connection(self._db_path)
        try:
            note = NoteRepository(_Db(conn)).get(note_id)
            if note is None:
                self._send_json(404, {"error": "note not found"})
                return
            versions = NoteVersionRepository(_Db(conn)).list_for_note(note_id)
            self._send_json(200, {"versions": [_version_to_dict(v) for v in versions]})
        except Exception:
            logger.exception("Failed to list versions for note %d", note_id)
            self._send_json(500, {"error": "failed to list note versions"})
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
        elif self.path == "/tasks":
            self._handle_create_task()
        else:
            self._send_json(404, {"error": "not found"})

    def do_PUT(self) -> None:
        if m := _NOTES_ID_RE.match(self.path):
            self._handle_update_note(int(m.group(1)))
        elif m := _TASKS_ID_RE.match(self.path):
            self._handle_update_task(int(m.group(1)))
        elif m := _DELIVERABLES_ID_RE.match(self.path):
            self._handle_update_deliverable(int(m.group(1)))
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
            db = _Db(conn)
            note = NoteRepository(db).create(
                project_id=body.get("project_id"),
                title=title,
                body=body.get("body", ""),
                dt=dt,
                folder_id=body.get("folder_id"),
            )
            NoteVersionRepository(db).create_version(note)
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
            NoteVersionRepository(_Db(conn)).create_version(note)
            self._send_json(200, _note_to_dict(note))
        except Exception:
            logger.exception("Failed to update note %d", note_id)
            self._send_json(500, {"error": "failed to update note"})
        finally:
            conn.close()

    def _handle_task_detail(self, task_id: int) -> None:
        conn = open_connection(self._db_path)
        try:
            db = _Db(conn)
            task = TaskRepository(db).get(task_id)
            if task is None:
                self._send_json(404, {"error": "task not found"})
                return
            subtasks = SubtaskRepository(db).list_for_task(task_id)
            self._send_json(200, _task_to_dict(task, subtasks))
        except Exception:
            logger.exception("Failed to get task %d", task_id)
            self._send_json(500, {"error": "failed to get task"})
        finally:
            conn.close()

    def _handle_create_task(self) -> None:
        try:
            body = self._read_json_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid JSON body"})
            return

        project_id = body.get("project_id")
        if not isinstance(project_id, int):
            self._send_json(400, {"error": "project_id is required and must be an integer"})
            return

        title = body.get("title", "").strip()
        if not title:
            self._send_json(400, {"error": "title is required"})
            return

        state = TaskState.New
        if "state" in body:
            state, err = _parse_enum(TaskState, body["state"], "state")
            if err:
                self._send_json(400, {"error": err})
                return

        priority = TaskPriority.Medium
        if "priority" in body:
            priority, err = _parse_enum(TaskPriority, body["priority"], "priority")
            if err:
                self._send_json(400, {"error": err})
                return

        bucket = TaskBucket.Inbox
        if "bucket" in body:
            bucket, err = _parse_enum(TaskBucket, body["bucket"], "bucket")
            if err:
                self._send_json(400, {"error": err})
                return

        subtasks_input = body.get("subtasks", [])
        if not isinstance(subtasks_input, list):
            self._send_json(400, {"error": "subtasks must be a list"})
            return

        conn = open_connection(self._db_path)
        try:
            row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                self._send_json(404, {"error": f"project {project_id} not found"})
                return
            db = _Db(conn)
            task = TaskRepository(db).create(
                project_id=project_id,
                title=title,
                description=body.get("description", ""),
                state=state,
                priority=priority,
                bucket=bucket,
            )
            subtask_repo = SubtaskRepository(db)
            created_subtasks = []
            for st in subtasks_input:
                st_title = str(st.get("title", "")).strip()
                if not st_title:
                    continue
                subtask = subtask_repo.create(task.id, st_title)
                if st.get("completed"):
                    subtask_repo.set_completed(subtask.id, True)
                    subtask = Subtask(id=subtask.id, task_id=task.id, title=st_title, completed=True)
                created_subtasks.append(subtask)
            self._send_json(201, _task_to_dict(task, created_subtasks))
        except Exception:
            logger.exception("Failed to create task")
            self._send_json(500, {"error": "failed to create task"})
        finally:
            conn.close()

    def _handle_update_task(self, task_id: int) -> None:
        conn = open_connection(self._db_path)
        try:
            db = _Db(conn)
            task_repo = TaskRepository(db)
            task = task_repo.get(task_id)
            if task is None:
                self._send_json(404, {"error": "task not found"})
                return

            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "invalid JSON body"})
                return

            if "title" in body:
                title = body["title"].strip()
                if not title:
                    self._send_json(400, {"error": "title cannot be blank"})
                    return
                task.title = title

            if "description" in body:
                task.description = body["description"]

            if "state" in body:
                state, err = _parse_enum(TaskState, body["state"], "state")
                if err:
                    self._send_json(400, {"error": err})
                    return
                task.state = state

            if "priority" in body:
                priority, err = _parse_enum(TaskPriority, body["priority"], "priority")
                if err:
                    self._send_json(400, {"error": err})
                    return
                task.priority = priority

            if "bucket" in body:
                bucket, err = _parse_enum(TaskBucket, body["bucket"], "bucket")
                if err:
                    self._send_json(400, {"error": err})
                    return
                task.bucket = bucket

            if "archived" in body:
                task.archived = bool(body["archived"])

            task_repo.update(task)

            subtask_repo = SubtaskRepository(db)
            if "subtasks" in body:
                subtasks_input = body["subtasks"]
                if not isinstance(subtasks_input, list):
                    self._send_json(400, {"error": "subtasks must be a list"})
                    return
                final_subtasks = _sync_subtasks(conn, subtask_repo, task_id, subtasks_input)
            else:
                final_subtasks = subtask_repo.list_for_task(task_id)

            self._send_json(200, _task_to_dict(task, final_subtasks))
        except Exception:
            logger.exception("Failed to update task %d", task_id)
            self._send_json(500, {"error": "failed to update task"})
        finally:
            conn.close()

    def _handle_deliverable_detail(self, deliverable_id: int) -> None:
        conn = open_connection(self._db_path)
        try:
            deliverable = DeliverableRepository(_Db(conn)).get(deliverable_id)
            if deliverable is None:
                self._send_json(404, {"error": "deliverable not found"})
                return
            self._send_json(200, _deliverable_to_dict(deliverable))
        except Exception:
            logger.exception("Failed to get deliverable %d", deliverable_id)
            self._send_json(500, {"error": "failed to get deliverable"})
        finally:
            conn.close()

    def _handle_update_deliverable(self, deliverable_id: int) -> None:
        conn = open_connection(self._db_path)
        try:
            repo = DeliverableRepository(_Db(conn))
            deliverable = repo.get(deliverable_id)
            if deliverable is None:
                self._send_json(404, {"error": "deliverable not found"})
                return
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "invalid JSON body"})
                return
            if "title" in body:
                deliverable.title = body["title"]
            if "body" in body:
                deliverable.body = body["body"]
            if "state" in body:
                try:
                    deliverable.state = DeliverableState(body["state"])
                except ValueError:
                    self._send_json(400, {"error": f"invalid state: {body['state']!r}"})
                    return
            repo.update(deliverable)
            self._send_json(200, _deliverable_to_dict(deliverable))
        except Exception:
            logger.exception("Failed to update deliverable %d", deliverable_id)
            self._send_json(500, {"error": "failed to update deliverable"})
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
