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

## Note Windows And Sticky Notes

[../src/horizon/note_window.py](../src/horizon/note_window.py) hosts a `NoteDetailWidget` in a
standalone frameless `QMainWindow`. It has two modes, both opened from `MainWindow`:

| Mode | Trigger | Size preference |
|---|---|---|
| Windowed | `⧉ Fenêtre` | `note_window_size` |
| Sticky | `📌 Pense-bête` | `sticky_note_window_size` |

A note has **at most one** detached window, whichever mode was asked for first: `_note_windows`
is keyed by note id, and asking for the other mode raises the existing window. Two editors on
one note would diverge exactly the way the lock below exists to prevent.

Sticky mode is for taking notes during a meeting or a presentation. `NoteDetailWidget(sticky=True)`
keeps only the editor and the save indicator: the header row, the project/folder row, the
separator, the markdown formatting toolbar and the preview are all gone. The preview
`QWebEngineView` is **not constructed at all**, and `_do_render` returns early — rendering
markdown on every keystroke is the bulk of the per-edit cost and nothing would consume it.
Everything else (5 s autosave, `flush_and_save()` on close, `{task: …}` sync, Ctrl+S) is the
shared code path, unchanged.

There is no button to leave sticky mode: the note lives in its own window, so closing it is the
exit. Autofocus waits for `WebMarkdownEditor.editor_ready` — `call_js()` is inert until
CodeMirror has loaded, so focusing right after `show()` would be lost.

A sticky window is pinned above other windows on open. The pin is the Win32 mechanism already
behind the Win+Ctrl+T hotkey (`MainWindow._pin_hwnd` / `_unpin_hwnd`: `SetWindowPos(HWND_TOPMOST)`
plus a `PinBorderOverlay`), not a Qt window flag — `setWindowFlags()` after `show()` recreates the
native window on Windows and would drop the frameless `nativeEvent` handling. Because the overlay
is registered in the shared `_pin_borders` map, Win+Ctrl+T unpins a sticky note like any other
window, and closing it removes the border.

### One writer per note

Both `NoteDetailWidget`s — the one in the main stack and the one in the window — hold their own
`_current_note` and `_body_raw`, and nothing reconciles them. `NoteRepository.update` rewrites
*every* column from the in-memory object, so a stale main-stack copy overwrites the window's
work not just on a body edit but on any project, folder, title or archive change.

So while a window holds a note, the main panel is locked: `NoteDetailWidget.set_locked(True)`
puts the editor in read-only, shows a banner and disables the title field, both combos, the
archive checkbox, the delete button and the history button. The six persisting methods carry a
`_locked` guard as well — the widgets are disabled, but the cost of one write getting through is
lost data.

`_locked` is orthogonal to `_viewing_version` (browsing a historical version): both end in
read-only, with a different message and a different scope. `_apply_readonly()` is the single
place that resolves the two into a presentation.

Locking flushes the main panel *before* it takes effect, because the window reads the note from
the database immediately afterwards. `MainWindow` recomputes the lock whenever a note is loaded
into the panel (`_load_note_into_detail`) and whenever the set of windows changes — on open, on
close (`NoteWindow.closed`, emitted after `flush_and_save()`), and when a window follows a
`[[link]]` to another note (`NoteWindow.note_changed`, which re-keys the registry). On close the
panel reloads the note from the database and unlocks.

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
