from __future__ import annotations

from ortools.sat.python import cp_model

from .models import Duty, SolverInput


def add_soft_objective(model: cp_model.CpModel, data: SolverInput, variables: dict) -> None:
    penalties = []
    x, half_a, half_b, vacancy = variables["x"], variables["half_a"], variables["half_b"], variables["vacancy"]
    consultant_index = {c.name: i for i, c in enumerate(data.consultants)}
    week_index = {w.start: i for i, w in enumerate(data.weeks)}

    for pref in data.preferences:
        if pref.hard:
            continue
        c, w = consultant_index[pref.consultant], week_index[pref.week_start]
        if pref.duty is None:
            works = model.new_bool_var(f"works_{c}_{w}")
            relevant = [x[c, w, duty] for duty in Duty] + [half_a[c, w], half_b[c, w]]
            model.add_max_equality(works, relevant)
        elif pref.duty == Duty.WEEKEND:
            works = model.new_bool_var(f"weekend_pref_{c}_{w}")
            model.add_max_equality(works, [x[c, w, Duty.WEEKEND], half_a[c, w], half_b[c, w]])
        else:
            works = x[c, w, pref.duty]
        penalties.append((1 - works if pref.wants_work else works) * pref.weight)

    for c, consultant in enumerate(data.consultants):
        preferred = {consultant_index[name] for name in consultant.preferred_split_partners if name in consultant_index}
        if preferred:
            for w in range(len(data.weeks)):
                for partner in range(len(data.consultants)):
                    if partner in preferred or partner == c:
                        continue
                    for own_half, partner_half, label in (
                        (half_a[c, w], half_b[partner, w], "ab"),
                        (half_b[c, w], half_a[partner, w], "ba"),
                    ):
                        mismatch = model.new_bool_var(f"partner_mismatch_{c}_{partner}_{w}_{label}")
                        model.add(mismatch <= own_half)
                        model.add(mismatch <= partner_half)
                        model.add(mismatch >= own_half + partner_half - 1)
                        penalties.append(mismatch)

    # Vacancy days are unavoidable when aggregate C-day targets are below coverage.
    # Prefer fewer vacant blocks when the same number of vacant days can be represented differently.
    vacancy_penalty = 100 * sum(vacancy[w, duty] for w in range(len(data.weeks)) for duty in (Duty.C1, Duty.C2))
    model.minimize(vacancy_penalty + sum(penalties))
