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
    def create_solver_run(self, record: dict) -> str: ...
    def finish_solver_run(self, run_id: str, record: dict) -> None: ...
    def save_draft(self, run_id: str, assignments: list[dict], validation: list[str]) -> str: ...
    def finalise_draft(self, draft_id: str) -> None: ...
    def get_draft(self, draft_id: str) -> dict: ...


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
            state = json.loads(self.path.read_text())
            state.setdefault("bank_holidays", [])
            if "solver not connected" in str(state.get("generation", {}).get("status", "")).casefold():
                state["generation"] = {"last_run": None, "status": "Not generated", "assignments": []}
                self.save(state)
            return state
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

    def create_solver_run(self, record: dict) -> str:
        from uuid import uuid4
        state = self.load(); run_id = uuid4().hex
        state.setdefault("solver_runs", []).append({"id": run_id, **record})
        self.save(state); return run_id

    def finish_solver_run(self, run_id: str, record: dict) -> None:
        state = self.load()
        run = next(item for item in state.setdefault("solver_runs", []) if item["id"] == run_id)
        run.update(record); self.save(state)

    def save_draft(self, run_id: str, assignments: list[dict], validation: list[str]) -> str:
        from uuid import uuid4
        state = self.load(); draft_id = uuid4().hex
        state.setdefault("drafts", []).append({"id": draft_id, "run_id": run_id, "status": "Draft", "assignments": assignments, "validation": validation})
        state["generation"] = {"last_run": next((r.get("finished_at") for r in state["solver_runs"] if r["id"] == run_id), None), "status": "Draft generated", "assignments": assignments, "draft_id": draft_id}
        self.save(state); return draft_id

    def finalise_draft(self, draft_id: str) -> None:
        from datetime import datetime, timezone
        state = self.load()
        draft = next(item for item in state.setdefault("drafts", []) if item["id"] == draft_id)
        if draft.get("validation"):
            raise StorageError("A draft with validation errors cannot be finalised.")
        if state.get("period", {}).get("status") == "Finalised":
            raise StorageError("This rota period is already finalised.")
        draft.update(status="Finalised", finalised_at=datetime.now(timezone.utc).isoformat())
        state["period"]["status"] = "Finalised"
        state["generation"].update(status="Finalised", assignments=draft["assignments"], draft_id=draft_id)
        self.save(state)

    def get_draft(self, draft_id: str) -> dict:
        state = self.load()
        return next(item for item in state.setdefault("drafts", []) if str(item["id"]) == str(draft_id))


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
            holidays = self.client.table("bank_holidays").select("id,holiday_date,name").eq("workspace_id", self.workspace_id).order("holiday_date").execute().data or []
            state["bank_holidays"] = [{"id": str(item["id"]), "date": item["holiday_date"], "name": item.get("name", "Bank holiday")} for item in holidays]
            # Draft history is append-only and deliberately loaded separately from
            # the inherited configuration-state RPC.
            drafts = self.client.table("rota_drafts").select("*").eq("workspace_id", self.workspace_id).order("created_at", desc=True).execute().data or []
            state["drafts"] = drafts
            if drafts:
                chosen = next((d for d in drafts if d.get("status") == "Finalised"), drafts[0])
                rows = self.client.table("assignments").select("consultant_id,week_commencing,assignment_type,weekend_credit,c_day_credit,duty_dates,t_block_credit,flexible").eq("draft_id", chosen["id"]).execute().data or []
                state["generation"] = {"last_run": chosen.get("created_at"), "status": chosen.get("status", "Draft"),
                                       "assignments": rows, "draft_id": str(chosen["id"])}
            elif "solver not connected" in str(state.get("generation", {}).get("status", "")).casefold():
                # Discard a status written by the pre-integration scaffold. It is
                # not a solver run and must not be presented as current state.
                state["generation"] = {"last_run": None, "status": "Not generated", "assignments": []}
            return state
        except Exception as exc:
            raise StorageError(f"Could not load rota data from Supabase: {exc}") from exc

    def save(self, state: dict) -> None:
        try:
            self.client.rpc(
                "save_rota_configuration",
                {"p_workspace_id": self.workspace_id, "p_state": state},
            ).execute()
            self.client.table("bank_holidays").delete().eq("workspace_id", self.workspace_id).execute()
            holidays = [{"id": item.get("id"), "workspace_id": self.workspace_id, "holiday_date": item["date"], "name": item.get("name", "Bank holiday")} for item in state.get("bank_holidays", [])]
            if holidays:
                self.client.table("bank_holidays").insert(holidays).execute()
        except Exception as exc:
            raise StorageError(f"Could not save rota data to Supabase: {exc}") from exc

    def reset(self) -> dict:
        state = default_state()
        self.save(state)
        return state

    def create_solver_run(self, record: dict) -> str:
        try:
            row = {"workspace_id": self.workspace_id, **record}
            return str(self.client.table("solver_runs").insert(row).execute().data[0]["id"])
        except Exception as exc:
            raise StorageError(f"Could not create solver run: {exc}") from exc

    def finish_solver_run(self, run_id: str, record: dict) -> None:
        try:
            self.client.table("solver_runs").update(record).eq("id", run_id).execute()
        except Exception as exc:
            raise StorageError(f"Could not update solver run: {exc}") from exc

    def save_draft(self, run_id: str, assignments: list[dict], validation: list[str]) -> str:
        try:
            draft = self.client.table("rota_drafts").insert({"workspace_id": self.workspace_id, "solver_run_id": run_id, "status": "Draft", "validation": validation}).execute().data[0]
            draft_id = str(draft["id"])
            rows = [{"workspace_id": self.workspace_id, "draft_id": draft_id, **item} for item in assignments]
            if rows: self.client.table("assignments").insert(rows).execute()
            return draft_id
        except Exception as exc:
            raise StorageError(f"Could not persist generated draft: {exc}") from exc

    def finalise_draft(self, draft_id: str) -> None:
        try:
            self.client.rpc("finalise_rota_draft", {"p_workspace_id": self.workspace_id, "p_draft_id": draft_id}).execute()
        except Exception as exc:
            raise StorageError(f"Could not finalise draft: {exc}") from exc

    def get_draft(self, draft_id: str) -> dict:
        try:
            draft = self.client.table("rota_drafts").select("*").eq("id", draft_id).single().execute().data
            draft["assignments"] = self.client.table("assignments").select("consultant_id,week_commencing,assignment_type,weekend_credit,c_day_credit,duty_dates,t_block_credit,flexible").eq("draft_id", draft_id).execute().data or []
            return draft
        except Exception as exc:
            raise StorageError(f"Could not load draft: {exc}") from exc


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
