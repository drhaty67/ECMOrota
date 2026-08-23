from __future__ import annotations

from collections import defaultdict

from .models import Duty, SolverInput, WeekendMode


def unavailable(data: SolverInput, consultant: str, week_index: int, component: str) -> bool:
    week = data.weeks[week_index]
    if component == "HALF_A":
        intervals = week.half_a
    elif component == "HALF_B":
        intervals = (week.half_b,)
    else:
        intervals = (week.duties[Duty(component)],)
    return any(
        absence.consultant == consultant
        and any(absence.interval.overlaps(interval) for interval in intervals)
        for absence in data.absences
    )


def pre_solver_validation(data: SolverInput) -> list[str]:
    errors: list[str] = []
    week_count = len(data.weeks)
    total_t = sum(c.t_target for c in data.consultants)
    total_weekends = sum(c.weekend_target for c in data.consultants)
    total_c_days = sum(c.c_day_target for c in data.consultants)
    required_c_days = 5 * week_count
    if total_t != week_count:
        errors.append(f"T target/coverage mismatch: targets total {total_t}; {week_count} weekly T blocks require {week_count}.")
    if total_weekends != week_count:
        errors.append(f"Weekend target/coverage mismatch: targets total {total_weekends}; {week_count} weekends require {week_count} credits.")
    if total_c_days > required_c_days:
        errors.append(f"C-day targets exceed coverage: targets total {total_c_days}; {week_count} C1+C2 weeks provide {required_c_days} C days.")
    else:
        gap = required_c_days - total_c_days
        representable = any(2 * c1 + 3 * c2 == gap for c1 in range(week_count + 1) for c2 in range(week_count + 1))
        if not representable:
            errors.append(f"C-day vacancy gap {gap} cannot be represented by whole C1 (2-day) and C2 (3-day) blocks.")

    for duty in (Duty.C1, Duty.C2, Duty.T):
        for week in data.weeks:
            candidates = [c.name for c in data.consultants if not unavailable(data, c.name, week.index, duty.value)]
            if not candidates:
                errors.append(f"No available candidate for {duty.value} in week {week.start}.")

    split = [c for c in data.consultants if c.weekend_mode != WeekendMode.STANDARD]
    if len(split) == 1:
        errors.append(f"Split weekend configuration has only one eligible consultant ({split[0].name}); every split weekend requires two distinct split consultants.")

    attainable_c_days = defaultdict(set)
    for consultant in data.consultants:
        attainable_c_days[consultant.name].add(0)
        for week in data.weeks:
            prior = set(attainable_c_days[consultant.name])
            if not unavailable(data, consultant.name, week.index, Duty.C1.value):
                attainable_c_days[consultant.name].update(value + 2 for value in prior)
            if not unavailable(data, consultant.name, week.index, Duty.C2.value):
                attainable_c_days[consultant.name].update(value + 3 for value in prior)
        if consultant.c_day_target not in attainable_c_days[consultant.name]:
            errors.append(f"{consultant.name}: C-day target {consultant.c_day_target} is unattainable from available 2-day C1 and 3-day C2 blocks.")
    return errors


def validate_solution(data: SolverInput, assignments: list) -> list[str]:
    errors: list[str] = []
    by_week_duty = defaultdict(list)
    by_consultant = defaultdict(list)
    for assignment in assignments:
        by_week_duty[(assignment.week_start, assignment.duty)].append(assignment)
        if assignment.consultant != "VACANCY":
            by_consultant[assignment.consultant].append(assignment)
    for week in data.weeks:
        for duty in ("C1", "C2", "T"):
            if len(by_week_duty[(week.start, duty)]) != 1:
                errors.append(f"{week.start} {duty}: expected one assignment.")
        weekend_rows = by_week_duty[(week.start, "WEEKEND")] + by_week_duty[(week.start, "HALF_A")] + by_week_duty[(week.start, "HALF_B")]
        if sum(row.credit for row in weekend_rows) != 1.0:
            errors.append(f"{week.start} weekend: expected 1.0 total credit.")
        if len({row.consultant for row in weekend_rows}) != len(weekend_rows):
            errors.append(f"{week.start} weekend: split components must use distinct consultants.")

    week_lookup = {week.start: week for week in data.weeks}
    for consultant in data.consultants:
        rows = by_consultant[consultant.name]
        t_actual = sum(row.duty == "T" for row in rows)
        weekend_actual = sum(row.credit for row in rows)
        c_actual = sum(2 if row.duty == "C1" else 3 if row.duty == "C2" else 0 for row in rows)
        if (t_actual, weekend_actual, c_actual) != (consultant.t_target, consultant.weekend_target, consultant.c_day_target):
            errors.append(f"{consultant.name}: actual T/WE/C {t_actual}/{weekend_actual}/{c_actual} does not match target {consultant.t_target}/{consultant.weekend_target}/{consultant.c_day_target}.")
        half_a_count = sum(row.duty == "HALF_A" for row in rows)
        half_b_count = sum(row.duty == "HALF_B" for row in rows)
        if consultant.weekend_mode == WeekendMode.STANDARD and (half_a_count or half_b_count):
            errors.append(f"{consultant.name}: standard consultant received split work.")
        if consultant.weekend_mode == WeekendMode.REQUIRED:
            if any(row.duty == "WEEKEND" for row in rows):
                errors.append(f"{consultant.name}: required-split consultant received a full weekend.")
            if half_a_count != half_b_count:
                errors.append(f"{consultant.name}: split halves are unbalanced ({half_a_count} A, {half_b_count} B).")

        indexed = defaultdict(set)
        for row in rows:
            indexed[week_lookup[row.week_start].index].add(row.duty)
            component = row.duty if row.duty in ("HALF_A", "HALF_B") else row.duty
            if unavailable(data, consultant.name, week_lookup[row.week_start].index, component):
                errors.append(f"{consultant.name}: {row.duty} on {row.week_start} overlaps an absence.")
        for index, duties in indexed.items():
            has_weekend = bool(duties & {"WEEKEND", "HALF_A", "HALF_B"})
            prohibited = (
                ("T" in duties and bool(duties & {"C1", "C2"}))
                or ("T" in duties and has_weekend)
                or ({"C1", "C2"} <= duties)
                or ("C2" in duties and has_weekend)
            )
            if prohibited:
                errors.append(f"{consultant.name}: prohibited same-week combination in week {data.weeks[index].start}.")
            if index + 1 in indexed:
                next_duties = indexed[index + 1]
                next_weekend = bool(next_duties & {"WEEKEND", "HALF_A", "HALF_B"})
                if "T" in duties and ("T" in next_duties or next_weekend):
                    errors.append(f"{consultant.name}: prohibited T adjacency after {data.weeks[index].start}.")
                if has_weekend and "T" in next_duties:
                    errors.append(f"{consultant.name}: prohibited weekend-to-T adjacency after {data.weeks[index].start}.")
                if consultant.weekend_mode == WeekendMode.STANDARD and has_weekend and next_weekend:
                    errors.append(f"{consultant.name}: consecutive standard weekends after {data.weeks[index].start}.")
    return errors
