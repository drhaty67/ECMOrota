from __future__ import annotations

from datetime import date, timedelta


HARD_CONSTRAINTS = [
    "A consultant cannot work T in consecutive rota weeks.",
    "Standard full-weekend duties cannot be assigned in consecutive weekends.",
    "A T block cannot immediately precede or follow a weekend duty.",
    "T cannot be combined in the same week with C1, C2 or Weekend.",
    "C1 and C2 cannot be combined in the same week.",
    "C1 + Weekend is allowed; C2 + Weekend is prohibited.",
    "C1/C2 blocks may repeat in consecutive weeks.",
    "Annual leave, study leave and NOC block overlapping C1, C2, T and Weekend duties.",
    "An absence beginning Monday does not block the immediately preceding weekend.",
    "Split-mode consultants receive split weekends only: ½A is Friday + Sunday and ½B is Saturday.",
    "Each split consultant must receive equal numbers of ½A and ½B across the rota period.",
    "Consecutive split weekends are allowed; all other T/weekend and availability rules still apply.",
]


def mondays(start: date, end: date) -> list[date]:
    first = start + timedelta(days=(7 - start.weekday()) % 7)
    result = []
    cursor = first
    while cursor <= end:
        result.append(cursor)
        cursor += timedelta(days=7)
    return result


def readiness(state: dict) -> list[dict]:
    checks: list[dict] = []
    period = state.get("period", {})
    try:
        start = date.fromisoformat(period.get("start", ""))
        end = date.fromisoformat(period.get("end", ""))
        days = (end - start).days + 1
        checks.append({"ok": end > start and 150 <= days <= 215, "label": "Rota period", "detail": f"{days} days configured; expected roughly six months (150–215 days)."})
    except ValueError:
        start = end = date.today()
        checks.append({"ok": False, "label": "Rota period", "detail": "Choose valid start and end dates."})
    active = [c for c in state.get("consultants", []) if c.get("active")]
    checks.append({"ok": bool(active), "label": "Active consultants", "detail": f"{len(active)} active consultant(s)."})
    targets = state.get("targets", {})
    missing = [c["name"] for c in active if sum(int(targets.get(c["id"], {}).get(k, 0)) for k in ("t", "weekend", "c")) == 0]
    checks.append({"ok": not missing, "label": "Workload targets", "detail": "All active consultants have targets." if not missing else "No targets for: " + ", ".join(missing)})
    invalid_absences = [a for a in state.get("absences", []) if a.get("start", "") > a.get("end", "")]
    checks.append({"ok": not invalid_absences, "label": "Availability entries", "detail": "All date ranges are valid." if not invalid_absences else f"{len(invalid_absences)} invalid date range(s)."})
    special = state.get("special", {})
    active_ids = {c["id"] for c in active}
    split = [c for c in active if special.get(c["id"], {}).get("weekend_mode") == "Split"]
    bad_partners = [c["name"] for c in split if any(p not in active_ids or p == c["id"] for p in special.get(c["id"], {}).get("partner_ids", []))]
    odd_targets = [c["name"] for c in split if int(targets.get(c["id"], {}).get("weekend", 0)) < 1]
    ok = len(split) != 1 and not bad_partners and not odd_targets
    detail = f"{len(split)} split-mode consultant(s); balanced ½A/½B components will be required."
    if len(split) == 1: detail = "At least two split-mode consultants are required."
    elif bad_partners: detail = "Invalid split partner selection for: " + ", ".join(bad_partners)
    elif odd_targets: detail = "Split mode requires a positive weekend target for: " + ", ".join(odd_targets)
    checks.append({"ok": ok, "label": "Split-weekend configuration", "detail": detail})
    return checks

