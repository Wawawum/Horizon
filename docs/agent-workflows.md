# Agent Workflows

Task-oriented implementation notes for agents working on Horizon. Start with [../AGENTS.md](../AGENTS.md) for the short guide.

---

## Add A New Widget

1. Create `src/horizon/widgets/<feature>.py`.
2. Define `<Feature>ListWidget(QWidget)` if the feature needs a list view.
3. Define `<Feature>DetailWidget(QWidget)` if the feature needs a detail/edit view.
4. Declare typed Qt signals as class-level attributes.
5. Inject repositories through constructors.
6. Use `load()` or `load(entity_id)` to populate UI state.
7. Export public widgets from [../src/horizon/widgets/__init__.py](../src/horizon/widgets/__init__.py).
8. Wire the widget in [../src/horizon/app.py](../src/horizon/app.py): instantiate repositories, connect signals, and add the view to the relevant stack/layout.

Reference widgets:
- [../src/horizon/widgets/notes.py](../src/horizon/widgets/notes.py)
- [../src/horizon/widgets/deliverables.py](../src/horizon/widgets/deliverables.py)
- [../src/horizon/widgets/project.py](../src/horizon/widgets/project.py)

---

## Add A New Entity

1. Create `src/horizon/<entity>.py` with a dataclass and repository.
2. Add table DDL to `_DDL` in [../src/horizon/database.py](../src/horizon/database.py).
3. Add migration SQL to `_MIGRATIONS` for existing databases.
4. Decide whether the entity is searchable. If yes, update `search_index` on create/update/delete.
5. Decide whether the entity is tagged. If yes, add concrete tag helpers in `TagRepository` and sync them in repository mutations.
6. Add list/detail widgets under `src/horizon/widgets/` if the entity has UI.
7. Export widgets from [../src/horizon/widgets/__init__.py](../src/horizon/widgets/__init__.py).
8. Wire repositories, widgets, and signals in [../src/horizon/app.py](../src/horizon/app.py).
9. Add API endpoints in [../src/horizon/api_server.py](../src/horizon/api_server.py) only if external access is required.
10. Add MCP tools in [../src/horizon/mcp_server.py](../src/horizon/mcp_server.py) only if AI-agent access is required.

---

## Extend A Repository

1. Add the method to the existing repository class.
2. Keep SQL parameterized.
3. Return dataclasses, primitives, or lists of dataclasses; avoid returning raw SQLite rows outside repositories.
4. Update `search_index` or tags only if the entity participates in those systems.
5. Commit at the end of mutations.
6. Keep read-only methods side-effect free.

---

## Add Or Extend API Endpoints

Horizon uses stdlib `http.server`, not Flask/FastAPI.

1. Add route regexes near the existing route constants in [../src/horizon/api_server.py](../src/horizon/api_server.py).
2. Parse request JSON defensively.
3. Use repositories for data access.
4. Return JSON with `_send_json(...)`.
5. Log unexpected failures with `logger.exception(...)`.
6. Keep the API aligned with MCP tools when the endpoint is meant for agent access.

---

## Add Or Extend MCP Tools

MCP tools live in [../src/horizon/mcp_server.py](../src/horizon/mcp_server.py) and call the local HTTP API.

1. Add the tool schema in `list_tools()`.
2. Handle the tool name in the call handler.
3. Validate required inputs before making HTTP calls.
4. Use `HORIZON_API_PORT` or `~/.horizon/api.port` through the existing `_base_url()` helper.
5. Return structured text or JSON that agents can consume reliably.

---

## Add Qt Resources

Qt resources are declared in [../src/horizon/resources.qrc](../src/horizon/resources.qrc) and compiled into [../src/horizon/resources_rc.py](../src/horizon/resources_rc.py).

When adding icons/fonts/resources:
- Add source files under the existing resource folders.
- Add entries to `resources.qrc`.
- Regenerate `resources_rc.py` using the PySide6 Qt resource compiler.
- Do not edit minified third-party assets by hand.
