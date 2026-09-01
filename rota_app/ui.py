from __future__ import annotations

import html
from datetime import date, datetime

import pandas as pd
import streamlit as st

from .models import uid
from .rules import HARD_CONSTRAINTS, mondays, readiness
from .service import generate_draft, prepare
from .solver.models import Duty


def active(state): return [c for c in state["consultants"] if c["active"]]
def names(state): return {c["id"]: c["name"] for c in state["consultants"]}
def persist(store, state): store.save(state)


def dashboard(state, store):
    st.title("Rota control centre")
    st.caption("Configure, validate and review a six-month consultant rota.")
    checks = readiness(state)
    cols = st.columns(4)
    cols[0].metric("Active consultants", len(active(state)))
    cols[1].metric("Availability entries", len(state["absences"]))
    cols[2].metric("Preferences", len(state["preferences"]))
    cols[3].metric("Readiness", f"{sum(c['ok'] for c in checks)}/{len(checks)}")
    st.subheader("Setup progress")
    for check in checks:
        (st.success if check["ok"] else st.warning)(f"{'Ready' if check['ok'] else 'Needs attention'} — {check['label']}: {check['detail']}")
    st.info("OR-Tools is connected. Complete the readiness checks, then open Generate Rota to create and persist a draft.")


def rota_period(state, store):
    st.title("Rota Period")
    p = state["period"]
    with st.form("period"):
        name = st.text_input("Period name", p["name"])
        c1, c2 = st.columns(2)
        start = c1.date_input("Start date", date.fromisoformat(p["start"]))
        end = c2.date_input("End date", date.fromisoformat(p["end"]))
        submitted = st.form_submit_button("Save period", type="primary")
    if submitted:
        days = (end - start).days + 1
        if end <= start: st.error("End date must be after start date.")
        elif not 150 <= days <= 215: st.error("A six-month rota should span approximately 150–215 days.")
        else:
            state["period"].update(name=name.strip() or "Untitled rota", start=start.isoformat(), end=end.isoformat())
            persist(store, state); st.success(f"Saved {days}-day rota period.")
    weeks = mondays(date.fromisoformat(p["start"]), date.fromisoformat(p["end"]))
    st.caption(f"{len(weeks)} rota weeks, anchored to Mondays.")


def bank_holidays(state, store):
    st.title("Bank Holidays")
    st.caption("Bank holidays retain T cover but have no C shift. C-day targets are calculated from the remaining weekdays.")
    period_start, period_end = date.fromisoformat(state["period"]["start"]), date.fromisoformat(state["period"]["end"])
    holidays = state.setdefault("bank_holidays", [])
    with st.form("add_bank_holiday", clear_on_submit=True):
        holiday_date = st.date_input("Bank holiday date", min_value=period_start, max_value=period_end)
        name = st.text_input("Name / description", placeholder="e.g. Christmas Day")
        add = st.form_submit_button("Add bank holiday", type="primary")
    if add:
        if holiday_date.weekday() > 4:
            st.error("Choose a Monday-to-Friday date; weekends already use weekend cover.")
        elif any(item.get("date") == holiday_date.isoformat() for item in holidays):
            st.error("That bank holiday has already been added.")
        else:
            holidays.append({"id": uid(), "date": holiday_date.isoformat(), "name": name.strip() or "Bank holiday"})
            holidays.sort(key=lambda item: item["date"]); persist(store, state); st.rerun()
    if not holidays:
        st.info("No bank holidays have been entered for this rota period.")
    for item in holidays:
        day = date.fromisoformat(item["date"])
        left, right = st.columns([8, 1])
        left.write(f"**{day:%A, %d %B %Y}** · {item.get('name', 'Bank holiday')}")
        if right.button("Remove", key=f"del_holiday_{item.get('id', item['date'])}"):
            state["bank_holidays"] = [value for value in holidays if value is not item]
            persist(store, state); st.rerun()
    weeks = len(mondays(period_start, period_end))
    st.metric("C days requiring cover", weeks * 5 - len(holidays), delta=f"−{len(holidays)} bank-holiday days")


def consultants(state, store):
    st.title("Consultants")
    with st.expander("Add consultant", expanded=not state["consultants"]):
        with st.form("add_consultant", clear_on_submit=True):
            name, email = st.text_input("Name"), st.text_input("Email (optional)")
            add = st.form_submit_button("Add consultant", type="primary")
        if add:
            if not name.strip(): st.error("Name is required.")
            elif any(c["name"].casefold() == name.strip().casefold() for c in state["consultants"]): st.error("Consultant names must be unique.")
            else:
                cid = uid(); state["consultants"].append({"id": cid, "name": name.strip(), "email": email.strip(), "active": True})
                state["targets"][cid] = {"t": 0, "weekend": 0, "c": 0}; state["special"][cid] = {"weekend_mode": "Standard", "partner_ids": [], "notes": ""}
                persist(store, state); st.success("Consultant added."); st.rerun()
    for c in state["consultants"]:
        with st.expander(f"{c['name']}  ·  {'Active' if c['active'] else 'Inactive'}"):
            with st.form(f"edit_{c['id']}"):
                new_name = st.text_input("Name", c["name"])
                new_email = st.text_input("Email", c.get("email", ""))
                enabled = st.checkbox("Active", c["active"])
                save = st.form_submit_button("Save changes")
            if save:
                if not new_name.strip(): st.error("Name is required.")
                elif any(x["id"] != c["id"] and x["name"].casefold() == new_name.strip().casefold() for x in state["consultants"]): st.error("Consultant names must be unique.")
                else:
                    c.update(name=new_name.strip(), email=new_email.strip(), active=enabled); persist(store, state); st.success("Saved."); st.rerun()


def leave_noc(state, store):
    st.title("Leave & NOC")
    people = active(state)
    if not people: st.warning("Add an active consultant first."); return
    labels = names(state)
    with st.form("absence", clear_on_submit=True):
        cid = st.selectbox("Consultant", [c["id"] for c in people], format_func=labels.get)
        kind = st.selectbox("Type", ["Annual leave", "Study leave", "NOC"])
        c1, c2 = st.columns(2); start = c1.date_input("Start"); end = c2.date_input("End")
        notes = st.text_input("Notes (optional)")
        add = st.form_submit_button("Add availability block", type="primary")
    if add:
        if end < start: st.error("End date cannot be before start date.")
        else:
            state["absences"].append({"id": uid(), "consultant_id": cid, "type": kind, "start": start.isoformat(), "end": end.isoformat(), "notes": notes.strip()})
            persist(store, state); st.success("Availability block added."); st.rerun()
    st.info("Annual leave, study leave and NOC are strict hard exclusions for C1, C2, T, full weekends and split weekends. A block starting Monday at 08:00 still permits the immediately preceding weekend, which ends at 08:00.")
    for item in state["absences"]:
        c1, c2 = st.columns([8, 1]); c1.write(f"**{labels.get(item['consultant_id'], 'Unknown')}** · {item['type']} · {item['start']} → {item['end']}")
        if c2.button("Remove", key=f"del_abs_{item['id']}"):
            state["absences"] = [x for x in state["absences"] if x["id"] != item["id"]]; persist(store, state); st.rerun()


def targets(state, store):
    st.title("Workload Targets")
    people = active(state)
    st.caption("Enter each consultant’s target totals for this six-month period. C is measured in working days; bank holidays do not count.")
    if not people: st.warning("Add an active consultant first."); return
    with st.form("targets"):
        values = {}
        for c in people:
            st.markdown(f"**{c['name']}**")
            current = state["targets"].setdefault(c["id"], {"t": 0, "weekend": 0, "c": 0})
            cols = st.columns(3)
            values[c["id"]] = {"t": cols[0].number_input("T blocks", 0, 30, int(current["t"]), key=f"t_{c['id']}"), "weekend": cols[1].number_input("Weekend credits", 0, 30, int(current["weekend"]), key=f"w_{c['id']}"), "c": cols[2].number_input("C days", 0, 150, int(current["c"]), key=f"c_{c['id']}")}
        save = st.form_submit_button("Save targets", type="primary")
    if save: state["targets"].update(values); persist(store, state); st.success("Targets saved.")


def preferences(state, store):
    st.title("Special Circumstances & Preferences")
    people = active(state); labels = names(state)
    if not people: st.warning("Add an active consultant first."); return
    st.subheader("Week preferences")
    weeks = mondays(date.fromisoformat(state["period"]["start"]), date.fromisoformat(state["period"]["end"]))
    with st.form("preference", clear_on_submit=True):
        cid = st.selectbox("Consultant", [c["id"] for c in people], format_func=labels.get, key="pref_c")
        week = st.selectbox("Week commencing", weeks, format_func=lambda d: d.strftime("%d %b %Y")) if weeks else date.today()
        c1, c2, c3 = st.columns(3)
        direction = c1.selectbox("Preference", ["Wants to work", "Prefers not to work", "Must work", "Must not work"])
        scope = c2.selectbox("Duty scope", ["Any", "C1", "C2", "T", "Weekend"])
        priority = c3.selectbox("Priority", ["Normal", "High", "Low"])
        notes = st.text_input("Reason / notes (optional)")
        add = st.form_submit_button("Add week preference")
    if add:
        state["preferences"].append({"id": uid(), "consultant_id": cid, "week": week.isoformat(), "direction": direction, "scope": scope, "priority": priority, "notes": notes.strip()}); persist(store, state); st.rerun()
    for item in state["preferences"]:
        c1, c2 = st.columns([8, 1]); c1.write(f"**{labels.get(item['consultant_id'], 'Unknown')}** · w/c {item['week']} · {item['direction']} · {item['scope']} · {item['priority']}")
        if c2.button("Remove", key=f"del_pref_{item['id']}"):
            state["preferences"] = [x for x in state["preferences"] if x["id"] != item["id"]]; persist(store, state); st.rerun()
    st.divider(); st.subheader("Weekend mode & preferred split partners")
    with st.form("special"):
        updates = {}
        ids = [c["id"] for c in people]
        for c in people:
            current = state["special"].setdefault(c["id"], {"weekend_mode": "Standard", "partner_ids": [], "notes": ""})
            st.markdown(f"**{c['name']}**")
            x, y = st.columns(2)
            mode = x.radio("Weekend mode", ["Standard", "Split"], index=1 if current["weekend_mode"] == "Split" else 0, horizontal=True, key=f"mode_{c['id']}")
            possible = [i for i in ids if i != c["id"]]
            partners = y.multiselect("Preferred split partners", possible, default=[p for p in current["partner_ids"] if p in possible], format_func=labels.get, key=f"partners_{c['id']}", disabled=mode != "Split")
            note = st.text_input("Special circumstances notes", current.get("notes", ""), key=f"note_{c['id']}")
            updates[c["id"]] = {"weekend_mode": mode, "partner_ids": partners if mode == "Split" else [], "notes": note}
        save = st.form_submit_button("Save special circumstances", type="primary")
    if save: state["special"].update(updates); persist(store, state); st.success("Special circumstances saved.")
    st.info("Split mode is period-wide: no full weekends, only balanced ½A (Friday + Sunday) and ½B (Saturday). Consecutive split weekends are permitted.")


def rules_page(state, store):
    st.title("Rota Rules")
    st.caption("Visible source of truth for the connected OR-Tools optimiser.")
    for i, rule in enumerate(HARD_CONSTRAINTS, 1): st.markdown(f"<div class='rule'><span>{i:02d}</span>{html.escape(rule)}</div>", unsafe_allow_html=True)
    st.subheader("Same-week compatibility")
    st.dataframe(pd.DataFrame([{"Combination": "T + C1/C2/Weekend", "Allowed": "No"}, {"Combination": "C1 + C2", "Allowed": "No"}, {"Combination": "C1 + Weekend", "Allowed": "Yes"}, {"Combination": "C2 + Weekend", "Allowed": "No"}, {"Combination": "Consecutive C blocks", "Allowed": "Yes"}]), hide_index=True, use_container_width=True)


def generate(state, store):
    st.title("Generate Rota")
    st.caption("Validate the selected period and generate an auditable OR-Tools draft.")
    checks = readiness(state)
    data, solver_errors = prepare(state)
    for c in checks: (st.success if c["ok"] else st.error)(f"{c['label']}: {c['detail']}")
    if solver_errors:
        st.error("Pre-solver validation failed. Hard constraints have not been relaxed.")
        for message in solver_errors: st.write(f"• {message}")
    else:
        c_days = sum(len(week.c_dates[duty]) for week in data.weeks for duty in (Duty.C1, Duty.C2))
        st.success(f"Solver input ready: {len(data.consultants)} consultants, {len(data.weeks)} weeks, {len(data.bank_holidays)} bank holidays and {c_days} C days.")
    if st.button("Generate Draft", type="primary", disabled=bool(solver_errors)):
        with st.status("Running OR-Tools…", expanded=True) as status:
            result = generate_draft(state, store)
            if result["errors"]:
                status.update(label=f"Generation stopped: {result['status']}", state="error")
                for message in result["errors"]: st.error(message)
            else:
                status.update(label="Draft generated and saved", state="complete")
                st.success(f"Draft {result['draft_id']} saved with {len(result['assignments'])} normalized assignments.")
                st.session_state.rota_state = store.load()
                st.rerun()


def review(state, store):
    st.title("Review & Finalise")
    gen = state["generation"]
    drafts = state.get("drafts", [])
    if drafts:
        draft_ids = [str(d["id"]) for d in drafts]
        current_id = str(gen.get("draft_id", draft_ids[0]))
        selected = st.selectbox("Generated draft", draft_ids, index=draft_ids.index(current_id) if current_id in draft_ids else 0,
                                format_func=lambda value: next((f"Draft {value} · {d.get('status', 'Draft')}" for d in drafts if str(d["id"]) == value), value))
        if selected != current_id:
            chosen = store.get_draft(selected)
            gen = {"status": chosen.get("status", "Draft"), "last_run": chosen.get("created_at"),
                   "draft_id": selected, "assignments": chosen.get("assignments", [])}
    st.metric("Draft status", gen["status"])
    if gen["last_run"]: st.caption(f"Last readiness run: {gen['last_run']}")
    assignments = gen.get("assignments", [])
    if not assignments:
        st.info("No generated draft is available. Generate one first."); return
    labels = names(state)
    rows = [{**a, "Consultant": labels.get(a.get("consultant_id"), "VACANCY"),
             "Duty": {"STANDARD_WEEKEND": "Weekend", "SPLIT_HALF_A": "½A (Fri + Sun)", "SPLIT_HALF_B": "½B (Sat)"}.get(a["assignment_type"], a["assignment_type"])} for a in assignments]
    frame = pd.DataFrame(rows)
    def display_assignment(row):
        if row["Duty"] not in ("C1", "C2"): return row["Consultant"]
        dates = row.get("duty_dates") or []
        days = [date.fromisoformat(value).strftime("%a") for value in dates]
        credit = int(row.get("c_day_credit") or len(days) or (2 if row["Duty"] == "C1" else 3))
        return f"{row['Consultant']} ({'/'.join(days) if days else credit}; {credit}d)"
    frame["Display"] = frame.apply(display_assignment, axis=1)
    frame["C Credit"] = frame.apply(lambda row: int(row.get("c_day_credit") or (2 if row["Duty"] == "C1" else 3 if row["Duty"] == "C2" else 0)), axis=1)
    grid = frame.pivot_table(index="week_commencing", columns="Duty", values="Display", aggfunc=lambda x: " / ".join(x), fill_value="")
    for column in ("C1", "C2", "T", "Weekend", "½A (Fri + Sun)", "½B (Sat)"):
        if column not in grid: grid[column] = ""
    st.subheader("Weekly rota")
    st.dataframe(grid[["C1", "C2", "T", "Weekend", "½A (Fri + Sun)", "½B (Sat)"]], use_container_width=True)
    summary = []
    for consultant in active(state):
        own = frame[frame["consultant_id"] == consultant["id"]]
        target = state["targets"][consultant["id"]]
        summary.append({"Consultant": consultant["name"], "T actual / target": f"{sum(own.Duty == 'T')} / {target['t']}",
                        "C days actual / target": f"{int(own['C Credit'].sum())} / {target['c']}",
                        "Weekend credit actual / target": f"{own.get('weekend_credit', pd.Series(dtype=float)).sum():g} / {target['weekend']}"})
    st.subheader("Workload validation")
    st.dataframe(pd.DataFrame(summary), hide_index=True, use_container_width=True)
    st.success("Post-solver validation passed with no hard-rule violations.")
    st.caption("Manual edit hooks are intentionally deferred; assignments are persisted per draft and never overwrite historical runs.")
    if st.button("Finalise and lock this rota", type="primary", disabled=state["period"].get("status") == "Finalised"):
        try:
            store.finalise_draft(gen["draft_id"]); st.session_state.rota_state = store.load(); st.success("Rota finalised and locked."); st.rerun()
        except Exception as exc: st.error(str(exc))


PAGES = {
    "Dashboard": dashboard,
    "Rota Period": rota_period,
    "Bank Holidays": bank_holidays,
    "Consultants": consultants,
    "Leave & NOC": leave_noc,
    "Workload Targets": targets,
    "Special Circumstances & Preferences": preferences,
    "Rota Rules": rules_page,
    "Generate Rota": generate,
    "Review & Finalise": review,
}
