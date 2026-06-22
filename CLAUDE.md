# CLAUDE.md

This file is read by Claude (and compatible agents) when working on this repository.  
**All coding instructions are in [AGENTS.md](AGENTS.md).** Read it fully before making any changes.

---

## Claude-specific tips

- **Repository + Dataclass is the single most important pattern.** Every new entity follows it. When in doubt, read [src/horizon/note.py](src/horizon/note.py) as the canonical reference.
- **PySide6 requires care.** Always pass `parent` in widget constructors. Always declare `Signal` at class level with an explicit type. Never instantiate Qt objects outside of a running `QApplication`.
- **Schema changes require two edits:** add the table/column to `_DDL` in `database.py` AND add an `ALTER TABLE` to the `_MIGRATIONS` list in the same file.
- **Prefer asking over guessing** when introducing a brand-new entity type or a cross-cutting architectural change. The codebase is consistent — a misfit pattern will stand out.
- **No tests exist.** Validate changes by tracing the data flow mentally: Widget → Repository → DB → commit → Signal back.
