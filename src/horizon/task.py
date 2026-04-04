from dataclasses import dataclass, field
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


class TaskBucket(Enum):
    Inbox     = "Inbox"
    Today     = "Today"
    On_Hold   = "On hold"
    Completed = "Completed"


@dataclass
class Task:
    id:          int | None
    project_id:  int
    title:       str
    description: str
    state:       TaskState
    priority:    TaskPriority
    bucket:      TaskBucket = field(default=TaskBucket.Inbox)
    order:       int = 0


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
        bucket: TaskBucket = TaskBucket.Inbox,
    ) -> Task:
        row = self._db.conn.execute(
            'SELECT COALESCE(MAX("order"), 0) + 1000 AS next_order FROM tasks'
        ).fetchone()
        next_order: int = row["next_order"]
        cur = self._db.conn.execute(
            'INSERT INTO tasks (project_id, title, description, state, priority, bucket, "order")'
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, title, description, state.value, priority.value, bucket.value, next_order),
        )
        self._db.conn.commit()
        return Task(cur.lastrowid, project_id, title, description, state, priority, bucket, next_order)

    def get(self, task_id: int) -> "Task | None":
        row = self._db.conn.execute(
            'SELECT id, project_id, title, description, state, priority, bucket, "order"'
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
            bucket=TaskBucket(row["bucket"]),
            order=row["order"],
        )

    def update(self, task: Task) -> None:
        self._db.conn.execute(
            "UPDATE tasks SET title=?, description=?, state=?, priority=?, bucket=?"
            " WHERE id=?",
            (task.title, task.description, task.state.value, task.priority.value, task.bucket.value, task.id),
        )
        self._db.conn.commit()

    def list_for_project(self, project_id: int) -> list[Task]:
        rows = self._db.conn.execute(
            'SELECT id, project_id, title, description, state, priority, bucket, "order"'
            ' FROM tasks WHERE project_id = ? ORDER BY "order"',
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
                bucket=TaskBucket(r["bucket"]),
                order=r["order"],
            )
            for r in rows
        ]

    def list_all(self) -> list[Task]:
        rows = self._db.conn.execute(
            'SELECT id, project_id, title, description, state, priority, bucket, "order"'
            ' FROM tasks ORDER BY "order"'
        ).fetchall()
        return [
            Task(
                id=r["id"],
                project_id=r["project_id"],
                title=r["title"],
                description=r["description"],
                state=TaskState(r["state"]),
                priority=TaskPriority(r["priority"]),
                bucket=TaskBucket(r["bucket"]),
                order=r["order"],
            )
            for r in rows
        ]

    def swap_order(self, task_id_a: int, task_id_b: int) -> None:
        row_a = self._db.conn.execute(
            'SELECT "order" FROM tasks WHERE id = ?', (task_id_a,)
        ).fetchone()
        row_b = self._db.conn.execute(
            'SELECT "order" FROM tasks WHERE id = ?', (task_id_b,)
        ).fetchone()
        if row_a is None or row_b is None:
            return
        self._db.conn.execute(
            'UPDATE tasks SET "order" = ? WHERE id = ?', (row_b["order"], task_id_a)
        )
        self._db.conn.execute(
            'UPDATE tasks SET "order" = ? WHERE id = ?', (row_a["order"], task_id_b)
        )
        self._db.conn.commit()
