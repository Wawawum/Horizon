"""Contenu déposé dans une note : fichiers, courriels Outlook, URLs.

Deux temps, imposés par le glisser-déposer Windows :

1. `parse_drop(mime)` lit le `QMimeData` **pendant** l'événement de dépôt — il n'est
   valide que jusque-là — et le réduit à des objets Python simples.
2. `DropImporter.import_items()` archive ensuite le contenu et décrit les blocs à
   insérer. Il tourne *après* le retour du dépôt : Outlook est encore dans sa boucle
   DoDragDrop tant que le dépôt n'est pas terminé, et l'interroger par COM à ce
   moment-là peut bloquer les deux applications.

Chaque dépôt est soit **copié** dans Horizon (`DropMode.COPY` : fichier archivé, URL
téléchargée), soit **lié** à son original (`DropMode.LINK` : lien file://, lien vers le
courriel dans Outlook, lien web).

Les blocs sont des dictionnaires prêts pour le plugin `HorizonAttachment` de
`web/src/wysiwyg.js` (clés en camelCase), ou pour `blocks_to_markdown`.
"""

import email
import email.policy
import html as _html
import mimetypes
import re
import ssl
import struct
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import certifi
import httpx
from PySide6.QtCore import QUrl

from horizon.attachment import MAX_ATTACHMENT_BYTES, AttachmentRepository, guess_mime_type, safe_file_name
from horizon.attachment_preview import pdf_page_count
from horizon.document import extract_document_link
from horizon.image import ImageRepository
from horizon.note import html_to_text

_WIN_MIME = 'application/x-qt-windows-mime;value="{}"'
_FILE_GROUP_DESCRIPTOR_W = _WIN_MIME.format("FileGroupDescriptorW")
_FILE_CONTENTS = _WIN_MIME.format("FileContents")
_OUTLOOK_MESSAGES = _WIN_MIME.format("RenPrivateMessages")
_MOZ_URL = "text/x-moz-url"

# Les formats d'image que la note sait afficher (voir webeditor._image_mime) : déposés,
# ils deviennent des images de la note et non des pièces jointes.
_INLINE_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})

_EXCERPT_MAX = 2000  # caractères du corps d'un courriel gardés dans la note
_TITLE_MAX = 300
_TITLE_FETCH_BYTES = 256 * 1024
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

_OL_EXPLORER = 34  # OlObjectClass.olExplorer
_OL_INSPECTOR = 35  # OlObjectClass.olInspector
_OL_MSG_UNICODE = 9  # OlSaveAsType.olMSGUnicode


#: Schéma des liens vers un élément d'Outlook : outlook:<EntryID>?store=<StoreID>.
OUTLOOK_SCHEME = "outlook:"


class DropMode(Enum):
    COPY = "copy"  # une copie du document est archivée dans Horizon
    LINK = "link"  # un lien vers le document d'origine


class DropImportError(Exception):
    """Contenu déposé qui ne peut pas être archivé ; le message s'adresse à l'utilisateur."""


# ── Ce que le dépôt contenait ─────────────────────────────────────────────────


@dataclass
class DroppedFile:
    path: Path


@dataclass
class DroppedLink:
    url: str
    title: str  # vide : à déduire de l'URL, puis à chercher sur la page


@dataclass
class DroppedOutlookItems:
    """Éléments « virtuels » d'Outlook : courriels (`.msg`) ou pièces jointes d'un
    courriel. Ils n'existent pas sur le disque ; seuls leurs noms sont annoncés."""

    names: list[str]
    contents: bytes = b""  # FileContents, quand Qt a pu le lire (un seul fichier)


DroppedItem = DroppedFile | DroppedLink | DroppedOutlookItems


def _utf16(raw: bytes) -> str:
    return raw.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]


def _file_group_names(raw: bytes) -> list[str]:
    """Noms d'un FILEGROUPDESCRIPTORW : un compteur, puis des FILEDESCRIPTORW de 592
    octets dont le nom (260 WCHAR) commence à l'octet 72."""
    if len(raw) < 4:
        return []
    (count,) = struct.unpack_from("<I", raw, 0)
    names = []
    for i in range(min(count, 256)):
        start = 4 + i * 592 + 72
        chunk = raw[start:start + 520]
        if len(chunk) < 2:
            break
        name = _utf16(chunk).strip()
        if name:
            names.append(name)
    return names


def _is_web_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def parse_drop(mime, read_contents: bool = True) -> list[DroppedItem] | None:
    """Ce que la note doit archiver, ou None quand le dépôt ne la concerne pas — texte
    ou HTML glissé depuis une page, image d'une page web : l'éditeur les colle alors
    lui-même, comme avant."""
    if mime.hasFormat(_FILE_GROUP_DESCRIPTOR_W) and not mime.hasUrls():
        names = _file_group_names(bytes(mime.data(_FILE_GROUP_DESCRIPTOR_W).data()))
        if names:
            contents = b""
            if read_contents and len(names) == 1 and mime.hasFormat(_FILE_CONTENTS):
                contents = bytes(mime.data(_FILE_CONTENTS).data())
            return [DroppedOutlookItems(names, contents)]

    if mime.hasUrls():
        urls = mime.urls()
        files = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
        if files:
            return [DroppedFile(p) for p in files]
        web = [u.toString() for u in urls if _is_web_url(u.toString())]
        if web:
            # Une image glissée depuis une page : l'éditeur la gère (balise <img>).
            html = mime.html() if mime.hasHtml() else ""
            if "<img" in html.lower() and "<a" not in html.lower():
                return None
            return [DroppedLink(url, _link_title(mime, url)) for url in web]

    # SharePoint et certaines pages ne publient le lien qu'en HTML ou en texte.
    if mime.hasText() and not mime.hasHtml():
        text = mime.text().strip()
        if _is_web_url(text) and len(text.split()) == 1:
            return [DroppedLink(text, "")]
    return None


def _link_title(mime, url: str) -> str:
    """Titre fourni par le navigateur : text/x-moz-url (« url\ntitre ») ou le texte de
    l'ancre HTML qui pointe vers l'URL. Vide s'il n'y en a pas ou s'il répète l'URL."""
    title = ""
    if mime.hasFormat(_MOZ_URL):
        lines = _utf16(bytes(mime.data(_MOZ_URL).data())).splitlines()
        if len(lines) >= 2 and lines[0].strip() == url:
            title = lines[1].strip()
    if not title and mime.hasHtml():
        found = extract_document_link(mime.html(), None)
        if found is not None and found[1] == url:
            title = found[0]
    return "" if title == url else title


# ── Archivage ─────────────────────────────────────────────────────────────────


def link_unavailable_reason(items: list[DroppedItem]) -> str | None:
    """Pourquoi ce dépôt ne peut pas être lié à son original, ou None s'il le peut. Une
    pièce jointe glissée depuis un courriel n'existe que dans ce courriel."""
    for item in items:
        if isinstance(item, DroppedOutlookItems) and any(not n.lower().endswith(".msg") for n in item.names):
            return "une pièce jointe de courriel n'existe que dans Outlook"
    return None


@dataclass
class ImportResult:
    blocks: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    titles_to_fetch: list[tuple[str, str]] = field(default_factory=list)  # (url, titre provisoire)
    downloads: list[str] = field(default_factory=list)  # URLs à copier : téléchargées hors du thread UI


def markdown_link(text: str, url: str) -> str:
    """`[texte](url)` ; crochets du texte échappés, URL entre chevrons si elle contient
    des espaces ou des parenthèses (CommonMark)."""
    label = text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")
    if any(c in url for c in " ()<>"):
        url = "<" + url.replace("<", "%3C").replace(">", "%3E") + ">"
    return f"[{label}]({url})"


def blocks_to_markdown(blocks: list[dict]) -> str:
    """Les blocs d'un dépôt en markdown, un par ligne. Une pièce jointe devient un lien
    `horizon-attachment://<id>`, que l'aperçu affiche comme une icône du fichier."""
    lines = []
    for block in blocks:
        kind = block["kind"]
        if kind == "image":
            lines.append(f"![](horizon-image://{block['imageId']})")
        elif kind == "link":
            lines.append(markdown_link(block["title"], block["href"]))
        else:
            label = block.get("subject") if kind == "email" else block["name"]
            lines.append(markdown_link(label or block["name"], f"horizon-attachment://{block['attachmentId']}"))
    # Une ligne vide entre deux blocs : en markdown, des lignes consécutives forment un
    # seul paragraphe.
    return "\n\n".join(lines)


def host_title(url: str) -> str:
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")


def _excerpt(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > _EXCERPT_MAX:
        text = text[:_EXCERPT_MAX].rstrip() + " …"
    return text


def _format_date(value) -> str:
    if value is None:
        return ""
    try:
        return value.strftime("%d/%m/%Y %H:%M")
    except (AttributeError, ValueError):
        return str(value)


class DropImporter:
    def __init__(self, attachment_repo: AttachmentRepository, image_repo: ImageRepository | None) -> None:
        self._attachment_repo = attachment_repo
        self._image_repo = image_repo

    def import_items(
        self, items: list[DroppedItem], note_id: int | None, mode: DropMode = DropMode.COPY,
    ) -> ImportResult:
        result = ImportResult()
        link = mode is DropMode.LINK
        for item in items:
            try:
                if isinstance(item, DroppedFile):
                    result.blocks.append(
                        _file_link_block(item.path) if link else self._import_file(item.path, note_id))
                elif isinstance(item, DroppedLink):
                    if not link:
                        result.downloads.append(item.url)
                        continue
                    title = item.title.strip()[:_TITLE_MAX]
                    if not title:
                        title = host_title(item.url)
                        result.titles_to_fetch.append((item.url, title))
                    result.blocks.append({"kind": "link", "href": item.url, "title": title})
                elif link:
                    result.blocks.extend(outlook_item_links(item.names))
                else:
                    result.blocks.extend(self._import_outlook(item, note_id))
            except DropImportError as exc:
                result.errors.append(str(exc))
            except Exception as exc:  # un élément illisible ne doit pas perdre les autres
                print(f"Horizon: drop import failed: {exc!r}", file=sys.stderr)
                result.errors.append(f"Import impossible : {exc}")
        return result

    def import_bytes(self, name: str, data: bytes, note_id: int | None) -> dict:
        """Archive un contenu obtenu ailleurs (une URL téléchargée) et décrit son bloc."""
        return self._block_for_bytes(name, data, note_id)

    # ── Fichiers ──────────────────────────────────────────────────────────
    def _import_file(self, path: Path, note_id: int | None) -> dict:
        if path.is_dir():
            raise DropImportError(f"« {path.name} » est un dossier : déposez les fichiers qu'il contient.")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise DropImportError(f"Lecture de « {path.name} » impossible : {exc.strerror or exc}") from exc
        return self._block_for_bytes(path.name, data, note_id, source=path)

    def _block_for_bytes(self, name: str, data: bytes, note_id: int | None, source: Path | None = None) -> dict:
        suffix = Path(name).suffix.lower()
        if suffix in _INLINE_IMAGE_SUFFIXES and self._image_repo is not None:
            return {"kind": "image", "imageId": self._image_repo.create(data)}

        if suffix == ".eml":
            meta = _eml_metadata(data)
            return self._email_block(name, data, note_id, meta)
        if suffix == ".msg" and source is not None:
            meta = _msg_metadata_via_outlook(source)
            if meta is not None:
                return self._email_block(name, data, note_id, meta)

        attachment = self._create(name, data, note_id)
        pages = pdf_page_count(data) if suffix == ".pdf" or data[:5] == b"%PDF-" else 0
        return {
            "kind": "file",
            "attachmentId": attachment.id,
            "name": attachment.name,
            "size": attachment.size,
            "mime": attachment.mime_type,
            "pages": pages,
            "display": "preview" if pages > 0 else "icon",
        }

    def _create(self, name: str, data: bytes, note_id: int | None):
        try:
            return self._attachment_repo.create(name, data, note_id=note_id, mime_type=guess_mime_type(name))
        except ValueError as exc:
            raise DropImportError(str(exc)) from exc

    def _email_block(self, name: str, data: bytes, note_id: int | None, meta: dict) -> dict:
        attachment = self._create(name, data, note_id)
        return {
            "kind": "email",
            "attachmentId": attachment.id,
            "name": attachment.name,
            "size": attachment.size,
            "mime": attachment.mime_type,
            "subject": meta.get("subject") or Path(name).stem,
            "sender": meta.get("sender", ""),
            "date": meta.get("date", ""),
            "excerpt": _excerpt(meta.get("body", "")),
            "display": "preview",
        }

    # ── Outlook ───────────────────────────────────────────────────────────
    def _import_outlook(self, item: DroppedOutlookItems, note_id: int | None) -> list[dict]:
        # Une pièce jointe seule dont Qt a pu lire le contenu : pas besoin d'Outlook.
        if item.contents and len(item.names) == 1 and not item.names[0].lower().endswith(".msg"):
            return [self._block_for_bytes(item.names[0], item.contents, note_id)]

        blocks = []
        for exported in export_outlook_items(item.names):
            if exported.meta is not None:
                blocks.append(self._email_block(exported.name, exported.data, note_id, exported.meta))
            else:
                blocks.append(self._block_for_bytes(exported.name, exported.data, note_id))
        if not blocks:
            raise DropImportError(
                "Outlook n'a renvoyé aucun élément : sélectionnez le courriel dans Outlook puis glissez-le à nouveau."
            )
        return blocks


# ── Liens vers l'original ─────────────────────────────────────────────────────


def _file_link_block(path: Path) -> dict:
    """Lien vers un fichier ou un dossier tel qu'il est sur le disque (ou le partage) :
    rien n'est copié, la note suit l'original — et le perd s'il est déplacé."""
    return {
        "kind": "link",
        "href": QUrl.fromLocalFile(str(path)).toString(QUrl.ComponentFormattingOption.FullyEncoded),
        "title": path.name or str(path),
        "name": path.name,
        "mime": "inode/directory" if path.is_dir() else guess_mime_type(path.name),
    }


def outlook_item_links(names: list[str]) -> list[dict]:
    """Liens vers les courriels sélectionnés dans Outlook (outlook:<EntryID>?store=…)."""
    outlook = _outlook_application()
    window = outlook.ActiveWindow()
    if window is None or window.Class not in (_OL_EXPLORER, _OL_INSPECTOR):
        raise DropImportError("Aucune fenêtre Outlook active : glissez le courriel depuis Outlook.")
    blocks = []
    for item in _selected_items(window):
        meta = _item_metadata(item)
        entry_id = getattr(item, "EntryID", "")
        if meta is None or not entry_id:
            continue
        try:
            store_id = item.Parent.StoreID
        except Exception:
            store_id = ""
        href = OUTLOOK_SCHEME + entry_id + (f"?store={store_id}" if store_id else "")
        subject = meta["subject"] or "Courriel"
        blocks.append({
            "kind": "link",
            "href": href,
            "title": subject,
            "name": safe_file_name(subject) + ".msg",
            "sender": meta["sender"],
            "date": meta["date"],
        })
    if not blocks:
        raise DropImportError(
            "Outlook n'a renvoyé aucun courriel : sélectionnez-le dans Outlook puis glissez-le à nouveau."
        )
    return blocks


def open_outlook_item(href: str) -> None:
    """Ouvre dans Outlook le courriel d'un lien outlook:<EntryID>?store=<StoreID>. Lancé
    au besoin : c'est un clic explicite, pas un dépôt."""
    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except ImportError as exc:
        raise DropImportError("pywin32 n'est pas installé : ouverture Outlook indisponible.") from exc
    raw = href.removeprefix(OUTLOOK_SCHEME)
    entry_id, _, query = raw.partition("?")
    store_id = parse_qs(query).get("store", [""])[0]
    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        session = outlook.Session
        item = session.GetItemFromID(entry_id, store_id) if store_id else session.GetItemFromID(entry_id)
        item.Display()
    except pywintypes.com_error as exc:
        raise DropImportError(
            "Courriel introuvable dans Outlook : il a peut-être été supprimé ou déplacé vers une autre boîte."
        ) from exc


# ── Copie d'une URL ───────────────────────────────────────────────────────────


def _content_disposition_name(header: str) -> str:
    if not header:
        return ""
    message = Message()
    message["content-disposition"] = header
    name = message.get_filename() or ""
    return name.strip().strip('"')


def download_url(url: str, timeout: float = 30.0) -> tuple[str, bytes]:
    """Télécharge le document d'une URL : (nom de fichier, contenu). DropImportError si
    le site refuse, demande une connexion ou dépasse la taille maximale.

    Appelé hors du thread de l'interface ; n'écrit rien en base."""
    context = ssl.create_default_context(cafile=certifi.where())
    path_name = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    try:
        with httpx.Client(
            verify=context, timeout=timeout, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Horizon"},
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise DropImportError(f"Téléchargement refusé par le site ({response.status_code}) : {url}")
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                # Un lien vers un document (SharePoint, OneDrive…) qui répond par une page
                # HTML : c'est la page de connexion, pas le document.
                if content_type == "text/html" and Path(path_name).suffix.lower() not in ("", ".html", ".htm", ".aspx", ".php"):
                    raise DropImportError(
                        "Le site demande une connexion : copie impossible, choisissez « Créer un lien »."
                    )
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_ATTACHMENT_BYTES:
                        raise DropImportError(
                            f"Document trop volumineux (plus de {MAX_ATTACHMENT_BYTES // (1024 * 1024)} Mo) : {url}")
                    chunks.append(chunk)
                name = _content_disposition_name(response.headers.get("content-disposition", ""))
    except (httpx.HTTPError, ssl.SSLError, OSError) as exc:
        raise DropImportError(f"Téléchargement impossible ({exc.__class__.__name__}) : {url}") from exc

    name = safe_file_name(name or path_name or host_title(url))
    # « python.org » n'a pas d'extension .org : seul le type annoncé fait foi quand le
    # nom n'en a pas une reconnue.
    if content_type == "text/html":
        if Path(name).suffix.lower() not in (".html", ".htm"):
            name += ".html"
    elif mimetypes.guess_type(name)[0] is None:
        name += mimetypes.guess_extension(content_type or "") or ""
    return name, b"".join(chunks)


# ── Courriels ─────────────────────────────────────────────────────────────────


def _eml_metadata(data: bytes) -> dict:
    message = email.message_from_bytes(data, policy=email.policy.default)
    body = ""
    part = message.get_body(preferencelist=("plain", "html"))
    if part is not None:
        try:
            content = part.get_content()
        except (LookupError, ValueError):
            content = ""
        body = html_to_text(content) if part.get_content_type() == "text/html" else content
    date = ""
    if message["date"] is not None:
        try:
            date = _format_date(message["date"].datetime.astimezone())
        except (AttributeError, ValueError, TypeError):
            date = str(message["date"])
    return {
        "subject": str(message["subject"] or ""),
        "sender": str(message["from"] or ""),
        "date": date,
        "body": body,
    }


def _outlook_application():
    """Outlook *classique* déjà ouvert, ou DropImportError. Jamais lancé : un dépôt ne
    doit pas démarrer Outlook (et le nouvel Outlook n'a pas d'interface COM)."""
    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except ImportError as exc:
        raise DropImportError("pywin32 n'est pas installé : import Outlook indisponible.") from exc
    pythoncom.CoInitialize()
    try:
        return win32com.client.GetActiveObject("Outlook.Application")
    except pywintypes.com_error as exc:
        raise DropImportError(
            "Outlook classique n'est pas accessible : il doit être ouvert pour importer un courriel."
        ) from exc


def _item_metadata(item) -> dict | None:
    """Métadonnées d'un élément Outlook (courriel, invitation…), None s'il n'en a pas."""
    subject = getattr(item, "Subject", None)
    if subject is None:
        return None
    sender = getattr(item, "SenderName", "") or ""
    address = getattr(item, "SenderEmailAddress", "") or ""
    if "@" in address and address.lower() not in sender.lower():
        sender = f"{sender} <{address}>" if sender else address
    date = None
    for attribute in ("ReceivedTime", "SentOn", "Start", "CreationTime"):
        date = getattr(item, attribute, None)
        if date is not None:
            break
    return {
        "subject": str(subject),
        "sender": sender,
        "date": _format_date(date),
        "body": str(getattr(item, "Body", "") or ""),
    }


def _msg_metadata_via_outlook(path: Path) -> dict | None:
    """Métadonnées d'un .msg sur le disque, si Outlook est ouvert ; sinon le fichier
    reste une pièce jointe ordinaire."""
    try:
        outlook = _outlook_application()
        item = outlook.Session.OpenSharedItem(str(path))
    except Exception:
        return None
    try:
        return _item_metadata(item)
    finally:
        try:
            item.Close(1)  # olDiscard
        except Exception:
            pass


@dataclass
class OutlookExport:
    name: str
    data: bytes
    meta: dict | None  # None : pièce jointe d'un courriel, pas un courriel


def _selected_items(window) -> list:
    if window.Class == _OL_INSPECTOR:
        return [window.CurrentItem]
    selection = window.Selection
    return [selection.Item(i) for i in range(1, selection.Count + 1)]


def _selected_attachments(window) -> list:
    try:
        selection = window.AttachmentSelection
    except Exception:
        return []
    return [selection.Item(i) for i in range(1, selection.Count + 1)]


def export_outlook_items(names: list[str]) -> list[OutlookExport]:
    """Récupère par COM les éléments glissés depuis Outlook.

    Le glisser d'Outlook n'annonce que des noms (« Objet du courriel.msg »,
    « Rapport.pdf ») : leur contenu est lu dans la sélection de la fenêtre active
    d'Outlook, qui est forcément celle d'où vient le glisser."""
    outlook = _outlook_application()
    window = outlook.ActiveWindow()
    if window is None or window.Class not in (_OL_EXPLORER, _OL_INSPECTOR):
        raise DropImportError("Aucune fenêtre Outlook active : glissez le courriel depuis Outlook.")

    wanted_files = {n.lower() for n in names if not n.lower().endswith(".msg")}
    folder = Path(tempfile.mkdtemp(prefix="horizon-outlook-"))
    exports: list[OutlookExport] = []
    try:
        if wanted_files:
            for attachment in _selected_attachments(window):
                file_name = str(attachment.FileName)
                if file_name.lower() not in wanted_files:
                    continue
                path = folder / safe_file_name(file_name)
                attachment.SaveAsFile(str(path))
                exports.append(OutlookExport(file_name, path.read_bytes(), None))
        if len(exports) < len(names):
            for item in _selected_items(window):
                meta = _item_metadata(item)
                if meta is None:
                    continue
                name = safe_file_name(meta["subject"] or "Courriel") + ".msg"
                path = folder / f"{len(exports)}-{name}"
                item.SaveAs(str(path), _OL_MSG_UNICODE)
                exports.append(OutlookExport(name, path.read_bytes(), meta))
    finally:
        for child in folder.iterdir():
            child.unlink(missing_ok=True)
        folder.rmdir()
    return exports


# ── Titre d'une page ──────────────────────────────────────────────────────────


def fetch_page_title(url: str, timeout: float = 6.0) -> str | None:
    """`<title>` d'une page web, ou None (hors ligne, page protégée, pas de titre).

    Appelé hors du thread de l'interface : seule la page déposée est interrogée."""
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with httpx.Client(
            verify=context, timeout=timeout, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Horizon"},
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    return None
                if "html" not in response.headers.get("content-type", "html"):
                    return None
                raw = b""
                for chunk in response.iter_bytes():
                    raw += chunk
                    if len(raw) >= _TITLE_FETCH_BYTES or b"</title>" in raw.lower():
                        break
                encoding = response.encoding or "utf-8"
    except (httpx.HTTPError, ssl.SSLError, OSError, ValueError):
        return None
    match = _TITLE_RE.search(raw.decode(encoding, errors="replace"))
    if match is None:
        return None
    title = " ".join(_html.unescape(match.group(1)).split())
    return title[:_TITLE_MAX] or None

