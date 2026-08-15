# Architecture

Horizon is a Windows desktop productivity app built with Python, PySide6/Qt, and SQLite.

---

## Layers

```text
UI Layer      -> src/horizon/widgets/     QWidget subclasses, signals, view state
Data Layer    -> src/horizon/<entity>.py  Dataclasses + repositories
Infra Layer   -> database.py              SQLite connection, DDL, migrations
              -> api_server.py            Local HTTP API
              -> mcp_server.py            MCP server over stdio
```

Data flow:

```text
User action -> Qt Signal -> Widget method -> Repository -> Database.conn -> commit()
```

---

## Entry Point

[../src/horizon/__main__.py](../src/horizon/__main__.py):

1. Loads preferences.
2. Opens/initializes the database.
3. Creates the `QApplication`.
4. Starts the local API server.
5. Creates and shows `MainWindow`.
6. Stops the API and closes the DB on exit.

---

## Main Window

[../src/horizon/app.py](../src/horizon/app.py) owns the top-level wiring:

- Repository construction
- Main splitter/stack layout
- Signal connections between widgets
- Navigation between views
- Window preferences
- Pin/topmost hotkey integration

Widgets should emit signals and keep local UI state. Repositories should own data access and persistence.

---

## Database

[../src/horizon/database.py](../src/horizon/database.py) defines:

- `DB_PATH`: `~/.horizon/horizon.db`
- `open_connection(...)`: connection helper used by API code
- `_DDL`: current schema for new databases
- `_MIGRATIONS`: compatibility migrations for existing databases
- `_run_structural_migrations()`: manual rebuild-style migrations
- `_sync_search_index()`: full-text index initialization/update

SQLite uses WAL mode and foreign keys.

---

## Search And Tags

`search_index` is an FTS5 virtual table.

Current searchable entities:
- notes
- tasks
- projects

Tags are extracted from note/task bodies by [../src/horizon/tag.py](../src/horizon/tag.py). Current tag associations:
- `note_tags`
- `task_tags`

---

## Tasks In Notes

A note can declare a task inline, title on the first line and an optional description below:

```markdown
{task: Préparer le COPIL
Slides + relevé de décisions}
```

On an **explicit** save (Ctrl+S, blur, Back, window close — not the 5 s autosave) the block is
persisted as a real task in the note's project and rewritten to `{task: 42}`. A note with no
project is skipped silently. Blocks inside a fenced code region are ignored.

[../src/horizon/note_task.py](../src/horizon/note_task.py) owns the syntax and the `note_tasks`
N:N association, which is re-synced on every explicit save: removing a block unlinks the task
but never deletes it. Deleting the task from its project drops the link through the FK cascade,
and the note then renders the bare id — archiving does not, so archived tasks keep showing their
title and status.

The renderer resolves titles and states **when the note is opened**, not on every keystroke.

---

## HTTP API

[../src/horizon/api_server.py](../src/horizon/api_server.py) uses stdlib `ThreadingHTTPServer` and `BaseHTTPRequestHandler`.

The desktop app starts the local API automatically. The active port is written to `~/.horizon/api.port`.

---

## MCP Server

[../src/horizon/mcp_server.py](../src/horizon/mcp_server.py) exposes selected Horizon operations as MCP tools. It discovers the local API port from:

1. `HORIZON_API_PORT`
2. `~/.horizon/api.port`

The MCP server should generally call the HTTP API rather than opening the UI database directly.

---

## Verification

There are currently no automated tests. For low-risk validation, use:

```powershell
python -m compileall src
python -m horizon
```

For data-layer validation, prefer temporary database paths in small scripts instead of using the user's real `~/.horizon/horizon.db`.
