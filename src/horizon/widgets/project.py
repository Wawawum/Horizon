from pathlib import Path

from PySide6.QtCore import Qt, Signal, QByteArray, QMimeData, QPoint, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QBrush, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from horizon import theme as _theme
from horizon.deliverable import DeliverableRepository
from horizon.deliverable_template import DeliverableTemplateRepository
from horizon.dialogs import AlertDialog, ConfirmDialog, NewFolderDialog, NewProjectDialog, NewTaskDialog, TaskDetailDialog
from horizon.document import URL_SCHEMES, DocumentRepository, extract_document_link
from horizon.folder import Folder, FolderRepository
from horizon.note import NoteRepository
from horizon.project import ProjectRepository
from horizon.task import SubtaskRepository, TaskBucket, TaskPriority, TaskRepository, TaskState
from horizon.widgets.deliverables import ProjectDeliverablesPanel
from PySide6.QtCore import QEvent
from PySide6.QtGui import QTextCursor


_KANBAN_MIME        = "application/x-horizon-task-id"
_PROJECT_MIME       = "application/x-horizon-project-id"
_PRIORITY_ROLE      = Qt.ItemDataRole.UserRole + 1
_PROJECT_ROLE       = Qt.ItemDataRole.UserRole + 2
_SUBTASKS_ROLE      = Qt.ItemDataRole.UserRole + 3
_CHECK_SVG          = ":/icons/check_black.svg"
_PLUS_ICON: QIcon | None = None
_PLUS_ICON_SIZE     = QSize(12, 12)
_PLUS_ICON_WHITE: QIcon | None = None
_FOLDER_ICON: QIcon | None = None
_FOLDER_ICON_SIZE   = QSize(14, 14)
_DOCUMENT_ICON: QIcon | None = None

def _plus_icon() -> QIcon:
    global _PLUS_ICON
    if _PLUS_ICON is None:
        _PLUS_ICON = _theme.make_icon(":/icons/plus_cyan.svg", _PLUS_ICON_SIZE)
    return _PLUS_ICON

def _plus_icon_white() -> QIcon:
    global _PLUS_ICON_WHITE
    if _PLUS_ICON_WHITE is None:
        _PLUS_ICON_WHITE = QIcon(str(_RESOURCES_DIR / "plus_white.svg"))
    return _PLUS_ICON_WHITE

def _folder_icon() -> QIcon:
    global _FOLDER_ICON
    if _FOLDER_ICON is None:
        _FOLDER_ICON = QIcon(str(_RESOURCES_DIR / "folder_square.svg"))
    return _FOLDER_ICON

def _document_icon() -> QIcon:
    global _DOCUMENT_ICON
    if _DOCUMENT_ICON is None:
        _DOCUMENT_ICON = _theme.make_icon(":/icons/link_external_cyan.svg", _FOLDER_ICON_SIZE)
    return _DOCUMENT_ICON
_ARROW_ICON_SIZE    = QSize(10, 10)
_BAND_WIDTH         = 5
_TILE_RADIUS        = 0
_TILE_MARGIN        = 2
_PROJECT_COLOR_SQUARE = 10

_RESOURCES_DIR = Path(__file__).parent.parent / "resources"


def _arrow_icon(direction: str) -> QIcon:
    """Charge l'icône de flèche (up/down) depuis le fichier SVG généré par le thème."""
    return QIcon(str(_RESOURCES_DIR / f"arrow_{direction}.svg"))


# ── Style « terminal/HUD » du board (maquette) ───────────────────────────────
_BRACKET_LEN        = 18   # longueur des équerres d'angle du cadre
_BRACKET_WIDTH      = 2
_BOARD_FRAME_MARGIN = 12   # marge intérieure du cadre à équerres
_BOARD_FRAME_BG     = "#fbfcfd"          # fond du panneau TASKS
_BOARD_ACCENT_BLUE  = "rgb(10, 92, 255)" # `// TASKS` + libellés de colonnes actives

# ── Panneau Notes (maquette) ─────────────────────────────────────────────────
_NOTES_PANEL_BG     = "#eef2f8"
_NOTES_FOLDER_TEXT  = "#0f1729"
_NOTES_NOTE_TEXT    = "#56627a"

# Libellés des colonnes Kanban (affichage uniquement — l'enum reste inchangé)
_BUCKET_LABELS = {
    TaskBucket.Inbox:     "INBOX",
    TaskBucket.Today:     "TODAY",
    TaskBucket.On_Hold:   "ON HOLD",
    TaskBucket.Completed: "DONE",
}


class _SlashTitle(QWidget):
    """Titre au style maquette : `// <texte>` avec les slashes en couleur d'accent."""

    def __init__(self, text: str, point_size_delta: int = 4, color: str | None = None, parent=None) -> None:
        super().__init__(parent)
        t = _theme.current()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        slash_color = color or t.list_selected_accent
        text_color = color or t.text
        slash = QLabel("//")
        text_lbl = QLabel(text)
        for lbl, color in ((slash, slash_color), (text_lbl, text_color)):
            font = QFont(lbl.font())
            font.setBold(True)
            font.setPointSize(font.pointSize() + point_size_delta)
            lbl.setFont(font)
            lbl.setStyleSheet(f"color: {color}; background: transparent;")
        self._text_lbl = text_lbl

        layout.addWidget(slash)
        layout.addWidget(text_lbl)

    def set_text(self, text: str) -> None:
        self._text_lbl.setText(text)


class BoardFrame(QWidget):
    """Conteneur qui peint quatre équerres d'angle en cyan autour de son contenu."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            _BOARD_FRAME_MARGIN, _BOARD_FRAME_MARGIN, _BOARD_FRAME_MARGIN, _BOARD_FRAME_MARGIN
        )
        self._layout.setSpacing(6)

    def content_layout(self) -> QVBoxLayout:
        return self._layout

    def paintEvent(self, event) -> None:
        t = _theme.current()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(_BOARD_FRAME_BG))
        pen = QPen(QColor(t.list_selected_accent), _BRACKET_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        off = _BRACKET_WIDTH // 2 + 1
        L = _BRACKET_LEN
        w, h = self.width(), self.height()
        # Coin haut-gauche
        painter.drawLine(off, off, off + L, off)
        painter.drawLine(off, off, off, off + L)
        # Coin haut-droit
        painter.drawLine(w - off, off, w - off - L, off)
        painter.drawLine(w - off, off, w - off, off + L)
        # Coin bas-gauche
        painter.drawLine(off, h - off, off + L, h - off)
        painter.drawLine(off, h - off, off, h - off - L)
        # Coin bas-droit
        painter.drawLine(w - off, h - off, w - off - L, h - off)
        painter.drawLine(w - off, h - off, w - off, h - off - L)
        painter.end()


class _ColumnHeader(QWidget):
    """En-tête de colonne : `▸ INBOX` (MAJUSCULES) + badge compteur à droite."""

    def __init__(self, label: str, color: str | None = None, parent=None) -> None:
        super().__init__(parent)
        t = _theme.current()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background-color: {_BOARD_FRAME_BG};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)

        marker = QLabel("▸")
        marker.setStyleSheet(f"color: {t.tile_project_label}; background: transparent;")

        name = QLabel(label.upper())
        name_font = QFont(name.font())
        name_font.setBold(True)
        name_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        name.setFont(name_font)
        name.setStyleSheet(f"color: {color or t.text}; background: transparent;")

        self._badge = QLabel("00")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_font = QFont(self._badge.font())
        badge_font.setBold(True)
        self._badge.setFont(badge_font)
        self._badge.setStyleSheet(
            f"color: {t.tile_project_label}; background-color: {_BOARD_FRAME_BG};"
            f" border-radius: 3px; padding: 1px 6px;"
        )

        layout.addWidget(marker)
        layout.addWidget(name)
        layout.addStretch()
        layout.addWidget(self._badge)

    def set_count(self, n: int) -> None:
        self._badge.setText(f"{n:02d}")


class _DashedVLine(QWidget):
    """Fine ligne verticale pointillée pour séparer les colonnes Kanban."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:
        t = _theme.current()
        painter = QPainter(self)
        pen = QPen(QColor(t.border), 1)
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(0, 4, 0, self.height() - 4)
        painter.end()


_PROJECT_ITEM_MARGIN_X = 5
_PROJECT_ITEM_MARGIN_Y = 4
_PROJECT_ACCENT_WIDTH = 4       # thicker turquoise bar on the left edge
_PROJECT_ACCENT_TEXT_GAP = 12   # margin between the turquoise bar and the text
_PROJECT_TEXT_INDENT = 14       # left padding for unselected items
_PROJECT_GLOW_LAYERS = [(1, 70), (2, 40), (3, 18)]  # (offset, alpha) for the glow


class ProjectListDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        t = _theme.current()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        is_selected = bool(opt.state & QStyle.StateFlag.State_Selected)

        painter.save()

        if is_selected:
            # Sharp-cornered card; integer rect for crisp 1px edges.
            card_rect = option.rect.adjusted(
                _PROJECT_ITEM_MARGIN_X, _PROJECT_ITEM_MARGIN_Y,
                -_PROJECT_ITEM_MARGIN_X, -_PROJECT_ITEM_MARGIN_Y,
            )

            # Glow: concentric outlines around the card with decreasing alpha.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for offset, alpha in _PROJECT_GLOW_LAYERS:
                glow = QColor(t.list_selected_accent)
                glow.setAlpha(alpha)
                painter.setPen(QPen(glow, 1))
                painter.drawRect(card_rect.adjusted(-offset, -offset, offset, offset))

            # White background.
            painter.fillRect(card_rect, QColor(t.surface_bg))

            # Turquoise border around the card.
            painter.setPen(QPen(QColor(t.list_selected_accent), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(card_rect)

            # Thicker turquoise bar on the left edge.
            painter.fillRect(
                QRect(card_rect.x(), card_rect.y(), _PROJECT_ACCENT_WIDTH, card_rect.height()),
                QColor(t.list_selected_accent),
            )

            text_x = card_rect.x() + _PROJECT_ACCENT_WIDTH + _PROJECT_ACCENT_TEXT_GAP
            text_right = card_rect.right()
        else:
            # Unselected: white rectangle with a light grey border.
            card_rect = option.rect.adjusted(
                _PROJECT_ITEM_MARGIN_X, _PROJECT_ITEM_MARGIN_Y,
                -_PROJECT_ITEM_MARGIN_X, -_PROJECT_ITEM_MARGIN_Y,
            )
            painter.fillRect(card_rect, QColor(t.surface_bg))
            painter.setPen(QPen(QColor(t.border), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(card_rect)

            text_x = card_rect.x() + _PROJECT_TEXT_INDENT
            text_right = card_rect.right()

        text_rect = QRect(text_x, option.rect.y(), text_right - text_x, option.rect.height())
        text_color = QColor(t.list_selected_text) if is_selected else opt.palette.text().color()
        font = QFont(opt.font)
        font.setBold(is_selected)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, opt.text)

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + 14)
        return size


_NAV_CHAMFER = 9  # taille du biseau du coin inférieur droit (style maquette)


def _chamfered_rect_path(w: float, h: float, chamfer: float, inset: float = 0.5) -> QPainterPath:
    """Rectangle dont le coin inférieur droit est biseauté (style maquette)."""
    path = QPainterPath()
    path.moveTo(inset, inset)
    path.lineTo(w - inset, inset)
    path.lineTo(w - inset, h - chamfer)
    path.lineTo(w - chamfer, h - inset)
    path.lineTo(inset, h - inset)
    path.closeSubpath()
    return path


def _nav_state_colors(t, checked: bool, hover: bool):
    """Couleurs (fond, bordure, texte, gras, liseré) partagées par les boutons de
    navigation, inspirées des cartes de projet (ProjectListDelegate)."""
    if checked:
        return QColor(t.surface_bg), QColor(t.list_selected_accent), QColor(t.list_selected_text), True, True
    if hover:
        return QColor(t.button_hover), QColor(t.list_selected_accent), QColor(t.text), False, False
    return QColor(t.surface_bg), QColor(t.border), QColor(t.tile_project_label), False, False


class _NavButton(QPushButton):
    """Sidebar nav button: label on the left, dim ordinal on the right.

    Peint entièrement à la main : rectangle (sans arrondi) dont le coin
    inférieur droit est biseauté, comme d'autres éléments de la maquette."""

    def __init__(self, label: str, number: str, parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self._number = number
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        # Le texte est peint manuellement (pas via setText) : calculer la largeur
        # nécessaire pour le libellé + l'ordinal, plus les marges latérales (12 px
        # de chaque côté) et un espace de séparation. La hauteur reprend celle des
        # autres boutons (New Folder / New Note) : min-height 22 + padding 4/4.
        fm = self.fontMetrics()
        width = (
            fm.horizontalAdvance(self._label)
            + fm.horizontalAdvance(self._number)
            + 12 + 12 + 16
        )
        return QSize(width, max(fm.height(), 22) + 8)

    def paintEvent(self, event) -> None:
        # Style inspiré des cartes de sélection de projet (ProjectListDelegate) :
        # fond clair, bordure turquoise + liseré d'accent à gauche à l'état
        # sélectionné, texte foncé toujours lisible (pas de noir sur noir).
        t = _theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg, border, text_color, bold, accent_bar = _nav_state_colors(
            t, self.isChecked(), self.underMouse()
        )
        number_color = QColor(t.list_selected_accent) if self.isChecked() else QColor(t.color_btn_border)

        path = _chamfered_rect_path(self.width(), self.height(), _NAV_CHAMFER)
        painter.setPen(QPen(border, 1))
        painter.setBrush(QBrush(bg))
        painter.drawPath(path)

        if accent_bar:
            inset = 0.5
            painter.setClipPath(path)
            painter.fillRect(
                QRectF(inset, inset, _PROJECT_ACCENT_WIDTH, self.height() - 2 * inset),
                QColor(t.list_selected_accent),
            )
            painter.setClipping(False)

        font = QFont(self.font())
        font.setBold(bold)
        painter.setFont(font)
        r = self.rect().adjusted(12, 0, -12, 0)
        painter.setPen(text_color)
        painter.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)
        painter.setPen(number_color)
        painter.drawText(r, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._number)
        painter.end()


class CommandBar(QWidget):
    """Barre de commandes horizontale (sous la barre de titre) regroupant la
    navigation principale : Board, Notes, Tags, Deliverables, Media, ArchiMate, Debug."""

    home_requested = Signal()
    notes_requested = Signal()
    tags_requested = Signal()
    deliverables_requested = Signal()
    media_requested = Signal()
    archimate_requested = Signal()
    debug_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("command_bar", True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._board_btn = _NavButton("Board", "01")
        self._board_btn.setChecked(True)
        self._board_btn.clicked.connect(self.home_requested)

        self._notes_btn = _NavButton("Notes", "02")
        self._notes_btn.clicked.connect(self.notes_requested)

        self._tags_btn = _NavButton("Tags", "03")
        self._tags_btn.clicked.connect(self.tags_requested)

        self._deliverables_btn = _NavButton("Deliverables", "04")
        self._deliverables_btn.clicked.connect(self.deliverables_requested)

        self._media_btn = _NavButton("Media", "05")
        self._media_btn.clicked.connect(self.media_requested)

        self._archimate_btn = _NavButton("ArchiMate", "06")
        self._archimate_btn.clicked.connect(self.archimate_requested)

        self._debug_btn = _NavButton("Debug", "07")
        self._debug_btn.clicked.connect(self.debug_requested)

        self._buttons = {
            "board": self._board_btn,
            "notes": self._notes_btn,
            "tags": self._tags_btn,
            "deliverables": self._deliverables_btn,
            "media": self._media_btn,
            "archimate": self._archimate_btn,
            "debug": self._debug_btn,
        }

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for btn in self._buttons.values():
            # Largeur dictée par le contenu, hauteur fixe (barre horizontale).
            btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self._nav_group.addButton(btn)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        for btn in self._buttons.values():
            layout.addWidget(btn)
        layout.addStretch()

    def clear_active(self) -> None:
        """Décoche tout bouton actif (ex. lorsqu'un projet est sélectionné)."""
        self._nav_group.setExclusive(False)
        checked = self._nav_group.checkedButton()
        if checked:
            checked.setChecked(False)
        self._nav_group.setExclusive(True)

    def set_active(self, name: str) -> None:
        """Coche le bouton correspondant à la vue courante (navigation programmatique)."""
        btn = self._buttons.get(name)
        if btn is not None:
            btn.setChecked(True)


_DROP_LINE_HEIGHT = 3  # épaisseur de la ligne d'insertion turquoise
_DROP_CAP_HEIGHT  = 7  # hauteur des embouts verticaux aux extrémités
_DROP_CAP_WIDTH   = 2


class _ProjectListView(QListWidget):
    """Liste de projets réordonnable par glisser-déposer.

    L'indicateur de dépôt est peint à la main (ligne turquoise avec embouts)
    plutôt que via `setDropIndicatorShown`, dont le trait natif se voit mal
    sur les cartes dessinées par `ProjectListDelegate`."""

    projects_reordered = Signal(list)  # emits ordered list[int] of project ids

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drop_row: int | None = None
        self._press_pos = QPoint()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)  # remplacé par notre propre indicateur
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def _row_at(self, y: int) -> int:
        """Rang d'insertion pour une ordonnée donnée (0 .. count())."""
        for i in range(self.count()):
            if y < self.visualItemRect(self.item(i)).center().y():
                return i
        return self.count()

    def _clear_drop_indicator(self) -> None:
        if self._drop_row is not None:
            self._drop_row = None
            self.viewport().update()

    def mousePressEvent(self, event) -> None:
        self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        project_id: int = item.data(Qt.ItemDataRole.UserRole)
        mime = self.model().mimeData([self.currentIndex()])
        mime.setData(_PROJECT_MIME, QByteArray(str(project_id).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)

        # Aperçu semi-transparent de la carte déplacée, sous le curseur.
        rect = self.visualItemRect(item)
        ghost = QPixmap(rect.size())
        ghost.fill(Qt.GlobalColor.transparent)
        painter = QPainter(ghost)
        painter.setOpacity(0.75)
        painter.drawPixmap(0, 0, self.viewport().grab(rect))
        painter.end()
        drag.setPixmap(ghost)
        drag.setHotSpot(self._press_pos - rect.topLeft())

        drag.exec(Qt.DropAction.MoveAction)
        self._clear_drop_indicator()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_PROJECT_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_PROJECT_MIME):
            event.ignore()
            return
        super().dragMoveEvent(event)          # conserve le défilement automatique
        event.acceptProposedAction()
        row = self._row_at(event.position().toPoint().y())
        if row != self._drop_row:
            self._drop_row = row
            self.viewport().update()

    def dragLeaveEvent(self, event) -> None:
        self._clear_drop_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._clear_drop_indicator()
        if not event.mimeData().hasFormat(_PROJECT_MIME):
            event.ignore()
            return
        project_id = int(event.mimeData().data(_PROJECT_MIME).data().decode())
        event.acceptProposedAction()

        drop_row = self._row_at(event.position().toPoint().y())
        for i in range(self.count()):
            if self.item(i).data(Qt.ItemDataRole.UserRole) == project_id:
                if i == drop_row or i == drop_row - 1:
                    return                     # déposé à sa propre place
                # Bloquer les signaux : déplacer une carte ne doit pas changer
                # le projet affiché dans la vue principale.
                self.blockSignals(True)
                dragged = self.takeItem(i)
                if i < drop_row:
                    drop_row -= 1
                self.insertItem(drop_row, dragged)
                self.setCurrentItem(dragged)
                self.blockSignals(False)
                break
        else:
            return

        project_ids = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
        self.projects_reordered.emit(project_ids)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_row is None:
            return

        if self.count() == 0:
            y = _PROJECT_ITEM_MARGIN_Y
        elif self._drop_row < self.count():
            y = self.visualItemRect(self.item(self._drop_row)).top()
        else:
            y = self.visualItemRect(self.item(self.count() - 1)).bottom()

        viewport = self.viewport()
        half = _DROP_LINE_HEIGHT // 2
        y = max(half, min(y, viewport.height() - _DROP_LINE_HEIGHT + half))
        x0 = _PROJECT_ITEM_MARGIN_X
        x1 = viewport.width() - _PROJECT_ITEM_MARGIN_X

        color = QColor(_theme.current().list_selected_accent)
        painter = QPainter(viewport)
        painter.fillRect(QRect(x0, y - half, x1 - x0, _DROP_LINE_HEIGHT), color)
        cap_y = y - _DROP_CAP_HEIGHT // 2
        painter.fillRect(QRect(x0, cap_y, _DROP_CAP_WIDTH, _DROP_CAP_HEIGHT), color)
        painter.fillRect(QRect(x1 - _DROP_CAP_WIDTH, cap_y, _DROP_CAP_WIDTH, _DROP_CAP_HEIGHT), color)
        painter.end()


class ProjectListWidget(QWidget):
    project_selected = Signal(object)  # emits Project | None

    def __init__(self, repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self.setMinimumWidth(200)

        t = _theme.current()

        self._list = _ProjectListView(self)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self._list.setItemDelegate(ProjectListDelegate(self._list))
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.projects_reordered.connect(self._on_projects_reordered)

        self._show_archived_cb = QCheckBox("archived")
        self._show_archived_cb.stateChanged.connect(self._load_projects)

        accent_hover = QColor(t.accent_color).darker(115).name()
        self._new_btn = QPushButton("+ NEW")
        self._new_btn.setStyleSheet(
            f"QPushButton {{ background-color: {t.accent_color}; color: white; "
            f"border: none; border-radius: 6px; padding: 4px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {accent_hover}; }}"
        )
        self._new_btn.clicked.connect(self._on_new_project)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(4, 2, 4, 2)
        bottom_layout.addWidget(self._show_archived_cb)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self._new_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._list, stretch=1)      # fills all available vertical space
        layout.addLayout(bottom_layout)              # archived checkbox + new project button

        self._load_projects()

    def _load_projects(self) -> None:
        self._list.clear()
        for project in self._repo.list_all(archived_only=self._show_archived_cb.isChecked()):
            item = QListWidgetItem(project.name)
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            self._list.addItem(item)

    def _on_selection_changed(
        self, current: QListWidgetItem | None, _: QListWidgetItem | None
    ) -> None:
        if current is None:
            self.project_selected.emit(None)
            return
        project_id = current.data(Qt.ItemDataRole.UserRole)
        self.project_selected.emit(self._repo.get(project_id))

    def _on_projects_reordered(self, project_ids: list[int]) -> None:
        # La liste affichée est déjà dans le bon ordre : seule la persistance reste.
        self._repo.set_order(project_ids)

    def _on_new_project(self) -> None:
        dialog = NewProjectDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._repo.create(name=dialog.name(), description=dialog.description(), color=dialog.color())
            self._load_projects()

    def clear_selection(self) -> None:
        self._list.blockSignals(True)
        self._list.setCurrentRow(-1)
        self._list.blockSignals(False)


class KanbanCardDelegate(QStyledItemDelegate):
    def _project_font(self, base_font) -> QFont:
        font = QFont(base_font)
        font.setItalic(True)
        font.setPointSize(max(base_font.pointSize() - 2, 7))
        return font

    def paint(self, painter, option, index) -> None:
        t = _theme.current()
        tile_bg = QColor(t.tile_bg)
        tile_border = QColor(t.tile_border)
        priority_colors = {
            TaskPriority.Low:    QColor(t.priority_low),
            TaskPriority.Medium: QColor(t.priority_medium),
            TaskPriority.High:   QColor(t.priority_high),
        }

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tile_rect  = option.rect.adjusted(_TILE_MARGIN, _TILE_MARGIN, -_TILE_MARGIN, -_TILE_MARGIN)
        tile_rectf = QRectF(tile_rect)

        # background
        path = QPainterPath()
        path.addRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(tile_bg))
        painter.drawPath(path)

        # clip to tile so selection highlight respects rounded corners
        painter.setClipPath(path)

        priority = index.data(_PRIORITY_ROLE)
        color = priority_colors.get(priority, QColor(t.priority_low))
        band = QRect(tile_rect.x(), tile_rect.y(), _BAND_WIDTH, tile_rect.height())
        painter.fillRect(band, color)

        # border drawn outside clip so the stroke isn't cut off
        painter.restore()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(tile_border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + _TILE_MARGIN * 2)
        return size


class KanbanCardWidget(QWidget):
    def __init__(self, task, subtasks, project_name, subtask_repo, project_color: str = "", parent=None) -> None:
        super().__init__(parent)
        self._priority = task.priority
        self._project_color = project_color
        t = _theme.current()
        self.setStyleSheet(f"""
            QLabel    {{ color: {t.tile_text}; background: transparent; }}
            QCheckBox {{ color: {t.tile_text}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_BAND_WIDTH + 6, 10, 6, 10)
        layout.setSpacing(2)

        title = QLabel(task.title)
        title.setWordWrap(True)
        layout.addWidget(title)

        for subtask in subtasks:
            cb = QCheckBox(subtask.title)
            cb.setChecked(subtask.completed)
            # Give the checkbox a light palette so the system style draws a
            # visible indicator (border + checkmark) on our white card background.
            cb.setStyleSheet(
                f"QCheckBox {{ color: {t.tile_text}; }}"
                f" QCheckBox::indicator {{ border: 1px solid {t.tile_checkbox_border}; border-radius: 2px; }}"
                f" QCheckBox::indicator:checked {{ background-color: {t.tile_checkbox_checked_bg}; border-color: {t.tile_checkbox_checked_border}; image: url({_CHECK_SVG}); }}"
            )
            cb.stateChanged.connect(
                lambda state, sid=subtask.id: subtask_repo.set_completed(
                    sid, state == Qt.CheckState.Checked.value
                )
            )
            layout.addWidget(cb)

        if project_name:
            proj_label = QLabel(project_name)
            proj_font = QFont(proj_label.font())
            proj_font.setItalic(True)
            proj_font.setPointSize(max(proj_font.pointSize() - 2, 7))
            proj_label.setFont(proj_font)
            proj_label.setStyleSheet(f"color: {t.tile_project_label}; background: transparent;")
            layout.addWidget(proj_label)

    def paintEvent(self, event) -> None:
        t = _theme.current()
        tile_bg = QColor(t.tile_bg)
        tile_border = QColor(t.tile_border)
        priority_colors = {
            TaskPriority.Low:    QColor(t.priority_low),
            TaskPriority.Medium: QColor(t.priority_medium),
            TaskPriority.High:   QColor(t.priority_high),
        }

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tile_rect  = self.rect().adjusted(_TILE_MARGIN, _TILE_MARGIN, -_TILE_MARGIN, -_TILE_MARGIN)
        tile_rectf = QRectF(tile_rect)

        # Rounded background
        path = QPainterPath()
        path.addRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(tile_bg))
        painter.drawPath(path)

        # Priority band clipped to rounded rect
        painter.setClipPath(path)
        color = priority_colors.get(self._priority, QColor(t.priority_low))
        painter.fillRect(QRectF(tile_rect.x(), tile_rect.y(), _BAND_WIDTH, tile_rect.height()), color)

        # Project color square — bottom-right corner
        if self._project_color:
            sq = _PROJECT_COLOR_SQUARE
            sq_x = tile_rect.right() - sq - 4
            sq_y = tile_rect.bottom() - sq - 4
            painter.fillRect(QRectF(sq_x, sq_y, sq, sq), QColor(self._project_color))

        painter.setClipping(False)

        # Border
        painter.setPen(QPen(tile_border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(tile_rectf, _TILE_RADIUS, _TILE_RADIUS)


class KanbanColumnWidget(QListWidget):
    task_dropped    = Signal(int, object)   # (task_id, target_bucket: TaskBucket)
    tasks_reordered = Signal(object, list)  # (bucket: TaskBucket, task_ids: list[int])

    def __init__(self, bucket: TaskBucket, parent=None) -> None:
        super().__init__(parent)
        self._bucket = bucket
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        task_id: int = item.data(Qt.ItemDataRole.UserRole)
        mime = self.model().mimeData([self.currentIndex()])
        mime.setData(_KANBAN_MIME, QByteArray(str(task_id).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_KANBAN_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_KANBAN_MIME):
            super().dragMoveEvent(event)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_KANBAN_MIME):
            event.ignore()
            return
        task_id = int(event.mimeData().data(_KANBAN_MIME).data().decode())
        source = event.source()
        if isinstance(source, KanbanColumnWidget) and source._bucket == self._bucket:
            event.acceptProposedAction()
            pos = event.pos()
            drop_row = self.count()
            for i in range(self.count()):
                if pos.y() < self.visualItemRect(self.item(i)).center().y():
                    drop_row = i
                    break
            for i in range(self.count()):
                if self.item(i).data(Qt.ItemDataRole.UserRole) == task_id:
                    dragged_item = self.takeItem(i)
                    if i < drop_row:
                        drop_row -= 1
                    break
            else:
                return
            self.insertItem(drop_row, dragged_item)
            self.setCurrentItem(dragged_item)
            task_ids = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
            self.tasks_reordered.emit(self._bucket, task_ids)
            return
        event.acceptProposedAction()
        self.task_dropped.emit(task_id, self._bucket)


class KanbanBoardWidget(QWidget):
    task_edit_requested = Signal(int)           # emits task_id
    task_bucket_changed = Signal(int, object)   # (task_id, new_bucket: TaskBucket)
    task_selected       = Signal(int)           # emits task_id
    tasks_reordered     = Signal(object, list)  # (bucket: TaskBucket, task_ids: list[int])

    COLUMNS = [
        TaskBucket.Inbox,
        TaskBucket.Today,
        TaskBucket.On_Hold,
        TaskBucket.Completed,
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._columns: dict[TaskBucket, QListWidget] = {}
        self._headers: dict[TaskBucket, _ColumnHeader] = {}
        self._selected_task_id: int | None = None

        board = QWidget()
        board_layout = QHBoxLayout(board)
        board_layout.setSpacing(8)
        board_layout.setContentsMargins(0, 0, 0, 0)

        for i, bucket in enumerate(self.COLUMNS):
            if i > 0:
                board_layout.addWidget(_DashedVLine())

            col_widget = QWidget()
            col_layout = QVBoxLayout(col_widget)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(4)

            header_color = _BOARD_ACCENT_BLUE if bucket in (TaskBucket.Inbox, TaskBucket.Today) else None
            header = _ColumnHeader(_BUCKET_LABELS.get(bucket, bucket.value), color=header_color)
            col_layout.addWidget(header)

            list_widget = KanbanColumnWidget(bucket)
            list_widget.setSpacing(5)
            list_widget.setWordWrap(True)
            list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
            list_widget.task_dropped.connect(self._on_task_dropped)
            list_widget.tasks_reordered.connect(self._on_tasks_reordered)
            list_widget.currentItemChanged.connect(self._on_column_selection_changed)
            col_layout.addWidget(list_widget, stretch=1)

            self._columns[bucket] = list_widget
            self._headers[bucket] = header
            board_layout.addWidget(col_widget, stretch=1)

        scroll = QScrollArea()
        scroll.setWidget(board)
        scroll.setWidgetResizable(True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

    def populate(self, tasks: list, project_names: dict | None = None, project_colors: dict | None = None, subtask_repo=None) -> None:
        self._selected_task_id = None
        for lw in self._columns.values():
            lw.clear()
        for task in tasks:
            subtasks = subtask_repo.list_for_task(task.id) if subtask_repo else []
            project_name = project_names.get(task.project_id, "") if project_names else ""
            project_color = project_colors.get(task.project_id, "") if project_colors else ""
            card = KanbanCardWidget(task, subtasks, project_name, subtask_repo, project_color=project_color)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            item.setData(_PRIORITY_ROLE, task.priority)
            item.setData(_PROJECT_ROLE, project_name)
            item.setSizeHint(QSize(0, card.sizeHint().height() + _TILE_MARGIN * 2))
            column = self._columns[task.bucket]
            column.addItem(item)
            column.setItemWidget(item, card)
        self._refresh_column_states()

    def _refresh_column_states(self) -> None:
        """Met à jour le compteur de chaque colonne et l'apparence des colonnes vides."""
        t = _theme.current()
        for bucket, column in self._columns.items():
            count = column.count()
            self._headers[bucket].set_count(count)
            if count == 0:
                column.setStyleSheet(
                    f"QListWidget {{ background-color: {_BOARD_FRAME_BG};"
                    f" border: 1px dashed {t.border}; }}"
                )
            else:
                column.setStyleSheet(
                    f"QListWidget {{ background-color: {_BOARD_FRAME_BG};"
                    f" border: none; }}"
                )

    def _on_column_selection_changed(
        self, current: QListWidgetItem | None, _previous
    ) -> None:
        sender_widget = self.sender()
        for lw in self._columns.values():
            if lw is not sender_widget:
                lw.blockSignals(True)
                lw.clearSelection()
                lw.setCurrentItem(None)
                lw.blockSignals(False)
        if current is None:
            self._selected_task_id = None
            return
        self._selected_task_id = current.data(Qt.ItemDataRole.UserRole)
        self.task_selected.emit(self._selected_task_id)

    def selected_task_id(self) -> int | None:
        return self._selected_task_id

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self.task_edit_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_task_dropped(self, task_id: int, target_bucket) -> None:
        self.task_bucket_changed.emit(task_id, target_bucket)

    def _on_tasks_reordered(self, bucket, task_ids: list[int]) -> None:
        self.tasks_reordered.emit(bucket, task_ids)


class HomeWidget(QWidget):
    def __init__(self, task_repo: TaskRepository, subtask_repo: SubtaskRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._task_repo = task_repo
        self._subtask_repo = subtask_repo
        self._project_repo = project_repo

        self._board = KanbanBoardWidget()
        self._board.task_edit_requested.connect(self._on_task_edit_requested)
        self._board.task_bucket_changed.connect(self._on_bucket_changed)
        self._board.tasks_reordered.connect(self._on_tasks_reordered)

        title = _SlashTitle("ALL TASKS", point_size_delta=4)

        self._move_up_btn = QPushButton()
        self._move_up_btn.setIcon(_arrow_icon("up"))
        self._move_up_btn.setIconSize(_ARROW_ICON_SIZE)
        self._move_up_btn.setFixedWidth(28)
        self._move_up_btn.setToolTip("Move up")
        self._move_up_btn.clicked.connect(self._on_move_up)

        self._move_down_btn = QPushButton()
        self._move_down_btn.setIcon(_arrow_icon("down"))
        self._move_down_btn.setIconSize(_ARROW_ICON_SIZE)
        self._move_down_btn.setFixedWidth(28)
        self._move_down_btn.setToolTip("Move down")
        self._move_down_btn.clicked.connect(self._on_move_down)

        self._show_archived_cb = QCheckBox("Show archived")
        self._show_archived_cb.stateChanged.connect(self.load)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addStretch()

        # ── Panneau TASKS encadré (équerres cyan) ─────────────────────────
        board_frame = BoardFrame()
        board_header = QHBoxLayout()
        board_header.setContentsMargins(0, 0, 0, 0)
        board_header.addWidget(_SlashTitle("TASKS", point_size_delta=1, color=_BOARD_ACCENT_BLUE))
        board_header.addStretch()
        board_header.addWidget(self._show_archived_cb)
        board_header.addWidget(self._move_up_btn)
        board_header.addWidget(self._move_down_btn)

        board_sep = QFrame()
        board_sep.setFrameShape(QFrame.Shape.HLine)
        board_sep.setFrameShadow(QFrame.Shadow.Plain)

        frame_layout = board_frame.content_layout()
        frame_layout.addLayout(board_header)
        frame_layout.addWidget(board_sep)
        frame_layout.addWidget(self._board, stretch=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(board_frame, stretch=1)

    def load(self) -> None:
        projects = self._project_repo.list_all()
        project_names = {p.id: p.name for p in projects}
        project_colors = {p.id: p.color for p in projects}
        self._board.populate(self._task_repo.list_all(archived_only=self._show_archived_cb.isChecked()), project_names=project_names, project_colors=project_colors, subtask_repo=self._subtask_repo)

    def _on_move_up(self) -> None:
        self._on_move(-1)

    def _on_move_down(self) -> None:
        self._on_move(1)

    def _on_move(self, direction: int) -> None:
        task_id = self._board.selected_task_id()
        if task_id is None:
            return
        task = self._task_repo.get(task_id)
        if task is None:
            return
        bucket_tasks = [t for t in self._task_repo.list_all(archived_only=self._show_archived_cb.isChecked()) if t.bucket == task.bucket]
        idx = next((i for i, t in enumerate(bucket_tasks) if t.id == task_id), None)
        if idx is None:
            return
        neighbor_idx = idx + direction
        if not (0 <= neighbor_idx < len(bucket_tasks)):
            return
        self._task_repo.swap_order(task_id, bucket_tasks[neighbor_idx].id)
        self.load()

    def _on_task_edit_requested(self, task_id: int) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        dialog = TaskDetailDialog(task, self._subtask_repo, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.deleted():
                self._task_repo.delete(task.id)
            else:
                task.title = dialog.title()
                task.description = dialog.description()
                task.state = dialog.state()
                task.priority = dialog.priority()
                task.bucket = dialog.bucket()
                task.archived = dialog.archived()
                self._task_repo.update(task)
            self.load()

    def _on_bucket_changed(self, task_id: int, new_bucket) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        prev_bucket = task.bucket
        task.bucket = new_bucket
        if new_bucket == TaskBucket.Completed:
            task.state = TaskState.Completed
        elif new_bucket == TaskBucket.On_Hold:
            task.state = TaskState.On_Hold
        elif new_bucket in (TaskBucket.Inbox, TaskBucket.Today) and prev_bucket in (TaskBucket.Completed, TaskBucket.On_Hold):
            task.state = TaskState.In_Progress
        self._task_repo.update(task)
        self.load()

    def _on_tasks_reordered(self, bucket, task_ids: list[int]) -> None:
        self._task_repo.set_order_for_bucket(bucket, task_ids)


class _VerticalTabButton(QPushButton):
    """Bouton d'onglet vertical : même style que _NavButton (fond clair, bordure
    turquoise + liseré à la sélection, coin biseauté), texte pivoté à 90°."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._label = text
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self._label)
        text_h = fm.height()
        return QSize(text_h + 16, text_w + 24)

    def paintEvent(self, event):
        t = _theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg, border, text_color, bold, accent_bar = _nav_state_colors(
            t, self.isChecked(), self.underMouse()
        )

        path = _chamfered_rect_path(self.width(), self.height(), _NAV_CHAMFER)
        painter.setPen(QPen(border, 1))
        painter.setBrush(QBrush(bg))
        painter.drawPath(path)

        if accent_bar:
            # Liseré d'accent sur le bord supérieur (bord « d'attaque » du texte pivoté).
            inset = 0.5
            painter.setClipPath(path)
            painter.fillRect(
                QRectF(inset, inset, self.width() - 2 * inset, _PROJECT_ACCENT_WIDTH),
                QColor(t.list_selected_accent),
            )
            painter.setClipping(False)

        font = QFont(self.font())
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(
            QRect(0, 0, self.height(), self.width()),
            Qt.AlignmentFlag.AlignCenter,
            self._label,
        )
        painter.end()


class _VerticalTabBar(QWidget):
    """Barre d'onglets verticale à droite du contenu."""

    tab_changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self._buttons: list[_VerticalTabButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        for i, label in enumerate(labels):
            btn = _VerticalTabButton(label)
            self._group.addButton(btn, i)
            layout.addWidget(btn)
            self._buttons.append(btn)

        layout.addStretch()
        self._buttons[0].setChecked(True)
        self._group.idClicked.connect(self.tab_changed)


# QTreeWidget item data roles for the notes panel folder tree
_NOTE_NODE_DATA_ROLE   = Qt.ItemDataRole.UserRole        # folder_id, note_id or document_id
_NOTE_NODE_TYPE_ROLE   = Qt.ItemDataRole.UserRole + 1   # "folder" | "note" | "document"
_NOTE_NODE_FOLDER_ROLE = Qt.ItemDataRole.UserRole + 2   # folder_id of the note/document (leaf nodes only)
_NOTE_NODE_URL_ROLE    = Qt.ItemDataRole.UserRole + 3   # url (document nodes only)

_NOTE_NODE_TYPE_FOLDER   = "folder"
_NOTE_NODE_TYPE_NOTE     = "note"
_NOTE_NODE_TYPE_DOCUMENT = "document"


class _FolderTree(QTreeWidget):
    """QTreeWidget avec drag-and-drop pour déplacer dossiers, notes et documents.

    Accepte aussi les dépôts *externes* (Edge, Explorateur) porteurs d'un lien,
    qui créent un document dans le dossier visé."""

    folder_moved = Signal(int, object)  # (folder_id, new_parent_id: int | None)
    note_moved   = Signal(int, object)  # (note_id,   new_folder_id: int | None)
    document_moved = Signal(int, object)  # (document_id, new_folder_id: int | None)
    document_dropped = Signal(str, str, object)  # (name, url, folder_id: int | None)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        # DragDrop (et non InternalMove) : en InternalMove, QAbstractItemView
        # refuse tout drag dont la source n'est pas cette vue, avant même que
        # dropEvent ne soit atteint — les liens venus d'Edge n'arriveraient jamais.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        # InternalMove imposait Move ; en DragDrop il faut le redemander pour que
        # les déplacements internes gardent leur curseur (et non celui de copie).
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None or item.data(0, _NOTE_NODE_TYPE_ROLE) not in (
            _NOTE_NODE_TYPE_FOLDER, _NOTE_NODE_TYPE_NOTE, _NOTE_NODE_TYPE_DOCUMENT
        ):
            return
        super().startDrag(supported_actions)

    # ── Dépôts externes ───────────────────────────────────────────────────
    def dragEnterEvent(self, event) -> None:
        if self._is_external_link_drag(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._is_external_link_drag(event):
            # Laisser la vue faire son travail visuel (survol, auto-scroll,
            # dépliage des dossiers) avant d'imposer notre acceptation : elle
            # refuserait sinon un MIME que son modèle ne connaît pas.
            super().dragMoveEvent(event)
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    @staticmethod
    def _is_external_link_drag(event) -> bool:
        """Drag venu d'une autre application et porteur d'un lien potentiel.

        Test volontairement bon marché (appelé à chaque dragMoveEvent) : on cherche
        seulement un schéma d'URL, l'extraction complète n'a lieu qu'au dépôt."""
        if event.source() is not None:
            return False
        mime = event.mimeData()
        if mime.hasUrls():
            return True
        for payload in (mime.text() if mime.hasText() else "", mime.html() if mime.hasHtml() else ""):
            if any(scheme in payload for scheme in URL_SCHEMES):
                return True
        return False

    def dropEvent(self, event) -> None:
        # Le test doit précéder tout appel à currentItem() : sur un dépôt externe
        # celui-ci renvoie le dernier item *sélectionné*, et le code interne
        # déplacerait alors une note sans rapport avec le geste de l'utilisateur.
        if event.source() is None:
            self._handle_external_drop(event)
            return

        dragged = self.currentItem()
        if dragged is None:
            event.ignore()
            return

        dragged_type = dragged.data(0, _NOTE_NODE_TYPE_ROLE)
        target = self.itemAt(event.position().toPoint())
        if target is None or target is dragged:
            event.ignore()
            return

        indicator = self.dropIndicatorPosition()
        on_item = indicator == QAbstractItemView.DropIndicatorPosition.OnItem

        if dragged_type == _NOTE_NODE_TYPE_FOLDER:
            self._handle_folder_drop(dragged, target, on_item, event)
        elif dragged_type in (_NOTE_NODE_TYPE_NOTE, _NOTE_NODE_TYPE_DOCUMENT):
            self._handle_leaf_drop(dragged, target, on_item, event)
        else:
            event.ignore()

    def _handle_external_drop(self, event) -> None:
        """Crée un document à partir d'un lien déposé depuis une autre application.

        Le QMimeData d'un drag externe n'est valide que pendant l'événement : tout
        est extrait ici, de façon synchrone, avant d'émettre le signal."""
        mime = event.mimeData()
        link = extract_document_link(
            mime.html() if mime.hasHtml() else None,
            mime.text() if mime.hasText() else None,
            [u.toString() for u in mime.urls()] if mime.hasUrls() else [],
        )
        if link is None:
            event.ignore()
            return

        target = self.itemAt(event.position().toPoint())
        folder_id = self._resolve_drop_folder_id(target)
        # Contrairement aux dépôts internes, il faut accepter : la source (Edge)
        # considère sinon que le dépôt a été refusé.
        event.acceptProposedAction()
        name, url = link
        self.document_dropped.emit(name, url, folder_id)

    @staticmethod
    def _resolve_drop_folder_id(target) -> "int | None":
        """Dossier visé par un dépôt externe, None pour la racine du projet.

        Contrairement aux dépôts internes, la résolution ne s'appuie pas sur
        `dropIndicatorPosition()` : Qt ne le met à jour que lorsque son modèle
        reconnaît le MIME déposé, ce qui n'est jamais le cas d'un lien venu
        d'Edge. La règle est donc plus simple — déposer n'importe où sur la
        ligne d'un dossier place le document dans ce dossier, déposer sur une
        note ou un document le place à côté d'elle, et la zone vide sous le
        dernier élément vise la racine."""
        if target is None:
            return None
        if target.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_FOLDER:
            return target.data(0, _NOTE_NODE_DATA_ROLE)
        parent = target.parent()
        if parent is not None and parent.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_FOLDER:
            return parent.data(0, _NOTE_NODE_DATA_ROLE)
        return None

    def _handle_folder_drop(self, dragged, target, on_item, event) -> None:
        # Nouveau parent : le dossier cible (OnItem) ou le parent de la cible
        if target.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_FOLDER and on_item:
            new_parent_item = target
        else:
            new_parent_item = target.parent()  # None = racine

        # Refuser si dépôt dans soi-même ou un descendant
        ancestor = new_parent_item
        while ancestor is not None:
            if ancestor is dragged:
                event.ignore()
                return
            ancestor = ancestor.parent()

        folder_id: int = dragged.data(0, _NOTE_NODE_DATA_ROLE)
        new_parent_id = (
            new_parent_item.data(0, _NOTE_NODE_DATA_ROLE)
            if new_parent_item is not None else None
        )
        current_parent_item = dragged.parent()
        current_parent_id = (
            current_parent_item.data(0, _NOTE_NODE_DATA_ROLE)
            if current_parent_item is not None else None
        )
        if new_parent_id == current_parent_id:
            event.ignore()
            return

        event.ignore()
        self.folder_moved.emit(folder_id, new_parent_id)

    def _handle_leaf_drop(self, dragged, target, on_item, event) -> None:
        """Déplacement d'une feuille (note ou document) vers un autre dossier."""
        # Nouveau dossier : le dossier cible (OnItem) ou le dossier parent de la cible
        if target.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_FOLDER and on_item:
            new_folder_item = target
        else:
            parent = target.parent()
            new_folder_item = (
                parent
                if parent is not None and parent.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_FOLDER
                else None
            )

        entity_id: int = dragged.data(0, _NOTE_NODE_DATA_ROLE)
        new_folder_id = (
            new_folder_item.data(0, _NOTE_NODE_DATA_ROLE)
            if new_folder_item is not None else None
        )
        if new_folder_id == dragged.data(0, _NOTE_NODE_FOLDER_ROLE):
            event.ignore()
            return

        event.ignore()
        if dragged.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_DOCUMENT:
            self.document_moved.emit(entity_id, new_folder_id)
        else:
            self.note_moved.emit(entity_id, new_folder_id)


class ProjectDetailWidget(QWidget):
    note_edit_requested = Signal(int)        # emits note_id
    deliverable_edit_requested = Signal(int) # emits deliverable_id
    document_open_requested = Signal(str)    # emits url
    project_renamed = Signal()

    def __init__(self, task_repo: TaskRepository, project_repo: ProjectRepository, subtask_repo: SubtaskRepository, note_repo: NoteRepository, folder_repo: FolderRepository, deliverable_repo: DeliverableRepository, tmpl_repo: DeliverableTemplateRepository, document_repo: DocumentRepository, prefs=None, parent=None) -> None:
        super().__init__(parent)
        self._task_repo = task_repo
        self._project_repo = project_repo
        self._subtask_repo = subtask_repo
        self._note_repo = note_repo
        self._folder_repo = folder_repo
        self._deliverable_repo = deliverable_repo
        self._tmpl_repo = tmpl_repo
        self._document_repo = document_repo
        self._prefs = prefs
        self._current_project = None
        self._current_project_id: int | None = None
        self._desc_raw: str = ""
        self._note_selected_folder_id: int | None = None

        # --- Empty state page ---
        empty_label = QLabel("Select a project from the list")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # --- Content page ---
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(8)

        # Name header (inline-editable) — sans cadre pour ressembler à un titre
        self._name_label = QLineEdit()
        self._name_label.setFrame(False)
        self._name_label.setStyleSheet(
            "QLineEdit { background: transparent; border: none; padding: 0; }"
        )
        font = self._name_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self._name_label.setFont(font)
        self._name_label.editingFinished.connect(self._save_name)

        self._archive_cb = QCheckBox("Archive")
        self._archive_cb.stateChanged.connect(self._on_archive_changed)

        self._color_btn = QPushButton()
        self._color_btn.setFixedWidth(24)
        self._color_btn.setToolTip("Choose a color")
        self._color_btn.setStyleSheet(f"border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px; padding: 0; min-height: 0;")
        self._color_btn.clicked.connect(self._pick_color)

        name_slash = QLabel("//")
        slash_font = QFont(name_slash.font())
        slash_font.setBold(True)
        slash_font.setPointSize(slash_font.pointSize() + 4)
        name_slash.setFont(slash_font)
        name_slash.setStyleSheet(
            f"color: {_theme.current().list_selected_accent}; background: transparent;"
        )

        name_header = QHBoxLayout()
        name_header.addWidget(name_slash)
        name_header.addWidget(self._name_label, stretch=1)
        name_header.addWidget(self._color_btn)
        name_header.addWidget(self._archive_cb)
        content_layout.addLayout(name_header)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        content_layout.addWidget(sep1)

        # Description toggle
        self._desc_toggle = QToolButton()
        self._desc_toggle.setText("DESCRIPTION")
        self._desc_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._desc_toggle.setArrowType(Qt.ArrowType.RightArrow)  # collapsed by default
        self._desc_toggle.setCheckable(True)
        self._desc_toggle.setChecked(False)
        self._desc_toggle.setAutoRaise(True)
        self._desc_toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._desc_toggle.toggled.connect(self._on_desc_toggled)
        content_layout.addWidget(self._desc_toggle)

        # Description body (no stretch — sizeHint sizes it, task table takes remaining space)
        self._desc_text = QTextEdit()
        self._desc_text.setReadOnly(True)
        self._desc_text.setFrameShape(QFrame.Shape.NoFrame)
        self._desc_text.setVisible(False)
        self._desc_text.installEventFilter(self)
        self._desc_text.viewport().installEventFilter(self)
        self._desc_text.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        content_layout.addWidget(self._desc_text)

        # ── Tasks panel (left side of splitter) : cadre à équerres ────────
        tasks_panel = BoardFrame()
        tasks_panel_layout = tasks_panel.content_layout()

        # Tasks header row: `// TASKS` à gauche + contrôles à droite
        tasks_header = QHBoxLayout()
        tasks_header.setContentsMargins(0, 0, 0, 0)
        tasks_header.addWidget(_SlashTitle("TASKS", point_size_delta=1, color=_BOARD_ACCENT_BLUE))
        tasks_header.addStretch()

        self._view_selector = QComboBox()
        self._view_selector.addItem("List")
        self._view_selector.addItem("Board")
        self._view_selector.currentIndexChanged.connect(self._on_view_changed)
        tasks_header.addWidget(self._view_selector)

        self._purge_btn = QPushButton("PURGE")
        self._purge_btn.clicked.connect(self._on_purge)
        tasks_header.addWidget(self._purge_btn)

        self._move_up_btn = QPushButton()
        self._move_up_btn.setIcon(_arrow_icon("up"))
        self._move_up_btn.setIconSize(_ARROW_ICON_SIZE)
        self._move_up_btn.setFixedWidth(28)
        self._move_up_btn.setToolTip("Move up")
        self._move_up_btn.clicked.connect(self._on_move_up)

        self._move_down_btn = QPushButton()
        self._move_down_btn.setIcon(_arrow_icon("down"))
        self._move_down_btn.setIconSize(_ARROW_ICON_SIZE)
        self._move_down_btn.setFixedWidth(28)
        self._move_down_btn.setToolTip("Move down")
        self._move_down_btn.clicked.connect(self._on_move_down)

        t = _theme.current()
        accent_hover = QColor(t.accent_color).darker(115).name()
        new_task_btn = QPushButton("+ NEW")
        new_task_btn.setStyleSheet(
            f"QPushButton {{ background-color: {t.accent_color}; color: white; "
            f"border: none; border-radius: 6px; padding: 4px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {accent_hover}; }}"
        )
        new_task_btn.clicked.connect(self._on_new_task)

        tasks_header.addWidget(self._move_up_btn)
        tasks_header.addWidget(self._move_down_btn)
        tasks_header.addWidget(new_task_btn)
        tasks_panel_layout.addLayout(tasks_header)

        # Separator sous l'en-tête
        tasks_sep = QFrame()
        tasks_sep.setFrameShape(QFrame.Shape.HLine)
        tasks_sep.setFrameShadow(QFrame.Shadow.Plain)
        tasks_panel_layout.addWidget(tasks_sep)

        # Task table
        self._task_table = QTableWidget()
        self._task_table.setColumnCount(4)
        self._task_table.setHorizontalHeaderLabels(["Title", "State", "Priority", "Bucket"])
        self._task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._task_table.verticalHeader().setVisible(False)
        self._task_table.horizontalHeader().setStretchLastSection(True)
        self._task_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._task_table.cellDoubleClicked.connect(self._on_task_double_clicked)

        # Kanban board (board view)
        self._kanban_board = KanbanBoardWidget()
        self._kanban_board.task_edit_requested.connect(self._on_kanban_task_edit_requested)
        self._kanban_board.task_bucket_changed.connect(self._on_kanban_bucket_changed)
        self._kanban_board.tasks_reordered.connect(self._on_kanban_tasks_reordered)

        # Inner stack: index 0 = List, index 1 = Board
        self._task_view_stack = QStackedWidget()
        self._task_view_stack.addWidget(self._task_table)
        self._task_view_stack.addWidget(self._kanban_board)
        tasks_panel_layout.addWidget(self._task_view_stack, stretch=1)

        # ── Right panel: Notes / Deliverables / Documents ─────────────────
        # Notes content
        notes_content = QWidget()
        notes_content.setStyleSheet(f"background-color: {_NOTES_PANEL_BG};")
        notes_content_layout = QVBoxLayout(notes_content)
        notes_content_layout.setContentsMargins(8, 8, 8, 8)
        notes_content_layout.setSpacing(8)

        t_notes = _theme.current()
        notes_accent_hover = QColor(t_notes.accent_color).darker(115).name()

        notes_header = QHBoxLayout()
        notes_header.setContentsMargins(0, 0, 0, 0)
        notes_header.setSpacing(8)
        self._new_folder_btn = QPushButton("New Folder")
        self._new_folder_btn.setIcon(_plus_icon())
        self._new_folder_btn.setIconSize(_PLUS_ICON_SIZE)
        self._new_folder_btn.setStyleSheet(
            f"QPushButton {{ background-color: {t_notes.button_bg}; color: {t_notes.text}; "
            f"border: 1px solid {t_notes.border}; border-radius: 0; padding: 4px 12px; }}"
            f"QPushButton:hover {{ background-color: {t_notes.button_hover}; }}"
            f"QPushButton:pressed {{ background-color: {t_notes.button_pressed}; }}"
        )
        self._new_folder_btn.clicked.connect(self._on_new_folder)
        notes_header.addWidget(self._new_folder_btn, stretch=1)
        new_note_btn = QPushButton("New Note")
        new_note_btn.setIcon(_plus_icon_white())
        new_note_btn.setIconSize(_PLUS_ICON_SIZE)
        new_note_btn.setStyleSheet(
            f"QPushButton {{ background-color: {t_notes.accent_color}; color: white; "
            f"border: none; border-radius: 0; padding: 4px 12px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {notes_accent_hover}; }}"
        )
        new_note_btn.clicked.connect(self._on_new_note)
        notes_header.addWidget(new_note_btn, stretch=1)
        notes_content_layout.addLayout(notes_header)

        self._note_tree = _FolderTree()
        self._note_tree.setColumnCount(1)
        self._note_tree.setHeaderHidden(True)
        self._note_tree.setFrameShape(QFrame.Shape.NoFrame)
        self._note_tree.setStyleSheet(
            f"QTreeWidget {{ background-color: {_NOTES_PANEL_BG}; border: none; }}"
        )
        self._note_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._note_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._note_tree.itemDoubleClicked.connect(self._on_note_item_double_clicked)
        self._note_tree.currentItemChanged.connect(self._on_note_selection_changed)
        self._note_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._note_tree.customContextMenuRequested.connect(self._on_notes_context_menu)
        self._note_tree.folder_moved.connect(self._on_folder_moved)
        self._note_tree.note_moved.connect(self._on_note_moved)
        self._note_tree.document_moved.connect(self._on_document_moved)
        self._note_tree.document_dropped.connect(self._on_document_dropped)
        self._note_tree.itemExpanded.connect(self._on_folder_expanded)
        self._note_tree.itemCollapsed.connect(self._on_folder_collapsed)
        notes_content_layout.addWidget(self._note_tree, stretch=1)

        # Coller un lien (SharePoint…) crée un document dans le dossier sélectionné.
        # WindowShortcut plutôt que WidgetWithChildrenShortcut : le raccourci doit
        # marcher dès que la page projet est affichée, quel que soit le panneau qui
        # a le focus. Qt désactive les raccourcis des widgets non visibles, donc il
        # ne tire pas depuis les autres pages du QStackedWidget de la fenêtre.
        self._paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        self._paste_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._paste_shortcut.activated.connect(self._on_paste_document)

        # Deliverables panel
        self._deliverables_panel = ProjectDeliverablesPanel(self._deliverable_repo, self._tmpl_repo)
        self._deliverables_panel.deliverable_edit_requested.connect(self.deliverable_edit_requested)

        # Stacked content + vertical tab bar
        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(notes_content)           # index 0
        self._right_stack.addWidget(self._deliverables_panel) # index 1

        right_tab_bar = _VerticalTabBar(["Notes", "Deliverables"])
        right_tab_bar.tab_changed.connect(self._right_stack.setCurrentIndex)

        right_panel = QWidget()
        right_panel_layout = QHBoxLayout(right_panel)
        right_panel_layout.setContentsMargins(0, 0, 0, 0)
        right_panel_layout.setSpacing(0)
        right_panel_layout.addWidget(self._right_stack, stretch=1)
        right_panel_layout.addWidget(right_tab_bar)

        # ── Horizontal splitter holding both panels ───────────────────────
        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(tasks_panel)
        h_splitter.addWidget(right_panel)
        h_splitter.setStretchFactor(0, 3)
        h_splitter.setStretchFactor(1, 2)
        h_splitter.setHandleWidth(16)
        content_layout.addWidget(h_splitter, stretch=1)

        # --- Stack ---
        self._stack = QStackedWidget()
        self._stack.addWidget(empty_label)  # index 0
        self._stack.addWidget(content)      # index 1

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self._stack)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._desc_text.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and self._desc_text.isReadOnly():
                self._enter_desc_edit()
                return True
        if obj is self._desc_text:
            if event.type() == QEvent.Type.FocusOut and not self._desc_text.isReadOnly():
                self._save_and_render_desc()
        return super().eventFilter(obj, event)

    def _enter_desc_edit(self) -> None:
        self._desc_text.setFrameShape(QFrame.Shape.StyledPanel)
        self._desc_text.setReadOnly(False)
        self._desc_text.setPlainText(self._desc_raw)
        self._desc_text.viewport().unsetCursor()
        self._desc_text.moveCursor(QTextCursor.MoveOperation.End)
        self._desc_text.setFocus()

    def _save_and_render_desc(self) -> None:
        if self._current_project is None:
            return
        self._desc_raw = self._desc_text.toPlainText()
        self._current_project.description = self._desc_raw
        self._project_repo.update(self._current_project)
        if self._desc_raw:
            self._desc_text.setMarkdown(self._desc_raw)
        else:
            self._desc_text.setPlainText("")
        self._desc_text.setReadOnly(True)
        self._desc_text.setFrameShape(QFrame.Shape.NoFrame)
        self._desc_text.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def _pick_color(self) -> None:
        if self._current_project is None:
            return
        initial = QColor(self._current_project.color) if self._current_project.color else QColor()
        chosen = QColorDialog.getColor(initial=initial, parent=self)
        if chosen.isValid():
            self._current_project.color = chosen.name()
            self._project_repo.update(self._current_project)
            self._color_btn.setStyleSheet(
                f"background-color: {self._current_project.color}; border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px; padding: 0; min-height: 0;"
            )
            self.project_renamed.emit()

    def _on_purge(self) -> None:
        if self._current_project_id is None:
            return
        if not ConfirmDialog.ask(
            "Purge completed tasks",
            "Archive all completed tasks in this project?",
            self,
        ):
            return
        tasks = self._task_repo.list_for_project(self._current_project_id)
        for task in tasks:
            if task.state == TaskState.Completed and not task.archived:
                task.archived = True
                self._task_repo.update(task)
        self._load_tasks(self._current_project_id)

    def _on_archive_changed(self) -> None:
        if self._current_project is None:
            return
        self._current_project.archived = self._archive_cb.isChecked()
        self._project_repo.update(self._current_project)
        self.project_renamed.emit()

    def _save_name(self) -> None:
        if self._current_project is None:
            return
        new_name = self._name_label.text().strip()
        if not new_name:
            self._name_label.setText(self._current_project.name)
            return
        if new_name == self._current_project.name:
            return
        self._current_project.name = new_name
        self._project_repo.update(self._current_project)
        self.project_renamed.emit()

    def _on_desc_toggled(self, expanded: bool) -> None:
        self._desc_text.setVisible(expanded)
        self._desc_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _on_view_changed(self, index: int) -> None:
        self._task_view_stack.setCurrentIndex(index)
        if self._prefs is not None and self._current_project_id is not None:
            self._prefs.set_project_view(self._current_project_id, index)
            self._prefs.save()

    def _load_tasks(self, project_id: int) -> None:
        tasks = [t for t in self._task_repo.list_for_project(project_id) if not t.archived]
        self._populate_table(tasks)
        project_colors = {project_id: self._current_project.color} if self._current_project else None
        self._kanban_board.populate(tasks, project_colors=project_colors, subtask_repo=self._subtask_repo)

    def _populate_table(self, tasks: list) -> None:
        self._task_table.setRowCount(0)
        self._task_table.setRowCount(len(tasks))
        for i, task in enumerate(tasks):
            title_item = QTableWidgetItem(task.title)
            title_item.setData(Qt.ItemDataRole.UserRole, task.id)
            self._task_table.setItem(i, 0, title_item)
            self._task_table.setItem(i, 1, QTableWidgetItem(task.state.value))
            self._task_table.setItem(i, 2, QTableWidgetItem(task.priority.value))
            self._task_table.setItem(i, 3, QTableWidgetItem(task.bucket.value))

    def _on_task_double_clicked(self, row: int, _col: int) -> None:
        task_id = self._task_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        task = self._task_repo.get(task_id)
        if task is None:
            return
        dialog = TaskDetailDialog(task, self._subtask_repo, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            task.title = dialog.title()
            task.description = dialog.description()
            task.state = dialog.state()
            task.priority = dialog.priority()
            task.bucket = dialog.bucket()
            task.archived = dialog.archived()
            self._task_repo.update(task)
            self._load_tasks(self._current_project_id)

    def open_task(self, task_id: int) -> None:
        self._on_kanban_task_edit_requested(task_id)

    def _on_kanban_task_edit_requested(self, task_id: int) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        dialog = TaskDetailDialog(task, self._subtask_repo, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            task.title = dialog.title()
            task.description = dialog.description()
            task.state = dialog.state()
            task.priority = dialog.priority()
            task.bucket = dialog.bucket()
            task.archived = dialog.archived()
            self._task_repo.update(task)
            self._load_tasks(self._current_project_id)

    def _on_kanban_tasks_reordered(self, bucket, task_ids: list[int]) -> None:
        self._task_repo.set_order_for_bucket(bucket, task_ids)

    def _on_kanban_bucket_changed(self, task_id: int, new_bucket) -> None:
        task = self._task_repo.get(task_id)
        if task is None:
            return
        prev_bucket = task.bucket
        task.bucket = new_bucket
        if new_bucket == TaskBucket.Completed:
            task.state = TaskState.Completed
        elif new_bucket == TaskBucket.On_Hold:
            task.state = TaskState.On_Hold
        elif new_bucket in (TaskBucket.Inbox, TaskBucket.Today) and prev_bucket in (TaskBucket.Completed, TaskBucket.On_Hold):
            task.state = TaskState.In_Progress
        self._task_repo.update(task)
        self._load_tasks(self._current_project_id)

    def _on_move_up(self) -> None:
        self._on_move(-1)

    def _on_move_down(self) -> None:
        self._on_move(1)

    def _on_move(self, direction: int) -> None:
        if self._current_project_id is None:
            return
        if self._task_view_stack.currentIndex() == 0:  # List view
            row = self._task_table.currentRow()
            if row < 0:
                return
            task_id = self._task_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        else:  # Board view
            task_id = self._kanban_board.selected_task_id()
            if task_id is None:
                return
        task = self._task_repo.get(task_id)
        if task is None:
            return
        bucket_tasks = [
            t for t in self._task_repo.list_for_project(self._current_project_id)
            if t.bucket == task.bucket
        ]
        idx = next((i for i, t in enumerate(bucket_tasks) if t.id == task_id), None)
        if idx is None:
            return
        neighbor_idx = idx + direction
        if not (0 <= neighbor_idx < len(bucket_tasks)):
            return
        self._task_repo.swap_order(task_id, bucket_tasks[neighbor_idx].id)
        self._load_tasks(self._current_project_id)

    def _on_new_task(self) -> None:
        if self._current_project_id is None:
            return
        dialog = NewTaskDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._task_repo.create(
                project_id=self._current_project_id,
                title=dialog.title(),
                description=dialog.description(),
                state=dialog.state(),
                priority=dialog.priority(),
                bucket=dialog.bucket(),
            )
            self._load_tasks(self._current_project_id)

    def _load_notes(self, project_id: int, select_document_id: int | None = None) -> None:
        self._note_tree.clear()
        self._note_selected_folder_id = None

        notes = [n for n in self._note_repo.list_all_for_project(project_id) if not n.archived]
        all_folders = self._folder_repo.list_for_project(project_id)
        notes_by_folder = self._index_notes_by_folder(notes)
        docs_by_folder = self._index_documents_by_folder(self._document_repo.list_for_project(project_id))
        self._build_note_folder_subtree(None, all_folders, None, notes_by_folder, docs_by_folder)

        if select_document_id is not None:
            self._select_document_item(select_document_id)

    def _select_document_item(self, document_id: int) -> None:
        """Resélectionne un document après reconstruction de l'arbre.

        `_load_notes` repart de zéro et remet `_note_selected_folder_id` à None :
        sans cela, deux collages successifs sans reclic mettraient le second à la
        racine. Resélectionner restaure la cible via `currentItemChanged` et
        montre à l'utilisateur ce qui vient d'être ajouté."""
        iterator = QTreeWidgetItemIterator(self._note_tree)
        while iterator.value():
            item = iterator.value()
            if (
                item.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_DOCUMENT
                and item.data(0, _NOTE_NODE_DATA_ROLE) == document_id
            ):
                self._note_tree.setCurrentItem(item)
                self._note_tree.scrollToItem(item)
                return
            iterator += 1

    def _index_notes_by_folder(self, notes) -> dict:
        index: dict = {}
        for note in notes:
            index.setdefault(note.folder_id, []).append(note)
        return index

    def _index_documents_by_folder(self, documents) -> dict:
        index: dict = {}
        for document in documents:
            index.setdefault(document.folder_id, []).append(document)
        return index

    def _build_note_folder_subtree(self, parent_item, all_folders, parent_id, notes_by_folder, docs_by_folder) -> None:
        children = sorted(
            [f for f in all_folders if f.parent_id == parent_id],
            key=lambda f: f.name.lower(),
        )
        for folder in children:
            if parent_item is None:
                folder_item = QTreeWidgetItem(self._note_tree)
            else:
                folder_item = QTreeWidgetItem(parent_item)
            folder_item.setText(0, folder.name)
            folder_item.setIcon(0, _folder_icon())
            folder_item.setForeground(0, QBrush(QColor(_NOTES_FOLDER_TEXT)))
            folder_item.setData(0, _NOTE_NODE_DATA_ROLE, folder.id)
            folder_item.setData(0, _NOTE_NODE_TYPE_ROLE, _NOTE_NODE_TYPE_FOLDER)
            if self._prefs is not None and self._current_project_id is not None:
                folder_item.setExpanded(self._prefs.get_folder_expanded(self._current_project_id, folder.id))
            else:
                folder_item.setExpanded(True)

            self._build_note_folder_subtree(folder_item, all_folders, folder.id, notes_by_folder, docs_by_folder)

            for note in sorted(notes_by_folder.get(folder.id, []), key=lambda n: n.title.lower()):
                self._make_note_tree_item(folder_item, note)
            for document in sorted(docs_by_folder.get(folder.id, []), key=lambda d: d.name.lower()):
                self._make_document_tree_item(folder_item, document)

        if parent_id is None:
            for note in sorted(notes_by_folder.get(None, []), key=lambda n: n.title.lower()):
                self._make_note_tree_item(None, note)
            for document in sorted(docs_by_folder.get(None, []), key=lambda d: d.name.lower()):
                self._make_document_tree_item(None, document)

    def _make_note_tree_item(self, parent, note) -> QTreeWidgetItem:
        if parent is None:
            item = QTreeWidgetItem(self._note_tree)
        else:
            item = QTreeWidgetItem(parent)
        item.setText(0, note.title)
        item.setForeground(0, QBrush(QColor(_NOTES_NOTE_TEXT)))
        item.setData(0, _NOTE_NODE_DATA_ROLE, note.id)
        item.setData(0, _NOTE_NODE_TYPE_ROLE, _NOTE_NODE_TYPE_NOTE)
        item.setData(0, _NOTE_NODE_FOLDER_ROLE, note.folder_id)
        return item

    def _make_document_tree_item(self, parent, document) -> QTreeWidgetItem:
        if parent is None:
            item = QTreeWidgetItem(self._note_tree)
        else:
            item = QTreeWidgetItem(parent)
        item.setText(0, document.name)
        item.setIcon(0, _document_icon())
        item.setToolTip(0, document.url)
        item.setForeground(0, QBrush(QColor(_NOTES_NOTE_TEXT)))
        item.setData(0, _NOTE_NODE_DATA_ROLE, document.id)
        item.setData(0, _NOTE_NODE_TYPE_ROLE, _NOTE_NODE_TYPE_DOCUMENT)
        item.setData(0, _NOTE_NODE_FOLDER_ROLE, document.folder_id)
        item.setData(0, _NOTE_NODE_URL_ROLE, document.url)
        return item

    def _on_folder_expanded(self, item) -> None:
        if item.data(0, _NOTE_NODE_TYPE_ROLE) != _NOTE_NODE_TYPE_FOLDER:
            return
        if self._prefs is not None and self._current_project_id is not None:
            self._prefs.set_folder_expanded(self._current_project_id, item.data(0, _NOTE_NODE_DATA_ROLE), True)

    def _on_folder_collapsed(self, item) -> None:
        if item.data(0, _NOTE_NODE_TYPE_ROLE) != _NOTE_NODE_TYPE_FOLDER:
            return
        if self._prefs is not None and self._current_project_id is not None:
            self._prefs.set_folder_expanded(self._current_project_id, item.data(0, _NOTE_NODE_DATA_ROLE), False)

    def _on_note_selection_changed(self, current, _previous) -> None:
        if current is None:
            self._note_selected_folder_id = None
            return
        node_type = current.data(0, _NOTE_NODE_TYPE_ROLE)
        if node_type == _NOTE_NODE_TYPE_FOLDER:
            self._note_selected_folder_id = current.data(0, _NOTE_NODE_DATA_ROLE)
        elif node_type in (_NOTE_NODE_TYPE_NOTE, _NOTE_NODE_TYPE_DOCUMENT):
            self._note_selected_folder_id = current.data(0, _NOTE_NODE_FOLDER_ROLE)

    def _on_note_item_double_clicked(self, item, _col) -> None:
        node_type = item.data(0, _NOTE_NODE_TYPE_ROLE)
        if node_type == _NOTE_NODE_TYPE_NOTE:
            self.note_edit_requested.emit(item.data(0, _NOTE_NODE_DATA_ROLE))
        elif node_type == _NOTE_NODE_TYPE_DOCUMENT:
            self.document_open_requested.emit(item.data(0, _NOTE_NODE_URL_ROLE))

    def _on_notes_context_menu(self, pos) -> None:
        item = self._note_tree.itemAt(pos)
        if item is None:
            return
        if item.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_DOCUMENT:
            self._show_document_context_menu(item, pos)
            return
        if item.data(0, _NOTE_NODE_TYPE_ROLE) != _NOTE_NODE_TYPE_FOLDER:
            return
        menu = QMenu(self)
        rename_action = menu.addAction("Rename")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        chosen = menu.exec(self._note_tree.viewport().mapToGlobal(pos))
        if chosen is rename_action:
            self._rename_note_folder(item)
        elif chosen is delete_action:
            self._delete_note_folder(item)

    def _delete_note_folder(self, item) -> None:
        folder_id: int = item.data(0, _NOTE_NODE_DATA_ROLE)
        folder_name: str = item.text(0)
        if ConfirmDialog.ask(
            "Delete Folder",
            f"Delete folder \"{folder_name}\"?\n"
            "Sub-folders will also be deleted. Notes will be moved to the root.",
            self,
        ):
            self._folder_repo.delete(folder_id)
            self._load_notes(self._current_project_id)

    def _rename_note_folder(self, item) -> None:
        folder_id: int = item.data(0, _NOTE_NODE_DATA_ROLE)
        current_name: str = item.text(0)

        parent_item = item.parent()
        if parent_item is not None and parent_item.data(0, _NOTE_NODE_TYPE_ROLE) == _NOTE_NODE_TYPE_FOLDER:
            parent_id: int | None = parent_item.data(0, _NOTE_NODE_DATA_ROLE)
        else:
            parent_id = None

        dlg = NewFolderDialog(title="Rename Folder", initial_name=current_name, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = dlg.name()
        if new_name == current_name:
            return

        if self._folder_repo.exists_with_name(self._current_project_id, parent_id, new_name):
            AlertDialog.warn("Duplicate Name", f'A folder named "{new_name}" already exists at this level.', self)
            return

        self._folder_repo.rename(folder_id, new_name)
        self._load_notes(self._current_project_id)

    def _on_note_moved(self, note_id: int, new_folder_id) -> None:
        note = self._note_repo.get(note_id)
        if note is None:
            return
        note.folder_id = new_folder_id
        self._note_repo.update(note)
        self._load_notes(self._current_project_id)

    # ── Documents ─────────────────────────────────────────────────────────
    def _on_document_moved(self, document_id: int, new_folder_id) -> None:
        self._document_repo.move(document_id, new_folder_id)
        self._load_notes(self._current_project_id, select_document_id=document_id)

    def _on_document_dropped(self, name: str, url: str, folder_id) -> None:
        """Lien déposé sur l'arbre depuis une application externe."""
        self._create_document(name, url, folder_id)

    def _on_paste_document(self) -> None:
        """Ctrl+V sur la page projet : crée un document depuis le presse-papiers.

        Le raccourci étant en contexte fenêtre, il faut rendre la main aux champs
        éditables de la page pour ne pas leur voler leur collage."""
        if self._current_project_id is None:
            return
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit)):
            focused.paste()
            return

        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return
        link = extract_document_link(
            mime.html() if mime.hasHtml() else None,
            mime.text() if mime.hasText() else None,
            [u.toString() for u in mime.urls()] if mime.hasUrls() else [],
        )
        if link is None:
            return
        name, url = link
        self._create_document(name, url, self._note_selected_folder_id)

    def _create_document(self, name: str, url: str, folder_id) -> None:
        if self._current_project_id is None:
            return
        document = self._document_repo.create(
            project_id=self._current_project_id,
            name=name,
            url=url,
            folder_id=folder_id,
        )
        self._load_notes(self._current_project_id, select_document_id=document.id)

    def _show_document_context_menu(self, item, pos) -> None:
        menu = QMenu(self)
        open_action = menu.addAction("Open")
        rename_action = menu.addAction("Rename")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        chosen = menu.exec(self._note_tree.viewport().mapToGlobal(pos))
        if chosen is open_action:
            self.document_open_requested.emit(item.data(0, _NOTE_NODE_URL_ROLE))
        elif chosen is rename_action:
            self._rename_document(item)
        elif chosen is delete_action:
            self._delete_document(item)

    def _rename_document(self, item) -> None:
        document_id: int = item.data(0, _NOTE_NODE_DATA_ROLE)
        current_name: str = item.text(0)
        dlg = NewFolderDialog(title="Rename Document", initial_name=current_name, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dlg.name()
        if not new_name or new_name == current_name:
            return
        self._document_repo.rename(document_id, new_name)
        self._load_notes(self._current_project_id, select_document_id=document_id)

    def _delete_document(self, item) -> None:
        document_id: int = item.data(0, _NOTE_NODE_DATA_ROLE)
        name: str = item.text(0)
        if ConfirmDialog.ask(
            "Delete Document",
            f'Delete document "{name}"?\nOnly the link is removed; the file itself is untouched.',
            self,
        ):
            self._document_repo.delete(document_id)
            self._load_notes(self._current_project_id)

    def _on_folder_moved(self, folder_id: int, new_parent_id) -> None:
        if self._current_project_id is None:
            return
        folders = self._folder_repo.list_for_project(self._current_project_id)
        folder = next((f for f in folders if f.id == folder_id), None)
        if folder is None:
            return
        if self._folder_repo.exists_with_name(self._current_project_id, new_parent_id, folder.name):
            AlertDialog.warn(
                "Duplicate Name",
                f'A folder named "{folder.name}" already exists at the destination.',
                self,
            )
            return
        self._folder_repo.move(folder_id, new_parent_id)
        self._load_notes(self._current_project_id)

    def _on_new_folder(self) -> None:
        if self._current_project_id is None:
            return

        dlg = NewFolderDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        name = dlg.name()
        if self._folder_repo.exists_with_name(self._current_project_id, self._note_selected_folder_id, name):
            AlertDialog.warn("Duplicate Name", f'A folder named "{name}" already exists at this level.', self)
            return

        self._folder_repo.create(self._current_project_id, name, self._note_selected_folder_id)
        self._load_notes(self._current_project_id)

    def _on_new_note(self) -> None:
        if self._current_project_id is None:
            return
        note = self._note_repo.create(
            project_id=self._current_project_id,
            title="New Note",
            folder_id=self._note_selected_folder_id,
        )
        self._load_notes(self._current_project_id)
        self.note_edit_requested.emit(note.id)

    def load_project(self, project) -> None:
        if project is None:
            self._current_project = None
            self._current_project_id = None
            self._stack.setCurrentIndex(0)
        else:
            self._current_project = project
            self._current_project_id = project.id
            self._name_label.setText(project.name)
            self._archive_cb.setChecked(project.archived)
            if project.color:
                self._color_btn.setStyleSheet(
                    f"background-color: {project.color}; border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px; padding: 0; min-height: 0;"
                )
            else:
                self._color_btn.setStyleSheet(f"border: 1px solid {_theme.current().color_btn_border}; border-radius: 3px; padding: 0; min-height: 0;")
            self._desc_raw = project.description
            if self._desc_raw:
                self._desc_text.setMarkdown(self._desc_raw)
            else:
                self._desc_text.setPlainText("")
            self._desc_text.setReadOnly(True)
            self._desc_text.setFrameShape(QFrame.Shape.NoFrame)
            self._load_tasks(project.id)
            self._load_notes(project.id)
            self._deliverables_panel.load(project.id)
            if self._prefs is not None:
                view_index = self._prefs.get_project_view(project.id)
                self._view_selector.blockSignals(True)
                self._view_selector.setCurrentIndex(view_index)
                self._view_selector.blockSignals(False)
                self._task_view_stack.setCurrentIndex(view_index)
            self._stack.setCurrentIndex(1)
