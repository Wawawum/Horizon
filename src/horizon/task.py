from dataclasses import dataclass
from enum import Enum

from horizon.database import Database


class TaskState(Enum):
    New         = "New"
    In_Progress = "In-Progress"
    On_Hold     = "On hold"
    Completed   = "Completed"
    Cancelled   = "Cancelled"


class TaskPriority(Enum):
    Low    = "Low"
    Medium = "Medium"
    High   = "High"


@dataclass
class Task:
    id:          int | None
    project_id:  int
    title:       str
    description: str
    state:       TaskState
    priority:    TaskPriority


class TaskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        title: str,
        description: str = "",
        state: TaskState = TaskState.New,
        priority: TaskPriority = TaskPriority.Medium,
    ) -> Task:
        cur = self._db.conn.execute(
            "INSERT INTO tasks (project_id, title, description, state, priority)"
            " VALUES (?, ?, ?, ?, ?)",
            (project_id, title, description, state.value, priority.value),
        )
        self._db.conn.commit()
        return Task(cur.lastrowid, project_id, title, description, state, priority)

    def get(self, task_id: int) -> "Task | None":
        row = self._db.conn.execute(
            "SELECT id, project_id, title, description, state, priority"
            " FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return Task(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            state=TaskState(row["state"]),
            priority=TaskPriority(row["priority"]),
        )

    def update(self, task: Task) -> None:
        self._db.conn.execute(
            "UPDATE tasks SET title=?, description=?, state=?, priority=?"
            " WHERE id=?",
            (task.title, task.description, task.state.value, task.priority.value, task.id),
        )
        self._db.conn.commit()

    def list_for_project(self, project_id: int) -> list[Task]:
        rows = self._db.conn.execute(
            "SELECT id, project_id, title, description, state, priority"
            " FROM tasks WHERE project_id = ? ORDER BY id",
            (project_id,),
        ).fetchall()
        return [
            Task(
                id=r["id"],
                project_id=r["project_id"],
                title=r["title"],
                description=r["description"],
                state=TaskState(r["state"]),
                priority=TaskPriority(r["priority"]),
            )
            for r in rows
        ]
