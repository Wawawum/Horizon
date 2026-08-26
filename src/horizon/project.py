from dataclasses import dataclass

from horizon.database import Database


@dataclass
class Project:
    id: int | None
    name: str
    description: str
    archived: bool = False
    color: str = ""
    order: int = 0


class ProjectRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, name: str, description: str = "", archived: bool = False, color: str = "") -> Project:
        row = self._db.conn.execute(
            'SELECT COALESCE(MAX("order"), 0) + 1000 AS next_order FROM projects'
        ).fetchone()
        next_order: int = row["next_order"]
        cur = self._db.conn.execute(
            'INSERT INTO projects (name, description, archived, color, "order") VALUES (?, ?, ?, ?, ?)',
            (name, description, int(archived), color, next_order),
        )
        self._db.conn.execute(
            "INSERT INTO search_index(type, entity_id, title, body) VALUES ('project', ?, ?, ?)",
            (cur.lastrowid, name, description),
        )
        self._db.conn.commit()
        return Project(
            id=cur.lastrowid,
            name=name,
            description=description,
            archived=archived,
            color=color,
            order=next_order,
        )

    def get(self, project_id: int) -> Project | None:
        row = self._db.conn.execute(
            'SELECT id, name, description, archived, color, "order" FROM projects WHERE id = ?',
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
            order=row["order"],
        )

    def list_all(self, archived_only: bool | None = None) -> list[Project]:
        # archived_only=None : tous les projets ; True : les archivés ; False : les actifs.
        sql = 'SELECT id, name, description, archived, color, "order" FROM projects'
        params: tuple = ()
        if archived_only is not None:
            sql += " WHERE archived = ?"
            params = (int(archived_only),)
        sql += ' ORDER BY "order", id'
        rows = self._db.conn.execute(sql, params).fetchall()
        return [
            Project(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                archived=bool(row["archived"]),
                color=row["color"],
                order=row["order"],
            )
            for row in rows
        ]

    def set_order(self, project_ids: list[int]) -> None:
        # Rangs 1-based : 0 est la valeur sentinelle que la migration d'ordre
        # réinitialise au démarrage, aucun projet ne doit la porter.
        for i, pid in enumerate(project_ids, start=1):
            self._db.conn.execute(
                'UPDATE projects SET "order" = ? WHERE id = ?',
                (i * 1000, pid),
            )
        self._db.conn.commit()

    def update(self, project: Project) -> None:
        # "order" n'est volontairement pas touché ici : il appartient à set_order().
        self._db.conn.execute(
            "UPDATE projects SET name = ?, description = ?, archived = ?, color = ? WHERE id = ?",
            (project.name, project.description, int(project.archived), project.color, project.id),
        )
        self._db.conn.execute(
            "DELETE FROM search_index WHERE type='project' AND entity_id=?", (project.id,)
        )
        self._db.conn.execute(
            "INSERT INTO search_index(type, entity_id, title, body) VALUES ('project', ?, ?, ?)",
            (project.id, project.name, project.description),
        )
        self._db.conn.commit()

    def delete(self, project_id: int) -> None:
        self._db.conn.execute(
            "DELETE FROM projects WHERE id = ?", (project_id,)
        )
        self._db.conn.execute(
            "DELETE FROM search_index WHERE type='project' AND entity_id=?", (project_id,)
        )
        self._db.conn.commit()
