"""Horizon task blocks embedded in note markdown.

Authoring syntax, title on the first line and an optional description below:

    {task: Rédiger le cadrage}

    {task: Préparer le COPIL
    Slides + relevé de décisions}

On an explicit save the block is persisted as a real task in the note's project
and rewritten to its id — ``{task: 42}`` — which is what the renderer then turns
into a status glyph and a clickable title.

This module is the single source of truth for the syntax: both the persistence
side (widgets/notes.py) and the rendering side (widgets/markdown.py) import from
here. It stays Qt-free, like the rest of the data layer.
"""

import re
from typing import Callable

from horizon.database import Database

# Braces are excluded from the body so a stray "}" cannot swallow the rest of
# the note — same limitation as {#tag}.
_TASK_BLOCK_RE = re.compile(r'\{task:\s*([^{}]*?)\s*\}')

# Fenced code regions, so a documented example never becomes a real task
_FENCE_RE = re.compile(
    r'^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$',
    re.MULTILINE | re.DOTALL,
)


def split_title_description(raw: str) -> tuple[str, str]:
    """Split a block body into its title (first line) and description (rest)."""
    title, _, description = raw.partition('\n')
    return title.strip(), description.strip()


def sub_outside_code(repl: Callable[[re.Match], str], body: str) -> str:
    """Apply `repl` to every task block that is not inside a fenced code region."""
    out: list[str] = []
    pos = 0
    for fence in _FENCE_RE.finditer(body):
        out.append(_TASK_BLOCK_RE.sub(repl, body[pos:fence.start()]))
        out.append(fence.group(0))
        pos = fence.end()
    out.append(_TASK_BLOCK_RE.sub(repl, body[pos:]))
    return ''.join(out)


def parse_task_ids(body: str) -> list[int]:
    """Ids of the already-persisted task blocks in `body`, in order of appearance."""
    ids: list[int] = []

    def collect(m: re.Match) -> str:
        raw = m.group(1).strip()
        if raw.isdigit():
            ids.append(int(raw))
        return m.group(0)

    sub_outside_code(collect, body)
    return ids


def build_task_render_map(body: str, task_repo) -> dict[int, tuple[str, str]]:
    """Map ``{id: (title, state)}`` for the task blocks of `body` that still exist.

    Archived tasks are included: archiving is not deletion, so they keep showing
    their title and status. Ids of deleted tasks are simply absent, which is what
    makes the renderer fall back to displaying the bare id.
    """
    info: dict[int, tuple[str, str]] = {}
    for task_id in parse_task_ids(body):
        if task_id in info:
            continue
        task = task_repo.get(task_id)
        if task is not None:
            info[task_id] = (task.title, task.state.value)
    return info


class NoteTaskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def set_for_note(self, note_id: int, task_ids: list[int]) -> None:
        self._db.conn.execute(
            "DELETE FROM note_tasks WHERE note_id = ?", (note_id,)
        )
        for task_id in task_ids:
            # A block may reference a task that has since been deleted; the FK
            # would raise rather than be absorbed by OR IGNORE, so filter here.
            self._db.conn.execute(
                "INSERT OR IGNORE INTO note_tasks (note_id, task_id)"
                " SELECT ?, ? WHERE EXISTS (SELECT 1 FROM tasks WHERE id = ?)",
                (note_id, task_id, task_id),
            )
        self._db.conn.commit()

    def list_task_ids_for_note(self, note_id: int) -> list[int]:
        rows = self._db.conn.execute(
            "SELECT task_id FROM note_tasks WHERE note_id = ? ORDER BY task_id",
            (note_id,),
        ).fetchall()
        return [row["task_id"] for row in rows]

    def list_note_ids_for_task(self, task_id: int) -> list[int]:
        rows = self._db.conn.execute(
            "SELECT note_id FROM note_tasks WHERE task_id = ? ORDER BY note_id",
            (task_id,),
        ).fetchall()
        return [row["note_id"] for row in rows]


def sync_note_tasks(
    body: str,
    note_id: int,
    project_id: int | None,
    task_repo,
    note_task_repo: NoteTaskRepository,
) -> str:
    """Persist the task blocks of `body` and return the rewritten markdown.

    Tasks are created in the note's project. A note with no project is skipped
    silently: nothing is created, nothing is unlinked, the markdown is untouched.
    """
    if project_id is None:
        return body

    linked: list[int] = []

    def replace(m: re.Match) -> str:
        raw = m.group(1).strip()
        if raw.isdigit():
            linked.append(int(raw))
            return m.group(0)
        title, description = split_title_description(raw)
        if not title:
            return m.group(0)
        task = task_repo.create(
            project_id=project_id,
            title=title[:255],
            description=description,
        )
        linked.append(task.id)
        return f"{{task: {task.id}}}"

    new_body = sub_outside_code(replace, body)
    note_task_repo.set_for_note(note_id, linked)
    return new_body
