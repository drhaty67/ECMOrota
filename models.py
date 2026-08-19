from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4


def uid() -> str:
    return uuid4().hex[:10]


def default_state() -> dict:
    today = date.today()
    start = today + timedelta(days=(7 - today.weekday()) % 7)
    end = start + timedelta(days=181)
    consultants = [
        {"id": uid(), "name": "Consultant A", "email": "", "active": True},
        {"id": uid(), "name": "Consultant B", "email": "", "active": True},
    ]
    return {
        "period": {"name": f"Rota {start:%b %Y} – {end:%b %Y}", "start": start.isoformat(), "end": end.isoformat(), "status": "Draft"},
        "consultants": consultants,
        "absences": [],
        "targets": {c["id"]: {"t": 0, "weekend": 0, "c": 0} for c in consultants},
        "preferences": [],
        "special": {c["id"]: {"weekend_mode": "Standard", "partner_ids": [], "notes": ""} for c in consultants},
        "generation": {"last_run": None, "status": "Not generated", "assignments": []},
    }


def copy_default() -> dict:
    return deepcopy(default_state())

