from __future__ import annotations

import html
from datetime import date, datetime

import pandas as pd
import streamlit as st

from .models import uid
from .rules import HARD_CONSTRAINTS, mondays, readiness


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
    st.info("The optimiser is not connected yet. Complete setup, then use Generate Rota to inspect the solver-readiness payload.")


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
    st.info("Annual leave, study leave and NOC block overlapping C1, C2, T and Weekend. A block starting on Monday still permits the immediately preceding weekend.")
    for item in state["absences"]:
        c1, c2 = st.columns([8, 1]); c1.write(f"**{labels.get(item['consultant_id'], 'Unknown')}** · {item['type']} · {item['start']} → {item['end']}")
        if c2.button("Remove", key=f"del_abs_{item['id']}"):
            state["absences"] = [x for x in state["absences"] if x["id"] != item["id"]]; persist(store, state); st.rerun()


def targets(state, store):
    st.title("Workload Targets")
    people = active(state)
    st.caption("Enter each consultant’s target totals for this six-month period. C is the combined C1/C2 target at this stage.")
    if not people: st.warning("Add an active consultant first."); return
    with st.form("targets"):
        values = {}
        for c in people:
            st.markdown(f"**{c['name']}**")
            current = state["targets"].setdefault(c["id"], {"t": 0, "weekend": 0, "c": 0})
            cols = st.columns(3)
            values[c["id"]] = {"t": cols[0].number_input("T blocks", 0, 30, int(current["t"]), key=f"t_{c['id']}"), "weekend": cols[1].number_input("Weekend credits", 0, 30, int(current["weekend"]), key=f"w_{c['id']}"), "c": cols[2].number_input("C blocks", 0, 60, int(current["c"]), key=f"c_{c['id']}")}
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
    st.caption("Visible source of truth for the future optimiser. These constraints are fixed in this scaffold.")
    for i, rule in enumerate(HARD_CONSTRAINTS, 1): st.markdown(f"<div class='rule'><span>{i:02d}</span>{html.escape(rule)}</div>", unsafe_allow_html=True)
    st.subheader("Same-week compatibility")
    st.dataframe(pd.DataFrame([{"Combination": "T + C1/C2/Weekend", "Allowed": "No"}, {"Combination": "C1 + C2", "Allowed": "No"}, {"Combination": "C1 + Weekend", "Allowed": "Yes"}, {"Combination": "C2 + Weekend", "Allowed": "No"}, {"Combination": "Consecutive C blocks", "Allowed": "Yes"}]), hide_index=True, use_container_width=True)


def generate(state, store):
    st.title("Generate Rota")
    st.caption("Pre-flight validation for the future OR-Tools solver.")
    checks = readiness(state)
    for c in checks: (st.success if c["ok"] else st.error)(f"{c['label']}: {c['detail']}")
    ready = all(c["ok"] for c in checks)
    if st.button("Prepare solver draft", type="primary", disabled=not ready):
        state["generation"].update(last_run=datetime.now().isoformat(timespec="seconds"), status="Configuration validated — solver not connected", assignments=[])
        persist(store, state); st.success("Configuration validated. The data contract is ready for an OR-Tools adapter; no rota assignments were generated.")
    with st.expander("What the solver adapter will receive"):
        st.json({"period": state["period"], "active_consultants": active(state), "targets": state["targets"], "availability": state["absences"], "preferences": state["preferences"], "special_circumstances": state["special"], "hard_constraints": HARD_CONSTRAINTS}, expanded=False)


def review(state, store):
    st.title("Review & Finalise")
    gen = state["generation"]
    st.metric("Draft status", gen["status"])
    if gen["last_run"]: st.caption(f"Last readiness run: {gen['last_run']}")
    if not gen["assignments"]:
        st.info("No assignments yet. This page is ready for the future solver output, conflict review, manual overrides and finalisation workflow.")
    st.button("Finalise rota", disabled=True, help="Enabled after solver integration and a valid generated draft.")


PAGES = {
    "Dashboard": dashboard,
    "Rota Period": rota_period,
    "Consultants": consultants,
    "Leave & NOC": leave_noc,
    "Workload Targets": targets,
    "Special Circumstances & Preferences": preferences,
    "Rota Rules": rules_page,
    "Generate Rota": generate,
    "Review & Finalise": review,
}

