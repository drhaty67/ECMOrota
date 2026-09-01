from __future__ import annotations

from ortools.sat.python import cp_model

from .models import Duty, SolverInput, WeekendMode
from .validation import unavailable


def add_hard_constraints(model: cp_model.CpModel, data: SolverInput, variables: dict) -> None:
    x, half_a, half_b, split_weekend, vacancy = (variables[k] for k in ("x", "half_a", "half_b", "split_weekend", "vacancy"))
    consultants = range(len(data.consultants))
    weeks = range(len(data.weeks))

    for w in weeks:
        for duty in (Duty.C1, Duty.C2, Duty.T):
            if duty in (Duty.C1, Duty.C2):
                if data.weeks[w].c_dates[duty]:
                    model.add(sum(x[c, w, duty] for c in consultants) + vacancy[w, duty] == 1)
                else:
                    model.add(vacancy[w, duty] == 0)
                    for c in consultants:
                        model.add(x[c, w, duty] == 0)
            else:
                model.add_exactly_one(x[c, w, duty] for c in consultants)
        model.add(sum(x[c, w, Duty.WEEKEND] for c in consultants) == 1 - split_weekend[w])
        model.add(sum(half_a[c, w] for c in consultants) == split_weekend[w])
        model.add(sum(half_b[c, w] for c in consultants) == split_weekend[w])
        for c in consultants:
            model.add(half_a[c, w] + half_b[c, w] <= 1)

    for c, consultant in enumerate(data.consultants):
        model.add(sum(x[c, w, Duty.T] for w in weeks) == consultant.t_target)
        model.add(
            sum(x[c, w, Duty.WEEKEND] * 2 + half_a[c, w] + half_b[c, w] for w in weeks)
            == consultant.weekend_target * 2
        )
        model.add(sum(
            len(data.weeks[w].c_dates[Duty.C1]) * x[c, w, Duty.C1]
            + len(data.weeks[w].c_dates[Duty.C2]) * x[c, w, Duty.C2]
            for w in weeks
        ) == consultant.c_day_target)

        if consultant.weekend_mode == WeekendMode.STANDARD:
            for w in weeks:
                model.add(half_a[c, w] == 0)
                model.add(half_b[c, w] == 0)
        elif consultant.weekend_mode == WeekendMode.REQUIRED:
            for w in weeks:
                model.add(x[c, w, Duty.WEEKEND] == 0)
            model.add(sum(half_a[c, w] for w in weeks) == sum(half_b[c, w] for w in weeks))

        for w in weeks:
            weekend_work = x[c, w, Duty.WEEKEND] + half_a[c, w] + half_b[c, w]
            model.add(x[c, w, Duty.T] + x[c, w, Duty.C1] <= 1)
            model.add(x[c, w, Duty.T] + x[c, w, Duty.C2] <= 1)
            model.add(x[c, w, Duty.T] + weekend_work <= 1)
            model.add(x[c, w, Duty.C1] + x[c, w, Duty.C2] <= 1)
            model.add(x[c, w, Duty.C2] + weekend_work <= 1)

            for duty in Duty:
                if unavailable(data, consultant.name, w, duty.value):
                    model.add(x[c, w, duty] == 0)
            if unavailable(data, consultant.name, w, "HALF_A"):
                model.add(half_a[c, w] == 0)
            if unavailable(data, consultant.name, w, "HALF_B"):
                model.add(half_b[c, w] == 0)

        for w in range(len(data.weeks) - 1):
            this_weekend = x[c, w, Duty.WEEKEND] + half_a[c, w] + half_b[c, w]
            next_weekend = x[c, w + 1, Duty.WEEKEND] + half_a[c, w + 1] + half_b[c, w + 1]
            model.add(x[c, w, Duty.T] + x[c, w + 1, Duty.T] <= 1)
            model.add(x[c, w, Duty.T] + next_weekend <= 1)
            model.add(this_weekend + x[c, w + 1, Duty.T] <= 1)
            if consultant.weekend_mode == WeekendMode.STANDARD:
                model.add(this_weekend + next_weekend <= 1)

    for preference in data.preferences:
        if not preference.hard:
            continue
        c = next(i for i, item in enumerate(data.consultants) if item.name == preference.consultant)
        w = next(i for i, item in enumerate(data.weeks) if item.start == preference.week_start)
        duties = (preference.duty,) if preference.duty else tuple(Duty)
        for duty in duties:
            model.add(x[c, w, duty] == int(preference.wants_work))
