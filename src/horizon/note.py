import html as _html_mod
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from html.parser import HTMLParser

from horizon.database import Database
from horizon.tag import extract_tag_names as _extract_tag_names


class NoteFormat(Enum):
    Markdown = "markdown"  # CodeMirror + aperçu ; le corps est du markdown
    Html     = "html"      # CKEditor 5 ; le corps est du HTML, sans retour possible


@dataclass
class Note:
    id: int | None
    project_id: int | None
    title: str
    body: str
    dt: datetime  # stored as ISO-8601 TEXT in SQLite
    archived: bool = False
    folder_id: int | None = None
    format: NoteFormat = NoteFormat.Markdown


@dataclass
class NoteVersion:
    id: int | None
    note_id: int
    title: str
    body: str
    version_dt: datetime
    is_current: bool
    format: NoteFormat = NoteFormat.Markdown


_BLOCK_TAGS = frozenset({
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "blockquote", "figure", "figcaption", "table", "ul", "ol", "hr",
})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """Texte brut d'un corps HTML, pour l'index de recherche : sans lui, « strong » ou
    « figure » trouveraient toutes les notes WYSIWYG."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = _html_mod.unescape("".join(parser.parts))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _search_body(body: str, fmt: NoteFormat) -> str:
    return html_to_text(body) if fmt is NoteFormat.Html else body


_COLUMNS = "id, project_id, title, body, dt, archived, folder_id, format"


def _row_to_note(row) -> "Note":
    return Note(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        body=row["body"],
        dt=datetime.fromisoformat(row["dt"]),
        archived=bool(row["archived"]),
        folder_id=row["folder_id"],
        format=NoteFormat(row["format"]),
    )


class NoteRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int | None, title: str, body: str = "", dt: datetime | None = None, archived: bool = False, folder_id: int | None = None, format: NoteFormat = NoteFormat.Markdown) -> "Note":
        if dt is None:
            dt = datetime.now()
        cur = self._db.conn.execute(
            "INSERT INTO notes (project_id, title, body, dt, archived, folder_id, format) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, title, body, dt.isoformat(), int(archived), folder_id, format.value),
        )
        note_id = cur.lastrowid
        self._db.conn.execute(
            "INSERT INTO search_index(type, entity_id, title, body) VALUES ('note', ?, ?, ?)",
            (note_id, title, _search_body(body, format)),
        )
        from horizon.tag import TagRepository
        TagRepository(self._db).set_for_note(note_id, _extract_tag_names(body))
        self._db.conn.commit()
        return Note(id=note_id, project_id=project_id, title=title, body=body, dt=dt, archived=archived, folder_id=folder_id, format=format)

    def get(self, note_id: int) -> "Note | None":
        row = self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_note(row)

    def list_all_for_project(self, project_id: int) -> list["Note"]:
        rows = self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM notes"
            " WHERE project_id = ? ORDER BY dt DESC",
            (project_id,),
        ).fetchall()
        return [_row_to_note(row) for row in rows]

    def list_all(self, archived_only: bool = False) -> list["Note"]:
        rows = self._db.conn.execute(
            "SELECT notes.id, notes.project_id, notes.title, notes.body, notes.dt, notes.archived,"
            " notes.folder_id, notes.format"
            " FROM notes LEFT JOIN projects ON notes.project_id = projects.id"
            " WHERE notes.archived = ? AND (notes.project_id IS NULL OR projects.archived = 0)"
            " ORDER BY notes.dt DESC",
            (int(archived_only),),
        ).fetchall()
        return [_row_to_note(row) for row in rows]

    def list_for_tag(self, tag_id: int) -> list["Note"]:
        rows = self._db.conn.execute(
            "SELECT DISTINCT n.id, n.project_id, n.title, n.body, n.dt, n.archived, n.folder_id, n.format"
            " FROM notes n"
            " JOIN note_tags nt ON nt.note_id = n.id"
            " WHERE nt.tag_id = ? AND n.archived = 0"
            " ORDER BY n.dt DESC",
            (tag_id,),
        ).fetchall()
        return [_row_to_note(r) for r in rows]

    def update(self, note: "Note") -> None:
        # `format` n'est volontairement pas écrit : un objet Note périmé (panneau verrouillé,
        # client API) ne doit pas pouvoir ramener une note HTML en markdown. Le format ne
        # change que par convert_to_html().
        self._db.conn.execute(
            "UPDATE notes SET project_id = ?, title = ?, body = ?, dt = ?, archived = ?, folder_id = ? WHERE id = ?",
            (note.project_id, note.title, note.body, note.dt.isoformat(), int(note.archived), note.folder_id, note.id),
        )
        self._sync_index_and_tags(note.id, note.title, note.body)
        self._db.conn.commit()

    def convert_to_html(self, note: "Note", html_body: str) -> None:
        """Passe une note markdown en WYSIWYG. Irréversible : aucune méthode ne fait
        le chemin inverse."""
        self._db.conn.execute(
            "UPDATE notes SET body = ?, format = ? WHERE id = ?",
            (html_body, NoteFormat.Html.value, note.id),
        )
        note.body = html_body
        note.format = NoteFormat.Html
        self._sync_index_and_tags(note.id, note.title, note.body)
        self._db.conn.commit()

    def _sync_index_and_tags(self, note_id: int, title: str, body: str) -> None:
        # Le format est relu en base plutôt que pris sur l'objet, pour la même raison
        # que dans update().
        row = self._db.conn.execute("SELECT format FROM notes WHERE id = ?", (note_id,)).fetchone()
        fmt = NoteFormat(row["format"]) if row is not None else NoteFormat.Markdown
        self._db.conn.execute(
            "DELETE FROM search_index WHERE type = 'note' AND entity_id = ?", (note_id,)
        )
        self._db.conn.execute(
            "INSERT INTO search_index(type, entity_id, title, body) VALUES ('note', ?, ?, ?)",
            (note_id, title, _search_body(body, fmt)),
        )
        from horizon.tag import TagRepository
        TagRepository(self._db).set_for_note(note_id, _extract_tag_names(body))

    def find_referencing_image(self, image_id: int) -> list["Note"]:
        # Markdown : ![](horizon-image://12)  —  HTML : <img src="horizon-image://12">
        rows = self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM notes WHERE body LIKE ? OR body LIKE ?",
            (f"%horizon-image://{image_id})%", f'%horizon-image://{image_id}"%'),
        ).fetchall()
        return [_row_to_note(row) for row in rows]

    def delete(self, note_id: int) -> None:
        self._db.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._db.conn.execute(
            "DELETE FROM search_index WHERE type = 'note' AND entity_id = ?", (note_id,)
        )
        self._db.conn.commit()


def _row_to_version(row) -> "NoteVersion":
    return NoteVersion(id=row["id"], note_id=row["note_id"], title=row["title"],
                       body=row["body"], version_dt=datetime.fromisoformat(row["version_dt"]),
                       is_current=bool(row["is_current"]), format=NoteFormat(row["format"]))


class NoteVersionRepository:
    def __init__(self, db) -> None:
        self._db = db

    def create_version(self, note: "Note") -> "NoteVersion":
        now = datetime.now()
        self._db.conn.execute(
            "UPDATE note_versions SET is_current = 0 WHERE note_id = ?", (note.id,)
        )
        cur = self._db.conn.execute(
            "INSERT INTO note_versions (note_id, title, body, version_dt, is_current, format) VALUES (?, ?, ?, ?, 1, ?)",
            (note.id, note.title, note.body, now.isoformat(), note.format.value),
        )
        self._db.conn.commit()
        return NoteVersion(id=cur.lastrowid, note_id=note.id, title=note.title,
                           body=note.body, version_dt=now, is_current=True, format=note.format)

    def list_for_note(self, note_id: int) -> list["NoteVersion"]:
        rows = self._db.conn.execute(
            "SELECT id, note_id, title, body, version_dt, is_current, format FROM note_versions"
            # id départage deux versions du même instant (la conversion en crée deux).
            " WHERE note_id = ? ORDER BY version_dt DESC, id DESC",
            (note_id,),
        ).fetchall()
        return [_row_to_version(r) for r in rows]

    def get(self, version_id: int) -> "NoteVersion | None":
        row = self._db.conn.execute(
            "SELECT id, note_id, title, body, version_dt, is_current, format FROM note_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_version(row)
