from dataclasses import dataclass
from datetime import datetime

from horizon.database import Database


@dataclass
class Diagram:
    id: int | None
    project_id: int | None
    title: str
    xml: str                  # fichier draw.io (mxfile), tel que renvoyé par l'éditeur
    thumbnail: bytes | None   # PNG réduit pour la liste ; None tant que rien n'a été dessiné
    svg: str | None           # rendu affiché dans les notes WYSIWYG ; None tant que draw.io ne l'a pas exporté
    created_at: datetime      # stored as ISO-8601 TEXT in SQLite
    updated_at: datetime
    archived: bool = False


_COLUMNS = "id, project_id, title, xml, thumbnail, svg, created_at, updated_at, archived"


def _row_to_diagram(row) -> "Diagram":
    return Diagram(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        xml=row["xml"],
        thumbnail=bytes(row["thumbnail"]) if row["thumbnail"] is not None else None,
        svg=row["svg"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        archived=bool(row["archived"]),
    )


class DiagramRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, title: str, project_id: int | None = None) -> "Diagram":
        now = datetime.now()
        cur = self._db.conn.execute(
            "INSERT INTO diagrams (project_id, title, xml, thumbnail, svg, created_at, updated_at, archived)"
            " VALUES (?, ?, '', NULL, NULL, ?, ?, 0)",
            (project_id, title, now.isoformat(), now.isoformat()),
        )
        self._db.conn.commit()
        return Diagram(id=cur.lastrowid, project_id=project_id, title=title, xml="",
                       thumbnail=None, svg=None, created_at=now, updated_at=now)

    def get(self, diagram_id: int) -> "Diagram | None":
        row = self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM diagrams WHERE id = ?",
            (diagram_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_diagram(row)

    def list_all(self, archived_only: bool = False) -> list["Diagram"]:
        rows = self._db.conn.execute(
            "SELECT diagrams.id, diagrams.project_id, diagrams.title, diagrams.xml, diagrams.thumbnail,"
            " diagrams.svg, diagrams.created_at, diagrams.updated_at, diagrams.archived"
            " FROM diagrams LEFT JOIN projects ON diagrams.project_id = projects.id"
            " WHERE diagrams.archived = ? AND (diagrams.project_id IS NULL OR projects.archived = 0)"
            " ORDER BY diagrams.updated_at DESC",
            (int(archived_only),),
        ).fetchall()
        return [_row_to_diagram(row) for row in rows]

    def update(self, diagram: "Diagram") -> None:
        diagram.updated_at = datetime.now()
        self._db.conn.execute(
            "UPDATE diagrams SET project_id = ?, title = ?, xml = ?, thumbnail = ?, svg = ?, updated_at = ?,"
            " archived = ? WHERE id = ?",
            (diagram.project_id, diagram.title, diagram.xml, diagram.thumbnail, diagram.svg,
             diagram.updated_at.isoformat(), int(diagram.archived), diagram.id),
        )
        self._db.conn.commit()

    def delete(self, diagram_id: int) -> None:
        self._db.conn.execute("DELETE FROM diagrams WHERE id = ?", (diagram_id,))
        self._db.conn.commit()
