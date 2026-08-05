"""Page ArchiMate : arbre des modèles/vues à gauche, diagramme à droite.

Les modèles ne sont pas copiés en base — seul leur chemin l'est. Le fichier est
donc re-parsé à la première ouverture de chaque modèle dans la session, ce qui
garde l'affichage synchrone avec les modifications faites dans Archi.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from horizon import theme as _theme
from horizon.archimate import ArchimateModelRepository
from horizon.archimate_model import ArchimateModel, ArchimateParseError, ArchimateView, parse_archimate
from horizon.dialogs import AlertDialog, ConfirmDialog, ZoomableGraphicsView
from horizon.preferences import Preferences
from horizon.widgets.archimate_canvas import NodeItem, build_scene

# Rôles portés par les items de l'arbre.
_MODEL_ID_ROLE = Qt.ItemDataRole.UserRole
_VIEW_ID_ROLE = Qt.ItemDataRole.UserRole + 1

_ZOOM_IN = 1.2
_ZOOM_OUT = 1.0 / 1.2
_TREE_WIDTH = 260
_MISSING_FILE_COLOR = "#b04a4a"
# Les couleurs ArchiMate (pastels, texte foncé, traits gris) supposent une page
# claire : si le thème devient sombre, on garde un canevas clair plutôt que de
# rendre les traits illisibles.
_FALLBACK_CANVAS = "#ffffff"
_MIN_CANVAS_LIGHTNESS = 128


class _DiagramView(ZoomableGraphicsView):
    """Canevas du diagramme, avec navigation par double-clic sur une référence
    de vue (`DiagramModelReference`)."""

    view_reference_activated = Signal(str)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        if item is not None and item.node.ref_view_id:
            self.view_reference_activated.emit(item.node.ref_view_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ArchimateWidget(QWidget):
    """Liste les modèles `.archimate` référencés et affiche leurs vues."""

    view_selected = Signal(str, str)  # id du modèle, id de la vue

    def __init__(self, model_repo: ArchimateModelRepository, prefs: Preferences, parent=None) -> None:
        super().__init__(parent)
        self._model_repo = model_repo
        self._prefs = prefs
        # Modèles parsés, par id de référence en base. Le parsing est différé au
        # premier dépliage : un gros modèle ne ralentit pas l'ouverture de l'onglet.
        self._models: dict[int, ArchimateModel] = {}
        self._scene_rect = None

        title = QLabel("ArchiMate")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        import_btn = QPushButton("Import model…")
        import_btn.clicked.connect(self._on_import)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._on_remove)
        self._remove_btn.setEnabled(False)

        zoom_out_btn = QPushButton("−")
        zoom_in_btn = QPushButton("+")
        fit_btn = QPushButton("Fit")
        for btn in (zoom_out_btn, zoom_in_btn, fit_btn):
            btn.setFixedWidth(40)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addSpacing(16)
        header_layout.addWidget(import_btn)
        header_layout.addWidget(self._remove_btn)
        header_layout.addStretch()
        header_layout.addWidget(zoom_out_btn)
        header_layout.addWidget(zoom_in_btn)
        header_layout.addWidget(fit_btn)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(180)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)

        self._scene = QGraphicsScene(self)
        self._view = _DiagramView(self._scene, self)
        self._view.setBackgroundBrush(self._canvas_color())
        self._view.view_reference_activated.connect(self._on_view_reference_activated)

        self._message = QLabel("Select a view to display its diagram.")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._view)     # index 0 — diagramme
        self._stack.addWidget(self._message)  # index 1 — message

        zoom_out_btn.clicked.connect(lambda: self._view.zoom_by(_ZOOM_OUT))
        zoom_in_btn.clicked.connect(lambda: self._view.zoom_by(_ZOOM_IN))
        fit_btn.clicked.connect(self._on_fit)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._tree)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([_TREE_WIDTH, 800])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(splitter, stretch=1)

    @staticmethod
    def _canvas_color() -> QColor:
        color = QColor(_theme.current().surface_bg)
        if not color.isValid() or color.lightness() < _MIN_CANVAS_LIGHTNESS:
            return QColor(_FALLBACK_CANVAS)
        return color

    # ── Chargement ───────────────────────────────────────────────────────────

    def load(self) -> None:
        """Reconstruit l'arbre depuis la base. Le cache de parsing est conservé."""
        self._tree.clear()
        self._show_message("Select a view to display its diagram.")
        for ref in self._model_repo.list_all():
            item = QTreeWidgetItem(self._tree, [ref.name])
            item.setData(0, _MODEL_ID_ROLE, ref.id)
            item.setData(0, _VIEW_ID_ROLE, None)
            if not Path(ref.path).is_file():
                item.setForeground(0, QColor(_MISSING_FILE_COLOR))
                item.setToolTip(0, f"File not found:\n{ref.path}")
                continue
            item.setToolTip(0, ref.path)
            # Un enfant fictif rend l'item dépliable avant tout parsing.
            QTreeWidgetItem(item, ["…"])

        if self._tree.topLevelItemCount() == 0:
            self._show_message(
                "No ArchiMate model yet.\n\nUse “Import model…” to reference a .archimate file."
            )

    def _model_for(self, model_id: int) -> ArchimateModel | None:
        """Modèle parsé, depuis le cache ou depuis le disque."""
        cached = self._models.get(model_id)
        if cached is not None:
            return cached
        ref = self._model_repo.get(model_id)
        if ref is None:
            return None
        try:
            model = parse_archimate(ref.path)
        except ArchimateParseError as exc:
            self._show_message(str(exc))
            return None
        self._models[model_id] = model
        return model

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _VIEW_ID_ROLE) is not None or item.parent() is not None:
            return  # déjà peuplé, ou pas un item de modèle
        model = self._model_for(item.data(0, _MODEL_ID_ROLE))
        if model is None:
            item.takeChildren()
            return
        self._populate_views(item, model)

    def _populate_views(self, model_item: QTreeWidgetItem, model: ArchimateModel) -> None:
        model_item.takeChildren()
        model_id = model_item.data(0, _MODEL_ID_ROLE)
        if model.unsupported_views:
            model_item.setToolTip(
                0,
                f"{model_item.toolTip(0)}\n\n"
                f"{len(model.unsupported_views)} Sketch/Canvas view(s) not supported.",
            )

        # Les sous-dossiers de « Views » sont reproduits tels quels.
        folders: dict[tuple[str, ...], QTreeWidgetItem] = {(): model_item}

        def folder_item(path: tuple[str, ...]) -> QTreeWidgetItem:
            existing = folders.get(path)
            if existing is not None:
                return existing
            parent = folder_item(path[:-1])
            created = QTreeWidgetItem(parent, [path[-1]])
            created.setData(0, _MODEL_ID_ROLE, model_id)
            created.setData(0, _VIEW_ID_ROLE, None)
            folders[path] = created
            return created

        for view in sorted(model.views, key=lambda v: (v.folder_path, v.name.lower())):
            item = QTreeWidgetItem(folder_item(view.folder_path), [view.name])
            item.setData(0, _MODEL_ID_ROLE, model_id)
            item.setData(0, _VIEW_ID_ROLE, view.id)
            if view.documentation:
                item.setToolTip(0, view.documentation)

        if not model.views:
            placeholder = QTreeWidgetItem(model_item, ["(no view)"])
            placeholder.setDisabled(True)

    # ── Sélection et rendu ───────────────────────────────────────────────────

    def _on_current_item_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        self._remove_btn.setEnabled(current is not None)
        if current is None:
            return
        model_id = current.data(0, _MODEL_ID_ROLE)
        view_id = current.data(0, _VIEW_ID_ROLE)
        if model_id is None:
            return
        if view_id is None:
            ref = self._model_repo.get(model_id)
            if ref is not None and not Path(ref.path).is_file():
                self._show_message(
                    f"File not found:\n{ref.path}\n\n"
                    "Restore the file, or use “Remove” to drop the reference."
                )
            return

        model = self._model_for(model_id)
        if model is None:
            return
        view = next((v for v in model.views if v.id == view_id), None)
        if view is None:
            self._show_message("This view is no longer present in the file.")
            return
        self._render(model, view)

    def _render(self, model: ArchimateModel, view: ArchimateView) -> None:
        self._scene_rect = build_scene(view, self._scene, model)
        self._stack.setCurrentIndex(0)
        # `fitInView` dépend de la taille du viewport : la page de la pile vient
        # juste d'être activée et n'a pas encore sa géométrie définitive. On
        # recadre au tour de boucle suivant, une fois la mise en page faite.
        QTimer.singleShot(0, self._on_fit)
        self.view_selected.emit(model.id, view.id)

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentIndex(1)

    def _on_fit(self) -> None:
        if self._scene_rect is not None:
            self._view.fit(self._scene_rect)

    def _on_view_reference_activated(self, view_id: str) -> None:
        """Double-clic sur une référence : sélectionne la vue cible dans l'arbre."""
        current = self._tree.currentItem()
        if current is None:
            return
        model_id = current.data(0, _MODEL_ID_ROLE)
        target = self._find_view_item(model_id, view_id)
        if target is not None:
            self._tree.setCurrentItem(target)

    def _find_view_item(self, model_id: int, view_id: str) -> QTreeWidgetItem | None:
        stack = [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, _MODEL_ID_ROLE) == model_id and item.data(0, _VIEW_ID_ROLE) == view_id:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return None

    # ── Import / suppression ─────────────────────────────────────────────────

    def _on_import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Import ArchiMate model",
            self._prefs.last_archimate_dir,
            "ArchiMate models (*.archimate);;All files (*)",
        )
        if not path:
            return
        resolved = str(Path(path).resolve())

        existing = self._model_repo.find_by_path(resolved)
        if existing is not None:
            AlertDialog.warn(
                "Already imported",
                f"This file is already referenced as “{existing.name}”.",
                self,
            )
            return

        # Le fichier est parsé avant d'être enregistré : rien n'entre en base
        # tant qu'on ne sait pas le lire.
        try:
            model = parse_archimate(resolved)
        except ArchimateParseError as exc:
            AlertDialog.warn("Cannot read model", str(exc), self)
            return

        self._prefs.last_archimate_dir = str(Path(resolved).parent)
        self._prefs.save()

        ref = self._model_repo.create(model.name, resolved)
        self._models[ref.id] = model
        self.load()

        new_item = self._find_model_item(ref.id)
        if new_item is not None:
            self._populate_views(new_item, model)
            new_item.setExpanded(True)
            self._tree.setCurrentItem(new_item)

    def _find_model_item(self, model_id: int) -> QTreeWidgetItem | None:
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, _MODEL_ID_ROLE) == model_id:
                return item
        return None

    def _on_remove(self) -> None:
        current = self._tree.currentItem()
        if current is None:
            return
        model_id = current.data(0, _MODEL_ID_ROLE)
        ref = self._model_repo.get(model_id) if model_id is not None else None
        if ref is None:
            return
        if not ConfirmDialog.ask(
            "Remove model",
            f"Remove “{ref.name}” from Horizon?\n\nThe .archimate file itself is not deleted.",
            self,
        ):
            return
        self._model_repo.delete(ref.id)
        self._models.pop(ref.id, None)
        self.load()
