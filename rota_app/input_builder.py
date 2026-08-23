from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .solver.models import (
    Absence, Consultant, Duty, Interval, RotaWeek, SolverInput,
    WeekPreference, WeekendMode,
)

EIGHT_AM = time(8)


class InputBuildError(ValueError):
    pass


def _weeks(start: date, end: date) -> list[RotaWeek]:
    if start.weekday() != 0 or end.weekday() != 6:
        raise InputBuildError("Rota period must start on Monday and end on Sunday.")
    result = []
    cursor = start
    while cursor <= end:
        mon = datetime.combine(cursor, EIGHT_AM)
        wed, fri, sat, sun, next_mon = (mon + timedelta(days=n) for n in (2, 4, 5, 6, 7))
        result.append(RotaWeek(
            index=len(result), start=cursor,
            duties={Duty.C1: Interval(mon, wed), Duty.C2: Interval(wed, fri),
                    Duty.T: Interval(mon, fri), Duty.WEEKEND: Interval(fri, next_mon)},
            half_a=(Interval(fri, sat), Interval(sun, next_mon)),
            half_b=Interval(sat, sun),
        ))
        cursor += timedelta(days=7)
    return result


def build_solver_input(state: dict) -> SolverInput:
    """Translate repository domain records into the solver's typed contract."""
    try:
        start = date.fromisoformat(state["period"]["start"])
        end = date.fromisoformat(state["period"]["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InputBuildError("The rota period contains invalid or missing dates.") from exc

    people = [c for c in state.get("consultants", []) if c.get("active")]
    ids = {c["id"]: c for c in people}
    if not people:
        raise InputBuildError("At least one active consultant is required.")

    consultants = []
    for person in people:
        target = state.get("targets", {}).get(person["id"])
        if target is None:
            raise InputBuildError(f"Missing workload target for {person['name']}.")
        setting = state.get("special", {}).get(person["id"], {})
        partner_ids = setting.get("partner_ids", [])
        unknown = [value for value in partner_ids if value not in ids]
        if unknown:
            raise InputBuildError(f"{person['name']} has unknown/inactive split partner IDs: {', '.join(unknown)}.")
        consultants.append(Consultant(
            name=person["name"], t_target=int(target["t"]),
            weekend_target=int(target["weekend"]), c_day_target=int(target["c"]),
            weekend_mode=WeekendMode.REQUIRED if setting.get("weekend_mode") == "Split" else WeekendMode.STANDARD,
            preferred_split_partners=[ids[value]["name"] for value in partner_ids],
        ))

    absences = []
    for item in state.get("absences", []):
        if item.get("consultant_id") not in ids:
            raise InputBuildError(f"Absence {item.get('id', '')} references an unknown or inactive consultant.")
        try:
            first, last = date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
        except (KeyError, ValueError) as exc:
            raise InputBuildError(f"Absence {item.get('id', '')} has invalid dates.") from exc
        if last < first:
            raise InputBuildError(f"Absence {item.get('id', '')} ends before it starts.")
        absences.append(Absence(
            request_id=item.get("id", ""), consultant=ids[item["consultant_id"]]["name"],
            kind=item.get("type", ""),
            interval=Interval(datetime.combine(first, EIGHT_AM), datetime.combine(last + timedelta(days=1), EIGHT_AM)),
            note=item.get("notes", ""),
        ))

    weeks = _weeks(start, end)
    week_dates = {week.start for week in weeks}
    preferences = []
    weights = {"Low": 3, "Normal": 10, "High": 30}
    for item in state.get("preferences", []):
        if item.get("consultant_id") not in ids:
            raise InputBuildError(f"Preference {item.get('id', '')} references an unknown or inactive consultant.")
        try:
            week = date.fromisoformat(item["week"])
        except (KeyError, ValueError) as exc:
            raise InputBuildError(f"Preference {item.get('id', '')} has an invalid week date.") from exc
        if week not in week_dates:
            raise InputBuildError(f"Preference {item.get('id', '')} is outside the rota period or not a Monday.")
        scope = item.get("scope", "Any")
        duty = None if scope == "Any" else Duty.WEEKEND if scope == "Weekend" else Duty(scope)
        direction = item.get("direction", "Wants to work")
        preferences.append(WeekPreference(
            consultant=ids[item["consultant_id"]]["name"], week_start=week, duty=duty,
            wants_work=direction in ("Wants to work", "Must work"),
            hard=direction in ("Must work", "Must not work"),
            weight=weights.get(item.get("priority", "Normal"), 10), note=item.get("notes", ""),
        ))

    return SolverInput(start, end, consultants, absences, weeks, preferences)
