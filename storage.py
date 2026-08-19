from __future__ import annotations

import json
from pathlib import Path

from .models import default_state


class JsonStore:
    """Small persistence adapter; replace with a Supabase implementation later."""

    def __init__(self, path: str | Path = "data/rota_state.json") -> None:
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            state = default_state()
            self.save(state)
            return state
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            state = default_state()
            self.save(state)
            return state

    def save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2))
        temp.replace(self.path)

    def reset(self) -> dict:
        state = default_state()
        self.save(state)
        return state

