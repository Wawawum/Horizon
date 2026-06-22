# Agent Patterns

Detailed Horizon coding patterns for agents and contributors. Start with [../AGENTS.md](../AGENTS.md) for the short guide.

---

## Repository + Dataclass

Each domain entity should keep pure data in a dataclass and business logic in a repository class.

```python
@dataclass
class Task:
    id: int | None
    project_id: int
    title: str
    description: str
    state: TaskState
    priority: TaskPriority
    bucket: TaskBucket = field(default=TaskBucket.Inbox)
    order: int = 0
    archived: bool = False


class TaskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
```

Reference implementations:
- [../src/horizon/note.py](../src/horizon/note.py)
- [../src/horizon/task.py](../src/horizon/task.py)
- [../src/horizon/project.py](../src/horizon/project.py)
- [../src/horizon/deliverable.py](../src/horizon/deliverable.py)

---

## Imports

Use three groups, in this order:

```python
# 1. stdlib
import json
from pathlib import Path
from dataclasses import dataclass

# 2. third-party
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

# 3. local horizon
from horizon import theme as _theme
from horizon.database import Database
```

Keep local imports explicit. Do not use `from horizon.widgets import *`.

---

## Widgets

Widgets should build UI, expose typed signals, and delegate persistence/business logic to repositories.

```python
class NotesListWidget(QWidget):
    note_edit_requested = Signal(int)

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._build_ui()

    def load(self) -> None:
        notes = self._note_repo.list_all(...)
```

Rules:
- Always call `super().__init__(parent)` first in widget constructors.
- Prefer `load()` or `load(entity_id)` as the public refresh/populate method.
- Use class-level `Signal(...)` declarations for inter-widget communication.
- Use `QThread` subclasses for long-running operations, and emit failure signals instead of raising from `run()`.

Reference implementations:
- [../src/horizon/widgets/notes.py](../src/horizon/widgets/notes.py)
- [../src/horizon/widgets/project.py](../src/horizon/widgets/project.py)
- [../src/horizon/widgets/calendar.py](../src/horizon/widgets/calendar.py)

---

## Preferences

Preferences are backed by `self._data` in [../src/horizon/preferences.py](../src/horizon/preferences.py).

Rules:
- Property setters should not autosave.
- Call `save()` explicitly when persistence is intended.
- Helper methods may call `save()` immediately when that is the existing local pattern.

```python
@property
def theme(self) -> str:
    return self._data.get("theme", "dark")

@theme.setter
def theme(self, value: str) -> None:
    self._data["theme"] = value
```

---

## Data Layer

Every repository mutation should:

1. Execute the primary `INSERT`, `UPDATE`, or `DELETE`.
2. Update `search_index` when the entity is searchable.
3. Sync tags when the entity is tagged.
4. Commit at the end of the mutation.

Current searchable entities:
- notes
- tasks
- projects

Current tagged entities:
- notes via `TagRepository.set_for_note()`
- tasks via `TagRepository.set_for_task()`

Repositories such as deliverables, folders, images, and deliverable templates still follow the repository pattern and commit their mutations, but they do not currently sync tags or `search_index`.

---

## Database Migrations

Schema changes go in [../src/horizon/database.py](../src/horizon/database.py).

When adding a table or column:
- Update `_DDL` so new databases get the latest schema.
- Add a corresponding entry in `_MIGRATIONS` for existing databases.
- Use `_run_structural_migrations()` only for schema changes that cannot be expressed safely as simple `ALTER TABLE` statements.
- Do not remove old migrations unless the migration strategy changes intentionally.

---

## Error Handling

Patterns used in the repo:
- Optional imports use module-level `try`/`except ImportError` and an `_AVAILABLE` flag.
- API handler failures log with `logger.exception(...)` and return an HTTP error response.
- QThread workers emit failure signals instead of raising from `run()`.
- Silent `except: pass` is only acceptable in narrow, intentional cases such as DB migration compatibility or Qt object teardown.
