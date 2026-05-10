import re
from dataclasses import dataclass

from horizon.database import Database


@dataclass
class SearchResult:
    type: str       # 'note' or 'task'
    entity_id: int
    title: str
    snippet: str    # HTML excerpt with <b>…</b> around matches


class SearchRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(self, query: str) -> list[SearchResult]:
        fts_query = self._build_query(query)
        if not fts_query:
            return []
        try:
            rows = self._db.conn.execute(
                "SELECT type, entity_id, title,"
                " snippet(search_index, -1, '<b>', '</b>', '…', 20) AS snippet"
                " FROM search_index"
                " WHERE search_index MATCH ?"
                " ORDER BY rank",
                (fts_query,),
            ).fetchall()
        except Exception:
            return []
        return [
            SearchResult(
                type=row["type"],
                entity_id=row["entity_id"],
                title=row["title"],
                snippet=row["snippet"],
            )
            for row in rows
        ]

    @staticmethod
    def _build_query(query: str) -> str:
        words = re.findall(r'\w+', query, re.UNICODE)
        return " ".join(f'"{w}"*' for w in words)
