from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from .models import default_state


class Store(Protocol):
    backend_name: str
    def load(self) -> dict: ...
    def save(self, state: dict) -> None: ...
    def reset(self) -> dict: ...


class StorageError(RuntimeError):
    """A persistence operation failed."""


class JsonStore:
    """Small persistence adapter; replace with a Supabase implementation later."""

    def __init__(self, path: str | Path = "data/rota_state.json") -> None:
        self.path = Path(path)
        self.backend_name = "Local JSON"

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


class SupabaseStore:
    """Supabase adapter backed by transactional PostgreSQL RPC functions."""

    backend_name = "Supabase"

    def __init__(self, url: str, key: str, workspace_id: str = "default") -> None:
        if not url or not key:
            raise StorageError("Supabase URL and secret key are required.")
        try:
            from supabase import create_client
        except ImportError as exc:
            raise StorageError("Install the 'supabase' dependency before using Supabase.") from exc
        self.client = create_client(url, key)
        self.workspace_id = workspace_id or "default"

    def load(self) -> dict:
        try:
            response = self.client.rpc(
                "load_rota_state", {"p_workspace_id": self.workspace_id}
            ).execute()
            state = response.data
            if not state:
                state = default_state()
                self.save(state)
            return state
        except Exception as exc:
            raise StorageError(f"Could not load rota data from Supabase: {exc}") from exc

    def save(self, state: dict) -> None:
        try:
            self.client.rpc(
                "save_rota_state",
                {"p_workspace_id": self.workspace_id, "p_state": state},
            ).execute()
        except Exception as exc:
            raise StorageError(f"Could not save rota data to Supabase: {exc}") from exc

    def reset(self) -> dict:
        state = default_state()
        self.save(state)
        return state


def build_store(secrets: dict | None = None) -> Store:
    """Select Supabase when configured, otherwise retain local development mode."""
    supplied = {} if secrets is None else secrets
    try:
        section = supplied.get("supabase", {}) if hasattr(supplied, "get") else {}
    except FileNotFoundError:
        section = {}
    url = section.get("url") or os.getenv("SUPABASE_URL")
    key = section.get("service_role_key") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    workspace_id = section.get("workspace_id") or os.getenv("SUPABASE_WORKSPACE_ID", "default")
    if url or key:
        return SupabaseStore(url or "", key or "", workspace_id)
    return JsonStore()
