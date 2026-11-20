"""Pièces jointes des notes WYSIWYG : contenu archivé dans la base (BLOB).

Une note référence une pièce jointe par son id (`horizon-attachment://<id>`), comme les
images (`horizon-image://`) : le corps HTML ne contient jamais les octets. Le fichier
d'origine peut ensuite disparaître, être déplacé ou modifié — la note garde la copie
prise au moment du dépôt.
"""

import mimetypes
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from horizon.database import Database

#: Taille maximale d'un fichier archivé. Au-delà, la base grossirait de façon
#: déraisonnable pour un outil de prise de notes (et chaque sauvegarde avec elle).
MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024

# Caractères refusés dans un nom de fichier Windows.
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def guess_mime_type(name: str) -> str:
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


#: Pastille d'une pièce jointe (aperçu markdown) : couleur par famille d'extension. Même
#: palette que BADGE_COLORS dans web/src/wysiwyg.js (cartes des notes WYSIWYG).
_BADGE_COLORS = (
    (frozenset({"pdf"}), "#d93025"),
    (frozenset({"doc", "docx", "dot", "dotx", "rtf", "odt"}), "#2b579a"),
    (frozenset({"xls", "xlsx", "xlsm", "csv", "ods"}), "#217346"),
    (frozenset({"ppt", "pptx", "pot", "potx", "odp"}), "#d24726"),
    (frozenset({"msg", "eml"}), "#0078d4"),
    (frozenset({"zip", "7z", "rar", "gz", "tar"}), "#8a6d3b"),
    (frozenset({"vsd", "vsdx"}), "#3955a3"),
    (frozenset({"txt", "md", "log", "json", "xml", "yml", "yaml"}), "#5f6b7a"),
)
_DEFAULT_BADGE_COLOR = "#5f6b7a"


def attachment_badge(name: str) -> tuple[str, str]:
    """(libellé, couleur) de la pastille : l'extension en majuscules, 4 caractères au plus."""
    ext = Path(name).suffix.lower().lstrip(".")
    color = next((c for exts, c in _BADGE_COLORS if ext in exts), _DEFAULT_BADGE_COLOR)
    return (ext.upper()[:4] or "?", color)


def format_size(size: int) -> str:
    if size <= 0:
        return ""
    value = float(size)
    for unit in ("octets", "Ko", "Mo", "Go"):
        if value < 1024 or unit == "Go":
            break
        value /= 1024
    if unit == "octets":
        return f"{size} octets"
    return (f"{value:.1f}" if value < 10 else f"{value:.0f}").replace(".", ",") + f" {unit}"


def safe_file_name(name: str, fallback: str = "piece-jointe") -> str:
    """Nom utilisable sur le disque : sans séparateur ni caractère interdit."""
    cleaned = _UNSAFE_NAME_RE.sub("_", name).strip(" .")
    return cleaned[:180] or fallback


@dataclass
class Attachment:
    id: int | None
    note_id: int | None  # note où le contenu a été déposé ; None si elle a été supprimée
    name: str
    mime_type: str
    size: int
    created_at: datetime


class AttachmentRepository:
    """Les octets ne sont lus qu'à la demande (`get_data`) : `get` reste léger."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        name: str,
        data: bytes,
        note_id: int | None = None,
        mime_type: str | None = None,
    ) -> Attachment:
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError(
                f"« {name} » dépasse la taille maximale "
                f"({MAX_ATTACHMENT_BYTES // (1024 * 1024)} Mo)."
            )
        created_at = datetime.now()
        mime_type = mime_type or guess_mime_type(name)
        cur = self._db.conn.execute(
            "INSERT INTO attachments (note_id, name, mime_type, size, data, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (note_id, name, mime_type, len(data), data, created_at.isoformat()),
        )
        self._db.conn.commit()
        return Attachment(
            id=cur.lastrowid,
            note_id=note_id,
            name=name,
            mime_type=mime_type,
            size=len(data),
            created_at=created_at,
        )

    def get(self, attachment_id: int) -> Attachment | None:
        row = self._db.conn.execute(
            "SELECT id, note_id, name, mime_type, size, created_at FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
        return self._row_to_attachment(row) if row is not None else None

    def get_data(self, attachment_id: int) -> bytes | None:
        row = self._db.conn.execute(
            "SELECT data FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
        return bytes(row["data"]) if row is not None else None

    def delete(self, attachment_id: int) -> None:
        self._db.conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        self._db.conn.commit()

    def export_to_temp(self, attachment_id: int) -> Path | None:
        """Écrit la pièce jointe dans le dossier temporaire, sous son nom d'origine, pour
        l'ouvrir avec l'application associée. Une modification de cette copie ne revient
        pas dans Horizon : l'archive est la référence."""
        attachment = self.get(attachment_id)
        data = self.get_data(attachment_id)
        if attachment is None or data is None:
            return None
        folder = Path(tempfile.gettempdir()) / "Horizon" / "attachments" / str(attachment_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_file_name(attachment.name)
        path.write_bytes(data)
        return path

    def export_to(self, attachment_id: int, path: Path) -> bool:
        data = self.get_data(attachment_id)
        if data is None:
            return False
        path.write_bytes(data)
        return True

    @staticmethod
    def _row_to_attachment(row) -> Attachment:
        return Attachment(
            id=row["id"],
            note_id=row["note_id"],
            name=row["name"],
            mime_type=row["mime_type"],
            size=row["size"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
