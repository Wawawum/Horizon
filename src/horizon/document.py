import html as _html
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote, urlsplit

from horizon.database import Database

# Premier lien d'un fragment HTML. Le presse-papiers Windows encapsule le
# fragment copié (CF_HTML) : wrapper <html><body>, marqueurs <!--StartFragment-->
# et parfois un second <html> imbriqué. On ne cherche donc pas à parser la
# structure, seulement la première ancre.
_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")

#: Schémas acceptés pour un lien de document (partagé avec la cible de dépôt).
URL_SCHEMES = ("http://", "https://", "file://")


def _name_from_url(url: str) -> str:
    """Nom lisible déduit d'une URL : dernier segment de chemin, décodé.

    Les URLs SharePoint contiennent des `%20` (« Documents%20partages ») et se
    terminent par le nom de fichier pour les liens directs."""
    path = urlsplit(url).path
    segment = unquote(path.rstrip("/").rsplit("/", 1)[-1]) if path else ""
    return segment.strip() or url


def extract_document_link(
    html: str | None, text: str | None, urls: list[str] | None = None
) -> "tuple[str, str] | None":
    """Retourne (name, url) à partir d'un presse-papiers / drop, ou None.

    Les trois sources sont celles d'un QMimeData, par ordre de fiabilité décroissante.
    SharePoint ne publie ni `text/uri-list` ni URL exploitable au glisser : son option
    « Copier le lien » ne fournit que du HTML et du texte brut. Le HTML est donc la
    source privilégiée, car son ancre porte à la fois l'URL et le nom du document."""
    if html:
        match = _ANCHOR_RE.search(html)
        if match is not None:
            url = _html.unescape(match.group(1)).strip()
            label = _html.unescape(_TAG_RE.sub("", match.group(2))).strip()
            if url.startswith(URL_SCHEMES):
                return (label or _name_from_url(url), url)

    if text:
        candidate = text.strip()
        # Une URL seule, pas un texte quelconque qui en contiendrait une.
        if candidate.startswith(URL_SCHEMES) and not candidate.split()[1:]:
            return (_name_from_url(candidate), candidate)

    for url in urls or []:
        candidate = url.strip()
        if candidate.startswith(URL_SCHEMES):
            return (_name_from_url(candidate), candidate)

    return None


@dataclass
class Document:
    id: int | None
    project_id: int
    folder_id: int | None  # None = racine du projet
    name: str
    url: str
    created_at: datetime


class DocumentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, name: str, url: str, folder_id: int | None = None, created_at: datetime | None = None) -> "Document":
        if created_at is None:
            created_at = datetime.now()
        cur = self._db.conn.execute(
            "INSERT INTO documents (project_id, folder_id, name, url, created_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, folder_id, name, url, created_at.isoformat()),
        )
        self._db.conn.commit()
        return Document(
            id=cur.lastrowid,
            project_id=project_id,
            folder_id=folder_id,
            name=name,
            url=url,
            created_at=created_at,
        )

    def get(self, document_id: int) -> "Document | None":
        row = self._db.conn.execute(
            "SELECT id, project_id, folder_id, name, url, created_at FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

    def list_for_project(self, project_id: int) -> list["Document"]:
        rows = self._db.conn.execute(
            "SELECT id, project_id, folder_id, name, url, created_at FROM documents"
            " WHERE project_id = ? ORDER BY name COLLATE NOCASE",
            (project_id,),
        ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def rename(self, document_id: int, new_name: str) -> None:
        self._db.conn.execute("UPDATE documents SET name = ? WHERE id = ?", (new_name, document_id))
        self._db.conn.commit()

    def move(self, document_id: int, new_folder_id: int | None) -> None:
        self._db.conn.execute(
            "UPDATE documents SET folder_id = ? WHERE id = ?",
            (new_folder_id, document_id),
        )
        self._db.conn.commit()

    def delete(self, document_id: int) -> None:
        self._db.conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        self._db.conn.commit()

    @staticmethod
    def _row_to_document(row) -> "Document":
        return Document(
            id=row["id"],
            project_id=row["project_id"],
            folder_id=row["folder_id"],
            name=row["name"],
            url=row["url"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
