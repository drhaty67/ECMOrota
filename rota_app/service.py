from __future__ import annotations

from datetime import datetime, timezone
import platform

from .input_builder import InputBuildError, build_solver_input
from .solver import SOLVER_VERSION, solve
from .solver.validation import pre_solver_validation, validate_solution


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prepare(state: dict):
    try:
        data = build_solver_input(state)
    except InputBuildError as exc:
        return None, [str(exc)]
    return data, pre_solver_validation(data)


def generate_draft(state: dict, repository, time_limit_seconds: float = 30.0) -> dict:
    started = _now()
    metadata = {"status": "RUNNING", "started_at": started, "solver_version": SOLVER_VERSION,
                "configuration": {"time_limit_seconds": time_limit_seconds},
                "runtime": {"python": platform.python_version()}}
    run_id = repository.create_solver_run(metadata)
    try:
        data, errors = prepare(state)
        if errors:
            result = {"status": "PRECHECK_FAILED", "finished_at": _now(), "error_message": "\n".join(errors)}
            repository.finish_solver_run(run_id, result)
            return {"run_id": run_id, "draft_id": None, "errors": errors, **result}
        solved = solve(data, time_limit_seconds)
        if solved.status not in ("FEASIBLE", "OPTIMAL"):
            errors = solved.diagnostics or [f"Solver ended with status {solved.status}."]
            result = {"status": solved.status, "finished_at": _now(), "error_message": "\n".join(errors)}
            repository.finish_solver_run(run_id, result)
            return {"run_id": run_id, "draft_id": None, "errors": errors, **result}
        validation = validate_solution(data, solved.assignments)
        id_by_name = {c["name"]: c["id"] for c in state["consultants"]}
        assignments = [{
            "consultant_id": id_by_name.get(a.consultant), "week_commencing": a.week_start.isoformat(),
            "assignment_type": {"WEEKEND": "STANDARD_WEEKEND", "HALF_A": "SPLIT_HALF_A", "HALF_B": "SPLIT_HALF_B"}.get(a.duty, a.duty),
            "weekend_credit": a.credit,
        } for a in solved.assignments]
        result = {"status": "SUCCEEDED" if not validation else "VALIDATION_FAILED", "finished_at": _now(),
                  "objective_value": solved.objective_value, "error_message": "\n".join(validation) or None}
        repository.finish_solver_run(run_id, result)
        draft_id = repository.save_draft(run_id, assignments, validation)
        return {"run_id": run_id, "draft_id": draft_id, "assignments": assignments,
                "errors": validation, **result}
    except Exception as exc:
        result = {"status": "ERROR", "finished_at": _now(), "error_message": str(exc)}
        repository.finish_solver_run(run_id, result)
        return {"run_id": run_id, "draft_id": None, "errors": [str(exc)], **result}
