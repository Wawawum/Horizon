import json
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Theme:
    name: str
    font_family: str
    accent_color: str
    # ── App-level surfaces ────────────────────────────────────────────────
    app_bg: str           # fenêtre principale, dialogs
    surface_bg: str       # panneaux, listes, tables, champs
    surface_alt_bg: str   # en-têtes de colonnes, lignes alternées
    text: str             # texte principal
    border: str           # bordures, séparateurs
    # ── Champs de saisie ──────────────────────────────────────────────────
    input_bg: str
    # ── Boutons ───────────────────────────────────────────────────────────
    button_bg: str
    button_hover: str
    button_pressed: str
    # ── Scrollbars ────────────────────────────────────────────────────────
    scrollbar_bg: str
    scrollbar_handle: str
    scrollbar_handle_hover: str
    # ── Sélection dans les listes ─────────────────────────────────────────
    list_selected_bg: str
    list_selected_text: str
    # ── Tuiles Kanban ─────────────────────────────────────────────────────
    tile_bg: str
    tile_border: str
    tile_text: str
    tile_checkbox_border: str
    tile_checkbox_checked_bg: str
    tile_checkbox_checked_border: str
    tile_project_label: str
    # ── Priorités ─────────────────────────────────────────────────────────
    priority_low: str
    priority_medium: str
    priority_high: str
    # ── Calendrier ────────────────────────────────────────────────────────
    calendar_bg: str
    calendar_label: str
    calendar_hour_line: str
    calendar_half_hour_line: str
    calendar_event_bg: str
    calendar_event_text: str
    calendar_now_line: str
    # ── Horloge analogique ────────────────────────────────────────────────
    clock_face: str
    clock_ring: str
    clock_tick_hour: str
    clock_tick_minute: str
    clock_hand: str
    clock_second: str
    # ── Bouton couleur ────────────────────────────────────────────────────
    color_btn_border: str
    # ── Bouton supprimer ──────────────────────────────────────────────────
    delete_btn_text: str
    delete_btn_bg: str
    # ── Nav buttons gradient ──────────────────────────────────────────────
    nav_btn_gradient_from: str   # start color (left) for hover/active bg
    nav_btn_gradient_to: str     # end color (right) for hover/active bg
    # ── Aperçu Markdown ───────────────────────────────────────────────────
    preview_text: str
    preview_bg: str
    preview_border: str
    preview_code_bg: str
    preview_blockquote_border: str
    preview_blockquote_bg: str
    preview_blockquote_text: str
    preview_link: str
    preview_table_header_bg: str
    # ── Montre G-Shock ────────────────────────────────────────────────────
    gshock_case: str        = field(default="#1c1c1c")
    gshock_case_shadow: str = field(default="#0a0a0a")
    gshock_bezel: str       = field(default="#2a2a2a")
    gshock_lcd_bg: str      = field(default="#0d1a0d")
    gshock_lcd_fg: str      = field(default="#4de8c2")
    gshock_lcd_dim: str     = field(default="#0e1e10")
    gshock_lcd_label: str   = field(default="#3ab89a")
    gshock_lcd_alarm: str   = field(default="#c87820")
    gshock_screw: str       = field(default="#383838")
    # ── Barre de titre (indépendante du thème clair/sombre général) ────────
    titlebar_bg: str          = field(default="#0d1421")
    titlebar_border: str      = field(default="#1c2940")
    titlebar_text: str        = field(default="#e8edf5")
    titlebar_muted: str       = field(default="#5b6b85")
    titlebar_muted_hover: str = field(default="#8fa3c0")
    titlebar_accent: str      = field(default="#4fc3f7")
    titlebar_input_bg: str    = field(default="#101a2c")
    clock_live_dot: str       = field(default="#34d399")
    # ── Liste de projets : item sélectionné ─────────────────────────────────
    list_selected_accent: str       = field(default="#2dd4bf")
    project_list_selected_bg: str   = field(default="#d8e6fb")


_current: Theme | None = None
_THEME_DIR = Path(__file__).parent / "themes"
_FIELD_NAMES = {f.name for f in fields(Theme)}


def load() -> Theme:
    path = _THEME_DIR / "terminal.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Theme(**{k: v for k, v in data.items() if k in _FIELD_NAMES})


def init() -> None:
    global _current
    _current = load()


def current() -> Theme:
    if _current is None:
        raise RuntimeError("theme.init() has not been called")
    return _current


def make_icon(resource_path: str, size: "QSize") -> "QIcon":
    from PySide6.QtCore import QFile, QIODevice, QByteArray, Qt
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtGui import QPixmap, QPainter, QIcon

    f = QFile(resource_path)
    f.open(QIODevice.OpenModeFlag.ReadOnly)
    svg = bytes(f.readAll()).decode("utf-8")
    f.close()
    svg = svg.replace("#5ef2ff", current().accent_color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


_RESOURCES_DIR = Path(__file__).parent / "resources"


def _hex_to_rgba(hex_color: str, alpha: int) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def make_stylesheet(t: Theme) -> str:
    """Génère le QSS global à appliquer sur QApplication."""
    arrow_svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 6">'
        f'<path d="M1 1L5 5L9 1" fill="none" stroke="{t.text}"'
        f' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )
    arrow_path = _RESOURCES_DIR / "combo_arrow.svg"
    arrow_path.write_text(arrow_svg, encoding="utf-8")
    arrow_url = arrow_path.as_posix()

    (_RESOURCES_DIR / "arrow_up.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<path d="M1 7L5 3L9 7" fill="none" stroke="{t.priority_medium}"'
        f' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>',
        encoding="utf-8",
    )
    (_RESOURCES_DIR / "arrow_down.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<path d="M1 3L5 7L9 3" fill="none" stroke="{t.priority_medium}"'
        f' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>',
        encoding="utf-8",
    )
    return f"""
/* ── Base ──────────────────────────────────────────────────────────── */
QWidget {{
    background-color: {t.app_bg};
    color: {t.text};
}}
QMainWindow, QDialog {{
    background-color: {t.app_bg};
}}

/* ── Group boxes (Tasks / Notes panels) ─────────────────────────── */
QGroupBox {{
    border: 1px solid {t.border};
    border-radius: 2px;
    margin-top: 10px;
    padding-top: 4px;
    font-weight: bold;
    background-color: {t.surface_bg};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    background-color: {t.surface_bg};
    color: {t.text};
}}

/* ── Widgets transparents / pass-through ──────────────────────────── */
QLabel {{
    background-color: transparent;
}}
QCheckBox {{
    background-color: transparent;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {t.color_btn_border};
    border-radius: 3px;
    background-color: {t.input_bg};
}}
QCheckBox::indicator:checked {{
    background-color: {t.accent_color};
    border-color: {t.accent_color};
}}
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
QStackedWidget {{
    background-color: transparent;
}}

/* ── Barre de commandes (sous la barre de titre) ───────────────────── */
QWidget[command_bar="true"] {{
    background-color: #dde5f1;
    border-bottom: 1px solid {t.border};
}}

/* ── Nav buttons (Board / Notes) ───────────────────────────────────── */
QPushButton[nav_btn="true"] {{
    background-color: {t.button_bg};
    border: 1px solid {t.border};
    border-radius: 8px;
    min-height: 38px;
    color: transparent;
}}
QPushButton[nav_btn="true"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {t.nav_btn_gradient_from}, stop:1 {t.nav_btn_gradient_to});
    border-color: {t.scrollbar_handle_hover};
}}
QPushButton[nav_btn="true"]:checked {{
    background-color: {t.text};
    border-color: {t.text};
}}

/* ── Boutons ────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {t.button_bg};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 4px;
    padding: 4px 12px;
    min-height: 22px;
}}
QPushButton:hover {{
    background-color: {t.button_hover};
}}
QPushButton:pressed {{
    background-color: {t.button_pressed};
}}
QPushButton:disabled {{
    color: {t.scrollbar_handle};
}}
QToolButton {{
    background-color: {t.button_bg};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 3px;
    padding: 2px 6px;
}}
QToolButton:hover {{
    background-color: {t.button_hover};
}}
QToolButton:pressed, QToolButton:checked {{
    background-color: {t.button_pressed};
}}

/* ── Champs de saisie ───────────────────────────────────────────────── */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {t.input_bg};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 3px;
    padding: 2px 4px;
    selection-background-color: {t.list_selected_bg};
    selection-color: {t.list_selected_text};
}}

/* ── Liste déroulante ───────────────────────────────────────────────── */
QComboBox {{
    background-color: {t.input_bg};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 3px;
    padding: 2px 8px 2px 4px;
    min-height: 22px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {t.border};
    border-radius: 0 3px 3px 0;
}}
QComboBox::down-arrow {{
    image: url({arrow_url});
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {t.surface_bg};
    color: {t.text};
    border: 1px solid {t.border};
    selection-background-color: {t.list_selected_bg};
    selection-color: {t.list_selected_text};
    outline: none;
}}

/* ── Listes ─────────────────────────────────────────────────────────── */
QListWidget, QListView {{
    background-color: {t.surface_bg};
    color: {t.text};
    border: 1px solid {t.border};
    outline: none;
}}
QListWidget::item {{
    padding: 2px 0;
}}
QListWidget::item:selected, QListView::item:selected {{
    background-color: {t.list_selected_bg};
    color: {t.list_selected_text};
    border-left: 3px solid {t.accent_color};
}}
QListWidget::item:hover:!selected, QListView::item:hover:!selected {{
    background-color: {t.button_hover};
}}

/* ── Tables ─────────────────────────────────────────────────────────── */
QTableWidget, QTableView {{
    background-color: {t.surface_bg};
    color: {t.text};
    gridline-color: {t.border};
    border: 1px solid {t.border};
    outline: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {t.list_selected_bg};
    color: {t.list_selected_text};
    border-left: 3px solid {t.accent_color};
}}
QHeaderView {{
    background-color: {t.surface_alt_bg};
    border: none;
}}
QHeaderView::section {{
    background-color: {t.surface_alt_bg};
    color: {t.text};
    border: none;
    border-right: 1px solid {t.border};
    border-bottom: 1px solid {t.border};
    padding: 4px 8px;
}}
QHeaderView::section:last {{
    border-right: none;
}}
QTableCornerButton::section {{
    background-color: {t.surface_alt_bg};
    border: 1px solid {t.border};
}}

/* ── Séparateurs QFrame ─────────────────────────────────────────────── */
QFrame[frameShape="4"] {{
    background-color: {t.border};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QFrame[frameShape="5"] {{
    background-color: {t.border};
    border: none;
    max-width: 1px;
    min-width: 1px;
}}

/* ── Splitter ────────────────────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {t.border};
}}
QSplitter::handle:horizontal {{
    background-color: {t.app_bg};
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

/* ── Scrollbars ─────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background-color: {t.scrollbar_bg};
    width: 10px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {t.scrollbar_handle};
    min-height: 24px;
    border-radius: 5px;
    margin: 2px 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {t.scrollbar_handle_hover};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background-color: {t.scrollbar_bg};
    height: 10px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {t.scrollbar_handle};
    min-width: 24px;
    border-radius: 5px;
    margin: 2px 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {t.scrollbar_handle_hover};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* ── Menu contextuel ────────────────────────────────────────────────── */
QMenu {{
    background-color: {t.surface_bg};
    color: {t.text};
    border: 1px solid {t.border};
    padding: 2px 0;
}}
QMenu::item {{
    padding: 4px 24px 4px 12px;
    background-color: transparent;
}}
QMenu::item:selected {{
    background-color: {t.list_selected_bg};
    color: {t.list_selected_text};
}}
QMenu::separator {{
    height: 1px;
    background-color: {t.border};
    margin: 2px 6px;
}}

/* ── Tooltip ────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {t.surface_alt_bg};
    color: {t.text};
    border: 1px solid {t.border};
    padding: 2px 6px;
}}

/* ── Boutons OK / Cancel ─────────────────────────────────────────────── */
QDialogButtonBox QPushButton {{
    font-weight: bold;
}}
QPushButton:default {{
    color: {t.accent_color};
}}

/* ── Boîte de message ───────────────────────────────────────────────── */
QMessageBox {{
    background-color: {t.app_bg};
}}
QMessageBox QLabel {{
    color: {t.text};
    background-color: transparent;
}}

/* ── Barre de titre personnalisée (toujours sombre) ─────────────────── */
QWidget[titlebar="true"] {{
    background-color: {t.titlebar_bg};
    border-bottom: 1px solid {t.titlebar_border};
}}

QPushButton[title_btn="min"],
QPushButton[title_btn="max"],
QPushButton[title_btn="close"] {{
    background-color: transparent;
    border: none;
    border-radius: 0;
    color: {t.titlebar_muted};
    font-size: 14px;
    min-width: 46px;
    max-width: 46px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
}}
QPushButton[title_btn="min"]:hover,
QPushButton[title_btn="max"]:hover {{
    background-color: {_hex_to_rgba(t.titlebar_accent, 25)};
    color: {t.titlebar_accent};
}}
QPushButton[title_btn="close"]:hover {{
    background-color: {_hex_to_rgba(t.priority_high, 30)};
    color: {t.priority_high};
}}
QPushButton[title_btn="min"]:pressed,
QPushButton[title_btn="max"]:pressed {{
    background-color: {_hex_to_rgba(t.titlebar_accent, 50)};
}}
QPushButton[title_btn="close"]:pressed {{
    background-color: {_hex_to_rgba(t.priority_high, 60)};
}}
"""
