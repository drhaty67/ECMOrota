from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta

from ortools.sat.python import cp_model

from .models import Assignment, Duty, Interval, SolveResult, SolverInput, WeekendMode
from .validation import unavailable

EIGHT_AM = time(8)


def _day_interval(day) -> Interval:
    start = datetime.combine(day, EIGHT_AM)
    return Interval(start, start + timedelta(days=1))


def _blocked(data: SolverInput, consultant: str, interval: Interval) -> bool:
    return any(item.consultant == consultant and item.interval.overlaps(interval) for item in data.absences)


def flexible_pre_solver_validation(data: SolverInput) -> list[str]:
    errors: list[str] = []
    weeks = len(data.weeks)
    if sum(c.t_target for c in data.consultants) * 4 != weeks * 4:
        errors.append("T targets do not equal the required four T days per rota week.")
    if sum(c.weekend_target for c in data.consultants) != weeks:
        errors.append("Weekend targets do not equal the number of rota weekends.")
    required_c = sum(len(week.c_dates[duty]) for week in data.weeks for duty in (Duty.C1, Duty.C2))
    if sum(c.c_day_target for c in data.consultants) > required_c:
        errors.append(f"C targets exceed the {required_c} non-bank-holiday C days available.")
    split = [c for c in data.consultants if c.weekend_mode != WeekendMode.STANDARD]
    if len(split) == 1:
        errors.append("At least two split-weekend consultants are required.")
    for week in data.weeks:
        for offset in range(4):
            day = week.start + timedelta(days=offset)
            if not any(not _blocked(data, c.name, _day_interval(day)) for c in data.consultants):
                errors.append(f"No consultant is available for T on {day}.")
        for duty in (Duty.C1, Duty.C2):
            for day in week.c_dates[duty]:
                if not any(not _blocked(data, c.name, _day_interval(day)) for c in data.consultants):
                    errors.append(f"No consultant is available for {duty.value} on {day}.")
    return errors


def solve_flexible(data: SolverInput, time_limit_seconds: float = 30.0) -> SolveResult:
    diagnostics = flexible_pre_solver_validation(data)
    if diagnostics:
        return SolveResult("PRECHECK_FAILED", diagnostics=diagnostics, mode="FLEXIBLE_FALLBACK")

    model = cp_model.CpModel()
    consultants, weeks = range(len(data.consultants)), range(len(data.weeks))
    t_days = [(w, data.weeks[w].start + timedelta(days=offset)) for w in weeks for offset in range(4)]
    c_days = [(w, duty, day) for w in weeks for duty in (Duty.C1, Duty.C2) for day in data.weeks[w].c_dates[duty]]
    t = {(c, w, day): model.new_bool_var(f"t_{c}_{w}_{day}") for c in consultants for w, day in t_days}
    cvar = {(c, w, duty, day): model.new_bool_var(f"c_{c}_{w}_{duty.value}_{day}") for c in consultants for w, duty, day in c_days}
    vacancy = {(w, duty, day): model.new_bool_var(f"vac_{w}_{duty.value}_{day}") for w, duty, day in c_days}
    full = {(c, w): model.new_bool_var(f"weekend_{c}_{w}") for c in consultants for w in weeks}
    half_a = {(c, w): model.new_bool_var(f"half_a_{c}_{w}") for c in consultants for w in weeks}
    half_b = {(c, w): model.new_bool_var(f"half_b_{c}_{w}") for c in consultants for w in weeks}
    split = {w: model.new_bool_var(f"split_{w}") for w in weeks}
    t_work, c1_work, c2_work = {}, {}, {}

    for w in weeks:
        for _, day in [item for item in t_days if item[0] == w]:
            model.add_exactly_one(t[c, w, day] for c in consultants)
        for _, duty, day in [item for item in c_days if item[0] == w]:
            model.add(sum(cvar[c, w, duty, day] for c in consultants) + vacancy[w, duty, day] == 1)
        model.add(sum(full[c, w] for c in consultants) == 1 - split[w])
        model.add(sum(half_a[c, w] for c in consultants) == split[w])
        model.add(sum(half_b[c, w] for c in consultants) == split[w])

        for c, consultant in enumerate(data.consultants):
            t_work[c, w] = model.new_bool_var(f"t_work_{c}_{w}")
            c1_work[c, w] = model.new_bool_var(f"c1_work_{c}_{w}")
            c2_work[c, w] = model.new_bool_var(f"c2_work_{c}_{w}")
            model.add_max_equality(t_work[c, w], [t[c, w, day] for ww, day in t_days if ww == w])
            c1_vars = [cvar[c, w, Duty.C1, day] for ww, duty, day in c_days if ww == w and duty == Duty.C1]
            c2_vars = [cvar[c, w, Duty.C2, day] for ww, duty, day in c_days if ww == w and duty == Duty.C2]
            if c1_vars: model.add_max_equality(c1_work[c, w], c1_vars)
            else: model.add(c1_work[c, w] == 0)
            if c2_vars: model.add_max_equality(c2_work[c, w], c2_vars)
            else: model.add(c2_work[c, w] == 0)
            weekend_work = full[c, w] + half_a[c, w] + half_b[c, w]
            model.add(half_a[c, w] + half_b[c, w] <= 1)
            model.add(t_work[c, w] + c1_work[c, w] <= 1)
            model.add(t_work[c, w] + c2_work[c, w] <= 1)
            model.add(t_work[c, w] + weekend_work <= 1)
            model.add(c1_work[c, w] + c2_work[c, w] <= 1)
            model.add(c2_work[c, w] + weekend_work <= 1)

            if consultant.weekend_mode == WeekendMode.STANDARD:
                model.add(half_a[c, w] == 0); model.add(half_b[c, w] == 0)
            elif consultant.weekend_mode == WeekendMode.REQUIRED:
                model.add(full[c, w] == 0)
            if unavailable(data, consultant.name, w, Duty.WEEKEND.value): model.add(full[c, w] == 0)
            if unavailable(data, consultant.name, w, "HALF_A"): model.add(half_a[c, w] == 0)
            if unavailable(data, consultant.name, w, "HALF_B"): model.add(half_b[c, w] == 0)

    for c, consultant in enumerate(data.consultants):
        model.add(sum(t[c, w, day] for w, day in t_days) == consultant.t_target * 4)
        model.add(sum(cvar[c, w, duty, day] for w, duty, day in c_days) == consultant.c_day_target)
        model.add(sum(2 * full[c, w] + half_a[c, w] + half_b[c, w] for w in weeks) == consultant.weekend_target * 2)
        if consultant.weekend_mode == WeekendMode.REQUIRED:
            model.add(sum(half_a[c, w] for w in weeks) == sum(half_b[c, w] for w in weeks))
        for w, day in t_days:
            if _blocked(data, consultant.name, _day_interval(day)): model.add(t[c, w, day] == 0)
        for w, duty, day in c_days:
            if _blocked(data, consultant.name, _day_interval(day)): model.add(cvar[c, w, duty, day] == 0)
        for w in range(len(data.weeks) - 1):
            this_weekend = full[c, w] + half_a[c, w] + half_b[c, w]
            next_weekend = full[c, w + 1] + half_a[c, w + 1] + half_b[c, w + 1]
            model.add(t_work[c, w] + t_work[c, w + 1] <= 1)
            model.add(t_work[c, w] + next_weekend <= 1)
            model.add(this_weekend + t_work[c, w + 1] <= 1)
            if consultant.weekend_mode == WeekendMode.STANDARD:
                model.add(this_weekend + next_weekend <= 1)

    consultant_index = {item.name: i for i, item in enumerate(data.consultants)}
    week_index = {item.start: i for i, item in enumerate(data.weeks)}
    penalties = []
    for pref in data.preferences:
        c, w = consultant_index[pref.consultant], week_index[pref.week_start]
        if pref.duty == Duty.T: works = t_work[c, w]
        elif pref.duty == Duty.C1: works = c1_work[c, w]
        elif pref.duty == Duty.C2: works = c2_work[c, w]
        elif pref.duty == Duty.WEEKEND:
            works = model.new_bool_var(f"pref_weekend_{c}_{w}")
            model.add_max_equality(works, [full[c, w], half_a[c, w], half_b[c, w]])
        else:
            works = model.new_bool_var(f"pref_any_{c}_{w}")
            model.add_max_equality(works, [t_work[c, w], c1_work[c, w], c2_work[c, w], full[c, w], half_a[c, w], half_b[c, w]])
        if pref.hard: model.add(works == int(pref.wants_work))
        else: penalties.append((1 - works if pref.wants_work else works) * pref.weight)

    # Prefer the fewest split structures after feasibility; vacancies dominate.
    fragmentation = sum(t_work.values()) + sum(c1_work.values()) + sum(c2_work.values())
    vacancy_penalty = 1000 * sum(vacancy.values())
    model.minimize(vacancy_penalty + 10 * fragmentation + sum(penalties))
    engine = cp_model.CpSolver()
    engine.parameters.max_time_in_seconds = time_limit_seconds
    engine.parameters.num_search_workers = 8
    status = engine.solve(model)
    status_name = engine.status_name(status)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return SolveResult(status_name, diagnostics=["The split-duty fallback also found no solution without relaxing other hard constraints."], mode="FLEXIBLE_FALLBACK")

    assignments: list[Assignment] = []
    for c, consultant in enumerate(data.consultants):
        for w, week in enumerate(data.weeks):
            t_dates = tuple(day for ww, day in t_days if ww == w and engine.value(t[c, w, day]))
            if t_dates: assignments.append(Assignment(week.start, "T", consultant.name, duty_dates=t_dates, t_block_credit=len(t_dates) / 4, flexible=True))
            for duty in (Duty.C1, Duty.C2):
                dates = tuple(day for ww, dd, day in c_days if ww == w and dd == duty and engine.value(cvar[c, w, duty, day]))
                if dates: assignments.append(Assignment(week.start, duty.value, consultant.name, c_day_credit=len(dates), duty_dates=dates, flexible=True))
            if engine.value(full[c, w]): assignments.append(Assignment(week.start, "WEEKEND", consultant.name, credit=1.0, flexible=True))
            if engine.value(half_a[c, w]): assignments.append(Assignment(week.start, "HALF_A", consultant.name, credit=0.5, flexible=True))
            if engine.value(half_b[c, w]): assignments.append(Assignment(week.start, "HALF_B", consultant.name, credit=0.5, flexible=True))
    for w, duty, day in c_days:
        if engine.value(vacancy[w, duty, day]):
            assignments.append(Assignment(data.weeks[w].start, duty.value, "VACANCY", c_day_credit=1, duty_dates=(day,), flexible=True))
    return SolveResult(status_name, assignments, engine.objective_value, mode="FLEXIBLE_FALLBACK")


def validate_flexible_solution(data: SolverInput, assignments: list[Assignment]) -> list[str]:
    errors: list[str] = []
    by_consultant = defaultdict(list)
    coverage = defaultdict(list)
    week_index = {week.start: week.index for week in data.weeks}
    for row in assignments:
        if row.duty in ("T", "C1", "C2"):
            for day in row.duty_dates: coverage[(row.duty, day)].append(row.consultant)
        if row.consultant != "VACANCY": by_consultant[row.consultant].append(row)
    for week in data.weeks:
        for offset in range(4):
            day = week.start + timedelta(days=offset)
            if len(coverage[("T", day)]) != 1: errors.append(f"{day}: expected exactly one T consultant.")
        for duty in (Duty.C1, Duty.C2):
            for day in week.c_dates[duty]:
                if len(coverage[(duty.value, day)]) != 1: errors.append(f"{day}: expected exactly one {duty.value} assignment.")
        weekend_rows = [row for row in assignments if row.week_start == week.start and row.duty in ("WEEKEND", "HALF_A", "HALF_B")]
        if abs(sum(row.credit for row in weekend_rows) - 1.0) > 1e-9: errors.append(f"{week.start}: weekend coverage is not exactly one credit.")
        if len({row.consultant for row in weekend_rows}) != len(weekend_rows): errors.append(f"{week.start}: split weekend components must use distinct consultants.")
    for consultant in data.consultants:
        rows = by_consultant[consultant.name]
        if abs(sum(r.t_block_credit for r in rows) - consultant.t_target) > 1e-9: errors.append(f"{consultant.name}: T credit does not match target.")
        if sum(r.c_day_credit for r in rows) != consultant.c_day_target: errors.append(f"{consultant.name}: C-day credit does not match target.")
        if abs(sum(r.credit for r in rows) - consultant.weekend_target) > 1e-9: errors.append(f"{consultant.name}: weekend credit does not match target.")
        half_a_count = sum(r.duty == "HALF_A" for r in rows); half_b_count = sum(r.duty == "HALF_B" for r in rows)
        if consultant.weekend_mode == WeekendMode.STANDARD and (half_a_count or half_b_count): errors.append(f"{consultant.name}: standard consultant received split weekend work.")
        if consultant.weekend_mode == WeekendMode.REQUIRED:
            if any(r.duty == "WEEKEND" for r in rows): errors.append(f"{consultant.name}: split consultant received a full weekend.")
            if half_a_count != half_b_count: errors.append(f"{consultant.name}: split half credits are unbalanced.")
        indexed = defaultdict(set)
        for row in rows:
            w = week_index[row.week_start]; indexed[w].add(row.duty)
            intervals = [_day_interval(day) for day in row.duty_dates] if row.duty in ("T", "C1", "C2") else []
            if row.duty == "WEEKEND": intervals = [data.weeks[w].duties[Duty.WEEKEND]]
            elif row.duty == "HALF_A": intervals = list(data.weeks[w].half_a)
            elif row.duty == "HALF_B": intervals = [data.weeks[w].half_b]
            if any(_blocked(data, consultant.name, interval) for interval in intervals): errors.append(f"{consultant.name}: {row.duty} overlaps absence/NOC.")
        for w, duties in indexed.items():
            weekend = bool(duties & {"WEEKEND", "HALF_A", "HALF_B"})
            if "T" in duties and (bool(duties & {"C1", "C2"}) or weekend): errors.append(f"{consultant.name}: prohibited same-week T combination.")
            if {"C1", "C2"} <= duties or ("C2" in duties and weekend): errors.append(f"{consultant.name}: prohibited C combination.")
            if w + 1 in indexed:
                nxt = indexed[w + 1]; next_weekend = bool(nxt & {"WEEKEND", "HALF_A", "HALF_B"})
                if "T" in duties and ("T" in nxt or next_weekend): errors.append(f"{consultant.name}: prohibited T adjacency.")
                if weekend and "T" in nxt: errors.append(f"{consultant.name}: prohibited weekend-to-T adjacency.")
                if consultant.weekend_mode == WeekendMode.STANDARD and weekend and next_weekend: errors.append(f"{consultant.name}: consecutive standard weekends.")
    return errors
