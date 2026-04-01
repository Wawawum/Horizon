from dataclasses import dataclass

from horizon.database import Database


@dataclass
class Project:
    id: int | None
    name: str
    description: str


class ProjectRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, name: str, description: str = "") -> Project:
        cur = self._db.conn.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (name, description),
        )
        self._db.conn.commit()
        return Project(id=cur.lastrowid, name=name, description=description)

    def get(self, project_id: int) -> Project | None:
        row = self._db.conn.execute(
            "SELECT id, name, description FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return Project(**row) if row else None

    def list_all(self) -> list[Project]:
        rows = self._db.conn.execute(
            "SELECT id, name, description FROM projects ORDER BY id"
        ).fetchall()
        return [Project(**row) for row in rows]

    def update(self, project: Project) -> None:
        self._db.conn.execute(
            "UPDATE projects SET name = ?, description = ? WHERE id = ?",
            (project.name, project.description, project.id),
        )
        self._db.conn.commit()

    def delete(self, project_id: int) -> None:
        self._db.conn.execute(
            "DELETE FROM projects WHERE id = ?", (project_id,)
        )
        self._db.conn.commit()
