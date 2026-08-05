"""Références vers des fichiers `.archimate` externes.

Seul le *chemin* du fichier est persisté : le modèle est re-parsé à chaque
ouverture (voir `horizon.archimate_model`), afin que toute modification faite
dans Archi soit immédiatement visible. Un fichier introuvable reste référencé —
c'est l'UI qui le signale, la base n'oublie rien silencieusement.
"""

from dataclasses import dataclass, field
from datetime import datetime

from horizon.database import Database


@dataclass
class ArchimateModelRef:
    id: int | None
    name: str
    path: str
    project_id: int | None = None
    added_at: datetime = field(default_factory=datetime.now)


def _row_to_ref(r) -> "ArchimateModelRef":
    return ArchimateModelRef(
        id=r["id"],
        name=r["name"],
        path=r["path"],
        project_id=r["project_id"],
        added_at=datetime.fromisoformat(r["added_at"]) if r["added_at"] else datetime.now(),
    )


_COLUMNS = "id, project_id, name, path, added_at"


class ArchimateModelRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, name: str, path: str, project_id: int | None = None) -> "ArchimateModelRef":
        now = datetime.now().isoformat()
        cur = self._db.conn.execute(
            "INSERT INTO archimate_models (project_id, name, path, added_at) VALUES (?, ?, ?, ?)",
            (project_id, name, path, now),
        )
        self._db.conn.commit()
        return ArchimateModelRef(
            id=cur.lastrowid,
            name=name,
            path=path,
            project_id=project_id,
            added_at=datetime.fromisoformat(now),
        )

    def get(self, model_id: int) -> "ArchimateModelRef | None":
        row = self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM archimate_models WHERE id = ?", (model_id,)
        ).fetchone()
        return _row_to_ref(row) if row else None

    def find_by_path(self, path: str) -> "ArchimateModelRef | None":
        row = self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM archimate_models WHERE path = ?", (path,)
        ).fetchone()
        return _row_to_ref(row) if row else None

    def list_all(self) -> list["ArchimateModelRef"]:
        rows = self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM archimate_models ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
        return [_row_to_ref(r) for r in rows]

    def update(self, ref: "ArchimateModelRef") -> None:
        self._db.conn.execute(
            "UPDATE archimate_models SET name = ?, path = ?, project_id = ? WHERE id = ?",
            (ref.name, ref.path, ref.project_id, ref.id),
        )
        self._db.conn.commit()

    def delete(self, model_id: int) -> None:
        self._db.conn.execute("DELETE FROM archimate_models WHERE id = ?", (model_id,))
        self._db.conn.commit()
