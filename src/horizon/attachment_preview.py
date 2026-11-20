"""Aperçu des pièces jointes PDF : nombre de pages et rendu d'une page en PNG.

Le rendu est fait à la demande (schéma horizon-attachment://<id>?page=<n>) plutôt que
stocké : la base ne garde que le fichier d'origine, et l'aperçu suit le thème et la
taille d'affichage sans migration. QtPdf charge un document en mémoire de façon
synchrone ; le dernier document ouvert est gardé, car une note affiche plusieurs pages
du même PDF à la suite.
"""

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPdf import QPdfDocument

#: Nombre de pages montrées dans l'aperçu d'une note (comme l'« impression » de OneNote,
#: mais bornée : un PDF de 200 pages ne doit pas occuper la note entière).
PREVIEW_MAX_PAGES = 5

#: Largeur de rendu, en pixels : assez pour rester net en pleine largeur de note.
PREVIEW_WIDTH = 1100

_cache: tuple[int, QPdfDocument, QBuffer] | None = None


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def _open(data: bytes) -> tuple[QPdfDocument, QBuffer] | None:
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    doc = QPdfDocument()
    doc.load(buffer)
    if doc.status() != QPdfDocument.Status.Ready:
        return None
    return doc, buffer  # le buffer doit vivre aussi longtemps que le document


def pdf_page_count(data: bytes) -> int:
    """Nombre de pages, ou 0 si le PDF est illisible (chiffré, corrompu)."""
    opened = _open(data) if is_pdf(data) else None
    return opened[0].pageCount() if opened is not None else 0


def render_pdf_page(attachment_id: int, data: bytes, page: int, width: int = PREVIEW_WIDTH) -> bytes | None:
    """PNG de la page `page` (à partir de 0), ou None si elle n'existe pas."""
    global _cache
    if _cache is None or _cache[0] != attachment_id:
        opened = _open(data) if is_pdf(data) else None
        if opened is None:
            return None
        _cache = (attachment_id, *opened)
    doc = _cache[1]
    if not 0 <= page < doc.pageCount():
        return None
    points = doc.pagePointSize(page)
    if points.width() <= 0:
        return None
    height = round(width * points.height() / points.width())
    image = doc.render(page, QSize(width, height))
    if image.isNull():
        return None
    # Les PDF sans fond explicite sont transparents : sur un thème sombre le texte noir
    # deviendrait illisible. Le papier est blanc.
    flattened = QImage(image.size(), QImage.Format.Format_RGB32)
    flattened.fill(0xFFFFFF)
    painter = QPainter(flattened)
    painter.drawImage(0, 0, image)
    painter.end()
    out = QBuffer()
    out.open(QIODevice.OpenModeFlag.WriteOnly)
    flattened.save(out, "PNG")
    return bytes(out.data())
