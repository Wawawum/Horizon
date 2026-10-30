# AGENTS.md - Horizon Coding Guide

This is the root instruction file for coding agents and contributors. Keep it concise and actionable. For deeper explanations, use the linked docs below.

See [README.md](README.md) for the human-facing project overview and setup.

## Setup Commands

```powershell
# Install in editable mode
pip install -e .

# Run the desktop app
python -m horizon
# or
horizon

# Run the MCP server
horizon-mcp
```

- Database: auto-created at `~/.horizon/horizon.db` on first launch.
- Preferences: stored in `src/horizon/preferences.json`.
- API port: written to `~/.horizon/api.port` while the app is running.
- Tests: no automated test suite exists yet; validate changes manually and with lightweight checks.

## Quick Verification

```powershell
python -m compileall src
python -m horizon
```

For data-layer checks, prefer a temporary database path rather than the user database under `~/.horizon/`.

## Architecture Snapshot

```text
UI Layer      -> src/horizon/widgets/     QWidget subclasses, no business logic
Data Layer    -> src/horizon/<entity>.py  Dataclasses + Repositories
Infra Layer   -> database.py, api_server.py, mcp_server.py
```

Data flow: user action -> Qt `Signal` -> widget method -> repository -> SQLite -> `commit()`.

Detailed architecture notes: [docs/architecture.md](docs/architecture.md)

## Critical Rules

- Follow the repository + dataclass pattern for domain entities.
- Keep business logic out of widgets; widgets should coordinate UI and delegate to repositories.
- Use Qt `Signal`s for inter-widget communication; do not pass callbacks.
- Keep import order: stdlib, third-party, then local `horizon` imports.
- For searchable entities, keep `search_index` synchronized.
- For tagged entities, sync tags through concrete `TagRepository` helpers.
- Commit repository mutations at the end of the operation.
- Do not autosave `Preferences` inside property setters; call `save()` explicitly where persistence is intended.
- Add schema changes to both `_DDL` and `_MIGRATIONS` in `src/horizon/database.py`.

Detailed patterns: [docs/agent-patterns.md](docs/agent-patterns.md)

## Current Search And Tag Scope

- Searchable entities: notes, tasks, projects.
- Tagged entities: notes, tasks.
- Note↔task links: `note_tasks`, synced from the `{task: …}` blocks of a note body by `src/horizon/note_task.py` (markdown notes only).
- Note formats: `notes.format` is `markdown` or `html` (WYSIWYG, CKEditor 5). Only `NoteRepository.convert_to_html` changes it, one way; see [docs/architecture.md](docs/architecture.md).
- Other repositories, such as deliverables, diagrams, folders, images, and deliverable templates, still follow the repository pattern and commit mutations, but do not currently sync tags or `search_index`.

## Common Workflows

- Adding a widget
- Adding a full entity
- Extending a repository
- Adding optional API/MCP surface

Detailed workflows: [docs/agent-workflows.md](docs/agent-workflows.md)

## Key Files

| File | Purpose |
|---|---|
| [src/horizon/app.py](src/horizon/app.py) | `MainWindow`, widget wiring, hotkeys, signal routing |
| [src/horizon/titlebar.py](src/horizon/titlebar.py) | Custom `TitleBar` + DPI-aware `native_hit_test` for frameless windows |
| [src/horizon/database.py](src/horizon/database.py) | SQLite connection, DDL, migrations, search index sync |
| [src/horizon/note.py](src/horizon/note.py) | Canonical `Note` dataclass + `NoteRepository` |
| [src/horizon/note_task.py](src/horizon/note_task.py) | `{task: …}` block syntax, `NoteTaskRepository`, note→task sync |
| [src/horizon/task.py](src/horizon/task.py) | Canonical enum-backed `Task` + `TaskRepository` |
| [src/horizon/task_filter.py](src/horizon/task_filter.py) | `TaskFilter` (JSON in `task_filters`); one `Default` row today, future saved views |
| [src/horizon/widgets/task_filters.py](src/horizon/widgets/task_filters.py) | `TaskFilterModel` (shared selection, 5 s debounced save) + `TaskFilterBar` used by the ALL TASKS and project boards |
| [src/horizon/note_window.py](src/horizon/note_window.py) | Detached note window, windowed and sticky (pinned) modes |
| [src/horizon/preferences.py](src/horizon/preferences.py) | Preferences properties and explicit persistence |
| [src/horizon/widgets/notes.py](src/horizon/widgets/notes.py) | Canonical list/detail widget example |
| [src/horizon/widgets/webeditor.py](src/horizon/widgets/webeditor.py) | `WebMarkdownEditor` (CodeMirror) and `WebHtmlEditor` (CKEditor 5), `horizon-image://` and `horizon-diagram://` schemes |
| [src/horizon/diagram.py](src/horizon/diagram.py) | `Diagram` (draw.io XML + PNG thumbnail + SVG shown in WYSIWYG notes) + `DiagramRepository` |
| [src/horizon/widgets/drawio.py](src/horizon/widgets/drawio.py) | `DrawioEditor`: online draw.io embed in an iframe, JSON protocol over QWebChannel |
| [src/horizon/api_server.py](src/horizon/api_server.py) | Local HTTP REST API using stdlib `http.server` |
| [src/horizon/mcp_server.py](src/horizon/mcp_server.py) | MCP server entry point |
| [pyproject.toml](pyproject.toml) | Dependencies and script entry points |

## What Not To Do

- Do not put business logic inside widgets.
- Do not use callbacks for inter-widget communication.
- Do not use `from horizon.widgets import *`; import specific symbols.
- Do not silently swallow exceptions except in known migration cases.
- Do not add columns to `_DDL` without a matching migration.
- Do not hand-edit bundled minified resources unless explicitly requested.
- Do not hand-edit `src/horizon/resources/*.bundle.{js,css}`; edit the source under `web/src/` and
  rebuild with `cd web && npm run build` (see [web/README.md](web/README.md)).
- Do not run destructive checks against the user's real `~/.horizon/horizon.db`.
