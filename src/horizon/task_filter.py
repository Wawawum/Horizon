import json
from dataclasses import dataclass, field

from horizon.database import Database
from horizon.task import Task, TaskPriority, TaskState

DEFAULT_FILTER_TITLE = "Default"


@dataclass
class TaskFilter:
    # Une liste vide signifie « All » : aucun filtre sur ce champ.
    id:          int | None
    title:       str
    states:      list[TaskState]    = field(default_factory=list)
    project_ids: list[int]          = field(default_factory=list)
    priorities:  list[TaskPriority] = field(default_factory=list)

    def matches(self, task: Task, include_projects: bool = True) -> bool:
        # include_projects=False : board d'un projet, où le filtre projet ne s'applique pas.
        if self.states and task.state not in self.states:
            return False
        if include_projects and self.project_ids and task.project_id not in self.project_ids:
            return False
        if self.priorities and task.priority not in self.priorities:
            return False
        return True

    def to_json(self) -> str:
        return json.dumps({
            "states":      [s.value for s in self.states],
            "project_ids": list(self.project_ids),
            "priorities":  [p.value for p in self.priorities],
        })

    @classmethod
    def from_row(cls, filter_id: int, title: str, raw: str) -> "TaskFilter":
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls(
            id=filter_id,
            title=title,
            states=_parse_enum_list(TaskState, data.get("states")),
            project_ids=[v for v in data.get("project_ids") or [] if isinstance(v, int)],
            priorities=_parse_enum_list(TaskPriority, data.get("priorities")),
        )


def _parse_enum_list(enum_cls, values) -> list:
    # Valeurs inconnues ignorées : le JSON doit survivre à un renommage d'enum.
    result = []
    for v in values or []:
        try:
            result.append(enum_cls(v))
        except ValueError:
            pass
    return result


class TaskFilterRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, filter_id: int) -> TaskFilter | None:
        row = self._db.conn.execute(
            "SELECT id, title, filter FROM task_filters WHERE id = ?",
            (filter_id,),
        ).fetchone()
        if row is None:
            return None
        return TaskFilter.from_row(row["id"], row["title"], row["filter"])

    def get_default(self) -> TaskFilter:
        """Filtre « Default » du board, créé vide (tout afficher) s'il n'existe pas encore."""
        row = self._db.conn.execute(
            "SELECT id, title, filter FROM task_filters WHERE title = ? ORDER BY id LIMIT 1",
            (DEFAULT_FILTER_TITLE,),
        ).fetchone()
        if row is not None:
            return TaskFilter.from_row(row["id"], row["title"], row["filter"])
        task_filter = TaskFilter(id=None, title=DEFAULT_FILTER_TITLE)
        cur = self._db.conn.execute(
            "INSERT INTO task_filters (title, filter) VALUES (?, ?)",
            (task_filter.title, task_filter.to_json()),
        )
        self._db.conn.commit()
        task_filter.id = cur.lastrowid
        return task_filter

    def update(self, task_filter: TaskFilter) -> None:
        self._db.conn.execute(
            "UPDATE task_filters SET title = ?, filter = ? WHERE id = ?",
            (task_filter.title, task_filter.to_json(), task_filter.id),
        )
        self._db.conn.commit()
