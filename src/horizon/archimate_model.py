"""Lecture des fichiers `.archimate` (format XML de l'outil Archi).

Ce module ne contient **aucune dépendance Qt** : il transforme un fichier en un
graphe de dataclasses (`ArchimateModel`), que `widgets/archimate_canvas.py` sait
ensuite peindre. Il peut donc être exercé sans `QApplication`.

Deux graphes distincts cohabitent dans le format et ne doivent jamais être
confondus :

* le **modèle** — `Concept` et `Relationship`, dont les `source`/`target`
  désignent des identifiants de concepts ;
* le **diagramme** — `DiagramNode` et `DiagramConnection`, dont les
  `source`/`target` désignent des identifiants d'objets de diagramme.

Le pont entre les deux est l'attribut `archimateElement` (nœuds) et
`archimateRelationship` (connexions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# Taille de repli quand `bounds` est absent ou porte -1 (Archi omet les valeurs
# par défaut EMF). Ce sont les tailles par défaut de l'outil.
_DEFAULT_SIZE = (120, 55)
_DEFAULT_CONTAINER_SIZE = (185, 80)
_CONTAINER_KINDS = frozenset({"Note", "Group", "Container"})

# Les modèles antérieurs à Archi 4.6 emploient des noms de classes plus longs
# pour les mêmes objets : on normalise vers les noms modernes.
_KIND_ALIASES = {
    "ArchimateDiagramObject": "DiagramObject",
    "ArchimateDiagramConnection": "Connection",
    "DiagramModelArchimateObject": "DiagramObject",
    "DiagramModelArchimateConnection": "Connection",
    "DiagramModelNote": "Note",
    "DiagramModelGroup": "Group",
    "DiagramModelConnection": "Connection",
}

_VIEW_TYPES = frozenset({"ArchimateDiagramModel"})
# Vues non-ArchiMate d'Archi : reconnues pour être signalées, jamais rendues.
_UNSUPPORTED_VIEW_TYPES = frozenset({"SketchModel", "CanvasModel"})


class ArchimateParseError(Exception):
    """Fichier illisible : absent, XML invalide, ou racine inattendue."""


@dataclass
class Concept:
    """Élément du modèle (`ApplicationComponent`, `BusinessActor`, ...)."""

    id: str
    type: str
    name: str = ""
    documentation: str = ""


@dataclass
class Relationship:
    """Relation du modèle. `source`/`target` sont des ids de *concepts*."""

    id: str
    type: str
    source: str
    target: str
    name: str = ""
    documentation: str = ""
    access_type: int = 0
    strength: str = ""
    directed: bool = False


@dataclass
class DiagramNode:
    """Objet posé sur une vue. Les coordonnées sont **absolues** (les offsets
    des conteneurs parents ont déjà été accumulés au parsing)."""

    id: str
    kind: str
    x: int
    y: int
    width: int
    height: int
    concept: Concept | None = None
    label: str = ""
    fill_color: str | None = None
    line_color: str | None = None
    font_color: str | None = None
    font_family: str | None = None
    font_size: float | None = None
    bold: bool = False
    italic: bool = False
    text_position: int = 0
    text_alignment: int = 0
    figure_type: int = 0
    border_type: int = 0
    ref_view_id: str | None = None
    depth: int = 0
    children: list["DiagramNode"] = field(default_factory=list)

    @property
    def element_type(self) -> str:
        """Type ArchiMate du concept représenté, ou le type visuel à défaut."""
        return self.concept.type if self.concept is not None else self.kind


@dataclass
class DiagramConnection:
    """Trait posé sur une vue. `source`/`target` sont des ids d'*objets de
    diagramme*, jamais de concepts."""

    id: str
    source: str
    target: str
    relationship: Relationship | None = None
    label: str = ""
    line_color: str | None = None
    line_width: int = 1
    font_color: str | None = None
    # Offsets Archi (startX, startY, endX, endY), relatifs au centre de chaque
    # extrémité. Seuls les offsets « start » servent au tracé.
    bendpoints: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def relation_type(self) -> str:
        return self.relationship.type if self.relationship is not None else ""


@dataclass
class ArchimateView:
    id: str
    name: str
    folder_path: tuple[str, ...] = ()
    nodes: list[DiagramNode] = field(default_factory=list)
    connections: list[DiagramConnection] = field(default_factory=list)
    nodes_by_id: dict[str, DiagramNode] = field(default_factory=dict)
    documentation: str = ""


@dataclass
class ArchimateModel:
    id: str
    name: str
    version: str = ""
    path: str = ""
    concepts: dict[str, Concept] = field(default_factory=dict)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    views: list[ArchimateView] = field(default_factory=list)
    # Noms des vues Sketch/Canvas ignorées, pour information dans l'UI.
    unsupported_views: list[str] = field(default_factory=list)


# ── Helpers de bas niveau ────────────────────────────────────────────────────


def _local_type(el: ET.Element) -> str:
    """`xsi:type="archimate:DiagramObject"` → `"DiagramObject"`."""
    return el.get(_XSI_TYPE, "").split(":", 1)[-1]


def _int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _documentation(el: ET.Element) -> str:
    """La documentation est tantôt un attribut, tantôt un élément enfant."""
    attr = el.get("documentation")
    if attr:
        return attr
    child = el.find("documentation")
    if child is not None and child.text:
        return child.text
    return ""


def _parse_font(raw: str | None) -> tuple[str | None, float | None, bool, bool]:
    """Décode une chaîne SWT `FontData` : `1|Segoe UI|9.0|1|WINDOWS|...`.

    Champs utiles : 1 = famille, 2 = taille, 3 = masque de style
    (bit 0 = gras, bit 1 = italique). Le reste est dépendant de la plateforme.
    """
    if not raw:
        return None, None, False, False
    parts = raw.split("|")
    family = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    size: float | None = None
    if len(parts) > 2:
        try:
            size = float(parts[2])
        except ValueError:
            size = None
    style = _int(parts[3], 0) if len(parts) > 3 else 0
    return family, size, bool(style & 1), bool(style & 2)


def _default_size(kind: str) -> tuple[int, int]:
    return _DEFAULT_CONTAINER_SIZE if kind in _CONTAINER_KINDS else _DEFAULT_SIZE


def _parse_bounds(child: ET.Element, kind: str) -> tuple[int, int, int, int]:
    """`<bounds>` est un élément *enfant* et emploie `width`/`height`.

    Archi omet les attributs valant zéro, et écrit -1 pour « taille par défaut ».
    """
    default_w, default_h = _default_size(kind)
    bounds = child.find("bounds")
    if bounds is None:
        return 0, 0, default_w, default_h
    width = _int(bounds.get("width"), -1)
    height = _int(bounds.get("height"), -1)
    return (
        _int(bounds.get("x"), 0),
        _int(bounds.get("y"), 0),
        width if width > 0 else default_w,
        height if height > 0 else default_h,
    )


# ── Parsing du diagramme ─────────────────────────────────────────────────────


def _parse_connection(el: ET.Element, source_id: str, relationships: dict[str, Relationship]) -> DiagramConnection:
    relationship = relationships.get(el.get("archimateRelationship", ""))
    bendpoints = [
        (
            _int(bp.get("startX"), 0),
            _int(bp.get("startY"), 0),
            _int(bp.get("endX"), 0),
            _int(bp.get("endY"), 0),
        )
        for bp in el.findall("bendpoint")
    ]
    label = el.get("name") or (relationship.name if relationship is not None else "")
    return DiagramConnection(
        id=el.get("id", ""),
        # `source` est redondant avec l'id du <child> englobant, mais un fichier
        # tronqué peut l'omettre : on retombe sur le parent.
        source=el.get("source") or source_id,
        target=el.get("target", ""),
        relationship=relationship,
        label=label,
        line_color=el.get("lineColor"),
        line_width=_int(el.get("lineWidth"), 1),
        font_color=el.get("fontColor"),
        bendpoints=bendpoints,
    )


def _parse_node(
    el: ET.Element,
    offset_x: int,
    offset_y: int,
    depth: int,
    concepts: dict[str, Concept],
    relationships: dict[str, Relationship],
    view: ArchimateView,
) -> DiagramNode:
    raw_kind = _local_type(el)
    kind = _KIND_ALIASES.get(raw_kind, raw_kind)
    x, y, width, height = _parse_bounds(el, kind)
    abs_x, abs_y = offset_x + x, offset_y + y

    concept = concepts.get(el.get("archimateElement", ""))
    if kind == "Note":
        content = el.find("content")
        label = content.text if content is not None and content.text else ""
    elif concept is not None:
        label = concept.name
    else:
        label = el.get("name", "")

    family, size, bold, italic = _parse_font(el.get("font"))
    node = DiagramNode(
        id=el.get("id", ""),
        kind=kind,
        x=abs_x,
        y=abs_y,
        width=width,
        height=height,
        concept=concept,
        label=label,
        fill_color=el.get("fillColor"),
        line_color=el.get("lineColor"),
        font_color=el.get("fontColor"),
        font_family=family,
        font_size=size,
        bold=bold,
        italic=italic,
        text_position=_int(el.get("textPosition"), 0),
        text_alignment=_int(el.get("textAlignment"), 0),
        figure_type=_int(el.get("type"), 0),
        border_type=_int(el.get("borderType"), 0),
        ref_view_id=el.get("model"),
        depth=depth,
    )
    view.nodes_by_id[node.id] = node

    for conn_el in el.findall("sourceConnection"):
        view.connections.append(_parse_connection(conn_el, node.id, relationships))

    # Les coordonnées des enfants sont relatives au conteneur : on propage
    # l'origine absolue courante.
    for sub in el.findall("child"):
        node.children.append(
            _parse_node(sub, abs_x, abs_y, depth + 1, concepts, relationships, view)
        )
    return node


def _parse_view(
    el: ET.Element,
    folder_path: tuple[str, ...],
    concepts: dict[str, Concept],
    relationships: dict[str, Relationship],
) -> ArchimateView:
    view = ArchimateView(
        id=el.get("id", ""),
        name=el.get("name") or "(untitled view)",
        folder_path=folder_path,
        documentation=_documentation(el),
    )
    for child in el.findall("child"):
        view.nodes.append(_parse_node(child, 0, 0, 0, concepts, relationships, view))
    return view


# ── Parsing du modèle ────────────────────────────────────────────────────────


def _index_folder(
    folder: ET.Element,
    folder_path: tuple[str, ...],
    concepts: dict[str, Concept],
    relationships: dict[str, Relationship],
    view_elements: list[tuple[ET.Element, tuple[str, ...]]],
    unsupported: list[str],
) -> None:
    """Première passe : indexe concepts et relations, met les vues de côté.

    Le type d'un élément vient exclusivement de `xsi:type` ; le dossier qui le
    contient n'est qu'une commodité d'organisation dans Archi.
    """
    for el in folder.findall("element"):
        el_type = _local_type(el)
        el_id = el.get("id", "")
        if not el_id:
            continue
        if el_type in _VIEW_TYPES:
            view_elements.append((el, folder_path))
        elif el_type in _UNSUPPORTED_VIEW_TYPES:
            unsupported.append(el.get("name") or el_type)
        elif el_type.endswith("Relationship"):
            relationships[el_id] = Relationship(
                id=el_id,
                type=el_type,
                source=el.get("source", ""),
                target=el.get("target", ""),
                name=el.get("name", ""),
                documentation=_documentation(el),
                access_type=_int(el.get("accessType"), 0),
                strength=el.get("strength", ""),
                directed=el.get("directed") == "true",
            )
        else:
            concepts[el_id] = Concept(
                id=el_id,
                type=el_type,
                name=el.get("name", ""),
                documentation=_documentation(el),
            )

    for sub in folder.findall("folder"):
        _index_folder(
            sub,
            folder_path + (sub.get("name") or "",),
            concepts,
            relationships,
            view_elements,
            unsupported,
        )


def parse_archimate(path: str | Path) -> ArchimateModel:
    """Lit un fichier `.archimate` et renvoie le modèle complet.

    Lève `ArchimateParseError` si le fichier est absent, mal formé, ou n'est pas
    un modèle Archi.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise ArchimateParseError(f"File not found: {file_path}")

    try:
        root = ET.parse(str(file_path)).getroot()
    except ET.ParseError as exc:
        raise ArchimateParseError(f"Invalid XML in {file_path.name}: {exc}") from exc
    except OSError as exc:
        raise ArchimateParseError(f"Cannot read {file_path.name}: {exc}") from exc

    # La racine est `archimate:model`, qu'ElementTree expose sous forme
    # `{http://www.archimatetool.com/archimate}model`.
    if not root.tag.endswith("model"):
        raise ArchimateParseError(
            f"{file_path.name} is not an ArchiMate model (root element: {root.tag})"
        )

    concepts: dict[str, Concept] = {}
    relationships: dict[str, Relationship] = {}
    view_elements: list[tuple[ET.Element, tuple[str, ...]]] = []
    unsupported: list[str] = []

    # Les dossiers racine (Business, Views, ...) ne font pas partie du chemin
    # affiché : une vue rangée directement dans « Views » a un chemin vide.
    for folder in root.findall("folder"):
        _index_folder(folder, (), concepts, relationships, view_elements, unsupported)

    # Deuxième passe : les vues référencent concepts et relations, qui doivent
    # tous être indexés au préalable (l'ordre des dossiers n'est pas garanti).
    views = [_parse_view(el, path_, concepts, relationships) for el, path_ in view_elements]

    return ArchimateModel(
        id=root.get("id", ""),
        name=root.get("name") or file_path.stem,
        version=root.get("version", ""),
        path=str(file_path),
        concepts=concepts,
        relationships=relationships,
        views=views,
        unsupported_views=unsupported,
    )
