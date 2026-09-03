# Horizon

A personal productivity desktop app for Windows, built with Python and PySide6 (Qt).  
Manage notes, tasks, projects, deliverables, and calendar — all in one place, stored locally in SQLite.

---

## Features

- **Notes** — Rich Markdown editor with live preview, version history, tags, and folder organization
- **Tasks** — Kanban-style task management with subtasks, priorities, buckets, and states
- **Projects** — Group notes, tasks, folders, and deliverables per project
- **Deliverables** — Track work outputs with templates and state lifecycle
- **Tags** — Auto-extracted `#hashtags` from note/task body, searchable globally
- **Full-text search** — FTS5-powered search across notes, tasks, and projects
- **Calendar** — Outlook calendar integration (reads meetings via `win32com`)
- **Themes** — Dark, Light, Synthwave
- **HTTP API** — Local REST API for external integrations (port stored in `~/.horizon/api.port`)
- **MCP server** — Model Context Protocol server for AI agent integration

---

## Requirements

- Python 3.11+
- Windows (required for `pywin32` hotkeys and Outlook calendar integration)

---

## Setup

```powershell
# 1. Clone the repo
git clone <repo-url>
cd Horizon

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install in editable mode
pip install -e .
```

The SQLite database is created automatically on first launch at `~/.horizon/horizon.db`.  
No manual schema initialization is needed.

---

## Running

```powershell
# Launch the desktop app
horizon

# Or, equivalently
python -m horizon
```

The local HTTP API starts automatically alongside the app (default port in `~/.horizon/api.port`).

To run the MCP server separately (for AI agent integration):

```powershell
horizon-mcp
```

---

## Building a Windows executable

Every push to `main` and every pull request triggers
[`.github/workflows/build.yml`](.github/workflows/build.yml), which freezes the app with
PyInstaller on a Windows runner and uploads `Horizon-<version>-win64.zip` as a workflow
artifact. Tagging a commit `v*` additionally attaches that zip to a GitHub Release.

To reproduce the build locally:

```powershell
pip install . -r requirements-build.txt
python tools/make_icon.py          # optional, produces build/horizon.ico
pyinstaller --noconfirm horizon.spec
.\dist\Horizon\Horizon.exe
```

The build is `--onedir`, not `--onefile`: the app loads its resources into a
`QWebEngineView` through `file://` URLs, which onefile re-extracts to a temp directory on
every launch. Expect roughly 570 MB unpacked (~210 MB zipped), most of it QtWebEngine.

Dependencies are constrained at two levels: [`pyproject.toml`](pyproject.toml) carries
version bounds so a fresh `pip install -e .` cannot pull an incompatible release (mcp 2.x
dropped the low-level API `mcp_server.py` uses), while
[`requirements-build.txt`](requirements-build.txt) pins exact versions so two builds of the
same commit produce the same executable. Bump a version there, let CI pass, and launch the
resulting exe before merging.

Resources resolved at runtime via `Path(__file__).parent` must be declared in
[`horizon.spec`](horizon.spec) — if you add a directory next to the Python modules that is
read from disk (rather than through the Qt resource system in `resources.qrc`), add it to
`datas` there too.

---

## Architecture

```
UI Layer          │  src/horizon/widgets/   — PySide6 QWidget components
Data Layer        │  src/horizon/*.py       — Dataclasses + Repositories (SQLite)
Infrastructure    │  api_server.py          — HTTP REST API (stdlib http.server)
                  │  mcp_server.py          — MCP server
                  │  database.py            — SQLite connection + DDL + migrations
```

Data flow: **User action → Qt Signal → Widget → Repository → SQLite**

---

## Project Structure

```
src/horizon/
├── app.py                   # MainWindow — top-level orchestration
├── database.py              # Database class, DDL, migrations
├── api_server.py            # Local HTTP REST API
├── mcp_server.py            # MCP server entry point
├── preferences.py           # User preferences (JSON)
├── <entity>.py              # Dataclass + Repository per entity
│   (note, task, project, deliverable, tag, folder, image, search…)
├── widgets/
│   ├── __init__.py          # Public widget exports
│   ├── notes.py             # NotesListWidget, NoteDetailWidget
│   ├── project.py           # ProjectListWidget, ProjectDetailWidget
│   ├── deliverables.py      # Deliverable widgets
│   ├── calendar.py          # CalendarMeeting widget
│   └── …
├── themes/                  # dark.json, light.json, synthwave.json
└── resources/               # Bundled JS/CSS (highlight.js, mermaid)
```

---

## Contributing

See [AGENTS.md](AGENTS.md) for coding conventions, architecture patterns, and step-by-step guides for adding new features — written for both human contributors and AI coding agents.
