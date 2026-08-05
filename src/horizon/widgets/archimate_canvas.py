"""Moteur de rendu des vues ArchiMate.

Peuple une `QGraphicsScene` à partir d'un `ArchimateView` produit par
`horizon.archimate_model`. Tout est peint à la main, comme le reste de
l'application (voir les `paintEvent` de `widgets/project.py`).

Parti pris de couleurs : le fond du canevas suit le thème Horizon, mais les
remplissages d'éléments gardent les couleurs standard d'ArchiMate (jaune
business, bleu application, vert technologie...) pour que les diagrammes restent
reconnaissables. Le texte des éléments est donc forcé en foncé.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

from horizon.archimate_model import ArchimateModel, ArchimateView, DiagramConnection, DiagramNode

# ── Couches et couleurs ──────────────────────────────────────────────────────

# Couleurs de remplissage par défaut d'Archi. Indispensables : la plupart des
# modèles n'écrivent aucun `fillColor`, les éléments étant laissés au défaut.
LAYER_FILL = {
    "strategy": "#f5deaa",
    "business": "#ffffb5",
    "application": "#b5ffff",
    "technology": "#c9e7b7",
    "physical": "#c9e7b7",
    "motivation": "#ccccff",
    "implementation": "#ffe0e0",
    "other": "#ffffff",
}

_STRATEGY = ("Resource", "Capability", "CourseOfAction", "ValueStream")
_BUSINESS = (
    "BusinessActor", "BusinessRole", "BusinessCollaboration", "BusinessInterface",
    "BusinessProcess", "BusinessFunction", "BusinessInteraction", "BusinessEvent",
    "BusinessService", "BusinessObject", "Contract", "Representation", "Product",
)
_APPLICATION = (
    "ApplicationComponent", "ApplicationCollaboration", "ApplicationInterface",
    "ApplicationFunction", "ApplicationInteraction", "ApplicationProcess",
    "ApplicationEvent", "ApplicationService", "DataObject",
)
_TECHNOLOGY = (
    "Node", "Device", "SystemSoftware", "TechnologyCollaboration", "TechnologyInterface",
    "Path", "CommunicationNetwork", "TechnologyFunction", "TechnologyProcess",
    "TechnologyInteraction", "TechnologyEvent", "TechnologyService", "Artifact",
)
_PHYSICAL = ("Equipment", "Facility", "DistributionNetwork", "Material")
_MOTIVATION = (
    "Stakeholder", "Driver", "Assessment", "Goal", "Outcome",
    "Principle", "Requirement", "Constraint", "Meaning", "Value",
)
_IMPLEMENTATION = ("WorkPackage", "Deliverable", "ImplementationEvent", "Plateau", "Gap")
_OTHER = ("Location", "Grouping", "Junction", "AndJunction", "OrJunction")

ELEMENT_LAYER: dict[str, str] = {}
for _types, _layer in (
    (_STRATEGY, "strategy"),
    (_BUSINESS, "business"),
    (_APPLICATION, "application"),
    (_TECHNOLOGY, "technology"),
    (_PHYSICAL, "physical"),
    (_MOTIVATION, "motivation"),
    (_IMPLEMENTATION, "implementation"),
    (_OTHER, "other"),
):
    for _t in _types:
        ELEMENT_LAYER[_t] = _layer


# ── Formes ───────────────────────────────────────────────────────────────────

# Éléments de comportement : rectangle à coins arrondis. Les services sont
# entièrement arrondis (« stade »), les éléments de motivation octogonaux.
_ROUNDED_SUFFIXES = ("Process", "Function", "Interaction", "Event")
# Éléments arrondis sans suffixe de comportement reconnaissable.
_ROUNDED_TYPES = frozenset({"ValueStream", "WorkPackage"})
_ELLIPSE_TYPES = frozenset({"Value", "Meaning", "Junction", "AndJunction", "OrJunction"})
_OCTAGON_TYPES = frozenset(_MOTIVATION) - _ELLIPSE_TYPES


def shape_for(element_type: str) -> str:
    """Forme géométrique à employer pour un type ArchiMate donné."""
    if element_type in _ELLIPSE_TYPES:
        return "ellipse"
    if element_type in _OCTAGON_TYPES:
        return "octagon"
    if element_type == "Grouping":
        return "dashed_rect"
    if element_type == "Group":
        return "tabbed_rect"
    if element_type == "Note":
        return "note"
    if element_type.endswith("Service"):
        return "stadium"
    if element_type in _ROUNDED_TYPES or element_type.endswith(_ROUNDED_SUFFIXES):
        return "round"
    return "rect"


# ── Pictogrammes ─────────────────────────────────────────────────────────────
#
# Chaque peintre dessine dans une boîte carrée de 16 px, au trait, avec le stylo
# et la brosse déjà positionnés par l'appelant.

def _poly(painter: QPainter, points: list[tuple[float, float]], filled: bool = False) -> None:
    polygon = QPolygonF([QPointF(x, y) for x, y in points])
    painter.save()
    if filled:
        painter.setBrush(QBrush(painter.pen().color()))
    painter.drawPolygon(polygon)
    painter.restore()


def _badge_component(p: QPainter, r: QRectF) -> None:
    body = QRectF(r.left() + 4, r.top() + 2, r.width() - 4, r.height() - 4)
    p.drawRect(body)
    # Deux ergots débordant sur la gauche du corps, comme l'icône ArchiMate.
    tab_w, tab_h = 7.0, 3.5
    for ratio in (0.28, 0.72):
        center_y = body.top() + body.height() * ratio
        p.drawRect(QRectF(r.left(), center_y - tab_h / 2, tab_w, tab_h))


def _badge_stadium(p: QPainter, r: QRectF) -> None:
    box = QRectF(r.left(), r.top() + r.height() * 0.25, r.width(), r.height() * 0.5)
    p.drawRoundedRect(box, box.height() / 2, box.height() / 2)


def _badge_rounded(p: QPainter, r: QRectF) -> None:
    p.drawRoundedRect(QRectF(r.left(), r.top() + 3, r.width(), r.height() - 6), 3, 3)


def _badge_process(p: QPainter, r: QRectF) -> None:
    top, bottom = r.top() + 3, r.bottom() - 3
    mid = r.center().y()
    notch = r.right() - 5
    _poly(p, [
        (r.left(), top + 2), (notch, top + 2), (notch, top),
        (r.right(), mid), (notch, bottom), (notch, bottom - 2),
        (r.left(), bottom - 2),
    ])


def _badge_function(p: QPainter, r: QRectF) -> None:
    _poly(p, [
        (r.center().x(), r.top()), (r.right(), r.bottom()),
        (r.center().x(), r.bottom() - r.height() * 0.35), (r.left(), r.bottom()),
    ])


def _badge_interaction(p: QPainter, r: QRectF) -> None:
    h = r.height() * 0.6
    top = r.center().y() - h / 2
    gap = 2.0
    left = QRectF(r.left(), top, r.width() / 2 - gap / 2, h)
    right = QRectF(r.center().x() + gap / 2, top, r.width() / 2 - gap / 2, h)
    path = QPainterPath()
    path.moveTo(left.right(), left.top())
    path.arcTo(QRectF(left.left(), left.top(), left.width() * 2, left.height()), 90, 180)
    p.drawPath(path)
    path2 = QPainterPath()
    path2.moveTo(right.left(), right.bottom())
    path2.arcTo(QRectF(right.left() - right.width(), right.top(), right.width() * 2, right.height()), 270, 180)
    p.drawPath(path2)


def _badge_event(p: QPainter, r: QRectF) -> None:
    top, bottom = r.top() + 3, r.bottom() - 3
    mid = r.center().y()
    _poly(p, [
        (r.left(), top), (r.right() - 4, top), (r.right(), mid),
        (r.right() - 4, bottom), (r.left(), bottom), (r.left() + 4, mid),
    ])


def _badge_actor(p: QPainter, r: QRectF) -> None:
    head = r.width() * 0.3
    cx = r.center().x()
    p.drawEllipse(QPointF(cx, r.top() + head / 2 + 1), head / 2, head / 2)
    p.drawLine(QPointF(cx, r.top() + head + 1), QPointF(cx, r.bottom() - 4))
    p.drawLine(QPointF(r.left() + 1, r.top() + head + 3), QPointF(r.right() - 1, r.top() + head + 3))
    p.drawLine(QPointF(cx, r.bottom() - 4), QPointF(r.left() + 1, r.bottom()))
    p.drawLine(QPointF(cx, r.bottom() - 4), QPointF(r.right() - 1, r.bottom()))


def _badge_role(p: QPainter, r: QRectF) -> None:
    box = QRectF(r.left(), r.top() + r.height() * 0.28, r.width(), r.height() * 0.44)
    p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
    p.drawLine(QPointF(box.left() + box.width() * 0.55, box.top()),
               QPointF(box.left() + box.width() * 0.55, box.bottom()))


def _badge_collaboration(p: QPainter, r: QRectF) -> None:
    d = r.height() * 0.7
    y = r.center().y() - d / 2
    p.drawEllipse(QRectF(r.left(), y, d, d))
    p.drawEllipse(QRectF(r.right() - d, y, d, d))


def _badge_interface(p: QPainter, r: QRectF) -> None:
    d = r.height() * 0.6
    cy = r.center().y()
    p.drawLine(QPointF(r.left(), cy), QPointF(r.right() - d, cy))
    p.drawEllipse(QRectF(r.right() - d, cy - d / 2, d, d))


def _badge_object(p: QPainter, r: QRectF) -> None:
    box = QRectF(r.left(), r.top() + 2, r.width(), r.height() - 4)
    p.drawRect(box)
    p.drawLine(QPointF(box.left(), box.top() + 4), QPointF(box.right(), box.top() + 4))


def _badge_contract(p: QPainter, r: QRectF) -> None:
    _badge_object(p, r)
    box = QRectF(r.left(), r.top() + 2, r.width(), r.height() - 4)
    p.drawLine(QPointF(box.left(), box.bottom() - 4), QPointF(box.right(), box.bottom() - 4))


def _wavy_bottom(p: QPainter, box: QRectF) -> None:
    path = QPainterPath()
    path.moveTo(box.left(), box.top())
    path.lineTo(box.right(), box.top())
    path.lineTo(box.right(), box.bottom() - 3)
    path.cubicTo(
        QPointF(box.left() + box.width() * 0.66, box.bottom() + 2),
        QPointF(box.left() + box.width() * 0.33, box.bottom() - 6),
        QPointF(box.left(), box.bottom() - 2),
    )
    path.closeSubpath()
    p.drawPath(path)


def _badge_representation(p: QPainter, r: QRectF) -> None:
    _wavy_bottom(p, QRectF(r.left(), r.top() + 1, r.width(), r.height() - 2))


def _badge_product(p: QPainter, r: QRectF) -> None:
    box = QRectF(r.left(), r.top() + 2, r.width(), r.height() - 4)
    p.drawRect(box)
    p.fillRect(QRectF(box.left(), box.top(), box.width() * 0.45, 4), QBrush(p.pen().color()))


def _badge_node(p: QPainter, r: QRectF) -> None:
    depth = r.width() * 0.25
    front = QRectF(r.left(), r.top() + depth, r.width() - depth, r.height() - depth - 2)
    p.drawRect(front)
    _poly(p, [
        (front.left(), front.top()), (front.left() + depth, r.top() + 1),
        (r.right(), r.top() + 1), (r.right(), front.bottom() - depth),
        (front.right(), front.bottom()), (front.right(), front.top()),
    ])


def _badge_device(p: QPainter, r: QRectF) -> None:
    screen = QRectF(r.left(), r.top() + 1, r.width(), r.height() * 0.6)
    p.drawRoundedRect(screen, 2, 2)
    _poly(p, [
        (screen.left() - 1, r.bottom()), (screen.left() + 2, screen.bottom()),
        (screen.right() - 2, screen.bottom()), (screen.right() + 1, r.bottom()),
    ])


def _badge_system_software(p: QPainter, r: QRectF) -> None:
    d = r.height() * 0.8
    p.drawEllipse(QRectF(r.left(), r.center().y() - d / 2, d, d))
    p.drawEllipse(QRectF(r.left() + r.width() - d, r.center().y() - d / 2, d, d))


def _badge_artifact(p: QPainter, r: QRectF) -> None:
    fold = r.width() * 0.35
    box = QRectF(r.left() + 1, r.top() + 1, r.width() - 2, r.height() - 2)
    _poly(p, [
        (box.left(), box.top()), (box.right() - fold, box.top()),
        (box.right(), box.top() + fold), (box.right(), box.bottom()),
        (box.left(), box.bottom()),
    ])
    p.drawLine(QPointF(box.right() - fold, box.top()), QPointF(box.right() - fold, box.top() + fold))
    p.drawLine(QPointF(box.right() - fold, box.top() + fold), QPointF(box.right(), box.top() + fold))


def _badge_network(p: QPainter, r: QRectF) -> None:
    d = 5.0
    cy = r.center().y()
    p.drawEllipse(QRectF(r.left(), cy - d / 2, d, d))
    p.drawEllipse(QRectF(r.right() - d, cy - d / 2, d, d))
    p.drawLine(QPointF(r.left() + d, cy), QPointF(r.right() - d, cy))


def _badge_goal(p: QPainter, r: QRectF) -> None:
    c = r.center()
    for factor in (1.0, 0.6):
        d = r.height() * factor
        p.drawEllipse(QRectF(c.x() - d / 2, c.y() - d / 2, d, d))
    p.save()
    p.setBrush(QBrush(p.pen().color()))
    p.drawEllipse(c, 1.6, 1.6)
    p.restore()


def _badge_outcome(p: QPainter, r: QRectF) -> None:
    _badge_goal(p, r)
    p.drawLine(QPointF(r.center().x(), r.center().y()), QPointF(r.right(), r.top()))


def _badge_driver(p: QPainter, r: QRectF) -> None:
    c = r.center()
    radius = r.height() / 2
    p.drawEllipse(c, radius, radius)
    for angle in (90, 210, 330):
        rad = math.radians(angle)
        p.drawLine(c, QPointF(c.x() + radius * math.cos(rad), c.y() - radius * math.sin(rad)))


def _badge_assessment(p: QPainter, r: QRectF) -> None:
    d = r.height() * 0.72
    p.drawEllipse(QRectF(r.left(), r.top(), d, d))
    p.drawLine(QPointF(r.left() + d * 0.8, r.top() + d * 0.8), QPointF(r.right(), r.bottom()))


def _badge_principle(p: QPainter, r: QRectF) -> None:
    box = QRectF(r.left() + 2, r.top() + 1, r.width() - 4, r.height() - 2)
    p.drawRect(box)
    cx = box.center().x()
    p.drawLine(QPointF(cx, box.top() + 3), QPointF(cx, box.bottom() - 5))
    p.drawPoint(QPointF(cx, box.bottom() - 3))


def _badge_requirement(p: QPainter, r: QRectF) -> None:
    slant = r.width() * 0.22
    top, bottom = r.top() + 3, r.bottom() - 3
    _poly(p, [
        (r.left() + slant, top), (r.right(), top),
        (r.right() - slant, bottom), (r.left(), bottom),
    ])


def _badge_constraint(p: QPainter, r: QRectF) -> None:
    _badge_requirement(p, r)
    p.drawLine(QPointF(r.left() + r.width() * 0.45, r.top() + 3),
               QPointF(r.left() + r.width() * 0.2, r.bottom() - 3))


def _badge_meaning(p: QPainter, r: QRectF) -> None:
    path = QPainterPath()
    path.addEllipse(QRectF(r.left(), r.center().y() - 4, 9, 8))
    path.addEllipse(QRectF(r.left() + 5, r.top() + 1, 9, 8))
    path.addEllipse(QRectF(r.right() - 9, r.center().y() - 3, 9, 8))
    p.drawPath(path.simplified())


def _badge_value(p: QPainter, r: QRectF) -> None:
    p.drawEllipse(r.adjusted(0, 2, 0, -2))


def _badge_capability(p: QPainter, r: QRectF) -> None:
    unit = r.width() / 2 - 1
    p.drawRect(QRectF(r.left(), r.top(), unit, unit))
    p.drawRect(QRectF(r.left() + unit + 2, r.top(), unit, unit))
    p.drawRect(QRectF(r.left(), r.top() + unit + 2, unit, unit))


def _badge_resource(p: QPainter, r: QRectF) -> None:
    box = QRectF(r.left(), r.top() + 3, r.width(), r.height() - 6)
    p.drawRect(box)
    p.drawLine(QPointF(box.left() + 4, box.top()), QPointF(box.left() + 4, box.bottom()))


def _badge_course_of_action(p: QPainter, r: QRectF) -> None:
    c = r.center()
    p.drawEllipse(c, r.height() / 2, r.height() / 2)
    p.drawEllipse(c, r.height() / 6, r.height() / 6)
    p.drawLine(QPointF(c.x(), c.y()), QPointF(r.right(), r.top()))


def _badge_work_package(p: QPainter, r: QRectF) -> None:
    p.drawRoundedRect(QRectF(r.left(), r.top() + 3, r.width(), r.height() - 6), 3, 3)


def _badge_deliverable(p: QPainter, r: QRectF) -> None:
    _wavy_bottom(p, QRectF(r.left(), r.top() + 2, r.width(), r.height() - 4))


def _badge_plateau(p: QPainter, r: QRectF) -> None:
    bar = (r.height() - 4) / 3
    for i in range(3):
        p.fillRect(QRectF(r.left(), r.top() + i * (bar + 2), r.width(), bar), QBrush(p.pen().color()))


def _badge_gap(p: QPainter, r: QRectF) -> None:
    c = r.center()
    p.drawEllipse(c, r.height() / 2, r.height() / 2)
    p.drawLine(QPointF(r.left() - 1, c.y()), QPointF(r.right() + 1, c.y()))


def _badge_location(p: QPainter, r: QRectF) -> None:
    d = r.width() * 0.8
    cx = r.center().x()
    p.drawEllipse(QRectF(cx - d / 2, r.top(), d, d))
    _poly(p, [(cx - d / 4, r.top() + d * 0.75), (cx + d / 4, r.top() + d * 0.75), (cx, r.bottom())])


def _badge_equipment(p: QPainter, r: QRectF) -> None:
    c = r.center()
    radius = r.height() * 0.34
    p.drawEllipse(c, radius, radius)
    for angle in range(0, 360, 90):
        rad = math.radians(angle)
        p.drawLine(
            QPointF(c.x() + radius * math.cos(rad), c.y() - radius * math.sin(rad)),
            QPointF(c.x() + (radius + 3) * math.cos(rad), c.y() - (radius + 3) * math.sin(rad)),
        )


def _badge_facility(p: QPainter, r: QRectF) -> None:
    base = QRectF(r.left(), r.center().y(), r.width(), r.height() / 2)
    p.drawRect(base)
    _poly(p, [
        (r.left(), base.top()), (r.left() + r.width() * 0.4, r.top() + 2),
        (r.left() + r.width() * 0.4, base.top()),
    ])


_BADGES = {
    "component": _badge_component,
    "service": _badge_stadium,
    "process": _badge_process,
    "function": _badge_function,
    "interaction": _badge_interaction,
    "event": _badge_event,
    "actor": _badge_actor,
    "role": _badge_role,
    "collaboration": _badge_collaboration,
    "interface": _badge_interface,
    "object": _badge_object,
    "contract": _badge_contract,
    "representation": _badge_representation,
    "product": _badge_product,
    "node": _badge_node,
    "device": _badge_device,
    "system_software": _badge_system_software,
    "artifact": _badge_artifact,
    "network": _badge_network,
    "goal": _badge_goal,
    "outcome": _badge_outcome,
    "driver": _badge_driver,
    "assessment": _badge_assessment,
    "principle": _badge_principle,
    "requirement": _badge_requirement,
    "constraint": _badge_constraint,
    "meaning": _badge_meaning,
    "value": _badge_value,
    "capability": _badge_capability,
    "resource": _badge_resource,
    "course_of_action": _badge_course_of_action,
    "work_package": _badge_work_package,
    "deliverable": _badge_deliverable,
    "plateau": _badge_plateau,
    "gap": _badge_gap,
    "location": _badge_location,
    "equipment": _badge_equipment,
    "facility": _badge_facility,
    "rounded": _badge_rounded,
}

# Types dont le pictogramme ne se déduit pas d'un suffixe.
_BADGE_BY_TYPE = {
    "ApplicationComponent": "component",
    "BusinessActor": "actor",
    "BusinessRole": "role",
    "Stakeholder": "role",
    "BusinessObject": "object",
    "DataObject": "object",
    "Artifact": "artifact",
    "Contract": "contract",
    "Representation": "representation",
    "Product": "product",
    "Node": "node",
    "Device": "device",
    "SystemSoftware": "system_software",
    "CommunicationNetwork": "network",
    "DistributionNetwork": "network",
    "Path": "network",
    "Goal": "goal",
    "Outcome": "outcome",
    "Driver": "driver",
    "Assessment": "assessment",
    "Principle": "principle",
    "Requirement": "requirement",
    "Constraint": "constraint",
    # Meaning et Value n'ont pas de pictogramme : leur forme (ellipse) suffit à
    # les identifier, comme dans la notation.
    "Capability": "capability",
    "Resource": "resource",
    "CourseOfAction": "course_of_action",
    "ValueStream": "process",
    "WorkPackage": "work_package",
    "Deliverable": "deliverable",
    "Plateau": "plateau",
    "Gap": "gap",
    "Location": "location",
    "Equipment": "equipment",
    "Facility": "facility",
    "Material": "object",
}


def badge_for(element_type: str) -> str | None:
    """Nom du pictogramme d'un type, ou `None` s'il n'en a pas."""
    explicit = _BADGE_BY_TYPE.get(element_type)
    if explicit is not None:
        return explicit
    for suffix, name in (
        ("Collaboration", "collaboration"),
        ("Interface", "interface"),
        ("Service", "service"),
        ("Process", "process"),
        ("Function", "function"),
        ("Interaction", "interaction"),
        ("Event", "event"),
    ):
        if element_type.endswith(suffix):
            return name
    return None


# ── Styles de relations ──────────────────────────────────────────────────────
#
# (style de trait, tête côté source, tête côté cible). Les têtes possibles :
# "diamond_filled", "diamond_hollow", "ball", "arrow_filled", "arrow_open",
# "triangle_hollow".

RELATION_STYLE: dict[str, tuple[Qt.PenStyle, str | None, str | None]] = {
    "CompositionRelationship":    (Qt.PenStyle.SolidLine, "diamond_filled", None),
    "AggregationRelationship":    (Qt.PenStyle.SolidLine, "diamond_hollow", None),
    "AssignmentRelationship":     (Qt.PenStyle.SolidLine, "ball", "arrow_filled"),
    "RealizationRelationship":    (Qt.PenStyle.DotLine, None, "triangle_hollow"),
    "ServingRelationship":        (Qt.PenStyle.SolidLine, None, "arrow_open"),
    "AccessRelationship":         (Qt.PenStyle.DotLine, None, "arrow_open"),
    "InfluenceRelationship":      (Qt.PenStyle.DashLine, None, "arrow_open"),
    "TriggeringRelationship":     (Qt.PenStyle.SolidLine, None, "arrow_filled"),
    "FlowRelationship":           (Qt.PenStyle.DashLine, None, "arrow_filled"),
    "SpecializationRelationship": (Qt.PenStyle.SolidLine, None, "triangle_hollow"),
    "AssociationRelationship":    (Qt.PenStyle.SolidLine, None, None),
}
_DEFAULT_RELATION_STYLE = (Qt.PenStyle.SolidLine, None, None)

# accessType : 0 = écriture (flèche vers la cible), 1 = lecture (vers la source),
# 2 = accès indifférencié (aucune flèche), 3 = lecture/écriture (les deux).
_ACCESS_HEADS = {
    0: (None, "arrow_open"),
    1: ("arrow_open", None),
    2: (None, None),
    3: ("arrow_open", "arrow_open"),
}


# ── Items graphiques ─────────────────────────────────────────────────────────

_TEXT_MARGIN = 5
_BADGE_SIZE = 16
_BADGE_INSET = 4
_MIN_BADGE_WIDTH = 55
_MIN_BADGE_HEIGHT = 32
_ROUND_RADIUS = 10
_OCTAGON_CUT = 8
_NOTE_FOLD = 12
_GROUP_TAB_HEIGHT = 16
_GROUP_TAB_WIDTH_RATIO = 0.4
_CONNECTION_Z = 1000.0
_SCENE_MARGIN = 40


def _color(value: str | None, fallback: str) -> QColor:
    color = QColor(value) if value else QColor()
    return color if color.isValid() else QColor(fallback)


class NodeItem(QGraphicsItem):
    """Un objet de diagramme : forme, pictogramme et libellé."""

    def __init__(self, node: DiagramNode, label: str, parent=None) -> None:
        super().__init__(parent)
        self._node = node
        self._label = label
        self._rect = QRectF(node.x, node.y, node.width, node.height)

        element_type = node.element_type
        self._shape = shape_for(node.kind if node.kind in ("Note", "Group") else element_type)
        self._badge = badge_for(element_type) if node.kind == "DiagramObject" else None

        layer = ELEMENT_LAYER.get(element_type, "other")
        self._fill = _color(node.fill_color, LAYER_FILL.get(layer, LAYER_FILL["other"]))
        self._line = _color(node.line_color, self._fill.darker(155).name())
        self._text_color = _color(node.font_color, "#1a1a1a")
        self.setZValue(float(node.depth))
        self.setToolTip(self._build_tooltip())

    def _build_tooltip(self) -> str:
        node = self._node
        lines = [self._label or node.kind]
        if node.concept is not None:
            lines.append(node.concept.type)
            if node.concept.documentation:
                lines.append("")
                lines.append(node.concept.documentation)
        return "\n".join(lines)

    @property
    def node(self) -> DiagramNode:
        return self._node

    def boundingRect(self) -> QRectF:
        # Marge d'un pixel pour ne pas rogner le trait de bordure.
        return self._rect.adjusted(-1, -1, 1, 1)

    def _build_path(self) -> QPainterPath:
        r = self._rect
        path = QPainterPath()
        if self._shape == "ellipse":
            path.addEllipse(r)
        elif self._shape == "stadium":
            radius = min(r.height() / 2, r.width() / 2)
            path.addRoundedRect(r, radius, radius)
        elif self._shape == "round":
            path.addRoundedRect(r, _ROUND_RADIUS, _ROUND_RADIUS)
        elif self._shape == "octagon":
            cut = min(_OCTAGON_CUT, r.width() / 3, r.height() / 3)
            path.addPolygon(QPolygonF([
                QPointF(r.left() + cut, r.top()), QPointF(r.right() - cut, r.top()),
                QPointF(r.right(), r.top() + cut), QPointF(r.right(), r.bottom() - cut),
                QPointF(r.right() - cut, r.bottom()), QPointF(r.left() + cut, r.bottom()),
                QPointF(r.left(), r.bottom() - cut), QPointF(r.left(), r.top() + cut),
            ]))
            path.closeSubpath()
        elif self._shape == "note":
            fold = min(_NOTE_FOLD, r.width() / 3, r.height() / 3)
            path.addPolygon(QPolygonF([
                QPointF(r.left(), r.top()), QPointF(r.right(), r.top()),
                QPointF(r.right(), r.bottom() - fold), QPointF(r.right() - fold, r.bottom()),
                QPointF(r.left(), r.bottom()),
            ]))
            path.closeSubpath()
        elif self._shape == "tabbed_rect":
            tab_w = r.width() * _GROUP_TAB_WIDTH_RATIO
            tab_h = min(_GROUP_TAB_HEIGHT, r.height() / 3)
            path.addPolygon(QPolygonF([
                QPointF(r.left(), r.top()), QPointF(r.left() + tab_w, r.top()),
                QPointF(r.left() + tab_w, r.top() + tab_h), QPointF(r.right(), r.top() + tab_h),
                QPointF(r.right(), r.bottom()), QPointF(r.left(), r.bottom()),
            ]))
            path.closeSubpath()
        else:
            path.addRect(r)
        return path

    def _text_rect(self) -> QRectF:
        rect = self._rect.adjusted(_TEXT_MARGIN, _TEXT_MARGIN, -_TEXT_MARGIN, -_TEXT_MARGIN)
        if self._shape == "tabbed_rect":
            # Le libellé d'un Group tient dans l'onglet.
            tab_h = min(_GROUP_TAB_HEIGHT, self._rect.height() / 3)
            return QRectF(
                self._rect.left() + _TEXT_MARGIN, self._rect.top(),
                self._rect.width() * _GROUP_TAB_WIDTH_RATIO - _TEXT_MARGIN, tab_h,
            )
        if self._badge is not None and self._show_badge():
            rect.setRight(rect.right() - _BADGE_SIZE)
        return rect

    def _show_badge(self) -> bool:
        return self._rect.width() >= _MIN_BADGE_WIDTH and self._rect.height() >= _MIN_BADGE_HEIGHT

    def _text_flags(self, metrics: QFontMetricsF, available_width: float) -> int:
        # `textAlignment` : 1 gauche, 2 centre, 4 droite ; Archi omet la valeur
        # par défaut (centre). `textPosition` : 0 haut, 1 milieu, 2 bas.
        default_horizontal = (
            Qt.AlignmentFlag.AlignLeft if self._shape == "note" else Qt.AlignmentFlag.AlignHCenter
        )
        horizontal = {
            1: Qt.AlignmentFlag.AlignLeft,
            4: Qt.AlignmentFlag.AlignRight,
        }.get(self._node.text_alignment, default_horizontal)
        vertical = {
            1: Qt.AlignmentFlag.AlignVCenter,
            2: Qt.AlignmentFlag.AlignBottom,
        }.get(self._node.text_position, Qt.AlignmentFlag.AlignTop)
        if self._shape == "tabbed_rect":
            horizontal, vertical = Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignVCenter

        flags = int(horizontal) | int(vertical) | int(Qt.TextFlag.TextWordWrap)
        # Un mot plus large que la boîte déborderait des deux côtés : dans ce
        # seul cas on autorise la coupure en plein mot. Le texte courant d'une
        # note garde ainsi une césure aux espaces.
        if any(metrics.horizontalAdvance(word) > available_width for word in self._label.split()):
            flags |= int(Qt.TextFlag.TextWrapAnywhere)
        return flags

    def _font(self, painter: QPainter) -> QFont:
        font = QFont(painter.font())
        if self._node.font_family:
            font.setFamily(self._node.font_family)
        if self._node.font_size:
            font.setPointSizeF(self._node.font_size)
        font.setBold(self._node.bold)
        font.setItalic(self._node.italic)
        return font

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pen = QPen(self._line, 1.0)
        if self._shape == "dashed_rect":
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(self._fill))
        painter.drawPath(self._build_path())

        if self._badge is not None and self._show_badge():
            painter.save()
            painter.setPen(QPen(self._line, 1.0))
            # Les pictogrammes sont remplis de la couleur du nœud : les formes
            # qui se chevauchent (ergots d'un composant, cercles d'une
            # collaboration) restent lisibles, comme dans Archi.
            painter.setBrush(QBrush(self._fill))
            box = QRectF(
                self._rect.right() - _BADGE_INSET - _BADGE_SIZE,
                self._rect.top() + _BADGE_INSET,
                _BADGE_SIZE, _BADGE_SIZE,
            )
            _BADGES[self._badge](painter, box)
            painter.restore()

        if self._label:
            painter.setPen(QPen(self._text_color))
            painter.setFont(self._font(painter))
            text_rect = self._text_rect()
            flags = self._text_flags(QFontMetricsF(painter.font()), text_rect.width())
            painter.drawText(text_rect, flags, self._label)


def _clip_to_rect(rect: QRectF, inside: QPointF, outside: QPointF) -> QPointF:
    """Point où le segment `inside`→`outside` quitte `rect`.

    Employé pour que les traits s'arrêtent au bord des formes au lieu de courir
    jusqu'à leur centre.
    """
    dx, dy = outside.x() - inside.x(), outside.y() - inside.y()
    if dx == 0 and dy == 0:
        return QPointF(outside)

    best = 1.0
    candidates: list[tuple[float, float, float]] = []
    if dx != 0:
        for edge_x in (rect.left(), rect.right()):
            candidates.append(((edge_x - inside.x()) / dx, edge_x, float("nan")))
    if dy != 0:
        for edge_y in (rect.top(), rect.bottom()):
            candidates.append(((edge_y - inside.y()) / dy, float("nan"), edge_y))

    for t, _x, _y in candidates:
        if not 0.0 <= t <= 1.0:
            continue
        px = inside.x() + dx * t
        py = inside.y() + dy * t
        # Tolérance : le point calculé doit tomber sur le segment de bordure.
        if rect.left() - 0.01 <= px <= rect.right() + 0.01 and rect.top() - 0.01 <= py <= rect.bottom() + 0.01:
            best = min(best, t)

    return QPointF(inside.x() + dx * best, inside.y() + dy * best)


class ConnectionItem(QGraphicsItem):
    """Un trait entre deux objets de diagramme, tête(s) comprise(s)."""

    _HEAD_LENGTH = 11.0
    _HEAD_HALF_WIDTH = 4.5
    _DIAMOND_LENGTH = 14.0
    _BALL_RADIUS = 3.5

    def __init__(self, connection: DiagramConnection, source: QRectF, target: QRectF, parent=None) -> None:
        super().__init__(parent)
        self._connection = connection
        self._points = self._route(connection, source, target)

        style, source_head, target_head = RELATION_STYLE.get(
            connection.relation_type, _DEFAULT_RELATION_STYLE
        )
        if connection.relation_type == "AccessRelationship" and connection.relationship is not None:
            source_head, target_head = _ACCESS_HEADS.get(
                connection.relationship.access_type, (None, "arrow_open")
            )
        elif connection.relation_type == "AssociationRelationship" and connection.relationship is not None:
            if connection.relationship.directed:
                target_head = "arrow_open"
        self._pen_style = style
        self._source_head = source_head
        self._target_head = target_head

        self._line_color = _color(connection.line_color, "#5a5a5a")
        self._line_width = max(1, connection.line_width)
        self._label_color = _color(connection.font_color, "#3a3a3a")

        extent = max(self._DIAMOND_LENGTH, self._HEAD_LENGTH) + self._line_width + 2
        self._bounds = QPolygonF(self._points).boundingRect().adjusted(-extent, -extent, extent, extent)

    @staticmethod
    def _route(connection: DiagramConnection, source: QRectF, target: QRectF) -> list[QPointF]:
        source_center, target_center = source.center(), target.center()
        # Les bendpoints d'Archi sont des offsets relatifs au centre de la
        # source ; les offsets « end » décrivent le même point vu de la cible.
        waypoints = [
            QPointF(source_center.x() + start_x, source_center.y() + start_y)
            for start_x, start_y, _end_x, _end_y in connection.bendpoints
        ]
        first_target = waypoints[0] if waypoints else target_center
        last_source = waypoints[-1] if waypoints else source_center
        start = _clip_to_rect(source, source_center, first_target)
        end = _clip_to_rect(target, target_center, last_source)
        return [start, *waypoints, end]

    def boundingRect(self) -> QRectF:
        return self._bounds

    def _draw_head(self, painter: QPainter, kind: str, tip: QPointF, towards: QPointF) -> None:
        """Dessine une tête en `tip`, orientée depuis `towards` vers `tip`."""
        dx, dy = tip.x() - towards.x(), tip.y() - towards.y()
        length = math.hypot(dx, dy)
        if length == 0:
            return
        ux, uy = dx / length, dy / length
        px, py = -uy, ux  # perpendiculaire unitaire

        if kind == "ball":
            painter.setBrush(QBrush(self._line_color))
            painter.drawEllipse(tip, self._BALL_RADIUS, self._BALL_RADIUS)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            return

        if kind in ("diamond_filled", "diamond_hollow"):
            half = self._DIAMOND_LENGTH / 2
            center_x, center_y = tip.x() - ux * half, tip.y() - uy * half
            polygon = QPolygonF([
                QPointF(tip.x(), tip.y()),
                QPointF(center_x + px * self._HEAD_HALF_WIDTH, center_y + py * self._HEAD_HALF_WIDTH),
                QPointF(tip.x() - ux * self._DIAMOND_LENGTH, tip.y() - uy * self._DIAMOND_LENGTH),
                QPointF(center_x - px * self._HEAD_HALF_WIDTH, center_y - py * self._HEAD_HALF_WIDTH),
            ])
            painter.setBrush(QBrush(self._line_color if kind == "diamond_filled" else QColor("#ffffff")))
            painter.drawPolygon(polygon)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            return

        base_x, base_y = tip.x() - ux * self._HEAD_LENGTH, tip.y() - uy * self._HEAD_LENGTH
        left = QPointF(base_x + px * self._HEAD_HALF_WIDTH, base_y + py * self._HEAD_HALF_WIDTH)
        right = QPointF(base_x - px * self._HEAD_HALF_WIDTH, base_y - py * self._HEAD_HALF_WIDTH)

        if kind == "arrow_open":
            painter.drawLine(left, tip)
            painter.drawLine(right, tip)
        elif kind == "arrow_filled":
            painter.setBrush(QBrush(self._line_color))
            painter.drawPolygon(QPolygonF([tip, left, right]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        elif kind == "triangle_hollow":
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.drawPolygon(QPolygonF([tip, left, right]))
            painter.setBrush(Qt.BrushStyle.NoBrush)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        points = self._points

        pen = QPen(self._line_color, float(self._line_width), self._pen_style)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))

        # Les têtes sont toujours pleines, même sur un trait pointillé.
        painter.setPen(QPen(self._line_color, float(self._line_width), Qt.PenStyle.SolidLine))
        if self._source_head:
            self._draw_head(painter, self._source_head, points[0], points[1])
        if self._target_head:
            self._draw_head(painter, self._target_head, points[-1], points[-2])

        if self._connection.label:
            middle_index = len(points) // 2
            anchor = points[middle_index] if len(points) % 2 else (
                (points[middle_index - 1] + points[middle_index]) / 2
            )
            box = QRectF(anchor.x() - 80, anchor.y() - 20, 160, 16)
            painter.setPen(QPen(self._label_color))
            painter.drawText(
                box,
                int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.AlignmentFlag.AlignVCenter),
                self._connection.label,
            )


# ── Construction de la scène ─────────────────────────────────────────────────


def _add_nodes(
    nodes: list[DiagramNode],
    scene: QGraphicsScene,
    model: ArchimateModel | None,
    rects: dict[str, QRectF],
) -> None:
    for node in nodes:
        label = node.label
        if not label and node.kind == "DiagramModelReference" and model is not None:
            target = next((v for v in model.views if v.id == node.ref_view_id), None)
            label = target.name if target is not None else ""
        item = NodeItem(node, label)
        scene.addItem(item)
        rects[node.id] = QRectF(node.x, node.y, node.width, node.height)
        _add_nodes(node.children, scene, model, rects)


def build_scene(
    view: ArchimateView,
    scene: QGraphicsScene,
    model: ArchimateModel | None = None,
) -> QRectF:
    """Peuple `scene` avec la vue et renvoie le rectangle englobant (avec marge).

    Les nœuds imbriqués sont empilés selon leur profondeur, les connexions
    passent au-dessus de tous les nœuds.
    """
    scene.clear()
    rects: dict[str, QRectF] = {}
    _add_nodes(view.nodes, scene, model, rects)

    for connection in view.connections:
        source = rects.get(connection.source)
        target = rects.get(connection.target)
        # Une connexion dont une extrémité manque (fichier partiel, ou trait vers
        # un objet non supporté) est simplement omise du rendu.
        if source is None or target is None:
            continue
        item = ConnectionItem(connection, source, target)
        item.setZValue(_CONNECTION_Z)
        scene.addItem(item)

    bounds = scene.itemsBoundingRect()
    if bounds.isNull():
        bounds = QRectF(0, 0, 1, 1)
    bounds = bounds.adjusted(-_SCENE_MARGIN, -_SCENE_MARGIN, _SCENE_MARGIN, _SCENE_MARGIN)
    scene.setSceneRect(bounds)
    return bounds
