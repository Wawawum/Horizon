from dataclasses import dataclass, field
from datetime import datetime

from horizon.database import Database


@dataclass
class Deliverable:
    id: int | None
    project_id: int
    template_id: int | None
    title: str
    body: str
    created_at: datetime = field(default_factory=datetime.now)


class DeliverableRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, title: str, body: str, template_id: int | None = None) -> "Deliverable":
        now = datetime.now().isoformat()
        cur = self._db.conn.execute(
            "INSERT INTO deliverables (project_id, template_id, title, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, template_id, title, body, now),
        )
        self._db.conn.commit()
        return Deliverable(id=cur.lastrowid, project_id=project_id, template_id=template_id, title=title, body=body, created_at=datetime.fromisoformat(now))

    def get(self, deliverable_id: int) -> "Deliverable | None":
        row = self._db.conn.execute(
            "SELECT id, project_id, template_id, title, body, created_at FROM deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
        if row is None:
            return None
        return Deliverable(
            id=row["id"],
            project_id=row["project_id"],
            template_id=row["template_id"],
            title=row["title"],
            body=row["body"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
        )

    def list_for_project(self, project_id: int) -> list["Deliverable"]:
        rows = self._db.conn.execute(
            "SELECT id, project_id, template_id, title, body, created_at FROM deliverables WHERE project_id = ? ORDER BY title ASC",
            (project_id,),
        ).fetchall()
        return [
            Deliverable(
                id=r["id"],
                project_id=r["project_id"],
                template_id=r["template_id"],
                title=r["title"],
                body=r["body"],
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.now(),
            )
            for r in rows
        ]

    def list_all(self) -> list["Deliverable"]:
        rows = self._db.conn.execute(
            "SELECT d.id, d.project_id, d.template_id, d.title, d.body, d.created_at"
            " FROM deliverables d"
            " JOIN projects p ON d.project_id = p.id"
            " WHERE p.archived = 0"
            " ORDER BY d.created_at DESC"
        ).fetchall()
        return [
            Deliverable(
                id=r["id"],
                project_id=r["project_id"],
                template_id=r["template_id"],
                title=r["title"],
                body=r["body"],
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.now(),
            )
            for r in rows
        ]

    def update(self, deliverable: "Deliverable") -> None:
        self._db.conn.execute(
            "UPDATE deliverables SET title = ?, body = ? WHERE id = ?",
            (deliverable.title, deliverable.body, deliverable.id),
        )
        self._db.conn.commit()

    def delete(self, deliverable_id: int) -> None:
        self._db.conn.execute("DELETE FROM deliverables WHERE id = ?", (deliverable_id,))
        self._db.conn.commit()
