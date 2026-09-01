from datetime import date
from pathlib import Path
from unittest.mock import patch

from rota_app.input_builder import InputBuildError, build_solver_input
from rota_app.service import generate_draft, prepare
from rota_app.solver.models import Assignment, Duty, SolveResult
from rota_app.solver.validation import unavailable
from rota_app.storage import JsonStore


def six_month_state():
    people = [{"id": f"c{i}", "name": f"Consultant {i}", "email": "", "active": True} for i in range(8)]
    # 27 weeks. Totals exactly cover 27 T blocks, 27 weekend credits and 135 C days.
    t = [4, 4, 4, 3, 3, 3, 3, 3]
    weekends = [4, 4, 4, 3, 3, 3, 3, 3]
    c_days = [17, 17, 17, 17, 17, 17, 17, 16]
    return {
        "period": {"name": "Oct 2026 – May 2027", "start": "2026-10-26", "end": "2027-05-02", "status": "Draft"},
        "consultants": people, "absences": [], "preferences": [],
        "bank_holidays": [],
        "targets": {p["id"]: {"t": t[i], "weekend": weekends[i], "c": c_days[i]} for i, p in enumerate(people)},
        "special": {p["id"]: {"weekend_mode": "Standard", "partner_ids": [], "notes": ""} for p in people},
        "generation": {"last_run": None, "status": "Not generated", "assignments": []}, "solver_runs": [], "drafts": [],
    }


def test_builder_rejects_unknown_consultant_reference():
    state = six_month_state()
    state["absences"] = [{"id": "a1", "consultant_id": "missing", "type": "NOC", "start": "2026-11-01", "end": "2026-11-01"}]
    try:
        build_solver_input(state)
    except InputBuildError as exc:
        assert "unknown or inactive" in str(exc)
    else:
        raise AssertionError("unknown consultant was accepted")


def test_exact_six_month_precheck():
    data, errors = prepare(six_month_state())
    assert not errors
    assert len(data.weeks) == 27


def test_end_to_end_dry_run_persists_normalized_draft(tmp_path):
    repo = JsonStore(tmp_path / "state.json")
    state = six_month_state(); repo.save(state)
    result = generate_draft(state, repo, time_limit_seconds=20)
    assert result["status"] == "SUCCEEDED", result
    assert not result["errors"], result
    saved = repo.load()
    assert saved["drafts"][0]["assignments"]
    assert {a["assignment_type"] for a in saved["drafts"][0]["assignments"]} <= {"C1", "C2", "T", "STANDARD_WEEKEND", "SPLIT_HALF_A", "SPLIT_HALF_B"}


def bank_holiday_state():
    state = six_month_state()
    state["period"].update(start="2026-10-26", end="2027-04-25")
    state["bank_holidays"] = [
        {"id": "bh1", "date": "2026-12-25", "name": "Christmas Day"},
        {"id": "bh2", "date": "2026-12-28", "name": "Boxing Day substitute"},
        {"id": "bh3", "date": "2027-01-01", "name": "New Year's Day"},
        {"id": "bh4", "date": "2027-04-02", "name": "Good Friday"},
        {"id": "bh5", "date": "2027-04-05", "name": "Easter Monday"},
    ]
    t = [3, 3, 3, 3, 3, 4, 3, 4]
    weekends = [4, 3, 3, 3, 3, 3, 4, 3]
    c_days = [18, 23, 18, 9, 6, 15, 18, 18]
    for index, person in enumerate(state["consultants"]):
        state["targets"][person["id"]] = {"t": t[index], "weekend": weekends[index], "c": c_days[index]}
    return state


def test_bank_holidays_reduce_c_coverage_to_125_days():
    data, errors = prepare(bank_holiday_state())
    assert not errors, errors
    assert sum(len(week.c_dates[duty]) for week in data.weeks for duty in (Duty.C1, Duty.C2)) == 125
    christmas_week = next(week for week in data.weeks if week.start.isoformat() == "2026-12-21")
    assert len(christmas_week.c_dates[Duty.C2]) == 2
    easter_week = next(week for week in data.weeks if week.start.isoformat() == "2027-04-05")
    assert [day.isoformat() for day in easter_week.c_dates[Duty.C1]] == ["2027-04-06"]


def test_bank_holiday_end_to_end_has_no_c_vacancies(tmp_path):
    repo = JsonStore(tmp_path / "state.json")
    state = bank_holiday_state(); repo.save(state)
    result = generate_draft(state, repo, time_limit_seconds=30)
    assert result["status"] == "SUCCEEDED", result
    c_rows = [row for row in result["assignments"] if row["assignment_type"] in ("C1", "C2")]
    assert sum(row["c_day_credit"] for row in c_rows if row["consultant_id"]) == 125
    assert all(row["consultant_id"] for row in c_rows)
    easter_c1 = next(row for row in c_rows if row["week_commencing"] == "2027-04-05" and row["assignment_type"] == "C1")
    assert easter_c1["c_day_credit"] == 1
    assert easter_c1["duty_dates"] == ["2027-04-06"]


def test_absence_boundaries_are_strict_for_every_duty_component():
    state = six_month_state()
    consultant_id = state["consultants"][0]["id"]
    state["absences"] = [
        {"id": "al", "consultant_id": consultant_id, "type": "Annual leave", "start": "2026-11-02", "end": "2026-11-02"},
        {"id": "sl", "consultant_id": consultant_id, "type": "Study leave", "start": "2026-11-06", "end": "2026-11-06"},
        {"id": "noc-sat", "consultant_id": consultant_id, "type": "NOC", "start": "2026-11-07", "end": "2026-11-07"},
        {"id": "noc-sun", "consultant_id": consultant_id, "type": "NOC", "start": "2026-11-08", "end": "2026-11-08"},
    ]
    data = build_solver_input(state)
    name = state["consultants"][0]["name"]
    week = next(item for item in data.weeks if item.start.isoformat() == "2026-11-02")
    assert unavailable(data, name, week.index, "C1")
    assert unavailable(data, name, week.index, "C2")
    assert unavailable(data, name, week.index, "T")
    assert unavailable(data, name, week.index, "WEEKEND")
    assert unavailable(data, name, week.index, "HALF_A")
    assert unavailable(data, name, week.index, "HALF_B")
    previous = data.weeks[week.index - 1]
    assert not unavailable(data, name, previous.index, "WEEKEND")


def test_invalid_solver_output_is_never_persisted(tmp_path):
    repo = JsonStore(tmp_path / "state.json")
    state = six_month_state(); repo.save(state)
    invalid = SolveResult(status="OPTIMAL", assignments=[Assignment(date(2026, 10, 26), "C1", "Consultant 0", c_day_credit=2)])
    with patch("rota_app.service.solve", return_value=invalid):
        result = generate_draft(state, repo)
    assert result["status"] == "VALIDATION_FAILED"
    assert result["draft_id"] is None
    assert repo.load()["drafts"] == []


def flexible_fallback_state():
    people = [{"id": f"c{i}", "name": f"Consultant {i}", "email": "", "active": True} for i in range(8)]
    state = {
        "period": {"name": "Four-week fallback test", "start": "2026-10-26", "end": "2026-11-22", "status": "Draft"},
        "consultants": people, "absences": [], "bank_holidays": [],
        "preferences": [
            {"id": "p1", "consultant_id": "c0", "week": "2026-10-26", "direction": "Must work", "scope": "T", "priority": "High", "notes": ""},
            {"id": "p2", "consultant_id": "c0", "week": "2026-11-09", "direction": "Must work", "scope": "T", "priority": "High", "notes": ""},
        ],
        "targets": {},
        "special": {p["id"]: {"weekend_mode": "Standard", "partner_ids": [], "notes": ""} for p in people},
        "generation": {"last_run": None, "status": "Not generated", "assignments": []}, "solver_runs": [], "drafts": [],
    }
    t_targets = [1, 1, 1, 1, 0, 0, 0, 0]
    weekend_targets = [0, 0, 0, 0, 1, 1, 1, 1]
    c_targets = [2, 2, 2, 2, 3, 3, 3, 3]
    for index, person in enumerate(people):
        state["targets"][person["id"]] = {"t": t_targets[index], "weekend": weekend_targets[index], "c": c_targets[index]}
    return state


def test_flexible_fallback_runs_only_after_strict_infeasibility(tmp_path):
    state = flexible_fallback_state()
    strict_repo = JsonStore(tmp_path / "strict.json"); strict_repo.save(state)
    strict = generate_draft(state, strict_repo, time_limit_seconds=10, allow_flexible_fallback=False)
    assert strict["status"] == "INFEASIBLE"
    assert strict_repo.load()["drafts"] == []

    flexible_repo = JsonStore(tmp_path / "flexible.json"); flexible_repo.save(state)
    result = generate_draft(state, flexible_repo, time_limit_seconds=10, allow_flexible_fallback=True)
    assert result["status"] == "SUCCEEDED", result
    assert result["solve_mode"] == "FLEXIBLE_FALLBACK"
    consultant_t = [row for row in result["assignments"] if row["consultant_id"] == "c0" and row["assignment_type"] == "T"]
    assert len(consultant_t) == 2
    assert abs(sum(row["t_block_credit"] for row in consultant_t) - 1.0) < 1e-9
    assert all(row["flexible"] for row in result["assignments"])


def test_enabled_fallback_does_not_replace_feasible_strict_solution(tmp_path):
    state = bank_holiday_state()
    repo = JsonStore(tmp_path / "strict_first.json"); repo.save(state)
    result = generate_draft(state, repo, time_limit_seconds=20, allow_flexible_fallback=True)
    assert result["status"] == "SUCCEEDED", result
    assert result["solve_mode"] == "STRICT"
    assert not any(row["flexible"] for row in result["assignments"])


def test_audit_safe_migration_never_deletes_generation_history():
    sql = (Path(__file__).parents[1] / "supabase" / "audit_safe_configuration_v5.sql").read_text().casefold()
    assert "delete from solver_runs" not in sql
    assert "delete from rota_drafts" not in sql
    assert "delete from assignments" not in sql
    assert "save_rota_configuration" in sql
