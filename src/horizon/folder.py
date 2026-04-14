from dataclasses import dataclass

from horizon.database import Database


@dataclass
class Folder:
    id: int | None
    project_id: int
    parent_id: int | None
    name: str


class FolderRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, name: str, parent_id: int | None = None) -> "Folder":
        cur = self._db.conn.execute(
            "INSERT INTO folders (project_id, parent_id, name) VALUES (?, ?, ?)",
            (project_id, parent_id, name),
        )
        self._db.conn.commit()
        return Folder(id=cur.lastrowid, project_id=project_id, parent_id=parent_id, name=name)

    def list_for_project(self, project_id: int) -> list["Folder"]:
        rows = self._db.conn.execute(
            "SELECT id, project_id, parent_id, name FROM folders WHERE project_id = ? ORDER BY name COLLATE NOCASE",
            (project_id,),
        ).fetchall()
        return [
            Folder(id=row["id"], project_id=row["project_id"], parent_id=row["parent_id"], name=row["name"])
            for row in rows
        ]

    def rename(self, folder_id: int, new_name: str) -> None:
        self._db.conn.execute("UPDATE folders SET name = ? WHERE id = ?", (new_name, folder_id))
        self._db.conn.commit()

    def delete(self, folder_id: int) -> None:
        self._db.conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        self._db.conn.commit()

    def exists_with_name(self, project_id: int, parent_id: int | None, name: str) -> bool:
        row = self._db.conn.execute(
            "SELECT 1 FROM folders WHERE project_id = ? AND parent_id IS ? AND name = ? COLLATE NOCASE LIMIT 1",
            (project_id, parent_id, name),
        ).fetchone()
        return row is not None
