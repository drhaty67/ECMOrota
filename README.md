# Consultant Rota Drafting

A working Streamlit front-end scaffold for configuring a six-month consultant rota. Data is stored locally in `data/rota_state.json`; Supabase and OR-Tools are deliberately represented by adapter/service boundaries so they can be added later.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app creates `data/rota_state.json` on first use. Use **Reset demo data** in the sidebar to restore the starter configuration.

## Current scope

- Nine admin pages covering setup, people, availability, targets, preferences, rules, generation readiness and review.
- Consultant add/edit/deactivate workflow.
- Local JSON persistence plus Streamlit session state.
- Validation of period dates, active consultants, workload targets, date ranges, split-mode partner eligibility and split-weekend arithmetic.
- Solver readiness report and a deliberately non-solving draft placeholder.

The actual optimiser, authentication, Supabase persistence, audit history and production export are future integration points.

