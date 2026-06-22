# AGENTS.md — Horizon Coding Guide

This file contains everything a coding agent (or new contributor) needs to work effectively on this codebase.  
See [README.md](README.md) for project overview and setup.

---

## Setup Commands

```powershell
# Install (editable mode, includes all dependencies)
pip install -e .

# Run the desktop app
python -m horizon
# or
horizon

# Run the MCP server (for AI agent integration)
horizon-mcp
```

**Database**: Auto-created at `~/.horizon/horizon.db` on first launch. No manual init needed.  
**Preferences**: Stored in `src/horizon/preferences.json`.  
**API port**: Written to `~/.horizon/api.port` at runtime.

There are no automated tests at this time. Verify changes by running the app manually.

---

## Project Overview

Horizon is a Windows desktop productivity app (PySide6/Qt + SQLite). It manages notes, tasks, projects, deliverables, folders, tags, and a calendar — all stored locally.

**Three-layer architecture:**

```
UI Layer      → src/horizon/widgets/     QWidget subclasses, no business logic
Data Layer    → src/horizon/<entity>.py  Dataclasses + Repositories
Infra Layer   → database.py, api_server.py, mcp_server.py
```

**Data flow:**  
User action → Qt `Signal` → Widget method → `Repository` → `Database.conn` (SQLite) → `commit()`

**Entry point:** `src/horizon/__main__.py` — creates `Database`, `Preferences`, `ApiServer`, then `MainWindow`.

---

## Code Style & Patterns

### 1. Repository + Dataclass (core pattern — never deviate)

Each entity lives in a single file with:
- A `@dataclass` holding **pure data only** (no methods, no logic)
- A `Repository` class holding **all business logic** (CRUD, search indexing, tagging)

```python
# src/horizon/task.py

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
    archived:    bool = False


class TaskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, title: str, ...) -> Task:
        cur = self._db.conn.execute("INSERT INTO tasks (...) VALUES (...)", (...))
        task_id = cur.lastrowid
        # Searchable entities must update search_index
        self._db.conn.execute(
            "INSERT INTO search_index(type, entity_id, title, body) VALUES ('task', ?, ?, ?)",
            (task_id, title, description),
        )
        # Tagged entities use the concrete TagRepository helper for that entity
        TagRepository(self._db).set_for_task(task_id, extract_tag_names(description))
        self._db.conn.commit()
        return Task(id=task_id, ...)
```

Reference implementations: [src/horizon/note.py](src/horizon/note.py) · [src/horizon/task.py](src/horizon/task.py)

---

### 2. Import Order (strict)

```python
# 1. stdlib
import json
from pathlib import Path
from dataclasses import dataclass

# 2. third-party
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

# 3. local horizon
from horizon.database import Database
from horizon import theme as _theme   # always aliased with _
```

---

### 3. Widgets: `__init__()` + `load()` pattern

- Constructor: build UI, inject repositories via parameters, wire signals
- `load()` or `load(entity_id)`: public method to populate/refresh data
- No business logic inside widgets — delegate to repositories
- Always call `super().__init__(parent)` first

```python
class NotesListWidget(QWidget):
    note_edit_requested = Signal(int)   # always typed

    def __init__(self, note_repo: NoteRepository, project_repo: ProjectRepository, parent=None) -> None:
        super().__init__(parent)
        self._note_repo = note_repo
        self._project_repo = project_repo
        self._build_ui()

    def _build_ui(self) -> None:
        # layout, widgets, connect signals
        ...

    def load(self) -> None:
        notes = self._note_repo.list_all(...)
        # populate self._table
```

Reference: [src/horizon/widgets/notes.py](src/horizon/widgets/notes.py)

---

### 4. Qt Signals (always over callbacks)

- Declare signals as class-level attributes with explicit type: `signal_name = Signal(int)`
- Use signals for all inter-widget communication; never pass callbacks
- Use `QThread` subclasses for long-running operations (e.g. Outlook fetch)

```python
class OutlookFetchWorker(QThread):
    meetings_ready = Signal(list)
    fetch_failed   = Signal(str)

    def run(self) -> None:
        try:
            results = self._fetch()
            self.meetings_ready.emit(results)
        except Exception as exc:
            self.fetch_failed.emit(str(exc))   # signal, never raise
```

---

### 5. Preferences: properties + explicit `save()`

- Properties with getters/setters backed by `self._data` dict
- Property setters do not autosave — call `save()` explicitly after mutations that should persist
- Helper methods may save immediately when that is the existing local pattern
- Lazy-load from `preferences.json` in `__init__`

```python
@property
def theme(self) -> str:
    return self._data.get("theme", "dark")

@theme.setter
def theme(self, value: str) -> None:
    self._data["theme"] = value
    # do NOT call self.save() here
```

---

### 6. Naming Conventions

| Element | Convention | Example |
|---|---|---|
| Classes | PascalCase | `NoteDetailWidget`, `TaskRepository` |
| Functions / methods | snake_case | `load()`, `_build_ui()` |
| Private attributes | `_` prefix | `self._db`, `self._note_repo` |
| Module-level private | `_` prefix | `_PREFS_PATH`, `_theme` |
| Constants | UPPER_SNAKE | `HOUR_HEIGHT = 60` |
| Modules | lowercase | `note.py`, `api_server.py` |
| Enums | PascalCase class, PascalCase members | `TaskState.In_Progress` |

---

### 7. Data Layer Rules (search + tags + commit)

Every `create()` and `update()` in a Repository **must**:

1. Execute the primary `INSERT`/`UPDATE`
2. For searchable entities, update `search_index` (FTS5 virtual table)
3. For tagged entities, sync tags via the concrete `TagRepository` method (`set_for_note` or `set_for_task`)
4. Call `self._db.conn.commit()` at the end of the mutation

Current searchable entities are notes, tasks, and projects. Current tagged entities are notes and tasks. Other repositories, such as deliverables, folders, images, and deliverable templates, still follow the repository pattern and commit their mutations, but they do not currently sync tags or `search_index`.

```python
self._db.conn.execute(
    "INSERT INTO search_index(type, entity_id, title, body) VALUES (?, ?, ?, ?)",
    (entity_type, entity_id, title, body),
)
TagRepository(self._db).set_for_note(entity_id, extract_tag_names(body))
self._db.conn.commit()
```

---

### 8. Error Handling

- Optional imports: use try/except at module level, set an `_AVAILABLE` flag
- Async errors in `QThread.run()`: emit a `failed = Signal(str)` — never raise
- No silent `except: pass` except in DB migrations (where column-already-exists is expected)

```python
try:
    import win32com.client
    _OUTLOOK_AVAILABLE = True
except ImportError:
    _OUTLOOK_AVAILABLE = False
```

---

## Common Agent Tasks

### Adding a new widget (list + detail)

1. Create `src/horizon/widgets/<feature>.py`
2. Define `<Feature>ListWidget(QWidget)` with `<action>_requested = Signal(int)` and `load()`
3. Define `<Feature>DetailWidget(QWidget)` with `<action>_saved = Signal(int)` and `load(id)`
4. Export both from `src/horizon/widgets/__init__.py`
5. Wire in `src/horizon/app.py`: add repo injection, connect signals, add to `QStackedWidget`

### Adding a new entity (full feature)

1. **`src/horizon/<entity>.py`** — `@dataclass` + `Repository` (CRUD + search + tags + commit)
2. **`src/horizon/database.py`** — add DDL table in `_DDL` string AND a migration in `_MIGRATIONS`
3. **`src/horizon/widgets/<entity>.py`** — list widget + detail widget
4. **`src/horizon/widgets/__init__.py`** — export new widgets
5. **`src/horizon/app.py`** — instantiate repository, wire widgets and signals
6. **`src/horizon/api_server.py`** _(optional)_ — add REST endpoints if API access is needed

### Extending a repository

Add a new method to the existing `Repository` class in the entity file.  
Follow the same pattern: execute SQL → update `search_index`/tags when the entity participates in those systems → commit.

---

## Key Files Reference

| File | Purpose |
|---|---|
| [src/horizon/app.py](src/horizon/app.py) | `MainWindow` — all widget wiring, hotkeys, signal routing |
| [src/horizon/database.py](src/horizon/database.py) | `Database` class, DDL, migrations, search index sync |
| [src/horizon/note.py](src/horizon/note.py) | Canonical example: `Note` dataclass + `NoteRepository` |
| [src/horizon/task.py](src/horizon/task.py) | Canonical example with Enums: `Task` + `TaskRepository` |
| [src/horizon/preferences.py](src/horizon/preferences.py) | `Preferences` — property pattern + explicit `save()` |
| [src/horizon/widgets/notes.py](src/horizon/widgets/notes.py) | Canonical widget example: list + detail |
| [src/horizon/widgets/__init__.py](src/horizon/widgets/__init__.py) | Widget exports |
| [src/horizon/api_server.py](src/horizon/api_server.py) | HTTP REST API (stdlib `http.server`, no framework) |
| [src/horizon/mcp_server.py](src/horizon/mcp_server.py) | MCP server entry point |
| [pyproject.toml](pyproject.toml) | Dependencies and entry points |

---

## What NOT to Do

- Do not add business logic inside widgets — use repositories
- Do not use callbacks for inter-widget communication — use `Signal`
- Do not autosave `Preferences` inside property setters — call `save()` explicitly where persistence is intended
- Do not skip `search_index` updates for repositories whose entities are searchable
- Do not use `from horizon.widgets import *` — import specifically
- Do not use silent `except: pass` outside of DB migration loops
- Do not add new columns to `_DDL` without a corresponding entry in `_MIGRATIONS`
