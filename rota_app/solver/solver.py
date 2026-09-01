from __future__ import annotations

from ortools.sat.python import cp_model

from .constraints import add_hard_constraints
from .models import Assignment, Duty, SolveResult, SolverInput
from .objective import add_soft_objective
from .validation import pre_solver_validation


SOLVER_VERSION = "1.3.0-flexible-fallback"


def solve(data: SolverInput, time_limit_seconds: float = 30.0) -> SolveResult:
    diagnostics = pre_solver_validation(data)
    if diagnostics:
        return SolveResult(status="PRECHECK_FAILED", diagnostics=diagnostics)

    model = cp_model.CpModel()
    c_count, w_count = len(data.consultants), len(data.weeks)
    variables = {
        "x": {(c, w, duty): model.new_bool_var(f"x_{c}_{w}_{duty.value}") for c in range(c_count) for w in range(w_count) for duty in Duty},
        "half_a": {(c, w): model.new_bool_var(f"half_a_{c}_{w}") for c in range(c_count) for w in range(w_count)},
        "half_b": {(c, w): model.new_bool_var(f"half_b_{c}_{w}") for c in range(c_count) for w in range(w_count)},
        "split_weekend": {w: model.new_bool_var(f"split_{w}") for w in range(w_count)},
        "vacancy": {(w, duty): model.new_bool_var(f"vacancy_{w}_{duty.value}") for w in range(w_count) for duty in (Duty.C1, Duty.C2)},
    }
    add_hard_constraints(model, data, variables)
    add_soft_objective(model, data, variables)

    engine = cp_model.CpSolver()
    engine.parameters.max_time_in_seconds = time_limit_seconds
    engine.parameters.num_search_workers = 8
    status = engine.solve(model)
    status_name = engine.status_name(status)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return SolveResult(status=status_name, diagnostics=["CP-SAT found no solution under the complete hard-constraint model."])

    assignments: list[Assignment] = []
    x, half_a, half_b = variables["x"], variables["half_a"], variables["half_b"]
    for c, consultant in enumerate(data.consultants):
        for w, week in enumerate(data.weeks):
            for duty in Duty:
                if engine.value(x[c, w, duty]):
                    assignments.append(Assignment(
                        week.start, duty.value, consultant.name,
                        credit=1.0 if duty == Duty.WEEKEND else 0.0,
                        c_day_credit=len(week.c_dates[duty]) if duty in (Duty.C1, Duty.C2) else 0,
                        duty_dates=week.c_dates[duty] if duty in (Duty.C1, Duty.C2) else (),
                        t_block_credit=1.0 if duty == Duty.T else 0.0,
                    ))
            if engine.value(half_a[c, w]):
                assignments.append(Assignment(week.start, "HALF_A", consultant.name, credit=0.5))
            if engine.value(half_b[c, w]):
                assignments.append(Assignment(week.start, "HALF_B", consultant.name, credit=0.5))
    for w, week in enumerate(data.weeks):
        for duty in (Duty.C1, Duty.C2):
            if engine.value(variables["vacancy"][w, duty]):
                assignments.append(Assignment(
                    week.start, duty.value, "VACANCY", c_day_credit=len(week.c_dates[duty]),
                    duty_dates=week.c_dates[duty],
                ))
    return SolveResult(status=status_name, assignments=assignments, objective_value=engine.objective_value)
