from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMenu, QToolButton, QWidget, QWidgetAction

from horizon.task import Task, TaskPriority, TaskState
from horizon.task_filter import TaskFilter, TaskFilterRepository


class TaskFilterModel(QObject):
    """Sélection de filtres partagée par les boards (vue « Default »).

    Une seule instance alimente le board ALL TASKS et le board d'un projet : chaque
    changement est émis via `changed` et sauvegardé 5 s après le dernier."""

    changed = Signal()

    _SAVE_DELAY_MS = 5000

    def __init__(self, repo: TaskFilterRepository, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self._filter = repo.get_default()
        self._dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self._SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.flush_and_save)

    @property
    def states(self) -> list[TaskState]:
        return list(self._filter.states)

    @property
    def project_ids(self) -> list[int]:
        return list(self._filter.project_ids)

    @property
    def priorities(self) -> list[TaskPriority]:
        return list(self._filter.priorities)

    def matches(self, task: Task, include_projects: bool = True) -> bool:
        return self._filter.matches(task, include_projects=include_projects)

    def set_states(self, states: list[TaskState]) -> None:
        self._apply(states=list(states))

    def set_project_ids(self, project_ids: list[int]) -> None:
        self._apply(project_ids=list(project_ids))

    def set_priorities(self, priorities: list[TaskPriority]) -> None:
        self._apply(priorities=list(priorities))

    def drop_unknown_projects(self, known_ids: set[int]) -> None:
        # Un projet supprimé ou archivé sort de la sélection plutôt que de tout masquer.
        # Pas d'émission : la liste déroulante l'a déjà retiré de son affichage.
        self._filter.project_ids = [pid for pid in self._filter.project_ids if pid in known_ids]

    def flush_and_save(self) -> None:
        self._save_timer.stop()
        if not self._dirty:
            return
        self._repo.update(self._filter)
        self._dirty = False

    def _apply(self, **changes) -> None:
        if all(getattr(self._filter, name) == value for name, value in changes.items()):
            return
        for name, value in changes.items():
            setattr(self._filter, name, value)
        self._dirty = True
        self._save_timer.start()  # redémarre le décompte à chaque changement
        self.changed.emit()


class _MultiSelectDropdown(QToolButton):
    """Liste déroulante à cases à cocher, précédée d'une entrée « All » (aucun filtre).

    Fermée, elle affiche « All », la valeur cochée, ou les valeurs cochées séparées
    par des virgules (élidées si trop longues ; la liste complète est en tooltip)."""

    selection_changed = Signal()

    _WIDTH = 150
    _TEXT_PADDING = 30  # place réservée à l'indicateur de menu et aux marges

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setFixedWidth(self._WIDTH)
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        # Une QCheckBox dans un QWidgetAction garde le menu ouvert pendant les clics.
        self._all_cb, _ = self._add_checkbox("All")
        self._all_cb.setChecked(True)
        self._all_cb.toggled.connect(self._on_all_toggled)
        self._menu.addSeparator()
        self._options: list[tuple[QCheckBox, object, QWidgetAction]] = []
        self._refresh_text()

    def _add_checkbox(self, label: str) -> tuple[QCheckBox, QWidgetAction]:
        cb = QCheckBox(label, self._menu)
        cb.setStyleSheet("QCheckBox { padding: 4px 12px; }")
        action = QWidgetAction(self._menu)
        action.setDefaultWidget(cb)
        self._menu.addAction(action)
        return cb, action

    def set_options(self, options: list[tuple[str, object]]) -> None:
        """Remplace les options ; la sélection est conservée pour les valeurs encore présentes."""
        previous = set(self.selected())
        for _, _, action in self._options:
            self._menu.removeAction(action)
            action.deleteLater()
        self._options = []
        for label, value in options:
            cb, action = self._add_checkbox(label)
            cb.setChecked(value in previous)
            cb.toggled.connect(self._on_option_toggled)
            self._options.append((cb, value, action))
        self._set_all_checked(not self.selected())
        self._refresh_text()

    def set_selected(self, values: list) -> None:
        wanted = set(values)
        for cb, value, _ in self._options:
            cb.blockSignals(True)
            cb.setChecked(value in wanted)
            cb.blockSignals(False)
        self._set_all_checked(not self.selected())
        self._refresh_text()

    def selected(self) -> list:
        return [value for cb, value, _ in self._options if cb.isChecked()]

    def _set_all_checked(self, checked: bool) -> None:
        self._all_cb.blockSignals(True)
        self._all_cb.setChecked(checked)
        self._all_cb.blockSignals(False)

    def _on_all_toggled(self, checked: bool) -> None:
        if not checked:
            # « All » ne se décoche qu'en cochant une valeur.
            self._set_all_checked(True)
            return
        for cb, _, _ in self._options:
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._refresh_text()
        self.selection_changed.emit()

    def _on_option_toggled(self, _checked: bool) -> None:
        self._set_all_checked(not self.selected())
        self._refresh_text()
        self.selection_changed.emit()

    def _refresh_text(self) -> None:
        labels = [cb.text() for cb, _, _ in self._options if cb.isChecked()]
        full = ", ".join(labels) if labels else "All"
        self.setToolTip(full)
        self.setText(self.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideRight, self._WIDTH - self._TEXT_PADDING
        ))


class TaskFilterBar(QWidget):
    """Listes déroulantes Status / Project / Priority branchées sur un `TaskFilterModel`.

    `show_projects=False` masque le filtre projet (board d'un projet)."""

    def __init__(self, model: TaskFilterModel, show_projects: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._model = model

        self._state_filter = _MultiSelectDropdown(self)
        self._state_filter.set_options([(s.value, s) for s in TaskState])
        self._state_filter.selection_changed.connect(
            lambda: self._model.set_states(self._state_filter.selected())
        )

        self._project_filter: _MultiSelectDropdown | None = None
        if show_projects:
            self._project_filter = _MultiSelectDropdown(self)
            self._project_filter.selection_changed.connect(
                lambda: self._model.set_project_ids(self._project_filter.selected())
            )

        self._priority_filter = _MultiSelectDropdown(self)
        self._priority_filter.set_options([(p.value, p) for p in TaskPriority])
        self._priority_filter.selection_changed.connect(
            lambda: self._model.set_priorities(self._priority_filter.selected())
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for label, dropdown in (
            ("Status", self._state_filter),
            ("Project", self._project_filter),
            ("Priority", self._priority_filter),
        ):
            if dropdown is None:
                continue
            layout.addWidget(QLabel(label, self))
            layout.addWidget(dropdown)
            layout.addSpacing(8)

        self._model.changed.connect(self._sync_from_model)
        self._sync_from_model()

    def set_projects(self, projects: list[tuple[str, int]]) -> None:
        """(nom, id) des projets proposés dans le filtre projet."""
        if self._project_filter is None:
            return
        self._project_filter.set_options(projects)
        self._model.drop_unknown_projects({pid for _, pid in projects})
        self._project_filter.set_selected(self._model.project_ids)

    def _sync_from_model(self) -> None:
        # set_selected n'émet pas : pas de boucle avec le modèle.
        self._state_filter.set_selected(self._model.states)
        self._priority_filter.set_selected(self._model.priorities)
        if self._project_filter is not None:
            self._project_filter.set_selected(self._model.project_ids)
