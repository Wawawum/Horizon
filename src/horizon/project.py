from dataclasses import dataclass

from horizon.database import Database


@dataclass
class Project:
    id: int | None
    name: str
    description: str
    archived: bool = False
    color: str = ""


class ProjectRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, name: str, description: str = "", archived: bool = False, color: str = "") -> Project:
        cur = self._db.conn.execute(
            "INSERT INTO projects (name, description, archived, color) VALUES (?, ?, ?, ?)",
            (name, description, int(archived), color),
        )
        self._db.conn.commit()
        return Project(id=cur.lastrowid, name=name, description=description, archived=archived, color=color)

    def get(self, project_id: int) -> Project | None:
        row = self._db.conn.execute(
            "SELECT id, name, description, archived, color FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            archived=bool(row["archived"]),
            color=row["color"],
        )

    def list_all(self) -> list[Project]:
        rows = self._db.conn.execute(
            "SELECT id, name, description, archived, color FROM projects ORDER BY id"
        ).fetchall()
        return [
            Project(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                archived=bool(row["archived"]),
                color=row["color"],
            )
            for row in rows
        ]

    def update(self, project: Project) -> None:
        self._db.conn.execute(
            "UPDATE projects SET name = ?, description = ?, archived = ?, color = ? WHERE id = ?",
            (project.name, project.description, int(project.archived), project.color, project.id),
        )
        self._db.conn.commit()

    def delete(self, project_id: int) -> None:
        self._db.conn.execute(
            "DELETE FROM projects WHERE id = ?", (project_id,)
        )
        self._db.conn.commit()
