import json
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Theme:
    name: str
    tile_bg: str
    tile_border: str
    tile_text: str
    tile_checkbox_border: str
    tile_checkbox_checked_bg: str
    tile_checkbox_checked_border: str
    tile_project_label: str
    priority_low: str
    priority_medium: str
    priority_high: str
    calendar_bg: str
    calendar_label: str
    calendar_hour_line: str
    calendar_half_hour_line: str
    calendar_event_bg: str
    calendar_event_text: str
    calendar_now_line: str
    clock_face: str
    clock_ring: str
    clock_tick_hour: str
    clock_tick_minute: str
    clock_hand: str
    clock_second: str
    color_btn_border: str
    delete_btn_text: str
    delete_btn_bg: str
    preview_text: str
    preview_bg: str
    preview_border: str
    preview_code_bg: str
    preview_blockquote_border: str
    preview_blockquote_text: str
    preview_link: str
    preview_table_header_bg: str


_current: Theme | None = None
_THEME_DIR = Path(__file__).parent / "themes"
_FIELD_NAMES = {f.name for f in fields(Theme)}


def load(name: str) -> Theme:
    path = _THEME_DIR / f"{name}.json"
    if not path.exists():
        path = _THEME_DIR / "dark.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Theme(**{k: v for k, v in data.items() if k in _FIELD_NAMES})


def init(name: str) -> None:
    global _current
    _current = load(name)


def current() -> Theme:
    if _current is None:
        raise RuntimeError("theme.init() has not been called")
    return _current
