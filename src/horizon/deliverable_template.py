from dataclasses import dataclass
from datetime import datetime

from horizon.database import Database


@dataclass
class DeliverableTemplate:
    id: int | None
    title: str
    template: str
    created_at: datetime


class DeliverableTemplateRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, title: str = "New Template") -> DeliverableTemplate:
        now = datetime.now()
        cur = self._db.conn.execute(
            "INSERT INTO deliverable_templates (title, template, created_at) VALUES (?, ?, ?)",
            (title, "", now.isoformat()),
        )
        self._db.conn.commit()
        return DeliverableTemplate(id=cur.lastrowid, title=title, template="", created_at=now)

    def get(self, template_id: int) -> DeliverableTemplate | None:
        row = self._db.conn.execute(
            "SELECT id, title, template, created_at FROM deliverable_templates WHERE id = ?",
            (template_id,),
        ).fetchone()
        if row is None:
            return None
        return DeliverableTemplate(
            id=row["id"],
            title=row["title"],
            template=row["template"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_all(self) -> list[DeliverableTemplate]:
        rows = self._db.conn.execute(
            "SELECT id, title, template, created_at FROM deliverable_templates ORDER BY created_at DESC"
        ).fetchall()
        return [
            DeliverableTemplate(
                id=r["id"],
                title=r["title"],
                template=r["template"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def update(self, tmpl: DeliverableTemplate) -> None:
        self._db.conn.execute(
            "UPDATE deliverable_templates SET title = ?, template = ? WHERE id = ?",
            (tmpl.title, tmpl.template, tmpl.id),
        )
        self._db.conn.commit()

    def delete(self, template_id: int) -> None:
        self._db.conn.execute(
            "DELETE FROM deliverable_templates WHERE id = ?",
            (template_id,),
        )
        self._db.conn.commit()
