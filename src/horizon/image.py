from __future__ import annotations

from horizon.database import Database


class ImageRepository:
    def __init__(self, db: Database) -> None:
        self._conn = db.conn

    def create(self, data: bytes) -> int:
        cur = self._conn.execute("INSERT INTO images (data) VALUES (?)", (data,))
        self._conn.commit()
        return cur.lastrowid

    def get(self, image_id: int) -> bytes | None:
        row = self._conn.execute(
            "SELECT data FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        return bytes(row["data"]) if row else None
