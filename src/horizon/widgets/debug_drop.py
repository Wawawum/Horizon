from __future__ import annotations

import datetime
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_PREVIEW_BYTES = 512  # taille max de l'aperçu affiché pour chaque format brut
_MAX_TEXT = 2000      # troncature des accesseurs texte/html

# Formats Windows connus pour véhiculer de l'UTF-16LE : on tente un décodage
# lisible en plus de l'aperçu hexadécimal.
_UTF16_FORMATS = (
    'application/x-qt-windows-mime;value="UniformResourceLocatorW"',
    'application/x-qt-windows-mime;value="FileGroupDescriptorW"',
    'application/x-qt-windows-mime;value="FileNameW"',
    'application/x-qt-windows-mime;value="Shell IDList Array"',
    "text/x-moz-url",
)

_DROP_ACTION_NAMES = (
    (Qt.DropAction.CopyAction, "Copy"),
    (Qt.DropAction.MoveAction, "Move"),
    (Qt.DropAction.LinkAction, "Link"),
    (Qt.DropAction.IgnoreAction, "Ignore"),
    (Qt.DropAction.TargetMoveAction, "TargetMove"),
)


def _actions_to_str(actions) -> str:
    """Décrit un `Qt.DropAction` (ou une combinaison) de façon lisible."""
    names = [name for action, name in _DROP_ACTION_NAMES if actions & action]
    return " | ".join(names) if names else "None"


def _truncate(text: str, limit: int = _MAX_TEXT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (tronqué, {len(text)} caractères au total)"


def _decode_utf16(raw: bytes) -> str | None:
    """Décode un payload UTF-16LE terminé par un NUL, ou None si illisible."""
    try:
        text = raw.decode("utf-16-le", errors="strict")
    except UnicodeDecodeError:
        return None
    return text.rstrip("\x00")


def _preview_bytes(raw: bytes) -> str:
    """Aperçu d'un payload binaire : hexadécimal + rendu ASCII imprimable."""
    chunk = raw[:_PREVIEW_BYTES]
    hex_part = chunk.hex(" ")
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    suffix = "" if len(raw) <= _PREVIEW_BYTES else f"\n      … ({len(raw)} octets au total)"
    return f"      hex   : {hex_part}\n      ascii : {ascii_part}{suffix}"


def _describe_format(mime, fmt: str) -> list[str]:
    """Détail d'un format brut du QMimeData : taille, décodages, aperçu."""
    raw = bytes(mime.data(fmt).data())
    lines = [f"    · {fmt}  ({len(raw)} octets)"]
    if not raw:
        lines.append("      (payload vide — possible fichier « promis » non matérialisé)")
        return lines

    decoded_utf16 = _decode_utf16(raw) if fmt in _UTF16_FORMATS else None
    if decoded_utf16:
        lines.append(f"      utf-16-le : {_truncate(decoded_utf16)!r}")
    else:
        # Un payload UTF-16 se décode aussi en UTF-8 (un octet NUL sur deux) :
        # n'afficher la version UTF-8 que si l'UTF-16 n'a rien donné de lisible.
        try:
            as_utf8 = raw.decode("utf-8", errors="strict").rstrip("\x00")
        except UnicodeDecodeError:
            pass
        else:
            if as_utf8.strip():
                lines.append(f"      utf-8     : {_truncate(as_utf8)!r}")

    lines.append(_preview_bytes(raw))
    return lines


def _header(kind: str) -> list[str]:
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    return ["=" * 78, f"{kind} à {stamp}", "=" * 78, ""]


def _mime_sections(mime) -> list[str]:
    """Inspection d'un QMimeData : formats, accesseurs, payloads bruts.

    Commun au glisser-déposer et au presse-papiers, qui exposent la même API."""
    lines = ["── Formats annoncés ────────────────────────────────────────────────────"]
    formats = list(mime.formats())
    if formats:
        lines += [f"  {i + 1}. {fmt}" for i, fmt in enumerate(formats)]
    else:
        lines.append("  (aucun)")

    lines += ["", "── Accesseurs de haut niveau ───────────────────────────────────────────"]
    lines.append(f"  hasUrls  : {mime.hasUrls()}")
    if mime.hasUrls():
        for url in mime.urls():
            lines.append(f"    · toString()   : {url.toString()}")
            lines.append(f"      isLocalFile(): {url.isLocalFile()}")
            if url.isLocalFile():
                path = url.toLocalFile()
                exists = os.path.exists(path)
                size = os.path.getsize(path) if exists and os.path.isfile(path) else None
                lines.append(f"      toLocalFile(): {path}")
                lines.append(f"      existe       : {exists}" + (f"  ({size} octets)" if size is not None else ""))
    lines.append(f"  hasText  : {mime.hasText()}")
    if mime.hasText():
        lines.append(f"    · {_truncate(mime.text())!r}")
    lines.append(f"  hasHtml  : {mime.hasHtml()}")
    if mime.hasHtml():
        lines.append(f"    · {_truncate(mime.html())!r}")
    lines.append(f"  hasImage : {mime.hasImage()}")
    lines.append(f"  hasColor : {mime.hasColor()}")

    lines += ["", "── Payloads bruts ──────────────────────────────────────────────────────"]
    for fmt in formats:
        lines += _describe_format(mime, fmt)

    lines.append("")
    return lines


def _build_drop_report(event) -> str:
    """Rapport complet d'un événement de dépôt.

    Tout est extrait ici, de façon synchrone : le `QMimeData` d'un glisser-déposer
    externe n'est valide que pendant le traitement de l'événement."""
    lines = _header("DROP")
    lines += [
        "── Événement ───────────────────────────────────────────────────────────",
        f"  possibleActions : {_actions_to_str(event.possibleActions())}",
        f"  proposedAction  : {_actions_to_str(event.proposedAction())}",
        f"  source          : {event.source()!r}  "
        f"({'drag interne à Horizon' if event.source() is not None else 'drag externe'})",
        "",
    ]
    lines += _mime_sections(event.mimeData())
    return "\n".join(lines)


def _build_clipboard_report() -> str:
    """Rapport du contenu courant du presse-papiers (Ctrl+V)."""
    lines = _header("COLLAGE (Ctrl+V)")
    mime = QGuiApplication.clipboard().mimeData()
    if mime is None:
        lines.append("  (presse-papiers vide ou inaccessible)")
        lines.append("")
        return "\n".join(lines)
    lines += _mime_sections(mime)
    return "\n".join(lines)


class _DropZone(QFrame):
    """Zone de dépôt qui accepte *tout* et publie un rapport détaillé.

    Aucun filtrage sur les formats : le but est justement de découvrir ce que
    l'application source (Edge, l'Explorateur…) transmet réellement."""

    mime_inspected = Signal(str)  # emits the formatted report

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(160)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._hover = False
        self._refresh_style()

        label = QLabel(
            "Déposez ici un document\n\n"
            "depuis Edge (bibliothèque SharePoint, lien, barre d'adresse)\n"
            "ou depuis l'Explorateur Windows\n\n"
            "— ou collez le presse-papiers avec Ctrl+V —"
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(label)

    def _refresh_style(self) -> None:
        border = "#2aa9a0" if self._hover else "#9aa8bb"
        background = "rgba(42, 169, 160, 0.08)" if self._hover else "transparent"
        self.setStyleSheet(
            f"QFrame {{ border: 2px dashed {border}; background-color: {background}; }}"
        )

    def _set_hover(self, hover: bool) -> None:
        if self._hover != hover:
            self._hover = hover
            self._refresh_style()

    def dragEnterEvent(self, event) -> None:
        self._set_hover(True)
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_hover(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._set_hover(False)
        report = _build_drop_report(event)
        event.acceptProposedAction()
        self.mime_inspected.emit(report)


class DebugDropWidget(QWidget):
    """Page de diagnostic : inspecte le QMimeData reçu par glisser-déposer ou collage.

    Outil temporaire destiné à déterminer ce qu'Edge transmet lorsqu'on glisse un
    document d'une bibliothèque SharePoint (URL ? fichier ? fichier promis ?) et ce
    que produit son option « Copier le lien »."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        title = QLabel("Debug — glisser-déposer / presse-papiers")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        self._paste_btn = QPushButton("Coller (Ctrl+V)")
        self._paste_btn.clicked.connect(self._on_paste)
        self._copy_btn = QPushButton("Copier le rapport")
        self._copy_btn.clicked.connect(self._on_copy)
        self._clear_btn = QPushButton("Effacer")
        self._clear_btn.clicked.connect(self._on_clear)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._paste_btn)
        header.addWidget(self._copy_btn)
        header.addWidget(self._clear_btn)

        # QShortcut plutôt que keyPressEvent : le raccourci est traité avant le
        # widget qui a le focus, donc Ctrl+V fonctionne même depuis la zone de
        # rapport (un QPlainTextEdit en lecture seule ne consomme pas le collage,
        # mais on ne veut pas non plus dépendre du focus).
        self._paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        self._paste_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._paste_shortcut.activated.connect(self._on_paste)

        self._drop_zone = _DropZone()
        self._drop_zone.mime_inspected.connect(self._on_mime_inspected)

        self._report = QPlainTextEdit()
        self._report.setReadOnly(True)
        self._report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._report.setFont(QFont("Consolas", 9))
        self._report.setPlaceholderText("Le contenu du presse-papiers de glisser-déposer s'affichera ici.")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._drop_zone)
        layout.addWidget(self._report, stretch=1)

    def load(self) -> None:
        """Rien à recharger, mais prendre le focus pour que Ctrl+V soit actif
        dès l'affichage de la page (le rapport survit à la navigation)."""
        self.setFocus()

    def _on_paste(self) -> None:
        self._append(_build_clipboard_report())

    def _on_mime_inspected(self, report: str) -> None:
        self._append(report)

    def _append(self, report: str) -> None:
        existing = self._report.toPlainText()
        self._report.setPlainText(f"{report}\n{existing}" if existing else report)
        self._report.verticalScrollBar().setValue(0)

    def _on_copy(self) -> None:
        QGuiApplication.clipboard().setText(self._report.toPlainText())

    def _on_clear(self) -> None:
        self._report.clear()
