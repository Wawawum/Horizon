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

    def set_order_for_bucket(self, bucket: TaskBucket, task_ids: list[int]) -> None:
        for i, tid in enumerate(task_ids):
            self._db.conn.execute(
                'UPDATE tasks SET "order" = ? WHERE id = ?',
                (i * 1000, tid),
            )
        self._db.conn.commit()

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


@dataclass
class Subtask:
    id:        int | None
    task_id:   int
    title:     str
    completed: bool


class SubtaskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, task_id: int, title: str) -> "Subtask":
        row = self._db.conn.execute(
            'SELECT COALESCE(MAX("order"), 0) + 10 AS next_order FROM subtasks WHERE task_id = ?',
            (task_id,),
        ).fetchone()
        next_order: int = row["next_order"]
        cur = self._db.conn.execute(
            'INSERT INTO subtasks (task_id, title, completed, "order") VALUES (?, ?, 0, ?)',
            (task_id, title, next_order),
        )
        self._db.conn.commit()
        return Subtask(id=cur.lastrowid, task_id=task_id, title=title, completed=False)

    def list_for_task(self, task_id: int) -> "list[Subtask]":
        rows = self._db.conn.execute(
            'SELECT id, task_id, title, completed FROM subtasks WHERE task_id = ? ORDER BY "order"',
            (task_id,),
        ).fetchall()
        return [
            Subtask(id=r["id"], task_id=r["task_id"], title=r["title"], completed=bool(r["completed"]))
            for r in rows
        ]

    def set_order_for_task(self, task_id: int, subtask_ids: list) -> None:
        for i, sid in enumerate(subtask_ids):
            self._db.conn.execute(
                'UPDATE subtasks SET "order" = ? WHERE id = ? AND task_id = ?',
                (i * 10, sid, task_id),
            )
        self._db.conn.commit()

    def set_completed(self, subtask_id: int, completed: bool) -> None:
        self._db.conn.execute(
            "UPDATE subtasks SET completed = ? WHERE id = ?",
            (1 if completed else 0, subtask_id),
        )
        self._db.conn.commit()

    def delete(self, subtask_id: int) -> None:
        self._db.conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))
        self._db.conn.commit()
