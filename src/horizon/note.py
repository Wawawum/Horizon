from dataclasses import dataclass
from datetime import datetime

from horizon.database import Database


@dataclass
class Note:
    id: int | None
    project_id: int
    title: str
    body: str
    dt: datetime  # stored as ISO-8601 TEXT in SQLite


class NoteRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, title: str, body: str = "", dt: datetime | None = None) -> Note:
        if dt is None:
            dt = datetime.now()
        cur = self._db.conn.execute(
            "INSERT INTO notes (project_id, title, body, dt) VALUES (?, ?, ?, ?)",
            (project_id, title, body, dt.isoformat()),
        )
        self._db.conn.commit()
        return Note(id=cur.lastrowid, project_id=project_id, title=title, body=body, dt=dt)

    def get(self, note_id: int) -> Note | None:
        row = self._db.conn.execute(
            "SELECT id, project_id, title, body, dt FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
        if row is None:
            return None
        return Note(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            body=row["body"],
            dt=datetime.fromisoformat(row["dt"]),
        )

    def list_all_for_project(self, project_id: int) -> list[Note]:
        rows = self._db.conn.execute(
            "SELECT id, project_id, title, body, dt FROM notes"
            " WHERE project_id = ? ORDER BY dt DESC",
            (project_id,),
        ).fetchall()
        return [
            Note(
                id=row["id"],
                project_id=row["project_id"],
                title=row["title"],
                body=row["body"],
                dt=datetime.fromisoformat(row["dt"]),
            )
            for row in rows
        ]

    def list_all(self) -> list[Note]:
        rows = self._db.conn.execute(
            "SELECT id, project_id, title, body, dt FROM notes ORDER BY dt DESC"
        ).fetchall()
        return [
            Note(
                id=row["id"],
                project_id=row["project_id"],
                title=row["title"],
                body=row["body"],
                dt=datetime.fromisoformat(row["dt"]),
            )
            for row in rows
        ]

    def update(self, note: Note) -> None:
        self._db.conn.execute(
            "UPDATE notes SET project_id = ?, title = ?, body = ?, dt = ? WHERE id = ?",
            (note.project_id, note.title, note.body, note.dt.isoformat(), note.id),
        )
        self._db.conn.commit()

    def delete(self, note_id: int) -> None:
        self._db.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._db.conn.commit()
