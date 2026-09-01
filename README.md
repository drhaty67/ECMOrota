# Consultant Rota Drafting

A working Streamlit/Supabase/OR-Tools application for configuring, generating, reviewing and finalising a six-month consultant rota. A service layer separates UI, persistence and the typed solver contract.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Without Supabase credentials, the app creates `data/rota_state.json` on first use. Use **Reset demo data** in the sidebar to restore the starter configuration.

## Connect Supabase

1. Create a Supabase project.
2. Open **SQL Editor**, run `supabase/schema.sql`, then `supabase/integration_v2.sql`, then `supabase/bank_holidays_v3.sql`.
3. In Supabase **Project settings → API**, copy the project URL and server-side secret/service-role key.
4. In Streamlit Community Cloud, open **App settings → Secrets** and add:

```toml
[supabase]
url = "https://YOUR_PROJECT_REF.supabase.co"
service_role_key = "YOUR_SERVICE_ROLE_KEY"
anon_key = "YOUR_PUBLISHABLE_OR_ANON_KEY"
workspace_id = "default"

[auth]
enabled = true
```

5. Configure the first administrator as described below.
6. Save the secrets and reboot the Streamlit app. The app should show an administrator sign-in page; after login, the sidebar should show **Supabase**.

## Administrator authentication

1. In Supabase, open **Authentication → Users → Add user** and create the administrator with an email and password. Enable/confirm the user if prompted.
2. Open **SQL Editor** and run the following, replacing the email with the exact administrator email:

```sql
insert into public.admin_users (user_id, email)
select id, email
from auth.users
where lower(email) = lower('admin@example.com')
on conflict (user_id) do update set email = excluded.email, active = true;
```

3. Sign in to the Streamlit app with that account.

To revoke access without deleting the Supabase Auth account:

```sql
update public.admin_users
set active = false
where lower(email) = lower('admin@example.com');
```

The service-role database connection is created only after the user has successfully authenticated and their active administrator record has been verified through Row Level Security.

## Deployment access control

Use two layers of protection:

1. Keep the in-app Supabase administrator login enabled.
2. In Streamlit Community Cloud, open **App settings → Sharing**, select **Only specific people can view this app**, and invite only approved administrators. A private GitHub repository also causes the deployed app to be private by default.

Do not enter real staff information until both layers are configured.

For local Supabase testing, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in the real values. Never commit that file or expose the service-role key in source code.

### Security boundary

The SQL migration enables Row Level Security and grants the two application functions only to Supabase's `service_role`. The service key remains in Streamlit's server-side secrets and is never sent to the browser. The lower-privilege anon/publishable key is used only for login and administrator verification.

### Existing local data

The first connection creates clean demo data in Supabase. To carry over an existing local setup, configure Supabase locally and run the app once, then re-enter or import the current data. An automated migration command can be added once the production project and desired workspace identifier are known.

## Integrated flow

- Configure the period, consultants, targets, absences/NOC, preferences and split settings.
- Enter weekday bank holidays. These retain T cover, remove that day's C cover, and shorten the affected C1/C2 block for target accounting and availability checks.
- Pre-validate, run CP-SAT without relaxing hard constraints, record run metadata, and persist normalized draft assignments.
- Treat annual leave, study leave and NOC as strict hard exclusions across C1, C2, T, full weekends and both split components. Independent post-solver validation fails closed, so a conflicting result is never saved as a draft.
- Review weekly C1/C2/T/full and split weekend coverage plus workload-versus-target totals.
- Finalise and lock a valid draft while preserving earlier runs and drafts.
- Use local JSON for development or `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and optional `SUPABASE_WORKSPACE_ID` in production.

## Tests

```bash
pytest -q
```

The suite includes an end-to-end dry-run for 26 October 2026 through 2 May 2027.
It also includes a 26-week, five-bank-holiday run that reconciles 130 potential weekdays to exactly 125 allocated C days with no vacancy blocks.

## Schema migration note

The inherited schema models one selected period per workspace, and its original `save_rota_state` function deletes run/assignment history. `integration_v2.sql` adds normalized append-only drafts and finalisation. On an existing database, remove those two legacy history-deleting statements before production use. Multi-period browsing remains a known inherited UI/schema limitation.
