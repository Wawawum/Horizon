from dataclasses import dataclass

from horizon.database import Database


@dataclass
class Tag:
    id: int | None
    name: str


class TagRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_or_create(self, name: str) -> Tag:
        self._db.conn.execute(
            "INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,)
        )
        row = self._db.conn.execute(
            "SELECT id, name FROM tags WHERE name = ?", (name,)
        ).fetchone()
        return Tag(id=row["id"], name=row["name"])

    def list_for_note(self, note_id: int) -> list[Tag]:
        rows = self._db.conn.execute(
            "SELECT t.id, t.name FROM tags t"
            " JOIN note_tags nt ON nt.tag_id = t.id"
            " WHERE nt.note_id = ?"
            " ORDER BY t.name",
            (note_id,),
        ).fetchall()
        return [Tag(id=row["id"], name=row["name"]) for row in rows]

    def list_all(self) -> list[Tag]:
        rows = self._db.conn.execute(
            "SELECT id, name FROM tags ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [Tag(id=row["id"], name=row["name"]) for row in rows]

    def set_for_note(self, note_id: int, tag_names: list[str]) -> None:
        self._db.conn.execute(
            "DELETE FROM note_tags WHERE note_id = ?", (note_id,)
        )
        for name in tag_names:
            tag = self.get_or_create(name)
            self._db.conn.execute(
                "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?)",
                (note_id, tag.id),
            )
