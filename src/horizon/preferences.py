import json
from pathlib import Path


_PREFS_PATH = Path(__file__).parent / "preferences.json"


class Preferences:
    def __init__(self) -> None:
        self._data = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save(self) -> None:
        _PREFS_PATH.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    @property
    def window_size(self) -> tuple[int, int]:
        w = self._data.get("window", {})
        return w.get("width", 800), w.get("height", 600)

    @window_size.setter
    def window_size(self, value: tuple[int, int]) -> None:
        self._data.setdefault("window", {})
        self._data["window"]["width"] = value[0]
        self._data["window"]["height"] = value[1]

    @property
    def window_maximized(self) -> bool:
        return self._data.get("window", {}).get("maximized", False)

    @window_maximized.setter
    def window_maximized(self, value: bool) -> None:
        self._data.setdefault("window", {})
        self._data["window"]["maximized"] = value

    def get_project_view(self, project_id: int) -> int:
        return self._data.get("project_views", {}).get(str(project_id), 0)

    def set_project_view(self, project_id: int, index: int) -> None:
        self._data.setdefault("project_views", {})
        self._data["project_views"][str(project_id)] = index

    @property
    def splitter_sizes(self) -> list[int] | None:
        return self._data.get("splitter_sizes")

    @splitter_sizes.setter
    def splitter_sizes(self, value: list[int]) -> None:
        self._data["splitter_sizes"] = value

    @property
    def note_splitter_sizes(self) -> list[int] | None:
        return self._data.get("note_splitter_sizes")

    @note_splitter_sizes.setter
    def note_splitter_sizes(self, value: list[int]) -> None:
        self._data["note_splitter_sizes"] = value

    @property
    def theme(self) -> str:
        return self._data.get("theme", "dark")

    @theme.setter
    def theme(self, value: str) -> None:
        self._data["theme"] = value

    @property
    def api_port(self) -> int:
        return self._data.get("api", {}).get("port", 5555)

    @api_port.setter
    def api_port(self, value: int) -> None:
        self._data.setdefault("api", {})
        self._data["api"]["port"] = value

    @property
    def pin_hotkey(self) -> dict:
        default = {"modifiers": ["win", "ctrl"], "vk": 84}  # Win+Ctrl+T
        return self._data.get("pin_hotkey", default)

    @pin_hotkey.setter
    def pin_hotkey(self, value: dict) -> None:
        self._data["pin_hotkey"] = value
