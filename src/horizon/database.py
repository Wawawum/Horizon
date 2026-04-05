import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".horizon" / "horizon.db"

_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL CHECK(length(name) <= 255),
    description TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL CHECK(length(title) <= 255),
    description TEXT    NOT NULL DEFAULT '',
    state       TEXT    NOT NULL DEFAULT 'New'
                CHECK(state IN ('New','In-Progress','On hold','Completed','Cancelled')),
    priority    TEXT    NOT NULL DEFAULT 'Medium'
                CHECK(priority IN ('Low','Medium','High')),
    bucket      TEXT    NOT NULL DEFAULT 'Inbox'
                CHECK(bucket IN ('Inbox','Today','On hold','Completed'))
);

CREATE TABLE IF NOT EXISTS subtasks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id   INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    title     TEXT    NOT NULL CHECK(length(title) <= 255),
    completed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL CHECK(length(title) <= 255),
    body       TEXT    NOT NULL DEFAULT '',
    dt         TEXT    NOT NULL
);
"""

_MIGRATIONS = [
    "ALTER TABLE tasks ADD COLUMN bucket TEXT NOT NULL DEFAULT 'Inbox'"
    " CHECK(bucket IN ('Inbox','Today','On hold','Completed'))",
    'ALTER TABLE tasks ADD COLUMN "order" INTEGER NOT NULL DEFAULT 0',
    'UPDATE tasks SET "order" = id * 1000 WHERE "order" = 0',
    'ALTER TABLE subtasks ADD COLUMN "order" INTEGER NOT NULL DEFAULT 0',
    'UPDATE subtasks SET "order" = id * 10 WHERE "order" = 0',
]


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.executescript(_DDL)
        self._run_migrations()

    def _run_migrations(self) -> None:
        for sql in _MIGRATIONS:
            try:
                self._conn.execute(sql)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()
