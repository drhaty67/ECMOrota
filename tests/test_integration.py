from datetime import date

from rota_app.input_builder import InputBuildError, build_solver_input
from rota_app.service import generate_draft, prepare
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
    assert result["status"] in ("SUCCEEDED", "VALIDATION_FAILED"), result
    assert not result["errors"], result
    saved = repo.load()
    assert saved["drafts"][0]["assignments"]
    assert {a["assignment_type"] for a in saved["drafts"][0]["assignments"]} <= {"C1", "C2", "T", "STANDARD_WEEKEND", "SPLIT_HALF_A", "SPLIT_HALF_B"}
